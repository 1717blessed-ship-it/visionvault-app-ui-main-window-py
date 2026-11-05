"""Abre el historial real de Pedidos con datos ficticios en una base aislada."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ui.main_window import VisionVaultApp


def main():
    folder = ROOT / "artifacts" / "orders-sprint2-preview"
    folder.mkdir(parents=True, exist_ok=True)
    app = VisionVaultApp(database_path=folder / "preview.db", isolated_database=True)
    db = app.database
    orders = db.orders()
    if orders:
        order_id = orders[0]["id"]
    else:
        order_id = db.create_order_with_details("Cliente demostración Sprint 2", jobs=[{
            "title": "Stickers personalizados", "material": "Vinilo blanco", "size": "5 cm",
            "quantity": 100, "unit_kind": "item", "distribution_policy": "partial", "subtotal": 40000,
        }])
        db.register_order_payment(order_id, 10000, "Transferencia", "Seña confirmada", "demo-active")
        db.register_order_payment(order_id, 5000, "Efectivo", "Corrección de caja", "demo-cancelled")
        db.cancel_order_payment(order_id, db.order_payments(order_id)[0]["id"], "Ingreso registrado por error")
    def show():
        app.open_order_workspace(order_id)
        app.show_order_payments(order_id)
    app.after(5000, show)
    app.mainloop()


if __name__ == "__main__":
    main()
