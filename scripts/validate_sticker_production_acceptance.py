"""Homologación reproducible del candidato Sticker Studio 2.0.

Usa las 20 entradas preservadas del Sprint 1.5; no crea ni reescala originales
y nunca marca una máscara como aprobada.
"""

from __future__ import annotations

import gc
import hashlib
import json
from pathlib import Path
import shutil
import sys
import threading
import time

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.stickers.editor_v2.adapter import PipelineViewAdapter
from app.stickers.models import ProcessingProfile
from app.stickers.pipeline import ProcessingCancelled, StickerProcessor

OUT = ROOT / "artifacts/sticker-studio-production-candidate"
INPUTS = ROOT / "artifacts/sticker-studio-sprint15/batch20/inputs"
WORK = OUT / "pipeline"


def digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def memory_counters() -> tuple[int, int]:
    """Working set y pico real del proceso actual en Windows."""
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
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    query = kernel.K32GetProcessMemoryInfo
    query.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD)
    query.restype = wintypes.BOOL
    if not query(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise OSError("No se pudo consultar el working set del proceso.")
    return int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize)


def run() -> None:
    paths = sorted(INPUTS.glob("*.png"))
    if len(paths) != 20:
        raise RuntimeError(f"Se requieren exactamente 20 entradas preservadas; hay {len(paths)}.")
    OUT.mkdir(parents=True, exist_ok=True)
    exports = OUT / "exports"; exports.mkdir(exist_ok=True)
    processor = StickerProcessor(WORK, ProcessingProfile())

    rss_before, _ = memory_counters()
    peak_sampled = rss_before
    monitoring = True
    def monitor() -> None:
        nonlocal peak_sampled
        while monitoring:
            peak_sampled = max(peak_sampled, memory_counters()[0])
            time.sleep(.02)
    thread = threading.Thread(target=monitor, daemon=True); thread.start()

    open_started = time.perf_counter()
    for path in paths:
        with Image.open(path) as image:
            image.load()
    open_seconds = time.perf_counter() - open_started

    wall_started = time.perf_counter(); cpu_started = time.process_time()
    items = []
    for path in paths:
        started = time.perf_counter(); result = None; error = None
        try:
            result = processor.process(path, automatic_recovery=False)
            master = Path(result.artifacts["master"])
            destination = exports / f"{path.stem}_sticker.png"
            PipelineViewAdapter.export_final(master, destination)
            master_sha = digest(master); export_sha = digest(destination)
            if master_sha != export_sha:
                raise AssertionError("Exportación distinta del master.")
            with Image.open(master) as image:
                mode, size = image.mode, list(image.size)
            if mode != "RGBA":
                raise AssertionError(f"Master no RGBA: {mode}")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            master_sha = export_sha = None; size = None
        items.append({
            "input": str(path), "input_sha256": digest(path), "seconds": round(time.perf_counter()-started, 4),
            "error": error, "quality": getattr(result, "quality_status", None),
            "master": result.artifacts.get("master") if result else None,
            "master_sha256": master_sha, "export_sha256": export_sha,
            "master_equals_export": bool(master_sha and master_sha == export_sha),
            "master_size": size,
        })
    wall_seconds = time.perf_counter() - wall_started
    cpu_seconds = time.process_time() - cpu_started

    cancelled = {"value": False}
    def progress(percent, _message):
        if percent >= 35: cancelled["value"] = True
    cancellation = {"cancelled": False, "retry_ok": False}
    try:
        processor.process(paths[0], progress=progress, cancelled=lambda: cancelled["value"],
                          automatic_recovery=False)
    except ProcessingCancelled:
        cancellation["cancelled"] = True
    retry_started = time.perf_counter()
    retry = processor.process(paths[0], automatic_recovery=False)
    cancellation.update(retry_ok=Path(retry.artifacts["master"]).is_file(),
                        retry_seconds=round(time.perf_counter()-retry_started, 4))

    switch_started = time.perf_counter()
    for item in items:
        if item["master"]:
            with Image.open(item["master"]) as image:
                preview = image.convert("RGBA"); preview.thumbnail((1200, 800), Image.Resampling.LANCZOS)
                preview.load()
    switch_seconds = time.perf_counter() - switch_started

    monitoring = False; thread.join(timeout=1)
    gc.collect(); time.sleep(.2); gc.collect()
    rss_after_release, peak_native = memory_counters()
    report = {
        "candidate": "2.0.0-rc.1", "human_approval_performed": False,
        "dataset": {"count": len(paths), "kind": "preserved_real_content_load_derivatives",
                    "minimum_pixels": min(Image.open(p).width*Image.open(p).height for p in paths),
                    "maximum_pixels": max(Image.open(p).width*Image.open(p).height for p in paths)},
        "functional": {
            "successful": sum(not item["error"] for item in items),
            "errors": sum(bool(item["error"]) for item in items),
            "master_export_identical": sum(item["master_equals_export"] for item in items),
            "cancellation_and_retry": cancellation,
        },
        "performance": {
            "open_20_seconds": round(open_seconds, 4),
            "processing_wall_seconds": round(wall_seconds, 4),
            "processing_cpu_seconds": round(cpu_seconds, 4),
            "average_cpu_percent_one_core_equivalent": round(cpu_seconds/max(wall_seconds, .001)*100, 1),
            "switch_20_previews_seconds": round(switch_seconds, 4),
            "average_switch_ms": round(switch_seconds/len(paths)*1000, 3),
            "rss_before_mb": round(rss_before/1048576, 2),
            "peak_rss_mb": round(max(peak_sampled, peak_native)/1048576, 2),
            "rss_after_release_mb": round(rss_after_release/1048576, 2),
            "retained_delta_mb": round((rss_after_release-rss_before)/1048576, 2),
        },
        "items": items,
        "decision": "PENDIENTE DE VALIDACIÓN HUMANA Y FÍSICA",
    }
    (OUT / "acceptance_metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**report["functional"], **report["performance"]}, ensure_ascii=False))


if __name__ == "__main__":
    run()
