"""Autenticación de vendedores previa al enlace y sesión persistente."""

from datetime import datetime, timedelta
from io import BytesIO
import json
import sqlite3
from unittest.mock import Mock

import pytest

from app.api.mobile_jobs import MobileJobsHandler
from app.events.event_bus import EventBus
from app.events.event_repository import EventRepository
from app.security.mobile_access import MobileAccessRepository
from app.security.mobile_users import (
    LOCKOUT_MINUTES,
    MAX_LOGIN_ATTEMPTS,
    MobileUserRepository,
)


@pytest.fixture
def auth_context():
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    events = EventRepository(connection)
    events.create_tables()
    users = MobileUserRepository(connection)
    access = MobileAccessRepository(connection)
    event_bus = EventBus(events)
    yield connection, events, users, access, event_bus
    connection.close()


def _handler(auth_context, body, *, authorization=""):
    _connection, events, users, access, event_bus = auth_context
    handler = MobileJobsHandler.__new__(MobileJobsHandler)
    handler.event_repo = events
    handler.event_bus = event_bus
    handler.mobile_users = users
    handler.access_control = access
    handler.headers = {"Content-Length": "0"}
    if authorization:
        handler.headers["Authorization"] = f"Bearer {authorization}"
    encoded = json.dumps(body).encode("utf-8")
    handler.headers["Content-Length"] = str(len(encoded))
    handler.rfile = BytesIO(encoded)
    handler.path = "/api/v1/mobile/auth/login"
    handler.client_address = ("192.168.1.40", 50000)
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    handler.wfile = Mock()
    handler.wfile.write = Mock()
    handler._response_body = b""
    handler.wfile.write.side_effect = lambda data: setattr(
        handler, "_response_body", handler._response_body + data
    )
    return handler


def _response_json(handler):
    return json.loads(handler._response_body.decode("utf-8"))


def test_password_is_hashed_and_never_stored_in_plaintext(auth_context):
    connection, _events, users, _access, _bus = auth_context
    users.create_user("maria", "María", "Ventas2026segura")

    row = connection.execute("SELECT * FROM mobile_users").fetchone()

    assert row["password_hash"] != "Ventas2026segura"
    assert "Ventas2026segura" not in tuple(str(value) for value in row)
    assert len(row["password_salt"]) == 32


def test_valid_credentials_return_single_use_link_token(auth_context):
    _connection, _events, users, _access, _bus = auth_context
    user = users.create_user("maria", "María", "Ventas2026segura")

    result = users.authenticate("MARIA", "Ventas2026segura")

    assert result.success is True
    assert result.user is not None
    assert result.user.id == user.id
    assert result.link_token
    assert users.validate_link_token(result.link_token) is not None
    assert users.claim_link_token(result.link_token) is not None
    assert users.claim_link_token(result.link_token) is None


def test_account_is_temporarily_locked_after_repeated_failures(auth_context):
    _connection, _events, users, _access, _bus = auth_context
    user = users.create_user("pedro", "Pedro", "Clave2026segura")

    for _ in range(MAX_LOGIN_ATTEMPTS):
        result = users.authenticate("pedro", "incorrecta-2026")

    locked = users.get_user(user.id)
    assert result.success is False
    assert "bloqueada" in result.message.lower()
    assert locked is not None
    assert datetime.fromisoformat(locked.locked_until) > datetime.now()
    assert datetime.fromisoformat(locked.locked_until) <= datetime.now() + timedelta(
        minutes=LOCKOUT_MINUTES, seconds=2
    )


def test_disabling_user_revokes_link_and_device_sessions(auth_context):
    _connection, events, users, _access, _bus = auth_context
    user = users.create_user("luz", "Luz", "Clave2026segura")
    login = users.authenticate("luz", "Clave2026segura")
    claimed = users.claim_link_token(login.link_token)
    device_id, session_token = events.register_device(
        "fcm-luz", "android", "Teléfono Luz", user_id=claimed.id
    )

    users.set_active(user.id, False)

    assert events.validate_session_token(session_token) is None
    device = events.conn.execute(
        "SELECT active, session_token_hash FROM mobile_devices WHERE id = ?",
        (device_id,),
    ).fetchone()
    assert device["active"] == 0
    assert device["session_token_hash"] is None


def test_password_reset_revokes_existing_device(auth_context):
    _connection, events, users, _access, _bus = auth_context
    user = users.create_user("ana", "Ana", "Clave2026segura")
    _device_id, token = events.register_device(
        "fcm-ana", "android", "Teléfono Ana", user_id=user.id
    )

    users.reset_password(user.id, "Nueva2026segura")

    assert events.validate_session_token(token) is None
    assert users.authenticate("ana", "Clave2026segura").success is False
    assert users.authenticate("ana", "Nueva2026segura").success is True


