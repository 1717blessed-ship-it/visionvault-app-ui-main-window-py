"""Mide widgets, after() callbacks, y archivos escaneados durante el inicio.
Ejecuta: python measure_widgets.py
"""
import sys, json, time, os, tracemalloc
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Interceptar os.scandir y Path.iterdir para contar archivos escaneados
scanned_files = []
original_scandir = os.scandir

def patched_scandir(path=None):
    scanned_files.append(str(path))
    return original_scandir(path)

os.scandir = patched_scandir

if __name__ == "__main__":
    from app.database.database import ImageDatabase

    t0 = time.perf_counter()
    from app.ui.main_window import VisionVaultApp
    import_time = round((time.perf_counter() - t0) * 1000, 1)

    tracemalloc.start()

    t1 = time.perf_counter()
    try:
        app = VisionVaultApp()
        app_time = round((time.perf_counter() - t1) * 1000, 1)
    except Exception as e:
        print(json.dumps({"error": str(e), "import_ms": import_time}))
        sys.exit(1)

    # Contar widgets
    def count_widgets(widget, depth=0):
        result = []
        for child in widget.winfo_children():
            wtype = child.winfo_class()
            result.append({"type": wtype, "path": str(child), "depth": depth})
            result.extend(count_widgets(child, depth + 1))
        return result

    all_widgets = count_widgets(app)
    widget_types = {}
    for w in all_widgets:
        t = w["type"]
        widget_types[t] = widget_types.get(t, 0) + 1

    # Contar after() callbacks
    after_count = -1
    try:
        after_info = str(app.tk.call('info', 'after'))
        if after_info.strip():
            after_count = len([x for x in after_info.split() if x.strip()])
    except Exception:
        pass

    # Memoria
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Archivos escaneados
    scanned_dirs = list(set(scanned_files))

    # Cerrar
    try:
        app.destroy()
    except Exception:
        pass

    result = {
        "import_time_ms": import_time,
        "app_init_time_ms": app_time,
        "total_widgets": len(all_widgets),
        "widget_types": widget_types,
        "after_callbacks": after_count,
        "memory_current_mb": round(current / 1024 / 1024, 2),
        "memory_peak_mb": round(peak / 1024 / 1024, 2),
        "scanned_dirs_count": len(scanned_dirs),
        "scanned_dirs_sample": scanned_dirs[:30],
    }

    with open(PROJECT_ROOT / "widgets_results.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"Import: {import_time} ms")
    print(f"App init: {app_time} ms")
    print(f"Total widgets: {len(all_widgets)}")
    print(f"Widget types: {json.dumps(widget_types, indent=2)}")
    print(f"After callbacks: {after_count}")
    print(f"Memory: {result['memory_current_mb']} MB (current), {result['memory_peak_mb']} MB (peak)")
    print(f"Dirs scanned: {len(scanned_dirs)}")
    print(f"\nResultados guardados en widgets_results.json")
