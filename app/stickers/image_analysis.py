"""Análisis de imágenes para el creador de stickers.

Este módulo se encarga de analizar una imagen para determinar:
- Si tiene transparencia
- Los colores de las esquinas
- El posible fondo
- Si tiene borde blanco existente
- Métricas de calidad
- Confianza en la clasificación
- Casos ambiguos

No realiza modificaciones en la imagen, solo análisis.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.stickers.models import ImageAnalysis


# ══════════════════════════════════════════════════════════════════════════════
# Detección de transparencia
# ══════════════════════════════════════════════════════════════════════════════

def detect_transparency(rgba: Any) -> tuple[bool, float]:
    """Detecta si una imagen tiene transparencia significativa.

    Returns:
        (has_transparency, transparency_ratio)
    """
    from PIL import Image
    if not isinstance(rgba, Image.Image):
        rgba = Image.fromarray(np.asarray(rgba))
    alpha = rgba.getchannel("A")
    arr = np.asarray(alpha, dtype=np.float32) / 255.0
    has_transparency = arr.min() < 0.98
    transparency_ratio = float((arr < 0.05).mean())
    return has_transparency, transparency_ratio


# ══════════════════════════════════════════════════════════════════════════════
# Análisis de colores de esquinas
# ══════════════════════════════════════════════════════════════════════════════

def analyze_corner_colors(rgba: Any, corner_size: int = 10) -> dict[str, Any]:
    """Analiza los colores de las esquinas de la imagen."""
    from PIL import Image
    if not isinstance(rgba, Image.Image):
        rgba = Image.fromarray(np.asarray(rgba))
    rgb = rgba.convert("RGB")
    w, h = rgb.size
    cs = min(corner_size, w // 4, h // 4)

    corners = []
    for cx, cy in [(0, 0), (w - cs, 0), (0, h - cs), (w - cs, h - cs)]:
        region = rgb.crop((cx, cy, cx + cs, cy + cs))
        arr = np.asarray(region, dtype=np.float32)
        mean = tuple(int(arr[..., c].mean()) for c in range(3))
        corners.append(mean)

    corner_arr = np.array(corners, dtype=np.float32)
    spread = float(corner_arr.std(axis=0).mean())
    uniform = spread < 19

    return {
        "corner_colors": corners,
        "corner_spread": spread,
        "uniform_corners": uniform,
    }


def _simplified_saturation(r: int, g: int, b: int) -> float:
    """Calcula una saturación HSV simplificada (0–255)."""
    rgb_max = max(r, g, b)
    rgb_min = min(r, g, b)
    if rgb_max == 0:
        return 0.0
        return ((rgb_max - rgb_min) / rgb_max) * 255.0


# ══════════════════════════════════════════════════════════════════════════════
# Determinación del fondo
# ══════════════════════════════════════════════════════════════════════════════

def determine_background(rgba: Any, corner_info: dict | None = None) -> dict[str, Any]:
    """Determina el tipo de fondo de la imagen."""
    from PIL import Image
    if not isinstance(rgba, Image.Image):
        rgba = Image.fromarray(np.asarray(rgba))

    if corner_info is None:
        corner_info = analyze_corner_colors(rgba)

    corners = corner_info["corner_colors"]
    bg_color = tuple(int(c) for c in np.mean(corners, axis=0))

    r, g, b = bg_color
    brightness = 0.299 * r + 0.587 * g + 0.114 * b
    saturation = _simplified_saturation(r, g, b)

    if brightness < 60:
        bg_type = "dark"
        confidence = 0.9 if corner_info["corner_spread"] < 30 else 0.6
    elif brightness > 220 and saturation < 30:
        bg_type = "white"
        confidence = 0.95 if corner_info["corner_spread"] < 30 else 0.7
    elif corner_info["uniform_corners"]:
        bg_type = "color"
        confidence = 0.8
    else:
        bg_type = "mixed"
        confidence = 0.4

    has_transp, _ = detect_transparency(rgba)
    if has_transp:
        bg_type = "transparent"
        confidence = max(confidence, 0.85)

    return {
        "background_type": bg_type,
        "bg_color": bg_color,
        "confidence": confidence,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Detección de borde blanco existente
# ══════════════════════════════════════════════════════════════════════════════

def detect_existing_white_border(rgba: Any, tolerance: int = 30) -> dict[str, Any]:
    """Detecta si la imagen ya tiene un borde blanco existente."""
    from PIL import Image
    if not isinstance(rgba, Image.Image):
        rgba = Image.fromarray(np.asarray(rgba))
    rgb = np.asarray(rgba.convert("RGB"), dtype=np.uint8)
    h, w = rgb.shape[:2]

    border_width = min(40, w // 8, h // 8)
    if border_width < 2:
        return {"existing_white_border": False, "white_border_width": 0, "white_border_ratio": 0.0}

    edge_mask = np.zeros((h, w), dtype=bool)
    edge_mask[:border_width, :] = True
    edge_mask[-border_width:, :] = True
    edge_mask[:, :border_width] = True
    edge_mask[:, -border_width:] = True

    white = (rgb[..., 0] >= 255 - tolerance) & \
            (rgb[..., 1] >= 255 - tolerance) & \
            (rgb[..., 2] >= 255 - tolerance)
    white_in_border = white & edge_mask
    white_ratio = float(white_in_border.sum() / max(edge_mask.sum(), 1))

    white_width = 0
    if white_ratio > 0.3:
        for i in range(border_width):
            ring = np.zeros((h, w), dtype=bool)
            ring[i:i+1, :] = True
            ring[-(i+1):, :] = True
            ring[:, i:i+1] = True
            ring[:, -(i+1):] = True
            ring_white = (white & ring).sum() / max(ring.sum(), 1)
            if ring_white > 0.5:
                white_width = i + 1
            else:
                break

        return {
        "existing_white_border": white_ratio > 0.3,
        "white_border_width": white_width,
        "white_border_ratio": white_ratio,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Cálculo de métricas
# ══════════════════════════════════════════════════════════════════════════════

def calculate_metrics(rgba: Any) -> dict[str, Any]:
    """Calcula métricas de calidad de la imagen."""
    from PIL import Image, ImageFilter, ImageStat
    if not isinstance(rgba, Image.Image):
        rgba = Image.fromarray(np.asarray(rgba))

    w, h = rgba.size
    alpha = rgba.getchannel("A")
    alpha_arr = np.asarray(alpha, dtype=np.float32) / 255.0

    area_ratio = float((alpha_arr > 0.05).mean())

    gray = rgba.convert("L").filter(ImageFilter.FIND_EDGES)
    edge_density = float(ImageStat.Stat(gray).mean[0] / 255.0)

    sample = rgba.convert("RGB").resize((64, 64))
    colors = sample.convert("P", palette=1, colors=64).getcolors(4096)
    color_count = len(colors) if colors else 0

    resolution_ok = max(w, h) >= 800

    return {
        "area_ratio": area_ratio,
        "edge_density": edge_density,
        "color_count": color_count,
        "resolution_ok": resolution_ok,
        "width": w,
        "height": h,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Estimación de confianza
# ══════════════════════════════════════════════════════════════════════════════

def estimate_confidence(analysis: ImageAnalysis, metrics: dict[str, Any]) -> float:
    """Estima la confianza en la clasificación de la imagen (0.0–1.0)."""
    confidence = 0.5

    if analysis.has_transparency:
        confidence += 0.2
    if analysis.background_type in ("white", "dark", "color"):
        confidence += 0.15
    if analysis.existing_white_border:
        confidence += 0.1
    if metrics.get("resolution_ok", False):
        confidence += 0.05
    if metrics.get("color_count", 0) > 50:
        confidence -= 0.1
    if metrics.get("area_ratio", 0) < 0.01:
        confidence -= 0.15

        return max(0.0, min(1.0, confidence))


# ══════════════════════════════════════════════════════════════════════════════
# Clasificación de casos ambiguos
# ══════════════════════════════════════════════════════════════════════════════

def classify_ambiguous_cases(analysis: ImageAnalysis, metrics: dict[str, Any]) -> dict[str, Any]:
    """Clasifica casos ambiguos y determina si requieren revisión manual."""
    reasons: list[str] = []

    if analysis.has_transparency:
        case = "A"
        if analysis.transparency_ratio > 0.5:
            reasons.append("Alta proporción de transparencia")
    elif analysis.existing_white_border:
        case = "B"
    elif analysis.background_type in ("white", "dark", "color") and analysis.confidence > 0.7:
        case = "C"
    elif metrics.get("color_count", 0) > 40 and analysis.background_type == "mixed":
        case = "D"
    else:
        case = "ambiguous"
        reasons.append("No se pudo clasificar con confianza")

    requires_review = (
        case == "ambiguous"
        or analysis.confidence < 0.7
        or metrics.get("area_ratio", 0) < 0.01
    )

    if analysis.existing_white_border and analysis.background_type == "white":
        reasons.append("Fondo blanco con borde blanco existente: posible borde doble")

    return {
        "case_hypothesis": case,
        "requires_review": requires_review,
        "reasons": reasons,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Función principal de análisis
# ══════════════════════════════════════════════════════════════════════════════

def analyze_image(rgba: Any) -> ImageAnalysis:
    """Analiza una imagen y devuelve un ImageAnalysis completo."""
    from PIL import Image
    if not isinstance(rgba, Image.Image):
        rgba = Image.fromarray(np.asarray(rgba))

    w, h = rgba.size
    dpi = rgba.info.get("dpi")

    has_transparency, transparency_ratio = detect_transparency(rgba)
    corner_info = analyze_corner_colors(rgba)
    bg_info = determine_background(rgba, corner_info)
    border_info = detect_existing_white_border(rgba)
    metrics = calculate_metrics(rgba)

    analysis = ImageAnalysis(
        width=w,
        height=h,
        dpi=dpi,
        has_transparency=has_transparency,
        transparency_ratio=transparency_ratio,
        format=rgba.format or "",
        mode=rgba.mode,
        is_png=rgba.format == "PNG" if rgba.format else False,
        bg_color=bg_info["bg_color"],
        background_type=bg_info["background_type"],
        existing_white_border=border_info["existing_white_border"],
        existing_white_border_width=border_info["white_border_width"],
        metrics=metrics,
    )

    classification = classify_ambiguous_cases(analysis, metrics)
    analysis.case_hypothesis = classification["case_hypothesis"]
    analysis.requires_review = classification["requires_review"]
    analysis.metrics["classification_reasons"] = classification["reasons"]

    analysis.confidence = estimate_confidence(analysis, metrics)

    return analysis