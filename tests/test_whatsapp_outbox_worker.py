from __future__ import annotations

import json
import sqlite3
import time
import unittest
from typing import Any

from app.whatsapp.client import WhatsAppCloudClient
from app.whatsapp.config import WhatsAppConfig
from app.whatsapp.models import WhatsAppSendResult
from app.whatsapp.outbox_worker import WhatsAppOutboxWorker
from app.whatsapp.repository import create_whatsapp_tables, WhatsAppRepository
from app.whatsapp.service import WhatsAppService


def _ok_transport(
    url: str, data: dict[str, Any], headers: dict[str, str], timeout: float
) -> tuple[int, bytes, dict[str, str]]:
    resp = {
        "messaging_product": "whatsapp",
        "messages": [{"id": "wamid.ok123"}],
    }
    return 200, json.dumps(resp).encode("utf-8"), {}


def _make_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    create_whatsapp_tables(conn)
    return conn


def _make_config(**kwargs) -> WhatsAppConfig:
    overrides = dict(
        enabled=True,
        access_token="test_token",
        phone_number_id="pn_123",
        business_account_id="biz_1",
        verify_token="test_token",
        app_secret="test_secret",
        verify_signature=False,
        outbox_poll_seconds=3600,
        outbox_batch_size=20,
        outbox_max_attempts=5,
        outbox_retry_base_seconds=5,
        outbox_retry_max_seconds=900,
        outbox_processing_timeout_seconds=300,
    )
    overrides.update(kwargs)
    return WhatsAppConfig(**overrides)


def _make_worker(
    repo=None,
    client=None,
    config=None,
    transport=None,
) -> tuple[WhatsAppOutboxWorker, WhatsAppRepository, WhatsAppCloudClient, sqlite3.Connection]:
    conn = _make_connection()
    r = repo or WhatsAppRepository(conn)
    cfg = config or _make_config()
    if client is None:
        client = WhatsAppCloudClient(config=cfg, transport=transport or _ok_transport)
    w = WhatsAppOutboxWorker(repo=r, client=client, config=cfg)
    return w, r, client, conn


class TestEnqueue(unittest.TestCase):
    def test_enqueue_basic(self):
        _, repo, _, conn = _make_worker()
        item = repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text", payload_json={"body": "hi"},
        )
        self.assertIsNotNone(item.id)
        self.assertEqual(item.status, "pending")

    def test_enqueue_with_idempotency_key_new(self):
        _, repo, _, conn = _make_worker()
        item = repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text",
            payload_json={"body": "hi"}, idempotency_key="idem_1",
        )
        self.assertIsNotNone(item.id)
        self.assertEqual(item.idempotency_key, "idem_1")

    def test_enqueue_idempotency_key_duplicate(self):
        _, repo, _, conn = _make_worker()
        item1 = repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text",
            payload_json={"body": "hi"}, idempotency_key="idem_1",
        )
        item2 = repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text",
            payload_json={"body": "hi"}, idempotency_key="idem_1",
        )
        self.assertEqual(item1.id, item2.id)

    def test_different_messages_same_recipient_allowed(self):
        _, repo, _, conn = _make_worker()
        item1 = repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text", payload_json={"body": "hi"},
        )
        item2 = repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text", payload_json={"body": "bye"},
        )
        self.assertNotEqual(item1.id, item2.id)


class TestClaimAtomic(unittest.TestCase):
    def test_claim_returns_pending_items(self):
        w, repo, _, _ = _make_worker()
        repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text", payload_json={"body": "hi"},
        )
        items = repo.claim_pending_outbox_items(worker_id="test_w1", limit=10)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].status, "processing")

    def test_two_workers_no_double_claim(self):
        w, repo, _, _ = _make_worker()
        repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text", payload_json={"body": "hi"},
        )
        items1 = repo.claim_pending_outbox_items(worker_id="test_w1", limit=10)
        items2 = repo.claim_pending_outbox_items(worker_id="test_w2", limit=10)
        self.assertEqual(len(items1), 1)
        self.assertEqual(len(items2), 0)

    def test_claim_increments_attempts(self):
        w, repo, _, _ = _make_worker()
        repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text", payload_json={"body": "hi"},
        )
        repo.claim_pending_outbox_items(worker_id="test_w1", limit=10)
        items = repo.claim_pending_outbox_items(worker_id="test_w1", limit=10)
        self.assertEqual(len(items), 0)


