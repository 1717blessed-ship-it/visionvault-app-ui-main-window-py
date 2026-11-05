import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from app.stickers.mask_contraction import expand_alpha_signed_distance
from app.stickers.mask_editing import (
    MaskEditDocument, MaskStroke, compare_masks, save_approved_reference,
)
from app.stickers.models import ProcessingProfile
from app.stickers.pipeline import StickerProcessor


def base_mask(size=(100, 100)):
    image = Image.new("L", size, 0)
    ImageDraw.Draw(image).rectangle((25, 25, 74, 74), fill=255)
    return image


def test_restore_and_erase_are_non_destructive_and_use_image_coordinates():
    base = base_mask()
    before = base.tobytes()
    document = MaskEditDocument.for_base(base)
    document.add(MaskStroke("restore", ((10, 10),), 12, 1, 1))
    document.add(MaskStroke("erase", ((50, 50),), 12, 1, 1))
    edited, _ = document.render_manual(base)
    assert edited.getpixel((10, 10)) > 240
    assert edited.getpixel((50, 50)) < 15
    assert base.tobytes() == before


def test_hardness_and_opacity_preserve_partial_alpha():
    base = Image.new("L", (80, 80), 0)
    document = MaskEditDocument.for_base(base)
    document.add(MaskStroke("restore", ((40, 40),), 30, .2, .45))
    edited, _ = document.render_manual(base)
    values = np.asarray(edited)
    assert 45 < values[40, 40] < 180
    assert np.any((values > 0) & (values < values[40, 40]))


def test_protection_preserves_alpha_during_contraction():
    base = base_mask()
    document = MaskEditDocument.for_base(base)
    document.add(MaskStroke("protect", ((25, 50),), 12, 1, 1))
    adjusted, protection, _ = document.render(base, .5, 254, .08)
    assert protection.getpixel((25, 50)) > 240
    assert adjusted.getpixel((25, 50)) > 240


def test_expand_is_inverse_direction_without_resizing_canvas():
    base = base_mask()
    expanded, report = expand_alpha_signed_distance(base, .5, 254, .08)
    assert expanded.size == base.size
    assert report.area_after_px > report.area_before_px
    assert expanded.getpixel((22, 50)) > 0


def test_undo_redo_and_new_operation_clear_redo():
    base = base_mask()
    document = MaskEditDocument.for_base(base)
    a = MaskStroke("erase", ((30, 30),), 4)
    b = MaskStroke("restore", ((5, 5),), 4)
    document.add(a)
    assert document.undo()
    assert document.redo()
    assert document.undo()
    document.add(b)
    assert not document.redo()


def test_document_roundtrip_and_rejects_different_base(tmp_path):
    base = base_mask()
    document = MaskEditDocument.for_base(base)
    document.add(MaskStroke("refine", ((25, 25), (30, 30)), 8, .7, .8))
    path = document.save(tmp_path / "edits.json")
    loaded = MaskEditDocument.load(path)
    assert loaded == document
    assert loaded.compatible(base)
    assert not loaded.compatible(Image.new("L", base.size, 0))


def test_stickers_keep_independent_edit_documents():
    base = base_mask()
    first, second = MaskEditDocument.for_base(base), MaskEditDocument.for_base(base)
    first.add(MaskStroke("erase", ((50, 50),), 20))
    assert len(first.operations) == 1
    assert len(second.operations) == 0


def test_approval_is_explicit_and_records_source_hash(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGBA", (100, 100), "red").save(source)
    target = tmp_path / "approved.png"
    manifest = save_approved_reference(base_mask(), source, target)
    persisted = json.loads(target.with_suffix(".approval.json").read_text(encoding="utf-8"))
    assert manifest["approved"] is True
    assert persisted["approved_by"] == "usuario"
    assert persisted["dimensions"] == [100, 100]


def test_repeated_render_never_accumulates_operations():
    base = base_mask()
    document = MaskEditDocument.for_base(base)
    document.add(MaskStroke("erase", ((50, 50),), 10, .8, .5))
    first = document.render(base, .2, 254, .08)[0]
    second = document.render(base, .2, 254, .08)[0]
    assert first.tobytes() == second.tobytes()


def test_pipeline_expansion_and_protection_are_shared_and_persisted(tmp_path):
    source = tmp_path / "source.png"
    mask_path = tmp_path / "manual.png"
    protection_path = tmp_path / "protected.png"
    Image.new("RGBA", (120, 120), (230, 40, 90, 255)).save(source)
    mask = Image.new("L", (120, 120), 0)
    ImageDraw.Draw(mask).ellipse((30, 30, 89, 89), fill=255)
    mask.save(mask_path)
    protection = Image.new("L", mask.size, 0)
    ImageDraw.Draw(protection).ellipse((27, 53, 38, 66), fill=255)
    protection.save(protection_path)
    processor = StickerProcessor(tmp_path / "work", ProcessingProfile())
    result = processor.process(
        source, mask_override=mask_path, selection_expansion_mm=.2,
        selection_protection_mask=protection_path, automatic_recovery=False)
    parameters = json.loads(
        (Path(result.output_dir) / "metadata.json").read_text(encoding="utf-8")
    )["reprocess_parameters"]
    assert parameters["selection_expansion_mm"] == .2
    assert parameters["selection_protection_mask"] == str(protection_path)
    assert "selection_protection" in result.artifacts
    with Image.open(result.artifacts["selection_alpha_contracted"]) as adjusted:
        assert adjusted.size == mask.size
        assert np.asarray(adjusted, dtype=np.uint64).sum() > np.asarray(mask, dtype=np.uint64).sum()


def test_approved_reference_comparison_reports_local_and_global_differences(tmp_path):
    automatic = base_mask()
    reference = automatic.copy()
    ImageDraw.Draw(reference).ellipse((5, 5, 10, 10), fill=255)
    metrics = compare_masks(automatic, reference, tmp_path / "comparison.png")
    assert 0 < metrics["iou"] < 1
    assert metrics["restored_detail_pixels"] > 0
    assert metrics["boundary_different_pixels"] > 0
    assert Path(metrics["visual_comparison"]).is_file()
