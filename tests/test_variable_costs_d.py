"""Pruebas de Etapa D: Vinculación entre price_rules y variable_cost_models."""

import sys
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.database import ImageDatabase
from costos.services.cost_calculator import CostCalculator


# ---------------------------------------------------------------------------
# Vinculación básica
# ---------------------------------------------------------------------------

def test_link_price_rule_to_variable_cost_model(tmp_path):
    """Vincula una price_rule a un modelo de costo variable."""
    db = ImageDatabase(tmp_path / "link_basic.db")
    
    model_id = db.save_variable_cost_model(
        name="Modelo Vinilo 10cm",
        product_name="Vinilo Full Color HD 10cm",
        product_key="vinilo|full_color_hd|10cm",
        category="Vinilo",
        components=[{
            "name": "Vinilo",
            "calc_mode": "per_unit",
            "quantity": 1,
            "unit_value": 5.0,
            "waste_pct": 10,
            "sort_order": 0,
            "active": 1,
        }],
    )
    
    rule_id = db.save_price_rule(
        material="Vinilo Full Color HD",
        size="10cm",
        min_quantity=1,
        price=15.0,
        variable_cost_model_id=model_id,
    )
    
    rule = db.price_rule(rule_id)
    assert rule is not None
    assert rule["variable_cost_model_id"] == model_id


def test_unlink_price_rule_from_model(tmp_path):
    """Desvincula una price_rule de su modelo."""
    db = ImageDatabase(tmp_path / "unlink.db")
    
    model_id = db.save_variable_cost_model(
        name="Modelo",
        product_key="test|key",
        components=[{
            "name": "Comp",
            "calc_mode": "per_unit",
            "quantity": 1,
            "unit_value": 10,
            "waste_pct": 0,
            "sort_order": 0,
            "active": 1,
        }],
    )
    
    rule_id = db.save_price_rule(
        material="Test",
        size="10cm",
        min_quantity=1,
        price=20.0,
        variable_cost_model_id=model_id,
    )
    
    # Desvincular
    db.update_price_rule(
        rule_id,
        material="Test",
        size="10cm",
        min_quantity=1,
        price=20.0,
        variable_cost_model_id=None,
    )
    
    rule = db.price_rule(rule_id)
    assert rule["variable_cost_model_id"] is None


def test_load_linked_rule(tmp_path):
    """Carga una regla vinculada y resuelve su modelo."""
    db = ImageDatabase(tmp_path / "load_linked.db")
    
    model_id = db.save_variable_cost_model(
        name="Modelo Carga",
        product_key="test|load",
        components=[{
            "name": "Componente",
            "calc_mode": "per_unit",
            "quantity": 2,
            "unit_value": 7.5,
            "waste_pct": 5,
            "sort_order": 0,
            "active": 1,
        }],
    )
    
    rule_id = db.save_price_rule(
        material="Test",
        size="10cm",
        min_quantity=1,
        price=25.0,
        variable_cost_model_id=model_id,
    )
    
    rule = db.price_rule(rule_id)
    resolved, warning = db.resolve_price_rule_cost_model(rule)
    
    assert warning is None
    assert resolved is not None
    assert len(resolved.components) == 1


# ---------------------------------------------------------------------------
# Cálculo con VariableCostCalculator
# ---------------------------------------------------------------------------

def test_calculate_cost_using_variable_cost_model(tmp_path):
    """Calcula el costo usando el modelo de costo variable."""
    db = ImageDatabase(tmp_path / "calc_var.db")
    
    model_id = db.save_variable_cost_model(
        name="Modelo Cálculo",
        product_key="calc|test",
        components=[{
            "name": "Material",
            "calc_mode": "per_unit",
            "quantity": 1,
            "unit_value": 8.0,
            "waste_pct": 10,
            "sort_order": 0,
            "active": 1,
        }],
    )
    
    rule_id = db.save_price_rule(
        material="Test",
        size="10cm",
        min_quantity=1,
        price=20.0,
        variable_cost_model_id=model_id,
    )
    
    rule = db.price_rule(rule_id)
    resolved, _ = db.resolve_price_rule_cost_model(rule)
    
    analysis = CostCalculator.calculate(resolved, sale_price=20.0, quantity=1)
    
    # 8.0 * 1.10 = 8.8
    assert abs(analysis.cost_total - 8.8) < 0.01
    assert abs(analysis.gross_profit - 11.2) < 0.01


