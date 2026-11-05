"""Tests para ProductionStageService - Servicio de etapas de producción."""

import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
import pytest
from unittest.mock import Mock

from app.services.production_stage_service import ProductionStageService
from app.events.event_repository import EventRepository
from app.events.event_bus import EventBus


@pytest.fixture
def temp_db():
    """Crea una base de datos temporal para pruebas."""
    fd, path = tempfile.mkstemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    yield conn, path
    conn.close()
    import gc
    gc.collect()
    try:
        Path(path).unlink(missing_ok=True)
    except PermissionError:
        pass


@pytest.fixture
def repo(temp_db):
    """Crea un EventRepository con base de datos temporal."""
    conn, _ = temp_db
    repo = EventRepository(conn)
    repo.create_tables()
    
    # Ejecutar migraciones de mobile_devices (simulando database.py)
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(mobile_devices)")}
    for column, definition in (
        ("session_token_hash", "TEXT"),
        ("session_expires_at", "TEXT"),
        ("session_last_used_at", "TEXT"),
        ("app_version", "TEXT DEFAULT ''"),
    ):
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE mobile_devices ADD COLUMN {column} {definition}")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_mobile_devices_session ON mobile_devices(session_token_hash)")
    
    # Crear tablas adicionales necesarias para tests
    conn.execute(
        """CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            whatsapp TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY,
            client TEXT NOT NULL,
            client_id INTEGER,
            order_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Nuevo',
            material TEXT DEFAULT '',
            size TEXT DEFAULT '',
            quantity INTEGER DEFAULT 0,
            price REAL DEFAULT 0,
            delivery_date TEXT DEFAULT '',
            print_priority INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_autosave_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS order_jobs (
            id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT 'Trabajo',
            material TEXT DEFAULT '',
            size TEXT DEFAULT '',
            quantity INTEGER NOT NULL DEFAULT 1,
            status TEXT DEFAULT 'Pendiente',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS order_events (
            id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            data_json TEXT,
            created_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    
    return repo


@pytest.fixture
def event_bus(repo):
    """Crea un EventBus para pruebas."""
    return EventBus(repo)


@pytest.fixture
def stage_service(repo, event_bus):
    """Crea un ProductionStageService para pruebas."""
    return ProductionStageService(repo.conn, event_bus)


@pytest.fixture
def sample_order(repo):
    """Crea un pedido de prueba con jobs."""
    conn = repo.conn
    now = datetime.now().isoformat(timespec="seconds")
    
    # Crear cliente
    conn.execute(
        "INSERT INTO clients(name, whatsapp, created_at, updated_at) VALUES(?, ?, ?, ?)",
        ("Cliente Test", "1234567890", now, now),
    )
    client_id = conn.execute("SELECT id FROM clients").fetchone()["id"]
    
    # Crear pedido
    conn.execute(
        """INSERT INTO orders(client, client_id, order_date, status, material, size, quantity, price,
           created_at, updated_at, last_autosave_at)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("Cliente Test", client_id, now, "Nuevo", "Vinilo", "10cm", 10, 5000, now, now, now),
    )
    order_id = conn.execute("SELECT id FROM orders").fetchone()["id"]
    
    # Crear jobs
    conn.execute(
        """INSERT INTO order_jobs(order_id, title, material, size, quantity, status, created_at, updated_at)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
        (order_id, "Job 1", "Vinilo", "10cm", 5, "Recibido", now, now),
    )
    conn.execute(
        """INSERT INTO order_jobs(order_id, title, material, size, quantity, status, created_at, updated_at)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
        (order_id, "Job 2", "Vinilo", "10cm", 5, "Recibido", now, now),
    )
    
    conn.commit()
    return order_id


@pytest.fixture
def sample_device(repo):
    """Crea un dispositivo móvil de prueba."""
    conn = repo.conn
    
    device_id, session_token = repo.register_device(
        push_token="test_token_123",
        platform="android",
        device_name="Test Device",
    )
    
    return device_id, session_token


class TestLegacyStateMapping:
    """Tests para mapeo de estados legacy."""
    
    def test_recognized_legacy_state(self, stage_service):
        """Estados legacy reconocidos se mapean correctamente."""
        assert stage_service.normalize_stage("Nuevo") == "Recibido"
        assert stage_service.normalize_stage("En revisión") == "Esperando archivos"
        assert stage_service.normalize_stage("En diseño") == "Esperando archivos"
        assert stage_service.normalize_stage("Impreso") == "Impresión"
        assert stage_service.normalize_stage("Aprobado") == "Diseños confirmados"
    
    def test_valid_workflow_stage(self, stage_service):
        """Etapas válidas del workflow se conservan."""
        assert stage_service.normalize_stage("Recibido") == "Recibido"
        assert stage_service.normalize_stage("Impresión") == "Impresión"
        assert stage_service.normalize_stage("Finalizado") == "Finalizado"
        assert stage_service.normalize_stage("Entregado") == "Entregado"
    
    def test_unknown_state_preserved(self, stage_service, caplog):
        """Estados desconocidos se conservan con warning."""
        unknown_state = "EstadoDesconocidoXYZ"
        result = stage_service.normalize_stage(unknown_state)
        assert result == unknown_state
        assert "no reconocido" in caplog.text.lower()


