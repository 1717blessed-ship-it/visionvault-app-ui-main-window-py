from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from app.database.database import ImageDatabase
from app.domain.order_states import OrderStateService
from app.services.delivery_readiness import confirm_direct_source, assert_deliverable
from app.services.order_production_service import OrderProductionService
from app.services.production_batch_service import ProductionBatchService
from app.sales.repository import SellerRepository
from app.api.mobile_jobs import MobileJobsHandler
from app.services.production_stage_service import ProductionStageService


def order(db, quantity=5):
    db.connection.execute("INSERT OR IGNORE INTO images(path,name,extension,size,modified,caption,visible_width,visible_height) VALUES('delivery.png','Test','.png',1,1,'Test',100,100)")
    db.connection.commit()
    oid = db.create_order_with_details("Entrega de prueba", jobs=[{
        "title": "Stickers", "quantity": quantity, "unit_kind": "item", "material": "Vinilo",
        "subtotal": 500, "distribution_policy": "complete",
    }], designs=[{"image_path": "delivery.png", "quantity": quantity, "size_cm": 5,
                 "order_job_index": 0, "unit_kind": "item", "packing_mode": "standard_five_bands"}])
    return oid, db.order_jobs(oid)[0]["id"]


def prepare(db, oid, jid, quantity):
    batch = ProductionBatchService(db)
    bid = batch.save(OrderProductionService(db).preview(oid, {jid: quantity}))
    ids = [r[0] for r in db.connection.execute("SELECT plancha_id FROM production_batch_planchas WHERE batch_id=?", (bid,))]
    return bid, ids


@pytest.mark.parametrize("state", ["none", "prepared", "printed", "partial", "cancelled"])
def test_incomplete_delivery_is_blocked_in_every_stage(tmp_path, state):
    db = ImageDatabase(tmp_path / "db.sqlite")
    oid, jid = order(db)
    if state != "none":
        bid, plans = prepare(db, oid, jid, 5)
        if state in {"printed", "partial"}:
            for plan in plans:
                db.confirm_plancha_printed_assignments(plan)
            if state == "partial":
                row = db.plancha_assignments(plans[0])[0]
                db.confirm_plancha_finished_assignments(plans[0], [row["item_id"]])
        if state == "cancelled":
            ProductionBatchService(db).cancel(bid)
    db.register_order_payment(oid, 100)
    finances = db.order_financials(oid)
    with pytest.raises(ValueError, match="pendientes"):
        db.mark_order_delivered(oid)
    with pytest.raises(ValueError):
        OrderStateService(db.connection).transition(oid, "Entregado", force=True)
    with pytest.raises(sqlite3.IntegrityError):
        with db.connection:
            db.connection.execute("UPDATE orders SET status='Entregado' WHERE id=?", (oid,))
    assert db.order_financials(oid) == finances
    assert db.order(oid)["status"] != "Entregado"


