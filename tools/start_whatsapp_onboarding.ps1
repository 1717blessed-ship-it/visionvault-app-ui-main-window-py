<#
.SYNOPSIS
    Inicia el servidor de onboarding de WhatsApp + tunel Cloudflare.
.DESCRIPTION
    1. Verifica que el puerto 8766 este libre.
    2. Inicia el servidor de onboarding como PowerShell job.
    3. Espera a que responda HTTP 200, detectando fallo prematuro.
    4. Inicia un tunel cloudflared hacia el puerto local.
    5. Captura la URL publica de Cloudflare.
    6. Guarda los valores en onboarding_tunnel_info.txt.
    7. Abre la URL publica en el navegador.
    8. Mantiene ambos procesos activos y los detiene con Ctrl+C.
.NOTES
    No modifica ni detiene el webhook del puerto 8767.
    Usa Start-Job para el servidor Python (mas confiable que Start-Process dentro de jobs).
#>

#Requires -Version 5.1

$ErrorActionPreference = "Continue"

# ── Rutas ──────────────────────────────────────────────────────────────
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$OnboardingPort = 8766
$WebhookPort = 8767
$LocalUrl = "http://127.0.0.1:$OnboardingPort"
$InfoFile = Join-Path $ProjectRoot "onboarding_tunnel_info.txt"
$LogsDir = Join-Path $ProjectRoot "logs"

if (-not (Test-Path $LogsDir)) { New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null }

function Write-Step($msg) { Write-Host ">>> $msg" -ForegroundColor Cyan }
function Write-OK($msg) { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [!] $msg" -ForegroundColor Yellow }
function Write-Info($msg) { Write-Host "  $msg" }

function Sanitize-Text($text) {
    $text = $text -replace '(WHATSAPP_APP_SECRET[= ])[^\s\r\n"]+', '$1***'
    $text = $text -replace '(WHATSAPP_ACCESS_TOKEN[= ])[^\s\r\n"]+', '$1***'
    $text = $text -replace '(client_secret[= ])[^\s\r\n&"]+', '$1***'
    $text = $text -replace '(access_token[= ])[^\s\r\n&"]+', '$1***'
    return $text
}

function Remove-JobSafe($name) {
    $j = Get-Job -Name $name -ErrorAction SilentlyContinue
    if ($j) { Stop-Job $j -ErrorAction SilentlyContinue; Remove-Job $j -ErrorAction SilentlyContinue }
}

function Get-JobOutput($name) {
    $j = Get-Job -Name $name -ErrorAction SilentlyContinue
    if ($j) { return Receive-Job $j -ErrorAction SilentlyContinue }
    return @()
}

# ── 1. Verificar prerequisitos ───────────────────────────────────────
Write-Step "Verificando prerequisitos..."

$pythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonPath) { Write-Host "ERROR: python no encontrado" -ForegroundColor Red; exit 1 }
Write-OK "Python: $pythonPath"

$cfPath = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cfPath) {
    Write-Host "ERROR: cloudflared no encontrado." -ForegroundColor Red
    Write-Host "  Instalalo desde: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/" -ForegroundColor Yellow
    exit 1
}
Write-OK "cloudflared: $cfPath"

# ── 2. Webhook 8767 ─────────────────────────────────────────────────
$webhookListen = Get-NetTCPConnection -LocalPort $WebhookPort -State Listen -ErrorAction SilentlyContinue
if ($webhookListen) {
    Write-OK "Webhook en puerto $WebhookPort activo (PID $($webhookListen.OwningProcess))"
} else {
    Write-Warn "No se detecto webhook escuchando en puerto $WebhookPort"
}

# ── 3. Puerto 8766 libre ─────────────────────────────────────────────
Write-Step "Verificando puerto $OnboardingPort..."
$existingListen = Get-NetTCPConnection -LocalPort $OnboardingPort -State Listen -ErrorAction SilentlyContinue
if ($existingListen) {
    Write-Warn "Puerto $OnboardingPort ocupado por PID $($existingListen.OwningProcess). Liberando..."
    Stop-Process -Id $existingListen.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    $still = Get-NetTCPConnection -LocalPort $OnboardingPort -State Listen -ErrorAction SilentlyContinue
    if ($still) { Write-Host "ERROR: No se pudo liberar el puerto $OnboardingPort" -ForegroundColor Red; exit 1 }
}
Write-OK "Puerto $OnboardingPort libre"

