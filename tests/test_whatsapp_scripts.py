from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.whatsapp.config import WhatsAppConfig, _load_dotenv, load_config
from app.whatsapp.client import WhatsAppCloudClient


def _fake_transport_success(
    url: str, data: dict, headers: dict, timeout: float
) -> tuple[int, bytes, dict[str, str]]:
    resp = {"messaging_product": "whatsapp", "messages": [{"id": "wamid.fake_ok"}]}
    return 200, json.dumps(resp).encode("utf-8"), {}


def _fake_transport_error(
    url: str, data: dict, headers: dict, timeout: float
) -> tuple[int, bytes, dict[str, str]]:
    resp = {
        "error": {
            "code": 100,
            "message": "(#100) Param to is invalid",
            "error_data": {"details": "Invalid phone number"},
            "fbtrace_id": "fake_trace",
        }
    }
    return 400, json.dumps(resp).encode("utf-8"), {}


def _make_test_cfg(**overrides) -> WhatsAppConfig:
    base = WhatsAppConfig(
        enabled=True,
        access_token="test_token_12345",
        phone_number_id="pn_test_999",
        business_account_id="biz_test_abc",
        api_version="v22.0",
        verify_token="verify_test",
        app_secret="app_secret_test",
        webhook_port=8767,
        verify_signature=True,
        http_timeout_seconds=30,
            outbox_poll_seconds=2.0,
        outbox_batch_size=10,
        outbox_max_attempts=5,
        outbox_retry_base_seconds=10,
        outbox_retry_max_seconds=600,
        outbox_processing_timeout_seconds=300,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


class TestWhatsAppSendScriptCheckMode(unittest.TestCase):
    def test_check_output_format(self):
        from scripts.test_whatsapp_send import cmd_check

        cfg = _make_test_cfg()
        try:
            cmd_check(cfg)
        except SystemExit:
            self.fail("cmd_check raised SystemExit")

    def test_check_disabled_output(self):
        from scripts.test_whatsapp_send import cmd_check

        cfg = _make_test_cfg(enabled=False)
        try:
            cmd_check(cfg)
        except SystemExit:
            self.fail("cmd_check raised SystemExit")


class TestWhatsAppSendScriptDryRun(unittest.TestCase):
    def test_dry_run_requires_to_and_text(self):
        from scripts.test_whatsapp_send import cmd_dry_run

        class Args:
            to = "521234567890"
            text = "Hola mundo"
            preview_url = False

        cfg = _make_test_cfg()
        try:
            cmd_dry_run(cfg, Args())
        except SystemExit:
            self.fail("cmd_dry_run raised SystemExit")

    def test_dry_run_with_preview_url(self):
        from scripts.test_whatsapp_send import cmd_dry_run

        class Args:
            to = "521234567890"
            text = "Hola mundo"
            preview_url = True

        cfg = _make_test_cfg()
        try:
            cmd_dry_run(cfg, Args())
        except SystemExit:
            self.fail("cmd_dry_run raised SystemExit")


class TestWhatsAppSendScriptSendReal(unittest.TestCase):
    def test_send_real_requires_confirm(self):
        from scripts.test_whatsapp_send import cmd_send_real

        class Args:
            to = "521234567890"
            text = "Hola"
            preview_url = False
            confirm = ""

        cfg = _make_test_cfg()
        with self.assertRaises(SystemExit):
            cmd_send_real(cfg, Args())

    def test_send_real_with_wrong_confirm(self):
        from scripts.test_whatsapp_send import cmd_send_real

        class Args:
            to = "521234567890"
            text = "Hola"
            preview_url = False
            confirm = "NO"

        cfg = _make_test_cfg()
        with self.assertRaises(SystemExit):
            cmd_send_real(cfg, Args())

    def test_send_real_success_with_fake_transport(self):
        from scripts.test_whatsapp_send import cmd_send_real

        class Args:
            to = "521234567890"
            text = "Hola desde test"
            preview_url = False
            confirm = "SEND"

        cfg = _make_test_cfg()
        result = cmd_send_real(cfg, Args(), transport=_fake_transport_success)
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        self.assertEqual(result["http_status"], 200)
        self.assertEqual(result["whatsapp_message_id"], "wamid.fake_ok")

    def test_send_real_failure_with_fake_transport(self):
        from scripts.test_whatsapp_send import cmd_send_real

        class Args:
            to = "521234567890"
            text = "Hola"
            preview_url = False
            confirm = "SEND"

        cfg = _make_test_cfg()
        result = cmd_send_real(cfg, Args(), transport=_fake_transport_error)
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        self.assertEqual(result["http_status"], 400)
        self.assertEqual(result["error_code"], "100")

    def test_send_real_without_enabled(self):
        from scripts.test_whatsapp_send import cmd_send_real

        class Args:
            to = "521234567890"
            text = "Hola"
            preview_url = False
            confirm = "SEND"

        cfg = _make_test_cfg(enabled=False)
        with self.assertRaises(SystemExit):
            cmd_send_real(cfg, Args())


class TestWhatsAppSendScriptOutputReport(unittest.TestCase):
    def test_output_report_creates_file(self):
        from scripts.test_whatsapp_send import cmd_send_real

        class Args:
            to = "521234567890"
            text = "Test report"
            preview_url = False
            confirm = "SEND"

        cfg = _make_test_cfg()
        result = cmd_send_real(cfg, Args(), transport=_fake_transport_success)
        self.assertIn("timestamp", result)
        self.assertIn("recipient_last4", result)
        self.assertEqual(result["recipient_last4"], "7890")


class TestWhatsAppCheckWebhookScript(unittest.TestCase):
    def test_check_local_success(self):
        from scripts.check_whatsapp_webhook import cmd_check_local

        cfg = _make_test_cfg()
        try:
            cmd_check_local(cfg)
        except SystemExit:
            self.fail("cmd_check_local raised SystemExit")

    def test_status_without_db(self):
        from scripts.check_whatsapp_webhook import cmd_status

        cfg = _make_test_cfg()
        original_exists = Path.exists

        def fake_exists(self_):
            return False

        try:
            Path.exists = fake_exists
            try:
                cmd_status(cfg)
            finally:
                Path.exists = original_exists
        except SystemExit:
            self.fail("cmd_status raised SystemExit")


class TestWhatsAppSendScriptSendViaOutbox(unittest.TestCase):
    def test_send_via_outbox_requires_confirm(self):
        from scripts.test_whatsapp_send import cmd_send_via_outbox

        class Args:
            to = "521234567890"
            text = "Hola"
            confirm = ""

        cfg = _make_test_cfg()
        with self.assertRaises(SystemExit):
            cmd_send_via_outbox(cfg, Args())

    def test_send_via_outbox_with_wrong_confirm(self):
        from scripts.test_whatsapp_send import cmd_send_via_outbox

        class Args:
            to = "521234567890"
            text = "Hola"
            confirm = "NO"

        cfg = _make_test_cfg()
        with self.assertRaises(SystemExit):
            cmd_send_via_outbox(cfg, Args())


if __name__ == "__main__":
    unittest.main()
