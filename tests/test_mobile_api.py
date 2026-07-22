"""Tests para Mobile Jobs API - Endpoints HTTP del Operador Móvil."""

import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
import pytest
from http.server import BaseHTTPRequestHandler
from io import BytesIO
from unittest.mock import Mock, MagicMock

from app.api.mobile_jobs import MobileJobsHandler, MobileJobsServer
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
            is_archived INTEGER DEFAULT 0,
            whatsapp TEXT DEFAULT '',
            observations TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_autosave_at TEXT
        )"""
    )
    
    # Agregar columnas faltantes en clients
    existing_client_columns = {row[1] for row in conn.execute("PRAGMA table_info(clients)")}
    if "client_type" not in existing_client_columns:
        conn.execute("ALTER TABLE clients ADD COLUMN client_type TEXT DEFAULT 'Particular'")
    
    # Agregar columnas faltantes en orders
    existing_order_columns = {row[1] for row in conn.execute("PRAGMA table_info(orders)")}
    for column in ("order_concept", "order_description", "discount_percent",
                    "budget_total", "paid_amount", "payment_status"):
        if column not in existing_order_columns:
            default = "0" if column in ("discount_percent", "budget_total", "paid_amount") else "'Pendiente'" if column == "payment_status" else "''"
            conn.execute(f"ALTER TABLE orders ADD COLUMN {column} TEXT DEFAULT {default}")
    
    conn.execute(
        """CREATE TABLE IF NOT EXISTS order_jobs (
            id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT 'Trabajo',
            material TEXT DEFAULT '',
            size TEXT DEFAULT '',
            quantity INTEGER NOT NULL DEFAULT 1,
            status TEXT DEFAULT 'Pendiente',
            notes TEXT DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
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
    conn.execute(
        """CREATE TABLE IF NOT EXISTS order_payments (
            id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            method TEXT DEFAULT '',
            note TEXT DEFAULT '',
            paid_at TEXT NOT NULL,
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
def sample_device(repo):
    """Crea un dispositivo móvil de prueba."""
    device_id, session_token = repo.register_device(
        push_token="test_fcm_token",
        platform="android",
        device_name="Test Device",
    )
    return device_id, session_token


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
           delivery_date, print_priority, created_at, updated_at, last_autosave_at)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("Cliente Test", client_id, now, "Nuevo", "Vinilo", "10cm", 10, 5000, "2026-12-31", 2, now, now, now),
    )
    order_id = conn.execute("SELECT id FROM orders").fetchone()["id"]
    
    # Crear jobs
    conn.execute(
        """INSERT INTO order_jobs(order_id, title, material, size, quantity, status, created_at, updated_at)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
        (order_id, "Job Pendiente", "Vinilo", "10cm", 5, "Recibido", now, now),
    )
    conn.execute(
        """INSERT INTO order_jobs(order_id, title, material, size, quantity, status, created_at, updated_at)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
        (order_id, "Job Producción", "Vinilo", "10cm", 5, "Impresión", now, now),
    )
    conn.execute(
        """INSERT INTO order_jobs(order_id, title, material, size, quantity, status, created_at, updated_at)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
        (order_id, "Job Listo", "Vinilo", "10cm", 5, "Finalizado", now, now),
    )
    
    conn.commit()
    return order_id


class MockRequest:
    """Mock para simular requests HTTP."""
    
    def __init__(self, method, path, headers=None, body=None):
        self.method = method
        self.path = path
        self.headers = headers or {}
        self.body = body or b""
        self.rfile = BytesIO(self.body)


class MockResponse:
    """Mock para capturar respuestas HTTP."""
    
    def __init__(self):
        self.status_code = None
        self.headers = {}
        self.body = b""
    
    def send_response(self, status_code):
        self.status_code = status_code
    
    def send_header(self, name, value):
        self.headers[name] = value
    
    def end_headers(self):
        pass
    
    def wfile_write(self, data):
        self.body += data


def create_handler(repo, event_bus):
    """Crea un handler con mock de response."""
    from app.services.production_stage_service import ProductionStageService
    
    handler = MobileJobsHandler.__new__(MobileJobsHandler)
    handler.event_repo = repo
    handler.event_bus = event_bus
    handler.stage_service = ProductionStageService(repo.conn, event_bus)
    handler.server_version = "TestServer"
    handler.sys_version = "Test/1.0"
    handler.protocol_version = "HTTP/1.1"
    
    # Mock response
    handler.response = MockResponse()
    handler.send_response = handler.response.send_response
    handler.send_header = handler.response.send_header
    handler.end_headers = handler.response.end_headers
    handler.wfile = Mock()
    handler.wfile.write = handler.response.wfile_write
    
    return handler


class TestAuthentication:
    """Tests para autenticación Bearer token."""
    
    def test_valid_bearer_token(self, repo, event_bus, sample_device):
        """Bearer token válido autentica correctamente."""
        device_id, session_token = sample_device
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        
        device = handler._validate_auth()
        
        assert device is not None
        assert device["id"] == device_id
    
    def test_missing_authorization_header(self, repo, event_bus):
        """Sin header Authorization, retorna 401."""
        handler = create_handler(repo, event_bus)
        handler.headers = {}
        handler._send_error = Mock()
        
        device = handler._validate_auth()
        
        assert device is None
        handler._send_error.assert_called_once_with(401, "Authorization header missing")
    
    def test_invalid_bearer_token(self, repo, event_bus):
        """Bearer token inválido retorna 401."""
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": "Bearer invalid_token_xyz"}
        handler._send_error = Mock()
        
        device = handler._validate_auth()
        
        assert device is None
        handler._send_error.assert_called_once_with(401, "Invalid or expired session token")
    
    def test_expired_bearer_token(self, repo, event_bus, sample_device):
        """Bearer token expirado retorna 401."""
        device_id, session_token = sample_device
        
        # Expirar el token
        conn = repo.conn
        from datetime import timedelta
        past = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
        conn.execute(
            "UPDATE mobile_devices SET session_expires_at = ? WHERE id = ?",
            (past, device_id),
        )
        conn.commit()
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler._send_error = Mock()
        
        device = handler._validate_auth()
        
        assert device is None
        handler._send_error.assert_called_once_with(401, "Invalid or expired session token")


class TestListJobsEndpoint:
    """Tests para GET /api/mobile/jobs."""
    
    def test_list_jobs_without_filter(self, repo, event_bus, sample_device, sample_order):
        """Listar jobs sin filtro retorna todos."""
        device_id, session_token = sample_device
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/mobile/jobs"
        handler._parse_url_params = Mock(return_value={})
        
        handler._list_jobs({"id": device_id, "device_name": "Test Device"})
        
        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert "jobs" in response_data
        assert len(response_data["jobs"]) > 0
    
    def test_list_jobs_with_pending_filter(self, repo, event_bus, sample_device, sample_order):
        """Filtro pending retorna jobs en etapas iniciales."""
        device_id, session_token = sample_device
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/mobile/jobs?filter=pending"
        handler._parse_url_params = Mock(return_value={"filter": "pending"})
        
        handler._list_jobs({"id": device_id, "device_name": "Test Device"})
        
        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert "jobs" in response_data
        # Verificar que jobs están en etapas pendientes
        for job in response_data["jobs"]:
            assert job["status"] in ("Recibido", "Esperando archivos")
    
    def test_list_jobs_with_production_filter(self, repo, event_bus, sample_device, sample_order):
        """Filtro production retorna jobs en etapas productivas."""
        device_id, session_token = sample_device
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/mobile/jobs?filter=production"
        handler._parse_url_params = Mock(return_value={"filter": "production"})
        
        handler._list_jobs({"id": device_id, "device_name": "Test Device"})
        
        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert "jobs" in response_data
        # Verificar que jobs están en etapas productivas
        for job in response_data["jobs"]:
            assert job["status"] not in ("Recibido", "Esperando archivos", "Finalizado", "Entregado")
    
    def test_list_jobs_with_ready_filter(self, repo, event_bus, sample_device, sample_order):
        """Filtro ready retorna jobs finalizados o entregados."""
        device_id, session_token = sample_device
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/mobile/jobs?filter=ready"
        handler._parse_url_params = Mock(return_value={"filter": "ready"})
        
        handler._list_jobs({"id": device_id, "device_name": "Test Device"})
        
        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert "jobs" in response_data
        # Verificar que jobs están finalizados o entregados
        for job in response_data["jobs"]:
            assert job["status"] in ("Finalizado", "Entregado")
    
    def test_list_jobs_with_pagination(self, repo, event_bus, sample_device, sample_order):
        """Paginación funciona correctamente."""
        device_id, session_token = sample_device
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/mobile/jobs?limit=1&offset=0"
        handler._parse_url_params = Mock(return_value={"limit": "1", "offset": "0"})
        
        handler._list_jobs({"id": device_id, "device_name": "Test Device"})
        
        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert "jobs" in response_data
        assert len(response_data["jobs"]) <= 1
        assert response_data["limit"] == 1
        assert response_data["offset"] == 0


class TestGetJobDetailEndpoint:
    """Tests para GET /api/mobile/jobs/{id}."""
    
    def test_get_job_detail_success(self, repo, event_bus, sample_device, sample_order):
        """Obtener detalle de job existente."""
        device_id, session_token = sample_device
        conn = repo.conn
        job = conn.execute("SELECT id FROM order_jobs LIMIT 1").fetchone()
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = f"/api/mobile/jobs/{job['id']}"
        
        handler._get_job_detail(job["id"], {"id": device_id, "device_name": "Test Device"})
        
        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert response_data["id"] == job["id"]
        assert "progress" in response_data
        assert "current_stage" in response_data
        assert "workflow_stages" in response_data
        assert "stage_history" in response_data
    
    def test_get_job_detail_not_found(self, repo, event_bus, sample_device):
        """Job inexistente retorna 404."""
        device_id, session_token = sample_device
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/mobile/jobs/99999"
        handler._send_error = Mock()
        
        handler._get_job_detail(99999, {"id": device_id, "device_name": "Test Device"})
        
        handler._send_error.assert_called_once_with(404, "Job not found")


class TestChangeJobStageEndpoint:
    """Tests para POST /api/mobile/jobs/{id}/stage."""
    
    def test_change_stage_success(self, repo, event_bus, sample_device, sample_order):
        """Cambio de etapa exitoso."""
        device_id, session_token = sample_device
        conn = repo.conn
        job = conn.execute("SELECT id FROM order_jobs WHERE status = 'Recibido' LIMIT 1").fetchone()
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = f"/api/mobile/jobs/{job['id']}/stage"
        
        body_data = json.dumps({"stage": "Impresión", "notes": "Test change"}).encode("utf-8")
        handler.headers["Content-Length"] = str(len(body_data))
        handler.rfile = BytesIO(body_data)
        
        handler._change_job_stage(job["id"], {"id": device_id, "device_name": "Test Device"})
        
        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert response_data["success"] is True
        assert "job" in response_data
        assert response_data["job"]["status"] == "Impresión"
    
    def test_change_stage_missing_stage_field(self, repo, event_bus, sample_device, sample_order):
        """Sin campo stage retorna 400."""
        device_id, session_token = sample_device
        conn = repo.conn
        job = conn.execute("SELECT id FROM order_jobs LIMIT 1").fetchone()
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = f"/api/mobile/jobs/{job['id']}/stage"
        handler._send_error = Mock()
        
        body_data = json.dumps({"notes": "Test"}).encode("utf-8")
        handler.headers["Content-Length"] = str(len(body_data))
        handler.rfile = BytesIO(body_data)
        
        handler._change_job_stage(job["id"], {"id": device_id, "device_name": "Test Device"})
        
        handler._send_error.assert_called_once_with(400, "stage field is required and cannot be empty")
    
    def test_change_stage_invalid_json(self, repo, event_bus, sample_device, sample_order):
        """JSON inválido retorna 400."""
        device_id, session_token = sample_device
        conn = repo.conn
        job = conn.execute("SELECT id FROM order_jobs LIMIT 1").fetchone()
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = f"/api/mobile/jobs/{job['id']}/stage"
        handler._send_error = Mock()
        
        body_data = b"invalid json"
        handler.headers["Content-Length"] = str(len(body_data))
        handler.rfile = BytesIO(body_data)
        
        handler._change_job_stage(job["id"], {"id": device_id, "device_name": "Test Device"})
        
        handler._send_error.assert_called_once_with(400, "Invalid JSON body")


class TestFCMTokenRenewalIndependence:
    """Tests para independencia de renovación FCM y sesión HTTP."""
    
    def test_fcm_renewal_preserves_session(self, repo, event_bus, sample_device, sample_order):
        """Renovación de FCM preserva sesión válida."""
        device_id, session_token = sample_device
        
        # Renovar FCM token
        repo.update_device_token(device_id, "new_fcm_token")
        
        # Session token sigue siendo válido
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        
        device = handler._validate_auth()
        assert device is not None
        assert device["push_token"] == "new_fcm_token"
    
    def test_session_valid_with_expired_fcm(self, repo, event_bus, sample_device):
        """Sesión válida aunque FCM no se haya renovado."""
        device_id, session_token = sample_device
        
        # No renovar FCM, solo verificar sesión
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        
        device = handler._validate_auth()
        assert device is not None
        assert device["id"] == device_id



class TestReferenceEndpointsV1:
    """Tests para endpoints de referencia en /api/v1/mobile/reference/*."""
    
    def test_get_stages_v1(self, repo, event_bus, sample_device):
        """GET /api/v1/mobile/reference/stages retorna catálogo de etapas."""
        device_id, session_token = sample_device
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/reference/stages"
        
        handler._get_stages()
        
        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert "stages" in response_data
        assert len(response_data["stages"]) > 0
        # Verificar estructura de etapas
        stage = response_data["stages"][0]
        assert "key" in stage
        assert "label" in stage
        assert "category" in stage
        assert "description" in stage
        assert "color" in stage
    
    def test_get_workflows_v1(self, repo, event_bus, sample_device):
        """GET /api/v1/mobile/reference/workflows retorna workflows."""
        device_id, session_token = sample_device
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/reference/workflows"
        
        handler._get_workflows()
        
        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert "workflows" in response_data
        assert len(response_data["workflows"]) > 0
        # Verificar workflows esperados
        assert "general" in response_data["workflows"]
        assert "vinilo" in response_data["workflows"]
        # Verificar estructura
        workflow = response_data["workflows"]["general"]
        assert "name" in workflow
        assert "stages" in workflow
        assert isinstance(workflow["stages"], list)
    
    def test_get_materials_v1(self, repo, event_bus, sample_device, sample_order):
        """GET /api/v1/mobile/reference/materials retorna materiales."""
        device_id, session_token = sample_device
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/reference/materials"
        
        handler._get_materials()
        
        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert "materials" in response_data
        assert len(response_data["materials"]) > 0
        # Verificar que incluye material del sample_order
        assert "Vinilo" in response_data["materials"]


class TestDeviceEndpointsV1:
    """Tests para endpoints de dispositivo en /api/v1/mobile/device/*."""
    
    def test_get_device_status_v1(self, repo, event_bus, sample_device):
        """GET /api/v1/mobile/device/status retorna estado del dispositivo."""
        device_id, session_token = sample_device
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/device/status"
        
        # Obtener device completo desde el repo
        device_info = repo.validate_session_token(session_token)
        handler._get_device_status(device_info)
        
        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert response_data["device_id"] == device_id
        assert response_data["device_name"] == "Test Device"
        assert response_data["platform"] == "android"
        assert "registered_at" in response_data
        assert "last_seen" in response_data
        assert "is_paused" in response_data
        assert "notification_prefs" in response_data
        assert "stats" in response_data
        assert "server_version" in response_data
        # Verificar que NO expone datos sensibles
        assert "push_token" not in response_data
        assert "session_token" not in response_data
        assert "session_token_hash" not in response_data
    
    def test_update_preferences_success_v1(self, repo, event_bus, sample_device):
        """POST /api/v1/mobile/device/preferences actualiza preferencias."""
        device_id, session_token = sample_device
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/device/preferences"
        
        body_data = json.dumps({
            "preferences": {
                "job_stage_changed": True,
                "order_updated": False,
            }
        }).encode("utf-8")
        handler.headers["Content-Length"] = str(len(body_data))
        handler.rfile = BytesIO(body_data)
        
        device_info = repo.validate_session_token(session_token)
        handler._update_device_preferences(device_info)
        
        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert response_data["success"] is True
        assert "preferences" in response_data
        assert response_data["preferences"]["job_stage_changed"] is True
        assert response_data["preferences"]["order_updated"] is False
    
    def test_update_preferences_invalid_event_type_v1(self, repo, event_bus, sample_device):
        """POST /api/v1/mobile/device/preferences rechaza event_type desconocido."""
        device_id, session_token = sample_device
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/device/preferences"
        handler._send_error = Mock()
        
        body_data = json.dumps({
            "preferences": {
                "unknown_event_type": True,
            }
        }).encode("utf-8")
        handler.headers["Content-Length"] = str(len(body_data))
        handler.rfile = BytesIO(body_data)
        
        device_info = repo.validate_session_token(session_token)
        handler._update_device_preferences(device_info)
        
        handler._send_error.assert_called_once()
        call_args = handler._send_error.call_args[0]
        assert call_args[0] == 400
        assert "Unknown event type" in call_args[1]
    
    def test_update_preferences_non_boolean_value_v1(self, repo, event_bus, sample_device):
        """POST /api/v1/mobile/device/preferences rechaza valores no booleanos."""
        device_id, session_token = sample_device
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/device/preferences"
        handler._send_error = Mock()
        
        body_data = json.dumps({
            "preferences": {
                "job_stage_changed": "yes",  # String en vez de bool
            }
        }).encode("utf-8")
        handler.headers["Content-Length"] = str(len(body_data))
        handler.rfile = BytesIO(body_data)
        
        device_info = repo.validate_session_token(session_token)
        handler._update_device_preferences(device_info)
        
        handler._send_error.assert_called_once()
        call_args = handler._send_error.call_args[0]
        assert call_args[0] == 400
        assert "must be boolean" in call_args[1]


class TestSearchEndpointV1:
    """Tests para endpoint de búsqueda en /api/v1/mobile/jobs/search."""
    
    def test_search_jobs_by_title_v1(self, repo, event_bus, sample_device, sample_order):
        """GET /api/v1/mobile/jobs/search busca por título."""
        device_id, session_token = sample_device
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/jobs/search?q=Pendiente"
        handler._parse_url_params = Mock(return_value={"q": "Pendiente"})
        
        device_info = repo.validate_session_token(session_token)
        handler._search_jobs(device_info)
        
        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert "jobs" in response_data
        assert "query" in response_data
        assert response_data["query"] == "Pendiente"
        # Verificar que encontró el job
        assert len(response_data["jobs"]) > 0
        assert any("Pendiente" in job["title"] for job in response_data["jobs"])
    
    def test_search_jobs_by_client_v1(self, repo, event_bus, sample_device, sample_order):
        """GET /api/v1/mobile/jobs/search busca por cliente."""
        device_id, session_token = sample_device
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/jobs/search?q=Cliente"
        handler._parse_url_params = Mock(return_value={"q": "Cliente"})
        
        device_info = repo.validate_session_token(session_token)
        handler._search_jobs(device_info)
        
        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert "jobs" in response_data
        assert len(response_data["jobs"]) > 0
    
    def test_search_jobs_missing_query_v1(self, repo, event_bus, sample_device):
        """GET /api/v1/mobile/jobs/search sin query retorna 400."""
        device_id, session_token = sample_device
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/jobs/search"
        handler._parse_url_params = Mock(return_value={})
        handler._send_error = Mock()
        
        device_info = repo.validate_session_token(session_token)
        handler._search_jobs(device_info)
        
        handler._send_error.assert_called_once_with(400, "Query parameter 'q' is required")
    
    def test_search_jobs_query_too_long_v1(self, repo, event_bus, sample_device):
        """GET /api/v1/mobile/jobs/search con query muy largo retorna 400."""
        device_id, session_token = sample_device
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        long_query = "x" * 101  # Más de 100 caracteres
        handler.path = f"/api/v1/mobile/jobs/search?q={long_query}"
        handler._parse_url_params = Mock(return_value={"q": long_query})
        handler._send_error = Mock()
        
        device_info = repo.validate_session_token(session_token)
        handler._search_jobs(device_info)
        
        handler._send_error.assert_called_once()
        call_args = handler._send_error.call_args[0]
        assert call_args[0] == 400
        assert "too long" in call_args[1]


class TestLegacyCompatibility:
    """Tests para compatibilidad con rutas legacy /api/mobile/*."""
    
    def test_legacy_jobs_list_still_works(self, repo, event_bus, sample_device, sample_order):
        """Ruta legacy /api/mobile/jobs sigue funcionando."""
        device_id, session_token = sample_device
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/mobile/jobs"
        handler._parse_url_params = Mock(return_value={})
        
        handler._list_jobs({"id": device_id, "device_name": "Test Device"})
        
        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert "jobs" in response_data
    
    def test_legacy_job_detail_still_works(self, repo, event_bus, sample_device, sample_order):
        """Ruta legacy /api/mobile/jobs/{id} sigue funcionando."""
        device_id, session_token = sample_device
        conn = repo.conn
        job = conn.execute("SELECT id FROM order_jobs LIMIT 1").fetchone()
        
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = f"/api/mobile/jobs/{job['id']}"
        
        handler._get_job_detail(job["id"], {"id": device_id, "device_name": "Test Device"})
        
        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert response_data["id"] == job["id"]
    
    def test_legacy_change_stage_still_works(self, repo, event_bus, sample_device, sample_order):
        """Ruta legacy /api/mobile/jobs/{id}/stage sigue funcionando."""
        device_id, session_token = sample_device
        conn = repo.conn
        job = conn.execute("SELECT id FROM order_jobs WHERE status = 'Recibido' LIMIT 1").fetchone()

        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = f"/api/mobile/jobs/{job['id']}/stage"

        body_data = json.dumps({"stage": "Impresión", "notes": "Legacy test"}).encode("utf-8")
        handler.headers["Content-Length"] = str(len(body_data))
        handler.rfile = BytesIO(body_data)

        handler._change_job_stage(job["id"], {"id": device_id, "device_name": "Test Device"})

        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert response_data["success"] is True


class TestCapabilitiesEndpoint:
    """Tests para endpoint /api/v1/mobile/capabilities."""

    def test_capabilities_requires_auth(self, repo, event_bus):
        """Endpoint capabilities requiere autenticación."""
        handler = create_handler(repo, event_bus)
        handler._send_error = Mock()
        handler.headers = {}
        handler.path = "/api/v1/mobile/capabilities"
        handler.do_GET()

        handler._send_error.assert_called_once_with(401, "Authorization header missing")

    def test_capabilities_returns_contract(self, repo, event_bus, sample_device):
        """Endpoint capabilities retorna contrato válido."""
        device_id, session_token = sample_device

        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/capabilities"

        handler._get_capabilities()

        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert response_data["api_version"] == "1.0"
        assert response_data["server_version"] == "1.0.0"
        assert "jobs" in response_data["supported_types"]
        assert "orders" in response_data["supported_types"]
        assert "clients" in response_data["supported_types"]
        assert response_data["max_limit"] == 500
        assert response_data["cursor_version"] == 1
        assert response_data["supports_pull"] is True
        assert response_data["supports_push"] is False
        assert response_data["supports_deletions"] is False


class TestSyncPullEndpoint:
    """Tests para endpoint /api/v1/mobile/sync/pull."""

    def test_sync_pull_requires_auth(self, repo, event_bus):
        """Endpoint sync/pull requiere autenticación."""
        handler = create_handler(repo, event_bus)
        handler._send_error = Mock()
        handler.headers = {}
        handler.path = "/api/v1/mobile/sync/pull"
        handler.do_GET()

        handler._send_error.assert_called_once_with(401, "Authorization header missing")

    def test_sync_pull_empty_first_sync(self, repo, event_bus, sample_device):
        """Primera sincronización sin datos retorna estructura válida."""
        device_id, session_token = sample_device

        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/sync/pull"
        handler._parse_url_params = Mock(return_value={"limit": "10"})

        handler._sync_pull({"id": device_id, "device_name": "Test Device"})

        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert "server_time" in response_data
        assert "snapshot_until" in response_data
        assert "complete" in response_data
        assert "next_cursor" in response_data
        assert "entities" in response_data
        assert "jobs" in response_data["entities"]
        assert "orders" in response_data["entities"]
        assert "clients" in response_data["entities"]

    def test_sync_pull_with_data(self, repo, event_bus, sample_device, sample_order):
        """Primera sincronización con datos retorna items."""
        device_id, session_token = sample_device

        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/sync/pull"
        handler._parse_url_params = Mock(return_value={"limit": "10"})

        handler._sync_pull({"id": device_id, "device_name": "Test Device"})

        response_data = json.loads(handler.response.body.decode("utf-8"))
        jobs = response_data["entities"]["jobs"]["items"]
        # Debe haber al menos un job del sample_order
        assert len(jobs) > 0
        assert "id" in jobs[0]
        assert "updated_at" in jobs[0]

    def test_sync_pull_limit_plus_one(self, repo, event_bus, sample_device):
        """LIMIT + 1 determina has_more correctamente."""
        device_id, session_token = sample_device

        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/sync/pull"
        handler._parse_url_params = Mock(return_value={"limit": "2"})

        handler._sync_pull({"id": device_id, "device_name": "Test Device"})

        response_data = json.loads(handler.response.body.decode("utf-8"))
        jobs = response_data["entities"]["jobs"]["items"]
        # Si hay más de 2 jobs, has_more debe ser True
        if len(jobs) == 2:
            assert response_data["entities"]["jobs"]["has_more"] is True

    def test_sync_pull_cursor_pagination(self, repo, event_bus, sample_device):
        """Paginación con cursor funciona correctamente."""
        device_id, session_token = sample_device

        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/sync/pull"
        handler._parse_url_params = Mock(return_value={"limit": "1"})

        # Primera página
        handler._sync_pull({"id": device_id, "device_name": "Test Device"})
        response_data = json.loads(handler.response.body.decode("utf-8"))
        next_cursor = response_data.get("next_cursor")

        if next_cursor:
            # Segunda página con cursor
            handler._parse_url_params = Mock(return_value={"cursor": next_cursor, "limit": "1"})
            handler._sync_pull({"id": device_id, "device_name": "Test Device"})
            response_data_2 = json.loads(handler.response.body.decode("utf-8"))
            assert "entities" in response_data_2

    def test_sync_pull_partial_types(self, repo, event_bus, sample_device):
        """Sincronización parcial de tipos funciona."""
        device_id, session_token = sample_device

        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/sync/pull"
        handler._parse_url_params = Mock(return_value={"types": "jobs", "limit": "10"})

        handler._sync_pull({"id": device_id, "device_name": "Test Device"})

        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert "jobs" in response_data["entities"]
        # orders y clients no deben estar presentes
        assert "orders" not in response_data["entities"]
        assert "clients" not in response_data["entities"]

    def test_sync_pull_invalid_cursor(self, repo, event_bus, sample_device):
        """Cursor inválido retorna error 400."""
        device_id, session_token = sample_device

        handler = create_handler(repo, event_bus)
        handler._send_error = Mock()
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/sync/pull"
        handler._parse_url_params = Mock(return_value={"cursor": "invalid_base64_token"})

        handler._sync_pull({"id": device_id, "device_name": "Test Device"})

        handler._send_error.assert_called_once()
        call_args = handler._send_error.call_args[0]
        assert call_args[0] == 400

    def test_sync_pull_cursor_with_since_rejected(self, repo, event_bus, sample_device):
        """No se puede usar cursor con since simultáneamente."""
        device_id, session_token = sample_device

        # Primero obtener un cursor válido
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/sync/pull"
        handler._parse_url_params = Mock(return_value={"limit": "1"})
        handler._sync_pull({"id": device_id, "device_name": "Test Device"})
        response_data = json.loads(handler.response.body.decode("utf-8"))
        cursor = response_data.get("next_cursor")

        if cursor:
            # Intentar usar cursor con since
            handler._send_error = Mock()
            handler._parse_url_params = Mock(return_value={"cursor": cursor, "since": "2026-07-21T00:00:00"})
            handler._sync_pull({"id": device_id, "device_name": "Test Device"})

            handler._send_error.assert_called_once()
            call_args = handler._send_error.call_args[0]
            assert call_args[0] == 400

    def test_sync_pull_limit_validation(self, repo, event_bus, sample_device):
        """Validación de limit funciona correctamente."""
        device_id, session_token = sample_device

        # Test limit 0 (inválido)
        handler = create_handler(repo, event_bus)
        handler._send_error = Mock()
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/sync/pull"
        handler._parse_url_params = Mock(return_value={"limit": "0"})
        handler._sync_pull({"id": device_id, "device_name": "Test Device"})
        handler._send_error.assert_called_once()
        call_args = handler._send_error.call_args[0]
        assert call_args[0] == 400

        # Test limit 501 (inválido)
        handler._send_error.reset_mock()
        handler._parse_url_params = Mock(return_value={"limit": "501"})
        handler._sync_pull({"id": device_id, "device_name": "Test Device"})
        handler._send_error.assert_called_once()
        call_args = handler._send_error.call_args[0]
        assert call_args[0] == 400

        # Test limit 1 (válido)
        handler._send_error.reset_mock()
        handler._parse_url_params = Mock(return_value={"limit": "1"})
        handler._sync_pull({"id": device_id, "device_name": "Test Device"})
        handler._send_error.assert_not_called()

        # Test limit 500 (válido)
        handler._send_error.reset_mock()
        handler._parse_url_params = Mock(return_value={"limit": "500"})
        handler._sync_pull({"id": device_id, "device_name": "Test Device"})
        handler._send_error.assert_not_called()

    def test_sync_pull_incremental_with_since(self, repo, event_bus, sample_device):
        """Sincronización incremental con since funciona."""
        device_id, session_token = sample_device

        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/sync/pull"
        handler._parse_url_params = Mock(return_value={"since": "2026-07-20T00:00:00", "limit": "10"})

        handler._sync_pull({"id": device_id, "device_name": "Test Device"})

        response_data = json.loads(handler.response.body.decode("utf-8"))
        assert "entities" in response_data


class TestHealthEndpoint:
    """Tests para GET /api/v1/mobile/health — endpoint público sin autenticación."""

    def test_health_200_without_authorization(self, repo, event_bus):
        """Health check responde 200 sin header Authorization."""
        handler = create_handler(repo, event_bus)
        handler.headers = {}
        handler.path = "/api/v1/mobile/health"

        handler._get_health()

        assert handler.response.status_code == 200

    def test_health_content_type_json(self, repo, event_bus):
        """Content-Type es application/json."""
        handler = create_handler(repo, event_bus)
        handler.headers = {}
        handler.path = "/api/v1/mobile/health"

        handler._get_health()

        assert handler.response.headers["Content-Type"] == "application/json"

    def test_health_status_ok(self, repo, event_bus):
        """Campo status == 'ok'."""
        handler = create_handler(repo, event_bus)
        handler.headers = {}
        handler.path = "/api/v1/mobile/health"

        handler._get_health()

        data = json.loads(handler.response.body.decode("utf-8"))
        assert data["status"] == "ok"

    def test_health_service_name(self, repo, event_bus):
        """Campo service == 'doccione-studio'."""
        handler = create_handler(repo, event_bus)
        handler.headers = {}
        handler.path = "/api/v1/mobile/health"

        handler._get_health()

        data = json.loads(handler.response.body.decode("utf-8"))
        assert data["service"] == "doccione-studio"

    def test_health_api_version(self, repo, event_bus):
        """Campo api_version == 'v1'."""
        handler = create_handler(repo, event_bus)
        handler.headers = {}
        handler.path = "/api/v1/mobile/health"

        handler._get_health()

        data = json.loads(handler.response.body.decode("utf-8"))
        assert data["api_version"] == "v1"

    def test_health_mobile_api_true(self, repo, event_bus):
        """Campo mobile_api == True."""
        handler = create_handler(repo, event_bus)
        handler.headers = {}
        handler.path = "/api/v1/mobile/health"

        handler._get_health()

        data = json.loads(handler.response.body.decode("utf-8"))
        assert data["mobile_api"] is True

    def test_health_does_not_touch_repo(self, repo, event_bus):
        """Health check no accede al repositorio."""
        handler = create_handler(repo, event_bus)
        handler.headers = {}
        handler.path = "/api/v1/mobile/health"

        original_conn = handler.event_repo.conn
        handler.event_repo = Mock()
        handler.event_repo.conn = original_conn

        handler._get_health()

        handler.event_repo.validate_session_token.assert_not_called()

    def test_other_endpoints_still_require_auth(self, repo, event_bus):
        """Endpoints protegidos siguen pidiendo autenticación."""
        handler = create_handler(repo, event_bus)
        handler.headers = {}
        handler.path = "/api/v1/mobile/jobs"
        handler._send_error = Mock()

        handler.do_GET()

        handler._send_error.assert_called_once_with(401, "Authorization header missing")

    def test_health_via_do_GET_no_auth_required(self, repo, event_bus):
        """GET /api/v1/mobile/health vía do_GET no requiere token."""
        handler = create_handler(repo, event_bus)
        handler.headers = {}
        handler.path = "/api/v1/mobile/health"

        handler.do_GET()

        assert handler.response.status_code == 200
        data = json.loads(handler.response.body.decode("utf-8"))
        assert data["status"] == "ok"


class TestHandlerInitRealRepo:
    """Regresión: MobileJobsHandler.__init__ con EventRepository real."""

    def test_init_does_not_raise(self, repo, event_bus):
        """MobileJobsHandler se instancia con EventRepository real sin error."""
        handler = MobileJobsHandler.__new__(MobileJobsHandler)
        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "app.api.mobile_jobs.BaseHTTPRequestHandler.__init__"
        ):
            handler.__init__(event_repo=repo, event_bus=event_bus)
        assert handler.event_repo is repo

    def test_stage_service_receives_correct_connection(self, repo, event_bus):
        """ProductionStageService recibe repo.conn (sqlite3.Connection)."""
        handler = MobileJobsHandler.__new__(MobileJobsHandler)
        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "app.api.mobile_jobs.BaseHTTPRequestHandler.__init__"
        ):
            handler.__init__(event_repo=repo, event_bus=event_bus)
        from app.services.production_stage_service import ProductionStageService
        assert isinstance(handler.stage_service, ProductionStageService)
        assert handler.stage_service.conn is repo.conn

    def test_protected_endpoint_returns_401_not_crash(self, repo, event_bus):
        """GET /api/v1/mobile/jobs sin token devuelve 401 en vez de cerrar conexión."""
        handler = create_handler(repo, event_bus)
        handler.headers = {}
        handler.path = "/api/v1/mobile/jobs"
        handler._send_error = Mock()

        handler.do_GET()

        handler._send_error.assert_called_once_with(401, "Authorization header missing")


