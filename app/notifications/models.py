"""Modelos de datos para el sistema de notificaciones."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NotificationEvent:
    event_uuid: str
    event_type: str
    priority: str
    title: str
    message: str
    entity_type: str | None = None
    entity_id: int | None = None
    payload_json: str = "{}"
    created_at: str = ""
    processed: bool = False


@dataclass
class OutboxMessage:
    id: int
    event_uuid: str
    channel: str
    recipient_id: str | None = None
    status: str = "pending"
    attempts: int = 0
    last_error: str | None = None
    next_attempt_at: str | None = None
    sent_at: str | None = None
    created_at: str = ""


@dataclass
class MobileDevice:
    id: int
    push_token: str
    platform: str
    device_name: str = ""
    user_id: int | None = None
    active: bool = True
    last_seen_at: str = ""
    created_at: str = ""
