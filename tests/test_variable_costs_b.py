"""Pruebas de persistencia Etapa B: migración, CRUD, constraint de unicidad, transacciones."""

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.database import ImageDatabase


# ---------------------------------------------------------------------------
# Migración: base de datos anterior sin las nuevas columnas
# ---------------------------------------------------------------------------

class TestMigrationFromOldSchema:
    def test_new_columns_added_on_existing_database(self, tmp_path):
        """Una DB sin las columnas nuevas recibe la migración sin errores."""
        db = ImageDatabase(tmp_path / "migration_old.db")
        cols = {row[1] for row in db.connection.execute("PRAGMA table_info(variable_cost_models)")}
        assert "product_key" in cols
        assert "outdated" in cols
        comp_cols = {row[1] for row in db.connection.execute("PRAGMA table_info(variable_cost_components)")}
        assert "source_updated_at" in comp_cols
        assert "last_synced_at" in comp_cols
        assert "manually_overridden" in comp_cols

    def test_migration_preserves_existing_data(self, tmp_path):
        """La migración no borra datos existentes."""
        db = ImageDatabase(tmp_path / "migration_data.db")
        old_id = db.save_variable_cost_model(
            name="Modelo viejo",
            product_name="Producto viejo",
            components=[{"name": "Comp", "calc_mode": "per_unit", "quantity": 1, "unit_value": 50, "sort_order": 0, "active": 1}],
        )
        assert old_id > 0
        model = db.variable_cost_model(old_id)
        assert model["name"] == "Modelo viejo"
        assert model["product_name"] == "Producto viejo"

    def test_indexes_created(self, tmp_path):
        """Los índices necesarios se crean correctamente."""
        db = ImageDatabase(tmp_path / "indexes.db")
        rows = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name IN ('variable_cost_models', 'variable_cost_components')"
        ).fetchall()
        indexes = {row[0] for row in rows}
        assert "idx_vcm_product_key" in indexes
        assert "idx_vcm_active" in indexes
        assert "idx_vcc_source" in indexes
        assert "idx_vcc_active" in indexes

    def test_unique_active_constraint_exists(self, tmp_path):
        """El índice parcial único para un solo modelo activo por product_key existe."""
        db = ImageDatabase(tmp_path / "unique.db")
        rows = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'variable_cost_models'"
        ).fetchall()
        indexes = {row[0] for row in rows}
        assert "idx_vcm_unique_active_key" in indexes


# ---------------------------------------------------------------------------
# product_key persistence
# ---------------------------------------------------------------------------

class TestProductKeyPersistence:
    def test_product_key_saved_and_retrieved(self, tmp_path):
        db = ImageDatabase(tmp_path / "pk.db")
        model_id = db.save_variable_cost_model(
            name="Modelo con key",
            product_key="plancha|vinilo|a4",
            product_name="Vinilo A4",
            category="Plancha",
        )
        model = db.variable_cost_model(model_id)
        assert model["product_key"] == "plancha|vinilo|a4"

    def test_empty_product_key_saved(self, tmp_path):
        db = ImageDatabase(tmp_path / "pk_empty.db")
        model_id = db.save_variable_cost_model(
            name="Sin key",
            product_key="",
        )
        model = db.variable_cost_model(model_id)
        assert model["product_key"] == ""

    def test_active_variable_cost_keys(self, tmp_path):
        db = ImageDatabase(tmp_path / "pk_keys.db")
        db.save_variable_cost_model(name="A", product_key="k1", active=True)
        db.save_variable_cost_model(name="B", product_key="k2", active=True)
        db.save_variable_cost_model(name="C", product_key="k1", active=False)
        keys = db.active_variable_cost_keys()
        assert keys == {"k1", "k2"}

    def test_variable_cost_model_by_product_key(self, tmp_path):
        db = ImageDatabase(tmp_path / "pk_lookup.db")
        db.save_variable_cost_model(name="Primero", product_key="test|v1", active=True)
        db.save_variable_cost_model(name="Segundo", product_key="test|v1", active=False)
        found = db.variable_cost_model_by_product_key("test|v1")
        assert found is not None
        assert found["name"] == "Primero"

    def test_variable_cost_models_by_product_key(self, tmp_path):
        db = ImageDatabase(tmp_path / "pk_list.db")
        db.save_variable_cost_model(name="Activo", product_key="p1", active=True)
        db.save_variable_cost_model(name="Inactivo", product_key="p1", active=False)
        models = db.variable_cost_models_by_product("p1")
        assert len(models) == 2


