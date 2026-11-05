"""Persistencia SQLite del módulo WhatsApp."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from app.whatsapp.models import (
    WhatsAppContact,
    WhatsAppConversation,
    WhatsAppMessage,
    WhatsAppOutboxItem,
    WhatsAppWebhookEvent,
)

logger = logging.getLogger(__name__)

_DEFAULT_NOW = "1970-01-01T00:00:00"

_TABLE_DEFINITIONS: list[tuple[str, str, list[str]]] = [
    (
        "whatsapp_contacts",
        """CREATE TABLE IF NOT EXISTS whatsapp_contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wa_id TEXT NOT NULL,
            phone_number TEXT DEFAULT '',
            display_name TEXT DEFAULT '',
            client_id INTEGER,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        [
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_whatsapp_contacts_wa_id ON whatsapp_contacts(wa_id)",
            "CREATE INDEX IF NOT EXISTS idx_whatsapp_contacts_phone ON whatsapp_contacts(phone_number)",
            "CREATE INDEX IF NOT EXISTS idx_whatsapp_contacts_client ON whatsapp_contacts(client_id)",
        ],
    ),
    (
        "whatsapp_conversations",
        """CREATE TABLE IF NOT EXISTS whatsapp_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER NOT NULL,
            order_id INTEGER,
            phone_number_id TEXT DEFAULT '',
            business_account_id TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',
            assigned_to TEXT,
            unread_count INTEGER NOT NULL DEFAULT 0,
            last_message_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(contact_id) REFERENCES whatsapp_contacts(id)
        )""",
        [
            "CREATE INDEX IF NOT EXISTS idx_wa_conv_contact ON whatsapp_conversations(contact_id)",
            "CREATE INDEX IF NOT EXISTS idx_wa_conv_order ON whatsapp_conversations(order_id)",
            "CREATE INDEX IF NOT EXISTS idx_wa_conv_status ON whatsapp_conversations(status)",
            "CREATE INDEX IF NOT EXISTS idx_wa_conv_last_msg ON whatsapp_conversations(last_message_at)",
            "CREATE INDEX IF NOT EXISTS idx_wa_conv_phone_id ON whatsapp_conversations(phone_number_id)",
        ],
    ),
    (
        "whatsapp_messages",
        """CREATE TABLE IF NOT EXISTS whatsapp_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            whatsapp_message_id TEXT,
            conversation_id INTEGER NOT NULL,
            direction TEXT NOT NULL DEFAULT 'inbound',
            message_type TEXT NOT NULL DEFAULT 'text',
            text_body TEXT,
            media_id TEXT,
            media_path TEXT,
            mime_type TEXT,
            filename TEXT,
            caption TEXT,
            reply_to_message_id TEXT,
            delivery_status TEXT,
            error_code TEXT,
            message_timestamp TEXT,
            raw_payload_json TEXT,
            ai_processed INTEGER NOT NULL DEFAULT 0,
            intent TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(conversation_id) REFERENCES whatsapp_conversations(id)
        )""",
        [
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_wa_msg_meta_id ON whatsapp_messages(whatsapp_message_id)",
            "CREATE INDEX IF NOT EXISTS idx_wa_msg_conversation ON whatsapp_messages(conversation_id)",
            "CREATE INDEX IF NOT EXISTS idx_wa_msg_direction ON whatsapp_messages(direction)",
            "CREATE INDEX IF NOT EXISTS idx_wa_msg_delivery ON whatsapp_messages(delivery_status)",
            "CREATE INDEX IF NOT EXISTS idx_wa_msg_timestamp ON whatsapp_messages(message_timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_wa_msg_ai ON whatsapp_messages(ai_processed)",
            "CREATE INDEX IF NOT EXISTS idx_wa_msg_intent ON whatsapp_messages(intent)",
        ],
    ),
    (
        "whatsapp_webhook_events",
        """CREATE TABLE IF NOT EXISTS whatsapp_webhook_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT NOT NULL UNIQUE,
            event_type TEXT,
            phone_number_id TEXT,
            business_account_id TEXT,
            payload_json TEXT NOT NULL,
            processing_status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            received_at TEXT NOT NULL,
            processed_at TEXT
        )""",
        [
            "CREATE INDEX IF NOT EXISTS idx_wa_webhook_status ON whatsapp_webhook_events(processing_status)",
            "CREATE INDEX IF NOT EXISTS idx_wa_webhook_received ON whatsapp_webhook_events(received_at)",
            "CREATE INDEX IF NOT EXISTS idx_wa_webhook_phone ON whatsapp_webhook_events(phone_number_id)",
        ],
    ),
    (
        "whatsapp_outbox",
        """CREATE TABLE IF NOT EXISTS whatsapp_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER,
            recipient_wa_id TEXT NOT NULL,
            phone_number_id TEXT,
            message_type TEXT NOT NULL DEFAULT 'text',
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            sent_at TEXT,
            whatsapp_message_id TEXT,
            FOREIGN KEY(conversation_id) REFERENCES whatsapp_conversations(id)
        )""",
        [
            "CREATE INDEX IF NOT EXISTS idx_wa_outbox_status ON whatsapp_outbox(status)",
            "CREATE INDEX IF NOT EXISTS idx_wa_outbox_next_attempt ON whatsapp_outbox(next_attempt_at)",
            "CREATE INDEX IF NOT EXISTS idx_wa_outbox_conversation ON whatsapp_outbox(conversation_id)",
            "CREATE INDEX IF NOT EXISTS idx_wa_outbox_recipient ON whatsapp_outbox(recipient_wa_id)",
            "CREATE INDEX IF NOT EXISTS idx_wa_outbox_phone_id ON whatsapp_outbox(phone_number_id)",
        ],
    ),
]


