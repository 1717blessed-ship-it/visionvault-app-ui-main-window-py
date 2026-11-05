from __future__ import annotations

import sqlite3
from datetime import datetime

from app.database.database import ImageDatabase
from app.notifications.notification_service import NotificationService
from app.planchas.editor import PlanchaEditor
from app.planchas.model import PlanchaItem, PlanchaProject
from app.stickers.editor import AreaSelectionEditor, ProtectionZoneEditor
from app.ui.gallery import Gallery
from app.ui.module_registry import ModuleRegistry


class MovingCanvas:
    def __init__(self):
        self.moves = []

    def move(self, tag, delta_x, delta_y):
        self.moves.append((tag, delta_x, delta_y))


class SelectionCanvas:
    def __init__(self):
        self.created = []
        self.updated = []

    def create_rectangle(self, *coordinates, **options):
        self.created.append((coordinates, options))
        return 17

    def coords(self, item_id, *coordinates):
        self.updated.append((item_id, coordinates))


class EditorCanvas(SelectionCanvas):
    def __init__(self):
        super().__init__()
        self.polygons = []
        self.deleted = []

    def create_polygon(self, *coordinates, **options):
        self.polygons.append((coordinates, options))
        return 11

    def delete(self, item_id):
        self.deleted.append(item_id)


def test_plancha_drag_moves_only_the_active_canvas_item():
    editor = PlanchaEditor.__new__(PlanchaEditor)
    item = PlanchaItem("uno.png", "Uno", 4.0, 3.0, x_cm=0.15, y_cm=0.15)
    editor.project = PlanchaProject([item])
    editor.zoom = 1.0
    editor.show_hitboxes = False
    editor.selected_id = item.item_id
    editor.selected_ids = {item.item_id}
    editor.drag_offset = (0, 0)
    editor.drag_band_index = 0
    editor.area_selection_start = None
    editor.canvas_event_position = lambda event: (event.x, event.y)
    editor.canvas = MovingCanvas()
    full_renders = []
    editor.request_render = lambda: full_renders.append(True)

    target_x = 25 + editor.cm_to_px(2.0)
    target_y = 25 + editor.cm_to_px(1.0)
    editor.drag_item(type("Event", (), {"x": target_x, "y": target_y})())

    assert editor.canvas.moves
    assert editor.canvas.moves[-1][0] == item.item_id
    assert full_renders == []


def test_gallery_selection_reuses_one_canvas_rectangle():
    gallery = Gallery.__new__(Gallery)
    gallery._band_start = (10.0, 20.0)
    gallery._band_dragging = True
    gallery._band_rect = None
    gallery.canvas = SelectionCanvas()
    points = iter(((40.0, 50.0), (45.0, 55.0)))
    gallery._band_coords = lambda _event: next(points)

    gallery._band_motion(object())
    gallery._band_motion(object())

    assert len(gallery.canvas.created) == 1
    assert gallery.canvas.updated == [(17, (10.0, 20.0, 45.0, 55.0))]


def test_responsive_gallery_wraps_items_that_do_not_fit_in_one_row():
    gallery = Gallery.__new__(Gallery)
    gallery.responsive_columns = True
    gallery.canvas = type("Canvas", (), {"winfo_width": lambda self: 540})()

    assert gallery.grid_columns() == 6
    assert gallery.position_for(6) == (1, 0, "n")


def test_standard_gallery_keeps_the_existing_fixed_column_contract():
    gallery = Gallery.__new__(Gallery)
    gallery.responsive_columns = False
    gallery.canvas = type("Canvas", (), {"winfo_width": lambda self: 540})()

    assert gallery.grid_columns() == Gallery.FIXED_COLUMNS
    assert gallery.position_for(9) == (0, 9, "n")


