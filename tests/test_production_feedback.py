from app.database.database import ImageDatabase
from app.services.production_batch_service import ProductionBatchService
from app.services.production_feedback_service import ProductionFeedbackService


def _seed_image(db, path):
    db.connection.execute(
        """INSERT INTO images(path,name,extension,size,modified,caption,visible_width,visible_height)
           VALUES(?,?,?,?,?,?,?,?)""",
        (path, path, ".png", 1, 1, "ficticia", 100, 100),
    )


def _job(db, client, quantity, material, path, line_id, *, unit_kind="item", delivery="2030-01-02", urgency=0):
    order_id = db.create_order(client, jobs=[{
        "title": "Stickers" if unit_kind != "sheet" else "Planchas A4",
        "material": material, "size": "5 cm", "quantity": quantity,
    }])
    job = db.order_jobs(order_id)[0]
    _seed_image(db, path)
    db.link_design_to_order(order_id, path, quantity=quantity, size_cm=5,
                            order_job_id=job["id"], design_line_id=line_id)
    db.connection.execute(
        """UPDATE order_design_demand_lines SET unit_kind=?,packing_mode='standard_five_bands'
           WHERE design_line_id=?""", (unit_kind, line_id),
    )
    db.connection.execute(
        "UPDATE orders SET delivery_date=?,print_priority=? WHERE id=?",
        (delivery, urgency, order_id),
    )
    db.connection.commit()
    return order_id, job


def test_feedback_uses_traceable_quantities_and_unique_planchas(tmp_path):
    db = ImageDatabase(tmp_path / "feedback.db")
    order_a, job_a = _job(db, "Cliente A", 20, "Vinilo blanco", "a.png", "feedback-a", urgency=1)
    order_b, job_b = _job(db, "Cliente B", 12, "Vinilo blanco", "b.png", "feedback-b")
    order_c, job_c = _job(db, "Cliente C", 2, "Papel", "c.png", "feedback-c", unit_kind="sheet")
    batch = ProductionBatchService(db)
    feedback = ProductionFeedbackService(db)

    initial = feedback.summary()
    assert initial["available"]["quantities"] == {"units": 32.0, "sheets": 2.0}
    assert initial["available"]["items"][0]["order_id"] == order_a

    preview = batch.preview({"feedback-a": 8, "feedback-b": 12, "feedback-c": 2})
    batch_id = batch.save(preview, "Feedback ABC")
    after_save = feedback.summary()
    assert after_save["available"]["quantities"] == {"units": 12.0, "sheets": 0.0}
    assert {row["order_job_id"] for row in after_save["available"]["items"]} == {job_a["id"]}
    distinct_prepared = db.connection.execute(
        "SELECT COUNT(DISTINCT plancha_id) FROM plancha_item_assignments WHERE state='prepared'"
    ).fetchone()[0]
    assert after_save["prepared"]["work_count"] == distinct_prepared
    assert after_save["prepared"]["quantities"] == {"units": 20.0, "sheets": 2.0}

    mixed = db.connection.execute(
        """SELECT plancha_id FROM plancha_item_assignments WHERE state='prepared'
           GROUP BY plancha_id HAVING COUNT(DISTINCT order_id)>1 LIMIT 1"""
    ).fetchone()
    assert mixed is not None
    mixed_id = int(mixed[0])
    mixed_units = len(db.plancha_assignments(mixed_id))
    db.confirm_plancha_printed_assignments(mixed_id)
    after_print = feedback.summary()
    assert after_print["printed"]["work_count"] == 1
    assert after_print["printed"]["quantities"]["units"] == mixed_units

    first = db.plancha_assignments(mixed_id)[0]
    db.confirm_plancha_finished_assignments(mixed_id, [first["item_id"]])
    after_finish = feedback.summary()
    assert after_finish["printed"]["quantities"]["units"] == mixed_units - 1

    cancellation = batch.cancel(batch_id)
    after_cancel = feedback.summary()
    assert cancellation["released_units"] > 0
    assert cancellation["preserved_units"] == mixed_units
    assert after_cancel["available"]["quantities"]["units"] > 12
    assert after_cancel["printed"]["quantities"]["units"] == mixed_units - 1
    db.close()


def test_feedback_exposes_block_reason_and_is_financially_read_only(tmp_path):
    db = ImageDatabase(tmp_path / "blocked.db")
    order_id, job = _job(db, "Bloqueado", 4, "Papel", "blocked.png", "blocked-line", unit_kind="")
    db.connection.execute("UPDATE order_jobs SET title='Trabajo especial' WHERE id=?", (job["id"],))
    db.connection.execute("UPDATE order_design_demand_lines SET unit_kind='' WHERE design_line_id='blocked-line'")
    db.connection.commit()
    db.register_order_payment(order_id, 7)
    before_order = dict(db.order(order_id))
    before_financials = db.order_financials(order_id)

    summary = ProductionFeedbackService(db).summary()
    assert summary["available"]["work_count"] == 0
    assert summary["blocked"]["work_count"] == 1
    assert summary["blocked"]["items"][0]["order_job_id"] == job["id"]
    assert "correspondencia" in summary["blocked"]["items"][0]["reason"]
    assert db.order_financials(order_id) == before_financials
    assert db.order(order_id)["status"] == before_order["status"]
    db.close()


def test_feedback_does_not_hide_job_without_design_lines(tmp_path):
    db = ImageDatabase(tmp_path / "without-design.db")
    order_id = db.create_order("Sin diseño", jobs=[{
        "title": "Trabajo sin archivo", "material": "Vinilo", "size": "5 cm", "quantity": 3,
    }])
    job = db.order_jobs(order_id)[0]
    summary = ProductionFeedbackService(db).summary()
    blocked = next(row for row in summary["blocked"]["items"] if row["order_job_id"] == job["id"])
    assert "diseños" in blocked["reason"]
    assert summary["available"]["work_count"] == 0
    db.close()


def test_navigation_to_plancha_list_only_sets_the_relevant_filter():
    from app.ui.main_window import VisionVaultApp

    class Recorder:
        def __init__(self):
            self.calls = []

        def select(self, value):
            self.calls.append(value)

    class Variable:
        def __init__(self):
            self.value = "Todas"

        def set(self, value):
            self.value = value

    class Window:
        tabs = Recorder()
        production_tab = "production"
        production_notebook = Recorder()
        production_planchas_tab = "planchas"
        production_filter = Variable()

        def _ensure_production_module(self):
            self.module_opened = True

        def queue_production_refresh(self, delay=60):
            self.refresh_delay = delay

    window = Window()
    VisionVaultApp.show_production_planchas(window, "Pendientes de terminar")
    assert window.production_filter.value == "Pendientes de terminar"
    assert window.tabs.calls == ["production"]
    assert window.production_notebook.calls == ["planchas"]
    assert window.refresh_delay == 0
