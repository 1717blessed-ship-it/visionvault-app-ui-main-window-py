"""Renombra los diseños de Stick new y actualiza las referencias de Doccione.

Primero ejecutá sin ``--apply`` para revisar el alcance. Con ``--apply`` se
crea una copia de la base y un CSV con el mapeo antes de cambiar archivos.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path


DEFAULT_FOLDER = Path(r"C:\Users\Win 10\Desktop\Nueva carpeta\Stick new")


def build_mapping(connection: sqlite3.Connection, folder: Path) -> list[tuple[Path, Path]]:
    prefix = str(folder.resolve()).lower() + "\\"
    rows = connection.execute("SELECT path FROM images ORDER BY path COLLATE NOCASE").fetchall()
    paths = [Path(row[0]) for row in rows if str(row[0]).lower().startswith(prefix)]
    mapping = []
    for number, source in enumerate(paths, start=1):
        target = source.with_name(f"{number:05d}{source.suffix.lower()}")
        mapping.append((source, target))
    return mapping


def write_mapping(mapping: list[tuple[Path, Path]], output: Path) -> None:
    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(("anterior", "nuevo"))
        writer.writerows((str(source), str(target)) for source, target in mapping)


def replace_paths_in_database(connection: sqlite3.Connection, mapping: list[tuple[Path, Path]]) -> None:
    replacements = {str(source): str(target) for source, target in mapping}
    tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    for table in tables:
        columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
        for column in columns:
            if column not in {"path", "image_path", "original_path", "work_path", "duplicate_path"}:
                continue
            for source, target in replacements.items():
                connection.execute(f"UPDATE {table} SET {column} = ? WHERE {column} = ?", (target, source))

    projects = connection.execute("SELECT id, project_json FROM plancha_projects").fetchall()
    for project_id, project_json in projects:
        updated = project_json or ""
        for source, target in replacements.items():
            updated = updated.replace(source, target)
        if updated != project_json:
            connection.execute("UPDATE plancha_projects SET project_json = ? WHERE id = ?", (updated, project_id))


def main() -> None:
    parser = argparse.ArgumentParser(description="Renombra los diseños de Stick new como 00001.png, 00002.png, etc.")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--database", type=Path, default=Path("visionvault.db"))
    parser.add_argument("--apply", action="store_true", help="Aplica el renombrado y actualiza la base.")
    args = parser.parse_args()
    folder, database = args.folder.resolve(), args.database.resolve()
    connection = sqlite3.connect(database)
    mapping = build_mapping(connection, folder)
    print(f"Diseños encontrados: {len(mapping)}")
    if mapping:
        print(f"Primero: {mapping[0][0].name} -> {mapping[0][1].name}")
        print(f"Último: {mapping[-1][0].name} -> {mapping[-1][1].name}")
    if not args.apply:
        print("Vista previa solamente. Ejecutá con --apply para confirmar.")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = database.with_name(f"{database.stem}_antes_renombrar_{stamp}{database.suffix}")
    mapping_file = database.with_name(f"mapeo_stick_new_{stamp}.csv")
    shutil.copy2(database, backup)
    write_mapping(mapping, mapping_file)
    try:
        staged: list[tuple[Path, Path, Path]] = []
        token = uuid.uuid4().hex
        for index, (source, target) in enumerate(mapping):
            if not source.is_file():
                raise FileNotFoundError(f"No se encontró: {source}")
            temporary = source.with_name(f".__doccione_tmp_{token}_{index}{source.suffix}")
            source.rename(temporary)
            staged.append((source, temporary, target))
        for _source, temporary, target in staged:
            temporary.rename(target)
        with connection:
            replace_paths_in_database(connection, [(source, target) for source, _temporary, target in staged])
    except Exception:
        for source, temporary, target in reversed(locals().get("staged", [])):
            if target.exists():
                target.rename(source)
            elif temporary.exists():
                temporary.rename(source)
        raise
    finally:
        connection.close()
    print(f"Completado. Copia de la base: {backup}")
    print(f"Mapeo de archivos: {mapping_file}")


if __name__ == "__main__":
    main()
