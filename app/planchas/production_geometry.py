"""Política dimensional mínima para stickers antes de impresión.

Las funciones son estimaciones conservadoras: el corte ScanNCut de formas
irregulares puede variar levemente respecto de su bounding box.
"""

from __future__ import annotations

PRINT_SCALE = 0.9727
CUT_INSET_MM = 1.50
CUT_INSET_CM = CUT_INSET_MM / 10.0
MAX_FINAL_BONUS_CM = 0.50


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
