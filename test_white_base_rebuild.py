"""Tests Etapa 2A: reconstrucción de base blanca desplazada.

Valida que el estetoscopio rosa obtenga coverage >= 0.97
y que las demás imágenes no se modifiquen.
"""
import sys, logging
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
logging.disable(logging.CRITICAL)

from app.stickers.pipeline import StickerProcessor, BorderMode

FIXTURES = Path(r"C:\Users\Win 10\Downloads\Stickers-20260720T063709Z-1-001\Stickers")
WORKSPACE = Path(__file__).parent / "_test_2a_workspace"
WORKSPACE.mkdir(exist_ok=True)


def _measure(path):
    proc = StickerProcessor(WORKSPACE)
    result = proc.process(path, progress=lambda _p, _m: None)
    alpha = np.array(
        Image.open(result.artifacts["mask"]).convert("L"), dtype=np.uint8)
    rgb = np.array(Image.open(path).convert("RGB"), dtype=np.uint8)
    wb = StickerProcessor._measure_white_base(rgb, alpha)
    return wb, result.quality_status


def test_rosa_white_base():
    path = FIXTURES / "58bd17868ea5bf723c43aca8da0b79d6.jpg"
    wb, quality = _measure(path)

    assert wb["coverage_ratio"] >= 0.97, (
        f"coverage={wb['coverage_ratio']:.4f} < 0.97")
    assert wb["missing_ratio"] <= 0.03, (
        f"missing={wb['missing_ratio']:.4f} > 0.03")
    assert wb["excess_ratio"] <= 0.05, (
        f"excess={wb['excess_ratio']:.4f} > 0.05")
    print(f"\n[rosa_white_base] PASS "
          f"(cov={wb['coverage_ratio']:.4f}, "
          f"miss={wb['missing_ratio']:.4f}, "
          f"exc={wb['excess_ratio']:.4f})")


def test_other_cases_untouched():
    cases = [
        ("control", "3708b6f9a7cf9aa30b90fcfef5400c87.jpg"),
        ("hoja", "53367c1d3b3817e8165d25c4922a6301.jpg"),
        ("corazon", "792b8c98adf018cd0ae7512d1caa1974.jpg"),
    ]
    for name, fname in cases:
        path = FIXTURES / fname
        wb, _ = _measure(path)
        assert wb["coverage_ratio"] >= 0.95, (
            f"{name}: coverage={wb['coverage_ratio']:.4f} < 0.95")
        print(f"[{name}] PASS (cov={wb['coverage_ratio']:.4f})")


def test_rebuild_trigger_condition():
    analysis = StickerProcessor.analyze_original_border_structure(
        Image.open(FIXTURES / "58bd17868ea5bf723c43aca8da0b79d6.jpg")
        .convert("RGBA"))
    assert analysis["mode"] == BorderMode.AMBIGUOUS_WHITE_ON_WHITE
    print("[trigger_condition] PASS")


if __name__ == "__main__":
    test_rebuild_trigger_condition()
    test_rosa_white_base()
    test_other_cases_untouched()
    print("\nALL 2A TESTS PASSED")