class TestDerivedOrderStatus:
    """Tests para cálculo de estado derivado de pedidos."""
    
    def test_all_delivered(self, stage_service, repo, sample_order):
        """Todos los jobs entregados → Entregado."""
        conn = repo.conn
        order_id = sample_order
        
        # Actualizar todos los jobs a Entregado
        conn.execute("UPDATE order_jobs SET status = 'Entregado' WHERE order_id = ?", (order_id,))
        conn.commit()
        
        status = stage_service.derive_order_status(order_id)
        assert status == "Entregado"
    
    def test_all_finished_or_delivered(self, stage_service, repo, sample_order):
        """Todos los jobs Finalizados o Entregados → Finalizado."""
        conn = repo.conn
        order_id = sample_order
        
        # Actualizar jobs a mixto de Finalizado/Entregado
        jobs = conn.execute("SELECT id FROM order_jobs WHERE order_id = ?", (order_id,)).fetchall()
        conn.execute("UPDATE order_jobs SET status = 'Finalizado' WHERE id = ?", (jobs[0]["id"],))
        conn.execute("UPDATE order_jobs SET status = 'Entregado' WHERE id = ?", (jobs[1]["id"],))
        conn.commit()
        
        status = stage_service.derive_order_status(order_id)
        assert status == "Finalizado"
    
    def test_some_productive(self, stage_service, repo, sample_order):
        """Algún job en etapa productiva → En producción."""
        conn = repo.conn
        order_id = sample_order
        
        # Un job en producción, otro pendiente
        jobs = conn.execute("SELECT id FROM order_jobs WHERE order_id = ?", (order_id,)).fetchall()
        conn.execute("UPDATE order_jobs SET status = 'Impresión' WHERE id = ?", (jobs[0]["id"],))
        conn.execute("UPDATE order_jobs SET status = 'Recibido' WHERE id = ?", (jobs[1]["id"],))
        conn.commit()
        
        status = stage_service.derive_order_status(order_id)
        assert status == "En producción"
    
    def test_all_pending(self, stage_service, repo, sample_order):
        """Todos los jobs pendientes → Pendiente."""
        conn = repo.conn
        order_id = sample_order
        
        # Todos en Recibido
        conn.execute("UPDATE order_jobs SET status = 'Recibido' WHERE order_id = ?", (order_id,))
        conn.commit()
        
        status = stage_service.derive_order_status(order_id)
        assert status == "Pendiente"
    
    def test_no_jobs_preserves_current(self, stage_service, repo):
        """Sin jobs, conserva estado actual del pedido."""
        conn = repo.conn
        now = datetime.now().isoformat(timespec="seconds")
        
        # Crear pedido sin jobs
        conn.execute(
            """INSERT INTO orders(client, order_date, status, material, size, quantity, price,
               created_at, updated_at, last_autosave_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("Test Client", now, "EstadoPersonalizado", "Material", "10cm", 1, 100, now, now, now),
        )
        order_id = conn.execute("SELECT id FROM orders").fetchone()["id"]
        
        status = stage_service.derive_order_status(order_id)
        assert status == "EstadoPersonalizado"


class TestOrderProgressCalculation:
    """Tests para cálculo de progreso de pedidos."""
    
    def test_progress_from_jobs(self, stage_service, repo, sample_order):
        """Progreso calculado desde jobs."""
        conn = repo.conn
        order_id = sample_order
        
        # Jobs en diferentes etapas
        jobs = conn.execute("SELECT id FROM order_jobs WHERE order_id = ?", (order_id,)).fetchall()
        conn.execute("UPDATE order_jobs SET status = 'Impresión' WHERE id = ?", (jobs[0]["id"],))
        conn.execute("UPDATE order_jobs SET status = 'Recibido' WHERE id = ?", (jobs[1]["id"],))
        conn.commit()
        
        progress = stage_service.calculate_order_progress(order_id)
        # Recibido = 5%, Impresión = 60%, promedio = 32.5%
        assert 0 < progress < 1
    
    def test_no_jobs_zero_progress(self, stage_service, repo):
        """Sin jobs, progreso es 0."""
        conn = repo.conn
        now = datetime.now().isoformat(timespec="seconds")
        
        conn.execute(
            """INSERT INTO orders(client, order_date, status, material, size, quantity, price,
               created_at, updated_at, last_autosave_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("Test Client", now, "Nuevo", "Material", "10cm", 1, 100, now, now, now),
        )
        order_id = conn.execute("SELECT id FROM orders").fetchone()["id"]
        
        progress = stage_service.calculate_order_progress(order_id)
        assert progress == 0.0


class TestStageTransitionValidation:
    """Tests para validación de transiciones de etapa."""
    
    def test_valid_transition(self, stage_service, repo, sample_order):
        """Transición válida entre etapas del workflow."""
        conn = repo.conn
        order_id = sample_order
        job = conn.execute("SELECT * FROM order_jobs WHERE order_id = ? LIMIT 1", (order_id,)).fetchone()
        
        is_valid, error = stage_service.validate_transition(dict(job), "Impresión")
        assert is_valid is True
        assert error == ""
    
    def test_invalid_stage(self, stage_service, repo, sample_order):
        """Etapa destino no existe en workflow."""
        conn = repo.conn
        order_id = sample_order
        job = conn.execute("SELECT * FROM order_jobs WHERE order_id = ? LIMIT 1", (order_id,)).fetchone()
        
        is_valid, error = stage_service.validate_transition(dict(job), "EtapaInexistente")
        assert is_valid is False
        assert "no está en el workflow" in error.lower()


class TestTransactionalStageChange:
    """Tests para cambio de etapa transaccional."""
    
    def test_successful_stage_change(self, stage_service, repo, sample_order, sample_device):
        """Cambio de etapa exitoso con todos los efectos."""
        conn = repo.conn
        order_id = sample_order
        device_id, _ = sample_device
        
        job = conn.execute("SELECT * FROM order_jobs WHERE order_id = ? LIMIT 1", (order_id,)).fetchone()
        job_id = job["id"]
        old_status = job["status"]
        
        success, message, job_data = stage_service.change_job_stage(
            job_id=job_id,
            new_stage="Impresión",
            device_id=device_id,
            device_name="Test Device",
            operator_name="Test Operator",
            source="mobile",
            notes="Test note",
        )
        
        assert success is True
        assert job_data is not None
        assert job_data["status"] == "Impresión"
        
        # Verificar historial
        history = conn.execute(
            "SELECT * FROM production_stage_history WHERE job_id = ?", (job_id,)
        ).fetchone()
        assert history is not None
        assert history["old_stage"] == old_status
        assert history["new_stage"] == "Impresión"
        assert history["device_id"] == device_id
        
        # Verificar order_events
        event = conn.execute(
            "SELECT * FROM order_events WHERE order_id = ? AND event_type = 'stage.changed'", (order_id,)
        ).fetchone()
        assert event is not None
    
    def test_rollback_on_invalid_job(self, stage_service, sample_device):
        """Rollback si job no existe."""
        device_id, _ = sample_device
        
        success, message, job_data = stage_service.change_job_stage(
            job_id=99999,  # Job inexistente
            new_stage="Impresión",
            device_id=device_id,
            device_name="Test Device",
            source="mobile",
        )
        
        assert success is False
        assert "no encontrado" in message.lower()
        assert job_data is None
    
    def test_rollback_on_invalid_transition(self, stage_service, repo, sample_order, sample_device):
        """Rollback si transición es inválida."""
        conn = repo.conn
        order_id = sample_order
        device_id, _ = sample_device
        
        job = conn.execute("SELECT * FROM order_jobs WHERE order_id = ? LIMIT 1", (order_id,)).fetchone()
        
        success, message, job_data = stage_service.change_job_stage(
            job_id=job["id"],
            new_stage="EtapaInexistente",
            device_id=device_id,
            device_name="Test Device",
            source="mobile",
        )
        
        assert success is False
        assert job_data is None

    def test_delivering_last_job_clears_order_priority(
        self, stage_service, repo, sample_order, sample_device
    ):
        conn = repo.conn
        # This transition test represents physically fulfilled jobs.
        conn.executescript("""
            CREATE TABLE plancha_item_assignments(order_job_id INTEGER,quantity REAL,state TEXT);
            CREATE TABLE order_design_demand_lines(order_job_id INTEGER);
            INSERT INTO plancha_item_assignments
                SELECT id,quantity,'finished' FROM order_jobs;
        """)
        from app.services.delivery_readiness import install_delivery_guards
        install_delivery_guards(conn)
        order_id = sample_order
        device_id, _ = sample_device
        jobs = conn.execute(
            "SELECT id FROM order_jobs WHERE order_id = ? ORDER BY id", (order_id,)
        ).fetchall()
        conn.execute(
            "UPDATE order_jobs SET status = 'Entregado' WHERE id = ?", (jobs[0]["id"],)
        )
        conn.execute(
            "UPDATE orders SET print_priority = 4 WHERE id = ?", (order_id,)
        )
        conn.commit()

        success, _, _ = stage_service.change_job_stage(
            job_id=jobs[1]["id"],
            new_stage="Entregado",
            device_id=device_id,
            device_name="Test Device",
            source="mobile",
        )

        order = conn.execute(
            "SELECT status, print_priority FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        assert success is True
        assert order["status"] == "Entregado"
        assert order["print_priority"] == 0


class TestSessionTokenGeneration:
    """Tests para generación y validación de session tokens."""
    
    def test_session_token_generated_on_register(self, repo):
        """Session token generado al registrar dispositivo."""
        device_id, session_token = repo.register_device(
            push_token="new_token_123",
            platform="android",
            device_name="New Device",
        )
        
        assert device_id > 0
        assert session_token is not None
        assert len(session_token) > 20  # token_urlsafe(32) genera ~43 caracteres
    
    def test_session_token_hash_stored(self, repo):
        """Solo hash almacenado, no token en texto plano."""
        device_id, session_token = repo.register_device(
            push_token="token_hash_test",
            platform="android",
            device_name="Hash Test",
        )
        
        conn = repo.conn
        device = conn.execute("SELECT * FROM mobile_devices WHERE id = ?", (device_id,)).fetchone()
        
        assert device["session_token_hash"] is not None
        assert device["session_token_hash"] != session_token  # No es el token en texto plano
        assert session_token not in str(device)  # Token no aparece en ningún campo
    
    def test_valid_session_token(self, repo):
        """Session token válido se autentica correctamente."""
        device_id, session_token = repo.register_device(
            push_token="valid_token_test",
            platform="android",
            device_name="Valid Token",
        )
        
        device = repo.validate_session_token(session_token)
        assert device is not None
        assert device["id"] == device_id
        # Verificar campos adicionales requeridos por _get_device_status
        assert "registered_at" in device
        assert "app_version" in device
        assert "is_paused" in device
        # Verificar que is_paused es 0 para dispositivo activo
        assert device["is_paused"] == 0
    
    def test_invalid_session_token(self, repo):
        """Session token inválido es rechazado."""
        device = repo.validate_session_token("invalid_token_xyz")
        assert device is None
    
    def test_expired_session_token(self, repo):
        """Session token expirado es rechazado."""
        device_id, session_token = repo.register_device(
            push_token="expired_token_test",
            platform="android",
            device_name="Expired Token",
        )
        
        # Expirar el token manualmente
        conn = repo.conn
        past = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
        conn.execute(
            "UPDATE mobile_devices SET session_expires_at = ? WHERE id = ?",
            (past, device_id),
        )
        conn.commit()
        
        device = repo.validate_session_token(session_token)
        assert device is None
    
    def test_inactive_device_rejected(self, repo):
        """Dispositivo inactivo rechaza session token."""
        device_id, session_token = repo.register_device(
            push_token="inactive_token_test",
            platform="android",
            device_name="Inactive Device",
        )
        
        # Desactivar dispositivo
        conn = repo.conn
        conn.execute("UPDATE mobile_devices SET active = 0 WHERE id = ?", (device_id,))
        conn.commit()
        
        device = repo.validate_session_token(session_token)
        assert device is None


class TestSessionTokenVsFCMSeparation:
    """Tests para separación de session token y FCM token."""
    
    def test_session_token_independent_of_fcm(self, repo):
        """Session token es independiente del FCM token."""
        device_id, session_token = repo.register_device(
            push_token="fcm_token_abc",
            platform="android",
            device_name="Separation Test",
        )
        
        # Actualizar FCM token (renovación)
        repo.update_device_token(device_id, "new_fcm_token_xyz")
        
        # Session token sigue siendo válido
        device = repo.validate_session_token(session_token)
        assert device is not None
        assert device["push_token"] == "new_fcm_token_xyz"
    
    def test_fcm_renewal_with_valid_session(self, repo):
        """Renovación de FCM con sesión válida."""
        device_id, session_token = repo.register_device(
            push_token="old_fcm_token",
            platform="android",
            device_name="FCM Renewal",
        )
        
        # Session token sigue válido después de renovar FCM
        repo.update_device_token(device_id, "new_fcm_token")
        
        device = repo.validate_session_token(session_token)
        assert device is not None
        assert device["push_token"] == "new_fcm_token"
