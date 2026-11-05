import pytest

from app.database.database import ImageDatabase


def _order_values(db, order_id):
    values = dict(db.order(order_id))
    values["client"] = values.get("client_name") or values["client"]
    return values


def test_existing_job_keeps_updated_catalog_price_and_cost_snapshots(tmp_path):
    db = ImageDatabase(tmp_path / "orders.db")
    order_id = db.create_order_with_details("Cliente", jobs=[{
        "title": "Stickers", "material": "Vinilo blanco", "size": "5 cm",
        "quantity": 10, "unit_kind": "item", "subtotal": 100,
    }])
    job = db.order_jobs(order_id)[0]
    job.update({
        "product_id": 11, "variant_id": 22, "price_list_id": 33, "price_rule_id": 44,
        "unit_price_snapshot": 12.5, "fixed_price_snapshot": 25,
        "base_price_snapshot": 125, "suggested_price_snapshot": 140,
        "applied_price_snapshot": 135, "manual_price_snapshot": 135,
        "manual_override": True, "manual_override_reason": "Precio acordado",
        "price_source": "manual", "cost_mp": 30, "cost_mo": 20, "cost_cf": 10,
        "cost_total": 60, "productive_cost": 55, "commercial_cost_allocated": 5,
        "final_cost": 60, "productive_margin": 80, "final_margin": 75,
        "productive_classification": "rentable", "production_mode": "individual",
    })

    db.save_order_snapshot(order_id, _order_values(db, order_id), [], [job])
    saved = db.order_jobs(order_id)[0]

    for key in ("product_id", "variant_id", "price_list_id", "price_rule_id"):
        assert saved[key] == job[key]
    assert saved["manual_override"] == 1
    assert saved["manual_override_reason"] == "Precio acordado"
    assert saved["final_cost"] == 60
    assert saved["price_source"] == "manual"


def test_payment_cancellation_is_auditable_and_idempotency_prevents_duplicates(tmp_path):
    db = ImageDatabase(tmp_path / "orders.db")
    order_id = db.create_order_with_details("Cliente", jobs=[{
        "title": "Tarjetas", "quantity": 100, "unit_kind": "item", "subtotal": 500,
    }])
    db.register_order_payment(order_id, 200, "Transferencia", idempotency_key="mp-123")
    db.register_order_payment(order_id, 200, "Transferencia", idempotency_key="mp-123")
    assert len(db.order_payments(order_id)) == 1
    assert db.order_financials(order_id)["paid_amount"] == 200

    payment_id = db.order_payments(order_id)[0]["id"]
    db.cancel_order_payment(order_id, payment_id, "Transferencia revertida")

    history = db.order_payments(order_id)
    assert len(history) == 1
    assert history[0]["cancelled_at"]
    assert history[0]["cancellation_reason"] == "Transferencia revertida"
    assert db.order_financials(order_id)["paid_amount"] == 0
    with pytest.raises(ValueError, match="ya fue cancelado"):
        db.cancel_order_payment(order_id, payment_id)
