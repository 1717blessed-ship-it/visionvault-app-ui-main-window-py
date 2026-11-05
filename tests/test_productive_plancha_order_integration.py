import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.database import ImageDatabase
from app.services.productive_plancha_order_service import analysis_context, snapshot_job, supports_productive_plancha_a4


def test_a4_adapter_is_centralized_and_excludes_other_a4_products():
    assert supports_productive_plancha_a4({"title": "Plancha personalizada", "size": "A4"})
    assert not supports_productive_plancha_a4({"title": "Tarjetas", "size": "A4"})
    assert not supports_productive_plancha_a4({"product_code": "sticker_troquelado", "size": "A4"})


def test_simulation_does_not_persist_and_price_choices_snapshot(tmp_path):
    db = ImageDatabase(tmp_path / "orders.db")
    job = {"title": "Plancha A4", "material": "Plancha A4 - Vinilo estándar", "size": "A4", "quantity": 1,
           "production_estimate": {"unique_designs": 1, "design_minutes_list": [18], "print_minutes": 10, "cut_minutes": 10}}
    analysis = db.calculate_productive_plancha_a4(analysis_context(job))
    assert analysis["suggested_price"] == 6000
    assert db.connection.execute("SELECT COUNT(*) FROM order_jobs").fetchone()[0] == 0

    suggested_context = analysis_context(job, applied_price=analysis["suggested_price"])
    suggested_context["price_source"] = "suggested"
    suggested = db.calculate_productive_plancha_a4(suggested_context)
    saved = snapshot_job(job, suggested)
    order_id = db.create_order("Cliente", jobs=[saved])
    persisted = db.order_jobs(order_id)[0]
    assert persisted["applied_price_snapshot"] == 6000
    assert persisted["price_source"] == "suggested"
    assert persisted["productive_classification"] == "extended_design"
    assert persisted["production_estimate"]["unique_designs"] == 1

    db.connection.execute("UPDATE price_rules SET price = 6500 WHERE catalog_key = 'commercial_plancha_a4_diseno_unico'")
    db.connection.commit()
    assert db.order_jobs(order_id)[0]["applied_price_snapshot"] == 6000
    current = db.calculate_productive_plancha_a4(analysis_context(job, applied_price=6500))
    assert current["base_price"] == 6500
    db.connection.close()


def test_manual_price_below_cost_is_kept_with_motor_warning(tmp_path):
    db = ImageDatabase(tmp_path / "manual.db")
    job = {"title": "Plancha A4", "size": "A4", "quantity": 1,
           "production_estimate": {"unique_designs": 2, "design_minutes_list": [18, 18], "print_minutes": 10, "cut_minutes": 10}}
    context = analysis_context(job, applied_price=1000)
    context["manual_price"] = 1000
    analysis = db.calculate_productive_plancha_a4(context)
    assert analysis["price_source"] == "manual"
    assert any("no cubre" in warning for warning in analysis["warnings"])
    db.connection.close()


def test_design_minutes_are_persisted_per_unique_design_and_not_collapsed(tmp_path):
    db = ImageDatabase(tmp_path / "designs.db")
    job = {"title": "Plancha A4", "size": "A4", "quantity": 2,
           "production_estimate": {"unique_designs": 2, "design_minutes_list": [18, 18], "print_minutes": 20, "cut_minutes": 20}}
    analysis = db.calculate_productive_plancha_a4(analysis_context(job, applied_price=7000))
    order_id = db.create_order("Diseños", jobs=[snapshot_job(job, analysis)])
    loaded = db.order_jobs(order_id)[0]["production_estimate"]
    assert loaded["unique_designs"] == 2
    assert loaded["design_minutes_json"] == "[18, 18]"
    assert analysis["design_surcharge"] == 2000
    db.connection.close()


def test_no_applied_price_keeps_persisted_order_total_and_applied_total_is_used(tmp_path):
    db = ImageDatabase(tmp_path / "totals.db")
    order_id = db.create_order("Total", jobs=[{"title": "Tarjeta", "subtotal": 1200}])
    original_total = db.order(order_id)["budget_total"]
    draft_a4 = {"title": "Plancha A4", "size": "A4", "quantity": 1,
                "production_estimate": {"unique_designs": 1, "design_minutes_list": [10]}}
    simulation = db.calculate_productive_plancha_a4(analysis_context(draft_a4))
    assert simulation["applied_price"] is None
    assert db.order(order_id)["budget_total"] == original_total
    applied = db.calculate_productive_plancha_a4(analysis_context(draft_a4, applied_price=5000))
    db.replace_order_jobs(order_id, [snapshot_job(draft_a4, applied)])
    assert db.order(order_id)["budget_total"] == 5000
    db.connection.close()


def test_batch_is_accepted_without_commercial_discount(tmp_path):
    db = ImageDatabase(tmp_path / "batch.db")
    job = {"title": "Plancha A4", "size": "A4", "quantity": 5,
           "production_estimate": {"unique_designs": 1, "design_minutes_list": [10], "production_mode": "batch"}}
    result = db.calculate_productive_plancha_a4(analysis_context(job, applied_price=25000))
    assert result["production_mode"] == "batch"
    order_id = db.create_order("Tanda", jobs=[snapshot_job(job, result)])
    assert db.order(order_id)["commercial_cost"] == 500
    db.connection.close()
