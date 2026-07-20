"""Tests de deteccion de borde blanco con 8 casos obligatorios."""

import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))

from app.stickers.pipeline import BorderMode, StickerProcessor


def _run_case(name, image, expected_mode):
    start = time.perf_counter()
    border_analysis = StickerProcessor.analyze_original_border_structure(image)
    elapsed = (time.perf_counter() - start) * 1000

    mask = StickerProcessor._uniform_background_alpha(image, tolerance=42)
    analysis = StickerProcessor._analyze_white_border_structural(image, mask)
    mask_time = (time.perf_counter() - start) * 1000

    mode = border_analysis["mode"]
    passed = mode == expected_mode

    print(f"\n[{name}]")
    print(f"  modo:              {mode.value} (esperado: {expected_mode.value})")
    print(f"  porcentaje_blanco: {analysis['white_percentage']:.2%}")
    print(f"  grosor_estimado:   {analysis['estimated_border_thickness_px']:.2f} px")
    print(f"  continuidad:       {analysis['continuity']:.2%}")
    print(f"  area_conservada:   {mask.getbbox() is not None}")
    print(f"  tiempo:            {elapsed:.2f} ms")
    print(f"  {'OK' if passed else 'FAIL'}")
    return passed


def test_eight_mandatory_cases():
    print("\n" + "=" * 70)
    print("TEST: 8 casos obligatorios - deteccion de borde blanco")
    print("=" * 70)

    cases = []

    # 1. Fondo oscuro con borde blanco existente
    img1 = Image.new("RGBA", (300, 300), (18, 18, 18, 255))
    d = ImageDraw.Draw(img1)
    d.rectangle([50, 50, 250, 250], fill=(255, 255, 255))
    d.ellipse([80, 80, 220, 220], fill=(100, 150, 200))
    cases.append(("fondo oscuro + borde blanco", img1,
                   BorderMode.PRESERVE_EXISTING_BORDER))

    # 2. Fondo gris con sombra exterior suave
    img2 = Image.new("RGBA", (300, 300), (220, 220, 220, 255))
    d = ImageDraw.Draw(img2)
    d.rectangle([50, 50, 250, 250], fill=(240, 240, 240))
    d.ellipse([80, 80, 220, 220], fill=(100, 150, 200))
    cases.append(("fondo gris + sombra", img2,
                   BorderMode.GENERATE_WHITE_BORDER))

    # 3. Fondo blanco ligeramente distinto del borde
    img3 = Image.new("RGBA", (300, 300), (242, 242, 242, 255))
    d = ImageDraw.Draw(img3)
    d.rectangle([50, 50, 250, 250], fill=(255, 255, 255))
    d.ellipse([80, 80, 220, 220], fill=(100, 150, 200))
    cases.append(("fondo blanco-distinto + borde blanco", img3,
                   BorderMode.PRESERVE_EXISTING_BORDER))

    # 4. Fondo blanco identico al borde (ambiguo)
    img4 = Image.new("RGBA", (300, 300), (255, 255, 255, 255))
    d = ImageDraw.Draw(img4)
    d.rectangle([50, 50, 250, 250], fill=(255, 255, 255))
    d.ellipse([80, 80, 220, 220], fill=(100, 150, 200))
    cases.append(("fondo blanco = borde blanco (ambiguo)", img4,
                   BorderMode.AMBIGUOUS_WHITE_ON_WHITE))

    # 5. Diseno sin borde blanco
    img5 = Image.new("RGBA", (300, 300), (18, 18, 18, 255))
    d = ImageDraw.Draw(img5)
    d.ellipse([80, 80, 220, 220], fill=(100, 150, 200))
    cases.append(("sin borde blanco", img5,
                   BorderMode.GENERATE_WHITE_BORDER))

    # 6. Blancos interiores sin borde exterior
    img6 = Image.new("RGBA", (300, 300), (18, 18, 18, 255))
    d = ImageDraw.Draw(img6)
    d.ellipse([80, 80, 220, 220], fill=(100, 150, 200))
    d.rectangle([120, 100, 180, 200], fill=(255, 255, 255))
    cases.append(("blancos interiores sin borde exterior", img6,
                   BorderMode.GENERATE_WHITE_BORDER))

    # 7. PNG con transparencia real
    img7 = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    d = ImageDraw.Draw(img7)
    d.ellipse([60, 60, 240, 240], fill=(255, 255, 255, 255))
    d.ellipse([80, 80, 220, 220], fill=(100, 150, 200, 255))
    cases.append(("PNG transparencia real", img7,
                   BorderMode.NO_BORDER_REQUIRED))

    # 8. Diseno con grises interiores que no deben eliminarse
    img8 = Image.new("RGBA", (300, 300), (18, 18, 18, 255))
    d = ImageDraw.Draw(img8)
    d.rectangle([40, 40, 260, 260], fill=(255, 255, 255))
    d.ellipse([80, 80, 220, 220], fill=(100, 150, 200))
    d.rectangle([100, 100, 150, 150], fill=(180, 180, 180))
    cases.append(("grises interiores preservados", img8,
                   BorderMode.PRESERVE_EXISTING_BORDER))

    results = []
    for name, image, expected in cases:
        results.append(_run_case(name, image, expected))

    print("\n" + "=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"RESULTADO: {passed}/{total} casos correctos")
    if passed == total:
        print("TODOS LOS CASOS CORRECTOS")
    else:
        print(f"{total - passed} caso(s) incorrecto(s)")
    return all(results)


if __name__ == "__main__":
    try:
        success = test_eight_mandatory_cases()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
