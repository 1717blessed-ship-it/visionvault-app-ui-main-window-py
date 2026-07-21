"""Servicio central de notificaciones push de Doccione Studio."""

from __future__ import annotations

import json
import logging
import threading
import time

from app.events.event_repository import EventRepository
from app.notifications.firebase_sender import SendPayload, SendResult, send_push

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 5


class NotificationService:
    """Coordina el envío de notificaciones push usando el patrón outbox.

    Flujo:
    1. La aplicación publica un evento (EventBus).
    2. Se crea una entrada en notification_outbox para cada dispositivo activo.
    3. Un worker en background procesa el outbox y envía vía Firebase.
    4. Si falla, reintenta con backoff exponencial.
    5. Si el token es inválido, desactiva el dispositivo.
    """

    def __init__(self, repo: EventRepository):
        self.repo = repo
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._interval_seconds = 10

    def start_worker(self, interval_seconds: int = 10) -> None:
        """Inicia el worker de background que procesa el outbox."""
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._interval_seconds = interval_seconds
        self._worker_thread = threading.Thread(target=self._run_worker, daemon=True)
        self._worker_thread.start()
        logger.info("Notification worker iniciado (intervalo: %ds)", interval_seconds)

    def stop_worker(self) -> None:
        """Detiene el worker de forma ordenada."""
        self._stop_event.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
        logger.info("Notification worker detenido")

    def _run_worker(self) -> None:
        """Loop principal del worker de outbox."""
        while not self._stop_event.is_set():
            try:
                self.repo.cleanup_expired_pairing_codes()
                self._process_outbox()
            except Exception as exc:
                logger.error("Error procesando outbox: %s", exc)
            self._stop_event.wait(timeout=self._interval_seconds)

    def _process_outbox(self) -> None:
        """Procesa mensajes pendientes del outbox."""
        pending = self.repo.pending_outbox(limit=10)
        if not pending:
            return

        for item in pending:
            self._send_one(item)

    def _send_one(self, item: dict) -> None:
        """Envía un solo mensaje del outbox."""
        # Marcar como processing para evitar procesamiento concurrente
        self.repo.mark_outbox_processing(item["id"])

        token = item["recipient_id"]
        title = item["title"]
        message = item["message"]

        # Verificar si Firebase está inicializado
        from app.notifications.firebase_sender import _firebase_initialized
        if not _firebase_initialized:
            logger.debug("Firebase no configurado, mensaje pendiente: %s", title)
            self.repo.mark_outbox_failed(item["id"], "Firebase no configurado", retry_after_seconds=0)
            return

        # Construir payload estructurado
        payload = SendPayload(
            event_uuid=item.get("event_uuid", ""),
            event_type=item.get("event_type", ""),
            entity_type=item.get("entity_type") or "",
            entity_id=str(item.get("entity_id") or ""),
            priority=item.get("priority", "normal"),
            route=self._build_route(item),
        )

        collapse_key = f"{item.get('event_type', '')}:{item.get('entity_id', '')}"

        try:
            result: SendResult = send_push(
                token=token,
                title=title,
                body=message,
                data=payload,
                priority=item.get("priority", "normal"),
                event_type=item.get("event_type", ""),
                collapse_key=collapse_key,
            )
        except Exception as exc:
            result = SendResult(success=False, error=str(exc), raw_error=str(exc))

        if result.success:
            self.repo.mark_outbox_sent(item["id"])
            logger.info("Push enviado: %s → %s...", title, token[:12])
            return

        error_msg = result.error or "Error desconocido"

        # Error permanente: token inválido → desactivar dispositivo y dead letter
        if result.is_permanent:
            self.repo.deactivate_device_by_token(token, reason=error_msg)
            self.repo.mark_outbox_dead_letter(item["id"], error_msg)
            logger.error("Token inválido, dispositivo desactivado: %s — %s", token[:12], error_msg)
            return

        # Máximo de intentos alcanzado → dead letter
        if item["attempts"] >= _MAX_ATTEMPTS:
            self.repo.mark_outbox_dead_letter(item["id"], error_msg)
            logger.error("Mensaje muerto (%d+ intentos): %s — %s", _MAX_ATTEMPTS, title, error_msg)
            return

        # Error reintentable o desconocido → backoff exponencial
        retry_seconds = min(300, 60 * (2 ** item["attempts"]))
        self.repo.mark_outbox_failed(item["id"], error_msg, retry_seconds)
        logger.warning("Push falló, reintento en %ds: %s — %s", retry_seconds, title, error_msg)

    def _build_route(self, item: dict) -> str:
        """Construye la ruta de navegación para la app móvil."""
        entity_type = item.get("entity_type") or ""
        entity_id = item.get("entity_id")
        if entity_type and entity_id:
            return f"/{entity_type}/{entity_id}"
        return ""

    def send_test_notification(self, token: str, title: str = "Prueba", message: str = "Notificación de prueba") -> bool:
        """Envía una notificación de prueba directamente (sin outbox)."""
        from app.notifications.firebase_sender import _firebase_initialized
        if not _firebase_initialized:
            logger.warning("Firebase no configurado para prueba")
            return False
        try:
            result = send_push(
                token=token,
                title=title,
                body=message,
                priority="normal",
                event_type="",
            )
            return result.success
        except Exception as exc:
            logger.error("Prueba falló: %s", exc)
            return False