class TestServerBindConfiguration:
    """Verifica que MobileJobsServer escucha en 0.0.0.0:port."""

    def test_bind_host_is_0_0_0_0(self, repo, event_bus):
        """HTTPServer se crea con host 0.0.0.0 para acceso en red local."""
        from app.api.mobile_jobs import MobileJobsServer
        from unittest.mock import patch as mock_patch

        mock_server = MagicMock()
        with mock_patch("app.api.mobile_jobs.HTTPServer", return_value=mock_server) as MockHTTP:
            server = MobileJobsServer(event_repo=repo, event_bus=event_bus, port=9999)
            server.start()
            server.stop()
            args, _ = MockHTTP.call_args
            assert args[0] == ("0.0.0.0", 9999)

    def test_port_matches_constructor(self, repo, event_bus):
        """El puerto usado es el recibido por el constructor."""
        from app.api.mobile_jobs import MobileJobsServer
        from unittest.mock import patch as mock_patch

        mock_server = MagicMock()
        with mock_patch("app.api.mobile_jobs.HTTPServer", return_value=mock_server) as MockHTTP:
            server = MobileJobsServer(event_repo=repo, event_bus=event_bus, port=5555)
            server.start()
            server.stop()
            args, _ = MockHTTP.call_args
            assert args[0][1] == 5555

    def test_health_responds_200(self, repo, event_bus):
        """Health endpoint sigue respondiendo 200 después del cambio de bind."""
        handler = create_handler(repo, event_bus)
        handler.headers = {}
        handler.path = "/api/v1/mobile/health"

        handler._get_health()

        assert handler.response.status_code == 200
        data = json.loads(handler.response.body.decode("utf-8"))
        assert data["status"] == "ok"

    def test_protected_still_401_without_token(self, repo, event_bus):
        """Endpoints protegidos siguen devolviendo 401 sin token."""
        handler = create_handler(repo, event_bus)
        handler.headers = {}
        handler.path = "/api/v1/mobile/jobs"
        handler._send_error = Mock()

        handler.do_GET()

        handler._send_error.assert_called_once_with(401, "Authorization header missing")