class TestProcessOnce(unittest.TestCase):
    def test_process_once_success(self):
        w, repo, _, _ = _make_worker()
        repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text",
            payload_json={"messaging_product": "whatsapp", "type": "text", "text": {"body": "hi"}},
            conversation_id=1,
        )
        count = w.process_once(limit=10)
        self.assertEqual(count, 1)
        rows = repo.conn.execute("SELECT status, whatsapp_message_id FROM whatsapp_outbox").fetchall()
        self.assertEqual(rows[0]["status"], "sent")
        self.assertEqual(rows[0]["whatsapp_message_id"], "wamid.ok123")

    def test_process_once_creates_outbound_message(self):
        w, repo, _, conn = _make_worker()
        import app.whatsapp.repository as repo_mod
        contact = repo.create_or_update_contact(wa_id="wa_conv")
        conv = repo.create_or_get_open_conversation(contact.id)
        repo.enqueue_outbound_message(
            recipient_wa_id="wa_conv", message_type="text",
            payload_json={"messaging_product": "whatsapp", "to": "wa_conv", "type": "text", "text": {"body": "hi"}},
            conversation_id=conv.id,
        )
        w.process_once(limit=10)
        msgs = repo.conn.execute(
            "SELECT direction, delivery_status, text_body FROM whatsapp_messages WHERE conversation_id = ?",
            (conv.id,),
        ).fetchall()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["direction"], "outbound")
        self.assertEqual(msgs[0]["delivery_status"], "sent")

    def test_retryable_failure_releases_item(self):
        def fail_transport(url, data, headers, timeout):
            return 429, b"{}", {"Retry-After": "10"}
        w, repo, _, _ = _make_worker(transport=fail_transport)
        repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text",
            payload_json={"body": "hi"},
        )
        w.process_once(limit=10)
        rows = repo.conn.execute(
            "SELECT status, last_error FROM whatsapp_outbox"
        ).fetchall()
        self.assertEqual(rows[0]["status"], "pending")

    def test_permanent_failure(self):
        def fail_transport(url, data, headers, timeout):
            return 400, json.dumps({"error": {"code": 100, "message": "Bad"}}).encode("utf-8"), {}
        w, repo, _, _ = _make_worker(transport=fail_transport)
        repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text",
            payload_json={"body": "hi"},
        )
        w.process_once(limit=10)
        rows = repo.conn.execute(
            "SELECT status FROM whatsapp_outbox"
        ).fetchall()
        self.assertEqual(rows[0]["status"], "failed")

    def test_max_attempts_exceeded(self):
        attempts = 0
        def fail_transport(url, data, headers, timeout):
            nonlocal attempts
            attempts += 1
            return 500, b"{}", {}
        cfg = _make_config(outbox_max_attempts=1, outbox_retry_base_seconds=1)
        repo_conn = _make_connection()
        repo = WhatsAppRepository(repo_conn)
        client = WhatsAppCloudClient(config=cfg, transport=fail_transport)
        w = WhatsAppOutboxWorker(repo=repo, client=client, config=cfg)
        repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text",
            payload_json={"body": "hi"},
        )
        w.process_once(limit=10)
        # After max attempts on retryable, should be failed
        rows = repo.conn.execute("SELECT status FROM whatsapp_outbox").fetchall()
        self.assertEqual(rows[0]["status"], "failed")

    def test_disabled_whatsapp_skips(self):
        cfg = _make_config(enabled=False)
        repo_conn = _make_connection()
        repo = WhatsAppRepository(repo_conn)
        client = WhatsAppCloudClient(config=cfg, transport=_ok_transport)
        w = WhatsAppOutboxWorker(repo=repo, client=client, config=cfg)
        repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text", payload_json={"body": "hi"},
        )
        count = w.process_once(limit=10)
        self.assertEqual(count, 0)

    def test_backoff_computation(self):
        cfg = _make_config(outbox_retry_base_seconds=5, outbox_retry_max_seconds=900)
        repo_conn = _make_connection()
        repo = WhatsAppRepository(repo_conn)
        client = WhatsAppCloudClient(config=cfg, transport=_ok_transport)
        w = WhatsAppOutboxWorker(repo=repo, client=client, config=cfg)
        self.assertAlmostEqual(w._compute_backoff(1), 5, delta=6)
        self.assertAlmostEqual(w._compute_backoff(2), 10, delta=6)
        self.assertAlmostEqual(w._compute_backoff(3), 20, delta=6)

    def test_invalid_payload_fails_permanently(self):
        w, repo, _, _ = _make_worker()
        repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text",
            payload_json="not valid json",
        )
        w.process_once(limit=10)
        rows = repo.conn.execute("SELECT status FROM whatsapp_outbox").fetchall()
        self.assertEqual(rows[0]["status"], "failed")


class TestFutureItemNotClaimed(unittest.TestCase):
    def test_future_item_not_claimed(self):
        w, repo, _, _ = _make_worker()
        repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text", payload_json={"body": "hi"},
        )
        repo.conn.execute(
            "UPDATE whatsapp_outbox SET next_attempt_at = '2099-01-01T00:00:00'"
        )
        repo.conn.commit()
        items = repo.claim_pending_outbox_items(worker_id="w1", limit=10)
        self.assertEqual(len(items), 0)


