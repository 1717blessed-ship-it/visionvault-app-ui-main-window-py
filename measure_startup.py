"""Medicion de tiempo de inicio de Doccione Studio.
Ejecuta: python measure_startup.py
Realiza 3 mediciones en frio y 3 en caliente.
"""
import subprocess, sys, time, json, os, textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
MAIN_PY = PROJECT_ROOT / "main.py"
RESULTS_FILE = PROJECT_ROOT / "measurement_results.json"

COLD_SCRIPT = textwrap.dedent(r'''
import time, sys, os, json, importlib
from pathlib import Path

project_root = Path(r"PROJROOT")
sys.path.insert(0, str(project_root))

# -- Medir imports estandar --
std_modules = [
    "tkinter", "tkinter.ttk", "tkinter.messagebox", "tkinter.filedialog",
    "tkinter.simpledialog", "sqlite3", "threading", "json", "csv",
    "pathlib", "datetime", "re", "os", "sys", "traceback", "time",
    "subprocess", "webbrowser", "zipfile", "tempfile", "calendar",
]
import_times = {}
for mod in std_modules:
    t0 = time.perf_counter()
    try:
        importlib.import_module(mod)
    except ImportError:
        pass
    import_times[mod] = round((time.perf_counter() - t0) * 1000, 2)

# -- Medir import de app.database.database --
t0 = time.perf_counter()
from app.database.database import ImageDatabase
import_times["app.database.database"] = round((time.perf_counter() - t0) * 1000, 2)

# -- Medir import de app.ui.main_window (sin ejecutar mainloop) --
t0 = time.perf_counter()
from app.ui.main_window import VisionVaultApp
import_times["app.ui.main_window"] = round((time.perf_counter() - t0) * 1000, 2)

# -- Medir tiempo de ImageDatabase.__init__ --
t0 = time.perf_counter()
db = ImageDatabase(project_root / "visionvault.db")
db_init_time = round((time.perf_counter() - t0) * 1000, 2)

# -- Contar tablas e indices --
tables = db.connection.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
).fetchall()
indexes = db.connection.execute(
    "SELECT name FROM sqlite_master WHERE type='index'"
).fetchall()

# -- Medir VisionVaultApp.__init__ (sin mainloop) --
import tkinter as tk
t0 = time.perf_counter()
try:
    app = VisionVaultApp()
    app_init_time = round((time.perf_counter() - t0) * 1000, 2)

    # -- Contar widgets --
    widget_count = len(app.winfo_children())
    def count_all_widgets(widget):
        count = 0
        for child in widget.winfo_children():
            count += 1
            count += count_all_widgets(child)
        return count
    total_widgets = count_all_widgets(app)

    # -- Contar after() callbacks (aproximado) --
    after_ids = []
    try:
        # after_cancel no expone lista, pero podemos contar via.tk.call
        after_info = str(app.tk.call('info', 'after'))
        after_count = len(after_info.split()) if after_info else 0
    except Exception:
        after_count = -1

    # -- Memoria --
    import tracemalloc
    tracemalloc.start()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # -- Cerrar app --
    try:
        app.destroy()
    except Exception:
        pass

    result = {
        "import_times": import_times,
        "db_init_time_ms": db_init_time,
        "app_init_time_ms": app_init_time,
        "table_count": len(tables),
        "index_count": len(indexes),
        "total_widgets": total_widgets,
        "after_callbacks": after_count,
        "memory_current_bytes": current,
        "memory_peak_bytes": peak,
    }
except Exception as e:
    result = {
        "import_times": import_times,
        "db_init_time_ms": db_init_time,
        "app_init_time_ms": -1,
        "error": str(e),
    }

db.close()
print(json.dumps(result, indent=2))
''')

def measure_cold(iteration: int) -> dict:
    """Mide inicio en frio: subprocess fresco."""
    script = COLD_SCRIPT.replace("PROJROOT", str(PROJECT_ROOT))
    print(f"  [Frio {iteration}/3] Ejecutando subprocess...")
    t_start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=120,
        cwd=str(PROJECT_ROOT)
    )
    elapsed = round((time.perf_counter() - t_start) * 1000, 1)
    try:
        data = json.loads(proc.stdout.strip().split("\n")[-1])
    except (json.JSONDecodeError, IndexError):
        data = {"error": proc.stdout + proc.stderr, "elapsed_ms": elapsed}
    data["wall_clock_ms"] = elapsed
    return data