# ── Tests para Quick-Edit Endpoints ─────────────────────────────────────────

def _make_handler_with_body(repo, event_bus, session_token, path, body_dict):
    """Helper: crea un handler con body JSON simulado."""
    handler = create_handler(repo, event_bus)
    handler.headers = {"Authorization": f"Bearer {session_token}"}
    handler.path = path
    body_data = json.dumps(body_dict).encode("utf-8")
    handler.headers["Content-Length"] = str(len(body_data))
    handler.rfile = BytesIO(body_data)
    return handler


# ── PATCH /orders/{id}/status ──────────────────────────────────────────────

class TestUpdateOrderStatus:
    """Tests para PATCH /api/v1/mobile/orders/{id}/status."""

    def test_update_status_success(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/status",
                                          {"status": "En producción"})
        handler._update_order_status(sample_order, device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert data["success"] is True
        assert data["order"]["status"] == "En producción"

    def test_update_status_not_found(self, repo, event_bus, sample_device):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          "/api/v1/mobile/orders/99999/status",
                                          {"status": "Finalizado"})
        handler._update_order_status(99999, device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert "error" in data
        assert "not found" in data["error"].lower()

    def test_update_status_invalid_value(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/status",
                                          {"status": "ValorInvalido"})
        handler._update_order_status(sample_order, device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert "error" in data
        assert "Invalid status" in data["error"]

    def test_update_status_missing_field(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/status",
                                          {})
        handler._update_order_status(sample_order, device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert "error" in data
        assert "required" in data["error"]

    def test_update_status_empty_body(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = f"/api/v1/mobile/orders/{sample_order}/status"
        handler.headers["Content-Length"] = "0"
        handler.rfile = BytesIO(b"")
        handler._update_order_status(sample_order, device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert "error" in data
        assert "body is required" in data["error"]


# ── PATCH /orders/{id}/priority ─────────────────────────────────────────────

class TestUpdateOrderPriority:
    """Tests para PATCH /api/v1/mobile/orders/{id}/priority."""

    def test_update_priority_success(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/priority",
                                          {"print_priority": 3})
        handler._update_order_priority(sample_order, device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert data["success"] is True
        assert data["order"]["print_priority"] == 3

    def test_update_priority_clamp_low(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/priority",
                                          {"print_priority": -5})
        handler._update_order_priority(sample_order, device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert "error" in data
        assert "between 0 and 4" in data["error"]

    def test_update_priority_clamp_high(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/priority",
                                          {"print_priority": 10})
        handler._update_order_priority(sample_order, device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert "error" in data
        assert "between 0 and 4" in data["error"]

    def test_update_priority_not_found(self, repo, event_bus, sample_device):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          "/api/v1/mobile/orders/99999/priority",
                                          {"print_priority": 2})
        handler._update_order_priority(99999, device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert "error" in data

    def test_update_priority_missing_field(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/priority",
                                          {})
        handler._update_order_priority(sample_order, device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert "error" in data
        assert "required" in data["error"]

    def test_update_priority_not_integer(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/priority",
                                          {"print_priority": "alta"})
        handler._update_order_priority(sample_order, device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert "error" in data
        assert "integer" in data["error"]


# ── PATCH /orders/{oid}/jobs/{jid} ─────────────────────────────────────────

class TestUpdateJobFields:
    """Tests para PATCH /api/v1/mobile/orders/{oid}/jobs/{jid}."""

    def test_update_quantity_success(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        conn = repo.conn
        job = conn.execute("SELECT id FROM order_jobs WHERE order_id = ? LIMIT 1", (sample_order,)).fetchone()
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/jobs/{job['id']}",
                                          {"quantity": 25})
        handler._update_job_fields(sample_order, job["id"], device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert data["success"] is True
        assert data["job"]["quantity"] == 25

    def test_update_size_success(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        conn = repo.conn
        job = conn.execute("SELECT id FROM order_jobs WHERE order_id = ? LIMIT 1", (sample_order,)).fetchone()
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/jobs/{job['id']}",
                                          {"size": "20cm"})
        handler._update_job_fields(sample_order, job["id"], device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert data["success"] is True
        assert data["job"]["size"] == "20cm"

    def test_update_both_fields(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        conn = repo.conn
        job = conn.execute("SELECT id FROM order_jobs WHERE order_id = ? LIMIT 1", (sample_order,)).fetchone()
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/jobs/{job['id']}",
                                          {"quantity": 50, "size": "15cm"})
        handler._update_job_fields(sample_order, job["id"], device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert data["success"] is True
        assert data["job"]["quantity"] == 50
        assert data["job"]["size"] == "15cm"

    def test_quantity_floor_at_one(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        conn = repo.conn
        job = conn.execute("SELECT id FROM order_jobs WHERE order_id = ? LIMIT 1", (sample_order,)).fetchone()
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/jobs/{job['id']}",
                                          {"quantity": -3})
        handler._update_job_fields(sample_order, job["id"], device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert data["success"] is True
        assert data["job"]["quantity"] == 1

    def test_job_not_found(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/jobs/99999",
                                          {"quantity": 5})
        handler._update_job_fields(sample_order, 99999, device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert "error" in data
        assert "not found" in data["error"].lower()

    def test_missing_all_fields(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        conn = repo.conn
        job = conn.execute("SELECT id FROM order_jobs WHERE order_id = ? LIMIT 1", (sample_order,)).fetchone()
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/jobs/{job['id']}",
                                          {})
        handler._update_job_fields(sample_order, job["id"], device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert "error" in data
        assert "required" in data["error"]

    def test_order_total_quantity_updates(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        conn = repo.conn
        job = conn.execute("SELECT id FROM order_jobs WHERE order_id = ? LIMIT 1", (sample_order,)).fetchone()
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/jobs/{job['id']}",
                                          {"quantity": 99})
        handler._update_job_fields(sample_order, job["id"], device)

        # sample_order has 3 jobs with qty 5 each (total 15). Changing one to 99 → 99+5+5 = 109
        order_row = conn.execute("SELECT quantity FROM orders WHERE id = ?", (sample_order,)).fetchone()
        assert order_row["quantity"] == 109


# ── POST /orders/{id}/payments ──────────────────────────────────────────────

class TestRegisterPayment:
    """Tests para POST /api/v1/mobile/orders/{id}/payments."""

    def test_register_payment_success(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/payments",
                                          {"amount": 2500, "method": "Efectivo"})
        handler._register_payment(sample_order, device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert data["success"] is True
        assert data["payment"]["amount"] == 2500.0
        assert data["payment"]["method"] == "Efectivo"
        assert "financials" in data

    def test_register_payment_not_found(self, repo, event_bus, sample_device):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          "/api/v1/mobile/orders/99999/payments",
                                          {"amount": 1000})
        handler._register_payment(99999, device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert "error" in data

    def test_register_payment_zero_amount(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/payments",
                                          {"amount": 0})
        handler._register_payment(sample_order, device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert "error" in data
        assert "greater than zero" in data["error"]

    def test_register_payment_negative_amount(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/payments",
                                          {"amount": -100})
        handler._register_payment(sample_order, device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert "error" in data

    def test_register_payment_missing_amount(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/payments",
                                          {"method": "Transferencia"})
        handler._register_payment(sample_order, device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert "error" in data
        assert "required" in data["error"]

    def test_payment_creates_event(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/payments",
                                          {"amount": 1500, "method": "MP"})
        handler._register_payment(sample_order, device)

        events = repo.conn.execute(
            "SELECT * FROM order_events WHERE order_id = ? AND event_type = 'payment.received'",
            (sample_order,),
        ).fetchall()
        assert len(events) >= 1


# ── POST /orders/{id}/deliver ───────────────────────────────────────────────

class TestMarkDelivered:
    """Tests para POST /api/v1/mobile/orders/{id}/deliver."""

    def test_mark_delivered_success(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        repo.conn.execute(
            "UPDATE order_jobs SET status = 'Finalizado' WHERE order_id = ?", (sample_order,)
        )
        repo.conn.commit()

        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = f"/api/v1/mobile/orders/{sample_order}/deliver"
        handler._mark_delivered(sample_order, device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert data["success"] is True
        assert data["order"]["status"] == "Entregado"

    def test_mark_delivered_not_found(self, repo, event_bus, sample_device):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/orders/99999/deliver"
        handler._mark_delivered(99999, device)

        data = json.loads(handler.response.body.decode("utf-8"))
        assert "error" in data
        assert "not found" in data["error"].lower()

    def test_mark_delivered_creates_event(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = f"/api/v1/mobile/orders/{sample_order}/deliver"
        handler._mark_delivered(sample_order, device)

        events = repo.conn.execute(
            "SELECT * FROM order_events WHERE order_id = ? AND event_type = 'order.delivered'",
            (sample_order,),
        ).fetchall()
        assert len(events) >= 1

    def test_mark_delivered_all_jobs_entregado_status(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        device = {"id": device_id, "device_name": "Test Device"}
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = f"/api/v1/mobile/orders/{sample_order}/deliver"
        handler._mark_delivered(sample_order, device)

        jobs = repo.conn.execute(
            "SELECT status FROM order_jobs WHERE order_id = ?", (sample_order,)
        ).fetchall()
        assert all(j["status"] == "Entregado" for j in jobs)


# ── do_PATCH routing ────────────────────────────────────────────────────────

class TestDoPATCHRouting:
    """Verifica que do_PATCH enruta correctamente."""

    def test_patch_status_routes_correctly(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/status",
                                          {"status": "Finalizado"})
        handler.do_PATCH()
        data = json.loads(handler.response.body.decode("utf-8"))
        assert data["success"] is True

    def test_patch_priority_routes_correctly(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/priority",
                                          {"print_priority": 1})
        handler.do_PATCH()
        data = json.loads(handler.response.body.decode("utf-8"))
        assert data["success"] is True

    def test_patch_unknown_returns_404(self, repo, event_bus, sample_device):
        device_id, session_token = sample_device
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = "/api/v1/mobile/orders/1/unknown"
        handler.do_PATCH()
        data = json.loads(handler.response.body.decode("utf-8"))
        assert "error" in data
        assert "not found" in data["error"].lower()

    def test_post_deliver_routes_correctly(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        handler = create_handler(repo, event_bus)
        handler.headers = {"Authorization": f"Bearer {session_token}"}
        handler.path = f"/api/v1/mobile/orders/{sample_order}/deliver"
        handler.headers["Content-Length"] = "2"
        handler.rfile = BytesIO(b"{}")
        handler.do_POST()
        data = json.loads(handler.response.body.decode("utf-8"))
        assert data["success"] is True

    def test_post_payment_routes_correctly(self, repo, event_bus, sample_device, sample_order):
        device_id, session_token = sample_device
        handler = _make_handler_with_body(repo, event_bus, session_token,
                                          f"/api/v1/mobile/orders/{sample_order}/payments",
                                          {"amount": 500})
        handler.do_POST()
        data = json.loads(handler.response.body.decode("utf-8"))
        assert data["success"] is True


# ── Auth check for do_PATCH ─────────────────────────────────────────────────

class TestDoPATCHRequiresAuth:
    """Verifica que do_PATCH requiere autenticación."""

    def test_patch_requires_auth(self, repo, event_bus, sample_order):
        handler = create_handler(repo, event_bus)
        handler.headers = {}
        handler.path = f"/api/v1/mobile/orders/{sample_order}/status"
        handler._send_error = Mock()
        handler.do_PATCH()
        handler._send_error.assert_called_once_with(401, "Authorization header missing")