def test_area_editor_reuses_selection_and_handle_items():
    editor = AreaSelectionEditor.__new__(AreaSelectionEditor)
    editor.selection_box = (10, 20, 100, 120)
    editor.display_offset = (0, 0)
    editor.display_scale = 1.0
    editor.selection_angle = type("Angle", (), {"get": lambda self: 0.0})()
    editor.selection_item = None
    editor.selection_handle_items = []
    editor.canvas = EditorCanvas()

    editor._draw_selection()
    editor.selection_box = (20, 30, 110, 130)
    editor._draw_selection()

    assert len(editor.canvas.polygons) == 1
    assert len(editor.canvas.created) == 4
    assert len(editor.canvas.updated) == 5


def test_protection_zone_drag_reuses_live_rectangle():
    editor = ProtectionZoneEditor.__new__(ProtectionZoneEditor)
    editor._drag_start = (1, 2)
    editor._live_rect = None
    editor._canvas = SelectionCanvas()
    editor._canvas_to_image = lambda x, y: (x, y)
    editor._image_to_canvas = lambda x, y: (x, y)

    editor._on_drag(type("Event", (), {"x": 10, "y": 20})())
    editor._on_drag(type("Event", (), {"x": 15, "y": 25})())

    assert len(editor._canvas.created) == 1
    assert editor._canvas.updated == [(17, (1, 2, 15, 25))]


def test_module_status_keeps_failure_available_for_review_and_retry():
    attempts = []
    registry = ModuleRegistry()

    def factory():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("conexión temporal")
        return "conectado"

    registry.register("ventas", factory)
    try:
        registry.ensure("ventas")
    except RuntimeError:
        pass

    assert registry.statuses()["ventas"]["error"] == "conexión temporal"
    assert registry.ensure("ventas") == "conectado"
    assert registry.statuses()["ventas"]["error"] == ""


def test_database_maintenance_can_run_after_initial_connection(tmp_path):
    path = tmp_path / "deferred.db"
    ImageDatabase(path).close()

    database = ImageDatabase(path, defer_automatic_maintenance=True)
    assert database.automatic_maintenance_pending is True
    assert not list((tmp_path / "backups" / "automatic").glob("visionvault_daily_*.db"))

    database.run_automatic_maintenance()

    assert database.automatic_maintenance_pending is False
    assert len(list((tmp_path / "backups" / "automatic").glob("visionvault_daily_*.db"))) == 1
    database.close()


def _notification_service_with_quiet_settings(*, bypass_errors: bool = True):
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE app_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL)"
    )
    connection.executemany(
        "INSERT INTO app_settings(setting_key, setting_value) VALUES(?, ?)",
        [
            ("notifications.quiet_from", "23:00"),
            ("notifications.quiet_to", "07:00"),
            ("notifications.quiet_errors_bypass", "1" if bypass_errors else "0"),
        ],
    )
    return NotificationService(type("Repo", (), {"conn": connection})()), connection


def test_notification_quiet_hours_cover_cross_midnight_and_release_during_day():
    service, connection = _notification_service_with_quiet_settings()
    normal = {"event_type": "order.created"}

    assert service._should_pause_for_quiet_hours(normal, datetime(2026, 8, 20, 23, 30)) is True
    assert service._should_pause_for_quiet_hours(normal, datetime(2026, 8, 21, 6, 30)) is True
    assert service._should_pause_for_quiet_hours(normal, datetime(2026, 8, 21, 12, 0)) is False
    connection.close()


def test_production_error_can_bypass_quiet_hours_when_enabled():
    service, connection = _notification_service_with_quiet_settings(bypass_errors=True)
    error = {"event_type": "production.error"}

    assert service._should_pause_for_quiet_hours(error, datetime(2026, 8, 20, 23, 30)) is False
    connection.close()


def test_quiet_worker_retains_pending_message_without_sending_it():
    class PendingRepo:
        def pending_outbox(self, limit):
            assert limit == 10
            return [{"id": 41, "event_type": "order.created"}]

    service = NotificationService(PendingRepo())
    sent = []
    service._should_pause_for_quiet_hours = lambda _item: True
    service._send_one = sent.append

    service._process_outbox()

    assert sent == []
