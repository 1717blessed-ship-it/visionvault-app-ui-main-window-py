"""Contracción física no destructiva de máscaras alfa."""

from __future__ import annotations

from dataclasses import dataclass, asdict

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class ContractionReport:
    requested_mm: float
    smoothing_mm: float
    effective_dpi: float
    contraction_px: float
    smoothing_px: float
    area_before_px: int
    area_after_px: int
    retained_area_ratio: float
    components_before: int
    components_after: int
    requires_review: bool
    warnings: tuple[str, ...]

    def to_dict(self):
        data = asdict(self)
        data["warnings"] = list(self.warnings)
        return data


def offset_alpha_signed_distance(alpha: Image.Image, offset_mm: float,
                                 effective_dpi: float,
                                 smoothing_mm: float = 0.08):
    """Desplaza el contorno: positivo contrae y negativo expande."""
    offset_mm = float(offset_mm)
    if not -2 <= offset_mm <= 2:
        raise ValueError("El desplazamiento debe estar entre -2 y 2 mm.")
    return _offset_alpha(alpha, offset_mm, effective_dpi, smoothing_mm)


def contract_alpha_signed_distance(alpha: Image.Image, contraction_mm: float,
                                   effective_dpi: float,
                                   smoothing_mm: float = 0.08):
    """Desplaza el contorno alfa hacia dentro mediante distancia firmada.

    El tamaño del raster no cambia. Cero milímetros devuelve exactamente los
    bytes de entrada. La transición subpíxel se reconstruye como cobertura y
    no se aplica ninguna operación a RGB.
    """
    contraction_mm = float(contraction_mm)
    if not 0 <= contraction_mm <= 2:
        raise ValueError("La contracción debe estar entre 0 y 2 mm.")
    return _offset_alpha(alpha, contraction_mm, effective_dpi, smoothing_mm)


def expand_alpha_signed_distance(alpha: Image.Image, expansion_mm: float,
                                 effective_dpi: float,
                                 smoothing_mm: float = 0.08):
    """Expande la selección sin reescalar el raster ni modificar RGB."""
    expansion_mm = float(expansion_mm)
    if not 0 <= expansion_mm <= 2:
        raise ValueError("La expansión debe estar entre 0 y 2 mm.")
    result, report = _offset_alpha(alpha, -expansion_mm, effective_dpi, smoothing_mm)
    return result, report


def _offset_alpha(alpha: Image.Image, contraction_mm: float,
                  effective_dpi: float, smoothing_mm: float):
    contraction_mm = float(contraction_mm)
    smoothing_mm = float(smoothing_mm)
    effective_dpi = float(effective_dpi)
    if not np.isfinite(effective_dpi) or effective_dpi <= 0:
        raise ValueError("La resolución efectiva debe ser positiva.")
    if not -2 <= contraction_mm <= 2:
        raise ValueError("El desplazamiento debe estar entre -2 y 2 mm.")
    if not 0 <= smoothing_mm <= 1:
        raise ValueError("El suavizado debe estar entre 0 y 1 mm.")

    source = alpha.convert("L")
    arr = np.asarray(source, dtype=np.uint8)
    foreground = arr > 127
    before_area = int(foreground.sum())
    before_components = max(0, cv2.connectedComponents(
        foreground.astype(np.uint8), connectivity=8)[0] - 1)
    contraction_px = contraction_mm * effective_dpi / 25.4
    smoothing_px = smoothing_mm * effective_dpi / 25.4
    if abs(contraction_px) <= 1e-9:
        report = ContractionReport(
            contraction_mm, smoothing_mm, effective_dpi, 0.0, smoothing_px,
            before_area, before_area, 1.0, before_components,
            before_components, False, ())
        return source.copy(), report

    inside = cv2.distanceTransform(foreground.astype(np.uint8), cv2.DIST_L2, 5)
    outside = cv2.distanceTransform((~foreground).astype(np.uint8), cv2.DIST_L2, 5)
    signed = np.where(foreground, inside - .5, -(outside - .5)).astype(np.float32)
    # El alfa fuente ajusta la localización subpíxel del isocontorno sin
    # convertir colores claros/oscuros en geometría.
    fractional = (arr > 0) & (arr < 255)
    signed += np.where(
        fractional, arr.astype(np.float32) / 255.0 - .5, 0.0)
    feather = max(.35, smoothing_px)
    coverage = np.clip(.5 + (signed - contraction_px) / feather, 0.0, 1.0)
    result_arr = np.rint(coverage * 255).astype(np.uint8)
    after = result_arr > 127
    after_area = int(after.sum())
    after_components = max(0, cv2.connectedComponents(
        after.astype(np.uint8), connectivity=8)[0] - 1)
    retained = float(after_area / max(1, before_area))
    warnings = []
    if before_area and not after_area:
        warnings.append("La contracción elimina toda la selección.")
    if after_components < before_components:
        warnings.append("La contracción elimina uno o más elementos separados.")
    elif after_components > before_components:
        warnings.append("La contracción corta conexiones o divide elementos.")
    if retained < .85:
        warnings.append("La contracción pierde más del 15 % de la superficie seleccionada.")
    report = ContractionReport(
        contraction_mm, smoothing_mm, effective_dpi, contraction_px,
        smoothing_px, before_area, after_area, retained, before_components,
        after_components, bool(warnings), tuple(warnings))
    return Image.fromarray(result_arr, mode="L"), report
