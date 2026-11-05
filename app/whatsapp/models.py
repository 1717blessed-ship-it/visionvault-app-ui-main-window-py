"""Modelos de datos para WhatsApp Business."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class WhatsAppSendResult:
    success: bool = False
    http_status: int = 0
    whatsapp_message_id: str | None = None
    response_json: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    retry_after_seconds: int | None = None


@dataclass
class WhatsAppContact:
    id: int | None = None
    wa_id: str = ""
    phone_number: str = ""
    display_name: str = ""
    client_id: int | None = None
    first_seen_at: str = ""
    last_seen_at: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class WhatsAppConversation:
    id: int | None = None
    contact_id: int = 0
    order_id: int | None = None
    phone_number_id: str = ""
    business_account_id: str = ""
    status: str = "open"
    assigned_to: str | None = None
    unread_count: int = 0
    last_message_at: str | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class WhatsAppMessage:
    id: int | None = None
    whatsapp_message_id: str | None = None
    conversation_id: int = 0
    direction: str = "inbound"
    message_type: str = "text"
    text_body: str | None = None
    media_id: str | None = None
    media_path: str | None = None
    mime_type: str | None = None
    filename: str | None = None
    caption: str | None = None
    reply_to_message_id: str | None = None
    delivery_status: str | None = None
    error_code: str | None = None
    message_timestamp: str | None = None
    raw_payload_json: str | None = None
    ai_processed: int = 0
    intent: str | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class WhatsAppWebhookEvent:
    id: int | None = None
    event_key: str = ""
    event_type: str | None = None
    phone_number_id: str | None = None
    business_account_id: str | None = None
    payload_json: str = ""
    processing_status: str = "pending"
    attempts: int = 0
    last_error: str | None = None
    received_at: str = ""
    processed_at: str | None = None


@dataclass
class WhatsAppOutboxItem:
    id: int | None = None
    conversation_id: int | None = None
    recipient_wa_id: str = ""
    phone_number_id: str | None = None
    message_type: str = "text"
    payload_json: str = ""
    status: str = "pending"
    attempts: int = 0
    next_attempt_at: str | None = None
    last_error: str | None = None
    created_at: str = ""
    sent_at: str | None = None
    whatsapp_message_id: str | None = None
    idempotency_key: str | None = None
    worker_id: str | None = None
    processing_started_at: str | None = None


# ── Estructuras internas del parser ──────────────────────────────────────


@dataclass
class ParsedMetadata:
    phone_number_id: str = ""
    business_account_id: str = ""
    display_phone_number: str = ""


@dataclass
class ParsedContact:
    wa_id: str = ""
    profile_name: str = ""


@dataclass
class ParsedMessage:
    message_id: str = ""
    from_wa_id: str = ""
    timestamp: str = ""
    message_type: str = "unknown"
    text_body: str | None = None
    media_id: str | None = None
    media_path: str | None = None
    mime_type: str | None = None
    filename: str | None = None
    caption: str | None = None
    reply_to_message_id: str | None = None
    context_wa_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    reaction_emoji: str | None = None
    reaction_message_id: str | None = None
    interactive_type: str | None = None
    interactive_button_reply: dict[str, Any] | None = None
    interactive_list_reply: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedStatus:
    message_id: str = ""
    status: str = ""
    timestamp: str = ""
    recipient_wa_id: str = ""
    pricing_model: str | None = None
    billing_category: str | None = None
    error_code: str | None = None
    error_title: str | None = None


@dataclass
class ParsedPayload:
    metadata: ParsedMetadata | None = None
    contacts: list[ParsedContact] = field(default_factory=list)
    messages: list[ParsedMessage] = field(default_factory=list)
    statuses: list[ParsedStatus] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
