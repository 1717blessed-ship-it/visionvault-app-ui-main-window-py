<#
Genera el APK release de Doccione Mobile aun cuando Windows use un perfil
con espacios (por ejemplo: C:\Users\Win 10). Algunos paquetes de Flutter
no interpretan bien esas rutas, por lo que este script crea unidades
temporales sin espacios solo durante la compilacion.

Uso desde PowerShell:
  powershell -ExecutionPolicy Bypass -File .\tools\build_mobile_apk.ps1
#>

[CmdletBinding()]
param(
    [string]$FlutterRoot = (Join-Path $env:USERPROFILE 'Downloads\flutter')
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$mobileRoot = Join-Path $projectRoot 'mobile\doccione_mobile'
$flutterBat = Join-Path $FlutterRoot 'bin\flutter.bat'

if (-not (Test-Path $mobileRoot)) {
    throw "No se encontro la app movil: $mobileRoot"
}
if (-not (Test-Path $flutterBat)) {
    throw "No se encontro Flutter en: $flutterBat. Indica la ruta con -FlutterRoot."
}

# Un APK distribuible nunca debe compilarse con el checkout reducido que sólo
# contiene el manifiesto. Verificar el payload externo antes de limpiar/build.
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $pythonExe)) {
    $pythonExe = (Get-Command python -ErrorAction Stop).Source
}
& $pythonExe (Join-Path $projectRoot 'tools\mobile_sticker_bank.py') verify
if ($LASTEXITCODE -ne 0) {
    throw 'El banco móvil externo falta o no coincide con su lock; se canceló el build.'
}

function Set-TemporarySubstDrive([string]$drive, [string]$path) {
    # Las letras se reservan para este proceso de build y se reasignan para
    # que siempre apunten al proyecto y SDK actuales.
    & subst "$drive`:" /d 2>$null
    & subst "$drive`:" $path
    if (-not (Test-Path "$drive`:\")) {
        throw "No se pudo crear la unidad temporal $drive`:"
    }
}

try {
    Set-TemporarySubstDrive 'P' $projectRoot
    Set-TemporarySubstDrive 'G' $FlutterRoot

    Push-Location 'P:\mobile\doccione_mobile'
    try {
        & 'G:\bin\flutter.bat' clean
        & 'G:\bin\flutter.bat' pub get
        & 'G:\bin\flutter.bat' build apk --release --android-skip-build-dependency-validation
        if ($LASTEXITCODE -ne 0) { throw "Flutter termino con codigo $LASTEXITCODE" }
    }
    finally {
        Pop-Location
    }

    $apk = 'P:\mobile\doccione_mobile\build\app\outputs\flutter-apk\app-release.apk'
    if (-not (Test-Path $apk)) { throw 'Flutter finalizo pero no se encontro app-release.apk.' }
    Write-Host "`nAPK generado correctamente:" -ForegroundColor Green
    Write-Host $apk -ForegroundColor Green
}
finally {
    # No se eliminan P: ni G: porque aceleran futuras compilaciones y hacen
    # simples las rutas de instalacion. El script las actualiza al ejecutarse.
}
