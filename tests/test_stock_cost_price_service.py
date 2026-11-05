import sqlite3

import pytest

from app.services.stock_cost_price_service import (
    InsufficientStockError,
    PriceSuggestion,
    StockCostPriceService,
)


@pytest.fixture()
def service_connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS variable_cost_models (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS variable_cost_components (
            id INTEGER PRIMARY KEY,
            model_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            quantity REAL DEFAULT 0,
            unit_value REAL DEFAULT 0,
            unit TEXT DEFAULT ''
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS price_rules (
            id INTEGER PRIMARY KEY,
            material TEXT DEFAULT '',
            size TEXT DEFAULT '',
            min_quantity INTEGER DEFAULT 1,
            price REAL NOT NULL,
            extra_service TEXT DEFAULT '',
            discount_percent REAL DEFAULT 0,
            active INTEGER DEFAULT 1,
            price_mode TEXT DEFAULT 'fijo',
            pack_quantity INTEGER DEFAULT 1,
            catalog_key TEXT DEFAULT '',
            variable_cost_model_id INTEGER DEFAULT NULL,
            outdated INTEGER DEFAULT 0,
            source_updated_at TEXT DEFAULT '',
            last_synced_at TEXT DEFAULT '',
            manually_overridden INTEGER DEFAULT 0
        )
        """
    )
    connection.commit()
    return connection


def test_create_material_and_purchase_update_cost_and_stock(service_connection):
    service = StockCostPriceService(service_connection)

    material_id = service.create_material(
        name="Vinilo blanco A4",
        unit="hoja",
        physical_stock=50,
        min_stock=10,
        unit_cost=1700,
        supplier="Proveedor principal",
    )

    assert material_id > 0

    purchase = service.register_purchase(
        material_id=material_id,
        quantity=20,
        total_cost=40000,
        reference="Factura 0001-00000234",
    )

    assert purchase == pytest.approx(1785.71, rel=1e-3)

    material = service.get_material(material_id)
    assert material["physical_stock"] == 70
    assert material["available_stock"] == 70
    assert material["unit_cost"] == pytest.approx(1785.71, rel=1e-3)


def test_link_component_to_material_updates_component_unit_value(service_connection):
    service = StockCostPriceService(service_connection)
    service_connection.execute(
        "INSERT INTO variable_cost_models (id, name) VALUES (1, 'Modelo prueba')"
    )
    service_connection.execute(
        "INSERT INTO variable_cost_components (id, model_id, name, quantity, unit_value, unit) VALUES (12, 1, 'Vinilo', 1, 1000, 'hoja')"
    )
    service_connection.commit()

    material_id = service.create_material(name="Vinilo blanco A4", unit="hoja", physical_stock=10, unit_cost=1700)
    service.link_component_to_material(component_id=12, material_id=material_id, sync_unit_cost=True)

    component = service_connection.execute(
        "SELECT unit_value FROM variable_cost_components WHERE id = 12"
    ).fetchone()
    assert component[0] == pytest.approx(1700.0)


def test_configure_price_policy_and_price_suggestion(service_connection):
    service = StockCostPriceService(service_connection)
    service_connection.execute(
        "INSERT INTO price_rules (id, material, price, active) VALUES (5, 'Vinilo blanco A4', 1500, 1)"
    )
    service_connection.commit()

    material_id = service.create_material(name="Vinilo blanco A4", unit="hoja", physical_stock=10, unit_cost=2000)
    service.configure_price_policy(
        price_rule_id=5,
        mode="review",
        calculation_type="margin",
        target_percentage=45,
        rounding_step=500,
        minimum_price=1500,
    )
    suggestion = service.price_suggestion(price_rule_id=5)

    assert isinstance(suggestion, PriceSuggestion)
    assert suggestion.unit_cost == pytest.approx(2000.0)
    assert suggestion.current_price == 1500.0
    assert suggestion.suggested_price == pytest.approx(3636.36, rel=1e-3)
    assert suggestion.margin_pct == pytest.approx(45.0, rel=1e-3)

    service.apply_suggested_price(price_rule_id=5)
    rule = service_connection.execute("SELECT price FROM price_rules WHERE id = 5").fetchone()
    assert rule[0] == pytest.approx(3636.36, rel=1e-3)


def test_reserve_and_consume_order_reservations(service_connection):
    service = StockCostPriceService(service_connection)
    service_connection.execute(
        "INSERT INTO variable_cost_models (id, name) VALUES (1, 'Modelo prueba')"
    )
    service_connection.execute(
        "INSERT INTO variable_cost_components (id, model_id, name, quantity, unit_value, unit) VALUES (1, 1, 'Vinilo', 2, 1000, 'hoja')"
    )
    service_connection.commit()

    material_id = service.create_material(name="Vinilo", unit="hoja", physical_stock=20, unit_cost=1000)
    service.link_component_to_material(component_id=1, material_id=material_id, sync_unit_cost=False)

    service.reserve_for_order(order_job_id=77, cost_model_id=1, production_quantity=3)
    material = service.get_material(material_id)
    assert material["reserved_stock"] == 6
    assert material["available_stock"] == 14

    service.consume_order_reservations(order_job_id=77)
    material = service.get_material(material_id)
    assert material["physical_stock"] == 14
    assert material["reserved_stock"] == 0
    assert material["available_stock"] == 14


def test_save_order_snapshot_records_snapshot(service_connection):
    service = StockCostPriceService(service_connection)
    service_connection.execute(
        "INSERT INTO price_rules (id, material, price, active) VALUES (10, 'Material X', 5000, 1)"
    )
    service_connection.commit()

    material_id = service.create_material(name="Material X", unit="unidad", physical_stock=9, unit_cost=3000)
    service.save_order_snapshot(order_job_id=99, price_rule_id=10, production_quantity=3, sale_total=15000)

    row = service_connection.execute("SELECT * FROM stock_order_snapshots WHERE order_job_id = 99").fetchone()
    assert row is not None
    assert row["sale_total"] == 15000.0
    assert row["gross_profit"] == pytest.approx(6000.0)
    assert row["margin_pct"] == pytest.approx(40.0)


def test_sync_order_job_stock_reserves_and_consumes(service_connection):
    service = StockCostPriceService(service_connection)
    service_connection.execute(
        "INSERT INTO variable_cost_models (id, name) VALUES (1, 'Modelo prueba')"
    )
    service_connection.execute(
        "INSERT INTO variable_cost_components (id, model_id, name, quantity, unit_value, unit) VALUES (1, 1, 'Vinilo', 2, 1200, 'hoja')"
    )
    service_connection.commit()

    material_id = service.create_material(name="Vinilo azul", unit="hoja", physical_stock=10, unit_cost=1200)
    service.link_component_to_material(component_id=1, material_id=material_id, sync_unit_cost=False)

    service.sync_order_job_stock(order_job_id=77, state="reserved", cost_model_id=1, production_quantity=2)
    material = service.get_material(material_id)
    assert material["reserved_stock"] == 4
    assert material["available_stock"] == 6

    service.sync_order_job_stock(order_job_id=77, state="completed", cost_model_id=1, production_quantity=2)
    material = service.get_material(material_id)
    assert material["physical_stock"] == 6
    assert material["reserved_stock"] == 0
    assert material["available_stock"] == 6


def test_consume_order_reservations_is_idempotent(service_connection):
    service = StockCostPriceService(service_connection)
    service_connection.execute(
        "INSERT INTO variable_cost_models (id, name) VALUES (1, 'Modelo prueba')"
    )
    service_connection.execute(
        "INSERT INTO variable_cost_components (id, model_id, name, quantity, unit_value, unit) VALUES (1, 1, 'Vinilo', 1, 1000, 'hoja')"
    )
    service_connection.commit()

    material_id = service.create_material(name="Vinilo idempotente", unit="hoja", physical_stock=10, unit_cost=1000)
    service.link_component_to_material(component_id=1, material_id=material_id, sync_unit_cost=False)

    service.reserve_for_order(order_job_id=201, cost_model_id=1, production_quantity=2)
    service.consume_order_reservations(order_job_id=201)
    service.consume_order_reservations(order_job_id=201)

    material = service.get_material(material_id)
    assert material["physical_stock"] == 8
    assert material["reserved_stock"] == 0
    assert material["available_stock"] == 8


def test_transition_handling_uses_previous_state(service_connection):
    service = StockCostPriceService(service_connection)
    service_connection.execute(
        "INSERT INTO variable_cost_models (id, name) VALUES (1, 'Modelo prueba')"
    )
    service_connection.execute(
        "INSERT INTO variable_cost_components (id, model_id, name, quantity, unit_value, unit) VALUES (1, 1, 'Vinilo', 1, 1000, 'hoja')"
    )
    service_connection.commit()

    material_id = service.create_material(name="Vinilo transiciones", unit="hoja", physical_stock=10, unit_cost=1000)
    service.link_component_to_material(component_id=1, material_id=material_id, sync_unit_cost=False)

    service.sync_order_job_stock(
        order_job_id=202,
        state="reservado",
        previous_state="diseño",
        cost_model_id=1,
        production_quantity=2,
    )
    service.sync_order_job_stock(
        order_job_id=202,
        state="en producción",
        previous_state="confirmado",
        cost_model_id=1,
        production_quantity=2,
    )
    material = service.get_material(material_id)
    assert material["reserved_stock"] == 2
    assert material["available_stock"] == 8

    service.sync_order_job_stock(
        order_job_id=202,
        state="completed",
        previous_state="en producción",
        cost_model_id=1,
        production_quantity=2,
    )
    service.sync_order_job_stock(
        order_job_id=202,
        state="cancelado",
        previous_state="en producción",
        cost_model_id=1,
        production_quantity=2,
    )
    material = service.get_material(material_id)
    assert material["physical_stock"] == 8
    assert material["reserved_stock"] == 0
    assert material["available_stock"] == 8


def test_adjust_stock_updates_physical_stock(service_connection):
    service = StockCostPriceService(service_connection)
    material_id = service.create_material(name="Cartulina", unit="hoja", physical_stock=5, unit_cost=250)

    service.adjust_stock(material_id=material_id, delta=-2, reference="Consumo")
    material = service.get_material(material_id)
    assert material["physical_stock"] == 3
    assert material["available_stock"] == 3


def test_repeated_reserve_does_not_double_count(service_connection):
    service = StockCostPriceService(service_connection)
    service_connection.execute(
        "INSERT INTO variable_cost_models (id, name) VALUES (1, 'Modelo prueba')"
    )
    service_connection.execute(
        "INSERT INTO variable_cost_components (id, model_id, name, quantity, unit_value, unit) VALUES (1, 1, 'Vinilo', 1, 1000, 'hoja')"
    )
    service_connection.commit()

    material_id = service.create_material(name="Vinilo repetido", unit="hoja", physical_stock=10, unit_cost=1000)
    service.link_component_to_material(component_id=1, material_id=material_id, sync_unit_cost=False)

    service.reserve_for_order(order_job_id=101, cost_model_id=1, production_quantity=2)
    service.reserve_for_order(order_job_id=101, cost_model_id=1, production_quantity=2)

    material = service.get_material(material_id)
    assert material["reserved_stock"] == 2
    assert material["available_stock"] == 8
