"""Parser de payloads de webhook de Meta WhatsApp Business API.

Todas las funciones son puras: no escriben en base de datos, no tienen
efectos secundarios. Solamente transforman el payload JSON de Meta en
estructuras internas.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from app.whatsapp.models import (
    ParsedContact,
    ParsedMessage,
    ParsedMetadata,
    ParsedPayload,
    ParsedStatus,
)


def extract_metadata(entry: dict[str, Any]) -> ParsedMetadata | None:
    """Extrae metadatos de un entry del webhook."""
    changes = entry.get("changes", [])
    if not changes:
        return None
    value = changes[0].get("value", {})
    metadata = value.get("metadata", {})
    if not metadata:
        return None
    return ParsedMetadata(
        phone_number_id=metadata.get("phone_number_id", ""),
        business_account_id=metadata.get("business_account_id", ""),
        display_phone_number=metadata.get("display_phone_number", ""),
    )


def extract_contacts(entry: dict[str, Any]) -> list[ParsedContact]:
    """Extrae los contactos involucrados en un entry del webhook."""
    changes = entry.get("changes", [])
    if not changes:
        return []
    value = changes[0].get("value", {})
    raw_contacts = value.get("contacts", [])
    result = []
    for raw in raw_contacts:
        result.append(
            ParsedContact(
                wa_id=raw.get("wa_id", ""),
                profile_name=raw.get("profile", {}).get("name", ""),
            )
        )
    return result


def extract_messages(entry: dict[str, Any]) -> list[ParsedMessage]:
    """Extrae los mensajes de un entry del webhook.

    Soporta: text, image, sticker, video, audio, voice, document,
    location, contacts, reaction, interactive, y cualquier tipo
    desconocido.
    """
    changes = entry.get("changes", [])
    if not changes:
        return []
    value = changes[0].get("value", {})
    raw_messages = value.get("messages", [])
    result = []
    for raw in raw_messages:
        msg_type = raw.get("type", "unknown")
        parsed = ParsedMessage(
            message_id=raw.get("id", ""),
            from_wa_id=raw.get("from", ""),
            timestamp=raw.get("timestamp", ""),
            message_type=msg_type,
            raw=raw,
        )

        text = raw.get("text")
        if text:
            parsed.text_body = text.get("body", "")

        context = raw.get("context")
        if context:
            parsed.context_wa_id = context.get("from", "")
            parsed.reply_to_message_id = context.get("id", "")

        image = raw.get("image")
        if image:
            parsed.media_id = image.get("id", "")
            parsed.mime_type = image.get("mime_type", "")
            parsed.caption = image.get("caption", "")
            parsed.filename = image.get("filename", "")

        sticker = raw.get("sticker")
        if sticker:
            parsed.media_id = sticker.get("id", "")
            parsed.mime_type = sticker.get("mime_type", "")

        video = raw.get("video")
        if video:
            parsed.media_id = video.get("id", "")
            parsed.mime_type = video.get("mime_type", "")
            parsed.caption = video.get("caption", "")
            parsed.filename = video.get("filename", "")

        audio = raw.get("audio")
        if audio:
            parsed.media_id = audio.get("id", "")
            parsed.mime_type = audio.get("mime_type", "")

        voice = raw.get("voice")
        if voice:
            parsed.media_id = voice.get("id", "")
            parsed.mime_type = voice.get("mime_type", "")

        document = raw.get("document")
        if document:
            parsed.media_id = document.get("id", "")
            parsed.mime_type = document.get("mime_type", "")
            parsed.filename = document.get("filename", "")
            parsed.caption = document.get("caption", "")

        location = raw.get("location")
        if location:
            try:
                parsed.latitude = float(location.get("latitude", 0))
                parsed.longitude = float(location.get("longitude", 0))
            except (ValueError, TypeError):
                pass

        contacts_list = raw.get("contacts")
        if contacts_list:
            pass

        reaction = raw.get("reaction")
        if reaction:
            parsed.reaction_emoji = reaction.get("emoji", "")
            parsed.reaction_message_id = reaction.get("message_id", "")

        interactive = raw.get("interactive")
        if interactive:
            parsed.interactive_type = interactive.get("type", "")
            button_reply = interactive.get("button_reply")
            if button_reply:
                parsed.interactive_button_reply = button_reply
            list_reply = interactive.get("list_reply")
            if list_reply:
                parsed.interactive_list_reply = list_reply

        result.append(parsed)

    return result


def extract_status_updates(entry: dict[str, Any]) -> list[ParsedStatus]:
    """Extrae actualizaciones de estado de los mensajes."""
    changes = entry.get("changes", [])
    if not changes:
        return []
    value = changes[0].get("value", {})
    raw_statuses = value.get("statuses", [])
    result = []
    for raw in raw_statuses:
        error = raw.get("errors", [{}])[0] if raw.get("errors") else {}
        result.append(
            ParsedStatus(
                message_id=raw.get("id", ""),
                status=raw.get("status", ""),
                timestamp=raw.get("timestamp", ""),
                recipient_wa_id=raw.get("recipient_id", ""),
                pricing_model=raw.get("pricing", {}).get("pricing_model"),
                billing_category=raw.get("pricing", {}).get("category"),
                error_code=error.get("code"),
                error_title=error.get("title"),
            )
        )
    return result


def build_event_key(entry: dict[str, Any]) -> str:
    """Construye una clave única para un evento del webhook.

    La clave se basa en message_id + timestamp para mensajes,
    o en id + status + timestamp para actualizaciones de estado.
    """
    changes = entry.get("changes", [])
    if not changes:
        return ""
    value = changes[0].get("value", {})

    messages = value.get("messages", [])
    if messages:
        msg = messages[0]
        raw = f"msg:{msg.get('id', '')}:{msg.get('timestamp', '')}"
        return hashlib.sha256(raw.encode()).hexdigest()

    statuses = value.get("statuses", [])
    if statuses:
        st = statuses[0]
        raw = f"status:{st.get('id', '')}:{st.get('status', '')}:{st.get('timestamp', '')}"
        return hashlib.sha256(raw.encode()).hexdigest()

    fallback = json.dumps(entry, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(fallback.encode()).hexdigest()


def parse_payload(
    raw_body: str | bytes | dict[str, Any],
) -> ParsedPayload:
    """Parsea un payload completo del webhook de Meta.

    Tolerante a payloads sin mensajes, con estados, campos
    desconocidos, mensajes no soportados y estructuras incompletas.
    """
    if isinstance(raw_body, (str, bytes)):
        payload = json.loads(raw_body) if isinstance(raw_body, str) else json.loads(raw_body.decode("utf-8"))
    else:
        payload = raw_body

    result = ParsedPayload(raw=payload)

    entries = payload.get("entry", [])

    for entry in entries:
        metadata = extract_metadata(entry)
        if metadata is not None:
            result.metadata = metadata

        contacts = extract_contacts(entry)
        result.contacts.extend(contacts)

        messages = extract_messages(entry)
        result.messages.extend(messages)

        statuses = extract_status_updates(entry)
        result.statuses.extend(statuses)

    return result


def verify_signature(
    raw_body: bytes,
    signature_header: str,
    app_secret: str,
) -> bool:
    """Verifica la firma SHA-256 del webhook (Meta envía SHA256)."""
    if not signature_header:
        return False
    expected = "sha256=" + hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)
