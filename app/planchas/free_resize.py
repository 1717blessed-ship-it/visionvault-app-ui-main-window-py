"""Redimensionado productivo manual para planchas libres de stickers."""

from __future__ import annotations

from dataclasses import dataclass

from app.planchas.model import A4_WIDTH_CM, HITBOX_INNER_CLEARANCE_CM, PlanchaItem
from app.planchas.production_geometry import production_max_for_nominal, production_min_for_nominal


FREE_RESIZE_STEP_CM = 0.05


@dataclass(frozen=True)
class ProductiveResizeResult:
    changed: bool
    major_cm: float
    at_minimum: bool
    at_maximum: bool
    fits_area: bool


def resize_productive_item(
    item: PlanchaItem, *, target_major_cm: float, margin_cm: float, bottom_cm: float,
) -> ProductiveResizeResult:
    """Escala un item proporcionalmente dentro de sus límites comerciales.

    Conserva el centro de la hitbox. Si el tamaño pedido no entra, usa el mayor
    tamaño válido que permanece dentro del área imprimible sin desplazarlo.
    """
    if item.nominal_size_cm is None:
        raise ValueError("El sticker no tiene tamaño nominal definido.")
    old_major = max(item.width_cm, item.height_cm)
    old_layout_w, old_layout_h = item.reserved_width_cm, item.reserved_height_cm
    center_x = item.x_cm + old_layout_w / 2
    center_y = item.y_cm + old_layout_h / 2
    minimum = production_min_for_nominal(item.nominal_size_cm)
    maximum = production_max_for_nominal(item.nominal_size_cm)
    requested = min(max(float(target_major_cm), minimum), maximum)

    # La hitbox máxima permitida por el centro actual, sin mover el item.
    max_layout_w = 2 * min(center_x - margin_cm, (A4_WIDTH_CM - margin_cm) - center_x)
    max_layout_h = 2 * min(center_y - margin_cm, bottom_cm - center_y)
    aspect_w = item.width_cm / old_major
    aspect_h = item.height_cm / old_major
    area_limit = min(
        (max_layout_w - 2 * HITBOX_INNER_CLEARANCE_CM) / max(aspect_w, 1e-9),
        (max_layout_h - 2 * HITBOX_INNER_CLEARANCE_CM) / max(aspect_h, 1e-9),
    )
    target = min(requested, area_limit)
    if target < minimum - 1e-8:
        return ProductiveResizeResult(False, old_major, old_major <= minimum + 1e-8, old_major >= maximum - 1e-8, False)

    width, height = target * aspect_w, target * aspect_h
    layout_w = width + 2 * HITBOX_INNER_CLEARANCE_CM
    layout_h = height + 2 * HITBOX_INNER_CLEARANCE_CM
    item.width_cm, item.height_cm = width, height
    item.layout_width_cm, item.layout_height_cm = layout_w, layout_h
    item.x_cm, item.y_cm = center_x - layout_w / 2, center_y - layout_h / 2
    return ProductiveResizeResult(
        abs(target - old_major) > 1e-9, target,
        target <= minimum + 1e-8, target >= maximum - 1e-8,
        target >= requested - 1e-8,
    )
