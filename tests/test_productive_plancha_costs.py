import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.database import ImageDatabase
from costos.services.cost_calculator import CostCalculator


SETTINGS = {
    "base_price": 5000,
    "standard_design_minutes": 10,
    "standard_print_minutes": 10,
    "standard_cut_minutes": 10,
    "additional_design_block_minutes": 10,
    "additional_design_block_rate": 1000,
    "standard_raw_material_cost": 635,
    "standard_overhead_cost": 465,
    "labor_hour_rate": 1800,
    "commercial_cost_first_purchase": 500,
    "commercial_cost_recurrent": 300,
}


def test_standard_plancha_uses_configurable_cost_and_price():
    result = CostCalculator.calculate_plancha_a4({"quantity": 1, "design_minutes": [10]}, SETTINGS)

    assert result.suggested_price == 5000
    assert result.productive_cost == 2000
    assert result.commercial_cost == 500
    assert result.final_cost == 2500
    assert result.classification == "standard"


def test_design_surcharge_rounds_up_per_unique_design():
    result = CostCalculator.calculate_plancha_a4({"quantity": 10, "design_minutes": [11]}, SETTINGS)

    assert result.unique_designs == 1
    assert result.design_surcharge == 1000
    assert result.suggested_price == 51000
    assert result.classification == "extended_design"


def test_complex_design_and_internal_incident_do_not_raise_suggested_price():
    base = CostCalculator.calculate_plancha_a4({"quantity": 1, "design_minutes": [21]}, SETTINGS)
    incident = CostCalculator.calculate_plancha_a4(
        {"quantity": 1, "design_minutes": [21], "internal_incident_cost": 700}, SETTINGS
    )

    assert base.classification == "complex_design"
    assert incident.classification == "internal_incident"
    assert incident.suggested_price == base.suggested_price
    assert incident.productive_cost == base.productive_cost + 700
    assert incident.warnings


def test_recurrent_customer_commercial_cost_is_once_per_order():
    result = CostCalculator.calculate_plancha_a4(
        {"quantity": 10, "design_minutes": [10], "customer_kind": "recurrent"}, SETTINGS
    )

    assert result.commercial_cost == 300
    assert result.final_cost == result.productive_cost + 300


def test_migration_is_idempotent_and_old_orders_keep_safe_defaults(tmp_path):
    db_path = tmp_path / "old.db"
    db = ImageDatabase(db_path)
    order_id = db.create_order("Cliente histórico")
    db.connection.close()

    migrated = ImageDatabase(db_path)
    job_columns = {row[1] for row in migrated.connection.execute("PRAGMA table_info(order_jobs)")}
    order_columns = {row[1] for row in migrated.connection.execute("PRAGMA table_info(orders)")}
    assert {"productive_cost", "final_cost", "productive_margin", "production_mode"} <= job_columns
    assert {"commercial_cost", "final_cost", "final_margin"} <= order_columns
    assert migrated.order(order_id)["final_cost"] == 500
    assert migrated.productive_plancha_a4_settings()["base_price"] == 5000
    assert db_path.with_suffix(db_path.suffix + ".before_productive_plancha_costs.bak").exists()

    migrated.connection.close()
    rerun = ImageDatabase(db_path)
    assert rerun.calculate_productive_plancha_a4({"quantity": 1, "design_minutes": [10]})["productive_cost"] == 2000
    rerun.connection.close()


def test_applied_price_metrics_and_warnings():
    simulation = CostCalculator.calculate_plancha_a4({"quantity": 1, "design_minutes": [10]}, SETTINGS)
    assert simulation.applied_price is None
    equal = CostCalculator.calculate_plancha_a4({"quantity": 1, "design_minutes": [10], "applied_price": 5000}, SETTINGS)
    assert equal.applied_price == 5000
    assert equal.applied_final_profit == 2500
    assert equal.applied_final_margin_percentage == 50

    below = CostCalculator.calculate_plancha_a4({"quantity": 1, "design_minutes": [10], "applied_price": 4000}, SETTINGS)
    above = CostCalculator.calculate_plancha_a4({"quantity": 1, "design_minutes": [10], "applied_price": 6000}, SETTINGS)
    zero = CostCalculator.calculate_plancha_a4({"quantity": 1, "design_minutes": [10], "applied_price": 0}, SETTINGS)
    loss = CostCalculator.calculate_plancha_a4({"quantity": 1, "design_minutes": [10], "applied_price": 1000}, SETTINGS)
    assert any("inferior" in warning for warning in below.warnings)
    assert above.applied_final_profit > equal.applied_final_profit
    assert zero.applied_final_margin_percentage == 0
    assert any("no cubre" in warning for warning in loss.warnings)


