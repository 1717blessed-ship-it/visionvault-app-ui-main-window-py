"""Registro estructurado y rotativo para diagnóstico operativo."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key in ("component", "event", "entity_type", "entity_id", "duration_ms"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(base_dir: str | Path, *, level: int = logging.INFO) -> Path:
    log_dir = Path(base_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "doccione.jsonl"
    root = logging.getLogger()
    if not any(getattr(handler, "_doccione_handler", False) for handler in root.handlers):
        handler = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
        handler._doccione_handler = True  # type: ignore[attr-defined]
        handler.setFormatter(JsonLineFormatter())
        root.addHandler(handler)
    root.setLevel(level)
    return log_path


def record_health(connection, component: str, level: str, message: str, details: dict[str, Any] | None = None) -> None:
    logger = logging.getLogger("doccione.health")
    numeric = getattr(logging, str(level).upper(), logging.INFO)
    logger.log(numeric, message, extra={"component": component, "event": "health"})
    try:
        connection.execute(
            """INSERT INTO app_health_events(component,level,message,details_json,created_at)
               VALUES(?,?,?,?,?)""",
            (component, str(level).upper(), message, json.dumps(details or {}, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")),
        )
        connection.commit()
    except Exception:
        logger.debug("No se pudo persistir el evento de salud", exc_info=True)
