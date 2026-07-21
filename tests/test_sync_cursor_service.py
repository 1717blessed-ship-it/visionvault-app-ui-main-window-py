"""Tests para SyncCursorService - Servicio de cursor opaco."""

import pytest

from app.services.sync_cursor_service import SyncCursorError, SyncCursorService


class TestSyncCursorService:
    """Tests para encode/decode y validación de cursores."""

    def test_encode_decode_roundtrip(self):
        """Encode y decode deben ser inversos."""
        snapshot_until = "2026-07-21T17:30:00"
        types = {"jobs", "orders"}
        limit = 100
        entity_cursors = {
            "jobs": {"updated_at": "2026-07-21T17:25:00", "id": 143, "complete": False},
            "orders": {"updated_at": "2026-07-21T17:20:00", "id": 45, "complete": True},
        }

        token = SyncCursorService.encode_cursor(
            snapshot_until, types, limit, entity_cursors
        )
        decoded = SyncCursorService.decode_cursor(token)

        assert decoded["version"] == 1
        assert decoded["snapshot_until"] == snapshot_until
        assert set(decoded["types"]) == types
        assert decoded["limit"] == limit
        assert decoded["entities"]["jobs"]["id"] == 143
        assert decoded["entities"]["orders"]["complete"] is True

    def test_decode_invalid_base64(self):
        """Base64 inválido debe lanzar SyncCursorError."""
        with pytest.raises(SyncCursorError, match="Invalid cursor format"):
            SyncCursorService.decode_cursor("not_base64!!!")

    def test_decode_invalid_json(self):
        """JSON inválido debe lanzar SyncCursorError."""
        invalid_token = SyncCursorService.encode_cursor(
            "2026-07-21T17:30:00", {"jobs"}, 100, {}
        )
        # Corromper el token
        corrupted = invalid_token[:-5] + "XXXXX"
        with pytest.raises(SyncCursorError, match="Invalid cursor format"):
            SyncCursorService.decode_cursor(corrupted)

    def test_decode_missing_version(self):
        """Cursor sin versión debe fallar."""
        cursor_data = {"snapshot_until": "2026-07-21T17:30:00", "types": ["jobs"], "limit": 100, "entities": {}}
        import json, base64
        token = base64.urlsafe_b64encode(json.dumps(cursor_data).encode()).decode()
        with pytest.raises(SyncCursorError, match="Incomplete cursor structure"):
            SyncCursorService.decode_cursor(token)

    def test_decode_unsupported_version(self):
        """Versión no soportada debe fallar."""
        cursor_data = {
            "version": 999,
            "snapshot_until": "2026-07-21T17:30:00",
            "types": ["jobs"],
            "limit": 100,
            "entities": {},
        }
        import json, base64
        token = base64.urlsafe_b64encode(json.dumps(cursor_data).encode()).decode()
        with pytest.raises(SyncCursorError, match="Unsupported cursor version"):
            SyncCursorService.decode_cursor(token)

    def test_decode_invalid_types_format(self):
        """Types no lista debe fallar."""
        cursor_data = {
            "version": 1,
            "snapshot_until": "2026-07-21T17:30:00",
            "types": "jobs",  # Debe ser lista
            "limit": 100,
            "entities": {},
        }
        import json, base64
        token = base64.urlsafe_b64encode(json.dumps(cursor_data).encode()).decode()
        with pytest.raises(SyncCursorError, match="Invalid types format"):
            SyncCursorService.decode_cursor(token)

    def test_decode_unknown_entity_type(self):
        """Tipo de entidad desconocido debe fallar."""
        cursor_data = {
            "version": 1,
            "snapshot_until": "2026-07-21T17:30:00",
            "types": ["unknown_type"],
            "limit": 100,
            "entities": {},
        }
        import json, base64
        token = base64.urlsafe_b64encode(json.dumps(cursor_data).encode()).decode()
        with pytest.raises(SyncCursorError, match="Unknown entity type"):
            SyncCursorService.decode_cursor(token)

    def test_decode_duplicate_types(self):
        """Tipos duplicados deben fallar."""
        cursor_data = {
            "version": 1,
            "snapshot_until": "2026-07-21T17:30:00",
            "types": ["jobs", "jobs"],
            "limit": 100,
            "entities": {},
        }
        import json, base64
        token = base64.urlsafe_b64encode(json.dumps(cursor_data).encode()).decode()
        with pytest.raises(SyncCursorError, match="Duplicate types"):
            SyncCursorService.decode_cursor(token)

    def test_decode_invalid_limit(self):
        """Límite inválido debe fallar."""
        cursor_data = {
            "version": 1,
            "snapshot_until": "2026-07-21T17:30:00",
            "types": ["jobs"],
            "limit": "invalid",  # Debe ser int
            "entities": {},
        }
        import json, base64
        token = base64.urlsafe_b64encode(json.dumps(cursor_data).encode()).decode()
        with pytest.raises(SyncCursorError, match="Invalid limit format"):
            SyncCursorService.decode_cursor(token)

    def test_decode_limit_out_of_range(self):
        """Límite fuera de rango debe fallar."""
        cursor_data = {
            "version": 1,
            "snapshot_until": "2026-07-21T17:30:00",
            "types": ["jobs"],
            "limit": 999,  # > MAX_LIMIT
            "entities": {},
        }
        import json, base64
        token = base64.urlsafe_b64encode(json.dumps(cursor_data).encode()).decode()
        with pytest.raises(SyncCursorError, match="Limit out of range"):
            SyncCursorService.decode_cursor(token)

    def test_decode_invalid_timestamp(self):
        """Timestamp inválido debe fallar."""
        cursor_data = {
            "version": 1,
            "snapshot_until": "invalid-timestamp",
            "types": ["jobs"],
            "limit": 100,
            "entities": {},
        }
        import json, base64
        token = base64.urlsafe_b64encode(json.dumps(cursor_data).encode()).decode()
        with pytest.raises(SyncCursorError, match="Invalid timestamp format"):
            SyncCursorService.decode_cursor(token)

    def test_decode_invalid_entity_cursor(self):
        """Cursor de entidad inválido debe fallar."""
        cursor_data = {
            "version": 1,
            "snapshot_until": "2026-07-21T17:30:00",
            "types": ["jobs"],
            "limit": 100,
            "entities": {"jobs": "invalid"},  # Debe ser dict
        }
        import json, base64
        token = base64.urlsafe_b64encode(json.dumps(cursor_data).encode()).decode()
        with pytest.raises(SyncCursorError, match="Invalid entity cursor format"):
            SyncCursorService.decode_cursor(token)

    def test_decode_incomplete_entity_cursor(self):
        """Cursor de entidad incompleto debe fallar."""
        cursor_data = {
            "version": 1,
            "snapshot_until": "2026-07-21T17:30:00",
            "types": ["jobs"],
            "limit": 100,
            "entities": {"jobs": {"updated_at": "2026-07-21T17:25:00"}},  # Falta id y complete
        }
        import json, base64
        token = base64.urlsafe_b64encode(json.dumps(cursor_data).encode()).decode()
        with pytest.raises(SyncCursorError, match="Incomplete entity cursor"):
            SyncCursorService.decode_cursor(token)

    def test_decode_negative_entity_id(self):
        """ID negativo debe fallar."""
        cursor_data = {
            "version": 1,
            "snapshot_until": "2026-07-21T17:30:00",
            "types": ["jobs"],
            "limit": 100,
            "entities": {"jobs": {"updated_at": "2026-07-21T17:25:00", "id": -1, "complete": False}},
        }
        import json, base64
        token = base64.urlsafe_b64encode(json.dumps(cursor_data).encode()).decode()
        with pytest.raises(SyncCursorError, match="Invalid entity ID"):
            SyncCursorService.decode_cursor(token)

    def test_validate_timestamp_not_future(self):
        """Timestamp futuro debe fallar."""
        from datetime import datetime, timedelta
        future = (datetime.now() + timedelta(days=1)).isoformat(timespec="seconds")
        with pytest.raises(SyncCursorError, match="Timestamp is in the future"):
            SyncCursorService.validate_timestamp_not_future(future)

    def test_validate_timestamp_not_future_valid(self):
        """Timestamp pasado debe ser válido."""
        SyncCursorService.validate_timestamp_not_future("2026-07-20T00:00:00")

    def test_validate_types_empty(self):
        """Types vacío debe fallar."""
        with pytest.raises(SyncCursorError, match="Types cannot be empty"):
            SyncCursorService.validate_types([])

    def test_validate_types_unknown(self):
        """Tipo desconocido debe fallar."""
        with pytest.raises(SyncCursorError, match="Unknown entity type"):
            SyncCursorService.validate_types(["unknown"])

    def test_validate_types_duplicate(self):
        """Tipos duplicados deben fallar."""
        with pytest.raises(SyncCursorError, match="Duplicate types"):
            SyncCursorService.validate_types(["jobs", "jobs"])

    def test_validate_types_valid(self):
        """Tipos válidos deben pasar."""
        SyncCursorService.validate_types(["jobs", "orders", "clients"])

    def test_validate_limit_invalid_type(self):
        """Límite no entero debe fallar."""
        with pytest.raises(SyncCursorError, match="Invalid limit format"):
            SyncCursorService.validate_limit("invalid")

    def test_validate_limit_out_of_range_low(self):
        """Límite < MIN_LIMIT debe fallar."""
        with pytest.raises(SyncCursorError, match="Limit out of range"):
            SyncCursorService.validate_limit(0)

    def test_validate_limit_out_of_range_high(self):
        """Límite > MAX_LIMIT debe fallar."""
        with pytest.raises(SyncCursorError, match="Limit out of range"):
            SyncCursorService.validate_limit(501)

    def test_validate_limit_valid(self):
        """Límites válidos deben pasar."""
        SyncCursorService.validate_limit(1)
        SyncCursorService.validate_limit(100)
        SyncCursorService.validate_limit(500)

    def test_validate_cursor_compatibility_types_mismatch(self):
        """Cursor con types diferentes debe fallar."""
        cursor = {
            "version": 1,
            "snapshot_until": "2026-07-21T17:30:00",
            "types": ["jobs"],
            "limit": 100,
            "entities": {},
        }
        with pytest.raises(SyncCursorError, match="Cursor incompatible with requested types"):
            SyncCursorService.validate_cursor_compatibility(cursor, ["orders"], None)

    def test_validate_cursor_compatibility_limit_mismatch(self):
        """Cursor con limit diferente debe fallar."""
        cursor = {
            "version": 1,
            "snapshot_until": "2026-07-21T17:30:00",
            "types": ["jobs"],
            "limit": 100,
            "entities": {},
        }
        with pytest.raises(SyncCursorError, match="Cursor incompatible with requested limit"):
            SyncCursorService.validate_cursor_compatibility(cursor, None, 200)

    def test_validate_cursor_compatibility_valid(self):
        """Cursor compatible debe pasar."""
        cursor = {
            "version": 1,
            "snapshot_until": "2026-07-21T17:30:00",
            "types": ["jobs"],
            "limit": 100,
            "entities": {},
        }
        SyncCursorService.validate_cursor_compatibility(cursor, ["jobs"], 100)
        SyncCursorService.validate_cursor_compatibility(cursor, None, None)

    def test_create_initial_entity_cursor(self):
        """Cursor inicial debe tener valores por defecto."""
        cursor = SyncCursorService.create_initial_entity_cursor()
        assert cursor["updated_at"] == ""
        assert cursor["id"] == 0
        assert cursor["complete"] is False

    def test_update_entity_cursor(self):
        """Actualizar cursor debe reflejar nueva posición."""
        initial = SyncCursorService.create_initial_entity_cursor()
        updated = SyncCursorService.update_entity_cursor(
            initial, "2026-07-21T17:25:00", 143, has_more=True
        )
        assert updated["updated_at"] == "2026-07-21T17:25:00"
        assert updated["id"] == 143
        assert updated["complete"] is False  # has_more=True → complete=False

        updated_complete = SyncCursorService.update_entity_cursor(
            updated, "2026-07-21T17:30:00", 200, has_more=False
        )
        assert updated_complete["complete"] is True  # has_more=False → complete=True
