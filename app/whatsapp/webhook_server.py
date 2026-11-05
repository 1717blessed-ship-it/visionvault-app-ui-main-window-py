"""Servidor HTTP para webhook de WhatsApp Business Cloud API.

Usa http.server.ThreadingHTTPServer para manejo concurrente.
No depende de Flask, FastAPI ni dependencias externas.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Any, Callable
from urllib.parse import urlparse, parse_qs

from app.whatsapp.config import load_config
from app.whatsapp.webhook_parser import (
    parse_payload,
    build_event_key,
    verify_signature,
)
from app.whatsapp.service import WhatsAppService

logger = logging.getLogger(__name__)


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """HTTPServer con soporte para threading (Python 3.7+ nativo)."""
    allow_reuse_address = True
    daemon_threads = True


class WhatsAppWebhookHandler(BaseHTTPRequestHandler):
    """Manejador de solicitudes del webhook de WhatsApp.

    GET  /api/whatsapp/webhook  → verificación de Meta (challenge)
    POST /api/whatsapp/webhook  → recepción de eventos
    """

    # Seteado por factory method
    service: WhatsAppService | None = None
    config: Any = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    # ── Routing ─────────────────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/whatsapp/webhook":
            self._handle_verification(parsed)
        else:
            self._send_text(404, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/whatsapp/webhook":
            self._handle_webhook()
        else:
            self._send_text(404, "Not Found")

    # ── GET: Verificación ───────────────────────────────────────────────

    def _handle_verification(self, parsed):
        params = parse_qs(parsed.query)
        mode = params.get("hub.mode", [None])[0]
        token = params.get("hub.verify_token", [None])[0]
        challenge = params.get("hub.challenge", [None])[0]

        cfg = self._get_config()

        if not mode or not token or challenge is None:
            self._send_text(400, "Bad Request: missing parameters")
            return

        if mode != "subscribe":
            self._send_text(400, f"Bad Request: unsupported mode '{mode}'")
            return

        if token != cfg.verify_token:
            self._send_text(403, "Forbidden: invalid verify token")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(str(challenge).encode("utf-8"))

    # ── POST: Webhook ───────────────────────────────────────────────────

    def _handle_webhook(self):
        cfg = self._get_config()

        # Validar Content-Length
        content_length = self.headers.get("Content-Length")
        if content_length:
            try:
                size = int(content_length)
            except (ValueError, TypeError):
                self._send_text(400, "Bad Request: invalid Content-Length")
                return
            if size > cfg.max_webhook_bytes:
                # Consumir una cantidad limitada del cuerpo ya enviado evita
                # que Windows cierre el socket con RST antes de entregar la
                # respuesta 413 al cliente. El límite mantiene esta ruta
                # segura ante Content-Lengths maliciosamente enormes.
                self.rfile.read(min(size, cfg.max_webhook_bytes + 1))
                self._send_text(413, "Payload Too Large")
                return
            if size == 0:
                self._send_text(400, "Bad Request: empty body")
                return

        # Leer cuerpo
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length)
        except Exception:
            self._send_text(400, "Bad Request: cannot read body")
            return

        if not raw_body:
            self._send_text(400, "Bad Request: empty body")
            return

        # Validar firma
        if cfg.verify_signature:
            sig_header = self.headers.get("X-Hub-Signature-256", "")
            if not sig_header:
                self._send_text(401, "Unauthorized: missing signature")
                return
            if not cfg.app_secret:
                self._send_text(500, "Server Error: APP_SECRET not configured")
                return
            if not verify_signature(raw_body, sig_header, cfg.app_secret):
                self._send_text(401, "Unauthorized: invalid signature")
                return

        # Parsear JSON
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_text(400, "Bad Request: invalid JSON")
            return

        # Generar event_key
        try:
            entries = payload.get("entry", [])
            if entries:
                event_key = build_event_key(entries[0])
            else:
                event_key = build_event_key(payload)
        except Exception:
            self._send_text(400, "Bad Request: cannot build event key")
            return

        # Parsear payload estructurado
        try:
            parsed = parse_payload(payload)
        except Exception:
            self._send_text(400, "Bad Request: cannot parse payload")
            return

        # Procesar
        svc = self._get_service()
        if svc is None:
            self._send_text(500, "Server Error: service not available")
            return

        try:
            result = svc.process_webhook_payload(
                parsed=parsed,
                event_key=event_key,
                raw_payload_json=json.dumps(payload, ensure_ascii=False),
            )
        except Exception as exc:
            logger.error("Error processing webhook: %s", exc)
            self._send_text(500, "Internal Server Error")
            return

        self._send_json(200, {"status": "ok", "result": result})

    # ── Helpers ─────────────────────────────────────────────────────────

    def _get_config(self):
        cfg = getattr(self, "config", None)
        if cfg is None:
            cfg = load_config()
            self.config = cfg
        return cfg

    def _get_service(self):
        return getattr(self, "service", None)

    def _send_text(self, status: int, text: str):
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(text.encode("utf-8"))

    def _send_json(self, status: int, data: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        logger.debug("Webhook: %s", format % args)


class WhatsAppWebhookServer:
    """Servidor HTTP para webhook de WhatsApp.

    Ciclo de vida independiente: start(), stop(), is_running.
    No se inicia automáticamente al importar.
    """

    def __init__(
        self,
        service: WhatsAppService,
        host: str = "0.0.0.0",
        port: int = 8767,
        config=None,
    ):
        self.service = service
        self.host = host
        self.port = port
        self._config = config
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        """Inicia el servidor en un hilo separado (daemon)."""
        if self._thread is not None and self._thread.is_alive():
            logger.debug("Webhook server already running on %s:%d", self.host, self.port)
            return True

        # Establecer atributos de clase ANTES de que BaseHTTPRequestHandler.__init__
        # llame a handle_one_request() durante la construcción.
        WhatsAppWebhookHandler.service = self.service
        WhatsAppWebhookHandler.config = self._config

        try:
            self._server = ThreadingHTTPServer((self.host, self.port), WhatsAppWebhookHandler)
            actual_port = self._server.server_address[1]
            self.port = actual_port
            self._thread = threading.Thread(
                target=self._serve,
                name="whatsapp-webhook",
                daemon=True,
            )
            self._thread.start()
            logger.info(
                "WhatsApp webhook server started on %s:%d",
                self.host, self.port,
            )
            return True
        except OSError as exc:
            logger.error("Cannot start webhook server on %s:%d: %s", self.host, self.port, exc)
            self._server = None
            return False

    def _serve(self):
        try:
            self._server.serve_forever(poll_interval=0.5)
        except Exception as exc:
            logger.error("Webhook server stopped: %s", exc)
        finally:
            if self._server:
                self._server.server_close()

    def stop(self):
        """Detiene el servidor de forma ordenada."""
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None

        if server is not None:
            try:
                server.shutdown()
            except Exception:
                pass
            try:
                server.server_close()
            except Exception:
                pass

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3)

        logger.info("WhatsApp webhook server stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


def main():
    """Punto de entrada independiente: python -m app.whatsapp.webhook_server"""
    import signal
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    from app.whatsapp.config import _load_dotenv, load_config
    _load_dotenv()
    cfg = load_config(reload=True)

    if not cfg.enabled:
        print("WHATSAPP_ENABLED=false — servidor no iniciado.")
        sys.exit(0)

    import sqlite3
    from app.whatsapp.repository import create_whatsapp_tables, WhatsAppRepository
    from app.whatsapp.service import WhatsAppService
    from pathlib import Path

    db_path = Path(__file__).resolve().parents[2] / "visionvault.db"
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    create_whatsapp_tables(conn)
    repo = WhatsAppRepository(conn)
    svc = WhatsAppService(repo)

    server = WhatsAppWebhookServer(
        service=svc,
        host="127.0.0.1",
        port=8767,
        config=cfg,
    )

    if not server.start():
        print("ERROR: no se pudo iniciar el servidor webhook.")
        sys.exit(1)

    print(f"Webhook escuchando en http://127.0.0.1:{server.port}/api/whatsapp/webhook")
    print("Presioná Ctrl+C para detener.")

    def shutdown(signum, frame):
        print("\nDeteniendo...")
        server.stop()
        conn.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        server._thread.join()
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()
