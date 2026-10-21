from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.planchas.model import PlanchaProject
from app.planchas.production_geometry import production_max_for_nominal, production_min_for_nominal
from app.stickers.models import ProcessingProfile
from app.stickers.pipeline import StickerProcessor


@pytest.mark.parametrize("nominal", [5.0, 8.0, 10.0, 15.0])
def test_nominal_profile_prepares_the_outer_asset_at_production_max(nominal):
    profile = ProcessingProfile(nominal_size_cm=nominal)
    expected_cm = production_max_for_nominal(nominal)

    assert profile.resolved_asset_target_size_cm == pytest.approx(expected_cm)
    assert profile.master_pixels == round(expected_cm / 2.54 * 300)


def test_legacy_profile_preserves_the_historical_master_and_policy_values():
    profile = ProcessingProfile()

    assert profile.nominal_size_cm is None
    assert profile.resolved_asset_target_size_cm == pytest.approx(5.70)
    assert profile.resolved_content_size_cm == pytest.approx(5.30)
    assert profile.master_pixels == round(5.70 / 2.54 * 300)
    assert (profile.final_white_px, profile.control_black_px, profile.transparent_padding_px) == (30, 2, 50)


def test_nominal_profile_retains_the_legacy_content_ratio_for_rectangles():
    profile = ProcessingProfile(nominal_size_cm=8)
    assert profile.resolved_content_size_cm / profile.resolved_asset_target_size_cm == pytest.approx(5.30 / 5.70)


def test_transparent_padding_is_outside_the_sticker_alpha_bounds():
    source = Image.new("RGBA", (24, 12), (0, 0, 0, 0))
    ImageDraw.Draw(source).rectangle((4, 3, 19, 8), fill=(20, 90, 200, 255))

    padded = StickerProcessor._add_transparent_padding(source, padding_px=50)
    assert padded.size == (124, 112)
    assert padded.getchannel("A").getbbox() == (54, 53, 70, 59)


def test_creator_resolution_does_not_become_plancha_physical_size():
    nominal = 8.0
    profile = ProcessingProfile(nominal_size_cm=nominal)
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "rectangular.png"
        Image.new("RGBA", (1200, 600), (20, 90, 200, 255)).save(source)
        project = PlanchaProject.from_images([{
            "path": str(source),
            "quantity": 1,
            "size_cm": nominal,
            "order_size_cm": nominal,
            "order_id": 77,
        }])
    item = project.items[0]

    assert max(item.production_width_cm, item.production_height_cm) == pytest.approx(
        production_min_for_nominal(nominal))
    assert max(item.production_width_cm, item.production_height_cm) < profile.resolved_asset_target_size_cm
    assert item.production_width_cm / item.production_height_cm == pytest.approx(2.0)


def test_resolution_change_preserves_normalized_mask_topology():
    """La escala cambia, pero no Case A/B, contornos ni la silueta lógica."""
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "estrella.png"
        image = Image.new("RGBA", (440, 440), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.polygon([(220, 20), (267, 154), (410, 158), (295, 240),
                      (338, 390), (220, 304), (102, 390), (145, 240),
                      (30, 158), (173, 154)], fill=(220, 45, 60, 255))
        image.save(source)

        masks = []
        cases = []
        for nominal in (5.0, 10.0):
            result = StickerProcessor(
                Path(folder) / f"work-{nominal}",
                ProcessingProfile(nominal_size_cm=nominal),
            ).process(source)
            # La máscara se compara antes del borde raster fijo: la forma
            # lógica no debe depender de la resolución de exportación.
            with Image.open(result.artifacts["mask"]) as master:
                alpha = master.convert("L")
                bbox = alpha.getbbox()
                masks.append(alpha.crop(bbox).resize((256, 256), Image.Resampling.NEAREST))
            cases.append(result.analysis["case"])

    first, second = (mask.point(lambda value: 1 if value > 127 else 0) for mask in masks)
    pairs = zip(first.get_flattened_data(), second.get_flattened_data())
    intersection = sum(a and b for a, b in pairs)
    union = sum(a or b for a, b in zip(first.get_flattened_data(), second.get_flattened_data()))
    assert cases[0] == cases[1]
    assert intersection / union > 0.995