def test_calculate_profit_margin_markup(tmp_path):
    """Calcula ganancia, margen y markup."""
    db = ImageDatabase(tmp_path / "profit_calc.db")
    
    model_id = db.save_variable_cost_model(
        name="Modelo Rentabilidad",
        product_key="profit|test",
        components=[{
            "name": "Costo",
            "calc_mode": "per_unit",
            "quantity": 1,
            "unit_value": 10.0,
            "waste_pct": 0,
            "sort_order": 0,
            "active": 1,
        }],
    )
    
    rule_id = db.save_price_rule(
        material="Test",
        size="10cm",
        min_quantity=1,
        price=15.0,
        variable_cost_model_id=model_id,
    )
    
    rule = db.price_rule(rule_id)
    resolved, _ = db.resolve_price_rule_cost_model(rule)
    
    analysis = CostCalculator.calculate(resolved, sale_price=15.0, quantity=1)
    
    assert analysis.cost_total == 10.0
    assert analysis.gross_profit == 5.0
    assert analysis.margin_percentage == 33.33  # 5/15 * 100
    assert analysis.markup_percentage == 50.0   # 5/10 * 100


# ---------------------------------------------------------------------------
# Resolución por prioridades
# ---------------------------------------------------------------------------

def test_resolve_by_product_key_fallback(tmp_path):
    """Resuelve por product_key cuando no hay modelo vinculado."""
    db = ImageDatabase(tmp_path / "priority_key.db")
    
    # Crear modelo activo por product_key
    db.save_variable_cost_model(
        name="Modelo por Key",
        product_key="fallback|test",
        components=[{
            "name": "Componente",
            "calc_mode": "per_unit",
            "quantity": 1,
            "unit_value": 12.0,
            "waste_pct": 0,
            "sort_order": 0,
            "active": 1,
        }],
    )
    
    # Crear regla sin modelo vinculado
    rule_id = db.save_price_rule(
        material="Test",
        size="10cm",
        min_quantity=1,
        price=20.0,
    )
    
    rule = db.price_rule(rule_id)
    resolved, warning = db.resolve_cost_model_with_priority(
        price_rule=rule,
        product_key="fallback|test",
    )
    
    assert warning is None
    assert resolved is not None


def test_variant_model_has_priority_over_rule_model(tmp_path):
    """El modelo de variante tiene prioridad sobre el de la regla."""
    db = ImageDatabase(tmp_path / "priority_variant.db")
    
    rule_model_id = db.save_variable_cost_model(
        name="Modelo Regla",
        product_key="variant|test",
        components=[{
            "name": "Regla Comp",
            "calc_mode": "per_unit",
            "quantity": 1,
            "unit_value": 5.0,
            "waste_pct": 0,
            "sort_order": 0,
            "active": 1,
        }],
    )
    
    # Desactivar el primero para poder crear el segundo con mismo product_key
    db.deactivate_variable_cost_model(rule_model_id)
    
    variant_model_id = db.save_variable_cost_model(
        name="Modelo Variante",
        product_key="variant|test",
        components=[{
            "name": "Variante Comp",
            "calc_mode": "per_unit",
            "quantity": 1,
            "unit_value": 15.0,
            "waste_pct": 0,
            "sort_order": 0,
            "active": 1,
        }],
    )
    
    rule_id = db.save_price_rule(
        material="Test",
        size="10cm",
        min_quantity=1,
        price=30.0,
        variable_cost_model_id=rule_model_id,
    )
    
    rule = db.price_rule(rule_id)
    resolved, warning = db.resolve_cost_model_with_priority(
        variant_model_id=variant_model_id,
        price_rule=rule,
    )
    
    assert warning is None
    assert resolved is not None
    # Debe usar el modelo de variante (15.0, no 5.0)
    assert any(comp.value == 15.0 for comp in resolved.components)


