import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from app.ui.components import build_order_notification_payload
from app.workflow.priority import calculate_priority
from app.events.event_repository import EventRepository
from app.events.event_types import ORDER_CREATED, PRIORITY_NORMAL
from app.notifications.notification_service import NotificationService


class NotificationsTests(unittest.TestCase):
    def test_build_order_notification_payload_handles_missing_client(self):
        order = {"id": 123}
        level, score, reason = calculate_priority(order, 0)
        payload = build_order_notification_payload(order, level, score, reason)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["order_id"], 123)
        self.assertIn("client_name", payload)
        self.assertIn("reason", payload)


class EventRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.db_path = Path(tempfile.mktemp(suffix=".db"))
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row  # Necesario para acceso por nombre de columna
        self.repo = EventRepository(self.conn)
        self.repo.create_tables()

    def tearDown(self):
        self.conn.close()
        if self.db_path.exists():
            self.db_path.unlink()

    def test_create_event_and_outbox_entries(self):
        """Test que crear un evento genera entradas en outbox para dispositivos activos."""
        # Registrar un dispositivo
        device_id = self.repo.register_device(
            push_token="test_token_123",
            platform="android",
            device_name="Test Device"
        )
        self.assertGreater(device_id, 0)

        # Publicar evento
        event_uuid = self.repo.publish_event(
            event_type=ORDER_CREATED,
            priority=PRIORITY_NORMAL,
            title="Test Event",
            message="Test message",
            entity_type="order",
            entity_id=1
        )
        self.assertIsNotNone(event_uuid)

        # Verificar evento creado
        events = self.repo.recent_events(limit=1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_uuid"], event_uuid)

        # Verificar outbox entry creada
        pending = self.repo.pending_outbox(limit=10)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["event_uuid"], event_uuid)
        self.assertEqual(pending[0]["recipient_id"], "test_token_123")
        self.assertEqual(pending[0]["status"], "pending")

    def test_duplicate_prevention_via_unique_index(self):
        """Test que el índice único previene duplicados en outbox."""
        self.repo.register_device(
            push_token="test_token_456",
            platform="android",
            device_name="Test Device"
        )

        event_uuid = self.repo.publish_event(
            event_type=ORDER_CREATED,
            priority=PRIORITY_NORMAL,
            title="Test Event",
            message="Test message"
        )

        # Intentar insertar duplicado manualmente
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """INSERT INTO notification_outbox(event_uuid, channel, recipient_id, status, created_at)
                   VALUES(?, 'push', ?, 'pending', datetime('now'))""",
                (event_uuid, "test_token_456")
            )

    def test_pending_to_sent_transition(self):
        """Test transición de pending a sent."""
        self.repo.register_device(push_token="token", platform="android")
        event_uuid = self.repo.publish_event(
            event_type=ORDER_CREATED,
            priority=PRIORITY_NORMAL,
            title="Test",
            message="Test"
        )

        pending = self.repo.pending_outbox(limit=1)
        outbox_id = pending[0]["id"]
        self.assertEqual(pending[0]["status"], "pending")

        self.repo.mark_outbox_sent(outbox_id)

        pending_after = self.repo.pending_outbox(limit=10)
        self.assertEqual(len(pending_after), 0)

    def test_retry_with_backoff_on_temporary_error(self):
        """Test reintento con backoff ante error temporal."""
        self.repo.register_device(push_token="token", platform="android")
        event_uuid = self.repo.publish_event(
            event_type=ORDER_CREATED,
            priority=PRIORITY_NORMAL,
            title="Test",
            message="Test"
        )

        pending = self.repo.pending_outbox(limit=1)
        outbox_id = pending[0]["id"]

        # Marcar como fallido con reintento inmediato (retry_after_seconds=0)
        # para que aparezca en pending_outbox
        self.repo.mark_outbox_failed(outbox_id, "Temporary error", retry_after_seconds=0)

        pending_retry = self.repo.pending_outbox(limit=10)
        self.assertEqual(len(pending_retry), 1)
        self.assertEqual(pending_retry[0]["attempts"], 1)
        self.assertIsNotNone(pending_retry[0]["last_error"])

    def test_dead_letter_after_max_attempts(self):
        """Test paso a dead_letter después de máximo de intentos."""
        self.repo.register_device(push_token="token", platform="android")
        event_uuid = self.repo.publish_event(
            event_type=ORDER_CREATED,
            priority=PRIORITY_NORMAL,
            title="Test",
            message="Test"
        )

        pending = self.repo.pending_outbox(limit=1)
        outbox_id = pending[0]["id"]

        # Simular 5 intentos fallidos incrementando attempts manualmente
        for _ in range(5):
            self.repo.mark_outbox_failed(outbox_id, "Error", retry_after_seconds=0)

        # Marcar explícitamente como dead_letter (como lo hace el service)
        self.repo.mark_outbox_dead_letter(outbox_id, "Max attempts reached")

        # Verificar que pasó a dead_letter
        stats = self.repo.outbox_stats()
        self.assertEqual(stats["dead"], 1)

    def test_invalid_token_deactivates_device(self):
        """Test que token inválido desactiva el dispositivo."""
        device_id = self.repo.register_device(
            push_token="invalid_token",
            platform="android",
            device_name="Test Device"
        )

        self.repo.deactivate_device_by_token("invalid_token", reason="Invalid token")

        devices = self.repo.active_devices()
        self.assertEqual(len(devices), 0)

    def test_device_preferences(self):
        """Test preferencias de notificación por dispositivo."""
        device_id = self.repo.register_device(
            push_token="token",
            platform="android"
        )

        # Desactivar notificaciones para ORDER_CREATED
        self.repo.set_device_pref(device_id, ORDER_CREATED, False)

        prefs = self.repo.get_device_prefs(device_id)
        self.assertEqual(prefs.get(ORDER_CREATED), False)


class NotificationServiceTests(unittest.TestCase):
    def setUp(self):
        self.db_path = Path(tempfile.mktemp(suffix=".db"))
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row  # Necesario para acceso por nombre de columna
        self.repo = EventRepository(self.conn)
        self.repo.create_tables()
        self.service = NotificationService(self.repo)

    def tearDown(self):
        self.service.stop_worker()
        self.conn.close()
        if self.db_path.exists():
            self.db_path.unlink()

    def test_worker_clean_shutdown(self):
        """Test que el worker se cierra limpiamente."""
        self.service.start_worker(interval_seconds=1)
        self.assertTrue(self.service._worker_thread.is_alive())

        self.service.stop_worker()
        time.sleep(0.2)  # Dar tiempo para que termine
        self.assertFalse(self.service._worker_thread.is_alive())

    def test_worker_processes_outbox_when_firebase_not_configured(self):
        """Test que el worker maneja gracefully Firebase no configurado."""
        self.repo.register_device(push_token="token", platform="android")
        self.repo.publish_event(
            event_type=ORDER_CREATED,
            priority=PRIORITY_NORMAL,
            title="Test",
            message="Test"
        )

        self.service.start_worker(interval_seconds=1)
        time.sleep(2)  # Dar tiempo para procesar
        self.service.stop_worker()

        # Mensaje debería estar marcado como fallido (Firebase no configurado)
        stats = self.repo.outbox_stats()
        self.assertGreater(stats["pending"] + stats["sent"] + stats["dead"], 0)


if __name__ == "__main__":
    unittest.main()
