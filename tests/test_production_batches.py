import json

import pytest

from app.database.database import ImageDatabase
from app.planchas.model import PlanchaProject
from app.services.production_batch_service import ProductionBatchService


def _seed_image(db, path):
    db.connection.execute(
        """INSERT INTO images(path,name,extension,size,modified,caption,visible_width,visible_height)
           VALUES(?,?,?,?,?,?,?,?)""",
        (path, path, ".png", 1, 1, "ficticia", 100, 100),
    )


def _order_with_line(db, client, quantity, material, path, line_id):
    order_id = db.create_order(client, jobs=[{
        "title": "Stickers", "material": material, "size": "5 cm", "quantity": quantity,
    }])
    job = db.order_jobs(order_id)[0]
    _seed_image(db, path)
    db.link_design_to_order(
        order_id, path, quantity=quantity, size_cm=5, order_job_id=job["id"], design_line_id=line_id,
    )
    db.connection.execute(
        "UPDATE order_design_demand_lines SET unit_kind='item',packing_mode='standard_five_bands' WHERE design_line_id=?",
        (line_id,),
    )
    db.connection.commit()
    return order_id, job


def _scenario(db):
    a = _order_with_line(db, "Cliente A", 20, "Vinilo blanco", "a.png", "line-a")
    b = _order_with_line(db, "Cliente B", 12, "Vinilo blanco", "b.png", "line-b")
    c = _order_with_line(db, "Cliente C", 10, "Vinilo especial", "c.png", "line-c")
    return a, b, c


def test_three_order_batch_groups_persists_and_tracks_partial_progress(tmp_path):
    path = tmp_path / "batch.db"
    db = ImageDatabase(path)
    (order_a, job_a), (order_b, job_b), (order_c, job_c) = _scenario(db)
    db.register_order_payment(order_a, 5)
    service = ProductionBatchService(db)

    preview = service.preview({"line-a": 8, "line-b": 12, "line-c": 10})
    assert len(preview.groups) == 2
    assert preview.plancha_count >= 2
    white = next(group for group in preview.groups if group.material == "Vinilo blanco")
    assert {item.order_id for project in white.projects for item in project.items} == {order_a, order_b}
    mixed_items = [item for project in white.projects for item in project.items]
    assert {item.client for item in mixed_items} == {"Cliente A", "Cliente B"}
    assert {item.order_job_title for item in mixed_items} == {"Stickers"}
    assert all(item.order_number and item.copy_number >= 1 for item in mixed_items)
    batch_id = service.save(preview, "Tanda ABC")

    assert db.order_job_production_quantities(job_a["id"])["prepared_unprinted"] == 8
    assert db.order_job_production_quantities(job_a["id"])["unprepared"] == 12
    assert db.order_job_production_quantities(job_b["id"])["prepared_unprinted"] == 12
    assert db.order_job_production_quantities(job_c["id"])["prepared_unprinted"] == 10
    assert service.preview({"line-a": 12}).groups[0].selections[0]["quantity"] == 12
    assert service.preview({"line-a": 20}).excluded[0]["reason"] == "Cantidad disponible: 12."
    db.close()

    reopened = ImageDatabase(path)
    service = ProductionBatchService(reopened)
    assert service.batches()[0]["id"] == batch_id
    mixed = reopened.connection.execute(
        """SELECT links.plancha_id FROM production_batch_planchas links
           JOIN plancha_item_assignments assignments ON assignments.plancha_id=links.plancha_id
           WHERE links.batch_id=? GROUP BY links.plancha_id HAVING COUNT(DISTINCT assignments.order_id)=2""",
        (batch_id,),
    ).fetchone()
    assert mixed is not None
    mixed_id = int(mixed[0])
    reopened.confirm_plancha_printed_assignments(mixed_id)
    assignments = reopened.plancha_assignments(mixed_id)
    first = assignments[0]
    reopened.confirm_plancha_finished_assignments(mixed_id, [first["item_id"]])
    reopened.confirm_plancha_finished_assignments(mixed_id, [first["item_id"]])
    progress_a = reopened.order_job_production_quantities(job_a["id"])
    progress_b = reopened.order_job_production_quantities(job_b["id"])
    assert progress_a["printed_unfinished"] + progress_a["finished"] == 8
    assert 0 < progress_b["printed_unfinished"] + progress_b["finished"] < 12
    assert progress_b["prepared_unprinted"] > 0
    assert progress_a["finished"] + progress_b["finished"] == 1
    assert reopened.order_financials(order_a)["paid_amount"] == 5
    assert reopened.order(order_a)["status"] != "Entregado"

    summary = service.cancel(batch_id)
    assert summary["released_units"] > 0
    assert summary["preserved_units"] > 0
    assert summary["removed_planchas"] > 0
    assert summary["preserved_planchas"] > 0
    assert service.batches()[0]["status"] == "cancelled"
    assert reopened.plancha_project(mixed_id) is not None
    assert all(row["state"] in {"printed", "finished"} for row in reopened.plancha_assignments(mixed_id))
    assert reopened.order_job_production_quantities(job_c["id"])["unprepared"] == 10
    assert reopened.order_financials(order_a)["paid_amount"] == 5
    assert reopened.order(order_a)["status"] != "Entregado"
    reopened.close()


