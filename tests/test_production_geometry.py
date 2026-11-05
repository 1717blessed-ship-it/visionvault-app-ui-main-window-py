import math

import pytest

from app.planchas.model import (
    FIVE_ROW_SIZE_CM,
    HITBOX_INNER_CLEARANCE_CM,
    SPECIAL_GEOMETRIC,
    PlanchaItem,
    STANDARD_FIVE_BANDS,
    PlanchaProject,
    optimize_multipage,
    maximize_special_multipage,
)
from app.planchas.production_geometry import (
    expected_final_size,
    production_min_for_nominal,
    production_max_for_nominal,
    proportional_production_size,
)


@pytest.mark.parametrize("nominal", [2, 5, 8, 10, 15, 20, 29])
def test_inverse_policy_reaches_nominal_after_estimated_process(nominal):
    production = production_min_for_nominal(nominal)
    assert expected_final_size(production) >= nominal - 1e-9


def test_forward_policy_uses_print_scale_and_cut_inset():
    assert expected_final_size(8.0) == pytest.approx(7.4816)


@pytest.mark.parametrize("nominal", [5, 8, 10, 15])
def test_commercial_maximum_caps_final_bonus(nominal):
    assert expected_final_size(production_max_for_nominal(nominal)) == pytest.approx(nominal + 0.5)


@pytest.mark.parametrize("dimensions, expected", [((200, 100), (8.0, 4.0)), ((100, 200), (4.0, 8.0))])
def test_rectangles_keep_aspect_ratio(dimensions, expected):
    width, height = proportional_production_size(8, *dimensions)
    assert width / height == pytest.approx(expected[0] / expected[1])
    assert max(width, height) == pytest.approx(production_min_for_nominal(8))


def test_standard_slot_contains_production_and_keeps_nominal_in_order_data():
    item = PlanchaProject.from_images([{
        "path": "standard.png", "visible_width": 100, "visible_height": 100,
        "order_size_cm": 5.0, "order_packing_mode": STANDARD_FIVE_BANDS,
    }]).items[0]
    assert item.nominal_size_cm == 5.0
    assert item.production_width_cm == pytest.approx(FIVE_ROW_SIZE_CM - 0.02)
    assert item.reserved_width_cm == pytest.approx(FIVE_ROW_SIZE_CM)
    assert item.production_width_cm < item.reserved_width_cm


def test_special_packing_uses_production_as_cut_and_larger_hitbox():
    item = PlanchaProject.from_images([{
        "path": "special.png", "visible_width": 100, "visible_height": 100,
        "order_size_cm": 8.0, "order_packing_mode": SPECIAL_GEOMETRIC,
    }]).items[0]
    result = optimize_multipage([item], margin_cm=0.15)
    placed = result.pages[0].placed[0]
    assert placed["cut_width_cm"] == pytest.approx(item.production_width_cm)
    assert placed["layout_width_cm"] == pytest.approx(item.production_width_cm + 2 * HITBOX_INNER_CLEARANCE_CM)
    assert expected_final_size(placed["cut_width_cm"]) >= item.nominal_size_cm - 1e-9


def test_special_rectangle_uses_only_inner_clearance_for_hitbox():
    item = PlanchaProject.from_images([{
        "path": "wide.png", "visible_width": 200, "visible_height": 100,
        "order_size_cm": 8.0, "order_packing_mode": SPECIAL_GEOMETRIC,
    }]).items[0]
    placed = optimize_multipage([item], margin_cm=0.15).pages[0].placed[0]
    assert max(placed["cut_width_cm"], placed["cut_height_cm"]) == pytest.approx(production_min_for_nominal(8))
    assert min(placed["cut_width_cm"], placed["cut_height_cm"]) == pytest.approx(production_min_for_nominal(8) / 2)
    assert placed["cut_height_cm"] > placed["cut_width_cm"]
    effective_cut_width = placed["cut_height_cm"] if placed.get("rotated") else placed["cut_width_cm"]
    effective_cut_height = placed["cut_width_cm"] if placed.get("rotated") else placed["cut_height_cm"]
    assert placed["layout_width_cm"] - effective_cut_width == pytest.approx(2 * HITBOX_INNER_CLEARANCE_CM)
    assert placed["layout_height_cm"] - effective_cut_height == pytest.approx(2 * HITBOX_INNER_CLEARANCE_CM)


def test_large_nominal_is_impossible_without_reducing_it():
    item = PlanchaProject.from_images([{
        "path": "large.png", "visible_width": 100, "visible_height": 100,
        "order_size_cm": 20.0, "order_packing_mode": SPECIAL_GEOMETRIC,
    }]).items[0]
    result = optimize_multipage([item], margin_cm=0.15)
    assert not result.pages
    assert len(result.impossible) == 1
    assert result.impossible[0]["cut_width_cm"] == pytest.approx(item.production_width_cm)
    assert "producción mínima" in result.impossible[0]["impossible_reason"].lower()
    assert item.nominal_size_cm == 20.0


def test_special_global_maximization_preserves_pages_copies_and_group_geometry():
    items = PlanchaProject.from_images([{
        "path": "eight.png", "visible_width": 100, "visible_height": 100,
        "order_id": 1, "order_quantity": 6, "order_size_cm": 8.0,
        "order_packing_mode": SPECIAL_GEOMETRIC,
    }]).items
    baseline = optimize_multipage(items, margin_cm=0.15)
    result, scale = maximize_special_multipage(items, margin_cm=0.15)
    placed = [entry for page in result.pages for entry in page.placed]
    assert scale >= 1
    assert len(result.pages) <= len(baseline.pages)
    assert len(placed) == len(items)
    assert len({round(entry["cut_width_cm"], 6) for entry in placed}) == 1
    assert all(entry["cut_width_cm"] >= items[0].production_width_cm for entry in placed)
    assert all(expected_final_size(entry["cut_width_cm"]) <= 8.5 + 1e-9 for entry in placed)


def test_special_maximization_is_deterministic():
    items = [PlanchaItem(path=f"{i}.png", name="x", width_cm=production_min_for_nominal(8), height_cm=production_min_for_nominal(8), group_id="same") for i in range(6)]
    snapshots = []
    for _ in range(3):
        result, scale = maximize_special_multipage(items, margin_cm=0.15)
        snapshots.append((round(scale, 6), [(round(x["x_cm"], 4), round(x["y_cm"], 4), round(x["cut_width_cm"], 4), x["rotated"]) for p in result.pages for x in p.placed]))
    assert snapshots[0] == snapshots[1] == snapshots[2]
