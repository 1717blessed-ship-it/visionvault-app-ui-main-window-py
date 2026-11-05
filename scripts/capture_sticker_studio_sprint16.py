"""Captura reproducible de la interfaz real de Sticker Studio 2.0."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace
import tkinter as tk

from PIL import Image, ImageDraw, ImageGrab

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from app.stickers.editor_v2.window import StickerStudioV2


class _Database:
    def category_counts(self): return []
    def sticker_processing_jobs(self, limit=500): return []
    def indexed_visual_search_images(self): return []
    def save_sticker_processing(self, result, category="", tags=None): return None
    def discard_processed_sticker(self, job_id): return None


def main() -> None:
    repository = REPOSITORY
    output = repository / "artifacts" / "sticker-studio-sprint16"
    output.mkdir(parents=True, exist_ok=True)
    source = output / "interface_capture_source.png"
    mask = output / "interface_capture_mask.png"
    master = output / "interface_capture_master.png"

    image = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((95, 80, 505, 490), fill=(232, 52, 139, 255),
                 outline=(255, 255, 255, 255), width=24)
    draw.polygon(((300, 25), (335, 120), (435, 120), (355, 180),
                  (385, 280), (300, 220), (215, 280), (245, 180),
                  (165, 120), (265, 120)), fill=(242, 242, 242, 255))
    image.save(source, dpi=(300, 300))
    image.getchannel("A").save(mask)
    image.save(master, dpi=(300, 300))

    session = output / "capture-session"
    session.mkdir(exist_ok=True)
    previous = Path.cwd()
    os.chdir(session)
    root = tk.Tk()
    root.withdraw()
    studio = StickerStudioV2(root, _Database())
    studio.geometry("1360x820+20+20")
    studio.add_paths([source], run_queue=False)
    job = studio.jobs[0]
    job.update(
        status="Procesado", selection_contraction_mm=0.2,
        border_treatment="Conservar y limpiar", review_state="Revisión requerida",
        result=SimpleNamespace(
            job_id="sprint16-capture", quality_status="Revisar",
            quality_notes=[], confidence=0.92,
            artifacts={"mask": str(mask), "design_layer": str(source),
                       "master": str(master), "print": str(master)},
            analysis={"border_treatment": {"effective": "Conservar y limpiar"},
                      "quality_report": {"warnings": [
                          {"message": "Validar detalles finos antes de aprobar."}]}}))
    studio.current_index = 0
    studio._v2_selection.indices = {0}
    studio._v2_sync(force=True)
    studio.deiconify()
    studio.lift()
    studio.update_idletasks()
    studio.update()
    studio._fit_canvas()
    studio.update()
    left, top = studio.winfo_rootx(), studio.winfo_rooty()
    right, bottom = left + studio.winfo_width(), top + studio.winfo_height()
    ImageGrab.grab((left, top, right, bottom), all_screens=True).save(
        output / "sticker_studio_2_sprint16.png")
    studio.close()
    root.destroy()
    os.chdir(previous)


if __name__ == "__main__":
    main()
