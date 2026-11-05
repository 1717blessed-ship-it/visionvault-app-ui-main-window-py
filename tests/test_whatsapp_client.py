from __future__ import annotations

import io
import json
import unittest
from typing import Any
from urllib.error import HTTPError

from app.whatsapp.client import WhatsAppCloudClient
from app.whatsapp.config import WhatsAppConfig
from app.whatsapp.models import WhatsAppSendResult


def _make_http_error(url: str, code: int, body: dict | None = None, headers: dict | None = None) -> HTTPError:
    body_bytes = json.dumps(body or {}).encode("utf-8")
    fp = io.BytesIO(body_bytes)
    return HTTPError(url, code, f"HTTP {code}", headers or {}, fp)


def _ok_transport(
    url: str, data: dict[str, Any], headers: dict[str, str], timeout: float
) -> tuple[int, bytes, dict[str, str]]:
    resp = {
        "messaging_product": "whatsapp",
        "messages": [{"id": "wamid.ok123"}],
    }
    return 200, json.dumps(resp).encode("utf-8"), {}


def _ok_no_id_transport(
    url: str, data: dict[str, Any], headers: dict[str, str], timeout: float
) -> tuple[int, bytes, dict[str, str]]:
    resp = {"messaging_product": "whatsapp", "messages": []}
    return 200, json.dumps(resp).encode("utf-8"), {}


def _make_client(
    transport=None,
    enabled=True,
    access_token="test_token",
    phone_number_id="pn_123",
    **kwargs,
) -> WhatsAppCloudClient:
    cfg = WhatsAppConfig(
        enabled=enabled,
        access_token=access_token,
        phone_number_id=phone_number_id,
        **kwargs,
    )
    return WhatsAppCloudClient(config=cfg, transport=transport)


class TestClientURL(unittest.TestCase):
    def test_url_uses_api_version_and_phone_number_id(self):
        client = _make_client(transport=_ok_transport)
        cfg = client._config
        expected = f"https://graph.facebook.com/{cfg.api_version}/{cfg.phone_number_id}/messages"
        result = client.send_text_message("wa_id", "hello")
        self.assertTrue(result.success)

    def test_url_with_custom_phone_number_id(self):
        client = _make_client(transport=_ok_transport)
        cfg = client._config
        expected = f"https://graph.facebook.com/{cfg.api_version}/custom_pn/messages"
        result = client.send_text_message("wa_id", "hello", phone_number_id="custom_pn")
        self.assertTrue(result.success)

    def test_api_version_configurable(self):
        client = _make_client(transport=_ok_transport, api_version="v99.0")
        self.assertEqual(client._config.api_version, "v99.0")


class TestClientHeaders(unittest.TestCase):
    def test_headers_include_bearer_token(self):
        captured: list[dict] = []

        def capture(url, data, headers, timeout):
            captured.append(headers)
            return _ok_transport(url, data, headers, timeout)

        client = _make_client(transport=capture, access_token="secret_token_123")
        client.send_text_message("wa_id", "hello")
        self.assertEqual(captured[0]["Authorization"], "Bearer secret_token_123")
        self.assertEqual(captured[0]["Content-Type"], "application/json")


class TestSendTextMessage(unittest.TestCase):
    def test_success(self):
        client = _make_client(transport=_ok_transport)
        result = client.send_text_message("wa_recipient", "Hello!")
        self.assertTrue(result.success)
        self.assertEqual(result.whatsapp_message_id, "wamid.ok123")
        self.assertEqual(result.http_status, 200)

    def test_empty_recipient_raises(self):
        client = _make_client(transport=_ok_transport)
        with self.assertRaises(ValueError):
            client.send_text_message("", "hello")

    def test_empty_text_raises(self):
        client = _make_client(transport=_ok_transport)
        with self.assertRaises(ValueError):
            client.send_text_message("wa_id", "")

    def test_reply_to_message(self):
        captured: list[dict] = []

        def capture(url, data, headers, timeout):
            captured.append(data)
            return _ok_transport(url, data, headers, timeout)

        client = _make_client(transport=capture)
        client.send_text_message("wa_id", "Reply text", reply_to_message_id="orig_123")
        self.assertIn("context", captured[0])
        self.assertEqual(captured[0]["context"]["message_id"], "orig_123")

    def test_preview_url_true(self):
        captured: list[dict] = []

        def capture(url, data, headers, timeout):
            captured.append(data)
            return _ok_transport(url, data, headers, timeout)

        client = _make_client(transport=capture)
        client.send_text_message("wa_id", "https://example.com", preview_url=True)
        self.assertTrue(captured[0]["text"]["preview_url"])


