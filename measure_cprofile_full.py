"""cProfile del VisionVaultApp.__init__ completo."""
import cProfile, pstats, json, sys, io, time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

def run_full_startup():
    from app.database.database import ImageDatabase
    from app.ui.main_window import VisionVaultApp
    db = ImageDatabase(PROJECT_ROOT / "visionvault.db")
    app = VisionVaultApp()
    return db, app

if __name__ == "__main__":
    print("Profiling full VisionVaultApp.__init__...")
    profiler = cProfile.Profile()
    profiler.enable()
    db, app = run_full_startup()
    profiler.disable()

    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats("cumulative")
    stats.print_stats(50)
    print(stream.getvalue())

    # Top 30 por tottime
    stream2 = io.StringIO()
    stats2 = pstats.Stats(profiler, stream=stream2)
    stats2.sort_stats("tottime")
    stats2.print_stats(30)
    print("\n--- Top 30 por tottime ---")
    print(stream2.getvalue())

    # Guardar
    results = []
    for func in stats.stats:
        filename, lineno, funcname = func
        cc, nc, tt, ct, callers = stats.stats[func]
        results.append({
            "file": filename, "line": lineno, "function": funcname,
            "ncalls": nc, "tottime_ms": round(tt * 1000, 2),
            "cumtime_ms": round(ct * 1000, 2),
        })
    results.sort(key=lambda x: x["tottime_ms"], reverse=True)
    with open(PROJECT_ROOT / "cprofile_full_results.json", "w") as f:
        json.dump(results[:60], f, indent=2)

    try:
        app.destroy()
    except:
        pass
    db.close()
    print(f"\nGuardado en cprofile_full_results.json")
