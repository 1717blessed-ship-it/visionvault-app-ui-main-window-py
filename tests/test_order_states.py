import sqlite3

import pytest

from app.domain.order_states import (
    OrderStateService,
    derive_order_status_from_jobs,
    normalize_status,
    validate_transition,
)


def _connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE orders(id INTEGER PRIMARY KEY,status TEXT,updated_at TEXT,delivery_date TEXT DEFAULT '',print_priority INTEGER DEFAULT 0);
        CREATE TABLE order_jobs(id INTEGER PRIMARY KEY,order_id INTEGER,status TEXT,updated_at TEXT,quantity REAL DEFAULT 1,title TEXT DEFAULT '',material TEXT DEFAULT '',size TEXT DEFAULT '');
        CREATE TABLE plancha_item_assignments(order_job_id INTEGER,quantity REAL,state TEXT);
        CREATE TABLE order_design_demand_lines(order_job_id INTEGER);
        CREATE TABLE order_designs(id INTEGER PRIMARY KEY,order_id INTEGER,status TEXT);
        CREATE TABLE plancha_projects(id INTEGER PRIMARY KEY,order_id INTEGER,production_status TEXT,updated_at TEXT);
        CREATE TABLE order_events(id INTEGER PRIMARY KEY,order_id INTEGER,event_type TEXT,message TEXT,data_json TEXT,created_at TEXT);
        CREATE TABLE order_state_history(id INTEGER PRIMARY KEY,order_id INTEGER,previous_status TEXT,new_status TEXT,actor TEXT,source TEXT,reason TEXT,changed_at TEXT);
        INSERT INTO orders(id,status,print_priority) VALUES(1,'En producción',4);
        INSERT INTO order_jobs(id,order_id,status) VALUES(10,1,'Impresión');
        INSERT INTO plancha_item_assignments VALUES(10,1,'finished');
        INSERT INTO order_designs(id,order_id,status) VALUES(20,1,'Confirmado');
        INSERT INTO plancha_projects(id,order_id,production_status) VALUES(30,1,'impresa');
        """
    )
    from app.services.delivery_readiness import install_delivery_guards
    install_delivery_guards(connection)
    return connection


def test_aliases_and_derivation_share_one_rule():
    assert normalize_status("Recibado") == "Recibido"
    assert normalize_status("  entregado ") == "Entregado"
    assert derive_order_status_from_jobs(["Recibido", "Recibido"], "Nuevo") == "Pendiente"
    assert derive_order_status_from_jobs(["Impresión", "Recibido"], "Recibido") == "En producción"
    assert derive_order_status_from_jobs(["Recibido"], "Terminado") == "Terminado"


def test_terminal_order_cannot_reopen_without_administrative_force():
    valid, message = validate_transition("Terminado", "Recibido")
    assert not valid
    assert "cerrado" in message
    assert validate_transition("Terminado", "Recibido", force=True)[0]


def test_transition_closes_related_records_and_keeps_audit():
    connection = _connection()
    result = OrderStateService(connection).transition(
        1, "Terminado", actor="Vendedor", source="sales.delivery",
        reason="Cliente confirmó recepción", sync_related=True,
    )
    order = connection.execute("SELECT * FROM orders WHERE id=1").fetchone()
    assert result["changed"]
    assert order["status"] == "Terminado"
    assert order["print_priority"] == 0
    assert order["delivery_date"]
    assert connection.execute("SELECT status FROM order_jobs WHERE id=10").fetchone()[0] == "Entregado"
    assert connection.execute("SELECT status FROM order_designs WHERE id=20").fetchone()[0] == "Entregado"
    assert connection.execute("SELECT production_status FROM plancha_projects WHERE id=30").fetchone()[0] == "entregado"
    history = connection.execute("SELECT * FROM order_state_history").fetchone()
    assert history["previous_status"] == "En producción"
    assert history["new_status"] == "Terminado"
    assert history["actor"] == "Vendedor"
    assert connection.execute("SELECT COUNT(*) FROM order_events").fetchone()[0] == 1

    with pytest.raises(ValueError, match="cerrado"):
        OrderStateService(connection).transition(1, "Recibido")
