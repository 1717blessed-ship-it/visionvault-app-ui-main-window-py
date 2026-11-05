"""Configuración del módulo WhatsApp vía variables de entorno."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WhatsAppConfig:
    enabled: bool = False
    access_token: str = ""
    phone_number_id: str = ""
    business_account_id: str = ""
    verify_token: str = ""
    app_secret: str = ""
    api_version: str = "v22.0"
    webhook_port: int = 8767
    verify_signature: bool = True
    max_webhook_bytes: int = 1048576
    webhook_max_attempts: int = 5
    http_timeout_seconds: int = 15
    outbox_poll_seconds: float = 2.0
    outbox_batch_size: int = 20
    outbox_max_attempts: int = 5
    outbox_retry_base_seconds: int = 5
    outbox_retry_max_seconds: int = 900
    outbox_processing_timeout_seconds: int = 300

    @classmethod
    def from_env(cls) -> WhatsAppConfig:
        enabled_raw = os.environ.get("WHATSAPP_ENABLED", "false").strip().lower()
        enabled = enabled_raw in ("1", "true", "yes")
        port_raw = os.environ.get("WHATSAPP_WEBHOOK_PORT", "8767").strip()
        try:
            webhook_port = int(port_raw)
        except (ValueError, TypeError):
            webhook_port = 8767
        max_bytes_raw = os.environ.get("WHATSAPP_MAX_WEBHOOK_BYTES", "1048576").strip()
        try:
            max_webhook_bytes = int(max_bytes_raw)
        except (ValueError, TypeError):
            max_webhook_bytes = 1048576
        max_attempts_raw = os.environ.get("WHATSAPP_WEBHOOK_MAX_ATTEMPTS", "5").strip()
        try:
            webhook_max_attempts = int(max_attempts_raw)
        except (ValueError, TypeError):
            webhook_max_attempts = 5
        verify_raw = os.environ.get("WHATSAPP_VERIFY_SIGNATURE", "true").strip().lower()
        verify_signature = verify_raw in ("1", "true", "yes")

        def _int_env(key: str, default: int) -> int:
            raw = os.environ.get(key, str(default)).strip()
            try:
                return int(raw)
            except (ValueError, TypeError):
                return default

        def _float_env(key: str, default: float) -> float:
            raw = os.environ.get(key, str(default)).strip()
            try:
                return float(raw)
            except (ValueError, TypeError):
                return default

        return cls(
            enabled=enabled,
            access_token=os.environ.get("WHATSAPP_ACCESS_TOKEN", ""),
            phone_number_id=os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
            business_account_id=os.environ.get("WHATSAPP_BUSINESS_ACCOUNT_ID", ""),
            verify_token=os.environ.get("WHATSAPP_VERIFY_TOKEN", ""),
            app_secret=os.environ.get("WHATSAPP_APP_SECRET", ""),
            api_version=os.environ.get("WHATSAPP_API_VERSION", "v22.0"),
            webhook_port=webhook_port,
            verify_signature=verify_signature,
            max_webhook_bytes=max_webhook_bytes,
            webhook_max_attempts=webhook_max_attempts,
            http_timeout_seconds=_int_env("WHATSAPP_HTTP_TIMEOUT_SECONDS", 15),
            outbox_poll_seconds=_float_env("WHATSAPP_OUTBOX_POLL_SECONDS", 2.0),
            outbox_batch_size=_int_env("WHATSAPP_OUTBOX_BATCH_SIZE", 20),
            outbox_max_attempts=_int_env("WHATSAPP_OUTBOX_MAX_ATTEMPTS", 5),
            outbox_retry_base_seconds=_int_env("WHATSAPP_OUTBOX_RETRY_BASE_SECONDS", 5),
            outbox_retry_max_seconds=_int_env("WHATSAPP_OUTBOX_RETRY_MAX_SECONDS", 900),
            outbox_processing_timeout_seconds=_int_env("WHATSAPP_OUTBOX_PROCESSING_TIMEOUT_SECONDS", 300),
        )


_CONFIG_CACHE: WhatsAppConfig | None = None


def load_config(*, reload: bool = False) -> WhatsAppConfig:
    global _CONFIG_CACHE

    if _CONFIG_CACHE is None or reload:
        _load_dotenv()
        _CONFIG_CACHE = WhatsAppConfig.from_env()

    return _CONFIG_CACHE


def is_enabled() -> bool:
    return load_config().enabled


def _load_dotenv(path: str | Path | None = None) -> None:
    """Carga un archivo .env si existe (no requiere python-dotenv)."""
    if path is None:
        path = Path(__file__).resolve().parents[2] / ".env"

    env_file = Path(path)
    if not env_file.exists():
        return

    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()

        if value.startswith(('"', "'")) and value[0] == value[-1]:
            value = value[1:-1]

        if key not in os.environ:
            os.environ[key] = value