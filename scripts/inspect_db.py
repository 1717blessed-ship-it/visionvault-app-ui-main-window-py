import sqlite3, json, sys, os
from pathlib import Path

root = Path(__file__).resolve().parents[1]
db_files = list(root.rglob('*.db'))
out = []
for db in db_files:
    info = {
        'path': str(db),
        'size': db.stat().st_size,
        'mtime': db.stat().st_mtime,
    }
    try:
        conn = sqlite3.connect(str(db))
        cur = conn.cursor()
        def cnt(table):
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                return cur.fetchone()[0]
            except Exception:
                return None
        info.update({
            'price_rules': cnt('price_rules'),
            'cost_rules': cnt('cost_rules'),
            'orders': cnt('orders'),
        })
        conn.close()
    except Exception as e:
        info['error'] = str(e)
    out.append(info)

payload = json.dumps(out, ensure_ascii=False, indent=2)
print(payload)
try:
    with open(Path(__file__).resolve().parents[1] / 'db_inspect_output.json', 'w', encoding='utf-8') as fh:
        fh.write(payload)
    print('WROTE:', str(Path(__file__).resolve().parents[1] / 'db_inspect_output.json'))
except Exception:
    pass
