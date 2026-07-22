"""Cuenta consultas SQLite durante el inicio de Doccione Studio.
Ejecuta: python measure_db_queries.py
Parchea el modulo _sqlite3 a nivel bajo.
"""
import sys, json, time, sqlite3
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Estrategia: interceptar via trace_callback que SQLite soporta nativamente
query_counter = Counter()
query_log = []

_original_connect = sqlite3.connect

def _traced_connect(path, *args, **kwargs):
    conn = _original_connect(path, *args, **kwargs)
    def _trace(sql):
        cleaned = sql.strip()[:200]
        query_counter[cleaned] += 1
        query_log.append(cleaned)
    conn.set_trace_callback(_trace)
    return conn

sqlite3.connect = _traced_connect

if __name__ == "__main__":
    t0 = time.perf_counter()
    from app.database.database import ImageDatabase
    import_time = round((time.perf_counter() - t0) * 1000, 1)

    t1 = time.perf_counter()
    db = ImageDatabase(PROJECT_ROOT / "visionvault.db")
    db_time = round((time.perf_counter() - t1) * 1000, 1)

    total = len(query_counter)
    unique = len(query_counter)
    repeated = {sql: c for sql, c in query_counter.items() if c > 3}
    dml = {sql: c for sql, c in query_counter.items()
           if any(sql.upper().startswith(k) for k in
                  ["SELECT","INSERT","UPDATE","DELETE","CREATE","ALTER","DROP","PRAGMA"])}

    result = {
        "total_queries": total,
        "unique_queries": unique,
        "import_time_ms": import_time,
        "db_init_time_ms": db_time,
        "repeated_3plus": dict(sorted(repeated.items(), key=lambda x: -x[1])),
        "dml_top": dict(sorted(dml.items(), key=lambda x: -x[1])),
        "all": dict(query_counter.most_common()),
    }

    with open(PROJECT_ROOT / "db_queries_results.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"Import: {import_time} ms")
    print(f"DB init: {db_time} ms")
    print(f"Total queries: {total}")
    print(f"Unique queries: {unique}")
    print(f"\n--- Repeated 3+ times ---")
    for sql, c in sorted(repeated.items(), key=lambda x: -x[1])[:25]:
        print(f"  [{c}x] {sql[:130]}")
    print(f"\n--- Top DML by frequency ---")
    for sql, c in sorted(dml.items(), key=lambda x: -x[1])[:30]:
        print(f"  [{c}x] {sql[:130]}")

    db.close()
