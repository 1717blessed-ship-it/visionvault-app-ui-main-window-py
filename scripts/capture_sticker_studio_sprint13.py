"""Captura local del Canvas V2 con un original real ya procesado."""

from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
import sys

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.stickers.editor_v2.window import StickerStudioV2


class EmptyDatabase:
    def category_counts(self): return []
    def sticker_processing_jobs(self, limit=500): return []


def main():
    source = ROOT / "artifacts/sticker-disc-human-review/original.png"
    run = next((ROOT / "artifacts/sticker-mask-contraction-sprint12/disc_421/0.2mm/pipeline").iterdir())
    artifacts = {
        "source_editable": str(run / "source_editable.png"),
        "selection_alpha_original": str(run / "selection_alpha_original.png"),
        "mask_editable": str(run / "mask_editable.png"),
        "master": str(run / "07_final_master.png"),
        "design_layer": str(run / "06_design_layer.png"),
        "cut": str(run / "10_cut.png"),
    }
    root = tk.Tk(); root.withdraw()
    studio = StickerStudioV2(root, EmptyDatabase())
    studio.geometry("1220x760+30+30")
    result = SimpleNamespace(artifacts=artifacts, analysis={"source_processing_dpi": 201.762},
                             quality_status="REVISAR · referencia humana pendiente")
    job = {"source_path": str(source), "status": "Procesado", "result": result,
           "selection_contraction_mm": .2, "selection_expansion_mm": 0,
           "selection_smoothing_mm": .1}
    studio.jobs[:] = [job]; studio.current_index = 0
    studio._v2_sync(force=True); studio._tool_action("mask")
    studio.update_idletasks(); studio.update()
    x, y = studio.winfo_rootx(), studio.winfo_rooty()
    target = ROOT / "artifacts/sticker-studio-sprint14/editor_operational.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab((x, y, x+studio.winfo_width(), y+studio.winfo_height())).save(target)
    studio.destroy(); root.destroy()
    print(target)


if __name__ == "__main__":
    main()
