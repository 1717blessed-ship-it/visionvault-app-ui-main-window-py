"""Tests de borde blanco con métricas explícitas y casos de regresión."""

import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))

from app.stickers.pipeline import StickerProcessor


def create_image_with_white_border(border_width=20, design_color=(100, 150, 200)):
    """Crea una imagen de prueba con borde blanco de grosor específico."""
    img = Image.new("RGBA", (300, 300), color=(255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    inner_box = (50 + border_width, 50 + border_width, 250 - border_width, 250 - border_width)
    draw.rectangle([50, 50, 250, 250], fill=(255, 255, 255))
    draw.ellipse(inner_box, fill=design_color)
    return img


def _run_border_case(name: str, image: Image.Image, expected: bool):
    start = time.perf_counter()
    mask = StickerProcessor._uniform_background_alpha(image, tolerance=42)
    mask_time = time.perf_counter() - start

    analysis_start = time.perf_counter()
    analysis = StickerProcessor._analyze_white_border_structural(image, mask)
    analysis_time = time.perf_counter() - analysis_start

    print(f"\n[{name}]")
    print(f"  detectado: {analysis['has_border']}")
    print(f"  esperado: {expected}")
    print(f"  porcentaje_blanco: {analysis['white_percentage']:.2%}")
    print(f"  grosor_estimado_px: {analysis['estimated_border_thickness_px']:.2f}")
    print(f"  continuidad: {analysis['continuity']:.2%}")
    print(f"  tiempo_mascara: {mask_time * 1000:.2f} ms")
    print(f"  tiempo_analisis: {analysis_time * 1000:.2f} ms")
    print(f"  tiempo_total: {(mask_time + analysis_time) * 1000:.2f} ms")
    return analysis['has_border'] == expected


def test_thin_border_detection():
    """Detectar borde blanco fino (5px)."""
    print("\n" + "=" * 70)
    print("TEST 1: Detección de Borde Blanco Fino (5px)")
    print("=" * 70)
    return _run_border_case("borde fino", create_image_with_white_border(border_width=5), True)


def test_medium_border_detection():
    """Detectar borde blanco medio (15px)."""
    print("\n" + "=" * 70)
    print("TEST 2: Detección de Borde Blanco Medio (15px)")
    print("=" * 70)
    return _run_border_case("borde medio", create_image_with_white_border(border_width=15), True)


def test_thick_border_detection():
    """Detectar borde blanco grueso (30px)."""
    print("\n" + "=" * 70)
    print("TEST 3: Detección de Borde Blanco Grueso (30px)")
    print("=" * 70)
    return _run_border_case("borde grueso", create_image_with_white_border(border_width=30), True)


def test_no_border_case():
    """No detectar borde cuando no hay uno."""
    print("\n" + "=" * 70)
    print("TEST 4: Sin Borde Blanco")
    print("=" * 70)
    img = Image.new("RGBA", (300, 300), color=(255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.ellipse([80, 80, 220, 220], fill=(100, 150, 200))
    draw.rectangle([120, 100, 180, 200], fill=(200, 100, 50))
    return _run_border_case("sin borde", img, False)


def test_multiwidth_detection():
    """Verificar detección multi-ancho."""
    print("\n" + "=" * 70)
    print("TEST 5: Detección Multi-Ancho")
    print("=" * 70)
    results = []
    for width in [3, 8, 15, 25]:
        results.append(_run_border_case(f"ancho {width}px", create_image_with_white_border(border_width=width), True))
    detected = sum(1 for value in results if value)
    print(f"\nDetectados: {detected}/4")
    return detected >= 3


def main():
    """Ejecuta todos los tests de detección."""
    print("\n" + "=" * 70)
    print("SUITE DE TESTS: Detección de Borde Blanco Mejorada")
    print("=" * 70)

    tests = [
        ("Borde Fino (5px)", test_thin_border_detection),
        ("Borde Medio (15px)", test_medium_border_detection),
        ("Borde Grueso (30px)", test_thick_border_detection),
        ("Sin Borde", test_no_border_case),
        ("Multi-Ancho", test_multiwidth_detection),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as exc:
            print(f"\n❌ Error en test '{name}': {exc}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    print("\n" + "=" * 70)
    print("RESUMEN DE RESULTADOS")
    print("=" * 70)
    passed = sum(1 for _, result in results if result)
    total = len(results)
    for name, result in results:
        status = "✅" if result else "❌"
        print(f"{status} {name}")
    print(f"\nTotal: {passed}/{total} tests pasados ({passed / total * 100:.0f}%)")
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