class TestSendTemplateMessage(unittest.TestCase):
    def test_success(self):
        client = _make_client(transport=_ok_transport)
        result = client.send_template_message("wa_id", "hello_world", "en")
        self.assertTrue(result.success)

    def test_with_components(self):
        captured: list[dict] = []

        def capture(url, data, headers, timeout):
            captured.append(data)
            return _ok_transport(url, data, headers, timeout)

        client = _make_client(transport=capture)
        components = [{"type": "body", "parameters": [{"type": "text", "text": "Valor"}]}]
        client.send_template_message("wa_id", "hello_world", "es", components=components)
        self.assertEqual(captured[0]["template"]["components"], components)

    def test_empty_template_name_raises(self):
        client = _make_client(transport=_ok_transport)
        with self.assertRaises(ValueError):
            client.send_template_message("wa_id", "", "en")

    def test_empty_language_raises(self):
        client = _make_client(transport=_ok_transport)
        with self.assertRaises(ValueError):
            client.send_template_message("wa_id", "name", "")


class TestSendImageMessage(unittest.TestCase):
    def test_with_media_id(self):
        client = _make_client(transport=_ok_transport)
        result = client.send_image_message("wa_id", media_id="img_123")
        self.assertTrue(result.success)

    def test_with_link(self):
        client = _make_client(transport=_ok_transport)
        result = client.send_image_message("wa_id", link="https://example.com/img.jpg")
        self.assertTrue(result.success)

    def test_both_id_and_link_raises(self):
        client = _make_client(transport=_ok_transport)
        with self.assertRaises(ValueError):
            client.send_image_message("wa_id", media_id="img_1", link="https://example.com/img.jpg")

    def test_neither_id_nor_link_raises(self):
        client = _make_client(transport=_ok_transport)
        with self.assertRaises(ValueError):
            client.send_image_message("wa_id")

    def test_with_caption(self):
        captured: list[dict] = []
        def capture(url, data, headers, timeout):
            captured.append(data)
            return _ok_transport(url, data, headers, timeout)
        client = _make_client(transport=capture)
        client.send_image_message("wa_id", media_id="img_1", caption="Foto")
        self.assertEqual(captured[0]["image"]["caption"], "Foto")


class TestSendDocumentMessage(unittest.TestCase):
    def test_with_filename(self):
        captured: list[dict] = []
        def capture(url, data, headers, timeout):
            captured.append(data)
            return _ok_transport(url, data, headers, timeout)
        client = _make_client(transport=capture)
        client.send_document_message("wa_id", media_id="doc_1", filename="reporte.pdf")
        self.assertEqual(captured[0]["document"]["filename"], "reporte.pdf")

    def test_with_caption(self):
        captured: list[dict] = []
        def capture(url, data, headers, timeout):
            captured.append(data)
            return _ok_transport(url, data, headers, timeout)
        client = _make_client(transport=capture)
        client.send_document_message("wa_id", media_id="doc_1", caption="Documento")
        self.assertEqual(captured[0]["document"]["caption"], "Documento")


class TestSendAudioMessage(unittest.TestCase):
    def test_success_with_media_id(self):
        client = _make_client(transport=_ok_transport)
        result = client.send_audio_message("wa_id", media_id="audio_1")
        self.assertTrue(result.success)


class TestSendVideoMessage(unittest.TestCase):
    def test_success_with_media_id(self):
        client = _make_client(transport=_ok_transport)
        result = client.send_video_message("wa_id", media_id="vid_1")
        self.assertTrue(result.success)

    def test_with_caption(self):
        captured: list[dict] = []
        def capture(url, data, headers, timeout):
            captured.append(data)
            return _ok_transport(url, data, headers, timeout)
        client = _make_client(transport=capture)
        client.send_video_message("wa_id", media_id="vid_1", caption="Video")
        self.assertEqual(captured[0]["video"]["caption"], "Video")


class TestSendStickerMessage(unittest.TestCase):
    def test_success_with_media_id(self):
        client = _make_client(transport=_ok_transport)
        result = client.send_sticker_message("wa_id", media_id="sticker_1")
        self.assertTrue(result.success)


class TestSendLocationMessage(unittest.TestCase):
    def test_success(self):
        client = _make_client(transport=_ok_transport)
        result = client.send_location_message("wa_id", 19.4326, -99.1332)
        self.assertTrue(result.success)

    def test_with_name_and_address(self):
        captured: list[dict] = []
        def capture(url, data, headers, timeout):
            captured.append(data)
            return _ok_transport(url, data, headers, timeout)
        client = _make_client(transport=capture)
        client.send_location_message("wa_id", 19.43, -99.13, name="CDMX", address="Centro")
        self.assertEqual(captured[0]["location"]["name"], "CDMX")
        self.assertEqual(captured[0]["location"]["address"], "Centro")


class TestMarkAsRead(unittest.TestCase):
    def test_success(self):
        client = _make_client(transport=_ok_transport)
        result = client.mark_message_as_read("msg_123")
        self.assertTrue(result.success)

    def test_empty_message_id_raises(self):
        client = _make_client(transport=_ok_transport)
        with self.assertRaises(ValueError):
            client.mark_message_as_read("")


