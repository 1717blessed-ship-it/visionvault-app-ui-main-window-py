import tkinter as tk
from unittest.mock import patch


from app.planchas.editor import PlanchaEditor
from app.planchas.model import PlanchaItem, PlanchaProject


def test_optimizer_keeps_every_hitbox_on_a_shared_band_line():
    items = [
        PlanchaItem(path=f"{index}.png", name=str(index), width_cm=4.2, height_cm=4.8)
        for index in range(10)
    ]
    project = PlanchaProject(items)

    assert project.optimize() == []

    band_height = project.usable_height / 5
    bands: dict[int, list[PlanchaItem]] = {}
    for item in project.items:
        band = int((item.y_cm - project.margin_cm) / band_height)
        bands.setdefault(band, []).append(item)

    assert set(bands).issubset({0, 1, 2, 3, 4})
    for row in bands.values():
        assert len({item.y_cm for item in row}) == 1
        visual_row = sorted(row, key=lambda item: item.x_cm)
        assert all(
            previous.x_cm + previous.width_cm + project.gap_cm <= current.x_cm + 0.001
            for previous, current in zip(visual_row, visual_row[1:])
        )


def test_optimizer_places_larger_hitboxes_before_smaller_ones():
    items = [
        PlanchaItem(path="small.png", name="small", width_cm=2.0, height_cm=2.0),
        PlanchaItem(path="large.png", name="large", width_cm=5.0, height_cm=5.0),
        PlanchaItem(path="medium.png", name="medium", width_cm=3.0, height_cm=3.0),
    ]
    project = PlanchaProject(items)

    assert project.optimize() == []

    top_row = min(project.items, key=lambda item: (item.y_cm, item.x_cm))
    assert top_row.name == "large"


def test_special_plancha_keeps_a_large_sticker_that_classic_five_bands_rejects():
    large = PlanchaItem(path="large.png", name="large", width_cm=8.0, height_cm=10.0)

    classic = PlanchaProject([PlanchaItem.from_dict(large.to_dict())])
    assert classic.optimize() == classic.items

    special = PlanchaProject([large], layout_mode="special")
    assert special.optimize() == []
    assert special.items[0].width_cm == 8.0
    assert special.items[0].height_cm == 10.0
    assert special.to_dict()["layout_mode"] == "special"


def test_a5_workspace_is_persisted_and_limits_the_usable_half_of_the_a4():
    item = PlanchaItem(path="a5.png", name="a5", width_cm=4.0, height_cm=4.0)
    project = PlanchaProject([item], workspace_format="a5")

    assert project.workspace_ratio == 1 / 2
    assert project.usable_height == (29.7 - project.margin_cm * 2) / 2
    assert project.optimize() == []
    assert item.y_cm + item.height_cm <= project.workspace_bottom_cm
    assert project.to_dict()["workspace_format"] == "a5"


def test_horizontal_band_rejects_stickers_taller_than_one_fifth_of_the_a4():
    too_tall = PlanchaItem(path="large.png", name="large", width_cm=4.0, height_cm=6.0)
    project = PlanchaProject([too_tall], workspace_format="franja")

    assert project.optimize() == [too_tall]


# --- geometric packing validation tests ---

from app.planchas.model import (
    A4_HEIGHT_CM,
    A4_WIDTH_CM,
    DEFAULT_EXTRA_LAYOUT_CM,
    DEFAULT_MARGIN_CM,
    PlanchaProject,
    effective_layout_size,
    fits_in_printable_area,
    geometric_pack,
    optimize_multipage,
    pack_all_pages,
    item_cut_size,
    validate_free_rectangles,
    validate_no_overlaps,
    validate_package_geometry,
    validate_overflow,
    sort_items,
)


def test_geometric_pack_marks_impossible_size_as_overflow():
    item = PlanchaItem(path="impossible.png", name="impossible", width_cm=20.0, height_cm=20.0)
    result = geometric_pack([item], extra_cm=0.75, allow_rotation=True)

    assert result.overflow
    assert not result.placed
    assert validate_overflow(result.placed, result.overflow)


