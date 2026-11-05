"""Configuración operativa remota para Doccione Mobile.

La configuración vive en ``app_settings`` para que Studio pueda cambiarla sin
recompilar la aplicación móvil. El servicio siempre devuelve un documento
completo y conservador: una clave ausente o inválida vuelve a los valores
seguros incluidos en la app.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Final

from app.services.stage_catalog_service import (
    get_all_stages_for_mobile,
    get_workflows_for_mobile,
)


RUNTIME_PREFIX: Final = "mobile_runtime."

DEFAULT_MATERIALS: Final[tuple[str, ...]] = (
    "Vinilo Full Color HD",
    "Vinilo Premium",
    "Vinilo Ploteado",
    "Resina 3D Premium",
)
DEFAULT_PAYMENT_METHODS: Final[tuple[str, ...]] = (
    "Efectivo",
    "Transferencia",
    "Mercado Pago",
    "Otro",
)
DEFAULT_STICKER_MODES: Final[tuple[str, ...]] = (
    "Plancha A4",
    "Plancha A5",
    "Franja",
    "Individuales",
)
DEFAULT_ORDER_STATUSES: Final[tuple[str, ...]] = (
    "Pendiente",
    "En producción",
    "Finalizado",
    "Entregado",
    "Cancelado",
    "Archivado",
)
DEFAULT_PRIORITIES: Final[tuple[tuple[int, str], ...]] = (
    (0, "Sin prisa"),
    (1, "Baja"),
    (2, "Media"),
    (3, "Alta"),
    (4, "Urgente"),
)
DEFAULT_FEATURES: Final[dict[str, bool]] = {
    "design_catalog": True,
    "product_catalog": True,
    "sticker_orders": True,
    "quick_edits": True,
    "payments": True,
    "push_notifications": True,
}


@dataclass(frozen=True)
class MobileRuntimeConfigService:
    """Lee y normaliza la configuración móvil almacenada por Studio."""

    connection: sqlite3.Connection

    def snapshot(self) -> dict[str, Any]:
        """Devuelve la configuración completa consumible por Flutter."""
        workflows = get_workflows_for_mobile()
        settings, updated_at = self._settings()
        page_size = self._integer(
            settings,
            "catalog_page_size",
            default=100,
            minimum=20,
            maximum=500,
        )

        features = {
            key: self._boolean(settings, f"feature.{key}", default)
            for key, default in DEFAULT_FEATURES.items()
        }
        materials = self._list(settings, "materials", DEFAULT_MATERIALS)
        payment_methods = self._list(
            settings, "payment_methods", DEFAULT_PAYMENT_METHODS
        )
        sticker_modes = [
            value
            for value in self._list(
                settings, "sticker_modes", DEFAULT_STICKER_MODES
            )
            if value in DEFAULT_STICKER_MODES
        ] or list(DEFAULT_STICKER_MODES)
        order_statuses = self._list(
            settings, "order_statuses", DEFAULT_ORDER_STATUSES
        )

        return {
            "config_version": 1,
            "updated_at": updated_at,
            "features": features,
            "announcement": {
                "enabled": self._boolean(settings, "announcement.enabled", False),
                "title": self._text(settings, "announcement.title", "", 120),
                "message": self._text(settings, "announcement.message", "", 800),
            },
            "maintenance": {
                "enabled": self._boolean(settings, "maintenance.enabled", False),
                "message": self._text(
                    settings,
                    "maintenance.message",
                    "Studio está en mantenimiento. Podés consultar datos, pero las "
                    "operaciones pueden estar temporalmente limitadas.",
                    800,
                ),
            },
            "compatibility": {
                "minimum_app_version": self._text(
                    settings, "minimum_app_version", "1.0.0", 32
                ),
                "recommended_app_version": self._text(
                    settings, "recommended_app_version", "1.0.2", 32
                ),
                "update_url": self._text(settings, "update_url", "", 500),
            },
            "catalog": {
                "page_size": page_size,
                "max_page_size": 500,
            },
            "references": {
                "stages": get_all_stages_for_mobile(),
                "workflows": workflows,
                "materials": materials,
                "payment_methods": payment_methods,
                "sticker_modes": sticker_modes,
                "order_statuses": order_statuses,
                "priorities": [
                    {"value": value, "label": label}
                    for value, label in DEFAULT_PRIORITIES
                ],
            },
        }

    def catalog_page_size(self) -> int:
        """Tamaño por defecto que también aprovechan APK antiguos."""
        settings, _ = self._settings()
        return self._integer(
            settings,
            "catalog_page_size",
            default=100,
            minimum=20,
            maximum=500,
        )

    def notification_text(
        self, event_type: str, title: str, message: str
    ) -> tuple[str, str]:
        """Aplica personalización segura a una notificación existente.

        Los valores vacíos no alteran el mensaje original. Los templates por
        tipo de evento aceptan ``{title}``, ``{message}`` y ``{event_type}``.
        Si un template tiene un placeholder inválido se conserva el original.
        """
        settings, _ = self._settings()
        clean_event = str(event_type or "").strip()
        context = {
            "title": str(title or ""),
            "message": str(message or ""),
            "event_type": clean_event,
        }
        event_prefix = f"notification.{clean_event}." if clean_event else ""
        title_template = (
            settings.get(f"{event_prefix}title")
            if event_prefix
            else None
        )
        message_template = (
            settings.get(f"{event_prefix}message")
            if event_prefix
            else None
        )
        resolved_title = self._format_template(title_template, context, context["title"])
        resolved_message = self._format_template(
            message_template, context, context["message"]
        )

        prefix = self._text(settings, "notification.title_prefix", "", 40)
        suffix = self._text(settings, "notification.message_suffix", "", 160)
        if prefix:
            resolved_title = f"{prefix} {resolved_title}".strip()
        if suffix:
            resolved_message = f"{resolved_message}\n{suffix}".strip()
        return resolved_title[:180], resolved_message[:1000]

    def _settings(self) -> tuple[dict[str, str], str]:
        try:
            rows = self.connection.execute(
                """SELECT setting_key, setting_value, updated_at
                     FROM app_settings
                    WHERE setting_key LIKE ?""",
                (f"{RUNTIME_PREFIX}%",),
            ).fetchall()
        except sqlite3.OperationalError as error:
            # Repositorios mínimos y bases antiguas pueden consultar
            # capabilities antes de ejecutar la migración general.
            if "no such table" in str(error).casefold():
                return {}, ""
            raise
        values: dict[str, str] = {}
        latest = ""
        for row in rows:
            key = str(row["setting_key"] if hasattr(row, "keys") else row[0])
            value = str(row["setting_value"] if hasattr(row, "keys") else row[1])
            changed = str(row["updated_at"] if hasattr(row, "keys") else row[2])
            values[key[len(RUNTIME_PREFIX) :]] = value
            latest = max(latest, changed)
        return values, latest

    @staticmethod
    def _boolean(settings: dict[str, str], key: str, default: bool) -> bool:
        raw = settings.get(key)
        if raw is None:
            return default
        normalized = raw.strip().casefold()
        if normalized in {"1", "true", "yes", "si", "sí", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return default

    @staticmethod
    def _text(
        settings: dict[str, str], key: str, default: str, maximum: int
    ) -> str:
        return str(settings.get(key, default) or "").strip()[:maximum]

    @staticmethod
    def _integer(
        settings: dict[str, str],
        key: str,
        *,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        try:
            value = int(settings.get(key, default))
        except (TypeError, ValueError):
            value = default
        return min(maximum, max(minimum, value))

    @staticmethod
    def _list(
        settings: dict[str, str], key: str, default: tuple[str, ...]
    ) -> list[str]:
        raw = settings.get(key)
        if raw is None:
            return list(default)
        try:
            decoded = json.loads(raw)
            candidates = decoded if isinstance(decoded, list) else []
        except json.JSONDecodeError:
            candidates = raw.replace("\r", "\n").replace(",", "\n").split("\n")
        values: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            clean = str(candidate or "").strip()[:120]
            folded = clean.casefold()
            if clean and folded not in seen:
                seen.add(folded)
                values.append(clean)
        return values or list(default)

    @staticmethod
    def _format_template(
        template: str | None, context: dict[str, str], fallback: str
    ) -> str:
        if not template:
            return fallback
        try:
            return str(template).format_map(context).strip() or fallback
        except (KeyError, ValueError):
            return fallback
