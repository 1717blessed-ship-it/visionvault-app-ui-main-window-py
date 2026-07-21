"""Etapa 1.5: métricas específicas de defectos visuales.

NO modifica el pipeline. Solo analiza imágenes originales y procesadas
para diagnosticar defectos concretos antes de implementar soluciones.
"""
import sys, io, json, logging
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

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

ALPHA_THRESHOLDS = [32, 96, 128, 192, 224]


# ── Helpers ──────────────────────────────────────────────────────────────────

def connected_components(mask_bool, min_area=1):
    """Devuelve lista de (area, bbox, mask) ordenada de mayor a menor."""
    from collections import deque
    h, w = mask_bool.shape
    visited = np.zeros_like(mask_bool, dtype=bool)
    components = []
    for y in range(h):
        for x in range(w):
            if mask_bool[y, x] and not visited[y, x]:
                q = deque([(x, y)])
                visited[y, x] = True
                pix = []
                while q:
                    cx, cy = q.popleft()
                    pix.append((cx, cy))
                    for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
                        nx, ny = cx+dx, cy+dy
                        if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx] and mask_bool[ny, nx]:
                            visited[ny, nx] = True
                            q.append((nx, ny))
                if len(pix) >= min_area:
                    arr = np.array(pix)
                    x_min, y_min = arr.min(axis=0)
                    x_max, y_max = arr.max(axis=0)
                    comp_mask = np.zeros_like(mask_bool)
                    comp_mask[arr[:,1], arr[:,0]] = True
                    components.append({
                        "area": len(pix),
                        "bbox": (int(x_min), int(y_min), int(x_max), int(y_max)),
                        "mask": comp_mask,
                        "centroid": (float(arr[:,0].mean()), float(arr[:,1].mean())),
                    })
    components.sort(key=lambda c: c["area"], reverse=True)
    return components


def measure_component_analysis(alpha_np, thresholds):
    """Analiza componentes conectados a múltiples umbrales de alfa."""
    results = {}
    for t in thresholds:
        binary = alpha_np > t
        comps = connected_components(binary, min_area=5)
        largest = comps[0]["area"] if comps else 0
        secondary = comps[1]["area"] if len(comps) > 1 else 0
        total = binary.sum()

        bridge_count = 0
        min_conn_width = 0
        if len(comps) >= 2:
            c1_mask = comps[0]["mask"]
            c2_mask = comps[1]["mask"]
            dilated1 = np.zeros_like(c1_mask)
            dilated2 = np.zeros_like(c2_mask)
            import cv2
            k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            dilated1 = cv2.dilate(c1_mask.astype(np.uint8), k3, iterations=1) > 0
            dilated2 = cv2.dilate(c2_mask.astype(np.uint8), k3, iterations=1) > 0
            bridge_zone = dilated1 & dilated2
            bridge_pixels = bridge_zone & (alpha_np > 10)
            bridge_count = int(bridge_pixels.sum())

            for width in range(1, 20):
                k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (width*2+1, width*2+1))
                dilated1_w = cv2.dilate(c1_mask.astype(np.uint8), k, iterations=1) > 0
                dilated2_w = cv2.dilate(c2_mask.astype(np.uint8), k, iterations=1) > 0
                if (dilated1_w & dilated2_w & (alpha_np > 10)).any():
                    min_conn_width = width
                    break

        results[f"t_{t}"] = {
            "component_count": len(comps),
            "largest_area": largest,
            "secondary_area": secondary,
            "bridge_pixel_count": bridge_count,
            "minimum_connection_width_px": min_conn_width,
        }
    return results


def measure_detail_preservation(rgb_np, alpha_final, subject_mask):
    """Métrica de preservación de detalle basada en RGB, no en alfa."""
    grey = np.mean(rgb_np.astype(np.float32), axis=2)

    local_std = np.zeros_like(grey)
    grad_mag = np.zeros_like(grey)
    import cv2
    grey_u8 = np.clip(grey, 0, 255).astype(np.uint8)
    local_std = cv2.blur(
        (grey_u8.astype(np.float32) - cv2.blur(grey_u8.astype(np.float32), (15,15)))**2,
        (15, 15))
    local_std = np.sqrt(np.maximum(local_std, 0))
    sobelx = cv2.Sobel(grey_u8, cv2.CV_32F, 1, 0, ksize=3)
    sobely = cv2.Sobel(grey_u8, cv2.CV_32F, 0, 1, ksize=3)
    grad_mag = np.sqrt(sobelx**2 + sobely**2)

    detail_mask = (local_std > 15) | (grad_mag > 30)
    detail_in_subject = detail_mask & subject_mask
    detail_in_final = detail_mask & (alpha_final > 127)

    detail_recall = float(detail_in_final.sum() / max(detail_in_subject.sum(), 1))

    dark_detail = detail_mask & (grey < 100)
    light_detail = detail_mask & (grey > 155)
    dark_recall = float(
        (dark_detail & (alpha_final > 127)).sum() / max(dark_detail.sum(), 1))
    light_recall = float(
        (light_detail & (alpha_final > 127)).sum() / max(light_detail.sum(), 1))

    return {
        "detail_recall": detail_recall,
        "dark_detail_recall": dark_recall,
        "light_detail_recall": light_recall,
        "detail_pixel_count": int(detail_mask.sum()),
        "detail_in_subject_count": int(detail_in_subject.sum()),
    }


