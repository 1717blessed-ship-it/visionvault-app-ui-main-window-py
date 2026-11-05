from pathlib import Path

import re
import pytest

from app.planchas.poster_print_editor import (
    CARD_SHEET_MM, PrinterProfile, PrinterProfileStore, export_a4_pdf,
    profile_offsets_for_side, render_cards_calibration_page,
)


def test_printer_profile_round_trip(tmp_path: Path):
    store = PrinterProfileStore(tmp_path / "profiles.json")
    profile = PrinterProfile("Epson", back_offset_x_mm=-1.1, back_offset_y_mm=.2,
                             flip_mode="short_edge", calibrated_at="2026-08-08T00:00:00+00:00")
    store.save([profile])
    assert store.load() == [profile]
    assert profile_offsets_for_side(profile, "back", .3, -.1) == (-.8, .1)
    assert profile_offsets_for_side(profile, "front") == (0.0, 0.0)


def test_calibration_sheet_is_a4_and_contains_real_scale_references():
    page = render_cards_calibration_page("front", dpi=254)
    assert page.size == (2100, 2970)
    # The 100 mm line starts at 15 mm / 282 mm and reaches exactly 1000 pixels later.
    assert page.getpixel((150, 2820)) == (0, 0, 0)
    assert page.getpixel((1150, 2820)) == (0, 0, 0)
    # Exact 90x50 card outline (A1) at the physical coordinates.
    assert page.getpixel((150, 235)) == (0, 0, 0)
    assert page.getpixel((1050, 735)) == (0, 0, 0)


def test_pdf_is_one_exact_a4_page_without_page_rescale(tmp_path: Path):
    pytest.importorskip("reportlab")
    target = tmp_path / "calibration.pdf"
    export_a4_pdf([render_cards_calibration_page("front")], target)
    # PDF points: 210 / 25.4 * 72 and 297 / 25.4 * 72.
    media_box = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", target.read_bytes())
    assert media_box
    assert float(media_box.group(1)) == pytest.approx(595.275591, abs=.00001)
    assert float(media_box.group(2)) == pytest.approx(841.889764, abs=.00001)


def test_calibration_back_uses_requested_flip_geometry():
    front = render_cards_calibration_page("front", dpi=254)
    back = render_cards_calibration_page("back", flip_mode="long_edge", dpi=254)
    # A1 front label/line exists in first cell; long-edge back maps A1 to column 2.
    assert front.getpixel((600, 485)) == (0, 0, 0)
    assert back.getpixel((1500, 485)) == (0, 0, 0)