class TestSentNotReSent(unittest.TestCase):
    def test_sent_not_reclaimed(self):
        w, repo, _, _ = _make_worker()
        repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text", payload_json={"body": "hi"},
        )
        repo.conn.execute("UPDATE whatsapp_outbox SET status = 'sent'")
        repo.conn.commit()
        items = repo.claim_pending_outbox_items(worker_id="w1", limit=10)
        self.assertEqual(len(items), 0)


class TestFailedNotReSent(unittest.TestCase):
    def test_failed_not_reclaimed(self):
        w, repo, _, _ = _make_worker()
        repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text", payload_json={"body": "hi"},
        )
        repo.conn.execute("UPDATE whatsapp_outbox SET status = 'failed'")
        repo.conn.commit()
        items = repo.claim_pending_outbox_items(worker_id="w1", limit=10)
        self.assertEqual(len(items), 0)


class TestCancelledNotReSent(unittest.TestCase):
    def test_cancelled_not_reclaimed(self):
        w, repo, _, _ = _make_worker()
        repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text", payload_json={"body": "hi"},
        )
        repo.conn.execute("UPDATE whatsapp_outbox SET status = 'cancelled'")
        repo.conn.commit()
        items = repo.claim_pending_outbox_items(worker_id="w1", limit=10)
        self.assertEqual(len(items), 0)


class TestCancelItem(unittest.TestCase):
    def test_cancel_pending_item(self):
        w, repo, _, _ = _make_worker()
        item = repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text", payload_json={"body": "hi"},
        )
        ok = repo.cancel_outbox_item(item.id)
        self.assertTrue(ok)
        rows = repo.conn.execute("SELECT status FROM whatsapp_outbox WHERE id = ?", (item.id,)).fetchall()
        self.assertEqual(rows[0]["status"], "cancelled")

    def test_cancel_sent_fails(self):
        w, repo, _, _ = _make_worker()
        item = repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text", payload_json={"body": "hi"},
        )
        repo.conn.execute("UPDATE whatsapp_outbox SET status = 'sent' WHERE id = ?", (item.id,))
        repo.conn.commit()
        ok = repo.cancel_outbox_item(item.id)
        self.assertFalse(ok)


class TestRecoverStaleProcessing(unittest.TestCase):
    def test_recover_stale_items(self):
        w, repo, _, _ = _make_worker()
        repo.enqueue_outbound_message(
            recipient_wa_id="wa_test", message_type="text", payload_json={"body": "hi"},
        )
        repo.conn.execute(
            "UPDATE whatsapp_outbox SET status = 'processing', "
            "worker_id = 'dead_w', processing_started_at = '2020-01-01T00:00:00'"
        )
        repo.conn.commit()
        recovered = repo.recover_stale_processing_items(processing_timeout_seconds=60)
        self.assertEqual(recovered, 1)
        rows = repo.conn.execute("SELECT status FROM whatsapp_outbox").fetchall()
        self.assertEqual(rows[0]["status"], "pending")


class TestWorkerLifecycle(unittest.TestCase):
    def setUp(self):
        self.w, self.repo, self.client, self.conn = _make_worker()

    def tearDown(self):
        try:
            self.w.stop()
        except Exception:
            pass

    def test_double_start_safe(self):
        self.assertTrue(self.w.start())
        self.assertTrue(self.w.start())

    def test_double_stop_safe(self):
        self.w.start()
        self.assertTrue(self.w.stop())
        self.assertFalse(self.w.stop())

    def test_is_running(self):
        self.assertFalse(self.w.is_running)
        self.w.start()
        self.assertTrue(self.w.is_running)
        self.w.stop()
        self.assertFalse(self.w.is_running)


class TestBatchLimit(unittest.TestCase):
    def test_batch_limit_respected(self):
        w, repo, _, _ = _make_worker()
        for i in range(5):
            repo.enqueue_outbound_message(
                recipient_wa_id=f"wa_{i}", message_type="text",
                payload_json={"body": f"msg_{i}"},
            )
        items = repo.claim_pending_outbox_items(worker_id="w1", limit=3)
        self.assertEqual(len(items), 3)


class TestServiceWorkerWake(unittest.TestCase):
    def test_service_wakes_worker_on_queue(self):
        conn = _make_connection()
        repo = WhatsAppRepository(conn)
        svc = WhatsAppService(repo)
        cfg = _make_config()
        client = WhatsAppCloudClient(config=cfg, transport=_ok_transport)
        w = WhatsAppOutboxWorker(repo=repo, client=client, config=cfg)
        svc.set_worker(w)
        wake_calls = []
        original_wake = w.wake_up
        w.wake_up = lambda: wake_calls.append(1)
        svc.queue_text_message(recipient_wa_id="wa_test", text_body="hello")
        self.assertEqual(len(wake_calls), 1)

    def test_service_works_without_worker(self):
        conn = _make_connection()
        repo = WhatsAppRepository(conn)
        svc = WhatsAppService(repo)
        item = svc.queue_text_message(recipient_wa_id="wa_test", text_body="hello")
        self.assertIsNotNone(item.id)
