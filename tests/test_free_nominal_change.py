import sqlite3
from pathlib import Path

import pytest

from app.planchas.free_nominal import change_nominal_size, source_supports_nominal_at_300dpi
from app.planchas.model import HITBOX_INNER_CLEARANCE_CM, PlanchaItem, PlanchaProject
from app.planchas.production_geometry import production_min_for_nominal


def _item(width=8.9, height=4.45, rotation=0, x=6, y=8):
    return PlanchaItem(
        path="missing-source.png", name="wide", width_cm=width, height_cm=height,
        layout_width_cm=width + 2 * HITBOX_INNER_CLEARANCE_CM,
        layout_height_cm=height + 2 * HITBOX_INNER_CLEARANCE_CM,
        x_cm=x, y_cm=y, nominal_size_cm=8, order_nominal_size_cm=8,
        rotation=rotation, order_id=9, group_id="group", item_id="item", copy_number=3,
    )


def _center(item):
    return item.x_cm + item.reserved_width_cm / 2, item.y_cm + item.reserved_height_cm / 2


def test_change_8_to_10_uses_new_minimum_preserves_identity_ratio_and_center():
    item = _item()
    center, identity = _center(item), (item.item_id, item.group_id, item.copy_number)
    result = change_nominal_size(item, new_nominal_cm=10, margin_cm=.15, bottom_cm=29.55)
    assert result.changed
    assert item.nominal_size_cm == 10
    assert max(item.width_cm, item.height_cm) == pytest.approx(production_min_for_nominal(10))
    assert item.width_cm / item.height_cm == pytest.approx(2)
    assert _center(item) == pytest.approx(center)
    assert (item.item_id, item.group_id, item.copy_number) == identity
    assert item.reserved_width_cm - item.width_cm == pytest.approx(2 * HITBOX_INNER_CLEARANCE_CM)


def test_change_10_to_5_recalculates_the_new_range():
    item = _item(width=10.8, height=5.4)
    item.nominal_size_cm = 10
    result = change_nominal_size(item, new_nominal_cm=5, margin_cm=.15, bottom_cm=29.55)
    assert result.changed
    assert item.nominal_size_cm == 5
    assert max(item.width_cm, item.height_cm) == pytest.approx(production_min_for_nominal(5))


def test_change_keeps_rotated_rectangular_orientation():
    item = _item(width=4.45, height=8.9, rotation=90)
    result = change_nominal_size(item, new_nominal_cm=10, margin_cm=.15, bottom_cm=29.55)
    assert result.changed
    assert item.rotation == 90
    assert item.height_cm / item.width_cm == pytest.approx(2)


def test_change_rejects_when_it_does_not_fit_at_current_position():
    item = _item(x=.15, y=.15)
    before = item.to_dict()
    result = change_nominal_size(item, new_nominal_cm=15, margin_cm=.15, bottom_cm=29.55)
    assert not result.changed and result.reason == "outside_position"
    assert item.to_dict() == before


def test_change_rejects_nominal_physically_impossible_in_a4():
    item = _item()
    result = change_nominal_size(item, new_nominal_cm=30, margin_cm=.15, bottom_cm=29.55)
    assert not result.changed and result.reason == "impossible_a4"


def _test_dir() -> Path:
    path = Path(".codex_test_tmp") / "free_nominal_change"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_change_is_project_only_and_persists(tmp_path):
    folder = tmp_path
    db_path = folder / "orders.sqlite"
    db_path.unlink(missing_ok=True)
    db = sqlite3.connect(db_path)
    db.execute("create table order_designs (size_cm real)")
    db.execute("insert into order_designs values (8)")
    db.commit()
    item = _item()
    assert change_nominal_size(item, new_nominal_cm=10, margin_cm=.15, bottom_cm=29.55).changed
    assert db.execute("select size_cm from order_designs").fetchone()[0] == 8
    project = PlanchaProject([item], project_type="sticker_free")
    path = folder / "free.json"
    project.save(path)
    restored = PlanchaProject.load(path)
    saved = restored.items[0]
    assert restored.project_type == "sticker_free"
    assert saved.nominal_size_cm == 10
    assert saved.to_dict() == item.to_dict()
    db.close()


def test_real_asset_requires_enough_pixels_for_new_nominal(tmp_path):
    from PIL import Image

    item = _item()
    item.path = str(tmp_path / "tiny.png")
    Image.new("RGBA", (100, 100), "white").save(item.path)
    assert not source_supports_nominal_at_300dpi(item, 10)
    Image.new("RGBA", (1600, 1600), "white").save(item.path)
    assert source_supports_nominal_at_300dpi(item, 10)
