"""Restaura nombres temporales creados por ``rename_stick_new.py``.

Este script no modifica la base de datos. Reconstruye los nombres originales
usando el orden que permanece registrado en ``images``.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path


DEFAULT_FOLDER = Path(r"C:\Users\Win 10\Desktop\Nueva carpeta\Stick new")
TEMPORARY_NAME = re.compile(
    r"^\.__doccione_tmp_[0-9a-f]+_(?P<index>\d+)(?P<suffix>\.[^.]+)$", re.IGNORECASE
)


def original_paths(connection: sqlite3.Connection, folder: Path) -> list[Path]:
    prefix = str(folder.resolve()).lower() + "\\"
    rows = connection.execute("SELECT path FROM images ORDER BY path COLLATE NOCASE").fetchall()
    return [Path(row[0]) for row in rows if str(row[0]).lower().startswith(prefix)]


def temporary_paths(folder: Path) -> dict[int, Path]:
    result: dict[int, Path] = {}
    for item in folder.iterdir():
        match = TEMPORARY_NAME.match(item.name)
        if not match:
            continue
        index = int(match.group("index"))
        if index in result:
            raise RuntimeError(f"Hay dos archivos temporales con el índice {index}.")
        result[index] = item
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Restaura los nombres originales de Stick new.")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--database", type=Path, default=Path("visionvault.db"))
    parser.add_argument("--apply", action="store_true", help="Restaura los nombres.")
    args = parser.parse_args()
    folder, database = args.folder.resolve(), args.database.resolve()

    with sqlite3.connect(database) as connection:
        originals = original_paths(connection, folder)
    temporary = temporary_paths(folder)
    expected = set(range(len(originals)))
    found = set(temporary)
    missing, extra = sorted(expected - found), sorted(found - expected)
    print(f"Registros esperados: {len(originals)}")
    print(f"Archivos temporales: {len(temporary)}")
    if missing or extra:
        raise RuntimeError(f"Índices incompatibles. Faltan: {missing[:10]}; extras: {extra[:10]}")

    operations = [(temporary[index], originals[index]) for index in range(len(originals))]
    collisions = [target for _temporary, target in operations if target.exists()]
    if collisions:
        raise RuntimeError(f"Ya existen {len(collisions)} nombres originales; no se hará ningún cambio.")
    print(f"Se restaurarán {len(operations)} archivos sin tocar la base de datos.")
    if not args.apply:
        print("Vista previa solamente. Ejecutá con --apply para restaurar.")
        return

    restored: list[tuple[Path, Path]] = []
    try:
        for temporary_file, original_file in operations:
            temporary_file.rename(original_file)
            restored.append((temporary_file, original_file))
    except Exception:
        for temporary_file, original_file in reversed(restored):
            if original_file.exists():
                original_file.rename(temporary_file)
        raise
    print("Nombres originales restaurados correctamente.")


if __name__ == "__main__":
    main()