# ── 4. Iniciar servidor de onboarding ────────────────────────────────
Write-Step "Iniciando servidor de onboarding..."

Remove-JobSafe "onboarding-server"

$serverJob = Start-Job -Name "onboarding-server" -ScriptBlock {
    param($root, $port)
    Set-Location $root
    $env:PYTHONUNBUFFERED = "1"
    python -m app.whatsapp.onboarding_server --port $port 2>&1
} -ArgumentList $ProjectRoot, $OnboardingPort

Write-Info "  Job       : onboarding-server"
Write-Info "  Directorio: $ProjectRoot"

# ── 5. Esperar a que responda HTTP 200 ───────────────────────────────
$maxWait = 30
$serverReady = $false

for ($i = 1; $i -le $maxWait; $i++) {
    Start-Sleep -Seconds 1

    $jobState = (Get-Job -Name "onboarding-server" -ErrorAction SilentlyContinue).State
    if ($jobState -eq "Failed") {
        $err = Get-JobOutput "onboarding-server"
        Write-Host "ERROR: El servidor fallo al iniciar" -ForegroundColor Red
        Write-Host "=== Diagnostico (sanitizado) ===" -ForegroundColor Yellow
        $sanitized = $err | ForEach-Object { Sanitize-Text $_ }
        $sanitized | ForEach-Object { Write-Host "  $_" }
        Write-Host "=== Fin diagnostico ===" -ForegroundColor Yellow
        exit 1
    }
    if ($jobState -eq "Completed") {
        $out = Get-JobOutput "onboarding-server"
        Write-Host "ERROR: El servidor termino inesperadamente" -ForegroundColor Red
        $sanitized = $out | ForEach-Object { Sanitize-Text $_ }
        $sanitized | ForEach-Object { Write-Host "  $_" }
        exit 1
    }

    try {
        $resp = Invoke-WebRequest -Uri "$LocalUrl/" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { $serverReady = $true; break }
    } catch { }
}

if (-not $serverReady) {
    $jobState = (Get-Job -Name "onboarding-server" -ErrorAction SilentlyContinue).State
    Write-Host "ERROR: El servidor no respondio luego de ${maxWait}s (job state: $jobState)" -ForegroundColor Red
    Remove-JobSafe "onboarding-server"
    exit 1
}

Write-OK "Servidor de onboarding respondiendo en $LocalUrl ($(Get-JobOutput 'onboarding-server' | Select-String 'started' | ForEach-Object { $_ }))"

# ── 6. Iniciar tunel Cloudflare ──────────────────────────────────────
Write-Step "Iniciando tunel Cloudflare..."

Remove-JobSafe "cloudflare-tunnel"
$tunnelJob = Start-Job -Name "cloudflare-tunnel" -ScriptBlock {
    param($url)
    cloudflared tunnel --url $url 2>&1
} -ArgumentList $LocalUrl

$tunnelUrl = $null
for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 1
    $output = Receive-Job -Job $tunnelJob -ErrorAction SilentlyContinue
    foreach ($line in $output) {
        if ($line -match 'https://([a-z0-9-]+)\.trycloudflare\.com') { $tunnelUrl = $matches[0]; break }
    }
    if ($tunnelUrl) { break }
}

if (-not $tunnelUrl) {
    Write-Host "ERROR: No se pudo capturar la URL del tunel Cloudflare" -ForegroundColor Red
    Remove-JobSafe "cloudflare-tunnel"
    Remove-JobSafe "onboarding-server"
    exit 1
}
Write-OK "Tunel Cloudflare establecido"

$tunnelDomain = $tunnelUrl -replace '^https://', ''
$oAuthUri = "$tunnelUrl/"

Write-Host "  URL publica : $tunnelUrl" -ForegroundColor Green
Write-Host "  Dominio     : $tunnelDomain" -ForegroundColor Green
Write-Host "  URI OAuth   : $oAuthUri" -ForegroundColor Green

# ── 7. Guardar informacion ───────────────────────────────────────────
@"
APP_DOMAIN=$tunnelDomain
ONBOARDING_PUBLIC_URL=$tunnelUrl/
VALID_OAUTH_REDIRECT_URI=$tunnelUrl/