def test_legacy_fallback_when_no_models(tmp_path):
    """Usa costos legacy cuando no hay modelos disponibles."""
    db = ImageDatabase(tmp_path / "priority_legacy.db")
    
    # Agregar columnas legacy
    for column, definition in (
        ("cost_mp_percent", "REAL DEFAULT 0"),
        ("cost_mp_fixed", "REAL DEFAULT 0"),
        ("cost_mp_unit", "REAL DEFAULT 0"),
    ):
        columns = {row[1] for row in db.connection.execute("PRAGMA table_info(price_rules)")}
        if column not in columns:
            db.connection.execute(f"ALTER TABLE price_rules ADD COLUMN {column} {definition}")
    
    rule_id = db.connection.execute(
        "INSERT INTO price_rules(material, size, min_quantity, price, extra_service, discount_percent, active, price_mode, pack_quantity, cost_mp_percent) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("Test", "10cm", 1, 20.0, "", 0.0, 1, "fijo", 1, 25.0),
    ).lastrowid
    db.connection.commit()
    
    rule = db.price_rule(rule_id)
    resolved, warning = db.resolve_cost_model_with_priority(price_rule=rule)
    
    assert warning is None
    assert resolved is not None
    assert any(comp.code == "mp" for comp in resolved.components)


# ---------------------------------------------------------------------------
# Sincronización
# ---------------------------------------------------------------------------

def test_mark_rules_outdated_on_model_update(tmp_path):
    """Marca reglas como desactualizadas al actualizar el modelo."""
    db = ImageDatabase(tmp_path / "sync_outdated.db")
    
    model_id = db.save_variable_cost_model(
        name="Modelo Original",
        product_key="sync|test",
        components=[{
            "name": "Original",
            "calc_mode": "per_unit",
            "quantity": 1,
            "unit_value": 10.0,
            "waste_pct": 0,
            "sort_order": 0,
            "active": 1,
        }],
    )
    
    rule_id = db.save_price_rule(
        material="Test",
        size="10cm",
        min_quantity=1,
        price=20.0,
        variable_cost_model_id=model_id,
    )
    
    # Actualizar modelo
    db.update_variable_cost_model(
        model_id,
        name="Modelo Actualizado",
        product_key="sync|test",
        components=[{
            "name": "Actualizado",
            "calc_mode": "per_unit",
            "quantity": 1,
            "unit_value": 15.0,
            "waste_pct": 0,
            "sort_order": 0,
            "active": 1,
        }],
    )
    
    rule = db.price_rule(rule_id)
    assert rule["outdated"] == 1
    assert rule["source_updated_at"] != ""


def test_sync_rule_with_model(tmp_path):
    """Sincroniza explícitamente una regla con su modelo."""
    db = ImageDatabase(tmp_path / "sync_explicit.db")
    
    model_id = db.save_variable_cost_model(
        name="Modelo Sync",
        product_key="sync|explicit",
        components=[{
            "name": "Componente",
            "calc_mode": "per_unit",
            "quantity": 1,
            "unit_value": 10.0,
            "waste_pct": 0,
            "sort_order": 0,
            "active": 1,
        }],
    )
    
    rule_id = db.save_price_rule(
        material="Test",
        size="10cm",
        min_quantity=1,
        price=20.0,
        variable_cost_model_id=model_id,
    )
    
    # Marcar como desactualizada
    db.connection.execute(
        "UPDATE price_rules SET outdated = 1 WHERE id = ?",
        (rule_id,),
    )
    db.connection.commit()
    
    # Sincronizar
    success, warning = db.sync_price_rule_with_model(rule_id)
    
    assert success is True
    assert warning is None
    
    rule = db.price_rule(rule_id)
    assert rule["outdated"] == 0
    assert rule["last_synced_at"] != ""