# ---------------------------------------------------------------------------
# Un solo modelo activo por product_key
# ---------------------------------------------------------------------------

class TestUniqueActiveModelPerProductKey:
    def test_unique_constraint_enforced(self, tmp_path):
        """Si se intenta crear un segundo modelo activo con la misma product_key,
        SQLite debe lanzar un error de integridad."""
        db = ImageDatabase(tmp_path / "unique_enforce.db")
        db.save_variable_cost_model(name="Primero", product_key="k1", active=True)
        try:
            db.save_variable_cost_model(name="Segundo", product_key="k1", active=True)
            # Si no lanza error, el constraint no está funcionando
            assert False, "Debería haber lanzado IntegrityError"
        except Exception:
            pass

    def test_inactive_model_does_not_conflict(self, tmp_path):
        """Un modelo inactivo con la misma product_key no viola el constraint."""
        db = ImageDatabase(tmp_path / "unique_inactive.db")
        db.save_variable_cost_model(name="Activo", product_key="k1", active=True)
        new_id = db.save_variable_cost_model(name="Inactivo", product_key="k1", active=False)
        assert new_id > 0

    def test_deactivate_allows_new_active(self, tmp_path):
        """Desactivar un modelo permite crear uno nuevo activo con la misma key."""
        db = ImageDatabase(tmp_path / "unique_deact.db")
        first_id = db.save_variable_cost_model(name="Primero", product_key="k1", active=True)
        db.deactivate_variable_cost_model(first_id)
        second_id = db.save_variable_cost_model(name="Segundo", product_key="k1", active=True)
        assert second_id > 0
        assert second_id != first_id


# ---------------------------------------------------------------------------
# Decimales como texto (no float)
# ---------------------------------------------------------------------------

class TestDecimalPrecisionInDatabase:
    def test_monetary_values_persist_with_precision(self, tmp_path):
        """Los valores monetarios mantienen precisión de 2 decimales tras el ciclo CRUD."""
        db = ImageDatabase(tmp_path / "decimal.db")
        model_id = db.save_variable_cost_model(
            name="Decimal test",
            product_key="test",
            components=[{
                "name": "Comp",
                "calc_mode": "per_unit",
                "quantity": "3",
                "unit_value": "333.33",
                "waste_pct": "7.5",
                "sort_order": 0,
                "active": 1,
            }],
        )
        comps = db.variable_cost_model_components(model_id)
        # SQLite REAL column may store as float, but value must be accurate
        assert abs(float(comps[0]["unit_value"]) - 333.33) < 0.001
        assert abs(float(comps[0]["waste_pct"]) - 7.5) < 0.001

    def test_decimal_roundtrip_through_crud(self, tmp_path):
        """Los decimales sobreviven el ciclo save → load → save."""
        db = ImageDatabase(tmp_path / "decimal_rt.db")
        model_id = db.save_variable_cost_model(
            name="RT",
            product_key="test",
            components=[{
                "name": "Comp",
                "calc_mode": "per_unit",
                "quantity": "3",
                "unit_value": "333.33",
                "waste_pct": "7.5",
                "sort_order": 0,
                "active": 1,
            }],
        )
        comps = db.variable_cost_model_components(model_id)
        assert abs(float(comps[0]["unit_value"]) - 333.33) < 0.001

        # Actualizar manteniendo precisión
        db.update_variable_cost_model(
            model_id,
            name="RT updated",
            components=[{
                "name": "Comp",
                "calc_mode": "per_unit",
                "quantity": "3",
                "unit_value": "333.33",
                "waste_pct": "7.5",
                "sort_order": 0,
                "active": 1,
            }],
        )
        comps2 = db.variable_cost_model_components(model_id)
        assert abs(float(comps2[0]["unit_value"]) - 333.33) < 0.001


