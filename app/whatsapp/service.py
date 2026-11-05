"""Servicio central del módulo WhatsApp."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.whatsapp.models import (
    WhatsAppMessage,
    WhatsAppConversation,
    WhatsAppContact,
    WhatsAppOutboxItem,
    ParsedPayload,
    ParsedMessage,
    ParsedStatus,
)
from app.whatsapp.repository import WhatsAppRepository

logger = logging.getLogger(__name__)

_VALID_MESSAGE_TYPES = frozenset({
    "text", "image", "sticker", "video", "audio", "voice",
    "document", "location", "contacts", "reaction", "interactive",
    "unknown",
})

_VALID_CONVERSATION_STATUSES = frozenset({
    "open", "pending", "resolved", "archived",
})


class WhatsAppService:
    """Coordina repositorio y reglas de negocio de WhatsApp.

    No depende de Tkinter, no llama a la API de Meta directamente,
    no importa main_window.
    """

    def __init__(self, repo: WhatsAppRepository):
        self.repo = repo
        self._worker: Any = None

    def set_worker(self, worker: Any) -> None:
        self._worker = worker

    def _wake_worker(self) -> None:
        w = self._worker
        if w is not None:
            try:
                w.wake_up()
            except Exception:
                pass

    # ── Registro de mensajes entrantes ──────────────────────────────────

    def register_inbound_message(
        self,
        wa_id: str,
        phone_number: str,
        display_name: str,
        message_type: str,
        wa_message_id: str | None = None,
        text_body: str | None = None,
        media_id: str | None = None,
        media_path: str | None = None,
        mime_type: str | None = None,
        filename: str | None = None,
        caption: str | None = None,
        reply_to_message_id: str | None = None,
        message_timestamp: str | None = None,
        raw_payload: dict | None = None,
        phone_number_id: str = "",
        business_account_id: str = "",
    ) -> dict[str, Any] | None:
        """Registra un mensaje entrante completo: contacto, conversación, mensaje.

        Returns dict con {contact, conversation, message} o None si duplicado.
        """
        message_type = message_type if message_type in _VALID_MESSAGE_TYPES else "unknown"

        contact = self.repo.create_or_update_contact(
            wa_id=wa_id,
            phone_number=phone_number,
            display_name=display_name,
        )

        conversation = self.repo.create_or_get_open_conversation(
            contact_id=contact.id,
            phone_number_id=phone_number_id,
            business_account_id=business_account_id,
        )

        message = self.repo.save_inbound_message(
            conversation_id=conversation.id,
            message_type=message_type,
            wa_message_id=wa_message_id,
            text_body=text_body,
            media_id=media_id,
            media_path=media_path,
            mime_type=mime_type,
            filename=filename,
            caption=caption,
            reply_to_message_id=reply_to_message_id,
            message_timestamp=message_timestamp,
            raw_payload_json=json.dumps(raw_payload, ensure_ascii=False) if raw_payload else None,
        )

        if message is None:
            return None

        self.repo.increment_unread_count(conversation.id)
        conversation = self.repo.get_conversation(conversation.id)

        return {
            "contact": contact,
            "conversation": conversation,
            "message": message,
        }

    # ── Actualización de estado de entrega ──────────────────────────────

    def register_status_update(
        self,
        wa_message_id: str,
        status: str,
        error_code: str | None = None,
    ) -> bool:
        """Actualiza el delivery_status de un mensaje saliente."""
        return self.repo.update_message_delivery_status(
            wa_message_id=wa_message_id,
            delivery_status=status,
            error_code=error_code,
        )

    # ── Cola de mensajes salientes ──────────────────────────────────────

    def queue_text_message(
        self,
        recipient_wa_id: str,
        text_body: str,
        conversation_id: int | None = None,
        phone_number_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> WhatsAppOutboxItem:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_wa_id,
            "type": "text",
            "text": {"preview_url": False, "body": text_body},
        }
        result = self.repo.enqueue_outbound_message(
            recipient_wa_id=recipient_wa_id,
            message_type="text",
            payload_json=payload,
            conversation_id=conversation_id,
            phone_number_id=phone_number_id,
            idempotency_key=idempotency_key,
        )
        self._wake_worker()
        return result

    def queue_media_message(
        self,
        recipient_wa_id: str,
        media_type: str,
        media_id_or_link: str,
        caption: str | None = None,
        filename: str | None = None,
        conversation_id: int | None = None,
        phone_number_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> WhatsAppOutboxItem:
        media_key = "link" if media_id_or_link.startswith("http") else "id"
        body: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_wa_id,
            "type": media_type,
            media_type: {media_key: media_id_or_link},
        }
        if caption:
            body[media_type]["caption"] = caption
        if filename and media_type == "document":
            body[media_type]["filename"] = filename
        result = self.repo.enqueue_outbound_message(
            recipient_wa_id=recipient_wa_id,
            message_type=media_type,
            payload_json=body,
            conversation_id=conversation_id,
            phone_number_id=phone_number_id,
            idempotency_key=idempotency_key,
        )
        self._wake_worker()
        return result

    # ── Vinculaciones ───────────────────────────────────────────────────

    def link_conversation_to_order(
        self, conversation_id: int, order_id: int
    ) -> bool:
        return self.repo.link_conversation_to_order(conversation_id, order_id)

    def link_contact_to_client(self, contact_id: int, client_id: int) -> bool:
        return self.repo.link_contact_to_client(contact_id, client_id)

    def mark_conversation_read(self, conversation_id: int) -> None:
        self.repo.clear_unread_count(conversation_id)

    # ── Consultas ───────────────────────────────────────────────────────

    def get_conversation_messages(
        self, conversation_id: int, limit: int = 100
    ) -> list[WhatsAppMessage]:
        return self.repo.get_messages_for_conversation(conversation_id, limit=limit)

    def get_contact(self, wa_id: str) -> WhatsAppContact | None:
        return self.repo.get_contact_by_wa_id(wa_id)

    def get_conversation(self, conversation_id: int) -> WhatsAppConversation | None:
        return self.repo.get_conversation(conversation_id)

    # ── Procesamiento de webhook ─────────────────────────────────────────

    def process_webhook_payload(
        self,
        parsed: ParsedPayload,
        event_key: str,
        raw_payload_json: str,
    ) -> dict:
        """Procesa un payload ya parseado del webhook de Meta.

        Flujo:
        1. Guardar evento si es nuevo.
        2. Crear/actualizar contactos.
        3. Crear/recuperar conversación abierta.
        4. Guardar mensajes entrantes e incrementar contador.
        5. Procesar estados (sent/delivered/read/failed).

        Returns dict con resultados del procesamiento.
        """
        result: dict[str, Any] = {
            "event_saved": False,
            "event_id": None,
            "contacts_created": 0,
            "messages_saved": 0,
            "statuses_processed": 0,
            "ignored": False,
        }

        if not parsed.messages and not parsed.statuses:
            result["ignored"] = True
            return result

        phone_number_id = parsed.metadata.phone_number_id if parsed.metadata else ""
        business_account_id = parsed.metadata.business_account_id if parsed.metadata else ""

        event_type = "messages"
        if parsed.statuses and not parsed.messages:
            event_type = "statuses"

        event = self.repo.save_webhook_event_if_new(
            event_key=event_key,
            event_type=event_type,
            phone_number_id=phone_number_id or None,
            business_account_id=business_account_id or None,
            payload_json=raw_payload_json,
        )

        if event is None:
            result["ignored"] = True
            return result

        result["event_saved"] = True
        result["event_id"] = event.id

        try:
            self.repo.mark_webhook_event_processing(event.id)

            for contact_data in parsed.contacts:
                contact = self.repo.create_or_update_contact(
                    wa_id=contact_data.wa_id,
                    display_name=contact_data.profile_name,
                )
                result["contacts_created"] += 1

            for msg in parsed.messages:
                c_contact = self.repo.create_or_update_contact(
                    wa_id=msg.from_wa_id,
                )
                conversation = self.repo.create_or_get_open_conversation(
                    contact_id=c_contact.id,
                    phone_number_id=phone_number_id,
                    business_account_id=business_account_id,
                )
                saved = self.repo.save_inbound_message(
                    conversation_id=conversation.id,
                    message_type=msg.message_type,
                    wa_message_id=msg.message_id,
                    text_body=msg.text_body,
                    media_id=msg.media_id,
                    mime_type=msg.mime_type,
                    filename=msg.filename,
                    caption=msg.caption,
                    reply_to_message_id=msg.reply_to_message_id,
                    message_timestamp=msg.timestamp,
                    raw_payload_json=json.dumps(msg.raw, ensure_ascii=False) if msg.raw else None,
                )
                if saved is not None:
                    self.repo.increment_unread_count(conversation.id)
                    result["messages_saved"] += 1

            for st in parsed.statuses:
                self.repo.update_message_delivery_status(
                    wa_message_id=st.message_id,
                    delivery_status=st.status,
                    error_code=st.error_code,
                )
                result["statuses_processed"] += 1

            self.repo.mark_webhook_event_processed(event.id)

        except Exception as exc:
            logger.error("Error procesando webhook event %s: %s", event_key, exc)
            self.repo.mark_webhook_event_failed(event.id, str(exc)[:500])

        return result
