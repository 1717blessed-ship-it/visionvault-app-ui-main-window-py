"""Servidor local de onboarding para Embedded Signup v4 (coexistencia).

Uso:
    python -m app.whatsapp.onboarding_server

Abre http://localhost:8766/ en el navegador.
Requiere WHATSAPP_APP_SECRET en .env (no compartir, solo local).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any

import argparse

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────

APP_ID = "1350164413306835"
CONFIG_ID = "1025463306928019"
DEFAULT_PORT = 8766

# Variables del .env que se actualizan tras el onboarding exitoso
ENV_TARGET_KEYS = {
    "WHATSAPP_WABA_ID",
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_BUSINESS_ID",
    "WHATSAPP_CONFIGURATION_ID",
}


# ── Helpers ───────────────────────────────────────────────────────────

def _mask(val: str, visible: int = 4) -> str:
    """Muestra solo los últimos N caracteres; reemplaza el resto con *."""
    if not val:
        return "(vacio)"
    if len(val) <= visible:
        return "*" * (len(val) - 1) + val[-1]
    return "*" * (len(val) - visible) + val[-visible:]


def _load_dotenv(path: str | Path | None = None) -> dict[str, str]:
    """Carga .env y devuelve dict clave->valor (solo primera ocurrencia)."""
    if path is None:
        path = Path(__file__).resolve().parents[2] / ".env"
    env_file = Path(path)
    result: dict[str, str] = {}
    if not env_file.exists():
        return result
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if value.startswith(('"', "'")) and value[0] == value[-1]:
            value = value[1:-1]
        if key not in result and key not in os.environ:
            result[key] = value
    return result


def _get_app_secret() -> str:
    """Lee WHATSAPP_APP_SECRET del entorno o .env. Sin exponerlo en logs."""
    secret = os.environ.get("WHATSAPP_APP_SECRET", "").strip()
    if secret:
        return secret
    env = _load_dotenv()
    secret = env.get("WHATSAPP_APP_SECRET", "").strip()
    if not secret:
        raise RuntimeError(
            "WHATSAPP_APP_SECRET no está configurado en .env. "
            "Copialo desde Meta App Dashboard > Configuración > Básico > App Secret."
        )
    return secret


def _exchange_code(code: str, app_secret: str) -> str:
    """Intercambia el code temporal por un access token (solo server-side).

    Documentación oficial:
    POST /v22.0/oauth/access_token
      ?client_id={app-id}&client_secret={app-secret}&code={code}
    """
    params = urllib.parse.urlencode({
        "client_id": APP_ID,
        "client_secret": app_secret,
        "code": code,
    })
    url = f"https://graph.facebook.com/v22.0/oauth/access_token?{params}"
    req = urllib.request.Request(url, method="POST")
    resp = urllib.request.urlopen(req, timeout=30)
    body = json.loads(resp.read().decode("utf-8"))
    token: str = body.get("access_token", "")
    if not token:
        raise RuntimeError(f"El intercambio del code no devolvió access_token: {body.get('error', body)}")
    logger.info("Code intercambiado exitosamente. Token obtenido: %s", _mask(token))
    return token


def _update_dotenv(updates: dict[str, str]) -> None:
    """Actualiza solo las variables indicadas en .env sin sobrescribir el resto."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        raise RuntimeError(f"No se encuentra .env en {env_path}")

    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    updated_keys: set[str] = set()

    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in ENV_TARGET_KEYS and key in updates:
                new_lines.append(f"{key}={updates[key]}\n".replace("\r\n", "\n").replace("\n", "\n"))
                updated_keys.add(key)
                continue
        new_lines.append(line)

    # Agregar variables que no existían en el archivo
    for key in ENV_TARGET_KEYS:
        if key in updates and key not in updated_keys:
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines.append("\n")
            new_lines.append(f"{key}={updates[key]}\n")

    env_path.write_text("".join(new_lines), encoding="utf-8")
    logger.info(".env actualizado: %s", ", ".join(updates.keys()))


