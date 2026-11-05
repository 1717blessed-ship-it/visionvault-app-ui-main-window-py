"""Política dimensional mínima para stickers antes de impresión.

Las funciones son estimaciones conservadoras: el corte ScanNCut de formas
irregulares puede variar levemente respecto de su bounding box.
"""

from __future__ import annotations

PRINT_SCALE = 0.9727
CUT_INSET_MM = 1.50
CUT_INSET_CM = CUT_INSET_MM / 10.0
MAX_FINAL_BONUS_CM = 0.50


def validate_print_scale(value) -> bool:
    """Escala lógica histórica 100 o compensación 97,27: backend aplica una vez."""
    try:
        return any(abs(float(value) - expected) < 0.00001 for expected in (100.0, PRINT_SCALE * 100))
    except (ValueError, TypeError):
        return False


def calibrated_print_pixels(width_px, height_px, dpi_x, dpi_y, source_dpi_x=300, source_dpi_y=300, *, printable_width=0, printable_height=0):
    """Geometría efectiva del Creador: una sola compensación, nunca auto-fit."""
    width = max(1, round(width_px * dpi_x / source_dpi_x * PRINT_SCALE))
    height = max(1, round(height_px * dpi_y / source_dpi_y * PRINT_SCALE))
    if (printable_width and width > printable_width + 2) or (printable_height and height > printable_height + 2):
        raise ValueError('La hoja calibrada no cabe en el área del driver. Revisá papel/perfil: no se aplicó una segunda reducción.')
    return width, height


def expected_final_size(production_cm: float) -> float:
    """Estimación del lado final tras impresión y corte interior."""
    return float(production_cm) * PRINT_SCALE - 2 * CUT_INSET_CM


def production_min_for_nominal(nominal_cm: float) -> float:
    """Mínimo preparado para que el lado final estimado alcance el nominal."""
    nominal = float(nominal_cm)
    if nominal <= 0:
        raise ValueError("El tamaño nominal debe ser positivo.")
    return (nominal + 2 * CUT_INSET_CM) / PRINT_SCALE


def production_max_for_nominal(nominal_cm: float) -> float:
    """Máximo comercial: evita que una hoja libre cambie el producto vendido."""
    nominal = float(nominal_cm)
    if nominal <= 0:
        raise ValueError("El tamaño nominal debe ser positivo.")
    return (nominal + MAX_FINAL_BONUS_CM + 2 * CUT_INSET_CM) / PRINT_SCALE


def proportional_production_size(
    nominal_major_cm: float, visible_width: float, visible_height: float,
) -> tuple[float, float]:
    """Escala un diseño sin deformarlo; el nominal siempre refiere al lado mayor."""
    width, height = float(visible_width), float(visible_height)
    if width <= 0 or height <= 0:
        width = height = 1.0
    major = production_min_for_nominal(nominal_major_cm)
    if width >= height:
        return major, major * height / width
    return major * width / height, major
