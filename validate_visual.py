"""Validacion visual: genera 7 imagenes sinteticas, analiza y guarda artefactos."""
import os, sys, time, json
from PIL import Image, ImageDraw, ImageFilter
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from app.stickers.pipeline import BorderMode, StickerProcessor

OUT = os.path.join(os.path.dirname(__file__), "validation_output")
os.makedirs(OUT, exist_ok=True)


def save(img, name, sub=""):
    path = os.path.join(OUT, f"{name}{sub}.png")
    img.save(path)
    return path


def save_mask(mask_pil, name, sub):
    return save(mask_pil, name, sub)


def make_synthetic_cases():
    cases = []

    # 1. Consola gris con sombra exterior suave
    c1 = Image.new("RGBA", (400, 400), (180, 180, 180, 255))
    d1 = ImageDraw.Draw(c1)
    d1.ellipse([80, 80, 320, 320], fill=(60, 120, 200, 255))
    shadow = c1.filter(ImageFilter.GaussianBlur(radius=15))
    cases.append(("01_gris_sombra", shadow))

    # 2. Corazon floral fondo oscuro con borde blanco original
    #    Perimeter is dark; white border sits inside (offset 30-55px)
    c2 = Image.new("RGBA", (400, 400), (20, 20, 20, 255))
    d2 = ImageDraw.Draw(c2)
    b2 = 30
    d2.rectangle([b2, b2, 400 - b2 - 1, 400 - b2 - 1], fill=(255, 255, 255, 255))
    d2.ellipse([65, 65, 335, 335], fill=(220, 30, 60, 255))
    cases.append(("02_corazon_borde_blanco", c2))

    # 3. Diseno sin borde blanco (colores solidos sobre fondo oscuro)
    c3 = Image.new("RGBA", (400, 400), (18, 18, 18, 255))
    d3 = ImageDraw.Draw(c3)
    d3.rectangle([100, 100, 300, 300], fill=(0, 100, 200, 255))
    d3.rectangle([140, 140, 260, 260], fill=(255, 200, 0, 255))
    cases.append(("03_sin_borde_blanco", c3))

    # 4. PNG con transparencia real
    c4 = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    d4 = ImageDraw.Draw(c4)
    d4.ellipse([60, 60, 340, 340], fill=(0, 180, 80, 255))
    cases.append(("04_transparencia", c4))

    # 5. Fondo blanco identico al borde (ambiguo)
    c5 = Image.new("RGBA", (400, 400), (255, 255, 255, 255))
    d5 = ImageDraw.Draw(c5)
    d5.rectangle([0, 0, 399, 25], fill=(255, 255, 255, 255))
    d5.rectangle([0, 375, 399, 399], fill=(255, 255, 255, 255))
    d5.rectangle([0, 0, 25, 399], fill=(255, 255, 255, 255))
    d5.rectangle([375, 0, 399, 399], fill=(255, 255, 255, 255))
    d5.ellipse([80, 80, 320, 320], fill=(200, 50, 50, 255))
    cases.append(("05_fondo_blanco_ambiguo", c5))

    # 6. Baja resolucion (64x64 upscaled with border inside dark perimeter)
    c6_small = Image.new("RGBA", (64, 64), (18, 18, 18, 255))
    d6 = ImageDraw.Draw(c6_small)
    d6.rectangle([6, 6, 57, 57], fill=(255, 255, 255, 255))
    d6.ellipse([12, 12, 52, 52], fill=(100, 50, 200, 255))
    c6 = c6_small.resize((400, 400), Image.NEAREST)
    cases.append(("06_baja_resolucion_64", c6))

    # 7. Imagen grande alta resolucion (2000x2000) con borde blanco INTERNO
    c7 = Image.new("RGBA", (2000, 2000), (25, 25, 30, 255))
    d7 = ImageDraw.Draw(c7)
    b7 = 60
    d7.rectangle([b7, b7, 2000 - b7 - 1, 2000 - b7 - 1], fill=(255, 255, 255, 255))
    d7.ellipse([200, 200, 1800, 1800], fill=(50, 140, 220, 255))
    d7.rectangle([700, 700, 1300, 1300], fill=(255, 200, 50, 255))
    cases.append(("07_alta_resolucion_2000", c7))

    return cases


