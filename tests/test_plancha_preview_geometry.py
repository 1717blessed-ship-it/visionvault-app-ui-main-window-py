"""Contrato geométrico de la vista previa A4.

La UI sólo convierte estos centímetros a píxeles: no puede cambiar la página,
las dimensiones, la hitbox ni la rotación calculadas por el packing.
"""

from app.planchas.editor import PlanchaEditor, preview_geometry
from app.planchas.model import (
    FIVE_ROW_SIZE_CM,
    PlanchaItem,
    PlanchaProject,
    production_max_for_nominal,
    visible_bbox,
)


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


def test_every_preview_normalizes_legacy_standard_geometry_once():
    project = PlanchaProject(
        project_type="sticker_standard",
        items=[
            PlanchaItem(path="wide.png", name="Ancho", width_cm=3.0, height_cm=1.5, nominal_size_cm=5.0),
            PlanchaItem(path="tall.png", name="Alto", width_cm=2.0, height_cm=4.0, nominal_size_cm=5.0),
        ],
    )
    editor = object.__new__(PlanchaEditor)
    editor.project = project

    PlanchaEditor._prepare_current_project_for_preview(editor)

    expected = min(production_max_for_nominal(5.0), FIVE_ROW_SIZE_CM - 0.02)
    assert all(abs(max(item.width_cm, item.height_cm) - expected) < 0.001 for item in project.items)
    first_geometry = [(item.width_cm, item.height_cm, item.x_cm, item.y_cm) for item in project.items]

    # Canvas, impresión, aprobación, cliente y exportación pueden invocar
    # el mismo contrato repetidamente sin volver a escalar ni mover la plancha.
    PlanchaEditor._prepare_current_project_for_preview(editor)
    assert [(item.width_cm, item.height_cm, item.x_cm, item.y_cm) for item in project.items] == first_geometry


def test_preview_does_not_equalize_mixed_or_free_projects():
    for project_type in ("sticker_mixed", "sticker_free"):
        project = PlanchaProject(
            project_type=project_type,
            items=[PlanchaItem(path="custom.png", name="Libre", width_cm=3.0, height_cm=1.5)],
        )
        editor = object.__new__(PlanchaEditor)
        editor.project = project

        PlanchaEditor._prepare_current_project_for_preview(editor)

        assert (project.items[0].width_cm, project.items[0].height_cm) == (3.0, 1.5)


def test_visible_bbox_ignores_nearly_transparent_export_residue():
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    # Residuo imperceptible que antes agrandaba la caja a casi todo el lienzo.
    image.putpixel((2, 2), (255, 255, 255, 4))
    ImageDraw.Draw(image).rectangle((40, 30, 79, 89), fill=(255, 0, 0, 255))

    left, top, right, bottom = visible_bbox(image)

    assert left > 2 and top > 2
    assert left <= 40 < right
    assert top <= 30 < bottom
    assert left < 80 <= right
    assert top < 90 <= bottom


def test_standard_preview_recalculates_stale_ratio_from_visible_file(tmp_path):
    from PIL import Image, ImageDraw

    path = tmp_path / "balloon.png"
    image = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    image.putpixel((1, 1), (255, 255, 255, 3))
    ImageDraw.Draw(image).rectangle((70, 20, 129, 179), fill=(255, 0, 0, 255))
    image.save(path)
    item = PlanchaItem(
        path=str(path), name="Globo", width_cm=5.0, height_cm=5.68,
        nominal_size_cm=5.0,
    )
    project = PlanchaProject(project_type="sticker_standard", items=[item])

    assert project.normalize_standard_geometry() is True

    assert item.height_cm == min(production_max_for_nominal(5.0), FIVE_ROW_SIZE_CM - 0.02)
    assert item.width_cm < item.height_cm * 0.5
