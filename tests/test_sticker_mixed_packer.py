import uuid
from pathlib import Path

import pytest

from app.planchas.model import HITBOX_INNER_CLEARANCE_CM, PlanchaProject, validate_no_overlaps
from app.planchas.production_geometry import expected_final_size, production_max_for_nominal, production_min_for_nominal
from app.planchas.sticker_mixed import StickerMixedPacker


def _items():
    return PlanchaProject.from_images([
        {"path": "five.png", "visible_width": 100, "visible_height": 100, "order_id": 1, "order_quantity": 2, "order_size_cm": 5},
        {"path": "eight.png", "visible_width": 100, "visible_height": 100, "order_id": 1, "order_quantity": 3, "order_size_cm": 8},
        {"path": "ten.png", "visible_width": 100, "visible_height": 100, "order_id": 1, "order_quantity": 2, "order_size_cm": 10},
        {"path": "fifteen.png", "visible_width": 100, "visible_height": 100, "order_id": 1, "order_quantity": 1, "order_size_cm": 15},
    ]).items


def _all_items(layout):
    return [item for project in layout.projects for item in project.items]


def test_sticker_mixed_packer_keeps_copies_nominals_and_no_collisions():
    source = _items()
    layout = StickerMixedPacker().pack(source)
    packed = _all_items(layout)

    assert len(packed) == len(source)
    assert not layout.impossible_items
    assert layout.page_count <= layout.baseline_page_count
    assert {item.item_id for item in packed} == {item.item_id for item in source}
    assert {item.nominal_size_cm for item in packed} == {5, 8, 10, 15}
    assert all(validate_no_overlaps(project.items) for project in layout.projects)


def test_sticker_mixed_packer_uses_productive_range_and_group_size():
    layout = StickerMixedPacker().pack(_items())
    packed = _all_items(layout)
    for item in packed:
        major = max(item.width_cm, item.height_cm)
        assert major >= production_min_for_nominal(item.nominal_size_cm) - 1e-6
        assert major <= production_max_for_nominal(item.nominal_size_cm) + 1e-6
        assert expected_final_size(major) >= item.nominal_size_cm - 1e-6
        assert item.reserved_width_cm - item.width_cm == pytest.approx(2 * HITBOX_INNER_CLEARANCE_CM)

    groups = {}
    for item in packed:
        groups.setdefault(item.group_id, set()).add((round(item.width_cm, 6), round(item.height_cm, 6)))
    assert all(len(sizes) == 1 for sizes in groups.values())


def test_sticker_mixed_packer_preserves_rectangular_aspect_and_rotation():
    source = PlanchaProject.from_images([{
        "path": "wide.png", "visible_width": 200, "visible_height": 100,
        "order_id": 2, "order_quantity": 2, "order_size_cm": 8,
    }]).items
    layout = StickerMixedPacker().pack(source)
    packed = _all_items(layout)

    assert len(packed) == 2
    assert all(max(item.width_cm, item.height_cm) / min(item.width_cm, item.height_cm) == pytest.approx(2) for item in packed)
    assert all(item.nominal_size_cm == 8 for item in packed)
    assert all(item.height_cm > item.width_cm for item in source)
    assert all(item.rotation == 90 for item in source)
    assert all(item.height_cm > item.width_cm for item in packed)
    assert all(item.rotation == 90 for item in packed)
    assert all(not item.rotation_allowed for item in source)


def test_sticker_mixed_packer_keeps_existing_rectangular_orientation():
    source = PlanchaProject.from_images([{
        "path": "rotated-wide.png", "visible_width": 200, "visible_height": 100,
        "order_id": 3, "order_size_cm": 8,
    }]).items
    packed = _all_items(StickerMixedPacker(allow_rotation=False).pack(source))

    assert len(packed) == 1
    assert packed[0].rotation == 90
    assert packed[0].height_cm / packed[0].width_cm == pytest.approx(2)


def test_sticker_mixed_packer_rejects_item_without_nominal_size():
    item = PlanchaProject.from_images([{
        "path": "unknown.png", "visible_width": 100, "visible_height": 100,
    }]).items[0]
    item.nominal_size_cm = None
    with pytest.raises(ValueError, match="tamaño nominal"):
        StickerMixedPacker().pack([item])


def test_sticker_mixed_projects_persist_without_repacking(tmp_path):
    layout = StickerMixedPacker().pack(_items())
    project = layout.projects[0]
    folder = tmp_path
    folder.mkdir(exist_ok=True)
    path = folder / f"mixta_{uuid.uuid4().hex}.doccione-plancha.json"
    try:
        project.save(path)
        restored = PlanchaProject.load(path)

        assert restored.project_type == "sticker_mixed"
        assert [(item.item_id, item.x_cm, item.y_cm, item.rotation, item.width_cm, item.height_cm)
                for item in restored.items] == [
            (item.item_id, item.x_cm, item.y_cm, item.rotation, item.width_cm, item.height_cm)
            for item in project.items
        ]
    finally:
        path.unlink(missing_ok=True)


def test_sticker_mixed_compacts_visible_holes_without_collisions():
    placed = [
        {"x_cm": 0.15, "y_cm": 0.15, "layout_width_cm": 4.0, "layout_height_cm": 4.0},
        {"x_cm": 5.0, "y_cm": 6.0, "layout_width_cm": 3.0, "layout_height_cm": 3.0},
        {"x_cm": 0.15, "y_cm": 10.0, "layout_width_cm": 3.0, "layout_height_cm": 3.0},
    ]

    StickerMixedPacker()._compact_page(placed)

    assert placed[1]["y_cm"] == pytest.approx(0.15)
    assert placed[2]["y_cm"] < 10.0
    assert validate_no_overlaps(placed)