class TestSendRawPayload(unittest.TestCase):
    def test_success(self):
        client = _make_client(transport=_ok_transport)
        result = client.send_raw_payload({"messaging_product": "whatsapp", "type": "text", "text": {"body": "test"}})
        self.assertTrue(result.success)

    def test_custom_phone_number_id(self):
        captured: list[str] = []
        def capture(url, data, headers, timeout):
            captured.append(url)
            return _ok_transport(url, data, headers, timeout)
        client = _make_client(transport=capture)
        client.send_raw_payload({"type": "text"}, phone_number_id="custom_pn")
        self.assertIn("custom_pn", captured[0])


class TestSendSuccessWithoutMessageID(unittest.TestCase):
    def test_200_without_message_id(self):
        client = _make_client(transport=_ok_no_id_transport)
        result = client.send_text_message("wa_id", "hello")
        self.assertFalse(result.success)
        self.assertEqual(result.http_status, 200)
        self.assertIsNone(result.whatsapp_message_id)


class TestClientErrorClassification(unittest.TestCase):
    def test_timeout_error(self):
        def timeout_transport(url, data, headers, timeout):
            raise TimeoutError("timed out")
        client = _make_client(transport=timeout_transport)
        result = client.send_text_message("wa_id", "hello")
        self.assertFalse(result.success)
        self.assertTrue(result.retryable)

    def test_connection_error(self):
        def conn_error(url, data, headers, timeout):
            from urllib.error import URLError
            raise URLError("connection refused")
        client = _make_client(transport=conn_error)
        result = client.send_text_message("wa_id", "hello")
        self.assertFalse(result.success)
        self.assertTrue(result.retryable)

    def test_http_400(self):
        def _transport(url, data, headers, timeout):
            raise _make_http_error(url, 400, body={"error": {"code": 100, "message": "Bad request"}})
        client = _make_client(transport=_transport)
        result = client.send_text_message("wa_id", "hello")
        self.assertFalse(result.success)
        self.assertFalse(result.retryable)
        self.assertEqual(result.http_status, 400)

    def test_http_401(self):
        def _transport(url, data, headers, timeout):
            raise _make_http_error(url, 401)
        client = _make_client(transport=_transport)
        result = client.send_text_message("wa_id", "hello")
        self.assertFalse(result.success)
        self.assertFalse(result.retryable)

    def test_http_403(self):
        def _transport(url, data, headers, timeout):
            raise _make_http_error(url, 403)
        client = _make_client(transport=_transport)
        result = client.send_text_message("wa_id", "hello")
        self.assertFalse(result.success)
        self.assertFalse(result.retryable)

    def test_http_429_with_retry_after(self):
        def _transport(url, data, headers, timeout):
            raise _make_http_error(url, 429, headers={"Retry-After": "120"})
        client = _make_client(transport=_transport)
        result = client.send_text_message("wa_id", "hello")
        self.assertFalse(result.success)
        self.assertTrue(result.retryable)
        self.assertEqual(result.retry_after_seconds, 120)

    def test_http_500(self):
        def _transport(url, data, headers, timeout):
            raise _make_http_error(url, 500)
        client = _make_client(transport=_transport)
        result = client.send_text_message("wa_id", "hello")
        self.assertFalse(result.success)
        self.assertTrue(result.retryable)


class TestClientConfigValidation(unittest.TestCase):
    def test_missing_access_token_raises(self):
        cfg = WhatsAppConfig(enabled=True, access_token="", phone_number_id="pn_123")
        client = WhatsAppCloudClient(config=cfg, transport=_ok_transport)
        with self.assertRaises(ValueError):
            client.send_text_message("wa_id", "hello")

    def test_missing_phone_number_id_raises(self):
        cfg = WhatsAppConfig(enabled=True, access_token="tok", phone_number_id="")
        client = WhatsAppCloudClient(config=cfg, transport=_ok_transport)
        with self.assertRaises(ValueError):
            client.send_text_message("wa_id", "hello")


class TestTransportInjection(unittest.TestCase):
    def test_custom_transport_called(self):
        calls = []
        def custom(url, data, headers, timeout):
            calls.append((url, data, headers, timeout))
            return _ok_transport(url, data, headers, timeout)
        client = _make_client(transport=custom)
        client.send_text_message("wa_id", "hello")
        self.assertEqual(len(calls), 1)

    def test_token_not_in_result(self):
        captured_headers: list[dict] = []
        def capture(url, data, headers, timeout):
            captured_headers.append(headers)
            return _ok_transport(url, data, headers, timeout)
        client = _make_client(transport=capture, access_token="super_secret")
        result = client.send_text_message("wa_id", "hello")
        result_str = json.dumps(result.response_json) if result.response_json else ""
        self.assertNotIn("super_secret", result_str)
        self.assertNotIn("super_secret", result.error_message or "")
