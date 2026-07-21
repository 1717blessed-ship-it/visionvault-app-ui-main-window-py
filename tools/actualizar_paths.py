"""Actualiza los paths de la DB tras mover una carpeta."""
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

OLD_PREFIX = r"C:\Users\Win 10\Desktop\Nueva carpeta\Stick new"
NEW_PREFIX = r"C:\Users\Win 10\Desktop\Stick new"
DB = Path(r"C:\Users\Win 10\Documents\Codex\2026-07-13\visionvault-app-ui-main-window-py\visionvault.db")

PATH_COLUMNS = {"path", "image_path", "original_path", "work_path", "duplicate_path", "query_path", "candidate_path"}

con = sqlite3.connect(DB)

# Backup
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = DB.with_name(f"{DB.stem}_backup_movepath_{stamp}{DB.suffix}")
shutil.copy2(DB, backup)
print(f"Backup: {backup}")

tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
total = 0

with con:
    for table in tables:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        for col in cols:
            if col not in PATH_COLUMNS:
                continue
            cur = con.execute(
                f"UPDATE {table} SET {col} = REPLACE({col}, ?, ?) WHERE {col} LIKE ?",
                (OLD_PREFIX, NEW_PREFIX, OLD_PREFIX + "%"),
            )
            if cur.rowcount:
                print(f"  {table}.{col}: {cur.rowcount} filas actualizadas")
                total += cur.rowcount

    # plancha_projects guarda paths embebidos en JSON
    if "plancha_projects" in tables:
        projects = con.execute("SELECT id, project_json FROM plancha_projects WHERE project_json LIKE ?",
                               (f"%{OLD_PREFIX}%",)).fetchall()
        for pid, pjson in projects:
            updated = (pjson or "").replace(OLD_PREFIX, NEW_PREFIX)
            con.execute("UPDATE plancha_projects SET project_json = ? WHERE id = ?", (updated, pid))
            total += 1
        if projects:
            print(f"  plancha_projects.project_json: {len(projects)} filas actualizadas")

print(f"\nTotal filas actualizadas: {total}")
con.close()
