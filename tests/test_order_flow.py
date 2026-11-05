import tempfile
import unittest
from pathlib import Path

from app.database.database import ImageDatabase


class OrderFlowTests(unittest.TestCase):
    def test_primary_job_can_be_deleted_without_being_restored_on_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "orders.db"
            database = ImageDatabase(path)
            try:
                order_id = database.create_order("Cliente")
                primary_job = database.order_jobs(order_id)[0]

                database.delete_order_job(order_id, primary_job["id"])

                self.assertEqual(database.order_jobs(order_id), [])
                order = database.order(order_id)
                self.assertEqual(order["budget_total"], 0)
                self.assertEqual(order["order_jobs_deleted"], 1)
            finally:
                database.close()

            reopened = ImageDatabase(path)
            try:
                self.assertEqual(reopened.order_jobs(order_id), [])
            finally:
                reopened.close()

    def test_archived_order_is_hidden_from_orders_and_pending_selector(self):
        with tempfile.TemporaryDirectory() as folder:
            database = ImageDatabase(Path(folder) / "orders.db")
            try:
                active_id = database.create_order("Cliente activo", status="Recibido")
                archived_id = database.create_order("Cliente archivado", status="Recibido")

                database.archive_order(archived_id)

                archived = database.connection.execute(
                    "SELECT status, is_archived FROM orders WHERE id = ?", (archived_id,)
                ).fetchone()
                self.assertEqual(archived["status"], "Archivado")
                self.assertEqual(archived["is_archived"], 1)
                self.assertEqual([row["id"] for row in database.orders()], [active_id])
                self.assertEqual([row["id"] for row in database.pending_orders()], [active_id])
            finally:
                database.close()

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

    def test_delivered_and_terminated_orders_are_closed_and_visible_in_completed_filter(self):
        with tempfile.TemporaryDirectory() as folder:
            database = ImageDatabase(Path(folder) / "orders.db")
            try:
                active_id = database.create_order("Activo", status="Recibido")
                delivered_id = database.create_order("Entregado", status="Recibido")
                terminated_id = database.create_order("Terminado", status="Recibido")
                from app.services.delivery_readiness import confirm_direct_source
                for oid, state in ((delivered_id, "Entregado"), (terminated_id, "Terminado")):
                    job = database.order_jobs(oid)[0]
                    confirm_direct_source(database.connection, job['id'], source='service', quantity=job['quantity'], reference='Servicio verificado', actor='Prueba')
                    database.update_order_status(oid, state)

                completed = database.orders(status=("Finalizado", "Entregado", "Terminado"))

                self.assertEqual({row["id"] for row in completed}, {delivered_id, terminated_id})
                self.assertEqual([row["id"] for row in database.pending_orders()], [active_id])
            finally:
                database.close()

    def test_delivering_an_urgent_order_clears_its_priority(self):
        with tempfile.TemporaryDirectory() as folder:
            database = ImageDatabase(Path(folder) / "orders.db")
            try:
                order_id = database.create_order(
                    "Pedido urgente",
                    status="Recibido",
                    print_priority=4,
                )

                from app.services.delivery_readiness import confirm_direct_source
                job = database.order_jobs(order_id)[0]
                confirm_direct_source(database.connection, job['id'], source='service', quantity=job['quantity'], reference='Servicio verificado', actor='Prueba')
                delivered = database.mark_order_delivered(order_id)
                stored = database.order(order_id)

                self.assertEqual(delivered["status"], "Entregado")
                self.assertEqual(stored["print_priority"], 0)
            finally:
                database.close()

    def test_status_change_to_delivered_clears_priority(self):
        with tempfile.TemporaryDirectory() as folder:
            database = ImageDatabase(Path(folder) / "orders.db")
            try:
                order_id = database.create_order(
                    "Pedido urgente",
                    status="Recibido",
                    print_priority=4,
                )

                from app.services.delivery_readiness import confirm_direct_source
                job = database.order_jobs(order_id)[0]
                confirm_direct_source(database.connection, job['id'], source='service', quantity=job['quantity'], reference='Servicio verificado', actor='Prueba')
                database.update_order_status(order_id, "Entregado")

                self.assertEqual(database.order(order_id)["print_priority"], 0)
            finally:
                database.close()

    def test_opening_database_normalizes_historical_delivered_priority(self):
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "orders.db"
            database = ImageDatabase(db_path)
            try:
                order_id = database.create_order("Pedido histórico", status="Recibido")
                # Emulate a record persisted before delivery guards existed.
                database.connection.execute("DROP TRIGGER guard_orders_total_delivery")
                database.connection.execute(
                    """UPDATE orders
                       SET status = 'Entregado', print_priority = 4
                       WHERE id = ?""",
                    (order_id,),
                )
                database.connection.commit()
            finally:
                database.close()

            reopened = ImageDatabase(db_path)
            try:
                self.assertEqual(reopened.order(order_id)["print_priority"], 0)
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
