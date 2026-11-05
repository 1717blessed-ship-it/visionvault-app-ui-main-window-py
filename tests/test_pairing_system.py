"""Tests para el sistema de emparejamiento de dispositivos móviles."""

import pytest
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

from app.events.event_repository import EventRepository


@pytest.fixture
def temp_db():
    """Crea una base de datos temporal para pruebas."""
    fd, path = tempfile.mkstemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    yield conn, path
    conn.close()
    # Forzar garbage collection para liberar el archivo en Windows
    import gc
    gc.collect()
    try:
        Path(path).unlink(missing_ok=True)
    except PermissionError:
        # En Windows, a veces el archivo no se libera inmediatamente
        pass


@pytest.fixture
def repo(temp_db):
    """Crea un EventRepository con base de datos temporal."""
    conn, _ = temp_db
    repo = EventRepository(conn)
    repo.create_tables()
    return repo


class TestPairingCodeSystem:
    """Tests para el sistema de códigos de emparejamiento."""

    def test_create_pairing_code(self, repo):
        """Test de generación de código de emparejamiento."""
        code = repo.create_pairing_code()
        assert len(code) == 6
        assert code.isdigit()

    def test_pairing_code_hash_storage(self, repo):
        """Test de que el código se almacena como hash, no en texto plano."""
        code = repo.create_pairing_code()
        
        # Verificar que el código no está almacenado en texto plano
        row = repo.conn.execute("SELECT * FROM pairing_codes").fetchone()
        assert row is not None
        assert row["code_hash"] != code  # El hash no debe ser igual al código
        assert len(row["code_hash"]) == 64  # SHA-256 produce 64 caracteres hex

    def test_validate_pairing_code_success(self, repo):
        """Test de validación de código correcto."""
        code = repo.create_pairing_code()
        result = repo.validate_pairing_code(code)
        assert result is not None
        assert result["used"] == 0

    def test_validate_pairing_code_invalid(self, repo):
        """Test de validación de código incorrecto."""
        result = repo.validate_pairing_code("000000")
        assert result is None

    def test_validate_pairing_code_expired(self, repo):
        """Test de código vencido."""
        # Crear un código expirado manualmente
        code_hash = repo._hash_code("123456")
        expired_time = (datetime.now() - timedelta(minutes=10)).isoformat(timespec="seconds")
        repo.conn.execute(
            "INSERT INTO pairing_codes(code_hash, installation_id, used, created_at, expires_at) VALUES(?, ?, 0, ?, ?)",
            (code_hash, "studio-principal", expired_time, expired_time),
        )
        repo.conn.commit()
        
        result = repo.validate_pairing_code("123456")
        assert result is None

    def test_consume_pairing_code_success(self, repo):
        """Test de consumo de código válido."""
        code = repo.create_pairing_code()
        success = repo.consume_pairing_code(code)
        assert success is True
        
        # Verificar que está marcado como usado
        row = repo.conn.execute("SELECT used FROM pairing_codes WHERE code_hash = ?", (repo._hash_code(code),)).fetchone()
        assert row["used"] == 1

    def test_consume_pairing_code_reused(self, repo):
        """Test de código reutilizado (no debe funcionar)."""
        code = repo.create_pairing_code()
        
        # Primera vez debe funcionar
        success1 = repo.consume_pairing_code(code)
        assert success1 is True
        
        # Segunda vez debe fallar
        success2 = repo.consume_pairing_code(code)
        assert success2 is False

    def test_register_device_with_pairing_success(self, repo):
        """Test de registro de dispositivo mediante código."""
        code = repo.create_pairing_code()
        success, message, device_id, session_token = repo.register_device_with_pairing(
            pairing_code=code,
            push_token="test_token_123",
            platform="android",
            device_name="Test Device",
        )
        
        assert success is True
        assert device_id is not None
        assert session_token
        assert "registrado" in message.lower()

    def test_register_device_with_pairing_invalid_code(self, repo):
        """Test de registro con código inválido."""
        success, message, device_id, session_token = repo.register_device_with_pairing(
            pairing_code="000000",
            push_token="test_token_123",
            platform="android",
        )
        
        assert success is False
        assert device_id is None
        assert session_token == ""
        assert "inválido" in message.lower() or "expirado" in message.lower()

    def test_register_device_with_pairing_reused_code(self, repo):
        """Test de registro con código ya usado."""
        code = repo.create_pairing_code()
        
        # Usar el código una vez
        repo.register_device_with_pairing(
            pairing_code=code,
            push_token="test_token_123",
            platform="android",
        )
        
        # Intentar usarlo de nuevo
        success, message, device_id, session_token = repo.register_device_with_pairing(
            pairing_code=code,
            push_token="test_token_456",
            platform="android",
        )
        
        assert success is False
        assert device_id is None
        assert session_token == ""

    def test_cleanup_expired_pairing_codes(self, repo):
        """Test de limpieza de códigos expirados."""
        # Crear código expirado
        code_hash = repo._hash_code("999999")
        expired_time = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
        repo.conn.execute(
            "INSERT INTO pairing_codes(code_hash, installation_id, used, created_at, expires_at) VALUES(?, ?, 0, ?, ?)",
            (code_hash, "studio-principal", expired_time, expired_time),
        )
        repo.conn.commit()
        
        # Crear código usado
        code = repo.create_pairing_code()
        repo.consume_pairing_code(code)
        
        # Limpiar
        repo.cleanup_expired_pairing_codes()
        
        # Verificar que solo quedan códigos válidos
        count = repo.conn.execute("SELECT COUNT(*) FROM pairing_codes").fetchone()[0]
        assert count == 0  # Ambos deberían haber sido eliminados


