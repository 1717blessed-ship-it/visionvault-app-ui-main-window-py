from __future__ import annotations

import json
import logging
import random
import threading
import time
from datetime import datetime, timezone

from app.whatsapp.client import WhatsAppCloudClient
from app.whatsapp.config import WhatsAppConfig
from app.whatsapp.models import WhatsAppOutboxItem, WhatsAppSendResult
from app.whatsapp.repository import WhatsAppRepository

logger = logging.getLogger(__name__)


class WhatsAppOutboxWorker:
    def __init__(
        self,
        repo: WhatsAppRepository,
        client: WhatsAppCloudClient,
        config: WhatsAppConfig,
    ):
        self._repo = repo
        self._client = client
        self._config = config
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._lock = threading.Lock()
        self._worker_id = f"worker_{id(self)}_{time.time_ns()}"

    def start(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                logger.debug("Outbox worker already running")
                return True
            self._stop_event.clear()
            self._wake_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="whatsapp-outbox-worker",
                daemon=True,
            )
            self._thread.start()
            logger.info("WhatsApp outbox worker started (%s)", self._worker_id[:16])
            return True

    def stop(self) -> bool:
        thread = None
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                return False
            self._stop_event.set()
            self._wake_event.set()
            thread = self._thread
            self._thread = None
        thread.join(timeout=10)
        logger.info("WhatsApp outbox worker stopped")
        return True

    @property
    def is_running(self) -> bool:
        t = self._thread
        return t is not None and t.is_alive()

    def wake_up(self) -> None:
        self._wake_event.set()

    def process_once(self, limit: int | None = None) -> int:
        if not self._config.enabled:
            logger.debug("WhatsApp disabled, skipping outbox processing")
            return 0

        batch_size = limit if limit is not None else self._config.outbox_batch_size
        items = self._repo.claim_pending_outbox_items(
            worker_id=self._worker_id,
            limit=batch_size,
            processing_timeout_seconds=self._config.outbox_processing_timeout_seconds,
        )
        if not items:
            return 0

        processed = 0
        for item in items:
            try:
                self._process_item(item)
            except Exception as exc:
                logger.error("Unhandled error processing outbox %d: %s", item.id, exc)
                self._repo.release_outbox_for_retry(
                    item.id,
                    error=f"Unhandled: {exc!s}"[:500],
                    retry_after_seconds=self._compute_backoff(item.attempts),
                )
            processed += 1
        return processed

    def _process_item(self, item: WhatsAppOutboxItem) -> None:
        try:
            payload = json.loads(item.payload_json)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Invalid payload in outbox %d: %s", item.id, exc)
            self._repo.mark_outbox_failed(item.id, error=f"Invalid payload: {exc!s}"[:500])
            return

        pn_id = item.phone_number_id or self._config.phone_number_id or None

        result = self._client.send_raw_payload(payload, phone_number_id=pn_id)

        if result.success:
            self._handle_success(item, result, payload)
        elif result.retryable:
            self._handle_retryable(item, result)
        else:
            self._handle_permanent_failure(item, result)

    def _handle_success(
        self,
        item: WhatsAppOutboxItem,
        result: WhatsAppSendResult,
        payload: dict[str, Any],
    ) -> None:
        wa_msg_id = result.whatsapp_message_id
        self._repo.mark_outbox_sent(item.id, wa_message_id=wa_msg_id)

        if item.conversation_id and wa_msg_id:
            msg_type = payload.get("type", item.message_type)
            text_body = None
            media_id = None
            mime_type = None
            filename = None
            caption = None
            msg_data = payload.get(msg_type, {}) if isinstance(payload.get(msg_type), dict) else {}
            if msg_type == "text":
                text_body = msg_data.get("body")
            elif "id" in msg_data:
                media_id = msg_data["id"]
                filename = msg_data.get("filename")
                caption = msg_data.get("caption")
            self._repo.update_outbound_message_after_send(
                conversation_id=item.conversation_id,
                wa_message_id=wa_msg_id,
                message_type=msg_type,
                text_body=text_body,
                media_id=media_id,
                mime_type=mime_type,
                filename=filename,
                caption=caption,
                delivery_status="sent",
            )

        last4 = item.recipient_wa_id[-4:] if len(item.recipient_wa_id) >= 4 else item.recipient_wa_id
        logger.info("Outbox %d sent to +...%s: wa_msg_id=%s", item.id, last4, wa_msg_id)

    def _handle_retryable(
        self,
        item: WhatsAppOutboxItem,
        result: WhatsAppSendResult,
    ) -> None:
        retry_after = result.retry_after_seconds
        if retry_after is None:
            retry_after = self._compute_backoff(item.attempts)

        last4 = item.recipient_wa_id[-4:] if len(item.recipient_wa_id) >= 4 else item.recipient_wa_id
        logger.info("Outbox %d to +...%s retryable (attempt %d/%d, retry in %ds)",
                    item.id, last4, item.attempts, self._config.outbox_max_attempts, retry_after)

        if item.attempts >= self._config.outbox_max_attempts:
            logger.warning("Outbox %d exceeded max attempts (%d), marking failed",
                          item.id, self._config.outbox_max_attempts)
            self._repo.mark_outbox_failed(
                item.id,
                error=f"Max attempts reached: {result.error_message or ''}"[:500],
            )
            return

        self._repo.release_outbox_for_retry(
            item.id,
            error=(result.error_message or "Retryable error")[:500],
            retry_after_seconds=retry_after,
        )

    def _handle_permanent_failure(
        self,
        item: WhatsAppOutboxItem,
        result: WhatsAppSendResult,
    ) -> None:
        last4 = item.recipient_wa_id[-4:] if len(item.recipient_wa_id) >= 4 else item.recipient_wa_id
        logger.warning("Outbox %d to +...%s permanently failed: HTTP %d %s",
                      item.id, last4, result.http_status, result.error_message or "")
        self._repo.mark_outbox_failed(
            item.id,
            error=(result.error_message or "Permanent failure")[:500],
        )

    def _compute_backoff(self, attempts: int) -> int:
        base = self._config.outbox_retry_base_seconds
        maximum = self._config.outbox_retry_max_seconds
        delay = min(base * (2 ** (attempts - 1)), maximum)
        jitter = random.randint(0, min(10, int(delay * 0.1) + 1))
        return delay + jitter

    def _run_loop(self) -> None:
        poll = self._config.outbox_poll_seconds
        while not self._stop_event.is_set():
            try:
                self.process_once()
            except Exception as exc:
                logger.error("Error in outbox worker loop: %s", exc)
            self._wake_event.wait(timeout=poll)
            self._wake_event.clear()
