"""Mide la bandeja V2 con imágenes reales sin modificar datos de usuario."""

from __future__ import annotations

import json
import gc
import os
import statistics
import sys
import time
import tkinter as tk
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

WORKSPACE = Path(__file__).resolve().parents[1]
CODE_ROOT = Path(os.environ.get("STICKER_CODE_ROOT", WORKSPACE)).resolve()
sys.path.insert(0, str(CODE_ROOT))

from app.stickers.editor_v2.components import ThumbnailTray


INPUTS = WORKSPACE / "artifacts" / "sticker-studio-sprint15" / "batch20" / "inputs"
OUTPUT = Path(os.environ.get(
    "STICKER_BENCHMARK_OUTPUT",
    WORKSPACE / "artifacts" / "sticker-performance-2.0.2" / "thumbnail_tray_benchmark.json"))


def elapsed_ms(action) -> float:
    started = time.perf_counter()
    action()
    return (time.perf_counter() - started) * 1000


def active_cards(tray) -> int:
    return int(getattr(tray, "active_card_count", len(tray.inner.winfo_children())))


def scroll_and_render(tray, host, fraction: float) -> None:
    tray.canvas.xview_moveto(fraction)
    render_visible = getattr(tray, "_render_visible", None)
    if render_visible is not None:
        render_visible()
    host.update_idletasks()


def drain_thumbnails(tray, host, timeout=10.0) -> None:
    deadline = time.perf_counter() + timeout
    while getattr(tray, "_thumbnail_queue", None) and time.perf_counter() < deadline:
        host.update()


def working_set_mb() -> float:
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]
    counters = Counters(); counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.K32GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return counters.WorkingSetSize / 1048576


def main() -> None:
    paths = sorted(INPUTS.glob("*.png"))
    if len(paths) < 20:
        raise SystemExit(f"Se requieren 20 entradas reales en {INPUTS}")

    root = tk.Tk(); root.withdraw()
    results = []
    for count in (20, 50, 100, 200):
        jobs = []
        for index in range(count):
            path = paths[index % len(paths)]
            result = SimpleNamespace(artifacts={"master": str(path)}, quality_status="Listo")
            jobs.append({"source_path": str(path), "status": "Procesado", "result": result})

        host = tk.Toplevel(root); host.geometry("900x150+0+0")
        tray = ThumbnailTray(host, lambda *_args, **_kwargs: None)
        tray.pack(fill="both", expand=True); host.update()
        gc.collect(); tracemalloc.start()
        memory_before = working_set_mb()
        cold_ms = elapsed_ms(lambda: (tray.refresh(jobs, {0}), host.update_idletasks(),
                                      drain_thumbnails(tray, host)))

        cached_samples = []
        for selected in range(1, 6):
            cached_samples.append(elapsed_ms(
                lambda selected=selected: (tray.refresh(jobs, {selected}), host.update_idletasks())))

        scroll_samples = []
        scroll_settle_samples = []
        live_counts = [active_cards(tray)]
        for fraction in (.1, .3, .5, .7, .9, 0):
            scroll_samples.append(elapsed_ms(
                lambda fraction=fraction: scroll_and_render(tray, host, fraction)))
            scroll_settle_samples.append(elapsed_ms(
                lambda: drain_thumbnails(tray, host)))
            live_counts.append(active_cards(tray))
        incremental_samples = []
        for _ in range(30):
            incremental_samples.append(elapsed_ms(
                lambda: (tray.canvas.xview_scroll(1, "units"),
                         getattr(tray, "_render_visible", lambda: None)(),
                         host.update_idletasks())))

        _current_allocated, peak_allocated = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        results.append({
            "items": count,
            "cold_ms": round(cold_ms, 3),
            "cached_selection_median_ms": round(statistics.median(cached_samples), 3),
            "scroll_median_ms": round(statistics.median(scroll_samples), 3),
            "scroll_p95_ms": round(sorted(scroll_samples)[-1], 3),
            "scroll_settle_median_ms": round(statistics.median(scroll_settle_samples), 3),
            "wheel_scroll_median_ms": round(statistics.median(incremental_samples), 3),
            "wheel_scroll_p95_ms": round(sorted(incremental_samples)[-2], 3),
            "active_cards_max": max(live_counts),
            "tk_widgets": len(tray.inner.winfo_children()),
            "working_set_delta_mb": round(working_set_mb() - memory_before, 2),
            "python_peak_allocated_mb": round(peak_allocated / 1048576, 2),
        })
        host.destroy(); gc.collect()

    root.destroy()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"results": results}, indent=2), encoding="utf-8")
    print(json.dumps({"results": results}, indent=2))


if __name__ == "__main__":
    main()
