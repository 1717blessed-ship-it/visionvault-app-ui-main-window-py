import json
import sqlite3
from io import BytesIO
from types import SimpleNamespace

from app.api.mobile_jobs import MobileJobsHandler


class _Response:
    def __init__(self) -> None:
        self.status = 0
        self.headers: dict[str, str] = {}
        self.body = bytearray()

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, name: str, value: str) -> None:
        self.headers[name] = value

    def end_headers(self) -> None:
        pass

    def write(self, payload: bytes) -> None:
        self.body.extend(payload)


def _handler(conn: sqlite3.Connection, payload: dict) -> tuple[MobileJobsHandler, _Response]:
    handler = MobileJobsHandler.__new__(MobileJobsHandler)
    handler.event_repo = SimpleNamespace(conn=conn)
    body = json.dumps(payload).encode("utf-8")
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = BytesIO(body)
    response = _Response()
    handler.send_response = response.send_response
    handler.send_header = response.send_header
    handler.end_headers = response.end_headers
    handler.wfile = SimpleNamespace(write=response.write)
    return handler, response


def _payload(*, version: int = 0, title: str = "Cliente Centro", force: bool = False) -> dict:
    return {
        "client_uuid": "visit-server-1",
        "title": title,
        "latitude": -27.481,
        "longitude": -55.117,
        "status": "pending",
        "created_at": "2026-08-12T09:00:00Z",
        "server_version": version,
        "force": force,
        "zone": "Centro",
        "result": "Volver la próxima semana",
    }


def test_visit_version_conflict_and_force_resolution():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    device = {"id": 1, "user_id": 77}

    handler, response = _handler(conn, _payload())
    handler._upsert_visit(device)
    assert response.status == 200
    assert json.loads(response.body)["visit"]["version"] == 1

    handler, response = _handler(conn, _payload(title="Cambio atrasado"))
    handler._upsert_visit(device)
    assert response.status == 409
    assert json.loads(response.body)["error"] == "visit_conflict"

    handler, response = _handler(
        conn, _payload(version=1, title="Cambio conservado", force=True)
    )
    handler._upsert_visit(device)
    saved = json.loads(response.body)["visit"]
    assert response.status == 200
    assert saved["title"] == "Cambio conservado"
    assert saved["version"] == 2


def test_history_is_shared_between_two_devices_of_the_same_user():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    first_device = {"id": 1, "user_id": 77}
    second_device = {"id": 2, "user_id": 77}
    event = {
        "event_uuid": "history-server-1",
        "client_uuid": "visit-server-1",
        "action": "Visita realizada",
        "note": "Pedido confirmado",
        "created_at": "2026-08-12T10:00:00Z",
    }

    handler, response = _handler(conn, event)
    handler._upsert_visit_history(first_device)
    assert response.status == 200

    handler, response = _handler(conn, {})
    handler._list_visit_history(second_device)
    history = json.loads(response.body)["history"]
    assert response.status == 200
    assert len(history) == 1
    assert history[0]["event_uuid"] == "history-server-1"
