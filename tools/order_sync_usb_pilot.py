"""Run the disposable Android USB/ADB-reverse integration pilot.

The listener is always TLS on 127.0.0.1:8875. This command accepts neither a
bind address nor a database path, so it cannot expose the pilot to LAN or use
operational data.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import signal
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.order_sync_integration import (
    OrderIntegrationEnvironment,
    secure_usb_integration_server,
)
from tools.order_sync_lan_pilot import create_certificates, seed_fictitious_data


def serve(args: argparse.Namespace) -> None:
    env = OrderIntegrationEnvironment(enable_writes=args.enable_fictitious_writes)
    stopped = threading.Event()
    try:
        seed_fictitious_data(env)
        code = env.database.event_repo.create_pairing_code()
        with secure_usb_integration_server(
                env, certificate=args.certificate,
                private_key=args.private_key) as url:
            print('ENTORNO USB AISLADO; BASE TEMPORAL:', env._path, flush=True)
            print('URL HTTPS:', url, flush=True)
            print('ESCUCHA: 127.0.0.1:8875 (NO LAN)', flush=True)
            print('Escrituras ficticias:', env.enable_writes, flush=True)
            print('Código de emparejamiento de un solo uso:', code, flush=True)
            print('Ctrl+C destruye la base temporal y detiene el piloto.', flush=True)
            signal.signal(signal.SIGINT, lambda *_: stopped.set())
            signal.signal(signal.SIGTERM, lambda *_: stopped.set())
            while not stopped.wait(.5):
                pass
    finally:
        env.close()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest='command', required=True)
    cert = commands.add_parser('create-certificates')
    cert.add_argument('--output', type=Path, required=True)
    cert.add_argument('--public-ca', type=Path, required=True)
    run = commands.add_parser('serve')
    run.add_argument('--certificate', type=Path, required=True)
    run.add_argument('--private-key', type=Path, required=True)
    run.add_argument('--enable-fictitious-writes', action='store_true')
    return result


def main() -> None:
    args = parser().parse_args()
    if args.command == 'create-certificates':
        create_certificates('127.0.0.1', args.output, args.public_ca)
    else:
        serve(args)


if __name__ == '__main__':
    main()