def assert_geometric_result_is_valid(result):
    assert validate_no_overlaps(result.placed)
    assert validate_package_geometry(result.placed)
    assert validate_free_rectangles(result.free_rectangles, result.placed)
    assert result.placed is not None


def test_geometric_physical_impossible_item_in_overflow():
    impossible = {"cut_width_cm": 50.0, "cut_height_cm": 50.0}
    possible = {"cut_width_cm": 5.0, "cut_height_cm": 5.0}
    result = geometric_pack([possible, impossible], extra_cm=DEFAULT_EXTRA_LAYOUT_CM, allow_rotation=True)
    assert impossible in result.overflow
    assert any(item["cut_width_cm"] == 5.0 and item["cut_height_cm"] == 5.0 for item in result.placed)


def test_geometric_space_limited_overflow_is_distinct_from_physical_impossible():
    item_a = {"cut_width_cm": 15.0, "cut_height_cm": 15.0}
    item_b = {"cut_width_cm": 15.0, "cut_height_cm": 15.0}
    # Each item fits individually
    assert fits_in_printable_area(effective_layout_size(*item_cut_size(item_a), DEFAULT_EXTRA_LAYOUT_CM))
    result = geometric_pack([item_a, item_b], extra_cm=DEFAULT_EXTRA_LAYOUT_CM, allow_rotation=True)
    # Ambos caben de forma aislada, pero solo uno entra en esta A4. Por lo
    # tanto el segundo overflow no es un fallo de tamaño físico.
    assert len(result.placed) == 1
    assert len(result.overflow) == 1
    overflow_item = result.overflow[0]
    layout = effective_layout_size(*item_cut_size(overflow_item), DEFAULT_EXTRA_LAYOUT_CM)
    assert fits_in_printable_area(layout, margin_cm=DEFAULT_MARGIN_CM, allow_rotation=True)


def test_geometric_pack_validates_no_overlaps_and_bounds():
    items = [
        PlanchaItem(path="g1.png", name="g1", width_cm=5.0, height_cm=5.0),
        PlanchaItem(path="g2.png", name="g2", width_cm=3.0, height_cm=3.0),
        PlanchaItem(path="g3.png", name="g3", width_cm=7.0, height_cm=4.0),
    ]
    result = geometric_pack(items, extra_cm=0.75, allow_rotation=True)

    assert_geometric_result_is_valid(result)
    assert result.placed


def test_geometric_pack_respects_strategy_difference():
    items = [
        {"cut_width_cm": 8.0, "cut_height_cm": 3.0},
        {"cut_width_cm": 6.0, "cut_height_cm": 5.0},
        {"cut_width_cm": 9.0, "cut_height_cm": 2.0},
    ]
    area_result = geometric_pack(items, extra_cm=0.75, allow_rotation=True, strategy="area_desc")
    long_result = geometric_pack(items, extra_cm=0.75, allow_rotation=True, strategy="longest_side_desc")

    assert area_result.strategy == "area_desc"
    assert long_result.strategy == "longest_side_desc"
    assert [p["cut_width_cm"] for p in area_result.placed] != [p["cut_width_cm"] for p in long_result.placed]


def test_geometric_pack_physical_overflow_vs_space():
    possible = {"cut_width_cm": 10.0, "cut_height_cm": 10.0}
    overflow = {"cut_width_cm": 20.0, "cut_height_cm": 20.0}
    result = geometric_pack([possible, overflow], extra_cm=DEFAULT_EXTRA_LAYOUT_CM, allow_rotation=True)

    assert validate_no_overlaps(result.placed)
    assert validate_package_geometry(result.placed)
    assert validate_free_rectangles(result.free_rectangles, result.placed)
    assert any(item["cut_width_cm"] == 20.0 for item in result.overflow)
    assert any(item["cut_width_cm"] == 10.0 for item in result.placed)