class TestTokenRefreshLogic:
    """Tests para la lógica de actualización de tokens."""

    def test_update_device_token_safe_new_token(self, repo):
        """Test de actualización con nuevo token."""
        # Registrar dispositivo con token antiguo
        old_token = "old_token_123"
        device_id, _ = repo.register_device(old_token, "android", "Test Device")
        
        # Actualizar con nuevo token
        new_token = "new_token_456"
        success = repo.update_device_token_safe(old_token, new_token)
        
        assert success is True
        
        # Verificar que el token antiguo está desactivado
        old_device = repo.conn.execute("SELECT active FROM mobile_devices WHERE push_token = ?", (old_token,)).fetchone()
        assert old_device["active"] == 0
        
        # Verificar que el nuevo token está activo
        new_device = repo.conn.execute("SELECT active FROM mobile_devices WHERE push_token = ?", (new_token,)).fetchone()
        assert new_device["active"] == 1

    def test_update_device_token_safe_already_exists(self, repo):
        """Test de actualización cuando el nuevo token ya existe."""
        # Registrar dos dispositivos
        token1 = "token_123"
        token2 = "token_456"
        repo.register_device(token1, "android", "Device 1")
        repo.register_device(token2, "android", "Device 2")
        
        # Intentar actualizar token1 a token2 (ya existe)
        success = repo.update_device_token_safe(token1, token2)
        
        assert success is True
        
        # Verificar que solo se actualizó last_seen del token2
        device = repo.conn.execute("SELECT * FROM mobile_devices WHERE push_token = ?", (token2,)).fetchone()
        assert device is not None

    def test_update_device_token_preserves_name(self, repo):
        """Test de que el nombre del dispositivo se preserva al actualizar token."""
        device_name = "Mi Redmi"
        old_token = "old_token_123"
        repo.register_device(old_token, "android", device_name)
        
        new_token = "new_token_456"
        repo.update_device_token_safe(old_token, new_token)
        
        # Verificar que el nombre se preservó
        new_device = repo.conn.execute("SELECT device_name FROM mobile_devices WHERE push_token = ?", (new_token,)).fetchone()
        assert new_device["device_name"] == device_name


class TestDeviceManagement:
    """Tests para la gestión de dispositivos."""

    def test_pause_device(self, repo):
        """Test de pausar dispositivo."""
        device_id, _ = repo.register_device("test_token", "android", "Test Device")
        
        repo.pause_device(device_id)
        
        device = repo.conn.execute("SELECT active FROM mobile_devices WHERE id = ?", (device_id,)).fetchone()
        assert device["active"] == 0

    def test_resume_device(self, repo):
        """Test de reactivar dispositivo."""
        device_id, _ = repo.register_device("test_token", "android", "Test Device")
        repo.pause_device(device_id)
        
        repo.resume_device(device_id)
        
        device = repo.conn.execute("SELECT active FROM mobile_devices WHERE id = ?", (device_id,)).fetchone()
        assert device["active"] == 1

    def test_rename_device(self, repo):
        """Test de renombrar dispositivo."""
        device_id, _ = repo.register_device("test_token", "android", "Old Name")
        
        repo.rename_device(device_id, "New Name")
        
        device = repo.conn.execute("SELECT device_name FROM mobile_devices WHERE id = ?", (device_id,)).fetchone()
        assert device["device_name"] == "New Name"

    def test_unlink_device(self, repo):
        """Test de desvincular dispositivo."""
        device_id, _ = repo.register_device("test_token", "android", "Test Device")
        
        repo.unlink_device(device_id)
        
        device = repo.conn.execute("SELECT active FROM mobile_devices WHERE id = ?", (device_id,)).fetchone()
        assert device["active"] == 0

    def test_duplicate_device_prevention(self, repo):
        """Test de prevención de duplicación de dispositivos con mismo token."""
        token = "duplicate_token_123"
        
        # Primer registro
        device_id1, _ = repo.register_device(token, "android", "Device 1")
        
        # Segundo registro con mismo token (debe actualizar el existente)
        device_id2, _ = repo.register_device(token, "android", "Device 2")
        
        # Debe ser el mismo ID
        assert device_id1 == device_id2
        
        # Verificar que el nombre se actualizó
        device = repo.conn.execute("SELECT device_name FROM mobile_devices WHERE id = ?", (device_id1,)).fetchone()
        assert device["device_name"] == "Device 2"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
