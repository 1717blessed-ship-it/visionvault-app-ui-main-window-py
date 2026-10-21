"""Mide interacción del Canvas V2 antes/después sin alterar datos de usuario."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
try:
    import psutil
except ImportError:
    psutil = None

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.stickers.editor_v2.canvas import StickerCanvas
from app.stickers.editor_v2.state import CanvasState


def milliseconds(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 3)


def main():
    output = Path("artifacts/sticker-studio-sprint16")
    output.mkdir(parents=True, exist_ok=True)
    source = output / "benchmark_2000.png"
    if not source.is_file():
        image = Image.new("RGBA", (2000, 2000), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((120, 120, 1880, 1880), fill=(225, 45, 110, 255))
        image.save(source)

    root = tk.Tk(); root.withdraw()
    process = psutil.Process() if psutil else None
    rss_before = process.memory_info().rss if process else None
    host = tk.Toplevel(root); host.geometry("900x700+0+0")
    canvas = StickerCanvas(host); canvas.pack(fill="both", expand=True)
    job = {"source_path": str(source.resolve()),
           "result": SimpleNamespace(artifacts={"master": str(source.resolve())})}
    state = CanvasState(mode="Final", zoom=.34, fitted=False)
    canvas.show_job(job, state); host.update()

    start = time.perf_counter()
    for index in range(30):
        state.pan_x = index * 3; state.pan_y = index * 2
        canvas.render(); host.update_idletasks()
    full_pan_ms = milliseconds(start)

    start = time.perf_counter()
    canvas._pan_start(SimpleNamespace(x=100, y=100))
    for index in range(30):
        canvas._pan_move(SimpleNamespace(x=100 + index * 3, y=100 + index * 2))
        host.update_idletasks()
    fast_pan_ms = milliseconds(start)

    start = time.perf_counter()
    for _ in range(20):
        state.set_zoom(state.zoom * 1.01); canvas.render(); host.update_idletasks()
    direct_zoom_ms = milliseconds(start)

    start = time.perf_counter()
    event = SimpleNamespace(delta=120, x=450, y=350)
    for _ in range(20):
        canvas._wheel(event)
    host.update(); host.after(25, host.quit); host.mainloop()
    throttled_zoom_ms = milliseconds(start)

    result = {
        "image": "2000x2000 RGBA", "iterations": {"pan": 30, "zoom": 20},
        "full_recomposition_pan_ms": full_pan_ms,
        "fast_transform_pan_ms": fast_pan_ms,
        "pan_speedup": round(full_pan_ms / max(fast_pan_ms, .001), 2),
        "direct_zoom_ms": direct_zoom_ms,
        "throttled_zoom_ms": throttled_zoom_ms,
        "zoom_speedup": round(direct_zoom_ms / max(throttled_zoom_ms, .001), 2),
        "cache_limit_mb": canvas._image_cache_limit // (1024 * 1024),
        "working_set_before_mb": round(rss_before / 1048576, 2) if rss_before else None,
        "working_set_after_mb": round(process.memory_info().rss / 1048576, 2) if process else None,
    }
    (output / "canvas_benchmark.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    host.destroy(); root.destroy()


if __name__ == "__main__":
    main()
