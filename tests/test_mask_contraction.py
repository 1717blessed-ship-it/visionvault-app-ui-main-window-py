from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.stickers.mask_contraction import contract_alpha_signed_distance
from app.stickers.models import ProcessingProfile
from app.stickers.pipeline import StickerProcessor


def _circle(size=240, radius=80):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((size//2-radius, size//2-radius,
                                  size//2+radius, size//2+radius), fill=255)
    return mask


def test_zero_contraction_is_byte_exact_and_non_destructive():
    mask = _circle()
    original = mask.tobytes()
    result, report = contract_alpha_signed_distance(mask, 0, 300, .08)
    assert result.tobytes() == original == mask.tobytes()
    assert report.contraction_px == 0


def test_one_mm_contracts_by_physical_distance_not_resize():
    mask = _circle()
    result, report = contract_alpha_signed_distance(mask, 1.0, 254, 0.05)
    before = np.asarray(mask) > 127
    after = np.asarray(result) > 127
    # 254 dpi => 10 px/mm; diameter falls approximately 20 px while canvas stays fixed.
    bx = np.where(before)[1]; ax = np.where(after)[1]
    assert mask.size == result.size
    assert 18 <= (bx.max()-bx.min()) - (ax.max()-ax.min()) <= 22
    assert report.contraction_px == pytest.approx(10.0)


def test_antialiasing_and_subpixel_edges_are_preserved():
    result, _ = contract_alpha_signed_distance(_circle(), .15, 300, .08)
    values = np.unique(np.asarray(result))
    assert 0 in values and 255 in values
    assert np.any((values > 0) & (values < 255))


def test_thin_connection_generates_review_warning():
    mask = Image.new("L", (180, 100), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((10, 20, 70, 80), fill=255)
    draw.ellipse((110, 20, 170, 80), fill=255)
    draw.rectangle((68, 48, 112, 52), fill=255)
    _, report = contract_alpha_signed_distance(mask, .5, 300, .05)
    assert report.requires_review
    assert report.components_after > report.components_before


def test_separated_small_element_loss_generates_review_warning():
    mask = _circle(180, 55)
    ImageDraw.Draw(mask).ellipse((8, 8, 14, 14), fill=255)
    _, report = contract_alpha_signed_distance(mask, .5, 300, .05)
    assert report.requires_review
    assert report.components_after < report.components_before


def test_small_contraction_preserves_fine_star_points():
    mask = Image.new("L", (220, 220), 0)
    points = []
    import math
    for index in range(10):
        angle = -math.pi / 2 + index * math.pi / 5
        radius = 88 if index % 2 == 0 else 34
        points.append((110 + math.cos(angle)*radius, 110 + math.sin(angle)*radius))
    ImageDraw.Draw(mask).polygon(points, fill=255)
    result, report = contract_alpha_signed_distance(mask, .1, 300, .05)
    contours, _ = cv2.findContours(
        (np.asarray(result) > 127).astype(np.uint8), cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE)
    assert len(contours) == 1
    assert len(cv2.approxPolyDP(contours[0], 2.0, True)) >= 10
    assert report.requires_review is False


def test_transparent_rgb_is_unchanged_when_alpha_is_contracted():
    rgba = Image.new("RGBA", (120, 120), (13, 77, 201, 0))
    alpha = _circle(120, 40)
    rgba.putalpha(alpha)
    contracted, _ = contract_alpha_signed_distance(alpha, .4, 300, .08)
    result = rgba.copy(); result.putalpha(contracted)
    assert result.convert("RGB").tobytes() == rgba.convert("RGB").tobytes()


@pytest.mark.parametrize("filename", ["original.png", "visual_support_600_OPAQUE.png"])
def test_real_disc_contraction_is_persisted_and_does_not_stack(tmp_path, filename):
    source = Path("artifacts/sticker-disc-human-review") / filename
    profile = ProcessingProfile(final_white_px=0)
    first = StickerProcessor(tmp_path / "first", profile).process(
        source, selection_contraction_mm=.2, selection_smoothing_mm=.08,
        automatic_recovery=False)
    second = StickerProcessor(tmp_path / "second", ProcessingProfile(final_white_px=0)).process(
        source, selection_contraction_mm=.2, selection_smoothing_mm=.08,
        automatic_recovery=False)
    assert first.analysis["selection_contraction"]["requested_mm"] == .2
    with Image.open(first.artifacts["selection_alpha_original"]) as base, \
         Image.open(first.artifacts["selection_alpha_contracted"]) as contracted:
        assert np.count_nonzero(np.asarray(contracted)) < np.count_nonzero(np.asarray(base))
    with Image.open(first.artifacts["master"]) as a, Image.open(second.artifacts["master"]) as b:
        assert a.convert("RGBA").tobytes() == b.convert("RGBA").tobytes()
        assert a.getchannel("A").getextrema() == (0, 255)
    assert first.profile["master_size_cm"] == second.profile["master_size_cm"]
    assert first.analysis["native_resolution"]["physical_size_cm"] == second.analysis["native_resolution"]["physical_size_cm"]