def generate_visualizations(img, name, border_info):
    rgb = np.asarray(img.convert("RGB"), dtype=np.uint8)
    h, w = rgb.shape[:2]

    bg_color = border_info["bg_color"]
    bg_arr = np.array(bg_color, dtype=np.int16)
    diffs = np.abs(rgb.astype(np.int16) - bg_arr)
    max_diff = diffs.max(axis=2)
    is_bg = max_diff < 35

    bg_mask = Image.fromarray((is_bg.astype(np.uint8) * 255), mode="L")
    save(bg_mask, name, "_bg_mask")

    mask = StickerProcessor._uniform_background_alpha(img, tolerance=42)
    save(mask, name, "_final_mask")

    rgba = img.copy()
    alpha = mask.convert("L")
    rgba.putalpha(alpha)
    save(rgba, name, "_processed_rgba")

    try:
        solid = alpha.point(lambda v: 255 if v > 127 else 0)
        stroke = StickerProcessor._build_inner_white_stroke(rgba, 2)
        save(stroke, name, "_stroke")
    except Exception as e:
        print(f"  stroke skip: {e}")

    return bg_mask, mask


def run_validation():
    cases = make_synthetic_cases()
    results = []

    for name, img in cases:
        print(f"\n{'=' * 60}")
        print(f"  {name}  ({img.size[0]}x{img.size[1]})")
        print(f"{'=' * 60}")

        save(img, name, "_original")

        t0 = time.perf_counter()
        info = StickerProcessor.analyze_original_border_structure(img)
        dt_analysis = (time.perf_counter() - t0) * 1000

        mode = info["mode"]
        bg_is_white = info["background_is_white"]
        border_dist = info["border_distinguishable"]
        white_ratio = info["white_band_ratio"]
        bg_color = info["bg_color"]

        print(f"  mode:              {mode.value}")
        print(f"  background_is_white: {bg_is_white}")
        print(f"  border_distinguishable: {border_dist}")
        print(f"  white_ratio:       {white_ratio:.2%}")
        print(f"  bg_color:          {bg_color}")
        print(f"  analysis_ms:       {dt_analysis:.1f}")

        bg_mask, final_mask = generate_visualizations(img, name, info)
        print(f"  artefactos guardados: OK")

        results.append({
            "name": name,
            "size": f"{img.size[0]}x{img.size[1]}",
            "mode": mode.value,
            "background_is_white": bg_is_white,
            "border_distinguishable": border_dist,
            "white_ratio": round(white_ratio, 4),
            "bg_color": bg_color,
            "analysis_ms": round(dt_analysis, 1),
            "ring_px": 15,
        })

    print(f"\n{'=' * 80}")
    print("RESUMEN DE VALIDACION VISUAL")
    print(f"{'=' * 80}")
    print(f"{'Caso':<36} {'Tam':<14} {'Modo':<30} {'%Blk':>6} {'Ring':>5}")
    print("-" * 95)
    for r in results:
        print(f"{r['name']:<36} {r['size']:<14} {r['mode']:<30} {r['white_ratio']:>5.1%} {r['ring_px']:>4}px")

    report_path = os.path.join(OUT, "report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nReporte: {report_path}")
    print(f"Artefactos: {OUT}/")
    print(f"\nArchivos por caso:")
    print(f"  *_original.png      - imagen de entrada")
    print(f"  *_bg_mask.png       - mascara de fondo (gris ~ bg)")
    print(f"  *_final_mask.png    - mascara final del pipeline")
    print(f"  *_processed_rgba.png- resultado con alpha")
    print(f"  *_stroke.png        - borde interior blanco")


if __name__ == "__main__":
    run_validation()
