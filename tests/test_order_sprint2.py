import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.database.database import ImageDatabase


def make_order(db, policy="partial", quantity=5, assigned=2, unit="item"):
    db.connection.execute("INSERT OR IGNORE INTO images(path,name,extension,size,modified,caption) VALUES('design.png','Design','.png',1,1,'test')")
    db.connection.commit()
    return db.create_order_with_details("Sprint 2", jobs=[{
        "title": "Stickers", "quantity": quantity, "subtotal": 100,
        "unit_kind": unit, "distribution_policy": policy,
    }], designs=[{"image_path": "design.png", "quantity": assigned,
                 "order_job_index": 0, "unit_kind": unit}] if assigned else [])


@pytest.mark.parametrize("policy,assigned,unit", [("complete", 5, "item"), ("partial", 2, "item"), ("complete", 5, "sheet")])
def test_policies_persist(tmp_path, policy, assigned, unit):
    path = tmp_path / "orders.db"
    db = ImageDatabase(path)
    order = make_order(db, policy, assigned=assigned, unit=unit)
    db.close()
    db = ImageDatabase(path)
    assert db.order_jobs(order)[0]["distribution_policy"] == policy
    assert sum(d["quantity"] for d in db.order_designs(order)) == assigned


@pytest.mark.parametrize("policy,assigned", [("complete", 2), ("complete", 0), ("partial", 6), ("partial", -1)])
def test_invalid_distribution_rolls_back(tmp_path, policy, assigned):
    db = ImageDatabase(tmp_path / "orders.db")
    with pytest.raises(ValueError):
        make_order(db, policy, assigned=assigned)
    assert not db.connection.execute("SELECT 1 FROM orders WHERE client='Sprint 2'").fetchone()


def test_payment_retries_conflicts_and_cancellation(tmp_path):
    db = ImageDatabase(tmp_path / "orders.db")
    order = make_order(db)
    db.register_order_payment(order, 20, "Banco", "Referencia", "external-1")
    with pytest.raises(ValueError, match="incompatibles"):
        db.register_order_payment(order, 30, "Banco", "Referencia", "external-1")
    db.cancel_order_payment(order, db.order_payments(order)[0]["id"], "Reversión")
    assert db.register_order_payment(order, 20, "Banco", "Referencia", "external-1")["paid_amount"] == 0
    assert len(db.order_payments(order)) == 1
    assert db.orders()[0]["current_paid_amount"] == 0
    assert db.order_summaries()[0]["paid_amount"] == 0
    assert sum(day["paid"] for day in db.sales_time_series(datetime.now().strftime('%Y-%m'))) == 0


def test_concurrent_payment_retry_creates_one_record(tmp_path):
    db = ImageDatabase(tmp_path / "orders.db")
    order = make_order(db)
    def pay(_):
        return db.register_order_payment(order, 20, "Banco", "R", "concurrent")["paid_amount"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(pay, range(2))) == [20, 20]
    assert len(db.order_payments(order)) == 1


def test_commercial_change_has_one_event_and_no_retroactive_repricing(tmp_path):
    db = ImageDatabase(tmp_path / "orders.db")
    order = make_order(db)
    jobs = db.order_jobs(order)
    jobs[0].update(subtotal=120, cost_total=45)
    values = dict(db.order(order))
    for _ in range(2):
        db.save_order_snapshot(order, values, db.order_designs(order), jobs)
    events = [e for e in db.order_events(order) if e["event_type"] == "Trabajo comercial"]
    assert len(events) == 1
    details = json.loads(events[0]["data_json"])
    assert details["before"]["subtotal"] == 100
    assert details["after"]["subtotal"] == 120


def test_legacy_migration_preserves_order_and_backs_up(tmp_path):
    path = tmp_path / "orders.db"
    db = ImageDatabase(path)
    order = make_order(db)
    db.connection.execute("ALTER TABLE order_jobs DROP COLUMN distribution_policy")
    db.connection.execute("DELETE FROM schema_migrations WHERE version=2026102301")
    db.connection.commit()
    db.close()
    db = ImageDatabase(path, defer_automatic_maintenance=True)
    assert db.order_jobs(order)[0]["distribution_policy"] == "legacy"
    assert list((tmp_path / "backups" / "automatic").glob("*pre_order_distribution_policy*.db"))


def test_design_only_save_enforces_policy_and_rejects_mixed_units(tmp_path):
    db = ImageDatabase(tmp_path / "orders.db")
    order = make_order(db, "complete", assigned=5)
    designs = db.order_designs(order)
    values = dict(db.order(order))
    designs[0]["quantity"] = 4
    with pytest.raises(ValueError, match="distribución completa"):
        db.save_order_snapshot(order, values, designs)
    designs[0]["quantity"] = 5
    designs[0]["unit_kind"] = "sheet"
    with pytest.raises(ValueError, match="unidad"):
        db.save_order_snapshot(order, values, designs)
    assert db.order_designs(order)[0]["quantity"] == 5


def test_edit_without_policy_does_not_change_existing_choice(tmp_path):
    db = ImageDatabase(tmp_path / "orders.db")
    order = make_order(db, "partial")
    jobs = db.order_jobs(order)
    del jobs[0]["distribution_policy"]
    db.save_order_snapshot(order, dict(db.order(order)), db.order_designs(order), jobs)
    assert db.order_jobs(order)[0]["distribution_policy"] == "partial"
