import json
from pathlib import Path

import pytest

from app.database.database import ImageDatabase
from app.planchas.model import PlanchaItem, PlanchaProject, requested_unit_key
from main import resolve_database_path


def _job(database, order_id, index=0):
    return database.order_jobs(order_id)[index]


def _items(order_id, job_id, path, quantity, *, size=5.0):
    return PlanchaProject.from_images([{
        "path": path,
        "visible_width": 100,
        "visible_height": 100,
        "order_id": order_id,
        "order_job_id": job_id,
        "order_quantity": quantity,
        "order_size_cm": size,
    }]).items


def _save(database, name, items, plancha_id=None, order_id=None):
    project = PlanchaProject(items=list(items))
    return database.save_plancha_project(
        order_id, name, "Vinilo", json.dumps(project.to_dict()), "", plancha_id,
    )


def test_two_orders_share_one_plancha_and_are_reported_separately(tmp_path):
    db = ImageDatabase(tmp_path / "mixed.db")
    first = db.create_order("Ana", material="Vinilo", quantity=2)
    second = db.create_order("Bruno", material="Vinilo", quantity=3)
    first_job, second_job = _job(db, first), _job(db, second)

    plancha_id = _save(db, "Mixta", [
        *_items(first, first_job["id"], "a.png", 2),
        *_items(second, second_job["id"], "b.png", 3),
    ])

    assert db.plancha_order_ids(plancha_id) == [first, second]
    assert db.order_job_production_quantities(first_job["id"])["prepared_unprinted"] == 2
    assert db.order_job_production_quantities(second_job["id"])["prepared_unprinted"] == 3
    row = next(item for item in db.production_planchas() if item["id"] == plancha_id)
    assert set(row["represented_order_ids"].split(",")) == {str(first), str(second)}
    db.close()


def test_same_file_in_two_jobs_has_distinct_requested_units(tmp_path):
    db = ImageDatabase(tmp_path / "same-file.db")
    order_id = db.create_order("Cliente", jobs=[
        {"title": "Stickers chicos", "quantity": 1},
        {"title": "Stickers grandes", "quantity": 1},
    ])
    jobs = db.order_jobs(order_id)
    db.link_design_to_order(order_id, "same.png", 1, 5, order_job_id=jobs[0]["id"])
    db.link_design_to_order(order_id, "same.png", 1, 8, order_job_id=jobs[1]["id"])
    assert db.connection.execute(
        "SELECT COUNT(*) FROM order_design_job_links WHERE order_id=?", (order_id,)
    ).fetchone()[0] == 2
    small = _items(order_id, jobs[0]["id"], "same.png", 1, size=5)[0]
    large = _items(order_id, jobs[1]["id"], "same.png", 1, size=8)[0]
    assert small.requested_unit_key != large.requested_unit_key
    plancha_id = _save(db, "Dos trabajos", [small, large], order_id=order_id)
    assert len(db.plancha_assignments(plancha_id)) == 2
    db.close()


def test_partial_production_reopens_and_repeated_actions_are_idempotent(tmp_path):
    path = tmp_path / "restart.db"
    db = ImageDatabase(path)
    order_id = db.create_order("Cliente", material="Vinilo", quantity=3)
    job = _job(db, order_id)
    items = _items(order_id, job["id"], "units.png", 3)
    plancha_id = _save(db, "Parcial", items[:2], order_id=order_id)
    _save(db, "Parcial", items[:2], plancha_id=plancha_id, order_id=order_id)
    assert len(db.plancha_assignments(plancha_id)) == 2
    assert db.confirm_plancha_printed_assignments(plancha_id) == 2
    assert db.confirm_plancha_printed_assignments(plancha_id) == 0
    assert db.confirm_plancha_finished_assignments(plancha_id, [items[0].item_id]) == 1
    assert db.confirm_plancha_finished_assignments(plancha_id, [items[0].item_id]) == 0
    db.close()

    reopened = ImageDatabase(path)
    progress = reopened.order_job_production_quantities(job["id"])
    assert progress == {
        "order_job_id": job["id"], "requested": 3.0, "unprepared": 1.0,
        "prepared_unprinted": 0.0, "printed_unfinished": 1.0,
        "finished": 1.0, "pending_finish": 2.0, "traceability": "configured",
    }
    reopened.close()


