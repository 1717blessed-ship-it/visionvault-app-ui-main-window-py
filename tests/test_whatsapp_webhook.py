"""Tests del servidor webhook de WhatsApp."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
import unittest
from http.client import HTTPConnection
from urllib.parse import urlencode

from app.whatsapp.config import WhatsAppConfig
from app.whatsapp.repository import create_whatsapp_tables, WhatsAppRepository
from app.whatsapp.service import WhatsAppService
from app.whatsapp.webhook_server import WhatsAppWebhookServer
from app.whatsapp.webhook_parser import build_event_key


def _make_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    create_whatsapp_tables(conn)
    return conn


def _make_signature(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()


def _make_server(
    repo=None,
    service=None,
    host="127.0.0.1",
    port=0,
    config=None,
) -> tuple[WhatsAppWebhookServer, WhatsAppService, WhatsAppRepository, sqlite3.Connection]:
    conn = _make_connection()
    r = repo or WhatsAppRepository(conn)
    s = service or WhatsAppService(r)
    cfg = config or WhatsAppConfig(
        enabled=True,
        verify_token="test_token",
        app_secret="test_secret",
        verify_signature=True,
    )
    sv = WhatsAppWebhookServer(service=s, host=host, port=port, config=cfg)
    sv.start()
    return sv, s, r, conn


def _do_get(host: str, port: int, path: str, params: dict | None = None) -> tuple[int, bytes]:
    conn = HTTPConnection(host, port, timeout=5)
    try:
        if params:
            qs = urlencode(params)
            full = f"{path}?{qs}"
        else:
            full = path
        conn.request("GET", full)
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, data
    finally:
        conn.close()


def _do_post(
    host: str,
    port: int,
    path: str,
    body: bytes,
    signature: str | None = None,
) -> tuple[int, bytes, dict]:
    conn = HTTPConnection(host, port, timeout=5)
    try:
        headers = {"Content-Type": "application/json"}
        if signature is not None:
            headers["X-Hub-Signature-256"] = signature
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, data, dict(resp.getheaders())
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
# Verificación (GET)
# ═══════════════════════════════════════════════════════════════════════


class TestVerificationGET(unittest.TestCase):
    def setUp(self):
        self.server, self.service, self.repo, self.conn = _make_server()
        self.host = "127.0.0.1"
        self.port = self.server.port

    def tearDown(self):
        self.server.stop()
        self.conn.close()

    def test_valid_challenge(self):
        status, data = _do_get(
            self.host, self.port,
            "/api/whatsapp/webhook",
            {"hub.mode": "subscribe", "hub.verify_token": "test_token", "hub.challenge": "12345"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(data.decode(), "12345")

    def test_invalid_token(self):
        status, data = _do_get(
            self.host, self.port,
            "/api/whatsapp/webhook",
            {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "12345"},
        )
        self.assertEqual(status, 403)

    def test_wrong_mode(self):
        status, data = _do_get(
            self.host, self.port,
            "/api/whatsapp/webhook",
            {"hub.mode": "unsubscribe", "hub.verify_token": "test_token", "hub.challenge": "12345"},
        )
        self.assertEqual(status, 400)

    def test_missing_parameters(self):
        status, data = _do_get(
            self.host, self.port,
            "/api/whatsapp/webhook",
            {"hub.mode": "subscribe"},
        )
        self.assertEqual(status, 400)

    def test_unknown_route(self):
        status, data = _do_get(self.host, self.port, "/api/whatsapp/unknown")
        self.assertEqual(status, 404)




# ═══════════════════════════════════════════════════════════════════════
# Webhook (POST) - básicos
# ═══════════════════════════════════════════════════════════════════════


class TestWebhookPOST(unittest.TestCase):
    def setUp(self):
        self.cfg = WhatsAppConfig(
            enabled=True,
            verify_token="test_token",
            app_secret="test_secret",
            verify_signature=True,
            max_webhook_bytes=1048576,
        )
        self.server, self.service, self.repo, self.conn = _make_server(config=self.cfg)
        self.host = "127.0.0.1"
        self.port = self.server.port

    def tearDown(self):
        self.server.stop()
        self.conn.close()

    def _post(self, payload: dict, sign: bool = True) -> tuple[int, dict]:
        body = json.dumps(payload).encode("utf-8")
        sig = _make_signature(body, "test_secret") if sign else None
        status, data, headers = _do_post(self.host, self.port, "/api/whatsapp/webhook", body, sig)
        try:
            parsed = json.loads(data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            parsed = {"raw": data.decode()}
        return status, parsed

    # ── Tipos de mensaje ───────────────────────────────────────────────

    def _make_text_payload(self, msg_id="msg_1", text_body="Hello"):
        return {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "biz_1",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "phone_number_id": "phone_123",
                            "display_phone_number": "+15551234567",
                        },
                        "contacts": [{"wa_id": "wa_sender", "profile": {"name": "Test User"}}],
                        "messages": [{
                            "id": msg_id,
                            "from": "wa_sender",
                            "timestamp": "1712345678",
                            "type": "text",
                            "text": {"body": text_body},
                        }],
                    }
                }],
            }],
        }

    def test_text_message(self):
        status, parsed = self._post(self._make_text_payload())
        self.assertEqual(status, 200)
        self.assertTrue(parsed.get("result", {}).get("event_saved"))
        self.assertEqual(parsed["result"]["messages_saved"], 1)

    def test_image_message(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "biz_1",
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "phone_123"},
                        "contacts": [{"wa_id": "img_sender", "profile": {"name": "Img"}}],
                        "messages": [{
                            "id": "img_msg_1",
                            "from": "img_sender",
                            "timestamp": "1712345679",
                            "type": "image",
                            "image": {
                                "id": "media_img_1",
                                "mime_type": "image/jpeg",
                                "caption": "Photo",
                            },
                        }],
                    }
                }],
            }],
        }
        status, parsed = self._post(payload)
        self.assertEqual(status, 200)
        self.assertEqual(parsed["result"]["messages_saved"], 1)

    def test_document_message(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "biz_1",
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "phone_123"},
                        "contacts": [{"wa_id": "doc_sender", "profile": {"name": "Doc"}}],
                        "messages": [{
                            "id": "doc_msg_1",
                            "from": "doc_sender",
                            "timestamp": "1712345680",
                            "type": "document",
                            "document": {
                                "id": "media_doc_1",
                                "mime_type": "application/pdf",
                                "filename": "report.pdf",
                                "caption": "Report",
                            },
                        }],
                    }
                }],
            }],
        }
        status, parsed = self._post(payload)
        self.assertEqual(status, 200)
        self.assertEqual(parsed["result"]["messages_saved"], 1)

    def test_audio_message(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "biz_1",
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "phone_123"},
                        "contacts": [{"wa_id": "aud_sender", "profile": {"name": "Aud"}}],
                        "messages": [{
                            "id": "aud_msg_1",
                            "from": "aud_sender",
                            "timestamp": "1712345681",
                            "type": "audio",
                            "audio": {"id": "media_aud_1", "mime_type": "audio/ogg"},
                        }],
                    }
                }],
            }],
        }
        status, parsed = self._post(payload)
        self.assertEqual(status, 200)
        self.assertEqual(parsed["result"]["messages_saved"], 1)

    def test_sticker_message(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "biz_1",
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "phone_123"},
                        "contacts": [{"wa_id": "st_sender", "profile": {"name": "St"}}],
                        "messages": [{
                            "id": "st_msg_1",
                            "from": "st_sender",
                            "timestamp": "1712345682",
                            "type": "sticker",
                            "sticker": {"id": "media_st_1", "mime_type": "image/webp"},
                        }],
                    }
                }],
            }],
        }
        status, parsed = self._post(payload)
        self.assertEqual(status, 200)
        self.assertEqual(parsed["result"]["messages_saved"], 1)

    def test_location_message(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "biz_1",
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "phone_123"},
                        "contacts": [{"wa_id": "loc_sender", "profile": {"name": "Loc"}}],
                        "messages": [{
                            "id": "loc_msg_1",
                            "from": "loc_sender",
                            "timestamp": "1712345683",
                            "type": "location",
                            "location": {"latitude": -34.6, "longitude": -58.4},
                        }],
                    }
                }],
            }],
        }
        status, parsed = self._post(payload)
        self.assertEqual(status, 200)
        self.assertEqual(parsed["result"]["messages_saved"], 1)

    def test_reaction_message(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "biz_1",
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "phone_123"},
                        "contacts": [{"wa_id": "re_sender", "profile": {"name": "Re"}}],
                        "messages": [{
                            "id": "re_msg_1",
                            "from": "re_sender",
                            "timestamp": "1712345684",
                            "type": "reaction",
                            "reaction": {"emoji": "👍", "message_id": "orig_msg"},
                        }],
                    }
                }],
            }],
        }
        status, parsed = self._post(payload)
        self.assertEqual(status, 200)
        self.assertEqual(parsed["result"]["messages_saved"], 1)

    def test_unknown_message_type(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "biz_1",
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "phone_123"},
                        "contacts": [{"wa_id": "unk_sender", "profile": {"name": "Unk"}}],
                        "messages": [{
                            "id": "unk_msg_1",
                            "from": "unk_sender",
                            "timestamp": "1712345685",
                            "type": "system",
                            "text": {"body": "System message"},
                        }],
                    }
                }],
            }],
        }
        status, parsed = self._post(payload)
        self.assertEqual(status, 200)
        self.assertEqual(parsed["result"]["messages_saved"], 1)

    # ── Status updates ─────────────────────────────────────────────────

    def _make_status_payload(self, msg_id="out_msg_1", status_type="sent"):
        return {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "biz_1",
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "phone_123"},
                        "statuses": [{
                            "id": msg_id,
                            "status": status_type,
                            "timestamp": "1712345690",
                            "recipient_id": "wa_recipient",
                        }],
                    }
                }],
            }],
        }

    def test_status_sent(self):
        status, parsed = self._post(self._make_status_payload("st_sent", "sent"))
        self.assertEqual(status, 200)
        self.assertEqual(parsed["result"]["statuses_processed"], 1)

    def test_status_delivered(self):
        status, parsed = self._post(self._make_status_payload("st_del", "delivered"))
        self.assertEqual(status, 200)
        self.assertEqual(parsed["result"]["statuses_processed"], 1)

    def test_status_read(self):
        status, parsed = self._post(self._make_status_payload("st_read", "read"))
        self.assertEqual(status, 200)
        self.assertEqual(parsed["result"]["statuses_processed"], 1)

    def test_status_failed(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "biz_1",
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "phone_123"},
                        "statuses": [{
                            "id": "st_fail",
                            "status": "failed",
                            "timestamp": "1712345691",
                            "recipient_id": "wa_recipient",
                            "errors": [{"code": 131026, "title": "Message undeliverable"}],
                        }],
                    }
                }],
            }],
        }
        status, parsed = self._post(payload)
        self.assertEqual(status, 200)
        self.assertEqual(parsed["result"]["statuses_processed"], 1)

    # ── Duplicados ─────────────────────────────────────────────────────

    def test_duplicate_payload(self):
        payload = self._make_text_payload("dup_msg")
        st1, p1 = self._post(payload)
        self.assertTrue(p1["result"]["event_saved"])
        st2, p2 = self._post(payload)
        self.assertTrue(p2["result"]["ignored"])

    def test_duplicate_message_id(self):
        payload1 = self._make_text_payload("same_msg_id", "First")
        payload2 = self._make_text_payload("same_msg_id", "Second")
        st1, p1 = self._post(payload1)
        self.assertEqual(p1["result"]["messages_saved"], 1)
        st2, p2 = self._post(payload2)
        self.assertTrue(p2["result"]["ignored"])

    def test_payload_without_messages(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "biz_1",
                "changes": [{"value": {"metadata": {"phone_number_id": "phone_123"}}}],
            }],
        }
        status, parsed = self._post(payload)
        self.assertEqual(status, 200)
        self.assertTrue(parsed.get("result", {}).get("ignored"))

    # ── Errores ────────────────────────────────────────────────────────

    def test_invalid_json(self):
        body = b"{invalid}"
        sig = _make_signature(body, "test_secret")
        st, data, _ = _do_post(self.host, self.port, "/api/whatsapp/webhook", body, sig)
        self.assertEqual(st, 400)

    def test_empty_body(self):
        sig = _make_signature(b"", "test_secret")
        st, data, _ = _do_post(self.host, self.port, "/api/whatsapp/webhook", b"", sig)
        self.assertEqual(st, 400)

    def test_body_too_large(self):
        big = b"x" * (self.cfg.max_webhook_bytes + 1)
        st, data, _ = _do_post(self.host, self.port, "/api/whatsapp/webhook", big, "sig")
        self.assertEqual(st, 413)

    def test_valid_signature(self):
        payload = self._make_text_payload()
        body = json.dumps(payload).encode()
        sig = _make_signature(body, "test_secret")
        st, data, _ = _do_post(self.host, self.port, "/api/whatsapp/webhook", body, sig)
        self.assertEqual(st, 200)

    def test_invalid_signature(self):
        payload = self._make_text_payload()
        body = json.dumps(payload).encode()
        st, data, _ = _do_post(self.host, self.port, "/api/whatsapp/webhook", body, "sha256=bad")
        self.assertEqual(st, 401)

    def test_missing_signature(self):
        payload = self._make_text_payload()
        body = json.dumps(payload).encode()
        st, data, _ = _do_post(self.host, self.port, "/api/whatsapp/webhook", body, None)
        self.assertEqual(st, 401)

    def test_signature_verification_disabled(self):
        cfg_disabled = WhatsAppConfig(
            enabled=True,
            verify_token="test_token",
            app_secret="test_secret",
            verify_signature=False,
        )
        sv, svc, r, conn = _make_server(config=cfg_disabled)
        body = json.dumps(self._make_text_payload()).encode()
        st, data, _ = _do_post("127.0.0.1", sv.port, "/api/whatsapp/webhook", body, None)
        self.assertEqual(st, 200)
        sv.stop()
        conn.close()

    def test_wrong_route(self):
        body = json.dumps(self._make_text_payload()).encode()
        sig = _make_signature(body, "test_secret")
        st, data, _ = _do_post(self.host, self.port, "/api/whatsapp/other", body, sig)
        self.assertEqual(st, 404)

    def test_method_not_allowed(self):
        conn = HTTPConnection(self.host, self.port, timeout=5)
        conn.request("PUT", "/api/whatsapp/webhook")
        resp = conn.getresponse()
        data = resp.read()
        self.assertIn(resp.status, (405, 501))
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
# Persistencia
# ═══════════════════════════════════════════════════════════════════════


class TestWebhookPersistence(unittest.TestCase):
    def setUp(self):
        self.conn = _make_connection()
        self.repo = WhatsAppRepository(self.conn)
        self.service = WhatsAppService(self.repo)
        self.cfg = WhatsAppConfig(
            enabled=True,
            verify_token="test_token",
            app_secret="test_secret",
            verify_signature=False,
        )
        self.server = WhatsAppWebhookServer(
            service=self.service, host="127.0.0.1", port=0, config=self.cfg,
        )
        self.server.start()
        self.host = "127.0.0.1"
        self.port = self.server.port

    def tearDown(self):
        self.server.stop()
        self.conn.close()

    def _post(self, payload: dict) -> tuple[int, dict]:
        body = json.dumps(payload).encode("utf-8")
        st, data, _ = _do_post(self.host, self.port, "/api/whatsapp/webhook", body, None)
        try:
            parsed = json.loads(data.decode())
        except Exception:
            parsed = {}
        return st, parsed

    def test_event_pending_on_receive(self):
        payload = self._make_text_payload()
        self._post(payload)
        events = self.repo.get_pending_webhook_events()
        self.assertEqual(len(events), 0)
        processed = self.conn.execute(
            "SELECT processing_status FROM whatsapp_webhook_events"
        ).fetchall()
        self.assertTrue(all(r["processing_status"] == "processed" for r in processed))

    def test_event_transitions(self):
        payload = self._make_text_payload()
        self._post(payload)
        row = self.conn.execute(
            "SELECT processing_status, attempts FROM whatsapp_webhook_events"
        ).fetchone()
        self.assertEqual(row["processing_status"], "processed")
        self.assertEqual(row["attempts"], 0)

    def test_contact_created(self):
        payload = self._make_text_payload()
        self._post(payload)
        contact = self.repo.get_contact_by_wa_id("wa_sender")
        self.assertIsNotNone(contact)
        self.assertEqual(contact.display_name, "Test User")

    def test_contact_updated(self):
        payload1 = self._make_text_payload()
        self._post(payload1)
        payload2 = self._make_text_payload(msg_id="msg_2", text_body="Second")
        # change the profile name
        payload2["entry"][0]["changes"][0]["value"]["contacts"][0]["profile"]["name"] = "Updated Name"
        self._post(payload2)
        contact = self.repo.get_contact_by_wa_id("wa_sender")
        self.assertEqual(contact.display_name, "Updated Name")

    def test_conversation_created(self):
        payload = self._make_text_payload()
        self._post(payload)
        contact = self.repo.get_contact_by_wa_id("wa_sender")
        conv = self.repo.create_or_get_open_conversation(contact.id)
        self.assertIsNotNone(conv)
        self.assertEqual(conv.status, "open")

    def test_unread_count_incremented_once(self):
        payload = self._make_text_payload()
        self._post(payload)
        contact = self.repo.get_contact_by_wa_id("wa_sender")
        conv = self.repo.get_conversation(
            self.repo.create_or_get_open_conversation(contact.id).id
        )
        self.assertEqual(conv.unread_count, 1)

    def test_message_status_updated(self):
        # First save an outbound message
        contact = self.repo.create_or_update_contact(wa_id="wa_recipient")
        conv = self.repo.create_or_get_open_conversation(contact.id)
        self.repo.create_outbound_message(
            conversation_id=conv.id,
            message_type="text",
            text_body="Test",
            wa_message_id="out_1",
        )
        # Now send a status update via webhook
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "biz_1",
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "phone_123"},
                        "statuses": [{
                            "id": "out_1",
                            "status": "read",
                            "timestamp": "1712345690",
                            "recipient_id": "wa_recipient",
                        }],
                    }
                }],
            }],
        }
        st, parsed = self._post(payload)
        self.assertEqual(st, 200)
        self.assertEqual(parsed["result"]["statuses_processed"], 1)
        msgs = self.conn.execute(
            "SELECT delivery_status FROM whatsapp_messages WHERE whatsapp_message_id = ?",
            ("out_1",),
        ).fetchone()
        self.assertEqual(msgs["delivery_status"], "read")

    def _make_text_payload(self, msg_id="msg_1", text_body="Hello"):
        return {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "biz_1",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "phone_number_id": "phone_123",
                            "display_phone_number": "+15551234567",
                        },
                        "contacts": [{"wa_id": "wa_sender", "profile": {"name": "Test User"}}],
                        "messages": [{
                            "id": msg_id,
                            "from": "wa_sender",
                            "timestamp": "1712345678",
                            "type": "text",
                            "text": {"body": text_body},
                        }],
                    }
                }],
            }],
        }


# ═══════════════════════════════════════════════════════════════════════
# Nuevos métodos del repositorio
# ═══════════════════════════════════════════════════════════════════════


class TestNewRepositoryMethods(unittest.TestCase):
    def setUp(self):
        self.conn = _make_connection()
        self.repo = WhatsAppRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_mark_webhook_event_processing(self):
        ev = self.repo.save_webhook_event_if_new(event_key="proc_test", payload_json="{}")
        self.repo.mark_webhook_event_processing(ev.id)
        row = self.conn.execute(
            "SELECT processing_status FROM whatsapp_webhook_events WHERE id = ?",
            (ev.id,),
        ).fetchone()
        self.assertEqual(row["processing_status"], "processing")

    def test_mark_webhook_event_ignored(self):
        ev = self.repo.save_webhook_event_if_new(event_key="ign_test", payload_json="{}")
        self.repo.mark_webhook_event_ignored(ev.id)
        row = self.conn.execute(
            "SELECT processing_status FROM whatsapp_webhook_events WHERE id = ?",
            (ev.id,),
        ).fetchone()
        self.assertEqual(row["processing_status"], "ignored")

    def test_get_pending_webhook_events(self):
        self.repo.save_webhook_event_if_new(event_key="p1", payload_json="{}")
        self.repo.save_webhook_event_if_new(event_key="p2", payload_json="{}")
        pending = self.repo.get_pending_webhook_events()
        self.assertEqual(len(pending), 2)

    def test_get_pending_after_processed(self):
        ev = self.repo.save_webhook_event_if_new(event_key="to_proc", payload_json="{}")
        self.repo.mark_webhook_event_processed(ev.id)
        pending = self.repo.get_pending_webhook_events()
        self.assertEqual(len(pending), 0)

    def test_retry_failed_event(self):
        ev = self.repo.save_webhook_event_if_new(event_key="retry_test", payload_json="{}")
        self.repo.mark_webhook_event_failed(ev.id, "Error")
        ok = self.repo.retry_failed_webhook_event(ev.id)
        self.assertTrue(ok)
        row = self.conn.execute(
            "SELECT processing_status, last_error FROM whatsapp_webhook_events WHERE id = ?",
            (ev.id,),
        ).fetchone()
        self.assertEqual(row["processing_status"], "pending")
        self.assertIsNone(row["last_error"])

    def test_webhook_event_attempts_incremented(self):
        ev = self.repo.save_webhook_event_if_new(event_key="attempt_test", payload_json="{}")
        self.repo.mark_webhook_event_failed(ev.id, "Error 1")
        self.repo.retry_failed_webhook_event(ev.id)
        self.repo.mark_webhook_event_failed(ev.id, "Error 2")
        row = self.conn.execute(
            "SELECT attempts, last_error FROM whatsapp_webhook_events WHERE id = ?",
            (ev.id,),
        ).fetchone()
        self.assertEqual(row["attempts"], 2)
        self.assertEqual(row["last_error"], "Error 2")


# ═══════════════════════════════════════════════════════════════════════
# Ciclo de vida del servidor
# ═══════════════════════════════════════════════════════════════════════


class TestServerLifecycle(unittest.TestCase):
    def setUp(self):
        self.conn = _make_connection()
        self.repo = WhatsAppRepository(self.conn)
        self.service = WhatsAppService(self.repo)

    def tearDown(self):
        self.conn.close()

    def test_start_stop(self):
        sv = WhatsAppWebhookServer(self.service, host="127.0.0.1", port=0)
        self.assertFalse(sv.is_running)
        ok = sv.start()
        self.assertTrue(ok)
        self.assertTrue(sv.is_running)
        sv.stop()
        self.assertFalse(sv.is_running)

    def test_double_start_safe(self):
        sv = WhatsAppWebhookServer(self.service, host="127.0.0.1", port=0)
        sv.start()
        sv.start()
        self.assertTrue(sv.is_running)
        sv.stop()

    def test_double_stop_safe(self):
        sv = WhatsAppWebhookServer(self.service, host="127.0.0.1", port=0)
        sv.start()
        sv.stop()
        sv.stop()

    def test_free_port_assigned(self):
        sv = WhatsAppWebhookServer(self.service, host="127.0.0.1", port=0)
        sv.start()
        self.assertGreater(sv.port, 0)
        sv.stop()

    def test_server_does_not_block(self):
        sv = WhatsAppWebhookServer(self.service, host="127.0.0.1", port=0)
        sv.start()
        self.assertTrue(sv.is_running)
        sv.stop()

    def test_responds_after_start(self):
        cfg = WhatsAppConfig(enabled=True, verify_token="test_token", app_secret="test_secret")
        sv = WhatsAppWebhookServer(self.service, host="127.0.0.1", port=0, config=cfg)
        sv.start()
        status, data = _do_get("127.0.0.1", sv.port, "/api/whatsapp/webhook",
                               {"hub.mode": "subscribe", "hub.verify_token": "test_token", "hub.challenge": "42"})
        self.assertEqual(status, 200)
        sv.stop()

    def test_serve_forever_poll(self):
        sv = WhatsAppWebhookServer(self.service, host="127.0.0.1", port=0)
        sv.start()
        time.sleep(0.1)
        self.assertTrue(sv.is_running)
        sv.stop()
