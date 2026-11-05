"""Cambio explícito de tamaño comercial en una plancha libre de stickers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.planchas.model import A4_WIDTH_CM, HITBOX_INNER_CLEARANCE_CM, PlanchaItem, visible_bbox
from app.planchas.production_geometry import production_max_for_nominal, production_min_for_nominal


PRINT_DPI = 300


@dataclass(frozen=True)
class NominalChangeResult:
    changed: bool
    reason: str | None = None


def change_nominal_size(
    item: PlanchaItem, *, new_nominal_cm: float, margin_cm: float, bottom_cm: float,
) -> NominalChangeResult:
    """Aplica el mínimo productivo del nuevo nominal sin mover el centro.

    Esta función sólo modifica al item recibido; no conoce el packing ni pedidos.
    """
    nominal = float(new_nominal_cm)
    new_major = production_min_for_nominal(nominal)
    old_major = max(item.width_cm, item.height_cm)
    if old_major <= 0:
        raise ValueError("El sticker no tiene geometría productiva válida.")
    ratio_w, ratio_h = item.width_cm / old_major, item.height_cm / old_major
    width, height = new_major * ratio_w, new_major * ratio_h
    layout_w = width + 2 * HITBOX_INNER_CLEARANCE_CM
    layout_h = height + 2 * HITBOX_INNER_CLEARANCE_CM

    # Primero distingue una medida imposible en la A4 de una que sólo no entra
    # en su posición actual.
    printable_w = A4_WIDTH_CM - 2 * margin_cm
    printable_h = bottom_cm - margin_cm
    if layout_w > printable_w + 1e-9 or layout_h > printable_h + 1e-9:
        return NominalChangeResult(False, "impossible_a4")

    center_x = item.x_cm + item.reserved_width_cm / 2
    center_y = item.y_cm + item.reserved_height_cm / 2
    x, y = center_x - layout_w / 2, center_y - layout_h / 2
    if x < margin_cm - 1e-9 or y < margin_cm - 1e-9 or x + layout_w > A4_WIDTH_CM - margin_cm + 1e-9 or y + layout_h > bottom_cm + 1e-9:
        return NominalChangeResult(False, "outside_position")

    item.nominal_size_cm = nominal
    item.width_cm, item.height_cm = width, height
    item.layout_width_cm, item.layout_height_cm = layout_w, layout_h
    item.x_cm, item.y_cm = x, y
    return NominalChangeResult(True)


def source_supports_nominal_at_300dpi(item: PlanchaItem, nominal_cm: float) -> bool:
    """Comprueba el raster visible para el máximo del nuevo rango comercial.

    Una ruta inexistente se deja a cargo del flujo de biblioteca/exportación: no
    se finge una imagen ni se escala. Las rutas reales deben cumplir 300 DPI.
    """
    path = Path(item.path)
    if not path.is_file():
        return True
    try:
        from PIL import Image

        with Image.open(path) as image:
            left, top, right, bottom = visible_bbox(image)
        available_major_px = max(right - left, bottom - top)
    except Exception:
        return False
    required_major_px = production_max_for_nominal(nominal_cm) / 2.54 * PRINT_DPI
    return available_major_px + 1e-6 >= required_major_px
