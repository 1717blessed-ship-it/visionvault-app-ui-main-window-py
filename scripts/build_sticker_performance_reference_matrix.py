"""Genera referencias reales para operaciones geométricas y de borde."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(os.environ.get("STICKER_CODE_ROOT", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT))

from app.stickers.models import ProcessingProfile
from app.stickers.pipeline import StickerProcessor


CASES = {
    "default": {},
    "contract_0_1": {"selection_contraction_mm": 0.1},
    "contract_0_2": {"selection_contraction_mm": 0.2},
    "contract_0_5": {"selection_contraction_mm": 0.5},
    "expand_0_2": {"selection_expansion_mm": 0.2},
    "smooth_0_2": {"selection_smoothing_mm": 0.2},
    "border_preserve": {"border_treatment": "Conservar y limpiar"},
    "border_replace": {"border_treatment": "Reemplazar"},
    "border_add": {"border_treatment": "Agregar nuevo"},
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("sources", nargs="+", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    workspace = args.output / "pipeline"
    processor = StickerProcessor(workspace, ProcessingProfile())
    rows = []
    for source in args.sources:
        if not source.is_file():
            raise FileNotFoundError(source)
        for case, options in CASES.items():
            result = processor.process(source.resolve(), automatic_recovery=False, **options)
            run = Path(result.artifacts["metadata"]).parent
            destination = args.output / "cases" / source.stem / case
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(run, destination)
            rasters = {
                path.name: digest(path) for path in sorted(destination.iterdir())
                if path.suffix.lower() in {".png", ".jpg", ".jpeg"}
            }
            metadata = json.loads((destination / "metadata.json").read_text(encoding="utf-8"))
            analysis = metadata["analysis"]
            rows.append({
                "source": source.name,
                "source_sha256": digest(source),
                "case": case,
                "options": options,
                "rasters": rasters,
                "production_contract": {
                    "route": analysis.get("case"),
                    "engine": analysis.get("engine"),
                    "quality": analysis.get("quality_report", {}).get("status"),
                    "native_resolution": analysis.get("native_resolution"),
                    "effective_content_dpi": analysis.get("effective_content_dpi"),
                    "selection_contraction": analysis.get("selection_contraction"),
                    "border_treatment": analysis.get("border_treatment"),
                },
            })
    manifest = {"sources": len(args.sources), "configurations": len(CASES), "rows": rows}
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"sources": len(args.sources), "configurations": len(CASES),
                      "runs": len(rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
