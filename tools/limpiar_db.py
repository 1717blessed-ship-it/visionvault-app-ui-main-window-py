"""Elimina de la DB todos los registros que NO pertenecen a Banco de Stickers.

Ejecutar sin --apply para ver el alcance. Con --apply hace backup y aplica.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

DB      = Path(r"C:\Users\Win 10\Documents\Codex\2026-07-13\visionvault-app-ui-main-window-py\visionvault.db")
KEEPER  = r"C:\Users\Win 10\Desktop\Banco de Stickers"

RELATED_TABLES = {
    "image_tags":          ["image_path"],
    "visual_similarities": ["query_path", "candidate_path"],
    "ai_results":          ["image_path"],
    "dismissed_ai_tags":   ["image_path"],
    "plancha_usage":       ["image_path"],
    "image_collections":   ["image_path"],
    "design_preparations": ["original_path", "work_path"],
    "order_designs":       ["image_path"],
}


def get_paths_to_delete(connection: sqlite3.Connection, keeper_prefix: str) -> list[str]:
    rows = connection.execute("SELECT path FROM images").fetchall()
    return [row[0] for row in rows if not row[0].startswith(keeper_prefix)]


def delete_paths(connection: sqlite3.Connection, paths: list[str]) -> int:
    if not paths:
        return 0
    # Borrar en lotes de 500 para no exceder límite de SQLite
    total = 0
    existing_tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for i in range(0, len(paths), 500):
        batch = paths[i:i + 500]
        placeholders = ",".join("?" * len(batch))
        for table, columns in RELATED_TABLES.items():
            if table not in existing_tables:
                continue
            for col in columns:
                connection.execute(f"DELETE FROM {table} WHERE {col} IN ({placeholders})", batch)
        cursor = connection.execute(f"DELETE FROM images WHERE path IN ({placeholders})", batch)
        total += cursor.rowcount
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DB)
    parser.add_argument("--keeper",   type=str,  default=KEEPER)
    parser.add_argument("--apply",    action="store_true")
    args = parser.parse_args()

    database      = args.database.resolve()
    keeper_prefix = args.keeper.rstrip("\\") + "\\"

    connection = sqlite3.connect(database)
    try:
        to_delete = get_paths_to_delete(connection, keeper_prefix)
        keepers   = connection.execute(
            "SELECT COUNT(*) FROM images WHERE path LIKE ?", (keeper_prefix + "%",)
        ).fetchone()[0]

        print(f"Registros a conservar (Banco de Stickers) : {keepers}")
        print(f"Registros a eliminar (todo lo demás)      : {len(to_delete)}")

        if not args.apply:
            print("\nVista previa. Ejecutar con --apply para confirmar.")
            return

        stamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = database.with_name(f"{database.stem}_backup_limpiar_{stamp}{database.suffix}")
        shutil.copy2(database, backup)
        print(f"\nBackup DB  : {backup}")

        print("Eliminando...")
        with connection:
            deleted = delete_paths(connection, to_delete)
        print(f"Eliminados : {deleted} registros de images + relaciones")

        remaining = connection.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        print(f"Quedan     : {remaining} registros en DB")
        print("\nListo.")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
