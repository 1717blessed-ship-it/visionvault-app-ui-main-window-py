"""Create and verify the external Doccione Mobile sticker-bank payload.

The catalog manifest remains versioned so Flutter analysis and catalog tests can
run from a fresh checkout. The image payload is restored before a distributable
build and verified against the versioned lock file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / "mobile" / "doccione_mobile" / "assets" / "sticker_bank"
CATALOG = BANK / "manifest.json"
LOCK = ROOT / "mobile" / "doccione_mobile" / "assets" / "sticker_bank.lock.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _catalog_paths() -> list[str]:
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    designs = payload.get("designs")
    if not isinstance(designs, list):
        raise ValueError("manifest.json no contiene una lista 'designs'")

    prefix = "assets/sticker_bank/"
    result: list[str] = []
    for index, design in enumerate(designs):
        if not isinstance(design, dict):
            raise ValueError(f"diseño {index} no es un objeto")
        asset = design.get("asset_preview_path")
        if not isinstance(asset, str) or not asset.startswith(prefix):
            raise ValueError(f"diseño {index} tiene asset_preview_path inválido")
        relative = asset[len(prefix) :]
        if not relative or Path(relative).name != relative:
            raise ValueError(f"ruta de asset insegura: {asset!r}")
        result.append(relative)
    if len(result) != len(set(result)):
        raise ValueError("el catálogo contiene rutas de imagen duplicadas")
    return sorted(result)


def create_lock() -> int:
    paths = _catalog_paths()
    missing = [name for name in paths if not (BANK / name).is_file()]
    if missing:
        print(f"No se puede generar el lock: faltan {len(missing)} imágenes.", file=sys.stderr)
        return 1

    files = []
    tree = hashlib.sha256()
    total = 0
    for name in paths:
        path = BANK / name
        size = path.stat().st_size
        checksum = _sha256(path)
        files.append({"path": name, "size": size, "sha256": checksum})
        tree.update(f"{name}\0{size}\0{checksum}\n".encode("utf-8"))
        total += size

    document = {
        "schema": 1,
        "catalog_sha256": _sha256(CATALOG),
        "file_count": len(files),
        "total_bytes": total,
        "tree_sha256": tree.hexdigest(),
        "files": files,
    }
    LOCK.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"Lock generado: {len(files)} imágenes, {total} bytes, "
        f"tree {document['tree_sha256']}"
    )
    return 0


def verify(*, allow_manifest_only: bool) -> int:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    expected = lock.get("files")
    if not isinstance(expected, list):
        print("Lock inválido: falta la lista 'files'.", file=sys.stderr)
        return 1
    if _sha256(CATALOG) != lock.get("catalog_sha256"):
        print("El catálogo no coincide con sticker_bank.lock.json.", file=sys.stderr)
        return 1

    present_images = [path for path in BANK.iterdir() if path.suffix.lower() == ".png"]
    if not present_images and allow_manifest_only:
        print("Checkout válido en modo manifiesto: payload externo no instalado.")
        return 0

    expected_names = {entry["path"] for entry in expected}
    actual_names = {path.name for path in present_images}
    missing = sorted(expected_names - actual_names)
    unexpected = sorted(actual_names - expected_names)
    invalid: list[str] = []
    for entry in expected:
        name = entry["path"]
        path = BANK / name
        if not path.is_file():
            continue
        if path.stat().st_size != entry["size"] or _sha256(path) != entry["sha256"]:
            invalid.append(name)

    if missing or unexpected or invalid:
        print(
            f"Banco inválido: faltan={len(missing)}, inesperadas={len(unexpected)}, "
            f"checksum/tamaño={len(invalid)}.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Banco verificado: {len(expected)} imágenes, "
        f"tree {lock.get('tree_sha256')}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("lock", help="regenera el lock desde el banco local")
    verify_parser = subparsers.add_parser("verify", help="verifica catálogo y payload")
    verify_parser.add_argument(
        "--allow-manifest-only",
        action="store_true",
        help="acepta un checkout sin imágenes (CI de análisis/pruebas)",
    )
    args = parser.parse_args()
    if args.command == "lock":
        return create_lock()
    return verify(allow_manifest_only=args.allow_manifest_only)


if __name__ == "__main__":
    raise SystemExit(main())
