"""Mide la bandeja V2 con imágenes reales sin modificar datos de usuario."""

from __future__ import annotations

import json
import statistics
import sys
import time
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.stickers.editor_v2.components import ThumbnailTray


INPUTS = ROOT / "artifacts" / "sticker-studio-sprint15" / "batch20" / "inputs"
OUTPUT = ROOT / "artifacts" / "sticker-performance-2.0.1-optimized" / "thumbnail_tray_benchmark.json"


def elapsed_ms(action) -> float:
    started = time.perf_counter()
    action()
    return (time.perf_counter() - started) * 1000


def main() -> None:
    paths = sorted(INPUTS.glob("*.png"))
    if len(paths) < 20:
        raise SystemExit(f"Se requieren 20 entradas reales en {INPUTS}")

    root = tk.Tk()
    root.withdraw()
    tray = ThumbnailTray(root, lambda *_args, **_kwargs: None)
    results = []
    for count in (20, 50, 100):
        jobs = []
        for index in range(count):
            path = paths[index % len(paths)]
            result = SimpleNamespace(artifacts={"master": str(path)}, quality_status="Listo")
            jobs.append({"source_path": str(path), "status": "Procesado", "result": result})

        tray._signature = None
        tray._thumbnail_cache.clear()
        cold_ms = elapsed_ms(lambda: (tray.refresh(jobs, {0}), root.update_idletasks()))

        cached_samples = []
        for selected in range(1, 6):
            cached_samples.append(elapsed_ms(
                lambda selected=selected: (tray.refresh(jobs, {selected}), root.update_idletasks())))

        uncached_samples = []
        for selected in range(6, 11):
            tray._thumbnail_cache.clear()
            uncached_samples.append(elapsed_ms(
                lambda selected=selected: (tray.refresh(jobs, {selected}), root.update_idletasks())))

        results.append({
            "items": count,
            "cold_ms": round(cold_ms, 3),
            "cached_selection_median_ms": round(statistics.median(cached_samples), 3),
            "uncached_selection_median_ms": round(statistics.median(uncached_samples), 3),
            "selection_speedup": round(
                statistics.median(uncached_samples) / max(statistics.median(cached_samples), 0.001), 2),
        })

    tray.destroy()
    root.destroy()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"results": results}, indent=2), encoding="utf-8")
    print(json.dumps({"results": results}, indent=2))


if __name__ == "__main__":
    main()