def test_duplicate_reservation_is_blocked_and_removal_releases_it(tmp_path):
    db = ImageDatabase(tmp_path / "reserve.db")
    order_id = db.create_order("Cliente", quantity=2)
    job = _job(db, order_id)
    items = _items(order_id, job["id"], "a.png", 2)
    first = _save(db, "Primera", items, order_id=order_id)

    with pytest.raises(ValueError, match="ya está preparada"):
        _save(db, "Duplicada", [items[0]], order_id=order_id)

    _save(db, "Primera", [items[1]], plancha_id=first, order_id=order_id)
    assert db.available_requested_copy_numbers(
        order_id=order_id, order_job_id=job["id"], image_path="a.png",
        nominal_size_cm=5, rotation=0, requested_quantity=2,
    ) == [1]
    second = _save(db, "Segunda", [items[0]], order_id=order_id)
    assert len(db.plancha_assignments(second)) == 1
    assert db.delete_plancha_project(second)
    assert db.available_requested_copy_numbers(
        order_id=order_id, order_job_id=job["id"], image_path="a.png",
        nominal_size_cm=5, rotation=0, requested_quantity=2,
    ) == [1]
    db.close()


def test_sticker_units_and_a4_commercial_units_do_not_share_counting_rules(tmp_path):
    db = ImageDatabase(tmp_path / "units.db")
    order_id = db.create_order("Cliente", jobs=[
        {"title": "Stickers", "quantity": 4},
        {"title": "Plancha A4", "material": "Plancha", "size": "A4", "quantity": 2},
    ])
    stickers_job, sheets_job = db.order_jobs(order_id)
    sticker_items = _items(order_id, stickers_job["id"], "sticker.png", 4)
    sheet_key = requested_unit_key(order_id, sheets_job["id"], "sheet-unit", 1, 0, 1)
    sheet_anchor = PlanchaItem(
        "layout.png", "Plancha comercial 1", 5, 5, order_id=order_id,
        order_job_id=sheets_job["id"], requested_unit_key=sheet_key,
        production_unit_kind="sheet", item_id="sheet-anchor-1",
    )
    _save(db, "Unidades", [*sticker_items, sheet_anchor], order_id=order_id)

    assert db.order_job_production_quantities(stickers_job["id"])["prepared_unprinted"] == 4
    sheet_progress = db.order_job_production_quantities(sheets_job["id"])
    assert sheet_progress["prepared_unprinted"] == 1
    assert sheet_progress["unprepared"] == 1
    db.close()


def test_legacy_plancha_opens_without_invented_assignments(tmp_path):
    db = ImageDatabase(tmp_path / "legacy.db")
    order_id = db.create_order("Cliente", quantity=1)
    legacy = PlanchaProject([PlanchaItem("old.png", "Vieja", 5, 5, order_id=order_id)])
    plancha_id = _save(db, "Vieja", legacy.items, order_id=order_id)
    assert db.plancha_project(plancha_id) is not None
    assert db.plancha_assignments(plancha_id) == []
    assert db.order_job_production_quantities(_job(db, order_id)["id"])["traceability"] == "untracked"
    assert db.link_plancha_to_order(plancha_id, order_id)
    db.close()


