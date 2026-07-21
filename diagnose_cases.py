"""Etapa 1 revisado: diagnóstico de clasificación y métricas de referencia.

Modificaciones vs. diagnose_fixtures.py original:
- Usa analyze_original_border_structure con campos extendidos
- Genera máscara de referencia con flood fill para métricas válidas
- Mide subject_recall y background_rejection en vez de pixel_loss bruto
"""
import sys, io, json, logging
from pathlib import Path

import numpy as np
from PIL import Image

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
logging.disable(logging.CRITICAL)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.stickers.pipeline import StickerProcessor, BorderMode

FIXTURES = Path(r"C:\Users\Win 10\Downloads\Stickers-20260720T063709Z-1-001\Stickers")
OUT_BASE = Path(__file__).resolve().parent / "diagnosis_etapa1"
OUT_BASE.mkdir(exist_ok=True)

CASES = [
    ("control_estetoscopio", FIXTURES / "3708b6f9a7cf9aa30b90fcfef5400c87.jpg"),
    ("hoja_clara", FIXTURES / "53367c1d3b3817e8165d25c4922a6301.jpg"),
    ("estetoscopio_rosa", FIXTURES / "58bd17868ea5bf723c43aca8da0b79d6.jpg"),
    ("corazon_anatomico", FIXTURES / "792b8c98adf018cd0ae7512d1caa1974.jpg"),
]


def compute_reference_background(rgb_np, bg_color, tolerance=40):
    """Flood fill desde bordes del canvas para generar máscara de referencia."""
    from app.stickers.mask_candidates import _flood_fill_background

    bg_mask = _flood_fill_background(rgb_np, tolerance, use_lab=True)
    reference_background = bg_mask > 127
    reference_subject = ~reference_background
    return reference_background, reference_subject


def compute_metrics(reference_subject, reference_background, processed_alpha):
    """Subject recall y background rejection basados en máscara de referencia."""
    processed_subject = processed_alpha > 10
    processed_background = ~processed_subject

    subject_recall = float(
        (processed_subject & reference_subject).sum()
        / max(reference_subject.sum(), 1)
    )
    background_rejection = float(
        (processed_background & reference_background).sum()
        / max(reference_background.sum(), 1)
    )
    return subject_recall, background_rejection


def main():
    workspace = OUT_BASE / "_pipeline_workspace"
    workspace.mkdir(exist_ok=True)
    processor = StickerProcessor(workspace)
    report = {}

    for name, path in CASES:
        print(f"\n{'=' * 60}")
        print(f"  {name}")
        print(f"{'=' * 60}")

        img = Image.open(path).convert("RGBA")
        rgb_np = np.array(img.convert("RGB"), dtype=np.uint8)

        analysis = StickerProcessor.analyze_original_border_structure(img)
        mode = analysis["mode"]

        print(f"  selected_mode:        {mode.value}")
        print(f"  mode_reason:          {analysis['mode_reason']}")
        print(f"  perimeter_median_rgb: {analysis['perimeter_median_rgb']}")
        print(f"  perimeter_luminance:  {analysis['perimeter_luminance']:.1f}")
        print(f"  perimeter_saturation: {analysis['perimeter_saturation']:.3f}")
        print(f"  background_is_white:  {analysis['background_is_white']}")
        print(f"  bg_color:             {analysis['bg_color']}")
        print(f"  white_in_ring_ratio:  {analysis['white_in_ring_ratio']:.3f}")
        print(f"  has_design:           {analysis['has_design']}")
        print(f"  bg_dist_threshold:    {analysis['background_distance_threshold']}")

        assert mode != BorderMode.AMBIGUOUS_WHITE_ON_WHITE or analysis["background_is_white"], (
            f"INVARIANT: AMBIGUOUS requires background_is_white for {name}")

        if mode == BorderMode.NO_BORDER_REQUIRED:
            print("  [skip] NO_BORDER_REQUIRED (transparency)")
            report[name] = {"mode": mode.value, "skipped": True}
            continue

        reference_bg, reference_subject = compute_reference_background(
            rgb_np, analysis["bg_color"])
        print(f"  reference_background: {reference_bg.sum()} px "
              f"({reference_bg.sum() / reference_bg.size * 100:.1f}%)")
        print(f"  reference_subject:    {reference_subject.sum()} px "
              f"({reference_subject.sum() / reference_subject.size * 100:.1f}%)")

        result = processor.process(
            path,
            progress=lambda _p, _m: None,
            cut_inset_mm=None,
        )

        mask_path = result.artifacts.get("mask")
        if mask_path:
            processed_alpha = np.array(
                Image.open(mask_path).convert("L"), dtype=np.uint8)
        else:
            clean_path = result.artifacts.get("clean")
            processed = Image.open(clean_path).convert("RGBA")
            processed_alpha = np.array(processed.getchannel("A"), dtype=np.uint8)

        subject_recall, background_rejection = compute_metrics(
            reference_subject, reference_bg, processed_alpha)
        print(f"  subject_recall:       {subject_recall:.3f}")
        print(f"  background_rejection: {background_rejection:.3f}")
        print(f"  output_dir:           {result.output_dir}")
        print(f"  quality:              {result.quality_status}")

        report[name] = {
            **analysis,
            "selected_mode": mode.value,
            "reference_background_pct": float(reference_bg.sum() / reference_bg.size * 100),
            "reference_subject_pct": float(reference_subject.sum() / reference_subject.size * 100),
            "subject_recall": subject_recall,
            "background_rejection": background_rejection,
            "quality": result.quality_status,
        }

    report_path = OUT_BASE / "baseline_report_v2.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nReporte guardado en {report_path}")

    ok = all(
        r.get("selected_mode") != BorderMode.AMBIGUOUS_WHITE_ON_WHITE.value
        or True
        for r in report.values()
        if not r.get("skipped")
    )
    print(f"\n{'='*60}")
    print(f"  VALIDACION INVARIANTE: PASS (AMBIGUOUS requiere background_is_white)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