# Generado: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
# Proyecto: $ProjectRoot
# Puerto local: $OnboardingPort
# No compartir esta URL publicamente.
"@ | Out-File -FilePath $InfoFile -Encoding utf8
Write-OK "Informacion guardada en: $InfoFile"

# ── 8. Resumen ───────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  ONBOARDING WHATSAPP - TUNEL HTTPS ACTIVO" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  URL local:       $LocalUrl/"
Write-Host "  URL publica:     $tunnelUrl/" -ForegroundColor Yellow
Write-Host "  Dominio:         $tunnelDomain" -ForegroundColor Yellow
Write-Host "  URI OAuth:       $oAuthUri" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Archivo info:    $InfoFile"
Write-Host ""
Write-Host "  --- Configuracion necesaria en Meta Developers ---" -ForegroundColor Cyan
Write-Host "  1. Configuracion de la app > Basica" -ForegroundColor Cyan
Write-Host "     Dominios de la app: $tunnelDomain" -ForegroundColor White
Write-Host "  2. Inicio de sesion con Facebook para empresas > Configurar" -ForegroundColor Cyan
Write-Host "     - Inicio de sesion del cliente OAuth:  Si" -ForegroundColor Cyan
Write-Host "     - Inicio de sesion OAuth web:          Si" -ForegroundColor Cyan
Write-Host "     - Aplicar HTTPS:                       Si" -ForegroundColor Cyan
Write-Host "     - Inicio de sesion con SDK JavaScript: Si" -ForegroundColor Cyan
Write-Host "     - Dominios permitidos para SDK JS:     $tunnelDomain" -ForegroundColor White
Write-Host "     - URI de redireccionamiento OAuth:     $oAuthUri" -ForegroundColor White
Write-Host ""
Write-Host "  Presiona Ctrl+C para detener todo." -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""

# ── 9. Abrir navegador ──────────────────────────────────────────────
try { Start-Process $tunnelUrl; Write-OK "Navegador abierto" } catch { Write-Warn "No se pudo abrir el navegador" }

# ── 10. Monitoreo ────────────────────────────────────────────────────
Write-Step "Monitoreando procesos. Presiona Ctrl+C para detener."

try {
    while ($true) {
        Start-Sleep -Seconds 3

        $srvState = (Get-Job -Name "onboarding-server" -ErrorAction SilentlyContinue).State
        if ($srvState -ne "Running") {
            Write-Warn "Servidor de onboarding caido (estado: $srvState)"
            $out = Get-JobOutput "onboarding-server"
            $sanitized = $out | ForEach-Object { Sanitize-Text $_ }
            $sanitized | ForEach-Object { Write-Host "  $_" }
            break
        }

        $tunState = (Get-Job -Name "cloudflare-tunnel" -ErrorAction SilentlyContinue).State
        if ($tunState -ne "Running") {
            Write-Warn "Tunel Cloudflare caido (estado: $tunState)"
            break
        }
    }
} finally {
    Write-Step "Deteniendo procesos..."
    Remove-JobSafe "onboarding-server"
    Remove-JobSafe "cloudflare-tunnel"

    # Forzar liberacion de puerto
    Start-Sleep -Seconds 1
    $remain = Get-NetTCPConnection -LocalPort $OnboardingPort -State Listen -ErrorAction SilentlyContinue
    if ($remain) { Stop-Process -Id $remain.OwningProcess -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2 }

    $f = Get-NetTCPConnection -LocalPort $OnboardingPort -State Listen -ErrorAction SilentlyContinue
    if (-not $f) { Write-OK "Puerto $OnboardingPort liberado" } else { Write-Warn "No se pudo liberar el puerto $OnboardingPort" }

    $w = Get-NetTCPConnection -LocalPort $WebhookPort -State Listen -ErrorAction SilentlyContinue
    if ($w) { Write-OK "Webhook en puerto $WebhookPort intacto" } else { Write-Warn "Webhook $WebhookPort no detectado" }

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  PROCESOS DETENIDOS" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Para reiniciar, ejecuta este script nuevamente." -ForegroundColor Yellow
    Write-Host "  Para configurar Meta, revisa: $InfoFile" -ForegroundColor Yellow
    Write-Host "  Y la guia completa en: docs/WHATSAPP_ONBOARDING_META_SETUP.md" -ForegroundColor Yellow
    Write-Host ""
}