def _subscribe_app(waba_id: str, token: str) -> dict[str, Any]:
    """Suscribe la aplicación a la WABA.

    POST /{waba_id}/subscribed_apps?access_token={token}
    """
    params = urllib.parse.urlencode({"access_token": token})
    url = f"https://graph.facebook.com/v22.0/{waba_id}/subscribed_apps?{params}"
    req = urllib.request.Request(url, method="POST")
    resp = urllib.request.urlopen(req, timeout=30)
    body = json.loads(resp.read().decode("utf-8"))
    logger.info("App suscrita a WABA %s: %s", waba_id, body)
    return body


def _check_webhook_fields(waba_id: str, token: str) -> list[dict[str, Any]]:
    """Obtiene los campos de webhook suscritos en la WABA.

    GET /{waba_id}/subscribed_apps?access_token={token}
    """
    params = urllib.parse.urlencode({"access_token": token})
    url = f"https://graph.facebook.com/v22.0/{waba_id}/subscribed_apps?{params}"
    req = urllib.request.Request(url, method="GET")
    resp = urllib.request.urlopen(req, timeout=30)
    body = json.loads(resp.read().decode("utf-8"))
    data = body.get("data", [body])
    logger.info("Webhook fields for WABA %s: %s", waba_id, data)
    return data


def _check_phone_number_status(pn_id: str, token: str) -> dict[str, Any]:
    """Obtiene el estado del número de teléfono.

    GET /{phone_number_id}?access_token={token}&fields=id,display_phone_number,verified_name,quality_rating,account_status
    """
    params = urllib.parse.urlencode({
        "access_token": token,
        "fields": "id,display_phone_number,verified_name,quality_rating,account_status,code_verification_status",
    })
    url = f"https://graph.facebook.com/v22.0/{pn_id}?{params}"
    req = urllib.request.Request(url, method="GET")
    resp = urllib.request.urlopen(req, timeout=30)
    body = json.loads(resp.read().decode("utf-8"))
    logger.info("Phone number status: display=%s status=%s", body.get("display_phone_number", "?"), body.get("account_status", "?"))
    return body


# ── HTML de la página de onboarding (incrustado) ──────────────────────
# El App Secret y tokens nunca aparecen aquí. Solo APP_ID y CONFIG_ID
# que son públicos.

