"""Smoke test without pytest for constrained desktop installations."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.events.event_bus import EventBus
from app.events.event_repository import EventRepository
from app.services.order_workflow_service import OrderWorkflowService
from app.services.stock_cost_price_service import StockCostPriceService


def run() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE orders (id INTEGER PRIMARY KEY, status TEXT, material TEXT, size TEXT, quantity INTEGER, price REAL, discount_percent REAL DEFAULT 0, extra_services TEXT DEFAULT '', observations TEXT DEFAULT '', cost_mp REAL DEFAULT 0, cost_mo REAL DEFAULT 0, cost_cf REAL DEFAULT 0, cost_total REAL DEFAULT 0, updated_at TEXT, is_archived INTEGER DEFAULT 0);
        CREATE TABLE order_jobs (id INTEGER PRIMARY KEY, order_id INTEGER, title TEXT, material TEXT, size TEXT, quantity INTEGER, subtotal REAL, discount_percent REAL DEFAULT 0, extra_services TEXT DEFAULT '', status TEXT, notes TEXT DEFAULT '', sort_order INTEGER DEFAULT 0, cost_mp REAL DEFAULT 0, cost_mo REAL DEFAULT 0, cost_cf REAL DEFAULT 0, cost_total REAL DEFAULT 0, created_at TEXT, updated_at TEXT);
        CREATE TABLE order_events (id INTEGER PRIMARY KEY, order_id INTEGER, event_type TEXT, message TEXT, data_json TEXT, created_at TEXT);
        CREATE TABLE price_rules (id INTEGER PRIMARY KEY, material TEXT, active INTEGER, variable_cost_model_id INTEGER);
        CREATE TABLE variable_cost_models (id INTEGER PRIMARY KEY, name TEXT, active INTEGER);
        CREATE TABLE variable_cost_components (id INTEGER PRIMARY KEY, model_id INTEGER, name TEXT, quantity REAL, unit_value REAL, unit TEXT);
    """)
    stock = StockCostPriceService(connection)
    event_repo = EventRepository(connection)
    event_repo.create_tables()
    material_id = stock.create_material(name="Vinilo", physical_stock=10)
    connection.executescript("""
        INSERT INTO variable_cost_models VALUES (1, 'Modelo', 1);
        INSERT INTO variable_cost_components VALUES (1, 1, 'Vinilo', 2, 0, 'u');
        INSERT INTO price_rules VALUES (1, 'Vinilo', 1, 1);
        INSERT INTO orders(id, status, material, size, quantity, price) VALUES (1, 'Nuevo', 'Vinilo', '10cm', 2, 100);
        INSERT INTO order_jobs(id, order_id, title, material, size, quantity, subtotal, status) VALUES (1, 1, 'Trabajo', 'Vinilo', '10cm', 2, 100, 'Nuevo');
    """)
    connection.execute("INSERT INTO material_component_links(material_id, component_id, created_at) VALUES (?, 1, 'now')", (material_id,))
    connection.commit()
    workflow = OrderWorkflowService(connection, stock, EventBus(event_repo))
    first = workflow.accept_order(1)
    second = workflow.accept_order(1)
    assert first["stock_reserved"] and second["already_processed"]
    assert connection.execute("SELECT reserved_stock FROM materials").fetchone()[0] == 4
    assert connection.execute("SELECT COUNT(*) FROM order_events WHERE event_type = 'order.accepted'").fetchone()[0] == 1
    print("manual acceptance/idempotence: PASS")


if __name__ == "__main__":
    run()
