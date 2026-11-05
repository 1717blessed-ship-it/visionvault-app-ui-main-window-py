from pathlib import Path

import pytest

from app.api.order_sync_integration import (
    OrderIntegrationEnvironment,
    secure_lan_integration_server,
)


def test_secure_lan_listener_fails_closed_for_unsafe_networks(tmp_path):
    env = OrderIntegrationEnvironment()
    cert = tmp_path/'server.pem'; key = tmp_path/'server.key'
    cert.write_text('not a certificate'); key.write_text('not a key')
    try:
        for bind, clients in [
                ('127.0.0.1', ['192.168.1.50']),
                ('8.8.8.8', ['192.168.1.50']),
                ('192.168.1.21', []),
                ('192.168.1.21', ['8.8.8.8']),
                ('192.168.1.21', ['127.0.0.1'])]:
            with pytest.raises(ValueError, match='private_lan_configuration_required'):
                with secure_lan_integration_server(env, bind_address=bind,
                        port=8875, certificate=cert, private_key=key,
                        allowed_client_addresses=clients):
                    pass
    finally:
        env.close()


def test_secure_lan_listener_requires_certificate_files(tmp_path):
    env = OrderIntegrationEnvironment()
    try:
        with pytest.raises(ValueError, match='tls_material_required'):
            with secure_lan_integration_server(env,
                    bind_address='192.168.1.21', port=8875,
                    certificate=tmp_path/'missing.pem',
                    private_key=tmp_path/'missing.key',
                    allowed_client_addresses=['192.168.1.50']):
                pass
    finally:
        env.close()


def test_pilot_cli_has_no_database_argument():
    source = (Path(__file__).parents[1]/'tools'/'order_sync_lan_pilot.py').read_text()
    assert "add_argument('--database'" not in source
    assert 'OrderIntegrationEnvironment(enable_writes=args.enable_fictitious_writes)' in source
