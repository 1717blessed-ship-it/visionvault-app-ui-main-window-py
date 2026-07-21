"""Test para verificar que la aplicación inicia con una base de datos antigua."""

import sqlite3
import tempfile
from pathlib import Path
import pytest


def test_migration_from_old_database():
    """Verifica que las migraciones funcionan sobre una base de datos existente."""
    fd, path = tempfile.mkstemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    
    try:
        # Crear schema antiguo (sin columnas de session token)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS mobile_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                device_name TEXT,
                platform TEXT NOT NULL,
                push_token TEXT NOT NULL UNIQUE,
                active INTEGER NOT NULL DEFAULT 1,
                last_seen_at TEXT,
                created_at TEXT NOT NULL
            )"""
        )
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_mobile_devices_token ON mobile_devices(push_token)")
        
        # Crear pairing_codes antiguo (con código en texto plano)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS pairing_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                installation_id TEXT NOT NULL DEFAULT 'studio-principal',
                used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )"""
        )
        
        # Insertar datos de prueba
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO mobile_devices(device_name, platform, push_token, active, created_at) VALUES(?, ?, ?, ?, ?)",
            ("Old Device", "android", "old_token_123", 1, now),
        )
        conn.execute(
            "INSERT INTO pairing_codes(code, installation_id, used, created_at, expires_at) VALUES(?, ?, ?, ?, ?)",
            ("123456", "studio-principal", 0, now, now),
        )
        conn.commit()
        
        # Verificar que las columnas NO existen antes de la migración
        columns_before = {row[1] for row in conn.execute("PRAGMA table_info(mobile_devices)")}
        assert "session_token_hash" not in columns_before
        assert "session_expires_at" not in columns_before
        assert "session_last_used_at" not in columns_before
        
        pairing_columns_before = {row[1] for row in conn.execute("PRAGMA table_info(pairing_codes)")}
        assert "code_hash" not in pairing_columns_before
        assert "code" in pairing_columns_before
        
        # Simular inicialización de Database con migraciones
        from app.database.database import ImageDatabase
        db = ImageDatabase(path)
        
        # Verificar que las columnas ahora existen después de la migración
        columns_after = {row[1] for row in conn.execute("PRAGMA table_info(mobile_devices)")}
        assert "session_token_hash" in columns_after
        assert "session_expires_at" in columns_after
        assert "session_last_used_at" in columns_after
        
        pairing_columns_after = {row[1] for row in conn.execute("PRAGMA table_info(pairing_codes)")}
        assert "code_hash" in pairing_columns_after
        assert "code" not in pairing_columns_after
        
        # Verificar que los datos antiguos se migraron correctamente
        # El código antiguo debería tener su hash en la nueva tabla
        import hashlib
        old_code = "123456"
        expected_hash = hashlib.sha256(old_code.encode()).hexdigest()
        pairing_row = conn.execute("SELECT * FROM pairing_codes").fetchone()
        assert pairing_row["code_hash"] == expected_hash
        
        # Verificar que el dispositivo antiguo sigue existiendo
        device_row = conn.execute("SELECT * FROM mobile_devices").fetchone()
        assert device_row["device_name"] == "Old Device"
        assert device_row["push_token"] == "old_token_123"
        
        # Verificar que EventRepository puede usar las nuevas columnas
        device_id, session_token = db.event_repo.register_device(
            push_token="new_token_456",
            platform="android",
            device_name="New Device",
        )
        assert device_id > 0
        assert session_token is not None
        assert len(session_token) > 20
        
        # Verificar que el session token se guardó correctamente
        new_device = conn.execute("SELECT * FROM mobile_devices WHERE id = ?", (device_id,)).fetchone()
        assert new_device["session_token_hash"] is not None
        assert new_device["session_expires_at"] is not None
        
        db.close()
        
    finally:
        conn.close()
        import gc
        gc.collect()
        try:
            Path(path).unlink(missing_ok=True)
        except PermissionError:
            pass


if __name__ == "__main__":
    test_migration_from_old_database()
    print("✅ Test de migración de base de datos antigua exitoso")
