import tempfile
import unittest
from pathlib import Path

from app.database.database import ImageDatabase


class OrderFlowTests(unittest.TestCase):
    def test_order_concept_description_and_delivery_are_persisted(self):
        with tempfile.TemporaryDirectory() as folder:
            database = ImageDatabase(Path(folder) / "orders.db")
            try:
                order_id = database.create_order(
                    "Cliente de prueba",
                    order_date="2026-07-19",
                    status="Recibido",
                    delivery_date="2026-07-20",
                    observations="Observación inicial",
                    order_concept="Concepto inicial",
                    order_description="Descripción inicial",
                )

                order = database.order(order_id)
                self.assertEqual(order["order_concept"], "Concepto inicial")
                self.assertEqual(order["order_description"], "Descripción inicial")
                self.assertEqual(order["delivery_date"], "2026-07-20")

                database.save_order_snapshot(
                    order_id,
                    {
                        "client": "Cliente de prueba",
                        "whatsapp": "",
                        "status": "Esperando archivos",
                        "material": "",
                        "size": "",
                        "quantity": 2,
                        "price": 0,
                        "discount_percent": 0,
                        "extra_services": "",
                        "assigned_to": "",
                        "observations": "Observación actualizada",
                        "pending_reason": "",
                        "delivery_date": "2026-07-25",
                        "order_concept": "Concepto actualizado",
                        "order_description": "Descripción actualizada",
                    },
                    [],
                    [],
                )

                updated = database.order(order_id)
                self.assertEqual(updated["order_concept"], "Concepto actualizado")
                self.assertEqual(updated["order_description"], "Descripción actualizada")
                self.assertEqual(updated["delivery_date"], "2026-07-25")
            finally:
                database.close()


if __name__ == "__main__":
    unittest.main()
