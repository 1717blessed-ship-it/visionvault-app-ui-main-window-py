import json
import sqlite3
from types import SimpleNamespace

from app.api.mobile_jobs import MobileJobsHandler
from app.services.mobile_runtime_config_service import MobileRuntimeConfigService


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE app_settings (
               setting_key TEXT PRIMARY KEY,
               setting_value TEXT NOT NULL,
               updated_at TEXT NOT NULL
           )"""
    )
    return connection


def _setting(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        """INSERT INTO app_settings(setting_key, setting_value, updated_at)
           VALUES(?, ?, '2026-07-29T12:00:00')""",
        (f"mobile_runtime.{key}", value),
    )
    connection.commit()


def test_runtime_config_has_safe_complete_defaults():
    config = MobileRuntimeConfigService(_connection()).snapshot()

    assert config["config_version"] == 1
    assert config["features"]["design_catalog"] is True
    assert config["maintenance"]["enabled"] is False
    assert config["catalog"]["page_size"] == 100
    assert config["catalog"]["max_page_size"] == 500
    assert config["references"]["workflows"]["general"]["stages"]
    assert config["references"]["materials"]
    assert config["references"]["payment_methods"]


def test_runtime_config_normalizes_remote_values():
    connection = _connection()
    _setting(connection, "feature.product_catalog", "false")
    _setting(connection, "maintenance.enabled", "true")
    _setting(connection, "catalog_page_size", "9999")
    _setting(
        connection,
        "materials",
        json.dumps(["Vinilo", " vinilo ", "Lona"], ensure_ascii=False),
    )
    _setting(
        connection,
        "sticker_modes",
        json.dumps(["Plancha A4", "Formato inventado"], ensure_ascii=False),
    )

    config = MobileRuntimeConfigService(connection).snapshot()

    assert config["features"]["product_catalog"] is False
    assert config["maintenance"]["enabled"] is True
    assert config["catalog"]["page_size"] == 500
    assert config["references"]["materials"] == ["Vinilo", "Lona"]
    assert config["references"]["sticker_modes"] == ["Plancha A4"]


def test_notification_templates_are_optional_and_safe():
    connection = _connection()
    _setting(connection, "notification.title_prefix", "[Taller]")
    _setting(
        connection,
        "notification.order.created.title",
        "Pedido nuevo · {title}",
    )
    _setting(
        connection,
        "notification.order.created.message",
        "{message} ({event_type})",
    )
    service = MobileRuntimeConfigService(connection)

    title, message = service.notification_text(
        "order.created", "Venta #32", "Ana"
    )
    assert title == "[Taller] Pedido nuevo · Venta #32"
    assert message == "Ana (order.created)"

    _setting(connection, "notification.order.updated.title", "{unknown}")
    title, _ = service.notification_text("order.updated", "Original", "Mensaje")
    assert title == "[Taller] Original"


def test_capabilities_keeps_legacy_contract_and_adds_runtime_config():
    connection = _connection()
    handler = object.__new__(MobileJobsHandler)
    handler.event_repo = SimpleNamespace(conn=connection)
    captured = {}
    handler._send_json_response = lambda status, payload: captured.update(
        status=status, payload=payload
    )

    handler._get_capabilities()

    payload = captured["payload"]
    assert captured["status"] == 200
    assert payload["supports_pull"] is True
    assert payload["supports_push"] is False
    assert payload["runtime_config"]["config_version"] == 1
    assert payload["runtime_config"]["features"]["quick_edits"] is True


def test_maintenance_and_feature_guards_return_503():
    connection = _connection()
    _setting(connection, "maintenance.enabled", "true")
    handler = object.__new__(MobileJobsHandler)
    handler.event_repo = SimpleNamespace(conn=connection)
    captured = {}
    handler._send_error = lambda status, message: captured.update(
        status=status, message=message
    )

    assert handler._require_mobile_mutations() is False
    assert captured["status"] == 503

    connection.execute("DELETE FROM app_settings")
    connection.commit()
    _setting(connection, "feature.design_catalog", "false")
    captured.clear()
    assert handler._require_mobile_feature("design_catalog") is False
    assert captured["status"] == 503
