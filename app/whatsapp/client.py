from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from app.whatsapp.config import WhatsAppConfig
from app.whatsapp.models import WhatsAppSendResult

logger = logging.getLogger(__name__)

HttpTransport = Callable[
    [str, dict[str, Any], dict[str, str], float],
    tuple[int, bytes, dict[str, str]],
]


def _default_transport(
    url: str,
    data: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
) -> tuple[int, bytes, dict[str, str]]:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    resp = urllib.request.urlopen(req, timeout=timeout)
    resp_headers = dict(resp.headers)
    raw = resp.read()
    return resp.status, raw, resp_headers


class WhatsAppCloudClient:
    def __init__(
        self,
        config: WhatsAppConfig,
        transport: HttpTransport | None = None,
    ):
        self._config = config
        self._transport = transport or _default_transport

    def _validate_config(self) -> None:
        cfg = self._config
        if not cfg.access_token:
            raise ValueError("WHATSAPP_ACCESS_TOKEN not configured")
        if not cfg.phone_number_id:
            raise ValueError("WHATSAPP_PHONE_NUMBER_ID not configured")

    def _build_url(self, phone_number_id: str | None = None) -> str:
        pn_id = phone_number_id or self._config.phone_number_id
        base = f"https://graph.facebook.com/{self._config.api_version}/{pn_id}/messages"
        return base

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.access_token}",
            "Content-Type": "application/json",
        }

    def _do_request(
        self,
        payload: dict[str, Any],
        phone_number_id: str | None = None,
    ) -> WhatsAppSendResult:
        self._validate_config()
        url = self._build_url(phone_number_id)
        headers = self._build_headers()
        timeout = self._config.http_timeout_seconds

        try:
            status, raw, resp_headers = self._transport(url, payload, headers, timeout)
        except urllib.error.HTTPError as exc:
            code = exc.code
            body = exc.read() if hasattr(exc, "read") else b""
            exc_headers = {}
            if hasattr(exc, "headers"):
                exc_headers = {k.lower(): v for k, v in exc.headers.items()} if exc.headers else {}
            resp_json: dict[str, Any] | None = None
            try:
                resp_json = json.loads(body.decode("utf-8", errors="replace"))
            except Exception:
                pass
            error_data = resp_json.get("error", {}) if resp_json else {}
            error_code = str(error_data.get("code", "")) if error_data else ""
            error_message = error_data.get("message", str(exc)) if error_data else str(exc)
            retryable, retry_after = self._classify_error(code, exc_headers)
            logger.warning("HTTP %d from WhatsApp API: %s", code, error_message[:200])
            return WhatsAppSendResult(
                success=False,
                http_status=code,
                response_json=resp_json,
                error_code=error_code,
                error_message=error_message[:500],
                retryable=retryable,
                retry_after_seconds=retry_after,
            )
        except urllib.error.URLError as exc:
            reason = str(exc.reason) if hasattr(exc, "reason") else str(exc)
            logger.warning("Connection error to WhatsApp API: %s", reason[:200])
            return WhatsAppSendResult(
                success=False,
                http_status=0,
                error_message=f"Connection error: {reason[:500]}",
                retryable=True,
            )
        except TimeoutError:
            logger.warning("Timeout connecting to WhatsApp API")
            return WhatsAppSendResult(
                success=False,
                http_status=0,
                error_message="Timeout",
                retryable=True,
            )

        try:
            resp_json = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            logger.warning("Invalid JSON response from WhatsApp API")
            return WhatsAppSendResult(
                success=False,
                http_status=status,
                response_json=None,
                error_message="Invalid JSON response",
                retryable=True,
            )

        raw_messages = resp_json.get("messages") if isinstance(resp_json.get("messages"), list) else []
        wa_msg_id = raw_messages[0].get("id") if raw_messages else None

        if status == 200 and wa_msg_id:
            return WhatsAppSendResult(
                success=True,
                http_status=status,
                whatsapp_message_id=wa_msg_id,
                response_json=resp_json,
                retryable=False,
            )

        if status == 200 and not wa_msg_id:
            logger.warning("WhatsApp API returned 200 without message ID")
            return WhatsAppSendResult(
                success=False,
                http_status=status,
                response_json=resp_json,
                error_message="No message ID in response",
                retryable=False,
            )

        error_data = resp_json.get("error", {}) if resp_json else {}
        error_code = str(error_data.get("code", "")) if error_data else ""
        error_message = error_data.get("message", "Unknown error") if error_data else "Unknown error"
        retryable, retry_after = self._classify_error(status, resp_headers)
        logger.warning("WhatsApp API error %s: %s", error_code, str(error_message)[:200])
        return WhatsAppSendResult(
            success=False,
            http_status=status,
            response_json=resp_json,
            error_code=error_code,
            error_message=str(error_message)[:500],
            retryable=retryable,
            retry_after_seconds=retry_after,
        )

    @staticmethod
    def _classify_error(
        http_status: int,
        resp_headers: dict[str, str] | None = None,
    ) -> tuple[bool, int | None]:
        if http_status == 0:
            return True, None
        if http_status == 429:
            retry_after = None
            if resp_headers:
                raw = resp_headers.get("Retry-After") or resp_headers.get("retry-after")
                if raw:
                    try:
                        retry_after = int(raw)
                    except (ValueError, TypeError):
                        pass
            return True, retry_after
        if 500 <= http_status <= 599:
            return True, None
        return False, None

    def send_raw_payload(
        self,
        payload: dict[str, Any],
        phone_number_id: str | None = None,
    ) -> WhatsAppSendResult:
        return self._do_request(payload, phone_number_id=phone_number_id)

    def send_text_message(
        self,
        recipient_wa_id: str,
        text: str,
        preview_url: bool | None = None,
        reply_to_message_id: str | None = None,
        phone_number_id: str | None = None,
    ) -> WhatsAppSendResult:
        if not recipient_wa_id:
            raise ValueError("recipient_wa_id is required")
        if not text:
            raise ValueError("text is required")
        body: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_wa_id,
            "type": "text",
            "text": {"preview_url": bool(preview_url) if preview_url is not None else False, "body": text},
        }
        if reply_to_message_id:
            body.setdefault("context", {})["message_id"] = reply_to_message_id
        return self._do_request(body, phone_number_id=phone_number_id)

    def send_template_message(
        self,
        recipient_wa_id: str,
        template_name: str,
        language_code: str,
        components: list[dict[str, Any]] | None = None,
        phone_number_id: str | None = None,
    ) -> WhatsAppSendResult:
        if not recipient_wa_id:
            raise ValueError("recipient_wa_id is required")
        if not template_name:
            raise ValueError("template_name is required")
        if not language_code:
            raise ValueError("language_code is required")
        template: dict[str, Any] = {
            "name": template_name,
            "language": {"code": language_code},
        }
        if components:
            template["components"] = components
        body: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_wa_id,
            "type": "template",
            "template": template,
        }
        return self._do_request(body, phone_number_id=phone_number_id)

    def _send_media_message(
        self,
        recipient_wa_id: str,
        media_type: str,
        media_id: str | None = None,
        link: str | None = None,
        caption: str | None = None,
        filename: str | None = None,
        phone_number_id: str | None = None,
    ) -> WhatsAppSendResult:
        if not recipient_wa_id:
            raise ValueError("recipient_wa_id is required")
        if not media_id and not link:
            raise ValueError("media_id or link is required")
        if media_id and link:
            raise ValueError("Provide either media_id or link, not both")
        media: dict[str, Any] = {}
        if media_id:
            media["id"] = media_id
        if link:
            media["link"] = link
        if caption:
            media["caption"] = caption
        if filename and media_type == "document":
            media["filename"] = filename
        body: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_wa_id,
            "type": media_type,
            media_type: media,
        }
        return self._do_request(body, phone_number_id=phone_number_id)

    def send_image_message(
        self,
        recipient_wa_id: str,
        media_id: str | None = None,
        link: str | None = None,
        caption: str | None = None,
        phone_number_id: str | None = None,
    ) -> WhatsAppSendResult:
        return self._send_media_message(
            recipient_wa_id, "image", media_id=media_id, link=link,
            caption=caption, phone_number_id=phone_number_id,
        )

    def send_document_message(
        self,
        recipient_wa_id: str,
        media_id: str | None = None,
        link: str | None = None,
        filename: str | None = None,
        caption: str | None = None,
        phone_number_id: str | None = None,
    ) -> WhatsAppSendResult:
        return self._send_media_message(
            recipient_wa_id, "document", media_id=media_id, link=link,
            filename=filename, caption=caption, phone_number_id=phone_number_id,
        )

    def send_audio_message(
        self,
        recipient_wa_id: str,
        media_id: str | None = None,
        link: str | None = None,
        phone_number_id: str | None = None,
    ) -> WhatsAppSendResult:
        return self._send_media_message(
            recipient_wa_id, "audio", media_id=media_id, link=link,
            phone_number_id=phone_number_id,
        )

    def send_video_message(
        self,
        recipient_wa_id: str,
        media_id: str | None = None,
        link: str | None = None,
        caption: str | None = None,
        phone_number_id: str | None = None,
    ) -> WhatsAppSendResult:
        return self._send_media_message(
            recipient_wa_id, "video", media_id=media_id, link=link,
            caption=caption, phone_number_id=phone_number_id,
        )

    def send_sticker_message(
        self,
        recipient_wa_id: str,
        media_id: str | None = None,
        link: str | None = None,
        phone_number_id: str | None = None,
    ) -> WhatsAppSendResult:
        return self._send_media_message(
            recipient_wa_id, "sticker", media_id=media_id, link=link,
            phone_number_id=phone_number_id,
        )

    def send_location_message(
        self,
        recipient_wa_id: str,
        latitude: float,
        longitude: float,
        name: str | None = None,
        address: str | None = None,
        phone_number_id: str | None = None,
    ) -> WhatsAppSendResult:
        if not recipient_wa_id:
            raise ValueError("recipient_wa_id is required")
        location: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
        }
        if name:
            location["name"] = name
        if address:
            location["address"] = address
        body: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_wa_id,
            "type": "location",
            "location": location,
        }
        return self._do_request(body, phone_number_id=phone_number_id)

    def mark_message_as_read(
        self,
        message_id: str,
        phone_number_id: str | None = None,
    ) -> WhatsAppSendResult:
        if not message_id:
            raise ValueError("message_id is required")
        body: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        return self._do_request(body, phone_number_id=phone_number_id)
