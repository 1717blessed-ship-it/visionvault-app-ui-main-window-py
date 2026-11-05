from concurrent.futures import ThreadPoolExecutor

import pytest

from app.database.database import ImageDatabase
from app.services.order_production_service import OrderProductionService
from app.services.production_batch_service import ProductionBatchService


def scenario(tmp_path, *, quantity=100, assigned=80, unit="item", policy="partial"):
    db = ImageDatabase(tmp_path / "orders.db")
    db.connection.execute("INSERT INTO images(path,name,extension,size,modified,caption,visible_width,visible_height) VALUES('design.png','Design','.png',1,1,'test',100,100)")
    db.connection.commit()
    order = db.create_order_with_details("Operativo", jobs=[{
        "title": "Stickers", "quantity": quantity, "unit_kind": unit, "distribution_policy": policy,
        "subtotal": 1000, "material": "Vinilo blanco", "size": "5 cm",
    }], designs=[{
        "image_path": "design.png", "quantity": assigned, "order_job_index": 0, "size_cm": 5,
        "unit_kind": unit, "packing_mode": "standard_five_bands", "design_line_id": "line-1",
    }])
    job_id = db.order_jobs(order)[0]["id"]
    return db, order, job_id


def test_partial_stages_are_disjoint_and_recover_after_reopen(tmp_path):
    db, order, job = scenario(tmp_path)
    db.register_order_payment(order, 200)
    finances = db.order_financials(order)
    batches = ProductionBatchService(db)
    service = OrderProductionService(db)
    for _ in range(3):
        batches.save(service.preview(order, {job: 20}))
    # 60 comprometidas, 40 impresas acumuladas, 30 terminadas.
    assignments = [dict(r) for r in db.connection.execute("SELECT * FROM plancha_item_assignments ORDER BY id")]
    first_40 = assignments[:40]
    # Usar los contratos de impresión por plancha: con 20 copias cada tanda es una plancha.
    for plancha in {r["plancha_id"] for r in first_40}:
        db.confirm_plancha_printed_assignments(plancha)
    for row in first_40[:30]:
        db.confirm_plancha_finished_assignments(row["plancha_id"], [row["item_id"]])
    before = service.snapshot(order)
    j = before["jobs"][0]
    assert (j["requested"], j["distributed"], j["undistributed"]) == (100, 80, 20)
    assert (j["prepared_accumulated"], j["printed_accumulated"], j["finished"]) == (60, 40, 30)
    assert (j["prepared_current"], j["printed_current"], j["assigned_unprepared"]) == (20, 10, 20)
    assert (j["available"], j["pending_print"], j["pending_finish"]) == (20, 60, 70)
    assert j["delivered"] is None
    assert len(before["batches"]) == 3
    assert db.order_financials(order) == finances
    db.close()
    reopened = ImageDatabase(tmp_path / "orders.db")
    assert OrderProductionService(reopened).snapshot(order) == before


@pytest.mark.parametrize("unit", ["item", "sheet"])
def test_complete_distribution_and_multiple_jobs_do_not_mix_quantities(tmp_path, unit):
    db, order, job = scenario(tmp_path, quantity=2, assigned=2, unit=unit, policy="complete")
    jobs = db.order_jobs(order)
    db.replace_order_jobs(order, [*jobs, {"title": "Tarjetas", "quantity": 100, "unit_kind": "item"}])
    service = OrderProductionService(db)
    batch = ProductionBatchService(db).save(service.preview(order, {job: 1}))
    snapshot = service.snapshot(order)
    first, second = snapshot["jobs"]
    assert first["unit_kind"] == unit and first["available"] == 1
    assert second["blocked_reason"] and second["available"] == 0
    assert snapshot["batches"][0]["id"] == batch


