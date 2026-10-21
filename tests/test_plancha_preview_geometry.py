"""Contrato geométrico de la vista previa A4.

La UI sólo convierte estos centímetros a píxeles: no puede cambiar la página,
las dimensiones, la hitbox ni la rotación calculadas por el packing.
"""

from app.planchas.editor import preview_geometry
from app.planchas.model import PlanchaItem


def test_preview_geometry_matches_model_and_final_render_anchor():
    item = PlanchaItem(
        path="design.png",
        name="Rectangular",
        width_cm=8.0,
        height_cm=4.0,
        x_cm=3.25,
        y_cm=7.5,
        rotation=90,
        layout_width_cm=8.8,
        layout_height_cm=4.6,
    )

    geometry = preview_geometry(item, page_number=2)

    assert geometry["item_id"] == item.item_id
    assert geometry["page"] == 2
    assert geometry["x_cm"] == item.x_cm
    assert geometry["y_cm"] == item.y_cm
    assert geometry["width_cm"] == item.width_cm
    assert geometry["height_cm"] == item.height_cm
    assert geometry["layout_width_cm"] == item.reserved_width_cm
    assert geometry["layout_height_cm"] == item.reserved_height_cm
    assert geometry["rotation"] == item.rotation

    # Misma regla de centrado que consume render_sheet al componer el PNG.
    assert geometry["design_x_cm"] == item.x_cm + (item.reserved_width_cm - item.width_cm) / 2
    assert geometry["design_y_cm"] == item.y_cm + (item.reserved_height_cm - item.height_cm) / 2
