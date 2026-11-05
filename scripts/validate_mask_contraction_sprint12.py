"""Genera evidencia real de la contracción no destructiva del Sprint 1.2."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from app.stickers.models import ProcessingProfile
from app.stickers.pipeline import StickerProcessor


ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "disc_421": ROOT / "artifacts/sticker-disc-human-review/original.png",
    "chrome_stars_600": ROOT / "artifacts/sticker-disc-human-review/visual_support_600_OPAQUE.png",
}
COLORS = {"white": "white", "black": "black", "grey": (128, 128, 128, 255),
          "magenta": (255, 0, 170, 255)}


def on_background(path, color):
    with Image.open(path) as source:
        rgba = source.convert("RGBA")
    background = Image.new("RGBA", rgba.size, color)
    background.alpha_composite(rgba)
    return background.convert("RGB")


def sheet(paths, labels):
    panels = []
    for path in paths:
        panel = on_background(path, COLORS["magenta"])
        panel.thumbnail((330, 330), Image.Resampling.LANCZOS)
        panels.append(panel)
    result = Image.new("RGB", (24 + len(panels)*354, 380), "#242428")
    draw = ImageDraw.Draw(result)
    x = 24
    for panel, label in zip(panels, labels):
        draw.text((x, 12), label, fill="white")
        result.paste(panel, (x, 38))
        x += 354
    return result


def main(output=ROOT / "artifacts/sticker-mask-contraction-sprint12"):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    audit = {"sources": {}, "runs": {}, "production_approved": False,
             "p1_resolved": False,
             "reason": "Falta máscara humana aprobada para certificar el halo del disco."}
    for name, source in SOURCES.items():
        if not source.exists():
            audit["sources"][name] = {"available": False, "path": str(source)}
            continue
        with Image.open(source) as image:
            audit["sources"][name] = {"available": True, "size": list(image.size),
                                      "mode": image.mode, "path": str(source)}
        finals, labels = [], []
        for contraction in (0.0, 0.1, 0.2, 0.5):
            key = f"{contraction:.1f}mm"
            processor = StickerProcessor(output / name / key / "pipeline", ProcessingProfile())
            result = processor.process(
                source, selection_contraction_mm=contraction,
                selection_smoothing_mm=.1, automatic_recovery=False)
            final = Path(result.artifacts["master"]); finals.append(final); labels.append(key)
            views = {}
            for background, color in COLORS.items():
                destination = output / name / key / f"on_{background}.png"
                destination.parent.mkdir(parents=True, exist_ok=True)
                on_background(final, color).save(destination)
                views[background] = str(destination)
            audit["runs"][f"{name}/{key}"] = {
                "final": str(final), "views": views,
                "contraction": result.analysis["selection_contraction"],
                "physical_size_cm": result.analysis["native_resolution"]["physical_size_cm"],
                "quality": result.quality_status,
                "artifacts": {
                    key: result.artifacts[key] for key in (
                        "selection_alpha_original", "selection_alpha_contracted",
                        "border_treatment_alpha", "master", "native_master", "cut")},
            }
        sheet(finals, labels).save(output / name / "comparison_magenta.png")
    (output / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output / "audit.json")


if __name__ == "__main__":
    main()
