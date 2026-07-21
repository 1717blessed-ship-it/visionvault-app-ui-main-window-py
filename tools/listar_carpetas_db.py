"""Lista todas las carpetas indexadas en la DB con su cantidad de registros."""
import sqlite3
from pathlib import Path
from collections import Counter

DB = Path(r"C:\Users\Win 10\Documents\Codex\2026-07-13\visionvault-app-ui-main-window-py\visionvault.db")

con = sqlite3.connect(DB)
rows = con.execute("SELECT path FROM images").fetchall()
con.close()

counter = Counter(str(Path(row[0]).parent) for row in rows)
total = sum(counter.values())
print(f"Total registros: {total}\n")
print(f"{'Carpeta':<80} {'Archivos':>8}")
print("-" * 90)
for folder, count in sorted(counter.items(), key=lambda x: -x[1]):
    print(f"{folder:<80} {count:>8}")
