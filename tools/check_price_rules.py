import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "visionvault.db"
print("DB path:", DB)
print("Exists:", DB.exists())

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM price_rules WHERE active = 1')
print('price_rules count:', cur.fetchone()[0])

print('\nSample rules:')
cur.execute('SELECT material,size,min_quantity,price,price_mode,discount_percent,extra_service FROM price_rules WHERE active = 1 ORDER BY material,size LIMIT 15')
for row in cur.fetchall():
    print(dict(row))

print('\nSample suggestions:')
cur.execute('SELECT DISTINCT material FROM price_rules WHERE active=1 AND material<>"" LIMIT 3')
materials = [r[0] for r in cur.fetchall()]
print('materials:', materials)
for material in materials:
    cur.execute('SELECT DISTINCT size FROM price_rules WHERE active=1 AND material=? AND size<>"" LIMIT 2', (material,))
    sizes = [r[0] for r in cur.fetchall()]
    for size in sizes:
        print('material', material, 'size', size)
        cur.execute('SELECT * FROM price_rules WHERE active=1 AND material=? AND size=? LIMIT 1', (material, size))
        row = cur.fetchone()
        print(' rule example:', dict(row))

try:
    from app.database.database import ImageDatabase
    db = ImageDatabase(DB)
    for material in materials:
        cur.execute('SELECT DISTINCT size FROM price_rules WHERE active=1 AND material=? AND size<>"" LIMIT 2', (material,))
        sizes = [r[0] for r in cur.fetchall()]
        for size in sizes:
            print('suggestion', material, size, db.suggest_price(material, size, 1))
except Exception as exc:
    print('Error importing or using ImageDatabase:', exc)

conn.close()
