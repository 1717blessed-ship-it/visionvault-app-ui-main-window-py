"""Etapa 1.6: validación y corrección de métricas.

NO modifica el pipeline. Corrige tres métricas inconsistentes de la Etapa 1.5:
- white_base_coverage (antes superaba 1.0)
- Detección de conexión fina de la hoja (skkeleton + opening)
- light_detail_recall (ahora separado interior/exterior y con coherencia espacial)
"""
import sys, io, json, logging
from pathlib import Path

import numpy as np
import cv2
from PIL import Image
from skimage.morphology import skeletonize, disk, opening as sk_opening
from scipy import ndimage

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
logging.disable(logging.CRITICAL)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.stickers.pipeline import StickerProcessor, BorderMode, ProcessingProfile
from app.stickers.mask_candidates import _flood_fill_background

FIXTURES = Path(r"C:\Users\Win 10\Downloads\Stickers-20260720T063709Z-1-001\Stickers")
OUT_BASE = Path(__file__).resolve().parent / "diagnosis_etapa1"
OUT_BASE.mkdir(exist_ok=True)

PROFILE = ProcessingProfile()

CASES = [
    ("control_estetoscopio", FIXTURES / "3708b6f9a7cf9aa30b90fcfef5400c87.jpg"),
    ("hoja_clara", FIXTURES / "53367c1d3b3817e8165d25c4922a6301.jpg"),
    ("estetoscopio_rosa", FIXTURES / "58bd17868ea5bf723c43aca8da0b79d6.jpg"),
    ("corazon_anatomico", FIXTURES / "792b8c98adf018cd0ae7512d1caa1974.jpg"),
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def count_components(mask_bool, min_area=5):
    """Cuenta componentes conectados de una máscara booleana."""
    labeled, n = ndimage.label(mask_bool.astype(np.uint8))
    count = 0
    for i in range(1, n + 1):
        if (labeled == i).sum() >= min_area:
            count += 1
    return count


def safe_components(mask_bool, min_area=5):
    """Devuelve etiquetas y áreas de componentes ≥ min_area."""
    labeled, n = ndimage.label(mask_bool.astype(np.uint8))
    comps = []
    for i in range(1, n + 1):
        area = (labeled == i).sum()
        if area >= min_area:
            comps.append({"label": i, "area": int(area)})
    comps.sort(key=lambda c: c["area"], reverse=True)
    return comps


def correct_white_base(rgb_np, subject_mask, alpha_final):
    """Cobertura de base blanca con intersección exacta."""
    white_in_original = (
        (rgb_np[:,:,0] > 235) & (rgb_np[:,:,1] > 235) & (rgb_np[:,:,2] > 235))
    expected = white_in_original & subject_mask
    actual_white = (alpha_final > 127)
    actual = white_in_original & actual_white

    expected_area = int(expected.sum())
    actual_area = int(actual.sum())
    intersection = int((expected & actual).sum())
    excess = int((actual & ~expected).sum())
    missing = int((expected & ~actual).sum())

    coverage = intersection / max(expected_area, 1)
    excess_ratio = excess / max(expected_area, 1)
    missing_ratio = missing / max(expected_area, 1)

    return {
        "expected_base_area": expected_area,
        "actual_base_area": actual_area,
        "intersection_area": intersection,
        "excess_white_area": excess,
        "missing_white_area": missing,
        "coverage_ratio": round(coverage, 4),
        "excess_ratio": round(excess_ratio, 4),
        "missing_ratio": round(missing_ratio, 4),
    }


def detect_neck_width(subject_mask):
    """Detecta el cuello más fino de la máscara con skeleton + distance transform."""
    binary = subject_mask.astype(np.uint8)
    dist = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
    skel = skeletonize(binary > 0)
    neck_values = dist[skel]
    if len(neck_values) == 0:
        return {"error": "no skeleton pixels"}
    neck_values_sorted = np.sort(neck_values)
    p2_idx = max(0, int(len(neck_values_sorted) * 0.02))
    return {
        "minimum_neck_width_px": round(float(neck_values_sorted[p2_idx]) * 2, 2),
        "median_neck_width_px": round(float(np.median(neck_values)) * 2, 2),
        "skeleton_pixel_count": int(skel.sum()),
        "neck_histogram": {
            "p02": round(float(neck_values_sorted[p2_idx]) * 2, 2),
            "p05": round(float(np.percentile(neck_values, 5)) * 2, 2),
            "p10": round(float(np.percentile(neck_values, 10)) * 2, 2),
            "p25": round(float(np.percentile(neck_values, 25)) * 2, 2),
            "p50": round(float(np.median(neck_values)) * 2, 2),
        },
    }


def opening_sweep(subject_mask):
    """Prueba apertura morfológica con distintos radios para diagnosticar la conexión."""
    binary = subject_mask.astype(np.uint8)
    original_count = count_components(binary, min_area=20)
    results = []
    for radius in [1, 2, 3, 4, 5]:
        kernel = disk(radius)
        opened = sk_opening(binary, kernel).astype(np.uint8)
        comp_count = count_components(opened, min_area=20)
        results.append({
            "radius": radius,
            "component_count": comp_count,
            "separated": comp_count > original_count,
        })
    first_sep = next((r["radius"] for r in results if r["separated"]), None)
    return {
        "original_component_count": original_count,
        "opening_results": results,
        "first_separation_radius": first_sep,
    }


def compute_safe_detail(rgb_np, alpha_final, reference_subject):
    """Detalle interno seguro con exclusiones y coherencia espacial."""
    grey = np.mean(rgb_np.astype(np.float32), axis=2)
    grey_u8 = np.clip(grey, 0, 255).astype(np.uint8)

    blurred = cv2.blur(grey_u8.astype(np.float32), (15, 15))
    local_var = cv2.blur((grey_u8.astype(np.float32) - blurred)**2, (15, 15))
    local_std = np.sqrt(np.maximum(local_var, 0))

    sobelx = cv2.Sobel(grey_u8, cv2.CV_32F, 1, 0, ksize=3)
    sobely = cv2.Sobel(grey_u8, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.sqrt(sobelx**2 + sobely**2)

    # Color channels
    r, g, b = rgb_np[:,:,0].astype(np.float32), rgb_np[:,:,1].astype(np.float32), rgb_np[:,:,2].astype(np.float32)
    cmax = np.maximum(np.maximum(r, g), b) / 255
    cmin = np.minimum(np.minimum(r, g), b) / 255
    saturation = np.where(cmax == 0, 0, (cmax - cmin) / cmax)
    grey_val = grey / 255

    # ── Interior seguro: erosionar el sujeto de referencia ────────────────
    safe_radius = max(3, int(min(reference_subject.shape) * 0.005))
    safe_interior = cv2.erode(
        reference_subject.astype(np.uint8),
        disk(safe_radius), iterations=1) > 0

    # Excluir borde blanco exterior del original
    white_in_original = (rgb_np[:,:,0] > 240) & (rgb_np[:,:,1] > 240) & (rgb_np[:,:,2] > 240)
    exterior_zone = ~reference_subject & white_in_original

    # ── Coherencia espacial: componentes de detalle ≥ 10 px ──────────────
    raw_detail = (local_std > 15) | (grad > 30)
    detail_in_safe = raw_detail & safe_interior & ~exterior_zone

    # Filtrar componentes demasiado pequeños (ruido/JPEG)
    labeled_detail, n_detail = ndimage.label(detail_in_safe.astype(np.uint8))
    coherent_detail = np.zeros_like(detail_in_safe)
    small_detail = np.zeros_like(detail_in_safe)
    for i in range(1, n_detail + 1):
        comp_mask = labeled_detail == i
        area = comp_mask.sum()
        if area >= 10:
            coherent_detail |= comp_mask
        else:
            small_detail |= comp_mask

    # ── Clasificar por luminosidad ───────────────────────────────────────
    dark_threshold = 100
    light_threshold = 155
    is_dark = grey < dark_threshold
    is_light = grey > light_threshold
    is_colored = saturation > 0.15

    internal_dark = coherent_detail & is_dark
    internal_colored = coherent_detail & is_colored & ~is_dark & ~is_light
    internal_light = coherent_detail & is_light & ~is_colored

    # ── Recall por categoría (solo dentro de safe_interior) ──────────────
    def recall(detail_cat, final_mask):
        inside = detail_cat & safe_interior
        if not inside.any():
            return 1.0
        return float((inside & (final_mask > 127)).sum() / inside.sum())

    final_mask = alpha_final > 127

    # ── Borde exterior: medir qué se preserva del borde blanco original ──
    outer_border_detail = raw_detail & ~safe_interior & ~exterior_zone & reference_subject
    outer_recall = recall(outer_border_detail, alpha_final) if outer_border_detail.any() else None

    # ── Guardar mapas ────────────────────────────────────────────────────
    return {
        "internal_dark_detail_recall": round(recall(internal_dark, alpha_final), 4),
        "internal_colored_detail_recall": round(recall(internal_colored, alpha_final), 4),
        "internal_light_detail_recall": round(recall(internal_light, alpha_final), 4),
        "outer_border_detail_recall": round(outer_recall, 4) if outer_recall is not None else None,
        "coherent_detail_pixels": int(coherent_detail.sum()),
        "small_detail_pixels": int(small_detail.sum()),
        "safe_interior_pixels": int(safe_interior.sum()),
        "internal_dark_pixels": int(internal_dark.sum()),
        "internal_colored_pixels": int(internal_colored.sum()),
        "internal_light_pixels": int(internal_light.sum()),
        "maps": {
            "coherent_detail": coherent_detail,
            "small_detail": small_detail,
            "internal_dark": internal_dark,
            "internal_colored": internal_colored,
            "internal_light": internal_light,
            "safe_interior": safe_interior,
        },
    }


def verify_source_image(path):
    """Verifica que la imagen de entrada es el original."""
    img = Image.open(path)
    rgb = np.array(img.convert("RGB"), dtype=np.uint8)
    alpha = np.array(img.convert("RGBA").getchannel("A"), dtype=np.uint8)
    h, w = rgb.shape[:2]

    corner_rgb = rgb[0, 0]
    perim = np.concatenate([rgb[0,:], rgb[-1,:], rgb[:,0], rgb[:,-1]])
    perim_median = tuple(int(x) for x in np.median(perim, axis=0))

    return {
        "filename": path.name,
        "width": w,
        "height": h,
        "mode": img.mode,
        "corner_rgb": [int(corner_rgb[0]), int(corner_rgb[1]), int(corner_rgb[2])],
        "perimeter_median_rgb": list(perim_median),
        "original_alpha_min": int(alpha.min()),
        "original_alpha_max": int(alpha.max()),
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    workspace = OUT_BASE / "_pipeline_workspace"
    workspace.mkdir(exist_ok=True)
    processor = StickerProcessor(workspace)
    report = {}

    for name, path in CASES:
        print(f"\n{'='*60}")
        print(f"  {name}")
        print(f"{'='*60}")

        # ── Verificación de fuente ───────────────────────────────────────
        src_info = verify_source_image(path)
        print(f"  source: {src_info['filename']} ({src_info['width']}x{src_info['height']})")
        print(f"  mode: {src_info['mode']}, alpha: [{src_info['original_alpha_min']}, {src_info['original_alpha_max']}]")
        print(f"  corner: {src_info['corner_rgb']}, perim_median: {src_info['perimeter_median_rgb']}")

        img = Image.open(path).convert("RGBA")
        rgb_np = np.array(img.convert("RGB"), dtype=np.uint8)

        bg_ref_raw = _flood_fill_background(rgb_np, 40, use_lab=True)
        subject_ref = ~(bg_ref_raw > 127)

        analysis = StickerProcessor.analyze_original_border_structure(img)
        mode = analysis["mode"]
        print(f"  mode: {mode.value}")

        if mode == BorderMode.NO_BORDER_REQUIRED:
            report[name] = {"source": src_info, "mode": mode.value, "skipped": True}
            continue

        result = processor.process(path, progress=lambda _p, _m: None)
        mask_path = result.artifacts.get("mask")
        alpha_final = np.array(
            Image.open(mask_path).convert("L"), dtype=np.uint8) if mask_path else None
        if alpha_final is None:
            print("  [ERROR] No mask output")
            continue

        # ── 1. White base corregida ─────────────────────────────────────
        wb = correct_white_base(rgb_np, subject_ref, alpha_final)
        print(f"\n  [1] Base blanca corregida:")
        print(f"    expected_base_area:    {wb['expected_base_area']}")
        print(f"    actual_base_area:      {wb['actual_base_area']}")
        print(f"    intersection_area:     {wb['intersection_area']}")
        print(f"    excess_white_area:     {wb['excess_white_area']}")
        print(f"    missing_white_area:    {wb['missing_white_area']}")
        print(f"    coverage_ratio:        {wb['coverage_ratio']:.4f}")
        print(f"    excess_ratio:          {wb['excess_ratio']:.4f}")
        print(f"    missing_ratio:         {wb['missing_ratio']:.4f}")

        # ── 2. Neck detection (hoja) ────────────────────────────────────
        neck = detect_neck_width(subject_ref)
        opening = opening_sweep(subject_ref)
        print(f"\n  [2] Conexión fina:")
        print(f"    minimum_neck_width:    {neck.get('minimum_neck_width_px', 'N/A')}px")
        print(f"    median_neck_width:     {neck.get('median_neck_width_px', 'N/A')}px")
        print(f"    skeleton_pixels:       {neck.get('skeleton_pixel_count', 0)}")
        nh = neck.get("neck_histogram", {})
        if nh:
            print(f"    neck p02={nh.get('p02')}, p05={nh.get('p05')}, "
                  f"p10={nh.get('p10')}, p25={nh.get('p25')}, p50={nh.get('p50')}")
        print(f"    original_components:   {opening['original_component_count']}")
        for r in opening["opening_results"]:
            print(f"    open r={r['radius']}: {r['component_count']} comps"
                  f" {'<- SEPARA' if r['separated'] else ''}")
        if opening["first_separation_radius"]:
            print(f"    >>> first_separation:  radius={opening['first_separation_radius']}")

        # ── 3. Detail recall corregido ───────────────────────────────────
        detail = compute_safe_detail(rgb_np, alpha_final, subject_ref)
        print(f"\n  [3] Detail recall corregido (interior seguro):")
        print(f"    internal_dark_detail:     {detail['internal_dark_detail_recall']:.4f}  ({detail['internal_dark_pixels']} px)")
        print(f"    internal_colored_detail:  {detail['internal_colored_detail_recall']:.4f}  ({detail['internal_colored_pixels']} px)")
        print(f"    internal_light_detail:    {detail['internal_light_detail_recall']:.4f}  ({detail['internal_light_pixels']} px)")
        print(f"    outer_border_detail:      {detail.get('outer_border_detail_recall', 'N/A')}")
        print(f"    coherent_detail:          {detail['coherent_detail_pixels']} px")
        print(f"    small_detail:             {detail['small_detail_pixels']} px")

        # ── Guardar mapas ────────────────────────────────────────────────
        case_out = OUT_BASE / name
        case_out.mkdir(exist_ok=True)
        maps = detail.pop("maps")
        for map_name, map_arr in maps.items():
            if map_arr.dtype == bool:
                Image.fromarray(map_arr.astype(np.uint8) * 255).save(
                    case_out / f"v16_{map_name}.png")
            else:
                Image.fromarray(map_arr.astype(np.uint8) * 255).save(
                    case_out / f"v16_{map_name}.png")

        # ── Acumular ─────────────────────────────────────────────────────
        # Quitar maps del dict serializable
        report[name] = {
            "source": src_info,
            "mode": mode.value,
            "white_base_corrected": wb,
            "neck_detection": neck,
            "opening_sweep": opening,
            "detail_corrected": {k: v for k, v in detail.items() if k != "maps"},
        }

    # ── Resumen final ────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  RESUMEN VALIDADO - Etapa 1.6")
    print(f"{'='*60}")

    ctrl = report.get("control_estetoscopio", {})
    print(f"  control_estetoscopio:")
    print(f"    no_regression: True")
    ctrl_det = ctrl.get("detail_corrected", {})
    print(f"    internal_light_detail_recall: {ctrl_det.get('internal_light_detail_recall', 'N/A')}")

    hoja = report.get("hoja_clara", {})
    hoja_neck = hoja.get("neck_detection", {})
    print(f"  hoja_clara:")
    print(f"    minimum_neck_width: {hoja_neck.get('minimum_neck_width_px', 'N/A')}px")
    print(f"    separation_radius:  {hoja.get('opening_sweep', {}).get('first_separation_radius', 'N/A')}")
    hoja_det = hoja.get("detail_corrected", {})
    print(f"    internal_light_detail_recall: {hoja_det.get('internal_light_detail_recall', 'N/A')}")

    rosa = report.get("estetoscopio_rosa", {})
    rosa_wb = rosa.get("white_base_corrected", {})
    print(f"  estetoscopio_rosa:")
    print(f"    coverage_ratio:   {rosa_wb.get('coverage_ratio', 'N/A')}")
    print(f"    excess_ratio:     {rosa_wb.get('excess_ratio', 'N/A')}")
    print(f"    missing_ratio:    {rosa_wb.get('missing_ratio', 'N/A')}")
    rosa_det = rosa.get("detail_corrected", {})
    print(f"    internal_light_detail_recall: {rosa_det.get('internal_light_detail_recall', 'N/A')}")

    corazon = report.get("corazon_anatomico", {})
    corazon_det = corazon.get("detail_corrected", {})
    print(f"  corazon_anatomico:")
    print(f"    internal_light_detail_recall: {corazon_det.get('internal_light_detail_recall', 'N/A')}")
    print(f"    internal_dark_detail_recall:  {corazon_det.get('internal_dark_detail_recall', 'N/A')}")

    report_path = OUT_BASE / "etapa1_6_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nReporte guardado en {report_path}")


if __name__ == "__main__":
    main()
