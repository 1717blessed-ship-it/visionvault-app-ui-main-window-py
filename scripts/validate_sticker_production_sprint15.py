"""Carga operativa reproducible de 20 stickers con métricas del proceso."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.stickers.models import ProcessingProfile
from app.stickers.pipeline import ProcessingCancelled, StickerProcessor
from app.stickers.editor_v2.adapter import PipelineViewAdapter

OUT = ROOT / "artifacts/sticker-studio-sprint15/batch20"
INPUTS = OUT / "inputs"
WORK = OUT / "pipeline"

BASES = [
    ROOT / "validation_output/07_alta_resolucion_2000_original.png",
    ROOT / "final_validation/corazon_anatomico_clean.png",
    ROOT / "final_validation/hoja_clara_clean.png",
    ROOT / "final_validation/estetoscopio_rosa_clean.png",
    ROOT / "corrected_stickers/rapunzel-flynn-corrected.png",
    ROOT / "corrected_stickers/cinderella-prince-corrected.png",
    ROOT / "corrected_stickers/iconic-corrected.png",
    ROOT / "artifacts/sticker-disc-human-review/original.png",
    ROOT / "artifacts/sticker-disc-human-review/visual_support_600_OPAQUE.png",
    ROOT / "validation_output/04_transparencia_original.png",
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rss_bytes():
    """Working set real del proceso en Windows, sin dependencia externa."""
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    counters = Counters(); counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    query = kernel.K32GetProcessMemoryInfo
    query.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD)
    query.restype = wintypes.BOOL
    handle = kernel.GetCurrentProcess()
    if not query(handle, ctypes.byref(counters), counters.cb):
        raise OSError("No se pudo leer la memoria del proceso.")
    return int(counters.WorkingSetSize)


def prepare_inputs():
    INPUTS.mkdir(parents=True, exist_ok=True)
    targets = (2000, 1800, 1600, 1400, 1200, 1000, 900, 800, 700, 600,
               2000, 1800, 1600, 1400, 1200, 1000, 900, 800, 700, 600)
    manifest = []
    for index, target in enumerate(targets):
        source = BASES[index % len(BASES)]
        if not source.is_file():
            raise FileNotFoundError(source)
        with Image.open(source) as opened:
            image = opened.convert("RGBA")
            scale = target / max(image.size)
            size = (max(1, round(image.width*scale)), max(1, round(image.height*scale)))
            if image.size != size:
                image = image.resize(size, Image.Resampling.LANCZOS)
            destination = INPUTS / f"{index+1:02d}_{source.stem}_{size[0]}x{size[1]}.png"
            image.save(destination)
        manifest.append({"path": str(destination), "source": str(source),
                         "dimensions": list(size), "source_kind": "real_content_load_derivative"})
    return manifest


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = prepare_inputs()
    processor = StickerProcessor(WORK, ProcessingProfile())
    running, peak_rss = True, rss_bytes()
    def sample():
        nonlocal peak_rss
        while running:
            peak_rss = max(peak_rss, rss_bytes())
            time.sleep(.02)
    monitor = threading.Thread(target=sample, daemon=True); monitor.start()
    started = time.perf_counter(); results = []
    exports = OUT / "exports"; exports.mkdir(exist_ok=True)
    for index, entry in enumerate(manifest):
        path = Path(entry["path"]); item_started = time.perf_counter()
        before = rss_bytes()
        status, error, result = "Requiere revisión", None, None
        try:
            result = processor.process(path, automatic_recovery=False)
            destination = exports / f"{path.stem}_sticker.png"
            PipelineViewAdapter.export_final(result.artifacts["master"], destination)
            if sha(destination) != sha(result.artifacts["master"]):
                raise AssertionError("La exportación no coincide byte a byte con el master.")
        except Exception as exc:
            status, error = "Error", f"{type(exc).__name__}: {exc}"
        results.append({**entry, "status": status, "error": error,
                        "seconds": round(time.perf_counter()-item_started, 4),
                        "rss_delta_mb": round((rss_bytes()-before)/1048576, 2),
                        "quality": getattr(result, "quality_status", None),
                        "export": str(destination) if result else None})
    # Cancelación cooperativa real y reintento del mismo original desde cero.
    cancelled = {"value": False}
    def progress(percent, _message):
        if percent >= 35: cancelled["value"] = True
    cancellation = {"status": "BLOQUEADO"}
    try:
        processor.process(manifest[0]["path"], progress=progress,
                          cancelled=lambda: cancelled["value"], automatic_recovery=False)
    except ProcessingCancelled:
        cancellation = {"status": "APROBADO", "cancelled_at_or_after_percent": 35}
    retry_started = time.perf_counter()
    retry = processor.process(manifest[0]["path"], automatic_recovery=False)
    cancellation["retry_status"] = "Requiere revisión"
    cancellation["retry_seconds"] = round(time.perf_counter()-retry_started, 4)
    running = False; monitor.join(timeout=1)
    report = {
        "dataset": manifest, "items": results,
        "summary": {"count": len(results),
                    "successful": sum(r["status"] != "Error" for r in results),
                    "errors": sum(r["status"] == "Error" for r in results),
                    "total_seconds": round(time.perf_counter()-started, 4),
                    "peak_rss_mb": round(peak_rss/1048576, 2),
                    "largest_pixels": max(w*h for w, h in (r["dimensions"] for r in results)),
                    "smallest_pixels": min(w*h for w, h in (r["dimensions"] for r in results))},
        "cancellation_and_retry": cancellation,
        "approval": "REQUIERE VALIDACIÓN HUMANA",
    }
    (OUT / "benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    run()