def test_demo_launcher_always_creates_a_new_isolated_database(tmp_path):
    from tools.launch_batch_demo import create_unique_demo

    first = create_unique_demo(tmp_path)
    second = create_unique_demo(tmp_path)
    assert first != second
    assert first.exists() and second.exists()
    assert (tmp_path / f"{first.stem}-assets").is_dir()
    assert (tmp_path / f"{second.stem}-assets").is_dir()


def test_batch_save_conflict_is_atomic(tmp_path):
    db = ImageDatabase(tmp_path / "conflict.db")
    (order_a, job_a), _, _ = _scenario(db)
    service = ProductionBatchService(db)
    preview = service.preview({"line-a": 3})
    competing_item = preview.groups[0].projects[0].items[0]
    competing = PlanchaProject([competing_item])
    db.save_plancha_project(
        order_a, "Competidora", "Vinilo blanco", json.dumps(competing.to_dict()), "",
    )
    batches_before = db.connection.execute("SELECT COUNT(*) FROM production_batches").fetchone()[0]
    planchas_before = db.connection.execute("SELECT COUNT(*) FROM plancha_projects").fetchone()[0]
    with pytest.raises(ValueError, match="reservada"):
        service.save(preview, "Debe fallar")
    assert db.connection.execute("SELECT COUNT(*) FROM production_batches").fetchone()[0] == batches_before
    assert db.connection.execute("SELECT COUNT(*) FROM plancha_projects").fetchone()[0] == planchas_before
    assert db.order_job_production_quantities(job_a["id"])["prepared_unprinted"] == 1
    db.close()


def test_v1_history_is_reconciled_or_blocks_ambiguity(tmp_path):
    db = ImageDatabase(tmp_path / "legacy.db")
    (order_a, job_a), _, _ = _scenario(db)
    legacy = PlanchaProject.from_images([{
        "path": "a.png", "visible_width": 100, "visible_height": 100,
        "order_id": order_a, "order_job_id": job_a["id"], "order_quantity": 1, "order_size_cm": 5,
    }])
    db.save_plancha_project(order_a, "V1", "Vinilo blanco", json.dumps(legacy.to_dict()), "")
    service = ProductionBatchService(db)
    line_a = next(row for row in service.candidates() if row.design_line_id == "line-a")
    assert line_a.available == 19
    assert service.preview({"line-a": 19}).groups[0].selections[0]["quantity"] == 19

    db.link_design_to_order(
        order_a, "a.png", quantity=1, size_cm=5, order_job_id=job_a["id"], design_line_id="line-a-2",
    )
    db.connection.execute(
        "UPDATE order_design_demand_lines SET unit_kind='item',packing_mode='standard_five_bands' WHERE design_line_id='line-a-2'"
    )
    db.connection.commit()
    blocked = [row for row in service.candidates() if row.order_job_id == job_a["id"]]
    assert blocked and all("v1 ambiguo" in row.blocked_reason for row in blocked)
    db.close()


def test_sheet_units_require_explicit_mapping_and_create_one_project_per_sheet(tmp_path):
    db = ImageDatabase(tmp_path / "sheets.db")
    order_id = db.create_order("Hojas", jobs=[{
        "title": "Planchas A4", "material": "Vinilo blanco", "size": "A4", "quantity": 2,
    }])
    job = db.order_jobs(order_id)[0]
    _seed_image(db, "sheet.png")
    db.link_design_to_order(
        order_id, "sheet.png", quantity=2, size_cm=20, order_job_id=job["id"], design_line_id="sheet-line",
    )
    service = ProductionBatchService(db)
    candidate = service.job_candidates()[0]
    assert "correspondencia" in candidate.blocked_reason
    assert service.preview_jobs({job["id"]: 2}).groups == []

    service.configure_job_unit(job["id"], "sheet")
    db.connection.execute(
        "UPDATE order_design_demand_lines SET packing_mode='standard_five_bands',workspace_format='a4' WHERE design_line_id='sheet-line'"
    )
    db.connection.commit()
    preview = service.preview_jobs({job["id"]: 2})
    assert len(preview.groups) == 1
    assert len(preview.groups[0].projects) == 2
    assert all(len(project.items) == 1 for project in preview.groups[0].projects)
    db.close()
