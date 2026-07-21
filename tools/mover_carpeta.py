"""Mueve la carpeta Stick new a una nueva ubicación y actualiza todos los paths en la DB.

Ejecutar sin --apply para ver el alcance. Con --apply hace backup y aplica.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

SOURCE     = Path(r"C:\Users\Win 10\Desktop\Stick new")
DEST       = Path(r"C:\Users\Win 10\Desktop\Banco de Stickers")
# Path que la DB cree que es el origen (puede diferir del físico si ya fue re-indexado)
DB_SOURCE  = Path(r"C:\Users\Win 10\Desktop\Stick new")
DB     = Path(r"C:\Users\Win 10\Documents\Codex\2026-07-13\visionvault-app-ui-main-window-py\visionvault.db")


def update_paths_in_db(connection: sqlite3.Connection, old_prefix: str, new_prefix: str) -> int:
    """Reemplaza el prefijo de path en todas las tablas y columnas relevantes."""
    path_columns = {
        "images":               ["path"],
        "image_tags":           ["image_path"],
        "visual_similarities":  ["query_path", "candidate_path"],
        "ai_results":           ["image_path"],
        "dismissed_ai_tags":    ["image_path"],
        "plancha_usage":        ["image_path"],
        "image_collections":    ["image_path"],
        "design_preparations":  ["original_path", "work_path"],
        "order_designs":        ["image_path"],
    }
    updated = 0
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, columns in path_columns.items():
        if table not in tables:
            continue
        for col in columns:
            cursor = connection.execute(
                f"UPDATE {table} SET {col} = ? || SUBSTR({col}, ?) WHERE {col} LIKE ?",
                (new_prefix, len(old_prefix) + 1, old_prefix + "%"),
            )
            updated += cursor.rowcount

    # plancha_projects guarda JSON con paths embebidos
    if "plancha_projects" in tables:
        projects = connection.execute("SELECT id, project_json FROM plancha_projects").fetchall()
        for project_id, project_json in projects:
            if project_json and old_prefix in project_json:
                updated_json = project_json.replace(old_prefix, new_prefix)
                connection.execute(
                    "UPDATE plancha_projects SET project_json = ? WHERE id = ?",
                    (updated_json, project_id),
                )
                updated += 1

    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",    type=Path, default=SOURCE)
    parser.add_argument("--dest",      type=Path, default=DEST)
    parser.add_argument("--db-source", type=Path, default=DB_SOURCE)
    parser.add_argument("--database",  type=Path, default=DB)
    parser.add_argument("--apply",     action="store_true")
    args = parser.parse_args()

    source    = args.source.resolve()
    dest      = args.dest.resolve()
    db_source = args.db_source.resolve()
    database  = args.database.resolve()

    if not source.is_dir():
        print(f"ERROR: No se encontró la carpeta origen en disco: {source}")
        return
    if dest.exists():
        print(f"ERROR: Ya existe una carpeta en el destino: {dest}")
        return

    # Contar archivos y registros afectados
    files = [f for f in source.iterdir() if f.is_file()]
    connection = sqlite3.connect(database)
    db_prefix = str(db_source) + "\\"
    count_db = connection.execute(
        "SELECT COUNT(*) FROM images WHERE path LIKE ?", (db_prefix + "%",)
    ).fetchone()[0]
    connection.close()

    print(f"Origen físico: {source}  ({len(files)} archivos)")
    print(f"Origen en DB : {db_source}  ({count_db} registros)")
    print(f"Destino      : {dest}")

    if not args.apply:
        print("\nVista previa. Ejecutar con --apply para confirmar.")
        return

    # Backup DB
    stamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = database.with_name(f"{database.stem}_backup_mover_{stamp}{database.suffix}")
    shutil.copy2(database, backup)
    print(f"\nBackup DB    : {backup}")

    # Mover carpeta física
    print("Moviendo carpeta en disco...")
    shutil.move(str(source), str(dest))
    print(f"  OK: {dest}")

    # Actualizar DB (el prefijo en DB puede ser diferente al físico)
    print("Actualizando paths en DB...")
    connection = sqlite3.connect(database)
    try:
        with connection:
            updated = update_paths_in_db(connection, str(db_source) + "\\", str(dest) + "\\")
        print(f"  Actualizados : {updated} referencias")
    finally:
        connection.close()

    print("\nListo.")


if __name__ == "__main__":
    main()
