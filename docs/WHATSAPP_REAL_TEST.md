# Prueba real de WhatsApp Business Cloud API

## Requisitos

1. **Variables de entorno** (`.env` al raíz del proyecto):

```ini
WHATSAPP_ENABLED=true
WHATSAPP_ACCESS_TOKEN=<token_de_acceso_permanente>
WHATSAPP_PHONE_NUMBER_ID=<id_del_número_de_teléfono>
WHATSAPP_BUSINESS_ACCOUNT_ID=<id_de_la_cuenta_comercial>
WHATSAPP_API_VERSION=v22.0
WHATSAPP_VERIFY_TOKEN=<token_de_verificación>
WHATSAPP_APP_SECRET=<app_secret>
WHATSAPP_WEBHOOK_PORT=8767
WHATSAPP_VERIFY_SIGNATURE=true
WHATSAPP_HTTP_TIMEOUT_SECONDS=30
WHATSAPP_OUTBOX_POLL_INTERVAL_SECONDS=5
WHATSAPP_OUTBOX_BATCH_SIZE=10
WHATSAPP_OUTBOX_MAX_ATTEMPTS=5
WHATSAPP_OUTBOX_RETRY_BASE_SECONDS=10
WHATSAPP_OUTBOX_RETRY_MAX_SECONDS=600
WHATSAPP_OUTBOX_PROCESSING_TIMEOUT_SECONDS=300
```

## Scripts

### 1. `scripts/test_whatsapp_send.py` — Envío manual

| Comando | Efecto |
|---|---|
| `--check` | Valida configuración sin enviar |
| `--dry-run --to "521234567890" --text "Hola"` | Simula envío; no conecta |
| `--send-real --confirm SEND --to "521234567890" --text "Hola"` | Envía mensaje real |
| `----preview-url` | Habilita preview de enlaces |
| `--send-via-outbox --confirm SEND --to "521234567890" --text "Hola"` | Encola y procesa por outbox |
| `--output-report report.json` | Guarda resultado sanitizado |

### 2. `scripts/check_whatsapp_webhook.py` — Verificación de webhook

| Comando | Efecto |
|---|---|
| `--check-local` | Inicia servidor efímero, prueba GET y POST, verifica persistencia |
| `--status` | Muestra estadísticas de la base de datos |

### 3. `scripts/run_whatsapp_webhook.py` — Servidor persistente

```bash
python scripts/run_whatsapp_webhook.py
```

## Seguridad

- `--send-real` requiere `--confirm SEND` explícito. Sin confirmación no se abre conexión.
- `--dry-run` no modifica SQLite ni llama a Meta.
- `--check` nunca muestra token, app secret, verify token ni Authorization.
- `--output-report` guarda solo campos sanitizados (últimos 4 dígitos, sin texto completo, sin token).
- Los tokens se cargan desde `.env` o variables de entorno reales; nunca se pasan por CLI.

## Configuración del webhook en Meta

1. En **Meta for Developers > WhatsApp > Configuration**, usar:
   - **Callback URL**: `https://<tu-dominio>/api/whatsapp/webhook`
   - **Verify Token**: el valor de `WHATSAPP_VERIFY_TOKEN`
2. Suscribirse a los campos: `messages`, `message_deliveries`, `message_reads`
3. El servidor valida HMAC SHA‑256 con `X-Hub-Signature-256` y `WHATSAPP_APP_SECRET`

## Prueba end-to-end local

Si no tenés un dominio público, usá **ngrok**:

```bash
ngrok http 8767
```

Luego configurá la **Callback URL** en Meta como `https://<ngrok-subdomain>.ngrok.io/api/whatsapp/webhook`.

Para verificar que el webhook funciona:

```bash
python scripts/check_whatsapp_webhook.py --status
```