_MIGRATIONS: list[tuple[str, str]] = [
    (
        "whatsapp_outbox_idempotency_key",
        "ALTER TABLE whatsapp_outbox ADD COLUMN idempotency_key TEXT NULL",
    ),
    (
        "whatsapp_outbox_worker_id",
        "ALTER TABLE whatsapp_outbox ADD COLUMN worker_id TEXT NULL",
    ),
    (
        "whatsapp_outbox_processing_started_at",
        "ALTER TABLE whatsapp_outbox ADD COLUMN processing_started_at TEXT NULL",
    ),
]


def _run_migrations(connection) -> None:
    for name, ddl in _MIGRATIONS:
        try:
            connection.execute(ddl)
        except Exception:
            pass
    try:
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_wa_outbox_idempotency "
            "ON whatsapp_outbox(idempotency_key) WHERE idempotency_key IS NOT NULL"
        )
    except Exception:
        pass
    connection.commit()


def create_whatsapp_tables(connection) -> None:
    for table_name, ddl, indexes in _TABLE_DEFINITIONS:
        connection.execute(ddl)
        for idx_ddl in indexes:
            try:
                connection.execute(idx_ddl)
            except Exception:
                pass
    _run_migrations(connection)
    connection.commit()


class WhatsAppRepository:
    def __init__(self, connection, lock: threading.Lock | None = None):
        self.conn = connection
        self._lock = lock or threading.Lock()

    # ── helpers internos ────────────────────────────────────────────────

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _row_to_contact(self, row: dict) -> WhatsAppContact:
        return WhatsAppContact(
            id=row["id"],
            wa_id=row["wa_id"],
            phone_number=row.get("phone_number") or "",
            display_name=row.get("display_name") or "",
            client_id=row.get("client_id"),
            first_seen_at=row.get("first_seen_at") or "",
            last_seen_at=row.get("last_seen_at") or "",
            created_at=row.get("created_at") or "",
            updated_at=row.get("updated_at") or "",
        )

    def _row_to_conversation(self, row: dict) -> WhatsAppConversation:
        return WhatsAppConversation(
            id=row["id"],
            contact_id=row["contact_id"],
            order_id=row.get("order_id"),
            phone_number_id=row.get("phone_number_id") or "",
            business_account_id=row.get("business_account_id") or "",
            status=row.get("status") or "open",
            assigned_to=row.get("assigned_to"),
            unread_count=row.get("unread_count") or 0,
            last_message_at=row.get("last_message_at"),
            created_at=row.get("created_at") or "",
            updated_at=row.get("updated_at") or "",
        )

    def _row_to_message(self, row: dict) -> WhatsAppMessage:
        return WhatsAppMessage(
            id=row["id"],
            whatsapp_message_id=row.get("whatsapp_message_id"),
            conversation_id=row["conversation_id"],
            direction=row.get("direction") or "inbound",
            message_type=row.get("message_type") or "text",
            text_body=row.get("text_body"),
            media_id=row.get("media_id"),
            media_path=row.get("media_path"),
            mime_type=row.get("mime_type"),
            filename=row.get("filename"),
            caption=row.get("caption"),
            reply_to_message_id=row.get("reply_to_message_id"),
            delivery_status=row.get("delivery_status"),
            error_code=row.get("error_code"),
            message_timestamp=row.get("message_timestamp"),
            raw_payload_json=row.get("raw_payload_json"),
            ai_processed=row.get("ai_processed") or 0,
            intent=row.get("intent"),
            created_at=row.get("created_at") or "",
            updated_at=row.get("updated_at") or "",
        )

    def _row_to_webhook_event(self, row: dict) -> WhatsAppWebhookEvent:
        return WhatsAppWebhookEvent(
            id=row["id"],
            event_key=row["event_key"],
            event_type=row.get("event_type"),
            phone_number_id=row.get("phone_number_id"),
            business_account_id=row.get("business_account_id"),
            payload_json=row.get("payload_json") or "",
            processing_status=row.get("processing_status") or "pending",
            attempts=row.get("attempts") or 0,
            last_error=row.get("last_error"),
            received_at=row.get("received_at") or "",
            processed_at=row.get("processed_at"),
        )

    def _row_to_outbox(self, row: dict) -> WhatsAppOutboxItem:
        return WhatsAppOutboxItem(
            id=row["id"],
            conversation_id=row.get("conversation_id"),
            recipient_wa_id=row["recipient_wa_id"],
            phone_number_id=row.get("phone_number_id"),
            message_type=row.get("message_type") or "text",
            payload_json=row.get("payload_json") or "",
            status=row.get("status") or "pending",
            attempts=row.get("attempts") or 0,
            next_attempt_at=row.get("next_attempt_at"),
            last_error=row.get("last_error"),
            created_at=row.get("created_at") or "",
            sent_at=row.get("sent_at"),
            whatsapp_message_id=row.get("whatsapp_message_id"),
            idempotency_key=row.get("idempotency_key"),
            worker_id=row.get("worker_id"),
            processing_started_at=row.get("processing_started_at"),
        )

    # ── Contactos ───────────────────────────────────────────────────────

    def create_or_update_contact(
        self,
        wa_id: str,
        phone_number: str = "",
        display_name: str = "",
    ) -> WhatsAppContact:
        now = self._now()
        with self._lock:
            existing = self.conn.execute(
                "SELECT * FROM whatsapp_contacts WHERE wa_id = ?", (wa_id,)
            ).fetchone()
            if existing:
                final_phone = phone_number if phone_number else existing["phone_number"] or ""
                final_name = display_name if display_name else existing["display_name"] or ""
                self.conn.execute(
                    """UPDATE whatsapp_contacts
                       SET phone_number = ?, display_name = ?,
                           last_seen_at = ?, updated_at = ?
                       WHERE id = ?""",
                    (final_phone, final_name, now, now, existing["id"]),
                )
                self.conn.commit()
                row = self.conn.execute(
                    "SELECT * FROM whatsapp_contacts WHERE id = ?",
                    (existing["id"],),
                ).fetchone()
                return self._row_to_contact(dict(row))
            self.conn.execute(
                """INSERT INTO whatsapp_contacts
                   (wa_id, phone_number, display_name, first_seen_at, last_seen_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (wa_id, phone_number, display_name, now, now, now, now),
            )
            self.conn.commit()
            row = self.conn.execute(
                "SELECT * FROM whatsapp_contacts WHERE wa_id = ?", (wa_id,)
            ).fetchone()
            return self._row_to_contact(dict(row))

    def get_contact_by_wa_id(self, wa_id: str) -> WhatsAppContact | None:
        row = self.conn.execute(
            "SELECT * FROM whatsapp_contacts WHERE wa_id = ?", (wa_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_contact(dict(row))

    def link_contact_to_client(self, contact_id: int, client_id: int) -> bool:
        now = self._now()
        with self._lock:
            self.conn.execute(
                "UPDATE whatsapp_contacts SET client_id = ?, updated_at = ? WHERE id = ?",
                (client_id, now, contact_id),
            )
            self.conn.commit()
            return self.conn.total_changes > 0

    # ── Conversaciones ──────────────────────────────────────────────────

    def create_or_get_open_conversation(
        self,
        contact_id: int,
        phone_number_id: str = "",
        business_account_id: str = "",
    ) -> WhatsAppConversation:
        with self._lock:
            row = self.conn.execute(
                """SELECT * FROM whatsapp_conversations
                   WHERE contact_id = ? AND status = 'open'""",
                (contact_id,),
            ).fetchone()
            if row:
                return self._row_to_conversation(dict(row))
            now = self._now()
            cursor = self.conn.execute(
                """INSERT INTO whatsapp_conversations
                   (contact_id, phone_number_id, business_account_id, status,
                    created_at, updated_at)
                   VALUES (?, ?, ?, 'open', ?, ?)""",
                (contact_id, phone_number_id, business_account_id, now, now),
            )
            self.conn.commit()
            row = self.conn.execute(
                "SELECT * FROM whatsapp_conversations WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            return self._row_to_conversation(dict(row))

    def get_conversation(self, conversation_id: int) -> WhatsAppConversation | None:
        row = self.conn.execute(
            "SELECT * FROM whatsapp_conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_conversation(dict(row))

    def list_conversations(self, limit: int = 200) -> list[dict[str, Any]]:
        """Devuelve conversaciones recientes con los datos necesarios para la bandeja."""
        rows = self.conn.execute(
            """SELECT c.*, ct.wa_id, ct.phone_number, ct.display_name,
                      (SELECT text_body FROM whatsapp_messages m
                       WHERE m.conversation_id = c.id
                       ORDER BY m.message_timestamp DESC, m.id DESC LIMIT 1) AS last_message
               FROM whatsapp_conversations c
               JOIN whatsapp_contacts ct ON ct.id = c.contact_id
               ORDER BY COALESCE(c.last_message_at, c.updated_at) DESC, c.id DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def link_conversation_to_order(
        self, conversation_id: int, order_id: int
    ) -> bool:
        now = self._now()
        with self._lock:
            self.conn.execute(
                "UPDATE whatsapp_conversations SET order_id = ?, updated_at = ? WHERE id = ?",
                (order_id, now, conversation_id),
            )
            self.conn.commit()
            return self.conn.total_changes > 0

    def update_conversation_status(
        self, conversation_id: int, new_status: str
    ) -> bool:
        now = self._now()
        with self._lock:
            self.conn.execute(
                "UPDATE whatsapp_conversations SET status = ?, updated_at = ? WHERE id = ?",
                (new_status, now, conversation_id),
            )
            self.conn.commit()
            return self.conn.total_changes > 0

    def increment_unread_count(self, conversation_id: int) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE whatsapp_conversations SET unread_count = unread_count + 1 WHERE id = ?",
                (conversation_id,),
            )
            self.conn.commit()

    def clear_unread_count(self, conversation_id: int) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE whatsapp_conversations SET unread_count = 0 WHERE id = ?",
                (conversation_id,),
            )
            self.conn.commit()

    # ── Mensajes ────────────────────────────────────────────────────────

    def save_inbound_message(
        self,
        conversation_id: int,
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
        raw_payload_json: str | None = None,
    ) -> WhatsAppMessage | None:
        if wa_message_id:
            existing = self.conn.execute(
                "SELECT id FROM whatsapp_messages WHERE whatsapp_message_id = ?",
                (wa_message_id,),
            ).fetchone()
            if existing:
                return None
        now = self._now()
        with self._lock:
            cursor = self.conn.execute(
                """INSERT INTO whatsapp_messages
                   (whatsapp_message_id, conversation_id, direction, message_type,
                    text_body, media_id, media_path, mime_type, filename, caption,
                    reply_to_message_id, message_timestamp, raw_payload_json,
                    created_at, updated_at)
                   VALUES (?, ?, 'inbound', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    wa_message_id,
                    conversation_id,
                    message_type,
                    text_body,
                    media_id,
                    media_path,
                    mime_type,
                    filename,
                    caption,
                    reply_to_message_id,
                    message_timestamp,
                    raw_payload_json,
                    now,
                    now,
                ),
            )
            self.conn.commit()
            row = self.conn.execute(
                "SELECT * FROM whatsapp_messages WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_message(dict(row))

    def create_outbound_message(
        self,
        conversation_id: int,
        message_type: str,
        text_body: str | None = None,
        wa_message_id: str | None = None,
        media_id: str | None = None,
        media_path: str | None = None,
        mime_type: str | None = None,
        filename: str | None = None,
        caption: str | None = None,
        delivery_status: str | None = None,
    ) -> WhatsAppMessage:
        now = self._now()
        with self._lock:
            cursor = self.conn.execute(
                """INSERT INTO whatsapp_messages
                   (whatsapp_message_id, conversation_id, direction, message_type,
                    text_body, media_id, media_path, mime_type, filename, caption,
                    delivery_status, created_at, updated_at)
                   VALUES (?, ?, 'outbound', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    wa_message_id, conversation_id, message_type,
                    text_body, media_id, media_path, mime_type, filename, caption,
                    delivery_status, now, now,
                ),
            )
            self.conn.commit()
            row = self.conn.execute(
                "SELECT * FROM whatsapp_messages WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            return self._row_to_message(dict(row))

    def update_outbound_message_after_send(
        self,
        conversation_id: int,
        wa_message_id: str,
        message_type: str,
        text_body: str | None = None,
        media_id: str | None = None,
        mime_type: str | None = None,
        filename: str | None = None,
        caption: str | None = None,
        delivery_status: str = "sent",
    ) -> WhatsAppMessage:
        now = self._now()
        existing = self.conn.execute(
            "SELECT id FROM whatsapp_messages WHERE whatsapp_message_id = ?",
            (wa_message_id,),
        ).fetchone()
        with self._lock:
            if existing:
                self.conn.execute(
                    """UPDATE whatsapp_messages
                       SET delivery_status = ?, error_code = NULL, updated_at = ?
                       WHERE id = ?""",
                    (delivery_status, now, existing["id"]),
                )
                self.conn.commit()
                row = self.conn.execute(
                    "SELECT * FROM whatsapp_messages WHERE id = ?",
                    (existing["id"],),
                ).fetchone()
                return self._row_to_message(dict(row))
            cursor = self.conn.execute(
                """INSERT INTO whatsapp_messages
                   (whatsapp_message_id, conversation_id, direction, message_type,
                    text_body, media_id, mime_type, filename, caption,
                    delivery_status, created_at, updated_at)
                   VALUES (?, ?, 'outbound', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    wa_message_id, conversation_id, message_type,
                    text_body, media_id, mime_type, filename, caption,
                    delivery_status, now, now,
                ),
            )
            self.conn.commit()
            row = self.conn.execute(
                "SELECT * FROM whatsapp_messages WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            return self._row_to_message(dict(row))

    def update_message_delivery_status(
        self,
        wa_message_id: str,
        delivery_status: str,
        error_code: str | None = None,
    ) -> bool:
        now = self._now()
        with self._lock:
            self.conn.execute(
                """UPDATE whatsapp_messages
                   SET delivery_status = ?, error_code = ?, updated_at = ?
                   WHERE whatsapp_message_id = ?""",
                (delivery_status, error_code, now, wa_message_id),
            )
            self.conn.commit()
            return self.conn.total_changes > 0

    def get_messages_for_conversation(
        self, conversation_id: int, limit: int = 100
    ) -> list[WhatsAppMessage]:
        rows = self.conn.execute(
            """SELECT * FROM whatsapp_messages
               WHERE conversation_id = ?
               ORDER BY message_timestamp ASC, id ASC
               LIMIT ?""",
            (conversation_id, limit),
        ).fetchall()
        return [self._row_to_message(dict(row)) for row in rows]

    # ── Webhook events ──────────────────────────────────────────────────

    def save_webhook_event_if_new(
        self,
        event_key: str,
        event_type: str | None = None,
        phone_number_id: str | None = None,
        business_account_id: str | None = None,
        payload_json: str | dict | None = None,
    ) -> WhatsAppWebhookEvent | None:
        existing = self.conn.execute(
            "SELECT id FROM whatsapp_webhook_events WHERE event_key = ?",
            (event_key,),
        ).fetchone()
        if existing:
            return None
        now = self._now()
        if payload_json is None:
            payload_json = "{}"
        elif not isinstance(payload_json, str):
            payload_json = json.dumps(payload_json, ensure_ascii=False)
        with self._lock:
            cursor = self.conn.execute(
                """INSERT INTO whatsapp_webhook_events
                   (event_key, event_type, phone_number_id, business_account_id,
                    payload_json, processing_status, received_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    event_key,
                    event_type,
                    phone_number_id,
                    business_account_id,
                    payload_json,
                    now,
                ),
            )
            self.conn.commit()
            row = self.conn.execute(
                "SELECT * FROM whatsapp_webhook_events WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_webhook_event(dict(row))

    def mark_webhook_event_processed(self, event_id: int) -> bool:
        now = self._now()
        with self._lock:
            self.conn.execute(
                "UPDATE whatsapp_webhook_events SET processing_status = 'processed', processed_at = ? WHERE id = ?",
                (now, event_id),
            )
            self.conn.commit()
            return self.conn.total_changes > 0

    def mark_webhook_event_failed(
        self, event_id: int, error: str
    ) -> bool:
        with self._lock:
            self.conn.execute(
                """UPDATE whatsapp_webhook_events
                   SET processing_status = 'failed', attempts = attempts + 1,
                       last_error = ?
                   WHERE id = ?""",
                (error, event_id),
            )
            self.conn.commit()
            return self.conn.total_changes > 0

    def mark_webhook_event_processing(self, event_id: int) -> bool:
        with self._lock:
            self.conn.execute(
                "UPDATE whatsapp_webhook_events SET processing_status = 'processing' WHERE id = ?",
                (event_id,),
            )
            self.conn.commit()
            return self.conn.total_changes > 0

    def mark_webhook_event_ignored(self, event_id: int) -> bool:
        now = self._now()
        with self._lock:
            self.conn.execute(
                "UPDATE whatsapp_webhook_events SET processing_status = 'ignored', processed_at = ? WHERE id = ?",
                (now, event_id),
            )
            self.conn.commit()
            return self.conn.total_changes > 0

    def get_pending_webhook_events(self, limit: int = 50) -> list[WhatsAppWebhookEvent]:
        now = self._now()
        rows = self.conn.execute(
            """SELECT * FROM whatsapp_webhook_events
               WHERE processing_status = 'pending'
                 AND (processed_at IS NULL)
               ORDER BY received_at ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [self._row_to_webhook_event(dict(row)) for row in rows]

    def retry_failed_webhook_event(self, event_id: int) -> bool:
        with self._lock:
            self.conn.execute(
                "UPDATE whatsapp_webhook_events SET processing_status = 'pending', last_error = NULL WHERE id = ?",
                (event_id,),
            )
            self.conn.commit()
            return self.conn.total_changes > 0

    # ── Outbox ──────────────────────────────────────────────────────────

    def enqueue_outbound_message(
        self,
        recipient_wa_id: str,
        message_type: str,
        payload_json: str | dict,
        conversation_id: int | None = None,
        phone_number_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> WhatsAppOutboxItem:
        now = self._now()
        if not isinstance(payload_json, str):
            payload_json = json.dumps(payload_json, ensure_ascii=False)
        with self._lock:
            if idempotency_key:
                existing = self.conn.execute(
                    "SELECT * FROM whatsapp_outbox WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing:
                    return self._row_to_outbox(dict(existing))
            cursor = self.conn.execute(
                """INSERT INTO whatsapp_outbox
                   (conversation_id, recipient_wa_id, phone_number_id,
                    message_type, payload_json, status, created_at, idempotency_key)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (
                    conversation_id,
                    recipient_wa_id,
                    phone_number_id,
                    message_type,
                    payload_json,
                    now,
                    idempotency_key,
                ),
            )
            self.conn.commit()
            row = self.conn.execute(
                "SELECT * FROM whatsapp_outbox WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            return self._row_to_outbox(dict(row))

    def get_pending_outbox_items(
        self, limit: int = 50
    ) -> list[WhatsAppOutboxItem]:
        now = self._now()
        rows = self.conn.execute(
            """SELECT * FROM whatsapp_outbox
               WHERE status = 'pending'
                 AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
               ORDER BY created_at ASC
               LIMIT ?""",
            (now, limit),
        ).fetchall()
        return [self._row_to_outbox(dict(row)) for row in rows]

    def claim_pending_outbox_items(
        self,
        worker_id: str,
        limit: int = 20,
        processing_timeout_seconds: int = 300,
    ) -> list[WhatsAppOutboxItem]:
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat(timespec="seconds")
        stale_cutoff = (
            now - __import__("datetime").timedelta(seconds=processing_timeout_seconds)
        ).isoformat(timespec="seconds")
        with self._lock:
            fresh_ids = [
                r[0] for r in self.conn.execute(
                    """SELECT id FROM whatsapp_outbox
                       WHERE status = 'pending'
                         AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                       ORDER BY created_at ASC
                       LIMIT ?""",
                    (now_iso, limit),
                ).fetchall()
            ]
            stale_ids = [
                r[0] for r in self.conn.execute(
                    """SELECT id FROM whatsapp_outbox
                       WHERE status = 'processing'
                         AND processing_started_at IS NOT NULL
                         AND processing_started_at < ?
                       ORDER BY created_at ASC
                       LIMIT ?""",
                    (stale_cutoff, limit),
                ).fetchall()
            ]
            all_ids = fresh_ids + stale_ids
            for oid in all_ids:
                self.conn.execute(
                    """UPDATE whatsapp_outbox
                       SET status = 'processing', worker_id = ?,
                           processing_started_at = ?,
                           attempts = attempts + 1
                       WHERE id = ?""",
                    (worker_id, now_iso, oid),
                )
            self.conn.commit()
            if not all_ids:
                return []
            placeholders = ",".join("?" for _ in all_ids)
            rows = self.conn.execute(
                f"""SELECT * FROM whatsapp_outbox
                    WHERE id IN ({placeholders})
                    ORDER BY created_at ASC""",
                all_ids,
            ).fetchall()
            return [self._row_to_outbox(dict(row)) for row in rows]

    def mark_outbox_sent(
        self,
        outbox_id: int,
        wa_message_id: str | None = None,
    ) -> bool:
        now = self._now()
        with self._lock:
            self.conn.execute(
                """UPDATE whatsapp_outbox
                   SET status = 'sent', sent_at = ?, worker_id = NULL,
                       processing_started_at = NULL,
                       whatsapp_message_id = COALESCE(?, whatsapp_message_id)
                   WHERE id = ?""",
                (now, wa_message_id, outbox_id),
            )
            self.conn.commit()
            return self.conn.total_changes > 0

    def release_outbox_for_retry(
        self,
        outbox_id: int,
        error: str,
        retry_after_seconds: int = 60,
    ) -> bool:
        now = datetime.now(timezone.utc)
        next_attempt = (
            now + __import__("datetime").timedelta(seconds=retry_after_seconds)
        ).isoformat(timespec="seconds")
        with self._lock:
            self.conn.execute(
                """UPDATE whatsapp_outbox
                   SET status = 'pending', worker_id = NULL,
                       processing_started_at = NULL,
                       last_error = ?, next_attempt_at = ?
                   WHERE id = ?""",
                (error, next_attempt, outbox_id),
            )
            self.conn.commit()
            return self.conn.total_changes > 0

    def mark_outbox_failed(
        self,
        outbox_id: int,
        error: str,
    ) -> bool:
        now = self._now()
        with self._lock:
            self.conn.execute(
                """UPDATE whatsapp_outbox
                   SET status = 'failed', worker_id = NULL,
                       processing_started_at = NULL,
                       last_error = ?, sent_at = ?
                   WHERE id = ?""",
                (error, now, outbox_id),
            )
            self.conn.commit()
            return self.conn.total_changes > 0

    def recover_stale_processing_items(
        self, processing_timeout_seconds: int = 300
    ) -> int:
        cutoff = (
            datetime.now(timezone.utc)
            - __import__("datetime").timedelta(seconds=processing_timeout_seconds)
        ).isoformat(timespec="seconds")
        with self._lock:
            stale_ids = [
                r[0] for r in self.conn.execute(
                    """SELECT id FROM whatsapp_outbox
                       WHERE status = 'processing'
                         AND processing_started_at IS NOT NULL
                         AND processing_started_at < ?""",
                    (cutoff,),
                ).fetchall()
            ]
            for oid in stale_ids:
                self.conn.execute(
                    """UPDATE whatsapp_outbox
                       SET status = 'pending', worker_id = NULL,
                           processing_started_at = NULL,
                           last_error = 'recovered from stale processing',
                           next_attempt_at = ?
                       WHERE id = ?""",
                    (self._now(), oid),
                )
            self.conn.commit()
            return len(stale_ids)

    def cancel_outbox_item(self, outbox_id: int) -> bool:
        with self._lock:
            row = self.conn.execute(
                "SELECT status FROM whatsapp_outbox WHERE id = ?", (outbox_id,)
            ).fetchone()
            if row is None:
                return False
            if row["status"] in ("sent", "failed", "cancelled"):
                return False
            self.conn.execute(
                "UPDATE whatsapp_outbox SET status = 'cancelled', worker_id = NULL, processing_started_at = NULL WHERE id = ?",
                (outbox_id,),
            )
            self.conn.commit()
            return self.conn.total_changes > 0
