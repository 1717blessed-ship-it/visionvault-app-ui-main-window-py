"""Compara binariamente una corrida optimizada con la referencia 2.0.0."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/sticker-performance-2.0.0-baseline"
OPT = ROOT / "artifacts/sticker-performance-2.0.1-optimized"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_dir(root: Path, item: dict) -> Path:
    return root / "pipeline" / Path(item["master"]).parent.name


def production_contract(run: Path) -> dict:
    metadata = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
    analysis = metadata["analysis"]
    return {
        "case": analysis.get("case"),
        "engine": analysis.get("engine"),
        "sticker_type": analysis.get("sticker_type"),
        "quality": analysis.get("quality"),
        "quality_status": analysis.get("quality_report", {}).get("status"),
        "reprocess_parameters": metadata.get("reprocess_parameters"),
        "source_pixels": analysis.get("source_pixels"),
        "processing_pixels": analysis.get("processing_pixels"),
        "native_resolution": analysis.get("native_resolution"),
        "effective_content_dpi": analysis.get("effective_content_dpi"),
        "printable_border_mm": analysis.get("printable_border_mm"),
        "selection_contraction": analysis.get("selection_contraction"),
        "border_treatment": analysis.get("border_treatment"),
    }


def main() -> None:
    base_report = json.loads((BASE / "acceptance_metrics.json").read_text(encoding="utf-8"))
    opt_report = json.loads((OPT / "acceptance_metrics.json").read_text(encoding="utf-8"))
    comparisons = []
    all_equal = True
    for before, after in zip(base_report["items"], opt_report["items"], strict=True):
        before_dir, after_dir = run_dir(BASE, before), run_dir(OPT, after)
        before_files = {path.name: path for path in before_dir.iterdir() if path.is_file()}
        after_files = {path.name: path for path in after_dir.iterdir() if path.is_file()}
        common = sorted(before_files.keys() & after_files.keys())
        binary = {name: sha(before_files[name]) == sha(after_files[name]) for name in common}
        # JSON incluye IDs/rutas/tiempos de corrida; se valida su contrato
        # semántico por separado, no como bytes dependientes del UUID.
        raster = {name: equal for name, equal in binary.items()
                  if Path(name).suffix.lower() in {".png", ".jpg", ".jpeg"}}
        item_equal = bool(raster) and all(raster.values())
        contract_equal = production_contract(before_dir) == production_contract(after_dir)
        all_equal &= item_equal
        comparisons.append({
            "input_sha256_equal": before["input_sha256"] == after["input_sha256"],
            "input": before["input"], "route_quality_equal": before["quality"] == after["quality"],
            "production_contract_equal": contract_equal,
            "raster_files_compared": len(raster), "all_raster_sha256_equal": item_equal,
            "differences": [name for name, equal in raster.items() if not equal],
        })
    report = {
        "baseline": "sticker-studio-v2.0.0", "candidate": "2.0.1-performance",
        "items": len(comparisons), "all_raster_outputs_equal": all_equal,
        "all_input_hashes_equal": all(row["input_sha256_equal"] for row in comparisons),
        "all_quality_states_equal": all(row["route_quality_equal"] for row in comparisons),
        "all_production_contracts_equal": all(row["production_contract_equal"] for row in comparisons),
        "comparisons": comparisons,
    }
    (OPT / "binary_comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "comparisons"}, ensure_ascii=False))
    if not all_equal or not report["all_production_contracts_equal"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