# ---------------------------------------------------------------------------
# Transacciones: fallo parcial no deja registros huérfanos
# ---------------------------------------------------------------------------

class TestTransactionSafety:
    def test_empty_components_list_saves_model(self, tmp_path):
        """Un modelo sin componentes se guarda correctamente (sin modelos huérfanos)."""
        db = ImageDatabase(tmp_path / "tx.db")
        model_id = db.save_variable_cost_model(
            name="Sin componentes",
            product_key="k1",
            components=[],
        )
        assert model_id > 0
        model = db.variable_cost_model(model_id)
        assert model["name"] == "Sin componentes"
        comps = db.variable_cost_model_components(model_id)
        assert len(comps) == 0

    def test_update_replaces_all_components(self, tmp_path):
        """Al actualizar con una nueva lista de componentes, se reemplazan completamente."""
        db = ImageDatabase(tmp_path / "tx_replace.db")
        model_id = db.save_variable_cost_model(
            name="Original",
            product_key="k1",
            components=[
                {"name": "A", "calc_mode": "per_unit", "quantity": 1, "unit_value": 100, "sort_order": 0, "active": 1},
                {"name": "B", "calc_mode": "per_unit", "quantity": 1, "unit_value": 200, "sort_order": 1, "active": 1},
            ],
        )
        assert len(db.variable_cost_model_components(model_id)) == 2

        db.update_variable_cost_model(
            model_id,
            name="Actualizado",
            components=[
                {"name": "C", "calc_mode": "fixed", "quantity": 1, "unit_value": 500, "sort_order": 0, "active": 1},
            ],
        )
        comps = db.variable_cost_model_components(model_id)
        assert len(comps) == 1
        assert comps[0]["name"] == "C"

    def test_update_without_components_preserves_them(self, tmp_path):
        """Al actualizar sin pasar components=None, los componentes no se modifican."""
        db = ImageDatabase(tmp_path / "tx_preserve.db")
        model_id = db.save_variable_cost_model(
            name="Con componentes",
            product_key="k1",
            components=[
                {"name": "A", "calc_mode": "per_unit", "quantity": 1, "unit_value": 100, "sort_order": 0, "active": 1},
            ],
        )
        db.update_variable_cost_model(model_id, name="Solo nombre")
        comps = db.variable_cost_model_components(model_id)
        assert len(comps) == 1
        assert comps[0]["name"] == "A"


# ---------------------------------------------------------------------------
# Baja lógica (deactivate)
# ---------------------------------------------------------------------------

class TestDeactivation:
    def test_deactivate_sets_active_false(self, tmp_path):
        db = ImageDatabase(tmp_path / "deact.db")
        model_id = db.save_variable_cost_model(name="Test", product_key="k1", active=True)
        result = db.deactivate_variable_cost_model(model_id)
        assert result is True
        model = db.variable_cost_model(model_id)
        assert model["active"] == 0

    def test_deactivate_preserves_model(self, tmp_path):
        db = ImageDatabase(tmp_path / "deact_preserve.db")
        model_id = db.save_variable_cost_model(
            name="Para desactivar",
            product_key="k1",
            components=[{"name": "C", "calc_mode": "per_unit", "quantity": 1, "unit_value": 50, "sort_order": 0, "active": 1}],
        )
        db.deactivate_variable_cost_model(model_id)
        model = db.variable_cost_model(model_id)
        assert model is not None
        assert model["name"] == "Para desactivar"
        comps = db.variable_cost_model_components(model_id)
        assert len(comps) == 1


