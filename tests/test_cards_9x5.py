"""Regression tests for the physical 9x5 card imposition."""
import json
from pathlib import Path

from PIL import Image

from app.planchas.poster_print_editor import (
    CARD_SHEET_MM, CARD_SIZE_MM, CardFace, CardSlot, FitMode, ImageTransform,
    card_back_paint_rect_mm, card_slot_rect_mm, cards_9x5_from_project_state,
    cards_9x5_project_state, render_cards_9x5_page, reverse_card_slot_index,
)

DPI = 254  # exactly 10 pixels per mm, simplifying physical assertions
COLORS = [(210, 20, 20), (20, 180, 20), (20, 20, 210), (210, 180, 20), (180, 20, 180),
          (20, 180, 180), (130, 60, 20), (100, 100, 100), (250, 100, 20), (20, 100, 250)]


def _designs(tmp_path: Path) -> list[Path]:
    result = []
    for index, color in enumerate(COLORS):
        target = tmp_path / f"card_{index}.png"
        Image.new("RGB", (180, 100), color).save(target)
        result.append(target)
    return result


def _slots(paths: list[Path], *, back=True) -> list[CardSlot]:
    return [CardSlot(front=CardFace(path=path), back=CardFace(path=path) if back else CardFace()) for path in paths]


def _center_px(index: int) -> tuple[int, int]:
    x, y, w, h = card_slot_rect_mm(index)
    return round((x + w / 2) * 10), round((y + h / 2) * 10)


def test_physical_geometry_and_centered_matrix():
    assert CARD_SHEET_MM == (210.0, 297.0)
    assert CARD_SIZE_MM == (90.0, 50.0)
    assert card_slot_rect_mm(0) == (15.0, 23.5, 90.0, 50.0)
    assert card_slot_rect_mm(9) == (105.0, 223.5, 90.0, 50.0)
    # Margins: 15 mm left/right; 23.5 mm top/bottom.
    assert card_slot_rect_mm(0)[0] == 15.0
    assert card_slot_rect_mm(0)[1] == 23.5


def test_back_bleed_is_only_allowed_at_outer_matrix_edges():
    assert card_back_paint_rect_mm(0, 3.0) == (12.0, 20.5, 105.0, 73.5)
    # Internal shared edges retain the exact cut edge: no inter-card bleed.
    assert card_back_paint_rect_mm(1, 3.0) == (105.0, 20.5, 198.0, 73.5)
    assert card_back_paint_rect_mm(2, 3.0) == (12.0, 73.5, 105.0, 123.5)


def test_ten_different_back_designs_never_contaminate_neighbor_cut_areas(tmp_path: Path):
    page = render_cards_9x5_page(_slots(_designs(tmp_path)), "back", double_sided=True, bleed_mm=3, dpi=DPI, flip_mode="manual")
    for index, color in enumerate(COLORS):
        assert page.getpixel(_center_px(index)) == color
    # Immediately either side of the shared horizontal cut belongs to its own card.
    assert page.getpixel((1049, 485)) == COLORS[0]
    assert page.getpixel((1050, 485)) == COLORS[1]
    # And so does the shared vertical cut between rows 0/1.
    assert page.getpixel((600, 734)) == COLORS[0]
    assert page.getpixel((600, 735)) == COLORS[2]


def test_equal_mixed_and_replaced_designs_render_independently(tmp_path: Path):
    paths = _designs(tmp_path)
    slots = _slots([paths[0]] * 10)
    slots[4].front.path = paths[4]              # one replacement
    for i in (5, 6, 7, 8, 9):                   # five independently replaced
        slots[i].front.path = paths[i]
    page = render_cards_9x5_page(slots, dpi=DPI)
    assert page.getpixel(_center_px(0)) == COLORS[0]
    assert page.getpixel(_center_px(4)) == COLORS[4]
    assert page.getpixel(_center_px(9)) == COLORS[9]


def test_reverse_render_mapping_is_visually_correct_for_each_flip_mode(tmp_path: Path):
    slots = _slots(_designs(tmp_path))
    for flip_mode in ("long_edge", "short_edge", "manual"):
        page = render_cards_9x5_page(slots, "back", double_sided=True, dpi=DPI, flip_mode=flip_mode)
        for source_index, color in enumerate(COLORS):
            assert page.getpixel(_center_px(reverse_card_slot_index(source_index, flip_mode))) == color