def test_session_expiration_slides_forward_while_used(auth_context):
    connection, events, users, _access, _bus = auth_context
    user = users.create_user("sol", "Sol", "Clave2026segura")
    device_id, token = events.register_device(
        "fcm-sol", "android", "Teléfono Sol", user_id=user.id
    )
    connection.execute(
        "UPDATE mobile_devices SET session_expires_at = ? WHERE id = ?",
        ((datetime.now() + timedelta(days=1)).isoformat(timespec="seconds"), device_id),
    )
    connection.commit()

    device = events.validate_session_token(token)
    renewed = connection.execute(
        "SELECT session_expires_at FROM mobile_devices WHERE id = ?", (device_id,)
    ).fetchone()[0]

    assert device["username"] == "sol"
    assert datetime.fromisoformat(renewed) > datetime.now() + timedelta(days=89)


def test_reassigning_same_phone_creates_new_isolated_device(auth_context):
    connection, events, users, _access, _bus = auth_context
    maria = users.create_user("maria", "María", "Ventas2026segura")
    pedro = users.create_user("pedro", "Pedro", "Ventas2026segura")
    maria_device, maria_token = events.register_device(
        "shared-fcm-token",
        "android",
        "Teléfono compartido",
        user_id=maria.id,
    )

    pedro_device, pedro_token = events.register_device(
        "shared-fcm-token",
        "android",
        "Teléfono compartido",
        user_id=pedro.id,
    )

    assert pedro_device != maria_device
    assert events.validate_session_token(maria_token) is None
    assert events.validate_session_token(pedro_token)["user_id"] == pedro.id
    rows = connection.execute(
        "SELECT id, user_id, push_token, active FROM mobile_devices ORDER BY id"
    ).fetchall()
    assert rows[0]["user_id"] == maria.id
    assert rows[0]["active"] == 0
    assert rows[0]["push_token"].startswith("revoked:")
    assert rows[1]["user_id"] == pedro.id
    assert rows[1]["push_token"] == "shared-fcm-token"


def test_login_endpoint_returns_temporary_authorization(auth_context):
    _connection, _events, users, _access, _bus = auth_context
    users.create_user("maria", "María", "Ventas2026segura")
    handler = _handler(
        auth_context,
        {"username": "maria", "password": "Ventas2026segura"},
    )

    handler._login_mobile_user()
    data = _response_json(handler)

    handler.send_response.assert_called_once_with(200)
    assert data["success"] is True
    assert data["link_token"]
    assert data["user"]["display_name"] == "María"


def test_login_endpoint_rejects_plain_http_from_public_network(auth_context):
    _connection, _events, users, _access, _bus = auth_context
    users.create_user("maria", "María", "Ventas2026segura")
    handler = _handler(
        auth_context,
        {"username": "maria", "password": "Ventas2026segura"},
    )
    handler.client_address = ("8.8.8.8", 50000)

    handler._login_mobile_user()

    handler.send_response.assert_called_once_with(426)
    assert "HTTPS" in _response_json(handler)["error"]


def test_credentials_transport_accepts_private_vpn_address(auth_context):
    handler = _handler(auth_context, {})
    handler.client_address = ("100.100.20.15", 50000)

    assert handler._allows_sensitive_credentials() is True

    handler.client_address = ("198.51.100.40", 50000)
    assert handler._allows_sensitive_credentials() is False


def test_pairing_endpoint_requires_login_then_links_user(auth_context):
    connection, events, users, _access, _bus = auth_context
    user = users.create_user("maria", "María", "Ventas2026segura")
    code = events.create_pairing_code()

    unauthorized = _handler(
        auth_context,
        {"code": code, "push_token": "fcm-no-auth"},
    )
    unauthorized.path = "/api/pair/validate"
    unauthorized._pair_device()
    unauthorized.send_response.assert_called_once_with(401)

    login = users.authenticate("maria", "Ventas2026segura")
    handler = _handler(
        auth_context,
        {
            "code": code,
            "push_token": "fcm-auth",
            "platform": "android",
            "device_name": "Teléfono María",
        },
        authorization=login.link_token,
    )
    handler.path = "/api/pair/validate"
    handler._pair_device()
    data = _response_json(handler)

    handler.send_response.assert_called_once_with(200)
    assert data["session_token"]
    device = connection.execute(
        "SELECT user_id FROM mobile_devices WHERE id = ?", (data["device_id"],)
    ).fetchone()
    assert device["user_id"] == user.id
