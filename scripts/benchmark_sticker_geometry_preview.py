"""Mide la reutilización exacta de geometría sobre una máscara real."""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

WORKSPACE = Path(__file__).resolve().parents[1]
CODE_ROOT = Path(os.environ.get("STICKER_CODE_ROOT", WORKSPACE)).resolve()
sys.path.insert(0, str(CODE_ROOT))

from app.stickers.mask_editing import MaskEditDocument
from app.stickers.editor_v2.window import StickerStudioV2

MASK = WORKSPACE / "artifacts/sticker-halo-real-20261019-v2/mask_before_contraction.png"
OUTPUT = Path(os.environ.get(
    "STICKER_BENCHMARK_OUTPUT",
    WORKSPACE / "artifacts/sticker-performance-2.0.2/geometry_preview_benchmark.json"))


def main() -> None:
    with Image.open(MASK) as image:
        base = image.convert("L").copy()
    document = MaskEditDocument.for_base(base)
    owner = SimpleNamespace(_v2_geometry_cache=OrderedDict(), _v2_geometry_cache_bytes=0,
                            _v2_geometry_cache_limit=64 * 1024 * 1024)
    cached_renderer = getattr(StickerStudioV2, "_render_geometry_preview", None)
    samples = []
    hashes = []
    for _ in range(12):
        started = time.perf_counter()
        if cached_renderer is None:
            mask, protection, report = document.render(base, .2, 300.0, .08)
        else:
            mask, protection, report = cached_renderer(owner, document, base, .2, 300.0, .08)
        samples.append((time.perf_counter() - started) * 1000)
        hashes.append(hash((mask.tobytes(), protection.tobytes(), tuple(report.warnings))))
    report = {
        "implementation": "cached" if cached_renderer else "uncached",
        "first_ms": round(samples[0], 3),
        "repeated_median_ms": round(statistics.median(samples[1:]), 3),
        "repeated_p95_ms": round(sorted(samples[1:])[-1], 3),
        "all_results_equal": len(set(hashes)) == 1,
        "iterations": len(samples),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
