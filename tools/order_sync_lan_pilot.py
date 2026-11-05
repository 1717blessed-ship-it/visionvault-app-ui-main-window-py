"""Explicit HTTPS pilot for Android against disposable fictitious data only.

This command never accepts a database path.  The database and generated
catalog live under OrderIntegrationEnvironment's owned TemporaryDirectory and
are removed when the process exits.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
from pathlib import Path
import signal
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from PIL import Image

from app.api.order_sync_integration import (
    OrderIntegrationEnvironment,
    secure_lan_integration_server,
)


def _private_ipv4(value: str) -> str:
    address = ipaddress.ip_address(value)
    if address.version != 4 or not address.is_private or address.is_loopback:
        raise argparse.ArgumentTypeError('se requiere una IPv4 privada no-loopback')
    return str(address)


def create_certificates(address: str, output: Path, public_ca: Path) -> None:
    """Create a local CA and an IP-bound leaf; private keys never enter APK."""
    output.mkdir(parents=True, exist_ok=True)
    public_ca.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_name = x509.Name([x509.NameAttribute(
        NameOID.COMMON_NAME, 'Doccione Integration Pilot CA')])
    ca_cert = (x509.CertificateBuilder().subject_name(ca_name)
        .issuer_name(ca_name).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(
            ca_key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(
            ca_key.public_key()), critical=False)
        .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False,
            content_commitment=False, data_encipherment=False, key_agreement=False,
            key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False),
            critical=True).sign(ca_key, hashes.SHA256()))
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    server_name = x509.Name([x509.NameAttribute(
        NameOID.COMMON_NAME, address)])
    server_cert = (x509.CertificateBuilder().subject_name(server_name)
        .issuer_name(ca_cert.subject).public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=90))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([
            x509.IPAddress(ipaddress.ip_address(address))]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(
            server_key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(
            ca_key.public_key()), critical=False)
        .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True,
            content_commitment=False, data_encipherment=False, key_agreement=False,
            key_cert_sign=False, crl_sign=False, encipher_only=False,
            decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([
            x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256()))
    private = serialization.PrivateFormat.TraditionalOpenSSL
    no_encryption = serialization.NoEncryption()
    (output/'pilot-ca.key').write_bytes(ca_key.private_bytes(
        serialization.Encoding.PEM, private, no_encryption))
    ca_bytes = ca_cert.public_bytes(serialization.Encoding.PEM)
    (output/'pilot-ca.pem').write_bytes(ca_bytes)
    public_ca.write_bytes(ca_bytes)
    (output/'pilot-server.key').write_bytes(server_key.private_bytes(
        serialization.Encoding.PEM, private, no_encryption))
    (output/'pilot-server.pem').write_bytes(
        server_cert.public_bytes(serialization.Encoding.PEM))
    print('Certificado emitido para:', address)
    print('CA SHA-256:', hashlib.sha256(ca_cert.public_bytes(
        serialization.Encoding.DER)).hexdigest())
    print('La clave privada queda solo en:', output.resolve())


def seed_fictitious_data(env: OrderIntegrationEnvironment) -> None:
    db = env.database
    db.save_catalog_product(name='Producto piloto ficticio', price=100)
    product = db.connection.execute(
        "SELECT id,code FROM products WHERE name='Producto piloto ficticio'").fetchone()
    rule = db.connection.execute(
        'SELECT material FROM price_rules WHERE product_id=?', (product[0],)).fetchone()
    db.connection.execute(
        "INSERT INTO product_variants(product_id,code,name,material,size,created_at,updated_at) "
        "VALUES(?,'pilot-variant','VARIANTE FICTICIA',?,'5cm','now','now')",
        (product[0], rule[0]))
    variant = db.connection.execute(
        "SELECT id FROM product_variants WHERE code='pilot-variant'").fetchone()[0]
    db.connection.execute(
        "UPDATE price_rules SET variant_id=?,size='5cm' WHERE product_id=?",
        (variant, product[0]))
    image = env._path.parent/'piloto-ficticio.png'
    Image.new('RGB', (300, 300), (190, 40, 100)).save(image)
    db.connection.execute(
        "INSERT INTO images(path,name,extension,size,modified,is_reusable,is_private,visible_width,visible_height) "
        "VALUES(?,? ,'.png',1,1,1,0,300,300)",
        (str(image), 'DISEÑO FICTICIO PILOTO'))
    db.connection.commit()


def serve(args: argparse.Namespace) -> None:
    env = OrderIntegrationEnvironment(enable_writes=args.enable_fictitious_writes)
    stopped = threading.Event()
    try:
        seed_fictitious_data(env)
        code = env.database.event_repo.create_pairing_code()
        with secure_lan_integration_server(env, bind_address=args.bind,
                port=args.port, certificate=args.certificate,
                private_key=args.private_key,
                allowed_client_addresses=[args.allowed_client]) as url:
            print('ENTORNO AISLADO; BASE TEMPORAL:', env._path)
            print('URL HTTPS:', url)
            print('Cliente autorizado:', args.allowed_client)
            print('Escrituras ficticias:', env.enable_writes)
            print('Código de emparejamiento de un solo uso:', code)
            print('Ctrl+C para destruir la base temporal y detener el piloto.')
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
    cert.add_argument('--address', type=_private_ipv4, required=True)
    cert.add_argument('--output', type=Path, required=True)
    cert.add_argument('--public-ca', type=Path, required=True)
    run = commands.add_parser('serve')
    run.add_argument('--bind', type=_private_ipv4, required=True)
    run.add_argument('--port', type=int, default=8875)
    run.add_argument('--allowed-client', type=_private_ipv4, required=True)
    run.add_argument('--certificate', type=Path, required=True)
    run.add_argument('--private-key', type=Path, required=True)
    run.add_argument('--enable-fictitious-writes', action='store_true')
    return result


def main() -> None:
    args = parser().parse_args()
    if args.command == 'create-certificates':
        create_certificates(args.address, args.output, args.public_ca)
    else:
        serve(args)


if __name__ == '__main__':
    main()