def measure_white_base_quality(rgb_np, alpha_np, subject_mask):
    """Calidad de la base blanca alrededor del diseño (para estetoscopio rosa)."""
    import cv2

    white_mask = (
        (rgb_np[:,:,0] > 235) & (rgb_np[:,:,1] > 235) & (rgb_np[:,:,2] > 235))
    white_in_subject = white_mask & subject_mask
    white_in_final = white_mask & (alpha_np > 127)

    if not white_in_subject.any():
        return {"error": "no white base found in subject"}

    coverage = float(white_in_final.sum() / max(white_in_subject.sum(), 1))

    dist = cv2.distanceTransform(
        white_in_final.astype(np.uint8), cv2.DIST_L2, 5)
    valid_dist = dist[dist > 0]

    continuity_components = connected_components(white_in_final, min_area=10)
    largest_white = continuity_components[0]["area"] if continuity_components else 0

    total_white = white_in_final.sum()
    if len(continuity_components) > 1:
        hole_area = sum(c["area"] for c in continuity_components[1:])
    else:
        hole_area = 0

    return {
        "white_base_coverage": coverage,
        "white_base_largest_component": largest_white,
        "white_base_total_px": int(total_white),
        "white_base_hole_px": hole_area,
        "white_base_hole_ratio": float(hole_area / max(total_white, 1)),
        "median_base_thickness_px": float(np.median(valid_dist)) if len(valid_dist) > 0 else 0,
        "minimum_base_thickness_px": float(valid_dist.min()) if len(valid_dist) > 0 else 0,
        "maximum_base_thickness_px": float(valid_dist.max()) if len(valid_dist) > 0 else 0,
    }


def measure_border_thickness(alpha_np, target_final_white_px=30):
    """Grosor del borde blanco exterior con distanceTransform."""
    import cv2

    binary = (alpha_np > 127).astype(np.uint8)
    dist = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
    inv_dist = cv2.distanceTransform(1 - binary, cv2.DIST_L2, 5)

    border_zone = (inv_dist <= target_final_white_px * 1.5) & (binary == 0)
    border_dist = inv_dist[border_zone]

    if len(border_dist) == 0:
        return {"error": "no border zone found"}

    return {
        "median_white_border_thickness": float(np.median(border_dist)),
        "p90_white_border_thickness": float(np.percentile(border_dist, 90)),
        "maximum_white_border_thickness": float(border_dist.max()),
        "border_thickness_variation": float(border_dist.std()),
        "target_border_thickness_px": target_final_white_px,
    }


def measure_detached_component(rgb_np, alpha_np, subject_mask):
    """Analiza componente(s) separados(s) del diseño principal."""
    binary = alpha_np > 127
    comps = connected_components(binary, min_area=5)
    if len(comps) < 2:
        return {"detached_count": 0, "components": []}

    main_area = comps[0]["area"]
    main_bbox = comps[0]["bbox"]
    main_cx, main_cy = comps[0]["centroid"]
    h, w = alpha_np.shape
    main_diag = np.sqrt(main_area)

    results = []
    for comp in comps[1:]:
        area_ratio = comp["area"] / max(main_area, 1)
        cx, cy = comp["centroid"]
        dist_ratio = np.sqrt((cx - main_cx)**2 + (cy - main_cy)**2) / max(main_diag, 1)

        comp_rgb = rgb_np[comp["mask"]]
        mean_color = comp_rgb.mean(axis=0) if len(comp_rgb) > 0 else np.array([0,0,0])
        sat = _rgb_saturation(mean_color)
        color_var = float(comp_rgb.std()) if len(comp_rgb) > 0 else 0.0

        grey = np.mean(rgb_np.astype(np.float32), axis=2)
        comp_grey = grey[comp["mask"]]
        dark_pix = (comp_grey < 80).sum()
        total_pix = comp["area"]
        dark_line_ratio = float(dark_pix / max(total_pix, 1))

        local_std_img = np.zeros_like(grey)
        import cv2
        grey_u8 = np.clip(grey, 0, 255).astype(np.uint8)
        blurred_sq = cv2.blur(grey_u8.astype(np.float32), (7,7))
        blurred = cv2.blur(grey_u8.astype(np.float32), (7,7))
        local_var = np.maximum(cv2.blur((grey_u8.astype(np.float32) - blurred)**2, (7,7)), 0)
        local_std_img = np.sqrt(local_var)
        texture_pix = (local_std_img[comp["mask"]] > 15).sum()
        texture_ratio = float(texture_pix / max(total_pix, 1))

        results.append({
            "area": comp["area"],
            "area_ratio": round(area_ratio, 4),
            "distance_ratio": round(dist_ratio, 4),
            "centroid": (round(cx, 1), round(cy, 1)),
            "mean_rgb": [round(float(c), 0) for c in mean_color],
            "saturation": round(sat, 3),
            "color_variance": round(color_var, 2),
            "dark_line_ratio": round(dark_line_ratio, 4),
            "texture_ratio": round(texture_ratio, 4),
            "bbox": comp["bbox"],
        })
    return {"detached_count": len(results), "components": results}