def test_complete_production_delivers_and_all_jobs_are_required(tmp_path):
    db = ImageDatabase(tmp_path / "db.sqlite")
    oid, jid = order(db)
    _, plans = prepare(db, oid, jid, 5)
    for plan in plans:
        db.confirm_plancha_printed_assignments(plan)
        db.confirm_plancha_finished_assignments(plan)
    db.replace_order_jobs(oid, [*db.order_jobs(oid), {"title": "Stock", "quantity": 2}])
    with pytest.raises(ValueError, match="Stock"):
        db.mark_order_delivered(oid)
    direct = db.order_jobs(oid)[1]
    confirm_direct_source(db.connection, direct["id"], source="stock", quantity=2,
                          reference="Remito depósito 123", actor="Operador")
    db.mark_order_delivered(oid)
    assert db.order(oid)["status"] == "Entregado"
    for statement in (
        "DELETE FROM order_jobs WHERE id=?",
        "DELETE FROM order_events WHERE event_type='delivery.source.confirmed' AND order_id=?",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            with db.connection:
                db.connection.execute(statement, (direct['id'] if 'order_jobs' in statement else oid,))
    with pytest.raises(sqlite3.IntegrityError):
        with db.connection:
            db.connection.execute("UPDATE plancha_item_assignments SET state='released' WHERE order_job_id=?", (jid,))
    with pytest.raises(sqlite3.IntegrityError):
        with db.connection:
            db.connection.execute("UPDATE order_jobs SET quantity=3 WHERE id=?", (direct["id"],))


def test_direct_source_is_not_a_production_override(tmp_path):
    db = ImageDatabase(tmp_path / "db.sqlite")
    oid, jid = order(db)
    with pytest.raises(ValueError, match="productivo"):
        confirm_direct_source(db.connection, jid, source="stock", quantity=5, reference="Stock", actor="Operador")


def test_api_delivery_returns_conflict_and_keeps_state(tmp_path):
    db = ImageDatabase(tmp_path / "db.sqlite")
    oid, jid = order(db)
    db.connection.execute("UPDATE orders SET creator_device_id=7 WHERE id=?", (oid,))
    db.connection.commit()
    errors = []
    handler = SimpleNamespace(event_repo=SimpleNamespace(conn=db.connection),
                              _send_error=lambda code, message: errors.append((code, message)))
    MobileJobsHandler._mark_delivered(handler, oid, {"id": 7})
    assert errors[0][0] == 409
    assert db.order(oid)["status"] != "Entregado"


def test_business_service_and_sales_delivery_are_atomic(tmp_path):
    db = ImageDatabase(tmp_path / "db.sqlite")
    oid, jid = order(db)
    service = ProductionStageService(db.connection, None)
    success, message, _ = service.finalize_order_delivery(oid, 0, "Prueba")
    assert not success and "pendientes" in message
    sales = SellerRepository(db.connection)
    with pytest.raises(ValueError):
        sales.upsert_delivery(oid, status="Entregada")
    assert sales.delivery(oid) is None


def test_api_status_patch_cannot_bypass_delivery_guard(tmp_path):
    db = ImageDatabase(tmp_path / 'patch.sqlite')
    oid, _ = order(db)
    db.connection.execute('UPDATE orders SET creator_device_id=7 WHERE id=?', (oid,))
    db.connection.commit()
    errors = []
    handler = SimpleNamespace(event_repo=SimpleNamespace(conn=db.connection),
                              _runtime_config=lambda: {},
                              _read_json_body=lambda: {'status': 'Entregado'},
                              _send_error=lambda code, message: errors.append((code, message)))
    MobileJobsHandler._update_order_status(handler, oid, {'id': 7})
    assert errors[0][0] == 409
    assert not db.connection.in_transaction
    assert db.order(oid)['status'] != 'Entregado'


def test_concurrent_quantity_increase_cannot_invalidate_delivery(tmp_path):
    db = ImageDatabase(tmp_path / "db.sqlite")
    oid = db.create_order("Stock", quantity=2)
    jid = db.order_jobs(oid)[0]["id"]
    confirm_direct_source(db.connection, jid, source="stock", quantity=2, reference="Remito 42", actor="Operador")
    barrier = threading.Barrier(2)
    def deliver():
        barrier.wait()
        try:
            db.mark_order_delivered(oid)
            return "delivered"
        except (ValueError, sqlite3.Error):
            return "blocked"
    def increase():
        barrier.wait()
        try:
            with db.connection:
                db.connection.execute("UPDATE order_jobs SET quantity=3 WHERE id=?", (jid,))
            return "increased"
        except sqlite3.Error:
            return "blocked"
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(deliver), pool.submit(increase)
        results = (a.result(), b.result())
    assert results != ("delivered", "increased")


def test_historical_inconsistency_is_visible_not_rewritten(tmp_path):
    db = ImageDatabase(tmp_path / "db.sqlite")
    oid, jid = order(db)
    db.connection.execute("DROP TRIGGER guard_orders_total_delivery")
    db.connection.execute("UPDATE orders SET status='Entregado' WHERE id=?", (oid,))
    db.connection.commit()
    before = dict(db.order(oid))
    snapshot = OrderProductionService(db).snapshot(oid)
    assert snapshot["anomalies"]
    assert dict(db.order(oid)) == before
