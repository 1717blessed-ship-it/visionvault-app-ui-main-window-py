"""Evidencia reproducible del Sprint 1.1 sobre originales reales disponibles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw
import numpy as np

from app.stickers.editor_v2.adapter import PipelineViewAdapter
from app.stickers.models import BorderTreatment, ProcessingProfile
from app.stickers.pipeline import StickerProcessor


ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "disc_421": ROOT / "artifacts/sticker-disc-human-review/original.png",
    "chrome_stars_support_600": ROOT / "artifacts/sticker-disc-human-review/visual_support_600_OPAQUE.png",
}
BACKGROUNDS = {
    "white": (255, 255, 255), "black": (0, 0, 0),
    "grey": (128, 128, 128), "magenta": (255, 0, 170),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def composite(path, color):
    with Image.open(path) as source:
        image = source.convert("RGBA")
    background = Image.new("RGBA", image.size, (*color, 255))
    background.alpha_composite(image)
    return background.convert("RGB")


def comparison(images, labels):
    opened = []
    for path in images:
        with Image.open(path) as source:
            image = source.convert("RGBA").copy()
        image.thumbnail((360, 360), Image.Resampling.LANCZOS)
        opened.append(image)
    width = sum(image.width for image in opened) + 24 * (len(opened) + 1)
    sheet = Image.new("RGB", (width, 420), "#242428")
    draw = ImageDraw.Draw(sheet)
    x = 24
    for image, label in zip(opened, labels):
        board = Image.new("RGBA", image.size, (255, 0, 170, 255))
        board.alpha_composite(image)
        sheet.paste(board.convert("RGB"), (x, 42))
        draw.text((x, 14), label, fill="white")
        x += image.width + 24
    return sheet


def main(output=ROOT / "artifacts/sticker-studio-sprint11"):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    audit = {"sources": {}, "runs": {}, "classic_v2_difference": None,
             "limitations": ["No existe mask_reviewed.png aprobada por una persona."]}
    for source_name, source in SOURCES.items():
        if not source.is_file():
            audit["sources"][source_name] = {"available": False, "path": str(source)}
            continue
        with Image.open(source) as image:
            audit["sources"][source_name] = {
                "available": True, "path": str(source), "size": list(image.size),
                "mode": image.mode, "alpha_extrema": list(image.convert("RGBA").getchannel("A").getextrema()),
                "sha256": sha(source),
            }
        run_paths = []
        labels = []
        for treatment in (None, *[item.value for item in BorderTreatment]):
            key = "automatic" if treatment is None else treatment.lower().replace(" ", "_")
            workspace = output / source_name / key / "pipeline"
            processor = StickerProcessor(workspace, ProcessingProfile())
            result = processor.process(source, border_treatment=treatment,
                                       automatic_recovery=False)
            final_path = Path(result.artifacts["master"])
            export_path = output / source_name / key / "exported_final.png"
            PipelineViewAdapter.export_final(final_path, export_path)
            views = {}
            for background, color in BACKGROUNDS.items():
                view = output / source_name / key / f"on_{background}.png"
                composite(export_path, color).save(view)
                views[background] = str(view)
            with Image.open(export_path) as final:
                alpha = final.convert("RGBA").getchannel("A")
                export_info = {"size": list(final.size), "mode": final.mode,
                               "alpha_extrema": list(alpha.getextrema()),
                               "transparent_pixels": int((np.asarray(alpha) == 0).sum())}
            audit["runs"][f"{source_name}/{key}"] = {
                "quality": result.quality_status, "case": result.analysis["case"],
                "border_treatment": result.analysis["border_treatment"],
                "halo": result.analysis["grey_halo_review"],
                "final": str(final_path), "export": str(export_path),
                "byte_identical_export": sha(final_path) == sha(export_path),
                "export_info": export_info, "views": views,
                "artifacts": result.artifacts,
            }
            run_paths.append(export_path)
            labels.append(key)
        comparison(run_paths, labels).save(output / source_name / "treatments_on_magenta.png")

    # Dos corridas independientes detectan además cualquier no determinismo
    # del motor que podría aparentar una diferencia entre interfaces.
    if SOURCES["disc_421"].is_file():
        classic = StickerProcessor(output / "differential/classic", ProcessingProfile()).process(
            SOURCES["disc_421"], automatic_recovery=False)
        v2 = StickerProcessor(output / "differential/v2", ProcessingProfile()).process(
            SOURCES["disc_421"], border_treatment=None, automatic_recovery=False)
        source, v2_path = classic.artifacts["master"], v2.artifacts["master"]
        with Image.open(source) as first, Image.open(v2_path) as second:
            first_rgba, second_rgba = first.convert("RGBA"), second.convert("RGBA")
            different = int(np.any(
                np.asarray(first_rgba) != np.asarray(second_rgba), axis=2).sum())
        audit["classic_v2_difference"] = {
            "classic_master": source, "v2_final": v2_path,
            "sha256_equal": sha(source) == sha(v2_path), "pixel_difference": different,
            "same_profile": classic.profile == v2.profile,
            "same_case": classic.analysis["case"] == v2.analysis["case"],
        }
    (output / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(output / "audit.json")


if __name__ == "__main__":
    main()
