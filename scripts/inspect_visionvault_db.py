import sqlite3, json, sys
from pathlib import Path
p = Path(__file__).resolve().parents[1] / 'visionvault.db'
out = {'db_path': str(p.resolve())}
conn = sqlite3.connect(str(p))
conn.row_factory = sqlite3.Row
cur = conn.cursor()
# list tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
out['tables'] = tables
# counts
counts = {}
for t in tables:
    try:
        cur.execute(f"SELECT COUNT(*) AS c FROM \"{t}\"")
        counts[t] = cur.fetchone()['c']
    except Exception as e:
        counts[t] = None
out['counts'] = counts
# schemas and first 5 rows for specific tables
def table_info(t):
    info = {}
    try:
        cur.execute(f"PRAGMA table_info(\"{t}\")")
        cols = [dict(r) for r in cur.fetchall()]
        info['schema'] = cols
    except Exception as e:
        info['schema_error'] = str(e)
    try:
        cur.execute(f"SELECT * FROM \"{t}\" LIMIT 5")
        rows = [dict(r) for r in cur.fetchall()]
        info['first_rows'] = rows
    except Exception as e:
        info['first_rows_error'] = str(e)
    # additional counts if zero
    try:
        cur.execute(f"SELECT COUNT(*) AS c FROM \"{t}\"")
        info['count'] = cur.fetchone()['c']
    except Exception as e:
        info['count_error'] = str(e)
    return info
for tab in ['price_rules','cost_rules','orders']:
    out[tab] = table_info(tab)
# check for possible filter columns and their distinct values
check_cols = ['active','deleted','is_deleted','archived','is_archived','status']
filters = {}
for tab in ['price_rules','cost_rules','orders']:
    filters[tab] = {}
    cols = [c['name'] for c in out[tab].get('schema',[])]
    for col in check_cols:
        if col in cols:
            try:
                cur.execute(f"SELECT DISTINCT \"{col}\" AS v FROM \"{tab}\"")
                vals = [r['v'] for r in cur.fetchall()]
                filters[tab][col] = vals
            except Exception as e:
                filters[tab][col] = str(e)
out['filter_columns'] = filters
# also include sqlite_master tables list
cur.execute("SELECT name, type, sql FROM sqlite_master WHERE type IN ('table','view') ORDER BY name")
out['sqlite_master'] = [dict(r) for r in cur.fetchall()]
# write output
out_path = Path(__file__).resolve().parents[1] / 'visionvault_db_inspect.json'
with open(out_path, 'w', encoding='utf-8') as fh:
    json.dump(out, fh, ensure_ascii=False, indent=2)
print(str(out_path))
conn.close()