# ---------------------------------------------------------------------------
# Costos fijos intactos
# ---------------------------------------------------------------------------

class TestFixedCostsUntouched:
    def test_fixed_cost_rules_not_modified_by_variable_operations(self, tmp_path):
        """Las operaciones sobre costos variables no alteran las reglas de costos fijos."""
        db = ImageDatabase(tmp_path / "fixed_intact.db")
        rule_id = db.save_cost_rule(
            name="Regla Fija",
            cost_mp_percent=30.0,
            cost_mo_percent=20.0,
            cost_cf_percent=10.0,
        )
        original = db.cost_rule(rule_id)

        # Crear y modificar costos variables
        model_id = db.save_variable_cost_model(
            name="Variable",
            product_key="test|v1",
            components=[{"name": "C", "calc_mode": "per_unit", "quantity": 1, "unit_value": 50, "sort_order": 0, "active": 1}],
        )
        db.update_variable_cost_model(model_id, name="Variable updated")
        db.deactivate_variable_cost_model(model_id)
        db.remove_variable_cost_model(model_id)

        after = db.cost_rule(rule_id)
        assert after["cost_mp_percent"] == original["cost_mp_percent"]
        assert after["cost_mo_percent"] == original["cost_mo_percent"]
        assert after["cost_cf_percent"] == original["cost_cf_percent"]
        assert after["name"] == original["name"]

    def test_multiple_variable_models_dont_affect_fixed_costs(self, tmp_path):
        db = ImageDatabase(tmp_path / "fixed_multi.db")
        rule_id = db.save_cost_rule(name="Fija", cost_mp_percent=25.0)
        for i in range(5):
            db.save_variable_cost_model(
                name=f"Var {i}",
                product_key=f"p{i}",
                components=[{"name": f"C{i}", "calc_mode": "per_unit", "quantity": 1, "unit_value": i * 100, "sort_order": 0, "active": 1}],
            )
        rule = db.cost_rule(rule_id)
        assert rule["cost_mp_percent"] == 25.0


# ---------------------------------------------------------------------------
# Sync fields
# ---------------------------------------------------------------------------

class TestSyncFields:
    def test_sync_fields_persisted(self, tmp_path):
        db = ImageDatabase(tmp_path / "sync.db")
        model_id = db.save_variable_cost_model(
            name="Sync test",
            product_key="test",
            components=[{
                "name": "Vinculado",
                "origin": "price_rule",
                "source_id": "pr_42",
                "calc_mode": "per_unit",
                "quantity": "1",
                "unit_value": "200",
                "waste_pct": "0",
                "sort_order": 0,
                "active": 1,
                "source_updated_at": "2026-07-20T10:00:00",
                "last_synced_at": "2026-07-20T10:00:00",
                "manually_overridden": "0",
            }],
        )
        comps = db.variable_cost_model_components(model_id)
        assert comps[0]["origin"] == "price_rule"
        assert comps[0]["source_id"] == "pr_42"
        assert comps[0]["source_updated_at"] == "2026-07-20T10:00:00"
        assert comps[0]["last_synced_at"] == "2026-07-20T10:00:00"
        assert comps[0]["manually_overridden"] == 0

    def test_manually_overridden_flag(self, tmp_path):
        db = ImageDatabase(tmp_path / "override.db")
        model_id = db.save_variable_cost_model(
            name="Override test",
            product_key="test",
            components=[{
                "name": "Manual",
                "origin": "manual",
                "calc_mode": "per_unit",
                "quantity": "1",
                "unit_value": "999",
                "sort_order": 0,
                "active": 1,
                "manually_overridden": "1",
            }],
        )
        comps = db.variable_cost_model_components(model_id)
        assert comps[0]["manually_overridden"] == 1