def _rgb_saturation(rgb):
    r, g, b = rgb[0]/255, rgb[1]/255, rgb[2]/255
    cmax = max(r, g, b)
    cmin = min(r, g, b)
    if cmax == 0:
        return 0.0
    return (cmax - cmin) / cmax


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

        img = Image.open(path).convert("RGBA")
        rgb_np = np.array(img.convert("RGB"), dtype=np.uint8)
        h, w = rgb_np.shape[:2]

        analysis = StickerProcessor.analyze_original_border_structure(img)
        mode = analysis["mode"]
        print(f"  mode: {mode.value}")

        if mode == BorderMode.NO_BORDER_REQUIRED:
            report[name] = {"mode": mode.value, "skipped": True}
            continue

        bg_ref_raw = _flood_fill_background(rgb_np, 40, use_lab=True)
        bg_mask = bg_ref_raw > 127
        subject_mask = ~bg_mask

        result = processor.process(path, progress=lambda _p, _m: None)
        mask_path = result.artifacts.get("mask")
        alpha_final = np.array(
            Image.open(mask_path).convert("L"), dtype=np.uint8) if mask_path else None
        clean_path = result.artifacts.get("clean")
        clean_img = Image.open(clean_path).convert("RGBA") if clean_path else None

        if alpha_final is None:
            print("  [ERROR] No mask output")
            continue

        # ── 1. Componentes a varios umbrales ─────────────────────────────
        comp_analysis = measure_component_analysis(alpha_final, ALPHA_THRESHOLDS)
        print(f"\n  [1] Componentes conectados:")
        for t_key, data in comp_analysis.items():
            t_val = t_key.split("_")[1]
            print(f"    t={t_val:>3}: count={data['component_count']}, "
                  f"largest={data['largest_area']}, "
                  f"secondary={data['secondary_area']}, "
                  f"bridges={data['bridge_pixel_count']}, "
                  f"min_conn={data['minimum_connection_width_px']}px")

        # ── 2. Preservación de detalle ───────────────────────────────────
        detail = measure_detail_preservation(rgb_np, alpha_final, subject_mask)
        print(f"\n  [2] Preservación de detalle:")
        print(f"    detail_recall:     {detail['detail_recall']:.3f}")
        print(f"    dark_detail:       {detail['dark_detail_recall']:.3f}")
        print(f"    light_detail:      {detail['light_detail_recall']:.3f}")
        print(f"    detail_pixels:     {detail['detail_pixel_count']}")
        print(f"    in_subject:        {detail['detail_in_subject_count']}")

        # Guardar mapas de detalle
        grey = np.mean(rgb_np.astype(np.float32), axis=2)
        import cv2
        grey_u8 = np.clip(grey, 0, 255).astype(np.uint8)
        local_var = cv2.blur((grey_u8.astype(np.float32) - cv2.blur(grey_u8.astype(np.float32), (15,15)))**2, (15,15))
        local_std = np.sqrt(np.maximum(local_var, 0))
        sobelx = cv2.Sobel(grey_u8, cv2.CV_32F, 1, 0, ksize=3)
        sobely = cv2.Sobel(grey_u8, cv2.CV_32F, 0, 1, ksize=3)
        grad = np.sqrt(sobelx**2 + sobely**2)
        detail_mask = ((local_std > 15) | (grad > 30)).astype(np.uint8) * 255
        detail_preserved = (detail_mask > 0) & (alpha_final > 127)
        detail_lost = (detail_mask > 0) & (alpha_final <= 127) & subject_mask

        case_out = OUT_BASE / name
        case_out.mkdir(exist_ok=True)
        Image.fromarray(detail_mask).save(case_out / "detail_map_original.png")
        Image.fromarray(detail_preserved.astype(np.uint8) * 255).save(case_out / "detail_preserved.png")
        Image.fromarray(detail_lost.astype(np.uint8) * 255).save(case_out / "detail_lost.png")

        # ── 3. Calidad de base blanca ────────────────────────────────────
        white_base = measure_white_base_quality(rgb_np, alpha_final, subject_mask)
        print(f"\n  [3] Base blanca:")
        for k, v in white_base.items():
            if isinstance(v, float):
                print(f"    {k}: {v:.4f}")
            else:
                print(f"    {k}: {v}")

        # ── 4. Grosor de borde ───────────────────────────────────────────
        border = measure_border_thickness(alpha_final, PROFILE.final_white_px)
        print(f"\n  [4] Grosor de borde blanco:")
        for k, v in border.items():
            if isinstance(v, float):
                print(f"    {k}: {v:.2f}")
            else:
                print(f"    {k}: {v}")

        # ── 5. Componentes separados ─────────────────────────────────────
        detached = measure_detached_component(rgb_np, alpha_final, subject_mask)
        print(f"\n  [5] Componentes separados: {detached['detached_count']}")
        for comp in detached.get("components", []):
            print(f"    area={comp['area']} ({comp['area_ratio']:.1%} of main), "
                  f"dist={comp['distance_ratio']:.2f}, "
                  f"sat={comp['saturation']:.3f}, "
                  f"texture={comp['texture_ratio']:.3f}, "
                  f"dark_lines={comp['dark_line_ratio']:.3f}, "
                  f"color_var={comp['color_variance']:.1f}, "
                  f"mean_rgb={comp['mean_rgb']}")

        # ── Guardar máscara y limpieza ───────────────────────────────────
        Image.fromarray(alpha_final).save(case_out / "final_mask.png")

        # ── Acumular reporte ─────────────────────────────────────────────
        report[name] = {
            "mode": mode.value,
            "components_by_threshold": comp_analysis,
            "detail": detail,
            "white_base": white_base,
            "border": border,
            "detached": {k: v for k, v in detached.items() if k != "components"},
            "detached_components": detached.get("components", []),
        }

    # ── Diagnóstico esperado ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  DIAGNOSTICO ESPERADO")
    print(f"{'='*60}")

    ctrl = report.get("control_estetoscopio", {})
    ctrl_detached = ctrl.get("detached_components", [])
    meaningful = any(
        c["area_ratio"] > 0.01 and c["saturation"] > 0.05
        for c in ctrl_detached)
    print(f"  control_estetoscopio:")
    print(f"    no_regression:              True")
    print(f"    meaningful_detached:        {meaningful}")

    hoja = report.get("hoja_clara", {})
    hoja_comp_t96 = hoja.get("components_by_threshold", {}).get("t_96", {})
    bridge = hoja_comp_t96.get("bridge_pixel_count", 0)
    min_conn = hoja_comp_t96.get("minimum_connection_width_px", 0)
    print(f"  hoja_clara:")
    print(f"    low_contrast_detail_loss:   {hoja.get('detail',{}).get('light_detail_recall',1) < 0.9}")
    print(f"    bridge_pixels_at_t96:       {bridge}")
    print(f"    min_connection_width:       {min_conn}px")

    rosa = report.get("estetoscopio_rosa", {})
    wb = rosa.get("white_base", {})
    print(f"  estetoscopio_rosa:")
    print(f"    incomplete_white_base:      {wb.get('white_base_coverage', 1) < 0.95}")
    print(f"    base_coverage:              {wb.get('white_base_coverage', 0):.1%}")

    corazon = report.get("corazon_anatomico", {})
    brd = corazon.get("border", {})
    print(f"  corazon_anatomico:")
    print(f"    excessive_white_border:     {brd.get('median_white_border_thickness', 0) > brd.get('target_border_thickness_px', 30) * 1.3}")
    print(f"    median_border_thickness:    {brd.get('median_white_border_thickness', 0):.1f}px "
          f"(target: {brd.get('target_border_thickness_px', 30)}px)")

    # ── Guardar reporte ──────────────────────────────────────────────────
    report_path = OUT_BASE / "etapa1_5_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nReporte guardado en {report_path}")


if __name__ == "__main__":
    main()