def test_geometric_pack_deterministic():
    items = [
        {"cut_width_cm": 7.0, "cut_height_cm": 3.0},
        {"cut_width_cm": 5.0, "cut_height_cm": 5.0},
        {"cut_width_cm": 4.0, "cut_height_cm": 4.0},
    ]
    first = geometric_pack(items, extra_cm=DEFAULT_EXTRA_LAYOUT_CM, allow_rotation=True)
    second = geometric_pack(items, extra_cm=DEFAULT_EXTRA_LAYOUT_CM, allow_rotation=True)

    assert first.placed == second.placed
    assert first.overflow == second.overflow
    assert first.packing_occupancy == second.packing_occupancy
    assert first.cut_occupancy == second.cut_occupancy
    assert first.strategy == second.strategy


def test_multipage_optimizer_chooses_a_global_strategy_deterministically():
    items = (
        [{"cut_width_cm": 15.0, "cut_height_cm": 8.0}]
        + [{"cut_width_cm": 10.0, "cut_height_cm": 6.0}] * 2
        + [{"cut_width_cm": 7.0, "cut_height_cm": 7.0}] * 3
        + [{"cut_width_cm": 5.0, "cut_height_cm": 5.0}] * 6
        + [{"cut_width_cm": 3.0, "cut_height_cm": 3.0}] * 8
    )
    first = optimize_multipage(items)
    second = optimize_multipage(items)

    assert first.strategy == "area_desc"  # desempate estable de la batería actual
    assert len(first.pages) == 2
    assert first.total_placed == len(items)
    assert not first.impossible
    assert first.strategy == second.strategy
    assert [page.placed for page in first.pages] == [page.placed for page in second.pages]
    for page in first.pages:
        assert validate_no_overlaps(page.placed)
        assert validate_package_geometry(page.placed)


def test_pack_all_pages_separates_physical_impossibles():
    result = pack_all_pages(
        [{"cut_width_cm": 5.0, "cut_height_cm": 5.0}, {"cut_width_cm": 50.0, "cut_height_cm": 50.0}],
        strategy="area_desc",
    )

    assert result.total_placed == 1
    assert len(result.impossible) == 1
    assert result.impossible[0]["cut_width_cm"] == 50.0


def test_geometric_pack_handles_rotated_rectangle_and_keeps_size_consistent():
    items = [
        {"cut_width_cm": 20.0, "cut_height_cm": 5.0},
        {"cut_width_cm": 3.0, "cut_height_cm": 3.0},
    ]

    result = geometric_pack(items, extra_cm=0.75, allow_rotation=True)

    assert result.placed
    assert all(
        sorted([p["layout_width_cm"], p["layout_height_cm"]])
        == sorted([p["cut_width_cm"] + 0.75, p["cut_height_cm"] + 0.75])
        for p in result.placed
    )
    assert all(
        p["layout_width_cm"] <= A4_WIDTH_CM - DEFAULT_MARGIN_CM * 2 + 1e-9
        and p["layout_height_cm"] <= A4_HEIGHT_CM - DEFAULT_MARGIN_CM * 2 + 1e-9
        for p in result.placed
    )
    assert any(
        p.get("rotated") and p["cut_width_cm"] == 20.0 and p["layout_width_cm"] == 5.75
        for p in result.placed
    )


def test_geometric_pack_supports_rectangular_and_small_large_mix():
    items = [
        {"cut_width_cm": 15.0, "cut_height_cm": 8.0},
        {"cut_width_cm": 5.0, "cut_height_cm": 5.0},
        {"cut_width_cm": 3.0, "cut_height_cm": 3.0},
        {"cut_width_cm": 7.0, "cut_height_cm": 7.0},
    ]
    result = geometric_pack(items, extra_cm=0.75, allow_rotation=True)

    assert result.placed
    assert validate_no_overlaps(result.placed)
    assert result.placed[0]["layout_width_cm"] >= 15.0
    assert result.placed[0]["layout_height_cm"] >= 8.0


