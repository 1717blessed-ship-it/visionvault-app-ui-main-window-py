from app.database.database import ImageDatabase


def test_sales_time_series_daily_aggregation(tmp_path):
    db_path = tmp_path / "sales_series.db"
    db = ImageDatabase(db_path)

    # Crear pedidos en distintos días
    id1 = db.create_order("A", order_date="2026-07-01", price=100, quantity=1, status="Finalizado")
    id2 = db.create_order("B", order_date="2026-07-02", price=200, quantity=1, status="Finalizado")
    id3 = db.create_order("C", order_date="2026-07-15", price=300, quantity=1, status="Finalizado")

    # Registrar pagos en fechas específicas
    # pago parcial el día 1
    db.register_order_payment(id1, 50, method="Efectivo")
    # pago el día 2
    db.register_order_payment(id2, 200, method="Transferencia")
    # pago el día 20 (fuera de la fecha de pedido, pero dentro del mes)
    db.register_order_payment(id3, 300, method="Efectivo")

    # Ajustar las fechas de los pagos para simular pagos en días específicos
    db.connection.execute("UPDATE order_payments SET paid_at = ?, created_at = ? WHERE order_id = ? AND amount = ?",
                          ("2026-07-01T10:00:00", "2026-07-01T10:00:00", id1, 50))
    db.connection.execute("UPDATE order_payments SET paid_at = ?, created_at = ? WHERE order_id = ? AND amount = ?",
                          ("2026-07-02T11:00:00", "2026-07-02T11:00:00", id2, 200))
    db.connection.execute("UPDATE order_payments SET paid_at = ?, created_at = ? WHERE order_id = ? AND amount = ?",
                          ("2026-07-20T09:00:00", "2026-07-20T09:00:00", id3, 300))
    db.connection.commit()

    series = db.sales_time_series("2026-07")
    # Julio tiene 31 días
    assert len(series) == 31
    day1 = next(item for item in series if item["date"] == "2026-07-01")
    assert day1["budget"] == 100.0
    assert day1["paid"] == 50.0
    day2 = next(item for item in series if item["date"] == "2026-07-02")
    assert day2["budget"] == 200.0
    assert day2["paid"] == 200.0
    day15 = next(item for item in series if item["date"] == "2026-07-15")
    assert day15["budget"] == 300.0
    # payment recorded on day 20
    day20 = next(item for item in series if item["date"] == "2026-07-20")
    assert day20["paid"] == 300.0
