"""Aceptación reproducible y explícitamente SIMULADA, sin escribir en la base operativa."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
from app.database.database import ImageDatabase
from app.services.order_production_service import OrderProductionService
from app.services.production_batch_service import ProductionBatchService


def checkpoint(db, destination):
    if destination.exists():
        raise ValueError(f"No sobrescribir: {destination}")
    db.connection.commit()
    with sqlite3.connect(destination) as target:
        db.connection.backup(target)


def run(folder):
    folder = folder.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    db = ImageDatabase(folder / "simulation.db")
    designs = []
    for label, quantity, color in (("A", 40, "#891e46"), ("B", 35, "#245da8"), ("C", 25, "#36864d")):
        path = folder / f"FICTICIO-{label}.png"
        image = Image.new("RGBA", (600, 600), "white")
        draw = ImageDraw.Draw(image)
        draw.ellipse((15, 15, 585, 585), fill=color)
        draw.text((100, 270), f"FICTICIO {label} - SOLO PRUEBA", fill="white", stroke_width=1)
        image.save(path)
        stat = path.stat()
        db.connection.execute(
            """INSERT INTO images(path,name,extension,size,modified,caption,visible_width,visible_height)
               VALUES(?,?,?,?,?,?,?,?)""",
            (str(path), f"FICTICIO {label}", ".png", stat.st_size, stat.st_mtime,
             "DISEÑO FICTICIO - VALIDACIÓN AISLADA SPRINT 3", 600, 600),
        )
        designs.append({"image_path": str(path), "quantity": quantity, "size_cm": 5,
                        "order_job_index": 0, "design_line_id": f"acceptance-{label}",
                        "unit_kind": "item", "packing_mode": "standard_five_bands", "workspace_format": "a4"})
    db.connection.commit()
    order = db.create_order_with_details("SIMULACIÓN EXPLÍCITA SPRINT 3 — NO ES VENTA", jobs=[{
        "title": "Stickers de prueba 5 cm", "material": "Vinilo blanco", "size": "5 cm",
        "quantity": 100, "unit_kind": "item", "distribution_policy": "complete", "subtotal": 40000,
    }], designs=designs, observations="BASE AISLADA. Impresión, terminación y cierre SIMULADOS. No corresponden a producción física.")
    job = db.order_jobs(order)[0]["id"]
    db.register_order_payment(order, 10000, "SIMULADO", "Seña ficticia", "acceptance-simulated")
    finances = db.order_financials(order)
    stages, checks = {}, {}

    def record(name):
        data = OrderProductionService(db).snapshot(order)
        stages[name] = data
        checkpoint(db, folder / f"{name}.db")
        return data["jobs"][0]

    initial = record("01-created")
    assert initial["distributed"] == initial["requested"] == initial["available"] == 100
    assert len(db.order_designs(order)) == 3
    batch = ProductionBatchService(db)
    split = {"acceptance-A": 8, "acceptance-B": 7, "acceptance-C": 5}
    preview = batch.preview(split)
    assert not preview.excluded
    first = batch.save(preview, "SIMULACIÓN — primera tanda 20 (A8/B7/C5)")
    prepared = record("02-prepared")
    assert (prepared["prepared_current"], prepared["available"]) == (20, 80)
    before = db.connection.execute("SELECT COUNT(*) FROM production_batches").fetchone()[0]
    try:
        batch.save(preview, "DEBE BLOQUEARSE")
        raise AssertionError("Se aceptó la preparación duplicada")
    except ValueError as error:
        checks["duplicate_preparation_blocked"] = str(error)
    assert db.connection.execute("SELECT COUNT(*) FROM production_batches").fetchone()[0] == before
    rows = [dict(r) for r in db.connection.execute(
        "SELECT a.* FROM plancha_item_assignments a JOIN production_batch_planchas p ON p.plancha_id=a.plancha_id WHERE p.batch_id=? ORDER BY a.id", (first,))]
    assert len(rows) == 20
    for plancha in {r["plancha_id"] for r in rows}:
        assert order in db.plancha_order_ids(plancha)
        db.confirm_plancha_printed_assignments(plancha)  # SIMULACIÓN, base aislada.
    for row in rows[:10]:
        db.confirm_plancha_finished_assignments(row["plancha_id"], [row["item_id"]])
    partial = record("03-partial")
    assert (partial["printed_accumulated"], partial["printed_current"], partial["finished"], partial["pending_finish"]) == (20, 10, 10, 90)
    preserved = batch.cancel(first)
    assert preserved["released_units"] == 0 and preserved["preserved_units"] == 20
    checks["printed_cancellation_preserves_20"] = preserved
    cancelled = batch.save(batch.preview({k: 3 for k in split}), "SIMULACIÓN — cancelar 9 sin imprimir")
    released = batch.cancel(cancelled)
    assert released["released_units"] == 9
    assert batch.cancel(cancelled)["released_units"] == 0
    checks["prepared_cancellation_releases_9"] = released
    second = batch.save(batch.preview(split), "SIMULACIÓN — segunda tanda 20")
    remaining = record("04-remaining")
    assert (remaining["committed"], remaining["available"], remaining["released"]) == (40, 60, 9)
    assert (remaining["printed_accumulated"], remaining["finished"]) == (20, 10)
    assert len(db.order_designs(order)) == 3
    db.close()
    db = ImageDatabase(folder / "simulation.db")
    assert OrderProductionService(db).snapshot(order) == stages["04-remaining"]
    checks["recovery_matches_saved_snapshot"] = True
    batch = ProductionBatchService(db)
    batch.save(OrderProductionService(db).preview(order, {job: 60}), "SIMULACIÓN — saldo final 60")
    for row in db.connection.execute("SELECT DISTINCT plancha_id FROM plancha_item_assignments WHERE state='prepared'").fetchall():
        db.confirm_plancha_printed_assignments(row[0])
    for row in db.connection.execute("SELECT DISTINCT plancha_id FROM plancha_item_assignments WHERE state='printed'").fetchall():
        db.confirm_plancha_finished_assignments(row[0])
    assert db.order_financials(order) == finances
    db.mark_order_delivered(order)  # CIERRE SIMULADO: no representa entrega física.
    final = record("05-closed")
    assert final["finished"] == 100 and final["pending_finish"] == final["pending_print"] == 0
    assert final["delivered"] is None
    assert db.order_financials(order) == finances
    assert not db.connection.execute("SELECT requested_unit_key FROM plancha_item_assignments WHERE state<>'released' GROUP BY requested_unit_key HAVING COUNT(*)>1").fetchall()
    checks["no_duplicate_active_requested_units"] = True
    checks["integrity_check"] = db.connection.execute("PRAGMA integrity_check").fetchone()[0]
    checks["foreign_key_check"] = [tuple(r) for r in db.connection.execute("PRAGMA foreign_key_check")]
    db.close()

    # Rama física independiente: ninguna impresión, corte o entrega confirmados.
    with sqlite3.connect(folder / "01-created.db") as source:
        with sqlite3.connect(folder / "physical-pending.db") as target:
            source.backup(target)
    physical = ImageDatabase(folder / "physical-pending.db")
    physical_batch = ProductionBatchService(physical)
    physical_id = physical_batch.save(physical_batch.preview({k: 1 for k in split}), "PENDIENTE OPERADOR — prueba física 3 unidades A/B/C")
    physical_snapshot = OrderProductionService(physical).snapshot(order)
    assert physical_snapshot["jobs"][0]["prepared_current"] == 3
    assert physical_snapshot["jobs"][0]["printed_accumulated"] == physical_snapshot["jobs"][0]["finished"] == 0
    checks["physical_batch_id"] = physical_id
    physical.close()
    report = {"simulation": True, "order_id": order, "job_id": job, "first_batch_id": first,
              "second_batch_id": second, "stages": stages, "checks": checks,
              "physical_pending": physical_snapshot, "created_at": datetime.now().isoformat()}
    (folder / "observations.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"folder": str(folder), "checks": checks}, ensure_ascii=False))


def gui(path):
    from app.ui.main_window import VisionVaultApp
    app = VisionVaultApp(database_path=path.resolve(), isolated_database=True)
    app.title(f"ACEPTACIÓN S3 — BASE AISLADA — {path.stem}")
    app.after(5000, lambda: app.open_order_workspace(1))
    app.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--gui", action="store_true")
    args = parser.parse_args()
    gui(args.path) if args.gui else run(args.path)