def test_print_finish_and_delivery_never_modify_payments_or_fabricate_progress(tmp_path):
    db = ImageDatabase(tmp_path / "separation.db")
    order_id = db.create_order("Cliente", quantity=2, price=100)
    job = _job(db, order_id)
    db.register_order_payment(order_id, 25)
    item = _items(order_id, job["id"], "one.png", 1)[0]
    plancha_id = _save(db, "Separada", [item], order_id=order_id)
    print_job = db.create_print_job(plancha_id, "Operador", "Manual", {}, 1, "final.png")
    db.update_print_job(print_job, "En cola", "Enviada al driver")
    assert db.order_job_production_quantities(job["id"])["prepared_unprinted"] == 1
    db.update_print_job(print_job, "Impresa", "Salida física confirmada")
    db.confirm_plancha_finished_assignments(plancha_id)
    assert db.order_financials(order_id)["paid_amount"] == 25
    before = db.order_job_production_quantities(job["id"])

    with pytest.raises(ValueError, match="pendientes"):
        db.mark_order_delivered(order_id)
    after = db.order_job_production_quantities(job["id"])
    assert after == before
    assert db.order_financials(order_id)["paid_amount"] == 25
    db.close()


def test_printed_plancha_cannot_be_deleted_silently(tmp_path):
    db = ImageDatabase(tmp_path / "history.db")
    order_id = db.create_order("Cliente", quantity=1)
    job = _job(db, order_id)
    plancha_id = _save(db, "Impresa", _items(order_id, job["id"], "a.png", 1), order_id=order_id)
    db.confirm_plancha_printed_assignments(plancha_id)
    with pytest.raises(RuntimeError, match="historial"):
        db.delete_plancha_project(plancha_id)
    assert db.plancha_project(plancha_id) is not None
    db.close()


def test_layout_edits_and_file_relocation_keep_requested_identity(tmp_path):
    db = ImageDatabase(tmp_path / "identity.db")
    order_id = db.create_order("Cliente", quantity=2)
    job = _job(db, order_id)
    line_id = "design-line-stable"
    first = PlanchaProject.from_images([{
        "path": str(tmp_path / "original" / "same.png"), "visible_width": 100,
        "visible_height": 100, "order_id": order_id, "order_job_id": job["id"],
        "order_design_line_id": line_id, "order_quantity": 2, "order_size_cm": 5,
    }]).items
    plancha_id = _save(db, "Editable", [first[0]], order_id=order_id)
    key = first[0].requested_unit_key
    first[0].x_cm, first[0].y_cm, first[0].rotation = 8.2, 11.4, 90
    first[0].path = str(tmp_path / "relocated" / "same.png")
    _save(db, "Editable", [first[0]], plancha_id=plancha_id, order_id=order_id)
    assignment = db.plancha_assignments(plancha_id)[0]
    assert assignment["requested_unit_key"] == key
    assert assignment["image_path"] == first[0].path
    assert db.available_requested_copy_numbers(
        order_id=order_id, order_job_id=job["id"], image_path=first[0].path,
        nominal_size_cm=5, rotation=90, requested_quantity=2, design_line_id=line_id,
    ) == [2]
    db.close()


def test_two_demand_lines_in_same_job_can_use_same_file(tmp_path):
    db = ImageDatabase(tmp_path / "lines.db")
    order_id = db.create_order("Cliente", quantity=2)
    job = _job(db, order_id)
    db.connection.execute(
        "INSERT INTO images(path,name,extension,size,modified,caption) VALUES(?,?,?,?,?,?)",
        ("same.png", "same.png", ".png", 1, 1, "ficticia"),
    )
    db.connection.commit()
    db.link_design_to_order(order_id, "same.png", order_job_id=job["id"], design_line_id="line-a")
    db.link_design_to_order(order_id, "same.png", order_job_id=job["id"], design_line_id="line-b")
    designs = db.order_designs(order_id)
    assert {row["design_line_id"] for row in designs} == {"line-a", "line-b"}
    keys = {
        requested_unit_key(order_id, job["id"], copy_number=1, design_line_id=row["design_line_id"])
        for row in designs
    }
    assert len(keys) == 2
    db.connection.execute(
        "INSERT INTO images(path,name,extension,size,modified,caption) VALUES(?,?,?,?,?,?)",
        ("moved.png", "moved.png", ".png", 1, 2, "ficticia"),
    )
    db.link_design_to_order(
        order_id, "moved.png", order_job_id=job["id"], design_line_id="line-a",
    )
    moved = {row["design_line_id"]: row for row in db.order_designs(order_id)}
    assert moved["line-a"]["image_path"] == "moved.png"
    assert moved["line-b"]["image_path"] == "same.png"
    assert requested_unit_key(
        order_id, job["id"], copy_number=1, design_line_id="line-a",
    ) in keys
    db.close()


