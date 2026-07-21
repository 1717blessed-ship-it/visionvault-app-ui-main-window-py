"""Verifica estado actual en disco y DB."""
import sqlite3
import re
from pathlib import Path

FOLDER = Path(r"C:\Users\Win 10\Desktop\Banco de Stickers")
DB = Path(r"C:\Users\Win 10\Documents\Codex\2026-07-13\visionvault-app-ui-main-window-py\visionvault.db")
TMP_PATTERN = re.compile(r"^\.__doccione_tmp_[0-9a-f]+_(\d+)(\.[^.]+)$", re.IGNORECASE)

files = list(FOLDER.iterdir())
tmp = [f for f in files if TMP_PATTERN.match(f.name)]
numeric = [f for f in files if f.stem.isdigit()]
other = [f for f in files if not TMP_PATTERN.match(f.name) and not f.stem.isdigit()]

print(f"=== DISCO ===")
print(f"Total archivos      : {len(files)}")
print(f"Numericos (00001...): {len(numeric)}")
print(f"Temporales          : {len(tmp)}")
print(f"Otros               : {len(other)}")
if other:
    print(f"  Ejemplos otros: {[f.name for f in other[:5]]}")
if numeric:
    nums = sorted(int(f.stem) for f in numeric)
    print(f"  Rango numericos : {nums[0]:05d} - {nums[-1]:05d}")
if tmp:
    indices = sorted(int(TMP_PATTERN.match(f.name).group(1)) for f in tmp)
    print(f"  Rango temporales: {indices[0]} - {indices[-1]}")

print()
print(f"=== BASE DE DATOS ===")
prefix = str(FOLDER).lower() + "\\"
con = sqlite3.connect(DB)
rows = con.execute("SELECT path FROM images ORDER BY path COLLATE NOCASE").fetchall()
db_paths = [row[0] for row in rows if row[0].lower().startswith(prefix)]
names = [Path(p).name for p in db_paths]
numeric_db = [n for n in names if Path(n).stem.isdigit()]
tmp_db = [n for n in names if TMP_PATTERN.match(n)]
other_db = [n for n in names if not Path(n).stem.isdigit() and not TMP_PATTERN.match(n)]
print(f"Total en DB         : {len(db_paths)}")
print(f"Numericos en DB     : {len(numeric_db)}")
print(f"Temporales en DB    : {len(tmp_db)}")
print(f"Originales en DB    : {len(other_db)}")
if numeric_db:
    nums = sorted(int(Path(n).stem) for n in numeric_db)
    print(f"  Rango numericos : {nums[0]:05d} - {nums[-1]:05d}")
if other_db:
    print(f"  Ejemplos originales: {other_db[:3]}")
con.close()
