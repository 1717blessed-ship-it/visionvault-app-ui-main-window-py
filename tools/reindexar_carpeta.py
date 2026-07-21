"""Limpia y re-indexa una carpeta del banco de imágenes.

Pasos:
  1. Elimina de la DB todos los registros cuyo path pertenece a la carpeta
     (images + todas las tablas relacionadas).
  2. Escanea los archivos de la carpeta en disco.
  3. Inserta los nuevos registros.

Ejecutar sin --apply para ver el alcance. Con --apply hace backup y aplica.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

# Ajustar si se usa otra DB o carpeta
FOLDER_DEFAULT = Path(r"C:\Users\Win 10\Desktop\Nueva carpeta\Stick new")
DB_DEFAULT = Path(r"C:\Users\Win 10\Documents\Codex\2026-07-13\visionvault-app-ui-main-window-py\visionvault.db")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff"}


def get_folder_paths(connection: sqlite3.Connection, folder: Path) -> list[str]:
    """Devuelve todos los paths de la DB que pertenecen a esta carpeta."""
    prefix = str(folder.resolve()).lower() + "\\"
    rows = connection.execute("SELECT path FROM images").fetchall()
    return [row[0] for row in rows if row[0].lower().startswith(prefix)]


def delete_folder_from_db(connection: sqlite3.Connection, paths: list[str]) -> None:
    """Elimina todos los registros relacionados con los paths dados."""
    if not paths:
        return
    placeholders = ",".join("?" * len(paths))

    # Tablas con FK directa a images.path
    related_tables = [
        "image_tags",
        "visual_similarities",          # query_path y candidate_path
        "ai_results",
        "dismissed_ai_tags",
        "plancha_usage",
        "image_collections",
        "design_preparations",          # original_path y work_path
        "order_designs",
    ]
    for table in related_tables:
        # Detectar qué columnas tiene para no asumir el nombre
        cols = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
        for col in cols:
            if col in {"image_path", "path", "query_path", "candidate_path", "original_path", "work_path"}:
                connection.execute(f"DELETE FROM {table} WHERE {col} IN ({placeholders})", paths)

    # Tabla principal
    connection.execute(f"DELETE FROM images WHERE path IN ({placeholders})", paths)


def scan_folder(folder: Path):
    """Genera dicts de imagen para cada archivo soportado en la carpeta."""
    import os
    for entry in os.scandir(folder):
        if not entry.is_file():
            continue
        p = Path(entry.path)
        if p.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        stat = entry.stat()
        # Caption mínimo: nombre sin extensión, sin guiones bajos
        caption = p.stem.replace("_", " ").replace("-", " ")
        yield {
            "path": str(p.resolve()),
            "name": p.name,
            "extension": p.suffix.lower(),
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "caption": caption,
        }


def upsert_images(connection: sqlite3.Connection, images: list[dict]) -> None:
    connection.executemany(
        """INSERT INTO images(path, name, extension, size, modified, caption)
           VALUES(:path, :name, :extension, :size, :modified, :caption)
           ON CONFLICT(path) DO UPDATE SET
             name=excluded.name, extension=excluded.extension,
             size=excluded.size, modified=excluded.modified""",
        images,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=FOLDER_DEFAULT)
    parser.add_argument("--database", type=Path, default=DB_DEFAULT)
    parser.add_argument("--apply", action="store_true", help="Aplica los cambios.")
    args = parser.parse_args()

    folder = args.folder.resolve()
    database = args.database.resolve()

    if not folder.is_dir():
        print(f"ERROR: No se encontró la carpeta: {folder}")
        return

    connection = sqlite3.connect(database)
    try:
        existing_paths = get_folder_paths(connection, folder)
        disk_images = list(scan_folder(folder))

        print(f"Carpeta      : {folder}")
        print(f"En DB        : {len(existing_paths)} registros a eliminar")
        print(f"En disco     : {len(disk_images)} archivos a indexar")

        if not args.apply:
            print("\nVista previa. Ejecutar con --apply para confirmar.")
            return

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = database.with_name(f"{database.stem}_backup_reindex_{stamp}{database.suffix}")
        shutil.copy2(database, backup)
        print(f"\nBackup DB    : {backup}")

        print("Limpiando registros existentes...")
        with connection:
            delete_folder_from_db(connection, existing_paths)
        print(f"  Eliminados : {len(existing_paths)} registros")

        print("Indexando archivos en disco...")
        with connection:
            upsert_images(connection, disk_images)
        print(f"  Indexados  : {len(disk_images)} archivos")

        print("\nListo.")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