def test_back_offsets_are_global_mm_with_tenth_mm_precision(tmp_path: Path):
    design = tmp_path / "marker.png"
    marker = Image.new("RGB", (180, 100), "white")
    for x in range(80, 100):
        for y in range(40, 60):
            marker.putpixel((x, y), (255, 0, 0))
    marker.save(design)
    slots = _slots([design] * 10)

    def marker_origin(page, slot):
        x, y, w, h = card_slot_rect_mm(slot)
        pixels = [(px, py) for py in range(round(y * 10), round((y + h) * 10))
                  for px in range(round(x * 10), round((x + w) * 10)) if page.getpixel((px, py)) == (255, 0, 0)]
        return min(px for px, _ in pixels), min(py for _, py in pixels)

    baseline = render_cards_9x5_page(slots, "back", double_sided=True, dpi=DPI, flip_mode="manual")
    for ox, oy, expected in ((1, 0, (10, 0)), (-1, 0, (-10, 0)), (0, 1, (0, 10)), (0, -1, (0, -10)), (.1, -.1, (1, -1))):
        shifted = render_cards_9x5_page(slots, "back", double_sided=True, dpi=DPI, flip_mode="manual", offset_x_mm=ox, offset_y_mm=oy)
        origin_0, origin_2 = marker_origin(shifted, 0), marker_origin(shifted, 2)
        baseline_0, baseline_2 = marker_origin(baseline, 0), marker_origin(baseline, 2)
        assert (origin_0[0] - baseline_0[0], origin_0[1] - baseline_0[1]) == expected
        # Both cards move equally: their relative placement is unchanged.
        assert (origin_2[0] - origin_0[0], origin_2[1] - origin_0[1]) == (baseline_2[0] - baseline_0[0], baseline_2[1] - baseline_0[1])


def test_front_offsets_are_applied_without_crossing_card_cut_areas(tmp_path: Path):
    """A front-side printer calibration moves artwork but not adjacent cards."""
    page = render_cards_9x5_page(
        _slots(_designs(tmp_path), back=False), dpi=DPI,
        offset_x_mm=1.0, offset_y_mm=0.0,
    )
    # The left edge of card 0 is now blank and its centre is shifted by 10 px.
    assert page.getpixel((150, 485)) == (255, 255, 255)
    assert page.getpixel((610, 485)) == COLORS[0]
    # The same shift may not let card 0 overwrite the start of card 1.
    assert page.getpixel((1050, 485)) == (255, 255, 255)
    assert page.getpixel((1060, 485)) == COLORS[1]


def test_cards_project_round_trip_preserves_faces_transforms_and_settings(tmp_path: Path):
    paths = _designs(tmp_path)
    slots = _slots(paths)
    slots[3].back.transform = ImageTransform(FitMode.MANUAL, 12.5, -7.25, 1.37, 90)
    project = cards_9x5_project_state(slots, double_sided=True, bleed_mm=3, offset_x_mm=-1.1,
                                      offset_y_mm=.1, flip_mode="short_edge", selected={3, 7})
    saved = tmp_path / "cards.cards_9x5.json"; saved.write_text(json.dumps(project), encoding="utf-8")
    restored, settings = cards_9x5_from_project_state(json.loads(saved.read_text(encoding="utf-8")))
    assert project["photo_print_mode"] == "cards_9x5"
    assert restored[3].back.path == paths[3]
    assert restored[3].back.transform == slots[3].back.transform
    assert settings == {"double_sided": True, "bleed_mm": 3.0, "offset_x_mm": -1.1, "offset_y_mm": .1,
                        "flip_mode": "short_edge", "selected": {3, 7}}


def test_render_has_no_preview_guides_and_is_a4_300dpi(tmp_path: Path):
    page = render_cards_9x5_page(_slots(_designs(tmp_path)), dpi=300)
    assert page.size == (2480, 3508)
    # Production render contains design pixels only, never preview guide colors.
    pixels = page.get_flattened_data()
    assert (54, 168, 255) not in pixels
    assert (245, 158, 11) not in pixels
    assert (34, 197, 94) not in pixels
