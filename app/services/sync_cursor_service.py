"""Servicio de cursor opaco para sincronización incremental móvil."""

import base64
import json
from datetime import datetime
from typing import Any

from app.services.stage_catalog_service import GENERAL_WORKFLOW


class SyncCursorError(Exception):
    """Error en validación o procesamiento de cursor."""
    pass


class SyncCursorService:
    """Servicio para manejo de cursores opacos de sincronización."""

    CURSOR_VERSION = 1
    SUPPORTED_TYPES = frozenset({"jobs", "orders", "clients"})
    MAX_LIMIT = 500
    MIN_LIMIT = 1

    @staticmethod
    def encode_cursor(
        snapshot_until: str,
        types: set[str],
        limit: int,
        entity_cursors: dict[str, dict[str, Any]],
    ) -> str:
        """Codifica cursor interno a token Base64 URL-safe."""
        cursor_data = {
            "version": SyncCursorService.CURSOR_VERSION,
            "snapshot_until": snapshot_until,
            "types": sorted(types),
            "limit": limit,
            "entities": entity_cursors,
        }
        json_str = json.dumps(cursor_data, separators=(",", ":"))
        return base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")

    @staticmethod
    def decode_cursor(cursor_token: str) -> dict[str, Any]:
        """Decodifica token Base64 a cursor interno."""
        try:
            json_bytes = base64.urlsafe_b64decode(cursor_token.encode("utf-8"))
            cursor_data = json.loads(json_bytes.decode("utf-8"))
            SyncCursorService._validate_cursor_structure(cursor_data)
            return cursor_data
        except (ValueError, json.JSONDecodeError) as e:
            raise SyncCursorError("Invalid cursor format") from e

    @staticmethod
    def _validate_cursor_structure(cursor: dict[str, Any]) -> None:
        """Valida estructura interna del cursor."""
        required_fields = {"version", "snapshot_until", "types", "limit", "entities"}
        if not required_fields.issubset(cursor.keys()):
            raise SyncCursorError("Incomplete cursor structure")

        if cursor["version"] != SyncCursorService.CURSOR_VERSION:
            raise SyncCursorError("Unsupported cursor version")

        if not isinstance(cursor["types"], list):
            raise SyncCursorError("Invalid types format")

        if not SyncCursorService.SUPPORTED_TYPES.issuperset(cursor["types"]):
            raise SyncCursorError("Unknown entity type in cursor")

        if len(cursor["types"]) != len(set(cursor["types"])):
            raise SyncCursorError("Duplicate types in cursor")

        if not isinstance(cursor["limit"], int):
            raise SyncCursorError("Invalid limit format")

        if not (SyncCursorService.MIN_LIMIT <= cursor["limit"] <= SyncCursorService.MAX_LIMIT):
            raise SyncCursorError("Limit out of range")

        SyncCursorService._validate_timestamp(cursor["snapshot_until"])

        for entity_name, entity_cursor in cursor["entities"].items():
            if entity_name not in SyncCursorService.SUPPORTED_TYPES:
                raise SyncCursorError(f"Unknown entity: {entity_name}")
            SyncCursorService._validate_entity_cursor(entity_cursor)

    @staticmethod
    def _validate_entity_cursor(entity_cursor: dict[str, Any]) -> None:
        """Valida cursor de entidad individual."""
        if not isinstance(entity_cursor, dict):
            raise SyncCursorError("Invalid entity cursor format")

        required = {"updated_at", "id", "complete"}
        if not required.issubset(entity_cursor.keys()):
            raise SyncCursorError("Incomplete entity cursor")

        SyncCursorService._validate_timestamp(entity_cursor["updated_at"])

        if not isinstance(entity_cursor["id"], int) or entity_cursor["id"] < 0:
            raise SyncCursorError("Invalid entity ID")

        if not isinstance(entity_cursor["complete"], bool):
            raise SyncCursorError("Invalid complete flag")

    @staticmethod
    def _validate_timestamp(timestamp: str) -> None:
        """Valida formato de timestamp ISO 8601 naive."""
        try:
            datetime.fromisoformat(timestamp)
        except ValueError as e:
            raise SyncCursorError("Invalid timestamp format") from e

    @staticmethod
    def validate_timestamp_not_future(timestamp: str) -> None:
        """Valida que timestamp no sea futuro."""
        try:
            ts = datetime.fromisoformat(timestamp)
            if ts > datetime.now():
                raise SyncCursorError("Timestamp is in the future")
        except ValueError as e:
            raise SyncCursorError("Invalid timestamp format") from e

    @staticmethod
    def validate_types(types: list[str]) -> None:
        """Valida lista de tipos solicitados."""
        if not types:
            raise SyncCursorError("Types cannot be empty")

        if not SyncCursorService.SUPPORTED_TYPES.issuperset(types):
            raise SyncCursorError("Unknown entity type")

        if len(types) != len(set(types)):
            raise SyncCursorError("Duplicate types")

    @staticmethod
    def validate_limit(limit: int) -> None:
        """Valida límite de registros."""
        if not isinstance(limit, int):
            raise SyncCursorError("Invalid limit format")

        if not (SyncCursorService.MIN_LIMIT <= limit <= SyncCursorService.MAX_LIMIT):
            raise SyncCursorError("Limit out of range")

    @staticmethod
    def validate_cursor_compatibility(
        cursor: dict[str, Any],
        types: list[str] | None,
        limit: int | None,
    ) -> None:
        """Valida que cursor sea compatible con parámetros de solicitud."""
        if types is not None and set(cursor["types"]) != set(types):
            raise SyncCursorError("Cursor incompatible with requested types")

        if limit is not None and cursor["limit"] != limit:
            raise SyncCursorError("Cursor incompatible with requested limit")

    @staticmethod
    def create_initial_entity_cursor() -> dict[str, Any]:
        """Crea cursor inicial para entidad (sin posición)."""
        return {
            "updated_at": "",
            "id": 0,
            "complete": False,
        }

    @staticmethod
    def update_entity_cursor(
        entity_cursor: dict[str, Any],
        updated_at: str,
        record_id: int,
        has_more: bool,
    ) -> dict[str, Any]:
        """Actualiza cursor de entidad con última posición."""
        return {
            "updated_at": updated_at,
            "id": record_id,
            "complete": not has_more,
        }
