"""Perfilamiento con cProfile del inicio de Doccione Studio.
Ejecuta: python measure_cprofile.py
"""
import cProfile, pstats, json, sys, io
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

def run_startup():
    from app.database.database import ImageDatabase
    db = ImageDatabase(PROJECT_ROOT / "visionvault.db")
    return db

if __name__ == "__main__":
    print("Profiling ImageDatabase.__init__ con cProfile...")
    profiler = cProfile.Profile()
    profiler.enable()
    db = run_startup()
    profiler.disable()

    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats("cumulative")
    stats.print_stats(40)
    print(stream.getvalue())

    # Top 20 por tiempo total
    stream2 = io.StringIO()
    stats2 = pstats.Stats(profiler, stream=stream2)
    stats2.sort_stats("tottime")
    stats2.print_stats(20)
    print("\n--- Top 20 por tiempo total ---")
    print(stream2.getvalue())

    # Guardar datos
    results = []
    for func in stats.stats:
        filename, lineno, funcname = func
        cc, nc, tt, ct, callers = stats.stats[func]
        results.append({
            "file": filename,
            "line": lineno,
            "function": funcname,
            "ncalls": nc,
            "tottime_ms": round(tt * 1000, 2),
            "cumtime_ms": round(ct * 1000, 2),
        })
    results.sort(key=lambda x: x["tottime_ms"], reverse=True)
    with open(PROJECT_ROOT / "cprofile_results.json", "w") as f:
        json.dump(results[:50], f, indent=2)
    print(f"Top 50 funciones guardadas en cprofile_results.json")

    db.close()
