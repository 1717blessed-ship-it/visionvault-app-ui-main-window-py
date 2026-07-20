"""Test rápido de detección estructural de borde blanco con métricas."""

import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))

from app.stickers.pipeline import StickerProcessor


def _measure_case(name: str, image: Image.Image, expected: bool):
    start = time.perf_counter()
    mask = StickerProcessor._uniform_background_alpha(image, tolerance=42)
    mask_time = time.perf_counter() - start

    analysis_start = time.perf_counter()
    analysis = StickerProcessor._analyze_white_border_structural(image, mask)
    analysis_time = time.perf_counter() - analysis_start

    total_time = mask_time + analysis_time
    print(f"\n[{name}]")
    print(f"  detectado: {analysis['has_border']}")
    print(f"  esperado: {expected}")
    print(f"  porcentaje_blanco: {analysis['white_percentage']:.2%}")
    print(f"  grosor_estimado_px: {analysis['estimated_border_thickness_px']:.2f}")
    print(f"  continuidad: {analysis['continuity']:.2%}")
    print(f"  tiempo_mascara: {mask_time * 1000:.2f} ms")
    print(f"  tiempo_analisis: {analysis_time * 1000:.2f} ms")
    print(f"  tiempo_total: {total_time * 1000:.2f} ms")

    passed = analysis['has_border'] == expected
    print(f"  {'OK' if passed else 'FAIL'} {'PASO' if passed else 'FALLO'}")
    return passed, analysis


def test_structural_detection():
    """Test de detección estructural con salida explícita y mediciones."""
    print("\n" + "=" * 70)
    print("TEST: Detección Estructural de Borde Blanco")
    print("=" * 70)

    img_dark_border = Image.new("RGBA", (220, 220), color=(18, 18, 18, 255))
    draw = ImageDraw.Draw(img_dark_border)
    draw.rectangle([20, 20, 200, 200], fill=(255, 255, 255))
    draw.ellipse([55, 55, 165, 165], fill=(80, 120, 220))

    img_no_border = Image.new("RGBA", (220, 220), color=(18, 18, 18, 255))
    draw = ImageDraw.Draw(img_no_border)
    draw.ellipse([60, 60, 160, 160], fill=(100, 100, 200))

    cases = [
        ("fondo oscuro y borde blanco", img_dark_border, True),
        ("sin borde blanco deliberado", img_no_border, False),
    ]

    results = []
    for name, image, expected in cases:
        passed, _ = _measure_case(name, image, expected)
        results.append(passed)

    print("\n" + "=" * 70)
    print("RESUMEN")
    print("=" * 70)
    print(f"Casos correctos: {sum(results)}/{len(results)}")

    success = all(results)
    if success:
        print("\nTODOS LOS CASOS CORRECTOS")
    else:
        print(f"\n{len(results) - sum(results)} caso(s) incorrecto(s)")
    return success


def test_structural_regression_cases():
    """Casos adicionales de regresión para bordes, sombras y transparencia."""
    print("\n" + "=" * 70)
    print("TEST: Casos de regresión estructural")
    print("=" * 70)

    cases = []

    # Fondo gris con sombra exterior
    img_gray_shadow = Image.new("RGBA", (260, 260), color=(220, 220, 220, 255))
    draw = ImageDraw.Draw(img_gray_shadow)
    draw.rectangle([45, 45, 215, 215], fill=(240, 240, 240))
    draw.ellipse([80, 80, 180, 180], fill=(70, 120, 180))
    draw.rectangle([195, 195, 225, 225], fill=(180, 180, 180))
    cases.append(("fondo gris con sombra exterior", img_gray_shadow, False))

    # Fondo oscuro con borde blanco existente
    img_dark_border = Image.new("RGBA", (220, 220), color=(18, 18, 18, 255))
    draw = ImageDraw.Draw(img_dark_border)
    draw.rectangle([20, 20, 200, 200], fill=(255, 255, 255))
    draw.ellipse([55, 55, 165, 165], fill=(80, 120, 220))
    cases.append(("fondo oscuro con borde blanco existente", img_dark_border, True))

    # Diseño sin borde blanco
    img_no_border = Image.new("RGBA", (220, 220), color=(18, 18, 18, 255))
    draw = ImageDraw.Draw(img_no_border)
    draw.ellipse([60, 60, 160, 160], fill=(100, 100, 200))
    cases.append(("diseño sin borde blanco", img_no_border, False))

    # PNG con transparencia real
    img_transparent = Image.new("RGBA", (220, 220), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img_transparent)
    draw.ellipse([45, 45, 175, 175], fill=(255, 255, 255, 255))
    draw.ellipse([55, 55, 165, 165], fill=(80, 120, 220, 255))
    cases.append(("png con transparencia real", img_transparent, True))

    # Zonas blancas interiores sin contorno blanco externo
    img_internal_white = Image.new("RGBA", (220, 220), color=(18, 18, 18, 255))
    draw = ImageDraw.Draw(img_internal_white)
    draw.ellipse([60, 60, 160, 160], fill=(100, 100, 200))
    draw.rectangle([90, 90, 110, 110], fill=(255, 255, 255))
    cases.append(("zonas blancas interiores sin contorno externo", img_internal_white, False))

    # Añadimos un caso extra con un borde blanco real pero sin fondo oscuro para
    # asegurar que la lógica no dependa del contexto de fondo.
    img_real_border = Image.new("RGBA", (220, 220), color=(255, 255, 255, 255))
    draw = ImageDraw.Draw(img_real_border)
    draw.ellipse([45, 45, 175, 175], fill=(255, 255, 255))
    draw.ellipse([55, 55, 165, 165], fill=(80, 120, 220))
    cases.append(("borde blanco real sobre fondo claro", img_real_border, True))

    passed = []
    for name, image, expected in cases:
        passed.append(_measure_case(name, image, expected)[0])

    print("\n" + "=" * 70)
    print(f"Casos de regresión correctos: {sum(passed)}/{len(passed)}")
    return all(passed)


if __name__ == "__main__":
    try:
        success = test_structural_detection() and test_structural_regression_cases()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
