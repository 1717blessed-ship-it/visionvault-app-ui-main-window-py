import csv
from app.ui.main_window import write_orders_csv


def test_write_orders_csv(tmp_path):
    orders = [
        {"id": 1, "client": "Acme", "created": "2026-07-01 10:00:00", "total": "$1,000.00", "paid": "$800.00", "pending": "$200.00", "status": "Cerrado"},
        {"id": 2, "client": "Beta", "created": "2026-07-02 11:00:00", "total": "$500.00", "paid": "$0.00", "pending": "$500.00", "status": "Nuevo", "products": "Sticker A x2, Sticker B x1"},
    ]
    path = tmp_path / "export.csv"
    write_orders_csv(orders, str(path))
    with open(path, newline='', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    assert len(rows) == 2
    assert rows[0]["client"] == "Acme"
    assert rows[1]["status"] == "Nuevo"
    assert "products" in rows[1]
    assert rows[1]["products"] == "Sticker A x2, Sticker B x1"


def test_write_order_lines_csv(tmp_path):
    lines = [
        {"name": "Sticker A", "quantity": 2, "size": "5x5", "price": "$200"},
        {"name": "Sticker B", "quantity": 1, "size": "4x4", "price": "$100"},
    ]
    path = tmp_path / "lines.csv"
    from app.ui.main_window import write_order_lines_csv
    write_order_lines_csv(lines, str(path))
    with open(path, newline='', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    assert len(rows) == 2
    assert rows[0]["name"] == "Sticker A"
    assert rows[1]["price"] == "$100"
