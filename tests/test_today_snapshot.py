from pathlib import Path

from app.database.database import ImageDatabase
from app.services.stock_cost_price_service import StockCostPriceService
from app.workflow.today import operational_snapshot


def test_snapshot_collects_operational_signals(tmp_path: Path):
    db = ImageDatabase(tmp_path / "today.db")
    db.create_order("Ana", delivery_date="2026-01-01", jobs=[{"title": "Stickers", "subtotal": 1000}])
    stock = StockCostPriceService(db.connection)
    stock.create_material(name="Vinilo", unit="m", physical_stock=1, min_stock=2)

    snapshot = operational_snapshot(db)
    assert snapshot["metrics"]["due_orders"] == 1
    assert snapshot["metrics"]["pending_payments"] == 1
    assert snapshot["metrics"]["low_stock"] == 1
