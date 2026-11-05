import pytest

from app.planchas.free_resize import FREE_RESIZE_STEP_CM, resize_productive_item
from app.planchas.model import HITBOX_INNER_CLEARANCE_CM, PlanchaItem
from app.planchas.production_geometry import production_max_for_nominal, production_min_for_nominal


def _item(width=8.5329, height=4.26645, rotation=0):
    return PlanchaItem(
        path="wide.png", name="wide", width_cm=width, height_cm=height,
        layout_width_cm=width + 2 * HITBOX_INNER_CLEARANCE_CM,
        layout_height_cm=height + 2 * HITBOX_INNER_CLEARANCE_CM,
        x_cm=6, y_cm=8, nominal_size_cm=8, rotation=rotation,
    )


def test_resize_clamps_to_productive_min_and_max_without_changing_nominal():
    item = _item()
    minimum, maximum = production_min_for_nominal(8), production_max_for_nominal(8)
    resize_productive_item(item, target_major_cm=1, margin_cm=.15, bottom_cm=29.55)
    assert max(item.width_cm, item.height_cm) == pytest.approx(minimum)
    resize_productive_item(item, target_major_cm=99, margin_cm=.15, bottom_cm=29.55)
    assert max(item.width_cm, item.height_cm) == pytest.approx(maximum)
    assert item.nominal_size_cm == 8


def test_resize_keeps_aspect_center_and_hitbox():
    item = _item()
    before_center = (item.x_cm + item.reserved_width_cm / 2, item.y_cm + item.reserved_height_cm / 2)
    resize_productive_item(item, target_major_cm=max(item.width_cm, item.height_cm) + FREE_RESIZE_STEP_CM, margin_cm=.15, bottom_cm=29.55)
    after_center = (item.x_cm + item.reserved_width_cm / 2, item.y_cm + item.reserved_height_cm / 2)
    assert item.width_cm / item.height_cm == pytest.approx(2)
    assert after_center == pytest.approx(before_center)
    assert item.reserved_width_cm - item.width_cm == pytest.approx(2 * HITBOX_INNER_CLEARANCE_CM)
    assert item.reserved_height_cm - item.height_cm == pytest.approx(2 * HITBOX_INNER_CLEARANCE_CM)


def test_resize_preserves_rotated_orientation_and_identity():
    item = _item(width=4.26645, height=8.5329, rotation=90)
    identity = item.item_id
    resize_productive_item(item, target_major_cm=8.8, margin_cm=.15, bottom_cm=29.55)
    assert item.height_cm / item.width_cm == pytest.approx(2)
    assert item.rotation == 90
    assert item.item_id == identity


def test_resize_does_not_overflow_when_center_is_near_edge():
    item = _item()
    item.x_cm = .15
    item.y_cm = .15
    before = (item.width_cm, item.height_cm, item.x_cm, item.y_cm)
    result = resize_productive_item(item, target_major_cm=production_max_for_nominal(8), margin_cm=.15, bottom_cm=29.55)
    assert not result.changed
    assert (item.width_cm, item.height_cm, item.x_cm, item.y_cm) == before