def test_batch_efficiency_is_opt_in_and_uses_shared_time():
    individual = CostCalculator.calculate_plancha_a4({"quantity": 10, "unique_designs": 1, "design_minutes": [10]}, SETTINGS)
    disabled = CostCalculator.calculate_plancha_a4({"quantity": 10, "unique_designs": 1, "design_minutes": [10], "production_mode": "batch"}, SETTINGS)
    enabled_settings = SETTINGS | {"batch_efficiency_enabled": 1, "batch_print_setup_minutes": 10,
                                   "batch_print_incremental_minutes": 1, "batch_cut_setup_minutes": 10,
                                   "batch_cut_incremental_minutes": 1}
    enabled = CostCalculator.calculate_plancha_a4({"quantity": 10, "unique_designs": 1, "design_minutes": [10], "production_mode": "batch"}, enabled_settings)
    many_designs = CostCalculator.calculate_plancha_a4({"quantity": 10, "unique_designs": 10, "design_minutes": [10] * 10}, enabled_settings)
    assert disabled.estimated_total_minutes == individual.estimated_total_minutes
    assert enabled.estimated_total_minutes < individual.estimated_total_minutes
    assert enabled.estimated_batch_savings > 0
    assert many_designs.estimated_design_minutes == 100


def test_commercial_cost_is_once_per_order_and_allocation_is_exact(tmp_path):
    db = ImageDatabase(tmp_path / "commercial.db")
    first = db.create_order("Nuevo", jobs=[{"subtotal": 1, "suggested_price_snapshot": 1} for _ in range(5)])
    jobs = db.order_jobs(first)
    assert db.order(first)["commercial_cost"] == 500
    assert sum(job["commercial_cost_allocated"] for job in jobs) == 500
    assert db.allocate_commercial_cost(1, [{"applied_price_snapshot": 1}, {"applied_price_snapshot": 1}, {"applied_price_snapshot": 1}]) == [0.33, 0.33, 0.34]
    recurrent = db.create_order("Nuevo", jobs=[{"subtotal": 10, "applied_price_snapshot": 10}])
    assert db.order(recurrent)["commercial_cost"] == 300
    db.connection.close()


def test_canonical_price_rule_and_job_snapshots_survive_rule_change(tmp_path):
    db = ImageDatabase(tmp_path / "snapshots.db")
    resolved = db.resolve_plancha_a4_base_price()
    assert resolved["source"] == "price_rules" and resolved["price"] == 5000
    order_id = db.create_order("Snapshot", jobs=[{"subtotal": 5000, "base_price_snapshot": 5000,
                               "suggested_price_snapshot": 5000, "applied_price_snapshot": 4500, "price_source": "manual"}])
    job = db.order_jobs(order_id)[0]
    db.connection.execute("UPDATE price_rules SET price = 6500 WHERE id = ?", (resolved["rule_id"],))
    db.connection.commit()
    assert db.resolve_plancha_a4_base_price()["price"] == 6500
    assert db.order_jobs(order_id)[0]["applied_price_snapshot"] == job["applied_price_snapshot"] == 4500
    assert db.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    db.connection.close()


def test_old_order_and_migration_rerun_are_safe(tmp_path):
    db_path = tmp_path / "old_fields.db"
    db = ImageDatabase(db_path)
    old_id = db.create_order("Histórico", jobs=[{"subtotal": 5000}])
    assert db.order_jobs(old_id)[0]["applied_price_snapshot"] is None
    db.connection.close()
    rerun = ImageDatabase(db_path)
    assert rerun.order_jobs(old_id)[0]["price_source"] in {"suggested", "legacy"}
    assert rerun.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    rerun.connection.close()
