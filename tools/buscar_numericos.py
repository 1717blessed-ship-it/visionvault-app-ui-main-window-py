"""Busca en la DB de dónde vienen los archivos 00001.png, y dónde están físicamente."""
import sqlite3
from pathlib import Path

DB = Path(r"C:\Users\Win 10\Documents\Codex\2026-07-13\visionvault-app-ui-main-window-py\visionvault.db")

con = sqlite3.connect(DB)

# Paths numéricos en DB
rows = con.execute("SELECT path FROM images WHERE name LIKE '0%.png' OR name LIKE '0%.jpg' ORDER BY path LIMIT 5").fetchall()
print("=== Paths numéricos en DB (primeros 5) ===")
for r in rows:
    print(" ", r[0])

total_num = con.execute("SELECT COUNT(*) FROM images WHERE name GLOB '[0-9][0-9][0-9][0-9][0-9].*'").fetchone()[0]
print(f"\nTotal numéricos (00000.*) en DB: {total_num}")

# Todas las carpetas distintas en DB
print("\n=== Carpetas en DB ===")
rows2 = con.execute("SELECT path FROM images").fetchall()
folders = set()
for r in rows2:
    p = Path(r[0])
    folders.add(str(p.parent))
for f in sorted(folders)[:20]:
    print(" ", f)

con.close()
