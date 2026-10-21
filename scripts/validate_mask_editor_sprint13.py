"""Evidencia reproducible de Sprint 1.3; nunca aprueba una referencia."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.stickers.mask_editing import MaskEditDocument, MaskStroke
from app.stickers.models import ProcessingProfile
from app.stickers.pipeline import StickerProcessor


OUT = ROOT / "artifacts" / "sticker-mask-editor-sprint13"
SOURCES = {
    "disc_421": ROOT / "artifacts/sticker-disc-human-review/original.png",
    "chrome_stars_600": ROOT / "artifacts/sticker-disc-human-review/visual_support_600_OPAQUE.png",
}


def background(rgba, color):
    canvas = Image.new("RGBA", rgba.size, color + (255,))
    canvas.alpha_composite(rgba)
    return canvas.convert("RGB")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    audit = {"approved_reference": False, "p1_resolved": False, "cases": {}}
    for name, source in SOURCES.items():
        case = OUT / name
        case.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as original:
            original.convert("RGBA").save(case / "original.png")
        processor = StickerProcessor(case / "pipeline", ProcessingProfile())
        baseline = processor.process(source, automatic_recovery=False)
        with Image.open(baseline.artifacts["selection_alpha_original"]) as opened:
            base = opened.convert("L").copy()
        with Image.open(baseline.artifacts["source_editable"]) as opened:
            design = opened.convert("RGBA").copy()
        base.save(case / "mask_base.png")
        # Operaciones neutras para ejercitar persistencia y protección sin
        # fingir una corrección humana del contenido real.
        document = MaskEditDocument.for_base(base)
        document.add(MaskStroke("protect", ((base.width/2, 2), (base.width/2, 16)),
                                       max(6, base.width*.018), .8, 1))
        document.save(case / "edits_demo_unapproved.json")
        case_data = {"source": str(source), "dimensions": list(base.size), "offsets": {}}
        for contraction in (0, .1, .2, .5):
            mask, protection, report = document.render(
                base, contraction, float(baseline.analysis.get("source_processing_dpi") or 300), .1)
            folder = case / f"{contraction:.1f}mm"
            folder.mkdir(exist_ok=True)
            mask.save(folder / "mask_candidate_unapproved.png")
            protection.save(folder / "protection.png")
            rgba = design.copy(); rgba.putalpha(mask)
            rgba.save(folder / "candidate_unapproved.png")
            background(rgba, (0, 0, 0)).save(folder / "on_black.png")
            background(rgba, (255, 0, 170)).save(folder / "on_magenta.png")
            case_data["offsets"][str(contraction)] = report.to_dict()
        panels = []
        for contraction in (0, .1, .2, .5):
            with Image.open(case / f"{contraction:.1f}mm/on_magenta.png") as opened:
                panel = opened.copy()
            ImageDraw.Draw(panel).rectangle((0, 0, 120, 28), fill="white")
            ImageDraw.Draw(panel).text((8, 7), f"{contraction:.1f} mm", fill="black")
            panels.append(panel)
        sheet = Image.new("RGB", (sum(p.width for p in panels), max(p.height for p in panels)), "white")
        x = 0
        for panel in panels:
            sheet.paste(panel, (x, 0)); x += panel.width
        sheet.save(case / "comparison_magenta.png")
        audit["cases"][name] = case_data
    (OUT / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
