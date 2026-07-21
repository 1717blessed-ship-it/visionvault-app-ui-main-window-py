import zipfile
from pathlib import Path
from app.ui.main_window import write_orders_zip


def test_write_orders_zip(tmp_path):
    orders = [
        {"id": 1, "client": "Acme", "created": "2026-07-01 10:00:00", "total": "$1,000.00", "paid": "$800.00", "pending": "$200.00", "status": "Cerrado"},
        {"id": 2, "client": "Beta", "created": "2026-07-02 11:00:00", "total": "$500.00", "paid": "$0.00", "pending": "$500.00", "status": "Nuevo"},
    ]
    lines_map = {
        1: [{"name": "Sticker A", "quantity": 2, "size": "5x5", "price": "$200"}],
        2: [{"name": "Sticker B", "quantity": 1, "size": "4x4", "price": "$100"}],
    }
    zip_path = tmp_path / "export.zip"
    write_orders_zip(orders, str(zip_path), order_lines_map=lines_map)
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path, 'r') as zf:
        names = zf.namelist()
    # Esperamos 4 archivos: order_1.csv, order_1_lines.csv, order_2.csv, order_2_lines.csv
    assert set(names) == {"order_1.csv", "order_1_lines.csv", "order_2.csv", "order_2_lines.csv"}
