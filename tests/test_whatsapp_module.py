"""Tests del módulo WhatsApp de Doccione Studio."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from app.whatsapp.config import WhatsAppConfig, load_config, is_enabled, _load_dotenv
from app.whatsapp.repository import WhatsAppRepository, create_whatsapp_tables
from app.whatsapp.service import WhatsAppService
from app.whatsapp.webhook_parser import (
    build_event_key,
    extract_contacts,
    extract_messages,
    extract_metadata,
    extract_status_updates,
    parse_payload,
    verify_signature,
)
from app.whatsapp.models import (
    ParsedContact,
    ParsedMessage,
    ParsedMetadata,
    ParsedStatus,
)


def _make_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    create_whatsapp_tables(conn)
    return conn


# ═══════════════════════════════════════════════════════════════════════
# Tablas
# ═══════════════════════════════════════════════════════════════════════


class TestTableCreation(unittest.TestCase):
    def test_all_tables_created(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        create_whatsapp_tables(conn)
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected = {
            "whatsapp_contacts",
            "whatsapp_conversations",
            "whatsapp_messages",
            "whatsapp_webhook_events",
            "whatsapp_outbox",
        }
        self.assertTrue(expected.issubset(tables), f"Faltan: {expected - tables}")

    def test_tables_idempotent(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        create_whatsapp_tables(conn)
        create_whatsapp_tables(conn)
        create_whatsapp_tables(conn)
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        self.assertIn("whatsapp_contacts", tables)

    def test_migration_on_existing_db(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY)")
        conn.commit()
        create_whatsapp_tables(conn)
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        self.assertIn("whatsapp_contacts", tables)
        self.assertIn("orders", tables)


# ═══════════════════════════════════════════════════════════════════════
# Contactos
# ═══════════════════════════════════════════════════════════════════════


class TestContactRepository(unittest.TestCase):
    def setUp(self):
        self.conn = _make_connection()
        self.repo = WhatsAppRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_create_contact(self):
        contact = self.repo.create_or_update_contact(
            wa_id="123456", phone_number="+5491112345678", display_name="Juan Pérez"
        )
        self.assertIsNotNone(contact.id)
        self.assertEqual(contact.wa_id, "123456")
        self.assertEqual(contact.phone_number, "+5491112345678")
        self.assertEqual(contact.display_name, "Juan Pérez")

    def test_update_contact_name(self):
        c1 = self.repo.create_or_update_contact(
            wa_id="123456", phone_number="+5491112345678", display_name="Juan"
        )
        c2 = self.repo.create_or_update_contact(
            wa_id="123456", phone_number="+5491112345678", display_name="Juan Pérez"
        )
        self.assertEqual(c1.id, c2.id)
        self.assertEqual(c2.display_name, "Juan Pérez")

    def test_contact_duplicate(self):
        c1 = self.repo.create_or_update_contact(wa_id="dup", display_name="A")
        c2 = self.repo.create_or_update_contact(wa_id="dup", display_name="B")
        self.assertEqual(c1.id, c2.id)
        count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM whatsapp_contacts"
        ).fetchone()["cnt"]
        self.assertEqual(count, 1)

    def test_get_contact_by_wa_id(self):
        self.repo.create_or_update_contact(wa_id="getme", display_name="Find")
        found = self.repo.get_contact_by_wa_id("getme")
        self.assertIsNotNone(found)
        self.assertEqual(found.display_name, "Find")

    def test_get_contact_not_found(self):
        self.assertIsNone(self.repo.get_contact_by_wa_id("nonexistent"))

    def test_link_contact_to_client(self):
        contact = self.repo.create_or_update_contact(wa_id="client_link")
        ok = self.repo.link_contact_to_client(contact.id, 42)
        self.assertTrue(ok)
        updated = self.repo.get_contact_by_wa_id("client_link")
        self.assertEqual(updated.client_id, 42)


# ═══════════════════════════════════════════════════════════════════════
# Conversaciones
# ═══════════════════════════════════════════════════════════════════════


class TestConversationRepository(unittest.TestCase):
    def setUp(self):
        self.conn = _make_connection()
        self.repo = WhatsAppRepository(self.conn)
        self.contact = self.repo.create_or_update_contact(
            wa_id="conv_test", display_name="Conv"
        )

    def tearDown(self):
        self.conn.close()

    def test_create_open_conversation(self):
        conv = self.repo.create_or_get_open_conversation(
            contact_id=self.contact.id,
            phone_number_id="phone_123",
            business_account_id="biz_abc",
        )
        self.assertIsNotNone(conv.id)
        self.assertEqual(conv.status, "open")
        self.assertEqual(conv.phone_number_id, "phone_123")

    def test_reuse_open_conversation(self):
        c1 = self.repo.create_or_get_open_conversation(self.contact.id)
        c2 = self.repo.create_or_get_open_conversation(self.contact.id)
        self.assertEqual(c1.id, c2.id)
        count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM whatsapp_conversations"
        ).fetchone()["cnt"]
        self.assertEqual(count, 1)

    def test_new_conversation_after_closing(self):
        c1 = self.repo.create_or_get_open_conversation(self.contact.id)
        self.repo.update_conversation_status(c1.id, "resolved")
        c2 = self.repo.create_or_get_open_conversation(self.contact.id)
        self.assertNotEqual(c1.id, c2.id)
        self.assertEqual(c2.status, "open")

    def test_link_conversation_to_order(self):
        conv = self.repo.create_or_get_open_conversation(self.contact.id)
        ok = self.repo.link_conversation_to_order(conv.id, 99)
        self.assertTrue(ok)
        updated = self.repo.get_conversation(conv.id)
        self.assertEqual(updated.order_id, 99)

    def test_update_conversation_status(self):
        conv = self.repo.create_or_get_open_conversation(self.contact.id)
        self.repo.update_conversation_status(conv.id, "archived")
        updated = self.repo.get_conversation(conv.id)
        self.assertEqual(updated.status, "archived")

    def test_increment_unread_count(self):
        conv = self.repo.create_or_get_open_conversation(self.contact.id)
        self.repo.increment_unread_count(conv.id)
        self.repo.increment_unread_count(conv.id)
        updated = self.repo.get_conversation(conv.id)
        self.assertEqual(updated.unread_count, 2)

    def test_clear_unread_count(self):
        conv = self.repo.create_or_get_open_conversation(self.contact.id)
        self.repo.increment_unread_count(conv.id)
        self.repo.increment_unread_count(conv.id)
        self.repo.clear_unread_count(conv.id)
        updated = self.repo.get_conversation(conv.id)
        self.assertEqual(updated.unread_count, 0)


# ═══════════════════════════════════════════════════════════════════════
# Mensajes
# ═══════════════════════════════════════════════════════════════════════


class TestMessageRepository(unittest.TestCase):
    def setUp(self):
        self.conn = _make_connection()
        self.repo = WhatsAppRepository(self.conn)
        self.contact = self.repo.create_or_update_contact(
            wa_id="msg_test", display_name="Msg"
        )
        self.conv = self.repo.create_or_get_open_conversation(self.contact.id)

    def tearDown(self):
        self.conn.close()

    def test_save_inbound_text(self):
        msg = self.repo.save_inbound_message(
            conversation_id=self.conv.id,
            message_type="text",
            wa_message_id="wa_msg_1",
            text_body="Hola, quiero un sticker",
        )
        self.assertIsNotNone(msg)
        self.assertEqual(msg.whatsapp_message_id, "wa_msg_1")
        self.assertEqual(msg.text_body, "Hola, quiero un sticker")
        self.assertEqual(msg.direction, "inbound")

    def test_save_inbound_image(self):
        msg = self.repo.save_inbound_message(
            conversation_id=self.conv.id,
            message_type="image",
            wa_message_id="wa_img_1",
            media_id="media_abc",
            mime_type="image/jpeg",
            caption="Foto de muestra",
        )
        self.assertIsNotNone(msg)
        self.assertEqual(msg.message_type, "image")
        self.assertEqual(msg.media_id, "media_abc")
        self.assertEqual(msg.caption, "Foto de muestra")

    def test_save_inbound_document(self):
        msg = self.repo.save_inbound_message(
            conversation_id=self.conv.id,
            message_type="document",
            wa_message_id="wa_doc_1",
            media_id="doc_xyz",
            filename="presupuesto.pdf",
            mime_type="application/pdf",
        )
        self.assertIsNotNone(msg)
        self.assertEqual(msg.message_type, "document")
        self.assertEqual(msg.filename, "presupuesto.pdf")

    def test_duplicate_message_id(self):
        self.repo.save_inbound_message(
            conversation_id=self.conv.id,
            message_type="text",
            wa_message_id="dup_msg",
            text_body="Primero",
        )
        dup = self.repo.save_inbound_message(
            conversation_id=self.conv.id,
            message_type="text",
            wa_message_id="dup_msg",
            text_body="Segundo",
        )
        self.assertIsNone(dup)
        count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM whatsapp_messages"
        ).fetchone()["cnt"]
        self.assertEqual(count, 1)

    def test_unknown_message_type(self):
        msg = self.repo.save_inbound_message(
            conversation_id=self.conv.id,
            message_type="unknown",
            wa_message_id="wa_unk",
        )
        self.assertIsNotNone(msg)
        self.assertEqual(msg.message_type, "unknown")

    def test_create_outbound_message(self):
        msg = self.repo.create_outbound_message(
            conversation_id=self.conv.id,
            message_type="text",
            text_body="Gracias por tu consulta",
        )
        self.assertIsNotNone(msg)
        self.assertEqual(msg.direction, "outbound")
        self.assertEqual(msg.text_body, "Gracias por tu consulta")

    def test_get_messages_for_conversation(self):
        self.repo.save_inbound_message(
            conversation_id=self.conv.id,
            message_type="text",
            wa_message_id="m1",
            text_body="Primero",
            message_timestamp="2026-01-01T10:00:00",
        )
        self.repo.save_inbound_message(
            conversation_id=self.conv.id,
            message_type="text",
            wa_message_id="m2",
            text_body="Segundo",
            message_timestamp="2026-01-01T10:01:00",
        )
        msgs = self.repo.get_messages_for_conversation(self.conv.id)
        self.assertEqual(len(msgs), 2)

    def test_update_message_delivery_status(self):
        self.repo.save_inbound_message(
            conversation_id=self.conv.id,
            message_type="text",
            wa_message_id="delivery_test",
        )
        ok = self.repo.update_message_delivery_status(
            wa_message_id="delivery_test",
            delivery_status="read",
        )
        self.assertTrue(ok)


# ═══════════════════════════════════════════════════════════════════════
# Webhook events
# ═══════════════════════════════════════════════════════════════════════


class TestWebhookEventRepository(unittest.TestCase):
    def setUp(self):
        self.conn = _make_connection()
        self.repo = WhatsAppRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_save_new_event(self):
        event = self.repo.save_webhook_event_if_new(
            event_key="key_1",
            event_type="messages",
            phone_number_id="phone_1",
            payload_json='{"test": true}',
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.event_key, "key_1")
        self.assertEqual(event.processing_status, "pending")

    def test_duplicate_event(self):
        self.repo.save_webhook_event_if_new(event_key="dup", payload_json="{}")
        dup = self.repo.save_webhook_event_if_new(event_key="dup", payload_json="{}")
        self.assertIsNone(dup)

    def test_mark_processed(self):
        event = self.repo.save_webhook_event_if_new(
            event_key="proc", payload_json="{}"
        )
        ok = self.repo.mark_webhook_event_processed(event.id)
        self.assertTrue(ok)
        row = self.conn.execute(
            "SELECT processing_status FROM whatsapp_webhook_events WHERE id = ?",
            (event.id,),
        ).fetchone()
        self.assertEqual(row["processing_status"], "processed")

    def test_mark_failed(self):
        event = self.repo.save_webhook_event_if_new(
            event_key="fail", payload_json="{}"
        )
        ok = self.repo.mark_webhook_event_failed(event.id, "Error test")
        self.assertTrue(ok)
        row = self.conn.execute(
            "SELECT processing_status, attempts, last_error FROM whatsapp_webhook_events WHERE id = ?",
            (event.id,),
        ).fetchone()
        self.assertEqual(row["processing_status"], "failed")
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(row["last_error"], "Error test")


# ═══════════════════════════════════════════════════════════════════════
# Outbox
# ═══════════════════════════════════════════════════════════════════════


class TestOutboxRepository(unittest.TestCase):
    def setUp(self):
        self.conn = _make_connection()
        self.repo = WhatsAppRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_enqueue_outbound(self):
        item = self.repo.enqueue_outbound_message(
            recipient_wa_id="wa_recipient",
            message_type="text",
            payload_json={"body": "Hola"},
        )
        self.assertIsNotNone(item.id)
        self.assertEqual(item.status, "pending")
        self.assertEqual(item.recipient_wa_id, "wa_recipient")

    def test_get_pending_outbox_items(self):
        self.repo.enqueue_outbound_message(
            recipient_wa_id="r1", message_type="text", payload_json={"body": "A"}
        )
        self.repo.enqueue_outbound_message(
            recipient_wa_id="r2", message_type="text", payload_json={"body": "B"}
        )
        pending = self.repo.get_pending_outbox_items()
        self.assertEqual(len(pending), 2)

    def test_mark_outbox_sent(self):
        item = self.repo.enqueue_outbound_message(
            recipient_wa_id="r1",
            message_type="text",
            payload_json={"body": "test"},
        )
        ok = self.repo.mark_outbox_sent(item.id, wa_message_id="wa_sent_1")
        self.assertTrue(ok)
        updated = self.conn.execute(
            "SELECT status, whatsapp_message_id FROM whatsapp_outbox WHERE id = ?",
            (item.id,),
        ).fetchone()
        self.assertEqual(updated["status"], "sent")
        self.assertEqual(updated["whatsapp_message_id"], "wa_sent_1")

    def test_release_outbox_for_retry(self):
        item = self.repo.enqueue_outbound_message(
            recipient_wa_id="r1",
            message_type="text",
            payload_json={"body": "test"},
        )
        ok = self.repo.release_outbox_for_retry(item.id, "Error", retry_after_seconds=30)
        self.assertTrue(ok)
        updated = self.conn.execute(
            "SELECT status, attempts, last_error, next_attempt_at FROM whatsapp_outbox WHERE id = ?",
            (item.id,),
        ).fetchone()
        self.assertEqual(updated["status"], "pending")
        self.assertEqual(updated["attempts"], 0)
        self.assertEqual(updated["last_error"], "Error")
        self.assertIsNotNone(updated["next_attempt_at"])

    def test_mark_outbox_failed_permanent(self):
        item = self.repo.enqueue_outbound_message(
            recipient_wa_id="r2",
            message_type="text",
            payload_json={"body": "fail"},
        )
        ok = self.repo.mark_outbox_failed(item.id, "Permanent error")
        self.assertTrue(ok)
        updated = self.conn.execute(
            "SELECT status, last_error FROM whatsapp_outbox WHERE id = ?",
            (item.id,),
        ).fetchone()
        self.assertEqual(updated["status"], "failed")
        self.assertEqual(updated["last_error"], "Permanent error")


# ═══════════════════════════════════════════════════════════════════════
# Servicio
# ═══════════════════════════════════════════════════════════════════════


class TestWhatsAppService(unittest.TestCase):
    def setUp(self):
        self.conn = _make_connection()
        self.repo = WhatsAppRepository(self.conn)
        self.service = WhatsAppService(self.repo)

    def tearDown(self):
        self.conn.close()

    def test_register_inbound_text_message(self):
        result = self.service.register_inbound_message(
            wa_id="wa_svc_1",
            phone_number="+549111",
            display_name="Carlos",
            message_type="text",
            wa_message_id="svc_msg_1",
            text_body="Hola, consulta",
            phone_number_id="phone_svc",
        )
        self.assertIsNotNone(result)
        self.assertIn("contact", result)
        self.assertIn("conversation", result)
        self.assertIn("message", result)
        self.assertEqual(result["message"].text_body, "Hola, consulta")
        self.assertEqual(result["conversation"].unread_count, 1)

    def test_register_duplicate_message(self):
        self.service.register_inbound_message(
            wa_id="dup_svc",
            phone_number="",
            display_name="Dup",
            message_type="text",
            wa_message_id="dup_svc_msg",
            text_body="Primero",
        )
        dup = self.service.register_inbound_message(
            wa_id="dup_svc",
            phone_number="",
            display_name="Dup",
            message_type="text",
            wa_message_id="dup_svc_msg",
            text_body="Segundo",
        )
        self.assertIsNone(dup)

    def test_register_status_update(self):
        self.service.register_inbound_message(
            wa_id="status_test",
            phone_number="",
            display_name="Status",
            message_type="text",
            wa_message_id="status_msg",
            text_body="Test",
        )
        ok = self.service.register_status_update(
            wa_message_id="status_msg", status="read"
        )
        self.assertTrue(ok)

    def test_queue_text_message(self):
        item = self.service.queue_text_message(
            recipient_wa_id="wa_q",
            text_body="Mensaje en cola",
        )
        self.assertIsNotNone(item.id)
        self.assertEqual(item.status, "pending")
        payload = json.loads(item.payload_json)
        self.assertEqual(payload["text"]["body"], "Mensaje en cola")

    def test_queue_media_message(self):
        item = self.service.queue_media_message(
            recipient_wa_id="wa_media",
            media_type="image",
            media_id_or_link="media_abc_123",
            caption="Foto",
            conversation_id=1,
        )
        self.assertIsNotNone(item.id)
        self.assertEqual(item.message_type, "image")
        payload = json.loads(item.payload_json)
        self.assertEqual(payload["image"]["id"], "media_abc_123")
        self.assertEqual(payload["image"]["caption"], "Foto")

    def test_link_conversation_to_order(self):
        contact = self.repo.create_or_update_contact(wa_id="link_svc")
        conv = self.repo.create_or_get_open_conversation(contact.id)
        ok = self.service.link_conversation_to_order(conv.id, 123)
        self.assertTrue(ok)

    def test_link_contact_to_client(self):
        contact = self.repo.create_or_update_contact(wa_id="link_client")
        ok = self.service.link_contact_to_client(contact.id, 77)
        self.assertTrue(ok)

    def test_mark_conversation_read(self):
        contact = self.repo.create_or_update_contact(wa_id="read_test")
        conv = self.repo.create_or_get_open_conversation(contact.id)
        self.repo.increment_unread_count(conv.id)
        self.service.mark_conversation_read(conv.id)
        updated = self.repo.get_conversation(conv.id)
        self.assertEqual(updated.unread_count, 0)

    def test_get_conversation_messages(self):
        result = self.service.register_inbound_message(
            wa_id="get_msgs",
            phone_number="",
            display_name="Getter",
            message_type="text",
            wa_message_id="get_msg_1",
            text_body="Mensaje 1",
        )
        conv_id = result["conversation"].id
        msgs = self.service.get_conversation_messages(conv_id)
        self.assertEqual(len(msgs), 1)

    def test_get_contact(self):
        self.service.register_inbound_message(
            wa_id="get_contact", phone_number="", display_name="Get", message_type="text"
        )
        contact = self.service.get_contact("get_contact")
        self.assertIsNotNone(contact)
        self.assertEqual(contact.display_name, "Get")


# ═══════════════════════════════════════════════════════════════════════
# Parser
# ═══════════════════════════════════════════════════════════════════════


class TestWebhookParser(unittest.TestCase):
    def test_extract_metadata(self):
        payload = {
            "changes": [
                {
                    "value": {
                        "metadata": {
                            "phone_number_id": "123456",
                            "business_account_id": "biz_789",
                            "display_phone_number": "+15551234567",
                        }
                    }
                }
            ]
        }
        meta = extract_metadata(payload)
        self.assertIsNotNone(meta)
        self.assertEqual(meta.phone_number_id, "123456")

    def test_extract_contacts(self):
        payload = {
            "changes": [
                {
                    "value": {
                        "contacts": [
                            {"wa_id": "wa_1", "profile": {"name": "Ana"}},
                            {"wa_id": "wa_2", "profile": {"name": "Pedro"}},
                        ]
                    }
                }
            ]
        }
        contacts = extract_contacts(payload)
        self.assertEqual(len(contacts), 2)
        self.assertEqual(contacts[0].wa_id, "wa_1")
        self.assertEqual(contacts[0].profile_name, "Ana")

    def test_extract_text_message(self):
        payload = {
            "changes": [
                {
                    "value": {
                        "messages": [
                            {
                                "id": "msg_1",
                                "from": "wa_sender",
                                "timestamp": "1712345678",
                                "type": "text",
                                "text": {"body": "Hola mundo"},
                            }
                        ]
                    }
                }
            ]
        }
        msgs = extract_messages(payload)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].message_id, "msg_1")
        self.assertEqual(msgs[0].text_body, "Hola mundo")
        self.assertEqual(msgs[0].message_type, "text")

    def test_extract_image_message(self):
        payload = {
            "changes": [
                {
                    "value": {
                        "messages": [
                            {
                                "id": "img_1",
                                "from": "wa_sender",
                                "timestamp": "1712345678",
                                "type": "image",
                                "image": {
                                    "id": "media_img",
                                    "mime_type": "image/png",
                                    "caption": "Foto",
                                },
                            }
                        ]
                    }
                }
            ]
        }
        msgs = extract_messages(payload)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].message_type, "image")
        self.assertEqual(msgs[0].media_id, "media_img")

    def test_extract_document_message(self):
        payload = {
            "changes": [
                {
                    "value": {
                        "messages": [
                            {
                                "id": "doc_1",
                                "from": "wa_sender",
                                "timestamp": "1712345678",
                                "type": "document",
                                "document": {
                                    "id": "media_doc",
                                    "mime_type": "application/pdf",
                                    "filename": "archivo.pdf",
                                },
                            }
                        ]
                    }
                }
            ]
        }
        msgs = extract_messages(payload)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].message_type, "document")
        self.assertEqual(msgs[0].filename, "archivo.pdf")

    def test_extract_status_update(self):
        payload = {
            "changes": [
                {
                    "value": {
                        "statuses": [
                            {
                                "id": "status_1",
                                "status": "read",
                                "timestamp": "1712345678",
                                "recipient_id": "wa_recipient",
                            }
                        ]
                    }
                }
            ]
        }
        statuses = extract_status_updates(payload)
        self.assertEqual(len(statuses), 1)
        self.assertEqual(statuses[0].status, "read")
        self.assertEqual(statuses[0].recipient_wa_id, "wa_recipient")

    def test_parse_full_payload(self):
        raw = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": "phone_1"},
                                "contacts": [
                                    {"wa_id": "c_1", "profile": {"name": "Test"}}
                                ],
                                "messages": [
                                    {
                                        "id": "m_1",
                                        "from": "c_1",
                                        "timestamp": "1000",
                                        "type": "text",
                                        "text": {"body": "Hola"},
                                    }
                                ],
                                "statuses": [
                                    {
                                        "id": "s_1",
                                        "status": "sent",
                                        "timestamp": "1001",
                                        "recipient_id": "c_1",
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }
        parsed = parse_payload(raw)
        self.assertIsNotNone(parsed.metadata)
        self.assertEqual(len(parsed.contacts), 1)
        self.assertEqual(len(parsed.messages), 1)
        self.assertEqual(len(parsed.statuses), 1)

    def test_empty_payload(self):
        parsed = parse_payload({"entry": []})
        self.assertEqual(len(parsed.messages), 0)
        self.assertEqual(len(parsed.statuses), 0)

    def test_payload_without_messages(self):
        parsed = parse_payload(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "statuses": [
                                        {
                                            "id": "s_1",
                                            "status": "sent",
                                            "timestamp": "1000",
                                            "recipient_id": "r_1",
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
        )
        self.assertEqual(len(parsed.messages), 0)
        self.assertEqual(len(parsed.statuses), 1)

    def test_unknown_fields_tolerated(self):
        parsed = parse_payload(
            {"entry": [{"changes": [{"value": {"unknown_field": True}}]}]}
        )
        self.assertIsNotNone(parsed)

    def test_incomplete_structure_tolerated(self):
        parsed = parse_payload({"entry": [{"changes": [{}]}]})
        self.assertIsNotNone(parsed)
        self.assertEqual(len(parsed.messages), 0)

    def test_build_event_key_message(self):
        entry = {
            "changes": [
                {
                    "value": {
                        "messages": [
                            {"id": "msg_abc", "timestamp": "1000"}
                        ]
                    }
                }
            ]
        }
        key = build_event_key(entry)
        self.assertTrue(len(key) > 0)
        self.assertEqual(len(key), 64)

    def test_build_event_key_status(self):
        entry = {
            "changes": [
                {
                    "value": {
                        "statuses": [
                            {"id": "st_abc", "status": "sent", "timestamp": "1000"}
                        ]
                    }
                }
            ]
        }
        key = build_event_key(entry)
        self.assertTrue(len(key) > 0)

    def test_verify_signature_valid(self):
        body = b'{"test": true}'
        secret = "my_secret"
        import hmac, hashlib
        expected = "sha256=" + hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        self.assertTrue(verify_signature(body, expected, secret))

    def test_verify_signature_invalid(self):
        body = b'{"test": true}'
        self.assertFalse(verify_signature(body, "sha256:invalid", "secret"))

    def test_verify_signature_empty(self):
        self.assertFalse(verify_signature(b"{}", "", "secret"))

    def test_parse_payload_json_string(self):
        raw_json = json.dumps({
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "id": "json_str",
                                        "from": "wa",
                                        "timestamp": "1",
                                        "type": "text",
                                        "text": {"body": "desde json string"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        })
        parsed = parse_payload(raw_json)
        self.assertEqual(len(parsed.messages), 1)
        self.assertEqual(parsed.messages[0].text_body, "desde json string")


# ═══════════════════════════════════════════════════════════════════════
# Configuración
# ═══════════════════════════════════════════════════════════════════════


class TestWhatsAppConfig(unittest.TestCase):
    def setUp(self):
        self._config_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._config_dir.cleanup)
        self.dotenv_path = Path(self._config_dir.name) / '.env'
        loader = patch('app.whatsapp.config._load_dotenv',
                       side_effect=lambda path=None: _load_dotenv(path or self.dotenv_path))
        loader.start()
        self.addCleanup(loader.stop)
        cache = patch('app.whatsapp.config._CONFIG_CACHE', None)
        cache.start()
        self.addCleanup(cache.stop)
        self._old_env = {}
        for key in (
            "WHATSAPP_ENABLED",
            "WHATSAPP_ACCESS_TOKEN",
            "WHATSAPP_PHONE_NUMBER_ID",
            "WHATSAPP_BUSINESS_ACCOUNT_ID",
            "WHATSAPP_VERIFY_TOKEN",
            "WHATSAPP_APP_SECRET",
            "WHATSAPP_API_VERSION",
            "WHATSAPP_WEBHOOK_PORT",
        ):
            self._old_env[key] = os.environ.pop(key, None)

    def tearDown(self):
        for key, val in self._old_env.items():
            if val is not None:
                os.environ[key] = val
            else:
                os.environ.pop(key, None)

    def test_disabled_by_default(self):
        cfg = WhatsAppConfig.from_env()
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.access_token, "")
        self.assertEqual(cfg.api_version, "v22.0")
        self.assertEqual(cfg.webhook_port, 8767)

    def test_enabled_explicitly(self):
        os.environ["WHATSAPP_ENABLED"] = "true"
        os.environ["WHATSAPP_ACCESS_TOKEN"] = "tok_abc"
        os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "phone_123"
        os.environ["WHATSAPP_WEBHOOK_PORT"] = "9000"
        cfg = WhatsAppConfig.from_env()
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.access_token, "tok_abc")
        self.assertEqual(cfg.phone_number_id, "phone_123")
        self.assertEqual(cfg.webhook_port, 9000)

    def test_api_version_configurable(self):
        os.environ["WHATSAPP_API_VERSION"] = "v21.0"
        cfg = WhatsAppConfig.from_env()
        self.assertEqual(cfg.api_version, "v21.0")

    def test_invalid_port_falls_back(self):
        os.environ["WHATSAPP_WEBHOOK_PORT"] = "not_a_number"
        cfg = WhatsAppConfig.from_env()
        self.assertEqual(cfg.webhook_port, 8767)

    def test_load_config_cache(self):
        cfg1 = load_config()
        cfg2 = load_config()
        self.assertIs(cfg1, cfg2)

    def test_load_config_reload(self):
        cfg1 = load_config()
        cfg2 = load_config(reload=True)
        self.assertIsNot(cfg1, cfg2)

    def test_is_enabled_returns_false(self):
        self.assertFalse(is_enabled())

    def test_missing_tokens_no_crash(self):
        cfg = WhatsAppConfig.from_env()
        # Solo verificar que no lance excepción
        self.assertIsInstance(cfg, WhatsAppConfig)

    def test_load_dotenv_no_file(self):
        _load_dotenv(Path(tempfile.gettempdir()) / "nonexistent.env")
        self.assertNotIn("WHATSAPP_ENABLED", os.environ)

    def test_load_config_reads_dotenv(self):
        dotenv_path = self.dotenv_path
        backup = None
        if dotenv_path.exists():
            backup = dotenv_path.read_text(encoding="utf-8")
        env_content = (
            "WHATSAPP_ENABLED=true\n"
            "WHATSAPP_ACCESS_TOKEN=eaa_load_config_test_token\n"
            "WHATSAPP_PHONE_NUMBER_ID=pn_load_config_test\n"
            "WHATSAPP_BUSINESS_ACCOUNT_ID=biz_load_config_test\n"
        )
        try:
            dotenv_path.write_text(env_content, encoding="utf-8")
            cfg = load_config(reload=True)
            self.assertTrue(cfg.enabled)
            self.assertEqual(cfg.access_token, "eaa_load_config_test_token")
            self.assertEqual(cfg.phone_number_id, "pn_load_config_test")
            self.assertEqual(cfg.business_account_id, "biz_load_config_test")
        finally:
            if backup is not None:
                dotenv_path.write_text(backup, encoding="utf-8")
            elif dotenv_path.exists():
                dotenv_path.unlink()