def _build_html(public_url: str = "") -> str:
    """Construye la página HTML de onboarding con la URL pública si está disponible."""
    public_url_script = ""
    if public_url:
        safe_url = public_url.replace("\\", "\\\\").replace("'", "\\'")
        public_url_script = (
            f"var PUBLIC_URL = '{safe_url}';\n"
            f"document.getElementById('publicUrlDisplay').textContent = "
            f"'URL p\u00fablica: ' + PUBLIC_URL;\n"
        )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Doccione Studio — Conectar WhatsApp Business</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f0f2f5; display: flex; justify-content: center; align-items: center; min-height: 100vh; padding: 20px; }}
  .card {{ background: #fff; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.12); padding: 32px; max-width: 520px; width: 100%; }}
  h1 {{ font-size: 22px; color: #1a1a2e; margin-bottom: 8px; }}
  p {{ color: #555; font-size: 14px; line-height: 1.5; margin-bottom: 20px; }}
  #status {{ padding: 12px 16px; border-radius: 8px; margin-bottom: 20px; font-size: 14px; }}
  #status.ready {{ background: #e8f5e9; color: #2e7d32; }}
  #status.loading {{ background: #fff3e0; color: #e65100; }}
  #status.error {{ background: #ffebee; color: #c62828; }}
  #status.success {{ background: #e8f5e9; color: #1b5e20; }}
  #status.info {{ background: #e3f2fd; color: #0d47a1; }}
  button {{ background: #25d366; border: none; border-radius: 8px; color: #fff; cursor: pointer; font-size: 16px; font-weight: 600; height: 48px; padding: 0 28px; width: 100%; transition: background 0.2s; }}
  button:hover:not(:disabled) {{ background: #20bd5a; }}
  button:disabled {{ background: #a8a8a8; cursor: not-allowed; }}
  .steps {{ margin: 20px 0; padding: 0; list-style: none; }}
  .steps li {{ padding: 8px 0 8px 28px; position: relative; font-size: 14px; color: #555; }}
  .steps li::before {{ content: ''; position: absolute; left: 0; top: 10px; width: 18px; height: 18px; border-radius: 50%; border: 2px solid #ccc; }}
  .steps li.done {{ color: #2e7d32; }}
  .steps li.done::before {{ background: #25d366; border-color: #25d366; }}
  .steps li.done::after {{ content: '\\2713'; position: absolute; left: 3px; top: 8px; color: #fff; font-size: 12px; font-weight: bold; }}
  .steps li.active {{ color: #0d47a1; font-weight: 600; }}
  .steps li.active::before {{ border-color: #0d47a1; }}
  .steps li.error {{ color: #c62828; }}
  .steps li.error::before {{ border-color: #c62828; }}
  #result {{ margin-top: 16px; }}
  .field {{ display: flex; justify-content: space-between; padding: 6px 0; font-size: 13px; border-bottom: 1px solid #eee; }}
  .field .label {{ color: #777; }}
  .field .value {{ color: #1a1a2e; font-family: 'Courier New', monospace; font-size: 12px; word-break: break-all; }}
  .footer {{ margin-top: 20px; font-size: 12px; color: #999; text-align: center; }}
  .footer a {{ color: #1877f2; text-decoration: none; }}
</style>
</head>
<body>
<div class="card">
  <h1>Conectar WhatsApp Business</h1>
  <p>Vinculá tu número de WhatsApp Business App existente con Doccione Studio mediante Cloud API. El n\u00famero seguir\u00e1 funcionando en tu celular.</p>

  <div id="status" class="ready">Inicializando SDK de Facebook...</div>

  <button id="connectBtn" onclick="launchWhatsAppSignup()" disabled>Conectar WhatsApp Business</button>

  <ol class="steps" id="steps">
    <li id="step-sdk">Inicializar SDK de Facebook</li>
    <li id="step-login">Iniciar sesi\u00f3n en Meta (Embedded Signup)</li>
    <li id="step-select">Seleccionar empresa y n\u00famero existente</li>
    <li id="step-qr">Escanear QR desde WhatsApp Business App</li>
    <li id="step-exchange">Intercambiar code por token de acceso</li>
    <li id="step-subscribe">Suscribir aplicaci\u00f3n a la WABA</li>
    <li id="step-verify">Verificar webhook y estado del n\u00famero</li>
  </ol>

  <div id="result"></div>
  <div id="phone-status"></div>

  <div class="footer">
    Doccione Studio &mdash; Embedded Signup v4 &mdash; Coexistencia
    <br/><small id="publicUrlDisplay"></small>
  </div>
</div>

<script>
function setStep(id, state) {{
  var el = document.getElementById('step-' + id);
  if (el) {{ el.className = state; }}
}}

function setStatus(msg, type) {{
  var el = document.getElementById('status');
  el.textContent = msg;
  el.className = type || 'info';
}}

function showResult(html) {{
  document.getElementById('result').innerHTML = html;
}}

function showPhoneStatus(html) {{
  document.getElementById('phone-status').innerHTML = html;
}}

window.addEventListener('message', function(event) {{
  if (!event.origin.endsWith('facebook.com')) return;
  try {{
    var data = JSON.parse(event.data);
    if (data.type === 'WA_EMBEDDED_SIGNUP') {{
      setStep('qr', 'done');
      setStep('login', 'done');
      var payload = JSON.stringify({{ sessionEvent: data }});
      fetch('/api/callback', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: payload
      }}).then(function(r) {{ return r.json(); }}).then(function(resp) {{
        if (resp.status === 'ok') {{
          setStep('exchange', 'done');
          setStep('subscribe', 'done');
          setStep('verify', 'done');
          setStatus('Conectado exitosamente', 'success');
          showResult(
            '<div class="field"><span class="label">WABA ID</span><span class="value">' + escapeHtml(resp.waba_id) + '</span></div>' +
            '<div class="field"><span class="label">Phone Number ID</span><span class="value">' + escapeHtml(resp.phone_number_id) + '</span></div>' +
            '<div class="field"><span class="label">Business ID</span><span class="value">' + escapeHtml(resp.business_id) + '</span></div>' +
            '<div class="field"><span class="label">Token (últimos 4)</span><span class="value">' + escapeHtml(resp.token_preview) + '</span></div>' +
            '<div class="field"><span class="label">Webhook fields</span><span class="value">' + escapeHtml(resp.webhook_fields) + '</span></div>' +
            '<div class="field"><span class="label">N\u00famero</span><span class="value">' + escapeHtml(resp.display_phone_number) + '</span></div>' +
            '<div class="field"><span class="label">Estado</span><span class="value">' + escapeHtml(resp.account_status) + '</span></div>'
          );
        }} else {{
          setStatus('Error: ' + (resp.error || 'desconocido'), 'error');
          showResult('<p style="color:#c62828;">' + escapeHtml(resp.error || 'Error en el servidor') + '</p>');
        }}
      }})['catch'](function(err) {{
        setStatus('Error de red: ' + err.message, 'error');
      }});
    }}
  }} catch(e) {{
  }}
}});

function escapeHtml(text) {{
  if (!text) return '';
  var d = document.createElement('div');
  d.appendChild(document.createTextNode(text));
  return d.innerHTML;
}}

window.fbAsyncInit = function() {{
  FB.init({{
    appId: '{APP_ID}',
    version: 'v22.0',
    xfbml: true
  }});
  setStatus('Listo para conectar. Hac\u00e9 clic en el bot\u00f3n.', 'ready');
  setStep('sdk', 'done');
  document.getElementById('connectBtn').disabled = false;
}};

(function(d, s, id) {{
  var js, fjs = d.getElementsByTagName(s)[0];
  if (d.getElementById(id)) return;
  js = d.createElement(s); js.id = id;
  js.src = 'https://connect.facebook.net/es_LA/sdk.js';
  fjs.parentNode.insertBefore(js, fjs);
}}(document, 'script', 'facebook-jssdk'));

var fbLoginCallback = function(response) {{
  if (response.authResponse && response.authResponse.code) {{
    var code = response.authResponse.code;
    setStep('login', 'done');
    setStatus('C\u00f3digo recibido, intercambiando token...', 'loading');
    fetch('/api/callback', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ code: code }})
    }}).then(function(r) {{ return r.json(); }}).then(function(resp) {{
      if (resp.status === 'ok') {{
        setStep('exchange', 'done');
        setStep('subscribe', 'done');
        setStep('verify', 'done');
        setStatus('Conectado exitosamente', 'success');
        showResult(
          '<div class="field"><span class="label">WABA ID</span><span class="value">' + escapeHtml(resp.waba_id) + '</span></div>' +
          '<div class="field"><span class="label">Phone Number ID</span><span class="value">' + escapeHtml(resp.phone_number_id) + '</span></div>' +
          '<div class="field"><span class="label">Business ID</span><span class="value">' + escapeHtml(resp.business_id) + '</span></div>' +
          '<div class="field"><span class="label">Token (últimos 4)</span><span class="value">' + escapeHtml(resp.token_preview) + '</span></div>' +
          '<div class="field"><span class="label">Webhook fields</span><span class="value">' + escapeHtml(resp.webhook_fields) + '</span></div>' +
          '<div class="field"><span class="label">N\u00famero</span><span class="value">' + escapeHtml(resp.display_phone_number) + '</span></div>' +
          '<div class="field"><span class="label">Estado</span><span class="value">' + escapeHtml(resp.account_status) + '</span></div>'
        );
      }} else {{
        setStatus('Error: ' + (resp.error || 'desconocido'), 'error');
        showResult('<p style="color:#c62828;">' + escapeHtml(resp.error || 'Error en el servidor') + '</p>');
      }}
    }})['catch'](function(err) {{
      setStatus('Error de red: ' + err.message, 'error');
    }});
  }} else {{
    setStatus('Inicio de sesi\u00f3n cancelado o incompleto.', 'error');
  }}
}};

function launchWhatsAppSignup() {{
  setStep('login', 'active');
  setStatus('Abriendo Embedded Signup...', 'loading');
  document.getElementById('connectBtn').disabled = true;
  FB.login(fbLoginCallback, {{
    config_id: '{CONFIG_ID}',
    response_type: 'code',
    override_default_response_type: true,
    extras: {{
      featureType: 'whatsapp_business_app_onboarding'
    }}
  }});
}}

{public_url_script}
</script>
</body>
</html>"""


# ── Servidor HTTP ──────────────────────────────────────────────────────

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class OnboardingHandler(BaseHTTPRequestHandler):
    """Manejador de solicitudes del servidor de onboarding.

    GET  /               → página HTML de onboarding
    GET  /api/status     → estado de la configuración actual
    POST /api/callback   → recibe code + session data
    """

    app_secret: str = ""
    public_url: str = ""

    def _allowed_origins(self) -> set[str]:
        origins = {
            "http://127.0.0.1:8766",
            "http://localhost:8766",
            "null",
        }
        local_port = getattr(self.server, "server_address", None)
        if local_port:
            origins.add(f"http://127.0.0.1:{local_port[1]}")
            origins.add(f"http://localhost:{local_port[1]}")
        if self.public_url:
            parsed = urllib.parse.urlparse(self.public_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            origins.add(origin)
        return origins

    def _resolve_origin(self) -> str:
        req_origin = self.headers.get("Origin", "")
        allowed = self._allowed_origins()
        if req_origin and req_origin in allowed:
            return req_origin
        if self.public_url:
            parsed = urllib.parse.urlparse(self.public_url)
            return f"{parsed.scheme}://{parsed.netloc}"
        return "*"

    def _send_json(self, status: int, data: dict[str, Any]):
        self.send_response(status)
        origin = self._resolve_origin()
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Content-Type", "application/json")
        self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _send_html(self, status: int, html: str):
        self.send_response(status)
        origin = self._resolve_origin()
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _send_error(self, status: int, msg: str):
        self._send_json(status, {"status": "error", "error": msg})

    def _get_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def log_message(self, fmt: str, *args):
        logger.debug("Onboarding HTTP: %s", fmt % args)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self._send_html(200, _build_html(self.public_url))
        elif parsed.path == "/api/status":
            self._handle_status()
        else:
            self._send_html(404, "<h1>404 Not Found</h1>")

    def _handle_status(self):
        env = _load_dotenv()
        data = {}
        for key in ENV_TARGET_KEYS:
            val = os.environ.get(key) or env.get(key, "")
            data[key] = _mask(val) if "TOKEN" in key or "SECRET" in key else val
        data["WHATSAPP_ENABLED"] = os.environ.get("WHATSAPP_ENABLED") or env.get("WHATSAPP_ENABLED", "false")
        app_secret = os.environ.get("WHATSAPP_APP_SECRET") or env.get("WHATSAPP_APP_SECRET", "")
        data["WHATSAPP_APP_SECRET"] = "**configurado**" if app_secret else "**falta**"
        data["ONBOARDING_PUBLIC_URL"] = self.public_url or "(solo local)"
        self._send_json(200, {"status": "ok", "config": data})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/callback":
            self._handle_callback()
        else:
            self._send_error(404, "endpoint no encontrado")

    def do_OPTIONS(self):
        origin = self._resolve_origin()
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def _handle_callback(self):
        try:
            body = self._get_body()
        except Exception:
            self._send_error(400, "JSON inválido")
            return

        code = body.get("code", "")
        session_event = body.get("sessionEvent")

        # Session event prioritario: trae waba_id y phone_number_id
        waba_id = ""
        phone_number_id = ""
        business_id = ""
        if session_event and isinstance(session_event, dict):
            event_data = session_event.get("data") or session_event
            if isinstance(event_data, dict):
                waba_id = event_data.get("waba_id", "")
                phone_number_id = event_data.get("phone_number_id", "")
                business_id = event_data.get("business_id", event_data.get("businessId", ""))

        if not code:
            self._send_error(400, "Código de intercambio no recibido. Completá el flujo de Embedded Signup.")
            return

        self._set_step("exchange")

        app_secret = self.app_secret

        # 1. Intercambiar code por token
        try:
            token = _exchange_code(code, app_secret)
        except Exception as exc:
            logger.error("Error intercambiando code: %s", exc)
            self._send_error(500, f"Error intercambiando el code: {exc}")
            return

        # Leer .env o entorno para obtener IDs si el session event no los trajo
        if not waba_id or not phone_number_id:
            env = _load_dotenv()
            if not waba_id:
                waba_id = os.environ.get("WHATSAPP_BUSINESS_ACCOUNT_ID") or env.get("WHATSAPP_BUSINESS_ACCOUNT_ID", "")
            if not phone_number_id:
                phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID") or env.get("WHATSAPP_PHONE_NUMBER_ID", "")
            if not business_id:
                business_id = os.environ.get("WHATSAPP_BUSINESS_ID") or env.get("WHATSAPP_BUSINESS_ID", "")

        if not waba_id or not phone_number_id:
            self._send_error(400, "No se recibió waba_id ni phone_number_id del Embedded Signup ni están en .env.")
            return

        self._set_step("subscribe")

        # 2. Suscribir app a la WABA
        try:
            sub_result = _subscribe_app(waba_id, token)
        except Exception as exc:
            logger.error("Error suscribiendo app a WABA %s: %s", waba_id, exc)
            sub_result = {"error": str(exc)[:200]}
            # No detenemos el flujo por esto; la suscripción puede reintentarse

        self._set_step("verify")

        # 3. Verificar webhook fields
        try:
            webhook_data = _check_webhook_fields(waba_id, token)
            webhook_fields = [item.get("whatsapp_business_api_data", {}).get("webhook_fields", [])
                              if isinstance(item, dict) else [] for item in webhook_data]
            webhook_summary = ", ".join(
                f for sublist in webhook_fields for f in sublist
            ) or "messages (esperado)"
        except Exception as exc:
            logger.error("Error verificando webhook: %s", exc)
            webhook_summary = f"error: {exc}"

        # 4. Verificar estado del número
        try:
            pn_status = _check_phone_number_status(phone_number_id, token)
            display_phone = pn_status.get("display_phone_number", phone_number_id)
            account_status = pn_status.get("account_status", "conectado")
        except Exception as exc:
            logger.error("Error verificando número: %s", exc)
            display_phone = phone_number_id
            account_status = f"error: {exc}"

        # 5. Actualizar .env
        try:
            _update_dotenv({
                "WHATSAPP_WABA_ID": waba_id,
                "WHATSAPP_PHONE_NUMBER_ID": phone_number_id,
                "WHATSAPP_ACCESS_TOKEN": token,
                "WHATSAPP_BUSINESS_ID": business_id,
                "WHATSAPP_CONFIGURATION_ID": CONFIG_ID,
            })
        except Exception as exc:
            logger.error("Error actualizando .env: %s", exc)
            self._send_error(500, f"Error actualizando .env: {exc}")
            return

        logger.info("Onboarding completado para WABA %s, número %s", waba_id, display_phone)

        self._send_json(200, {
            "status": "ok",
            "waba_id": waba_id,
            "phone_number_id": phone_number_id,
            "business_id": business_id or "(no proporcionado)",
            "token_preview": _mask(token),
            "webhook_fields": webhook_summary[:200],
            "display_phone_number": display_phone,
            "account_status": account_status,
        })

    def _set_step(self, step: str):
        logger.debug("Onboarding step: %s", step)


class OnboardingServer:
    """Servidor HTTP para el flujo de onboarding.

    start()  → inicia en hilo daemon
    stop()   → detiene ordenadamente
    """

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT, public_url: str = ""):
        self.host = host
        self.port = port
        self.public_url = public_url
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            logger.debug("Onboarding server already running on %s:%d", self.host, self.port)
            return True

        app_secret = _get_app_secret()
        OnboardingHandler.app_secret = app_secret
        OnboardingHandler.public_url = self.public_url

        try:
            self._server = ThreadingHTTPServer((self.host, self.port), OnboardingHandler)
            actual_port = self._server.server_address[1]
            self.port = actual_port
            self._thread = threading.Thread(
                target=self._serve,
                name="whatsapp-onboarding",
                daemon=True,
            )
            self._thread.start()
            logger.info("Onboarding server started on %s:%d", self.host, self.port)
            return True
        except OSError as exc:
            logger.error("Cannot start onboarding server on %s:%d: %s", self.host, self.port, exc)
            self._server = None
            return False

    def _serve(self):
        try:
            self._server.serve_forever(poll_interval=0.5)
        except Exception as exc:
            logger.error("Onboarding server stopped: %s", exc)
        finally:
            if self._server:
                self._server.server_close()

    def stop(self):
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server:
            try:
                server.shutdown()
            except Exception:
                pass
            try:
                server.server_close()
            except Exception:
                pass
        if thread and thread is not threading.current_thread():
            thread.join(timeout=3)
        logger.info("Onboarding server stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


# ── Entry point ────────────────────────────────────────────────────────

def main():
    import signal
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Verificar App Secret antes de arrancar
    try:
        secret = _get_app_secret()
        _ = len(secret)  # lint
    except RuntimeError as exc:
        print("=" * 60)
        print("ERROR:", exc)
        print("=" * 60)
        print()
        print("Agregá al archivo .env en la raíz del proyecto:")
        print()
        print("  WHATSAPP_APP_SECRET=tu_app_secret_de_meta")
        print()
        print("(sin comillas, sin espacios)")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Doccione - Onboarding WhatsApp Coexistencia")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Puerto local (default: 8766)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host (default: 127.0.0.1)")
    parser.add_argument("--public-url", type=str, default="", help="URL publica del tunel HTTPS (ej: https://xxx.trycloudflare.com)")
    args = parser.parse_args()

    public_url = args.public_url or os.environ.get("WHATSAPP_ONBOARDING_PUBLIC_URL", "")

    server = OnboardingServer(host=args.host, port=args.port, public_url=public_url)
    if not server.start():
        print(f"ERROR: No se pudo iniciar el servidor en {args.host}:{args.port}")
        sys.exit(1)

    url = f"http://{args.host}:{server.port}/"
    print()
    print("=" * 60)
    print("  Doccione Studio — Onboarding WhatsApp Coexistencia")
    print("=" * 60)
    print()
    if public_url:
        print(f"  URL publica:  {public_url}")
    print(f"  URL local:    {url}")
    print()
    print("  Pasos:")
    print("  1. Hacé clic en 'Conectar WhatsApp Business'")
    print("  2. Iniciá sesión con tu cuenta de Meta")
    print("  3. Seleccioná la empresa y el número +54 9 3755 30-4791")
    print("  4. Escaneá el QR desde WhatsApp Business App del celular")
    print("  5. El servidor intercambia el token y actualiza .env")
    print()
    print("  Presioná Ctrl+C para detener.")
    print()

    def shutdown(signum, frame):
        print("\nDeteniendo...")
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        server._thread.join()
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()
