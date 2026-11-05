"""Regression tests for full-page, content-aware smart collages."""

from pathlib import Path

from PIL import Image

from app.planchas.smart_collage import (
    CollageTemplateLibrary,
    ImportanceType,
    ImportantRegion,
    SmartCollageGenerator,
)


def _solid_images(tmp_path: Path, count: int) -> list[Path]:
    paths = []
    for index in range(count):
        path = tmp_path / f"image_{index}.png"
        Image.new("RGB", (240, 160), (index + 20, 80, 160)).save(path)
        paths.append(path)
    return paths


def test_five_image_template_covers_the_entire_canvas(tmp_path):
    paths = _solid_images(tmp_path, 5)
    collage = SmartCollageGenerator().create_collage(
        paths, canvas_width=500, canvas_height=700,
        template=CollageTemplateLibrary.five_focus(), gap=0,
    )

    assert collage.size == (500, 700)
    assert (255, 255, 255) not in list(collage.get_flattened_data())


def test_partial_template_is_redistributed_without_blank_cells(tmp_path):
    paths = _solid_images(tmp_path, 3)
    collage = SmartCollageGenerator().create_collage(
        paths, canvas_width=500, canvas_height=700,
        template=CollageTemplateLibrary.six_grid(), gap=0,
    )

    assert (255, 255, 255) not in list(collage.get_flattened_data())


def test_face_crop_prefers_a_window_that_contains_the_face():
    face = ImportantRegion(70, 40, 40, 40, 0.9, ImportanceType.FACE)
    box = SmartCollageGenerator._content_aware_crop_box((200, 100), (50, 100), [face])

    assert box[0] <= face.x
    assert box[1] <= face.y
    assert box[2] >= face.x + face.width
    assert box[3] >= face.y + face.height


def test_zoom_changes_the_visible_image_content(tmp_path):
    paths = _solid_images(tmp_path, 1)
    # Add a colored side so a real crop is observable after zooming.
    image = Image.open(paths[0])
    image.paste((250, 20, 20), (0, 0, 80, image.height))
    image.save(paths[0])
    generator = SmartCollageGenerator()
    normal = generator.create_collage(paths, 300, 500)
    zoomed = generator.create_collage(paths, 300, 500, image_scales={str(paths[0]): 1.8})

    assert normal.tobytes() != zoomed.tobytes()
