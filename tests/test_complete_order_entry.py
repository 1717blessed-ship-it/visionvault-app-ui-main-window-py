import pytest

from app.database.database import ImageDatabase
from app.services.production_batch_service import ProductionBatchService
from app.services.production_feedback_service import ProductionFeedbackService


def _image(db, path):
    db.connection.execute(
        """INSERT INTO images(path,name,extension,size,modified,caption,visible_width,visible_height)
           VALUES(?,?,?,?,?,?,?,?)""",
        (path, path, ".png", 1, 1, "ficticio", 100, 100),
    )
    db.connection.commit()


def _values(db, order_id):
    order = dict(db.order(order_id))
    order["client"] = order.get("client_name") or order["client"]
    return order


def test_complete_entry_reopens_multiple_jobs_and_independent_same_file_lines(tmp_path):
    db = ImageDatabase(tmp_path / "orders.db")
    _image(db, "shared.png")
    _image(db, "second.png")
    jobs = [
        {"title": "Stickers", "material": "Vinilo blanco", "size": "5 cm", "quantity": 10,
         "unit_kind": "item", "subtotal": 100},
        {"title": "Planchas", "material": "Vinilo especial", "size": "A4", "quantity": 2,
         "unit_kind": "sheet", "subtotal": 200},
    ]
    designs = [
        {"design_line_id": "line-a1", "image_path": "shared.png", "quantity": 4, "size_cm": 5,
         "order_job_index": 0, "unit_kind": "item", "packing_mode": "standard_five_bands"},
        {"design_line_id": "line-a2", "image_path": "second.png", "quantity": 6, "size_cm": 5,
         "order_job_index": 0, "unit_kind": "item", "packing_mode": "standard_five_bands"},
        {"design_line_id": "line-b1", "image_path": "shared.png", "quantity": 2, "size_cm": 20,
         "order_job_index": 1, "unit_kind": "sheet", "packing_mode": "special_geometric"},
    ]
    order_id = db.create_order_with_details(
        "Cliente", jobs=jobs, designs=designs, delivery_date="2026-10-20",
        observations="Todo cargado", status="Recibido",
    )

    db.close()
    db = ImageDatabase(tmp_path / "orders.db")

    reopened_jobs = db.order_jobs(order_id)
    reopened_designs = db.order_designs(order_id)
    assert [job["unit_kind"] for job in reopened_jobs] == ["item", "sheet"]
    assert {line["design_line_id"] for line in reopened_designs} == {"line-a1", "line-a2", "line-b1"}
    shared = [line for line in reopened_designs if line["image_path"] == "shared.png"]
    assert len(shared) == 2 and len({line["order_job_id"] for line in shared}) == 2

    candidates = ProductionBatchService(db).job_candidates()
    assert {candidate.order_job_id: candidate.available for candidate in candidates} == {
        reopened_jobs[0]["id"]: 10, reopened_jobs[1]["id"]: 2,
    }
    assert not any(candidate.blocked_reason for candidate in candidates)
    item_preview = ProductionBatchService(db).preview_jobs({reopened_jobs[0]["id"]: 5})
    assert item_preview.groups
    assert sum(item["quantity"] for item in item_preview.groups[0].selections) == 5

    original_ids = [line["design_line_id"] for line in reopened_designs]
    db.save_order_snapshot(order_id, _values(db, order_id), reopened_designs, reopened_jobs)
    assert [line["design_line_id"] for line in db.order_designs(order_id)] == original_ids
    assert db.connection.execute(
        "SELECT COUNT(*) FROM order_design_demand_lines WHERE order_id=?", (order_id,)
    ).fetchone()[0] == 3


def test_incomplete_order_is_saved_but_blocked_and_distribution_is_validated(tmp_path):
    db = ImageDatabase(tmp_path / "orders.db")
    incomplete = db.create_order_with_details("Sin diseño", jobs=[{
        "title": "Stickers", "material": "Vinilo", "size": "5 cm", "quantity": 5, "unit_kind": "item",
    }], designs=[])
    assert db.order(incomplete)
    assert ProductionBatchService(db).job_candidates() == []
    blocked = ProductionFeedbackService(db).summary()["blocked"]["items"]
    assert blocked[0]["order_id"] == incomplete
    assert "diseño" in blocked[0]["reason"].casefold()

    _image(db, "too-many.png")
    with pytest.raises(ValueError, match="distribuyen 6 unidades"):
        db.create_order_with_details("Exceso", jobs=[{
            "title": "Stickers", "material": "Vinilo", "size": "5 cm", "quantity": 5, "unit_kind": "item",
        }], designs=[{
            "design_line_id": "too-many", "image_path": "too-many.png", "quantity": 6,
            "size_cm": 5, "order_job_index": 0, "unit_kind": "item",
        }])
    assert not db.connection.execute("SELECT 1 FROM orders WHERE client='Exceso'").fetchone()


def test_edit_preserves_reservation_history_and_prevents_reduction(tmp_path):
    db = ImageDatabase(tmp_path / "orders.db")
    _image(db, "reserved.png")
    order_id = db.create_order_with_details("Reserva", jobs=[{
        "title": "Stickers", "material": "Vinilo", "size": "5 cm", "quantity": 5, "unit_kind": "item",
    }], designs=[{
        "design_line_id": "reserved-line", "image_path": "reserved.png", "quantity": 5, "size_cm": 5,
        "order_job_index": 0, "unit_kind": "item", "packing_mode": "standard_five_bands",
    }])
    service = ProductionBatchService(db)
    service.save(service.preview({"reserved-line": 3}), "Reserva parcial")
    assignments_before = db.connection.execute(
        "SELECT COUNT(*),SUM(quantity) FROM plancha_item_assignments WHERE order_design_line_id='reserved-line'"
    ).fetchone()

    jobs = db.order_jobs(order_id)
    designs = db.order_designs(order_id)
    db.save_order_snapshot(order_id, _values(db, order_id), designs, jobs)
    assignments_after = db.connection.execute(
        "SELECT COUNT(*),SUM(quantity) FROM plancha_item_assignments WHERE order_design_line_id='reserved-line'"
    ).fetchone()
    assert tuple(assignments_after) == tuple(assignments_before)
    designs[0]["quantity"] = 2
    with pytest.raises(ValueError, match="reservadas o producidas"):
        db.save_order_snapshot(order_id, _values(db, order_id), designs, jobs)
