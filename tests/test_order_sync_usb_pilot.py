from pathlib import Path

import pytest

from app.api.order_sync_integration import (
    OrderIntegrationEnvironment,
    secure_usb_integration_server,
)
from tools.order_sync_usb_pilot import parser


def test_usb_cli_exposes_no_bind_or_database_override():
    help_text = parser().format_help()
    assert '--bind' not in help_text
    assert '--database' not in help_text


def test_usb_server_requires_fixed_port_and_tls_material(tmp_path: Path):
    env = OrderIntegrationEnvironment()
    try:
        with pytest.raises(ValueError, match='usb_pilot_port_required'):
            with secure_usb_integration_server(
                    env, certificate=tmp_path/'missing.pem',
                    private_key=tmp_path/'missing.key', port=8876):
                pass
        with pytest.raises(ValueError, match='tls_material_required'):
            with secure_usb_integration_server(
                    env, certificate=tmp_path/'missing.pem',
                    private_key=tmp_path/'missing.key'):
                pass
    finally:
        env.close()


def test_usb_environment_defaults_to_write_disabled_and_temporary_database():
    env = OrderIntegrationEnvironment()
    try:
        assert env.enable_writes is False
        env.assert_isolated()
        assert env._path.name == 'integration.db'
        assert 'doccione-order-sync-integration-' in str(env._path.parent)
    finally:
        env.close()
