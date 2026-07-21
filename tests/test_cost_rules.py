from app.database.database import ImageDatabase
from costos.models.cost_component import CostComponent
from costos.models.cost_rule import CostRule
from costos.services.cost_calculator import CostCalculator


def test_cost_rule_modes_are_normalized_when_saved(tmp_path):
    db_path = tmp_path / "cost_rules_modes.db"
    db = ImageDatabase(db_path)

    rule_id = db.save_cost_rule(
        name="Regla prueba",
        cost_mp_mode="fijo",
        cost_mo_mode="fixed",
        cost_cf_mode="percent",
    )

    saved = db.cost_rule(rule_id)

    assert saved is not None
    assert saved["cost_mp_mode"] == "fixed"
    assert saved["cost_mo_mode"] == "fixed"
    assert saved["cost_cf_mode"] == "percent"


def test_price_rule_persists_model_reference_and_calculates_with_components(tmp_path):
    db = ImageDatabase(tmp_path / "price_rule_model.db")

    model_id = db.save_variable_cost_model(
        name="Modelo dinámico",
        product_name="Vinilo Full Color HD 10cm",
        product_key="vinilo|full_color_hd|10cm",
        category="Vinilo",
        components=[{
            "name": "Embalaje",
            "calc_mode": "per_unit",
            "quantity": 1,
            "unit_value": 8.0,
            "waste_pct": 0,
            "sort_order": 0,
            "active": 1,
        }],
    )

    price_rule_id = db.save_price_rule(
        material="Vinilo Full Color HD",
        size="10cm",
        min_quantity=1,
        price=100.0,
        variable_cost_model_id=model_id,
    )

    saved_rule = db.price_rule(price_rule_id)
    assert saved_rule is not None
    assert saved_rule["variable_cost_model_id"] == model_id

    resolved_rule, warning = db.resolve_price_rule_cost_model(saved_rule)
    assert warning is None
    assert resolved_rule is not None
    assert any(comp.code == "embalaje" for comp in resolved_rule.components)

    analysis = CostCalculator.calculate(resolved_rule, sale_price=100.0, quantity=1)
    assert analysis.cost_total == 8.0
    assert analysis.gross_profit == 92.0


def test_missing_or_inactive_model_returns_clear_warning(tmp_path):
    db = ImageDatabase(tmp_path / "missing_model.db")

    price_rule_id = db.save_price_rule(
        material="Vinilo Premium",
        size="15cm",
        min_quantity=1,
        price=80.0,
        variable_cost_model_id=999,
    )

    saved_rule = db.price_rule(price_rule_id)
    resolved_rule, warning = db.resolve_price_rule_cost_model(saved_rule)

    assert resolved_rule is None
    assert warning is not None
    assert "modelo de costos variables" in warning.lower()


def test_legacy_price_rule_with_inline_cost_columns_is_resolved(tmp_path):
    db = ImageDatabase(tmp_path / "legacy_rule.db")
    for column, definition in (
        ("cost_mp_percent", "REAL DEFAULT 0"),
        ("cost_mp_fixed", "REAL DEFAULT 0"),
        ("cost_mp_unit", "REAL DEFAULT 0"),
        ("cost_mo_percent", "REAL DEFAULT 0"),
        ("cost_mo_fixed", "REAL DEFAULT 0"),
        ("cost_mo_unit", "REAL DEFAULT 0"),
        ("cost_cf_percent", "REAL DEFAULT 0"),
        ("cost_cf_fixed", "REAL DEFAULT 0"),
        ("cost_cf_unit", "REAL DEFAULT 0"),
    ):
        columns = {row[1] for row in db.connection.execute("PRAGMA table_info(price_rules)")}
        if column not in columns:
            db.connection.execute(f"ALTER TABLE price_rules ADD COLUMN {column} {definition}")

    legacy_id = db.connection.execute(
        "INSERT INTO price_rules(material, size, min_quantity, price, extra_service, discount_percent, active, price_mode, pack_quantity, cost_mp_percent, cost_mp_fixed, cost_mp_unit, cost_mo_percent, cost_mo_fixed, cost_mo_unit, cost_cf_percent, cost_cf_fixed, cost_cf_unit) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("Resina 3D Premium", "20cm", 1, 90.0, "", 0.0, 1, "fijo", 1, 10.0, 0.0, 0.0, 5.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    ).lastrowid
    db.connection.commit()

    legacy_rule = db.price_rule(legacy_id)
    resolved_rule, warning = db.resolve_price_rule_cost_model(legacy_rule)

    assert warning is None
    assert resolved_rule is not None
    assert any(comp.code == "mp" for comp in resolved_rule.components)


def test_price_rule_presentations_use_calculated_engine_values(tmp_path):
    db = ImageDatabase(tmp_path / "presentation_adapter.db")

    model_id = db.save_variable_cost_model(
        name="Modelo para vista",
        product_name="Vinilo Premium 15cm",
        product_key="vinilo|premium|15cm",
        category="Vinilo",
        components=[
            {
                "name": "Embalaje",
                "calc_mode": "per_unit",
                "quantity": 1,
                "unit_value": 12.0,
                "waste_pct": 0,
                "sort_order": 0,
                "active": 1,
            },
        ],
    )

    rule_id = db.save_price_rule(
        material="Vinilo Premium",
        size="15cm",
        min_quantity=2,
        price=120.0,
        variable_cost_model_id=model_id,
    )

    presentation = next(p for p in db.price_rule_presentations() if p["id"] == rule_id)

    assert presentation["cost_total"] == 12.0
    assert presentation["margin"] == 108.0
    assert presentation["status"] == "Rentable"
    assert "embalaje" in presentation["detail"].lower()