def test_geometric_cases_are_valid_for_known_case_battery():
    cases = {
        "A": [
            {"cut_width_cm": 5.0, "cut_height_cm": 5.0},
        ] * 12,
        "B": [
            {"cut_width_cm": 5.0, "cut_height_cm": 5.0},
        ] * 8
        + [{"cut_width_cm": 3.0, "cut_height_cm": 3.0}] * 8,
        "C": [
            {"cut_width_cm": 7.0, "cut_height_cm": 7.0},
        ] * 3
        + [{"cut_width_cm": 5.0, "cut_height_cm": 5.0}] * 4
        + [{"cut_width_cm": 3.0, "cut_height_cm": 3.0}] * 5,
        "D": [
            {"cut_width_cm": 10.0, "cut_height_cm": 6.0},
        ]
        + [{"cut_width_cm": 5.0, "cut_height_cm": 5.0}] * 4
        + [{"cut_width_cm": 3.0, "cut_height_cm": 3.0}] * 6,
        "E": [
            {"cut_width_cm": 15.0, "cut_height_cm": 8.0},
        ]
        + [{"cut_width_cm": 5.0, "cut_height_cm": 5.0}] * 4
        + [{"cut_width_cm": 3.0, "cut_height_cm": 3.0}] * 6,
        "F": [
            {"cut_width_cm": 21.0, "cut_height_cm": 2.0},
        ]
        + [{"cut_width_cm": 3.0, "cut_height_cm": 3.0}] * 5,
        "G": [
            {"cut_width_cm": 15.0, "cut_height_cm": 8.0},
        ]
        + [{"cut_width_cm": 3.0, "cut_height_cm": 3.0}] * 10,
        "H": [{"cut_width_cm": 20.0, "cut_height_cm": 20.0}],
        "I": [{"cut_width_cm": 29.0, "cut_height_cm": 2.0}],
        "J": [
            {"cut_width_cm": 19.0, "cut_height_cm": 4.0},
            {"cut_width_cm": 17.0, "cut_height_cm": 5.0},
            {"cut_width_cm": 15.0, "cut_height_cm": 6.0},
            {"cut_width_cm": 13.0, "cut_height_cm": 7.0},
            {"cut_width_cm": 11.0, "cut_height_cm": 8.0},
            {"cut_width_cm": 9.0, "cut_height_cm": 9.0},
            {"cut_width_cm": 7.0, "cut_height_cm": 7.0},
            {"cut_width_cm": 5.0, "cut_height_cm": 5.0},
            {"cut_width_cm": 3.0, "cut_height_cm": 3.0},
            {"cut_width_cm": 2.0, "cut_height_cm": 2.0},
        ],
    }

    for name, items in cases.items():
        result = geometric_pack(items, extra_cm=DEFAULT_EXTRA_LAYOUT_CM, allow_rotation=True)
        assert_geometric_result_is_valid(result), f"{name} failed geometric invariants"


def test_editor_experimental_toggle_routes_to_the_correct_packing_engine():
    root = tk.Tk()
    root.withdraw()
    try:
        editor = PlanchaEditor(root, images=[])
        editor.project.items = [
            PlanchaItem(path="item1.png", name="item1", width_cm=5.0, height_cm=5.0),
            PlanchaItem(path="item2.png", name="item2", width_cm=3.0, height_cm=3.0),
        ]
        with patch("app.planchas.model.geometric_pack") as mocked_geometric, patch.object(PlanchaProject, "optimize", return_value=[]) as mocked_classic:
            editor.use_experimental_packing = False
            editor.organize_automatically()
            mocked_classic.assert_called_once()
            mocked_geometric.assert_not_called()

        with patch("app.planchas.model.geometric_pack") as mocked_geometric, patch.object(PlanchaProject, "optimize", return_value=[]) as mocked_classic:
            editor.use_experimental_packing = True
            editor.organize_automatically()
            mocked_geometric.assert_called_once()
            mocked_classic.assert_not_called()

        editor.use_experimental_packing = False
        assert not editor.use_experimental_packing
    finally:
        root.destroy()