def test_preserve_manually_overridden_flag(tmp_path):
    """No marca reglas con manually_overridden como desactualizadas."""
    db = ImageDatabase(tmp_path / "sync_override.db")
    
    model_id = db.save_variable_cost_model(
        name="Modelo Override",
        product_key="override|test",
        components=[{
            "name": "Componente",
            "calc_mode": "per_unit",
            "quantity": 1,
            "unit_value": 10.0,
            "waste_pct": 0,
            "sort_order": 0,
            "active": 1,
        }],
    )
    
    rule_id = db.save_price_rule(
        material="Test",
        size="10cm",
        min_quantity=1,
        price=20.0,
        variable_cost_model_id=model_id,
    )
    
    # Marcar como manualmente sobreescrita
    db.connection.execute(
        "UPDATE price_rules SET manually_overridden = 1 WHERE id = ?",
        (rule_id,),
    )
    db.connection.commit()
    
    # Actualizar modelo
    db.update_variable_cost_model(
        model_id,
        name="Modelo Actualizado",
        product_key="override|test",
        components=[{
            "name": "Actualizado",
            "calc_mode": "per_unit",
            "quantity": 1,
            "unit_value": 15.0,
            "waste_pct": 0,
            "sort_order": 0,
            "active": 1,
        }],
    )
    
    rule = db.price_rule(rule_id)
    # No debe estar marcada como desactualizada
    assert rule["outdated"] == 0
    assert rule["manually_overridden"] == 1


# ---------------------------------------------------------------------------
# Modelos no disponibles
# ---------------------------------------------------------------------------

def test_inactive_model_returns_warning(tmp_path):
    """Modelo inactivo retorna warning claro."""
    db = ImageDatabase(tmp_path / "inactive.db")
    
    model_id = db.save_variable_cost_model(
        name="Modelo Inactivo",
        product_key="inactive|test",
        active=False,
        components=[{
            "name": "Componente",
            "calc_mode": "per_unit",
            "quantity": 1,
            "unit_value": 10.0,
            "waste_pct": 0,
            "sort_order": 0,
            "active": 1,
        }],
    )
    
    rule_id = db.save_price_rule(
        material="Test",
        size="10cm",
        min_quantity=1,
        price=20.0,
        variable_cost_model_id=model_id,
    )
    
    rule = db.price_rule(rule_id)
    resolved, warning = db.resolve_price_rule_cost_model(rule)
    
    assert resolved is None
    assert warning is not None
    assert "desactivado" in warning.lower()


def test_deleted_model_returns_warning(tmp_path):
    """Modelo eliminado retorna warning claro."""
    db = ImageDatabase(tmp_path / "deleted.db")
    
    model_id = db.save_variable_cost_model(
        name="Modelo a Eliminar",
        product_key="deleted|test",
        components=[{
            "name": "Componente",
            "calc_mode": "per_unit",
            "quantity": 1,
            "unit_value": 10.0,
            "waste_pct": 0,
            "sort_order": 0,
            "active": 1,
        }],
    )
    
    rule_id = db.save_price_rule(
        material="Test",
        size="10cm",
        min_quantity=1,
        price=20.0,
        variable_cost_model_id=model_id,
    )
    
    # Eliminar modelo
    db.remove_variable_cost_model(model_id)
    
    rule = db.price_rule(rule_id)
    resolved, warning = db.resolve_price_rule_cost_model(rule)
    
    assert resolved is None
    assert warning is not None
    assert "inexistente" in warning.lower()


# ---------------------------------------------------------------------------
# Migración idempotente
# ---------------------------------------------------------------------------

def test_migration_runs_multiple_times(tmp_path):
    """La migración puede ejecutarse múltiples veces sin errores."""
    # Primera instancia
    db1 = ImageDatabase(tmp_path / "migrate1.db")
    cols1 = {row[1] for row in db1.connection.execute("PRAGMA table_info(price_rules)")}
    assert "variable_cost_model_id" in cols1
    assert "outdated" in cols1
    
    # Segunda instancia (mismo archivo)
    db2 = ImageDatabase(tmp_path / "migrate1.db")
    cols2 = {row[1] for row in db2.connection.execute("PRAGMA table_info(price_rules)")}
    assert "variable_cost_model_id" in cols2
    assert "outdated" in cols2
    
    # Tercera instancia
    db3 = ImageDatabase(tmp_path / "migrate1.db")
    cols3 = {row[1] for row in db3.connection.execute("PRAGMA table_info(price_rules)")}
    assert "variable_cost_model_id" in cols3
    assert "outdated" in cols3
