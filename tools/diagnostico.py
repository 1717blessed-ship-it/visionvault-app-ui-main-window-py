"""Diagnóstico: compara archivos en disco con la base de datos."""
import sqlite3
from pathlib import Path

FOLDER = Path(r"C:\Users\Win 10\Desktop\Nueva carpeta\Stick new")
DB = Path(r"C:\Users\Win 10\Documents\Codex\2026-07-13\visionvault-app-ui-main-window-py\visionvault.db")

# --- Disco ---
all_files = sorted(FOLDER.iterdir())
tmp_files = [f for f in all_files if f.name.startswith(".__doccione_tmp_")]
normal_files = [f for f in all_files if not f.name.startswith(".__doccione_tmp_")]

print(f"Archivos en disco: {len(all_files)}")
print(f"  Temporales (.__doccione_tmp_...): {len(tmp_files)}")
print(f"  Normales: {len(normal_files)}")
if normal_files:
    print(f"  Primeros normales: {[f.name for f in normal_files[:5]]}")
if tmp_files:
    print(f"  Indices de temporales (primeros 3): {[f.stem.split('_')[-1] for f in tmp_files[:3]]}")
    print(f"  Indices de temporales (ultimos 3):  {[f.stem.split('_')[-1] for f in tmp_files[-3:]]}")

# --- Base de datos ---
prefix = str(FOLDER).lower() + "\\"
con = sqlite3.connect(DB)
rows = con.execute("SELECT path FROM images ORDER BY path COLLATE NOCASE").fetchall()
db_paths = [Path(row[0]) for row in rows if row[0].lower().startswith(prefix)]
print(f"\nRegistros en DB para esta carpeta: {len(db_paths)}")
if db_paths:
    print(f"  Primeros 5: {[p.name for p in db_paths[:5]]}")
    print(f"  Ultimos 5:  {[p.name for p in db_paths[-5:]]}")

tmp_in_db = [p for p in db_paths if p.name.startswith(".__doccione_tmp_")]
numeric_in_db = [p for p in db_paths if p.stem.isdigit()]
print(f"  Temporales en DB: {len(tmp_in_db)}")
print(f"  Numericos en DB (00001...): {len(numeric_in_db)}")

con.close()