def test_quantity_cannot_drop_below_produced_history(tmp_path):
    db = ImageDatabase(tmp_path / "reconcile.db")
    order_id = db.create_order("Cliente", quantity=2)
    job = _job(db, order_id)
    plancha_id = _save(db, "Historial", _items(order_id, job["id"], "a.png", 2), order_id=order_id)
    db.confirm_plancha_printed_assignments(plancha_id)
    values = db.order(order_id)
    reduced = dict(job)
    reduced["quantity"] = 1
    with pytest.raises(ValueError, match="ya hay 2 unidad"):
        db.save_order_snapshot(order_id, values, db.order_designs(order_id), [reduced])
    assert db.order_job_production_quantities(job["id"])["requested"] == 2
    assert db.order_job_production_quantities(job["id"])["printed_unfinished"] == 2
    db.close()


def test_repeated_order_save_keeps_generated_design_line_identity(tmp_path):
    db = ImageDatabase(tmp_path / "snapshot-line.db")
    order_id = db.create_order("Cliente", quantity=1)
    job = _job(db, order_id)
    db.connection.execute(
        "INSERT INTO images(path,name,extension,size,modified,caption) VALUES(?,?,?,?,?,?)",
        ("design.png", "design.png", ".png", 1, 1, "ficticia"),
    )
    design = {"image_path": "design.png", "quantity": 1, "size_cm": 5,
              "rotation": 0, "order_job_id": job["id"]}
    values = db.order(order_id)
    db.save_order_snapshot(order_id, values, [design], [job])
    generated = design["design_line_id"]
    db.save_order_snapshot(order_id, values, [design], [job])
    rows = db.connection.execute(
        "SELECT design_line_id FROM order_design_demand_lines WHERE order_id=?", (order_id,)
    ).fetchall()
    assert [row[0] for row in rows] == [generated]
    item = PlanchaProject.from_images([{
        "path": "design.png", "visible_width": 100, "visible_height": 100,
        "order_id": order_id, "order_job_id": job["id"],
        "order_design_line_id": generated, "order_quantity": 1, "order_size_cm": 5,
    }]).items[0]
    plancha_id = _save(db, "Producida", [item], order_id=order_id)
    db.confirm_plancha_printed_assignments(plancha_id)
    design["size_cm"] = 8
    with pytest.raises(ValueError, match="línea nueva"):
        db.save_order_snapshot(order_id, values, [design], [job])
    assert db.plancha_assignments(plancha_id)[0]["state"] == "printed"
    db.close()


def test_alternative_database_path_is_explicit_and_does_not_touch_default(tmp_path):
    usual = Path(__file__).resolve().parents[1] / "visionvault.db"
    before = usual.stat().st_mtime_ns if usual.exists() else None
    alternative = tmp_path / "isolated.db"
    resolved, isolated = resolve_database_path(alternative)
    assert isolated is True
    db = ImageDatabase(resolved)
    db.create_order("Datos ficticios", quantity=1)
    db.close()
    assert alternative.exists()
    assert (usual.stat().st_mtime_ns if usual.exists() else None) == before
    with pytest.raises(ValueError, match="carpeta.*no existe"):
        resolve_database_path(tmp_path / "missing" / "invalid.db")
