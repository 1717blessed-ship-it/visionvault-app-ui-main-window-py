from app.database.database import ImageDatabase


def test_orders_for_month_returns_orders_in_selected_month(tmp_path):
    db_path = tmp_path / "orders_for_month.db"
    db = ImageDatabase(db_path)

    db.create_order("Ana", order_date="2026-07-05", price=100, quantity=1, status="Finalizado")
    db.create_order("Luis", order_date="2026-08-10", price=200, quantity=1, status="Finalizado")

    orders = db.orders_for_month("2026-07")

    assert len(orders) == 1
    assert orders[0]["client"] == "Ana"


def test_sales_statistics_aggregates_budget_paid_and_pending(tmp_path):
    db_path = tmp_path / "sales_stats.db"
    db = ImageDatabase(db_path)

    order_id = db.create_order(
        "María",
        order_date="2026-07-03",
        price=1000,
        quantity=1,
        material="Vinilo",
        size="10cm",
        status="Finalizado",
    )
    db.register_order_payment(order_id, 300, method="Efectivo")

    order_id_2 = db.create_order(
        "Juan",
        order_date="2026-07-14",
        price=500,
        quantity=1,
        material="Vinilo",
        size="10cm",
        status="Finalizado",
    )
    db.register_order_payment(order_id_2, 500, method="Transferencia")

    stats = db.sales_statistics("2026-07")

    assert stats["total_orders"] == 2
    assert stats["budget_total"] == 1500.0
    assert stats["paid_amount"] == 800.0
    assert stats["pending_amount"] == 700.0
    assert stats["collection_rate"] == 53.3
    assert stats["prev_month"] == "2026-06"
    assert stats["prev_budget_total"] == 0.0
    assert stats["budget_delta"] == 1500.0
    assert stats["budget_delta_pct"] == 0.0
    assert stats["paid_delta"] == 800.0
    assert stats["paid_delta_pct"] == 0.0
    assert stats["paid_orders"] == 1
    assert stats["partial_orders"] == 1
    assert stats["pending_orders"] == 0
