"""Pruebas de la whitelist y su persistencia de seguridad."""

import sqlite3

import pytest

from app.api.mobile_jobs import MobileJobsHandler, _get_client_ip
from app.security.mobile_access import MobileAccessRepository, normalize_ip_rule


@pytest.fixture
def access_control():
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    repository = MobileAccessRepository(connection)
    yield repository
    connection.close()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("203.0.113.8", "203.0.113.8"),
        ("192.168.1.44/24", "192.168.1.0/24"),
        ("2001:db8::8", "2001:db8::8"),
        ("2001:db8::8/48", "2001:db8::/48"),
    ],
)
def test_normalize_ip_rule(raw, expected):
    assert normalize_ip_rule(raw) == expected


def test_invalid_rule_is_rejected():
    with pytest.raises(ValueError, match="no es válida"):
        normalize_ip_rule("not-an-ip")


def test_client_ip_comes_from_socket_not_spoofable_proxy_headers():
    request = type(
        "Request",
        (),
        {
            "client_address": ("198.51.100.17", 54321),
            "headers": {
                "X-Forwarded-For": "203.0.113.99",
                "X-Real-IP": "203.0.113.100",
            },
        },
    )()

    assert _get_client_ip(request) == "198.51.100.17"


def test_security_headers_replace_obsolete_xss_header_and_gate_hsts():
    response = type(
        "Response",
        (),
        {
            "connection": object(),
            "headers_sent": {},
            "send_header": lambda self, name, value: self.headers_sent.__setitem__(
                name, value
            ),
        },
    )()

    MobileJobsHandler._send_security_headers(response)

    assert response.headers_sent["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" in response.headers_sent
    assert "X-XSS-Protection" not in response.headers_sent
    assert "Strict-Transport-Security" not in response.headers_sent


def test_disabled_whitelist_allows_any_valid_or_invalid_source(access_control):
    assert access_control.enabled is False
    assert access_control.is_allowed("198.51.100.22", "/api/test") is True
    assert access_control.is_allowed("not-an-ip", "/api/test") is True


def test_cidr_matches_hosts_inside_network(access_control):
    rule = access_control.add_rule("192.168.50.19/24", "Taller")
    access_control.set_enabled(True)

    assert rule.ip_address == "192.168.50.0/24"
    assert access_control.is_allowed("192.168.50.240", "/api/jobs") is True
    assert access_control.is_allowed("192.168.51.1", "/api/jobs") is False

    matched = access_control.get_rule(rule.id)
    assert matched is not None
    assert matched.last_matched_at


def test_ipv6_cidr_is_supported(access_control):
    access_control.add_rule("2001:db8:10::/48", "IPv6 móvil")
    access_control.set_enabled(True)

    assert access_control.is_allowed("2001:db8:10::abcd") is True
    assert access_control.is_allowed("2001:db8:11::1") is False


def test_enabled_empty_whitelist_fails_closed(access_control):
    access_control.connection.execute(
        "UPDATE app_settings SET setting_value = 'true' "
        "WHERE setting_key = 'mobile_api.ip_whitelist_enabled'"
    )
    access_control.connection.commit()
    access_control.reload()

    assert access_control.enabled is True
    assert access_control.active_rule_count == 0
    assert access_control.is_allowed("127.0.0.1") is False


def test_cannot_enable_without_active_rule(access_control):
    with pytest.raises(ValueError, match="al menos una"):
        access_control.set_enabled(True)


def test_cannot_remove_or_disable_last_active_rule(access_control):
    rule = access_control.add_rule("203.0.113.18", "Teléfono")
    access_control.set_enabled(True)

    with pytest.raises(ValueError, match="última regla"):
        access_control.set_rule_active(rule.id, False)
    with pytest.raises(ValueError, match="última regla"):
        access_control.delete_rule(rule.id)


def test_duplicate_normalized_network_is_rejected(access_control):
    access_control.add_rule("192.168.90.10/24", "Primera")

    with pytest.raises(ValueError, match="ya está"):
        access_control.add_rule("192.168.90.200/24", "Duplicada")


def test_deleted_default_rule_is_not_recreated(access_control):
    localhost = next(
        rule for rule in access_control.list_rules() if rule.ip_address == "127.0.0.1"
    )
    access_control.delete_rule(localhost.id)

    reloaded_repository = MobileAccessRepository(access_control.connection)

    assert all(
        rule.ip_address != "127.0.0.1"
        for rule in reloaded_repository.list_rules()
    )


def test_configuration_and_block_events_are_audited(access_control):
    rule = access_control.add_rule("198.51.100.8", "Vendedor")
    access_control.set_enabled(True)
    assert access_control.is_allowed("198.51.100.9", "/api/orders") is False
    access_control.set_enabled(False)
    access_control.delete_rule(rule.id)

    event_types = {
        event["event_type"] for event in access_control.recent_audit_events()
    }
    assert {
        "rule_added",
        "whitelist_enabled",
        "whitelist_blocked",
        "whitelist_disabled",
        "rule_deleted",
    }.issubset(event_types)