def measure_hot(iteration: int) -> dict:
    """Mide inicio en caliente: re-import en mismo proceso."""
    script = COLD_SCRIPT.replace("PROJROOT", str(PROJECT_ROOT))
    # Primera ejecucion (carga modulo en sys.modules)
    print(f"  [Caliente {iteration}/3] Primera carga...")
    proc1 = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=120,
        cwd=str(PROJECT_ROOT)
    )
    # Segunda ejecucion en mismo proceso via -c
    hot_script = textwrap.dedent(r'''
import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(r"PROJROOT")))

# Forzar re-import midiendo tiempo
t0 = time.perf_counter()
from app.database.database import ImageDatabase
from app.ui.main_window import VisionVaultApp
import_time = round((time.perf_counter() - t0) * 1000, 2)

import tkinter as tk
t1 = time.perf_counter()
try:
    app = VisionVaultApp()
    app_time = round((time.perf_counter() - t1) * 1000, 2)
    import tracemalloc
    tracemalloc.start()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    try:
        app.destroy()
    except:
        pass
    result = {"import_ms": import_time, "app_init_ms": app_time,
              "mem_current": current, "mem_peak": peak}
except Exception as e:
    result = {"import_ms": import_time, "app_init_ms": -1, "error": str(e)}
print(json.dumps(result))
''').replace("PROJROOT", str(PROJECT_ROOT))
    print(f"  [Caliente {iteration}/3] Segunda carga (hot)...")
    t_start = time.perf_counter()
    proc2 = subprocess.run(
        [sys.executable, "-c", hot_script],
        capture_output=True, text=True, timeout=120,
        cwd=str(PROJECT_ROOT)
    )
    elapsed = round((time.perf_counter() - t_start) * 1000, 1)
    try:
        data = json.loads(proc2.stdout.strip().split("\n")[-1])
    except (json.JSONDecodeError, IndexError):
        data = {"error": proc2.stdout + proc2.stderr}
    data["wall_clock_ms"] = elapsed
    return data

if __name__ == "__main__":
    print("=" * 60)
    print("MEDICION DE INICIO - Doccione Studio")
    print("=" * 60)

    cold_results = []
    hot_results = []

    print("\n--- Mediciones en FRIO (subprocess nuevo) ---")
    for i in range(1, 4):
        r = measure_cold(i)
        cold_results.append(r)
        print(f"  Resultado {i}: {r.get('wall_clock_ms', '?')} ms total, "
              f"DB init: {r.get('db_init_time_ms', '?')} ms, "
              f"App init: {r.get('app_init_time_ms', '?')} ms")
        time.sleep(2)

    print("\n--- Mediciones en CALIENTE (mismo proceso) ---")
    for i in range(1, 4):
        r = measure_hot(i)
        hot_results.append(r)
        print(f"  Resultado {i}: {r.get('wall_clock_ms', '?')} ms total")
        time.sleep(1)

    # Resumen
    cold_wall = [r.get("wall_clock_ms", 0) for r in cold_results if "wall_clock_ms" in r]
    hot_wall = [r.get("wall_clock_ms", 0) for r in hot_results if "wall_clock_ms" in r]
    cold_db = [r.get("db_init_time_ms", 0) for r in cold_results if "db_init_time_ms" in r]
    cold_app = [r.get("app_init_time_ms", 0) for r in cold_results if "app_init_time_ms" in r and r.get("app_init_time_ms", -1) > 0]

    summary = {
        "cold_start": {
            "avg_wall_ms": round(sum(cold_wall)/len(cold_wall), 1) if cold_wall else None,
            "measurements": cold_wall,
            "avg_db_init_ms": round(sum(cold_db)/len(cold_db), 1) if cold_db else None,
            "avg_app_init_ms": round(sum(cold_app)/len(cold_app), 1) if cold_app else None,
        },
        "hot_start": {
            "avg_wall_ms": round(sum(hot_wall)/len(hot_wall), 1) if hot_wall else None,
            "measurements": hot_wall,
        },
        "cold_raw": cold_results,
        "hot_raw": hot_results,
    }

    # Guardar import times del primer resultado cold
    if cold_results and "import_times" in cold_results[0]:
        summary["import_times"] = cold_results[0]["import_times"]
    if cold_results and "table_count" in cold_results[0]:
        summary["table_count"] = cold_results[0]["table_count"]
        summary["index_count"] = cold_results[0]["index_count"]
        summary["total_widgets"] = cold_results[0].get("total_widgets")
        summary["memory_peak_bytes"] = cold_results[0].get("memory_peak_bytes")

    with open(RESULTS_FILE, "w") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"  Frio  avg: {summary['cold_start']['avg_wall_ms']} ms")
    print(f"  Caliente avg: {summary['hot_start']['avg_wall_ms']} ms")
    print(f"  DB init avg: {summary['cold_start']['avg_db_init_ms']} ms")
    print(f"  App init avg: {summary['cold_start']['avg_app_init_ms']} ms")
    print(f"  Tablas: {summary.get('table_count')}, Indices: {summary.get('index_count')}")
    print(f"  Widgets: {summary.get('total_widgets')}")
    print(f"  Memoria pico: {summary.get('memory_peak_bytes', 0) / 1024 / 1024:.1f} MB")
    print(f"\nResultados guardados en: {RESULTS_FILE}")