def test_cancel_preserves_released_history_and_is_idempotent(tmp_path):
    db, order, job = scenario(tmp_path, quantity=5, assigned=5)
    service = OrderProductionService(db)
    batches = ProductionBatchService(db)
    batch = batches.save(service.preview(order, {job: 3}))
    summary = batches.cancel(batch)
    assert summary["released_units"] == 3
    assert batches.cancel(batch)["released_units"] == 0
    snapshot = service.snapshot(order)
    assert snapshot["jobs"][0]["released"] == 3
    assert snapshot["jobs"][0]["available"] == 5
    assert snapshot["batches"][0]["status"] == "cancelled"
    plancha = int(snapshot["batches"][0]["plancha_ids"])
    with pytest.raises(RuntimeError, match="tanda"):
        db.delete_plancha_project(plancha)
    with pytest.raises(ValueError, match="cancelada"):
        db.create_print_job(plancha, "Test", "Manual", {}, 1, "fake.png")
    batches.save(service.preview(order, {job: 5}))
    assert service.snapshot(order)["jobs"][0]["committed"] == 5


def test_saved_preview_is_revalidated_after_demand_change(tmp_path):
    db, order, job = scenario(tmp_path, quantity=5, assigned=5)
    preview = OrderProductionService(db).preview(order, {job: 5})
    designs = db.order_designs(order)
    designs[0]["quantity"] = 2
    db.save_order_snapshot(order, dict(db.order(order)), designs, db.order_jobs(order))
    with pytest.raises(ValueError, match="cambió|solicitada"):
        ProductionBatchService(db).save(preview)
    assert db.connection.execute("SELECT COUNT(*) FROM production_batches").fetchone()[0] == 0


def test_reservations_block_reductions_removal_and_duplicate_preparation(tmp_path):
    db, order, job = scenario(tmp_path, quantity=5, assigned=5)
    service = OrderProductionService(db)
    preview = service.preview(order, {job: 3})
    ProductionBatchService(db).save(preview)
    jobs = db.order_jobs(order)
    jobs[0]["quantity"] = 2
    with pytest.raises(ValueError, match="reservadas"):
        db.replace_order_jobs(order, jobs)
    with pytest.raises(ValueError):
        db.replace_order_jobs(order, [])
    with pytest.raises(ValueError):
        db.save_order_snapshot(order, dict(db.order(order)), [], db.order_jobs(order))
    with pytest.raises(ValueError, match="reservada"):
        ProductionBatchService(db).save(preview)
    assert service.snapshot(order)["jobs"][0]["committed"] == 3


def test_concurrent_previews_reserve_each_requested_unit_once(tmp_path):
    db, order, job = scenario(tmp_path, quantity=5, assigned=5)
    preview = OrderProductionService(db).preview(order, {job: 3})
    def save(_):
        try:
            return ProductionBatchService(db).save(preview)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, range(2)))
    assert sum(r is not None for r in results) == 1
    assert db.connection.execute("SELECT COUNT(*) FROM plancha_item_assignments WHERE state<>'released'").fetchone()[0] == 3


def test_historical_unknown_states_are_not_invented_progress(tmp_path):
    db, order, job = scenario(tmp_path, quantity=5, assigned=5)
    service = OrderProductionService(db)
    ProductionBatchService(db).save(service.preview(order, {job: 2}))
    db.connection.execute("UPDATE plancha_item_assignments SET state='historical-stage' WHERE order_job_id=?", (job,))
    db.connection.commit()
    snapshot = service.snapshot(order)["jobs"][0]
    assert snapshot["available"] == 0
    assert "histórico" in snapshot["blocked_reason"]
    assert snapshot["finished"] == 0


@pytest.mark.parametrize("field,value", [("material", ""), ("workspace_format", "letter")])
def test_missing_material_and_unknown_format_block_preparation(tmp_path, field, value):
    db, order, job = scenario(tmp_path)
    if field == "material":
        db.connection.execute("UPDATE order_jobs SET material=? WHERE id=?", (value, job))
    else:
        db.connection.execute("UPDATE order_design_demand_lines SET workspace_format=?", (value,))
    db.connection.commit()
    with pytest.raises(ValueError):
        OrderProductionService(db).preview(order, {job: 1})
