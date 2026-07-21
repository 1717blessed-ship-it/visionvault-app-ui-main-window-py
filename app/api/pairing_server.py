"""Servidor HTTP para vinculación de dispositivos móviles."""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Callable

logger = logging.getLogger(__name__)


class PairingRequestHandler(BaseHTTPRequestHandler):
    """Manejador de solicitudes HTTP para emparejamiento de dispositivos."""

    def __init__(self, *args, repo_callback: Callable | None = None, **kwargs):
        self.repo_callback = repo_callback
        super().__init__(*args, **kwargs)

    def do_POST(self):
        """Maneja solicitudes POST."""
        if self.path == "/api/pair/validate":
            self._handle_validate()
        elif self.path == "/api/device/update-token":
            self._handle_update_token()
        else:
            self._send_error(404, "Endpoint no encontrado")

    def _handle_validate(self):
        """Valida un código de emparejamiento y registra el dispositivo."""
        try:
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode("utf-8"))

            code = data.get("code")
            push_token = data.get("push_token")
            platform = data.get("platform", "android")
            device_name = data.get("device_name", "")
            app_version = data.get("app_version", "")

            if not code or not push_token:
                self._send_error(400, "Faltan campos requeridos: code, push_token")
                return

            repo = self.repo_callback()
            if not repo:
                self._send_error(500, "Repositorio no disponible")
                return

            success, message, device_id, session_token = repo.register_device_with_pairing(
                pairing_code=code,
                push_token=push_token,
                platform=platform,
                device_name=device_name,
                app_version=app_version,
            )

            if success:
                self._send_json({
                    "success": True,
                    "message": message,
                    "device_id": device_id,
                    "session_token": session_token,  # Token de sesión para autenticación HTTP
                })
            else:
                self._send_error(400, message)

        except json.JSONDecodeError:
            self._send_error(400, "JSON inválido")
        except Exception as e:
            logger.error("Error validando código: %s", e)
            self._send_error(500, str(e))

    def _handle_update_token(self):
        """Actualiza el token FCM de un dispositivo."""
        try:
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode("utf-8"))

            old_token = data.get("old_token")
            new_token = data.get("new_token")

            if not old_token or not new_token:
                self._send_error(400, "Faltan campos requeridos: old_token, new_token")
                return

            repo = self.repo_callback()
            if not repo:
                self._send_error(500, "Repositorio no disponible")
                return

            success = repo.update_device_token_safe(old_token, new_token)

            if success:
                self._send_json({
                    "success": True,
                    "message": "Token actualizado exitosamente",
                })
            else:
                self._send_error(400, "Error actualizando token")

        except json.JSONDecodeError:
            self._send_error(400, "JSON inválido")
        except Exception as e:
            logger.error("Error actualizando token: %s", e)
            self._send_error(500, str(e))

    def _send_json(self, data: dict, status: int = 200):
        """Envía respuesta JSON."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _send_error(self, status: int, message: str):
        """Envía respuesta de error."""
        self._send_json({"success": False, "error": message}, status)

    def log_message(self, format: str, *args):
        """Sobrescribe para reducir verbosity."""
        logger.debug(format, *args)


class PairingServer:
    """Servidor HTTP para emparejamiento de dispositivos."""

    def __init__(self, port: int = 8765, repo_callback: Callable | None = None):
        self.port = port
        self.repo_callback = repo_callback
        self.server: HTTPServer | None = None
        self.server_thread: Thread | None = None

    def start(self) -> bool:
        """Inicia el servidor en un thread separado."""
        try:
            def handler(*args, **kwargs):
                return PairingRequestHandler(*args, repo_callback=self.repo_callback, **kwargs)

            self.server = HTTPServer(("localhost", self.port), handler)
            self.server_thread = Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            logger.info("Servidor de emparejamiento iniciado en puerto %d", self.port)
            return True
        except OSError as e:
            logger.error("Error iniciando servidor: %s", e)
            return False

    def stop(self):
        """Detiene el servidor."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            logger.info("Servidor de emparejamiento detenido")
