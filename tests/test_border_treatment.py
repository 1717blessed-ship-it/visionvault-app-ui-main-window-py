from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.stickers.models import BorderTreatment, ProcessingProfile
from app.stickers.pipeline import StickerProcessor


def _bordered_art(size=(160, 160)):
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((22, 22, 138, 138), fill="white")
    draw.ellipse((34, 34, 126, 126), fill=(220, 30, 80, 255))
    return image


def test_replace_removes_only_exterior_connected_white_band():
    image = _bordered_art()
    clean, meta = StickerProcessor._remove_existing_white_border_for_replacement(
        image, image.getchannel("A"), max_depth_px=20)
    assert meta["applied"] is True
    before = np.asarray(image.getchannel("A")) > 12
    after = np.asarray(clean) > 12
    assert after.sum() < before.sum()
    assert after[80, 80]
    assert not after[25, 80]


def test_replace_fails_safe_when_no_white_border_is_isolated():
    image = Image.new("RGBA", (80, 80), (200, 20, 40, 255))
    clean, meta = StickerProcessor._remove_existing_white_border_for_replacement(
        image, image.getchannel("A"))
    assert meta["requires_review"] is True
    assert clean.tobytes() == image.getchannel("A").tobytes()


def test_unknown_border_treatment_is_rejected_before_processing(tmp_path):
    source = tmp_path / "source.png"
    _bordered_art().save(source)
    processor = StickerProcessor(tmp_path / "work", ProcessingProfile())
    with pytest.raises(ValueError, match="Tratamiento de borde desconocido"):
        processor.process(source, border_treatment="inventado", automatic_recovery=False)


@pytest.mark.parametrize("treatment", [item.value for item in BorderTreatment])
def test_declared_treatments_persist_in_metadata(tmp_path, treatment):
    source = tmp_path / f"source-{treatment}.png"
    _bordered_art().save(source)
    processor = StickerProcessor(tmp_path / treatment, ProcessingProfile())
    result = processor.process(source, border_treatment=treatment, automatic_recovery=False)
    assert result.analysis["border_treatment"]["requested"] == treatment
    import json
    metadata = json.loads(Path(result.artifacts["metadata"]).read_text(encoding="utf-8"))
    assert metadata["reprocess_parameters"]["border_treatment"] == treatment


@pytest.mark.parametrize("filename", ["original.png", "visual_support_600_OPAQUE.png"])
@pytest.mark.parametrize("treatment", [BorderTreatment.REPLACE.value, BorderTreatment.ADD.value])
def test_real_ambiguous_disc_never_stacks_or_destructively_replaces_border(
        tmp_path, filename, treatment):
    source = Path("artifacts/sticker-disc-human-review") / filename
    assert source.is_file(), f"Falta el original real: {source}"
    processor = StickerProcessor(tmp_path / f"{filename}-{treatment}", ProcessingProfile())
    result = processor.process(source, border_treatment=treatment,
                               automatic_recovery=False)
    decision = result.analysis["border_treatment"]
    assert decision["requires_review"] is True
    assert decision["effective"] == BorderTreatment.PRESERVE_CLEAN.value
    assert result.analysis["native_resolution"]["border_px"] == 0
    with Image.open(result.artifacts["master"]) as final:
        assert final.mode == "RGBA"
        assert final.getchannel("A").getextrema() == (0, 255)


def test_real_disc_processing_is_deterministic_for_classic_and_v2_defaults(tmp_path):
    source = Path("artifacts/sticker-disc-human-review/original.png")
    classic = StickerProcessor(tmp_path / "classic", ProcessingProfile()).process(
        source, automatic_recovery=False)
    v2 = StickerProcessor(tmp_path / "v2", ProcessingProfile()).process(
        source, border_treatment=None, automatic_recovery=False)
    with Image.open(classic.artifacts["master"]) as first, Image.open(v2.artifacts["master"]) as second:
        assert first.convert("RGBA").tobytes() == second.convert("RGBA").tobytes()
    assert classic.analysis["case"] == v2.analysis["case"]
    assert classic.profile == v2.profile
