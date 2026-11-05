import sqlite3

import pytest

from app.events.event_bus import EventBus
from app.events.event_repository import EventRepository
from app.services.order_workflow_service import OrderWorkflowService
from app.services.stock_cost_price_service import StockCostPriceService


@pytest.fixture()
def workflow():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, status TEXT, material TEXT, size TEXT, quantity INTEGER, price REAL, discount_percent REAL DEFAULT 0, extra_services TEXT DEFAULT '', observations TEXT DEFAULT '', cost_mp REAL DEFAULT 0, cost_mo REAL DEFAULT 0, cost_cf REAL DEFAULT 0, cost_total REAL DEFAULT 0, updated_at TEXT, is_archived INTEGER DEFAULT 0)")
    connection.execute("CREATE TABLE order_jobs (id INTEGER PRIMARY KEY, order_id INTEGER, title TEXT, material TEXT, size TEXT, quantity INTEGER, subtotal REAL, discount_percent REAL DEFAULT 0, extra_services TEXT DEFAULT '', status TEXT, notes TEXT DEFAULT '', sort_order INTEGER DEFAULT 0, cost_mp REAL DEFAULT 0, cost_mo REAL DEFAULT 0, cost_cf REAL DEFAULT 0, cost_total REAL DEFAULT 0, created_at TEXT, updated_at TEXT)")
    connection.execute("CREATE TABLE order_events (id INTEGER PRIMARY KEY, order_id INTEGER, event_type TEXT, message TEXT, data_json TEXT, created_at TEXT)")
    connection.execute("CREATE TABLE price_rules (id INTEGER PRIMARY KEY, material TEXT, active INTEGER, variable_cost_model_id INTEGER)")
    connection.execute("CREATE TABLE variable_cost_models (id INTEGER PRIMARY KEY, name TEXT, active INTEGER)")
    connection.execute("CREATE TABLE variable_cost_components (id INTEGER PRIMARY KEY, model_id INTEGER, name TEXT, quantity REAL, unit_value REAL, unit TEXT)")
    stock = StockCostPriceService(connection)
    events = EventBus(EventRepository(connection))
    EventRepository(connection).create_tables()
    return connection, stock, events, OrderWorkflowService(connection, stock, events)


def configure_material(workflow, stock=10):
    connection, service, _events, _workflow = workflow
    material_id = service.create_material(name="Vinilo", unit="u", physical_stock=stock)
    connection.execute("INSERT INTO variable_cost_models (id, name, active) VALUES (1, 'Vinilo', 1)")
    connection.execute("INSERT INTO variable_cost_components (id, model_id, name, quantity, unit_value, unit) VALUES (1, 1, 'Vinilo', 2, 0, 'u')")
    connection.execute("INSERT INTO material_component_links(material_id, component_id, created_at) VALUES (?, 1, 'now')", (material_id,))
    connection.execute("INSERT INTO price_rules(id, material, active, variable_cost_model_id) VALUES (1, 'Vinilo', 1, 1)")
    connection.commit()


def create_order(workflow, status="Nuevo", jobs=True):
    connection, _stock, _events, _workflow = workflow
    connection.execute("INSERT INTO orders(id, status, material, size, quantity, price) VALUES (1, ?, 'Vinilo', '10cm', 2, 100)", (status,))
    if jobs:
        connection.execute("INSERT INTO order_jobs(id, order_id, title, material, size, quantity, subtotal, status) VALUES (1, 1, 'Sticker', 'Vinilo', '10cm', 2, 100, 'Nuevo')")
    connection.commit()


def test_acceptance_is_atomic_and_publishes_event(workflow):
    configure_material(workflow)
    create_order(workflow)
    result = workflow[3].accept_order(1, actor="Ana")
    assert result["success"] and result["stock_reserved"]
    assert workflow[0].execute("SELECT status FROM orders WHERE id = 1").fetchone()[0] == "Recibido"
    assert workflow[0].execute("SELECT reserved_stock FROM materials").fetchone()[0] == 4
    assert workflow[0].execute("SELECT COUNT(*) FROM order_events WHERE event_type = 'order.accepted'").fetchone()[0] == 1
    assert workflow[0].execute("SELECT COUNT(*) FROM app_events WHERE event_type = 'order.accepted'").fetchone()[0] == 1


def test_acceptance_is_idempotent(workflow):
    configure_material(workflow)
    create_order(workflow)
    workflow[3].accept_order(1)
    second = workflow[3].accept_order(1)
    assert second["already_processed"]
    assert workflow[0].execute("SELECT COUNT(*) FROM order_jobs WHERE order_id = 1").fetchone()[0] == 1
    assert workflow[0].execute("SELECT COUNT(*) FROM order_stock_reservations").fetchone()[0] == 1
    assert workflow[0].execute("SELECT COUNT(*) FROM order_events WHERE event_type = 'order.accepted'").fetchone()[0] == 1


def test_insufficient_stock_rolls_back_everything(workflow):
    configure_material(workflow, stock=3)
    create_order(workflow)
    with pytest.raises(RuntimeError, match="Stock insuficiente"):
        workflow[3].accept_order(1)
    assert workflow[0].execute("SELECT status FROM orders WHERE id = 1").fetchone()[0] == "Nuevo"
    assert workflow[0].execute("SELECT COUNT(*) FROM order_stock_reservations").fetchone()[0] == 0
    assert workflow[0].execute("SELECT COUNT(*) FROM order_events WHERE event_type = 'order.accepted'").fetchone()[0] == 0


def test_error_after_job_creation_rolls_back(workflow, monkeypatch):
    create_order(workflow, jobs=False)
    monkeypatch.setattr(workflow[3], "_cost_model_id_for_job", lambda _job: (_ for _ in ()).throw(RuntimeError("fallo controlado")))
    with pytest.raises(RuntimeError, match="fallo controlado"):
        workflow[3].accept_order(1)
    assert workflow[0].execute("SELECT status FROM orders WHERE id = 1").fetchone()[0] == "Nuevo"
    assert workflow[0].execute("SELECT COUNT(*) FROM order_jobs WHERE order_id = 1").fetchone()[0] == 0


def test_missing_order_is_clear(workflow):
    with pytest.raises(ValueError, match="no encontrado"):
        workflow[3].accept_order(999)


def test_already_accepted_order_is_idempotent(workflow):
    configure_material(workflow)
    create_order(workflow, status="Recibido")
    workflow[3].accept_order(1)
    assert workflow[3].accept_order(1)["already_processed"]
