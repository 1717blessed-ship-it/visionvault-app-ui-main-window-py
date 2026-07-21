"""Recupera el renombrado interrumpido de Stick new y actualiza la base de datos.

Situación de partida:
- 00001.png ... 02726.png  -> ya existen en disco (fase 2 del run anterior completó hasta index 2717)
- .__doccione_tmp_..._2718.png ... .__doccione_tmp_..._5015.png -> quedaron en estado temporal
- La DB tiene los 5016 registros aún con los nombres originales (la actualización nunca se ejecutó)

Este script:
1. Renombra los archivos temporales a su nombre final (02719.png ... 05016.png)
   El índice está codificado en el propio nombre del archivo temporal.
2. Actualiza TODA la DB: mapea los nombres originales ordenados alfabéticamente
   a 00001.png ... 05016.png.

Primero ejecutar sin --apply para revisar. Con --apply hace backup y aplica.
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

FOLDER = Path(r"C:\Users\Win 10\Desktop\Nueva carpeta\Stick new")
DB_DEFAULT = Path(r"C:\Users\Win 10\Documents\Codex\2026-07-13\visionvault-app-ui-main-window-py\visionvault.db")

TMP_PATTERN = re.compile(r"^\.__doccione_tmp_[0-9a-f]+_(\d+)(\.[^.]+)$", re.IGNORECASE)


def get_db_paths(connection: sqlite3.Connection, folder: Path) -> list[Path]:
    """Devuelve los paths del folder ordenados alfabéticamente como los tiene la DB."""
    prefix = str(folder.resolve()).lower() + "\\"
    rows = connection.execute(
        "SELECT path FROM images ORDER BY path COLLATE NOCASE"
    ).fetchall()
    return [Path(row[0]) for row in rows if row[0].lower().startswith(prefix)]


def build_full_mapping(db_paths: list[Path]) -> list[tuple[Path, Path]]:
    """Construye el mapeo completo: nombre_original -> 00001.png, etc."""
    mapping = []
    for number, original in enumerate(db_paths, start=1):
        target = original.with_name(f"{number:05d}{original.suffix.lower()}")
        mapping.append((original, target))
    return mapping


def check_disk_state(folder: Path, mapping: list[tuple[Path, Path]]) -> dict:
    """Verifica el estado en disco para cada entrada del mapping."""
    tmp_files: dict[int, Path] = {}
    for f in folder.iterdir():
        m = TMP_PATTERN.match(f.name)
        if m:
            idx = int(m.group(1))  # índice 0-based del run anterior
            tmp_files[idx] = f

    ok = []        # ya tienen el nombre final correcto
    need_tmp = []  # están como temporales, hay que renombrar a final
    missing = []   # no están ni como final ni como temporal

    for i, (original, target) in enumerate(mapping):
        if target.exists():
            ok.append((i, original, target))
        elif i in tmp_files:
            need_tmp.append((i, tmp_files[i], target))
        else:
            missing.append((i, original, target))

    return {"ok": ok, "need_tmp": need_tmp, "missing": missing, "tmp_files": tmp_files}


def replace_paths_in_database(
    connection: sqlite3.Connection,
    mapping: list[tuple[Path, Path]],
) -> None:
    """Reemplaza todos los paths originales por los nuevos en todas las tablas relevantes."""
    replacements = {str(source): str(target) for source, target in mapping}

    tables = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    ]
    path_columns = {"path", "image_path", "original_path", "work_path", "duplicate_path"}

    for table in tables:
        columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
        for column in columns:
            if column not in path_columns:
                continue
            for source, target in replacements.items():
                connection.execute(
                    f"UPDATE {table} SET {column} = ? WHERE {column} = ?",
                    (target, source),
                )

    # plancha_projects guarda JSON con paths embebidos
    projects = connection.execute(
        "SELECT id, project_json FROM plancha_projects"
    ).fetchall()
    for project_id, project_json in projects:
        updated = project_json or ""
        for source, target in replacements.items():
            updated = updated.replace(source, target)
        if updated != project_json:
            connection.execute(
                "UPDATE plancha_projects SET project_json = ? WHERE id = ?",
                (updated, project_id),
            )


def write_mapping_csv(mapping: list[tuple[Path, Path]], output: Path) -> None:
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(("anterior", "nuevo"))
        writer.writerows((str(src), str(tgt)) for src, tgt in mapping)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=FOLDER)
    parser.add_argument("--database", type=Path, default=DB_DEFAULT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    folder = args.folder.resolve()
    database = args.database.resolve()

    connection = sqlite3.connect(database)
    try:
        db_paths = get_db_paths(connection, folder)
        mapping = build_full_mapping(db_paths)
        state = check_disk_state(folder, mapping)

        print(f"Registros en DB para esta carpeta : {len(mapping)}")
        print(f"  Ya con nombre final en disco     : {len(state['ok'])}")
        print(f"  Temporales que hay que completar : {len(state['need_tmp'])}")
        print(f"  Faltantes (ni final ni temporal) : {len(state['missing'])}")

        if state["missing"]:
            print("\nARCHIVOS FALTANTES (primeros 10):")
            for i, original, target in state["missing"][:10]:
                print(f"  [{i+1:05d}] {original.name}")

        if not args.apply:
            print("\nVista previa solamente. Ejecutar con --apply para confirmar.")
            return

        if state["missing"]:
            print("\nERROR: hay archivos que no se encuentran ni como final ni como temporal.")
            print("No se puede continuar sin todos los archivos.")
            return

        # --- Backup ---
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = database.with_name(f"{database.stem}_backup_{stamp}{database.suffix}")
        mapping_csv = database.with_name(f"mapeo_stick_new_{stamp}.csv")
        shutil.copy2(database, backup)
        write_mapping_csv(mapping, mapping_csv)
        print(f"\nBackup DB  : {backup}")
        print(f"CSV mapeo  : {mapping_csv}")

        # --- Renombrar temporales a nombres finales ---
        if state["need_tmp"]:
            print(f"\nRenombrando {len(state['need_tmp'])} archivos temporales...")
            for _i, tmp_path, target in state["need_tmp"]:
                tmp_path.rename(target)
            print("  Listo.")

        # --- Actualizar DB ---
        print("\nActualizando base de datos...")
        with connection:
            replace_paths_in_database(connection, mapping)
        print("  Listo.")

        print(f"\nCompletado. {len(mapping)} registros procesados.")
        print(f"Backup: {backup}")
        print(f"Mapeo:  {mapping_csv}")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
