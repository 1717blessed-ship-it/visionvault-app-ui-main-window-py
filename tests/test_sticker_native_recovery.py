import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.stickers.pipeline import StickerProcessor, ProcessingResult, ProcessingCancelled
from app.stickers.models import ProcessingProfile
from app.stickers.recovery import recovery_allowed, compare_recovery


def source_image(path, size=(220, 180)):
    image = Image.new("RGBA", size)
    ImageDraw.Draw(image).rectangle((20, 20, size[0] - 21, size[1] - 21), fill=(35, 120, 200, 255))
    image.save(path)
    return image


def test_native_processing_keeps_original_coordinates_and_physical_border(tmp_path):
    source = tmp_path / "large.png"
    image = source_image(source, (1800, 960))
    processor = StickerProcessor(tmp_path / "work")
    result = processor.process(source, automatic_recovery=False)
    assert result.analysis["processing_pixels"] == list(image.size)
    assert result.analysis["processing_downscaled"] is False
    with Image.open(result.artifacts["mask_editable"]) as mask:
        assert mask.size == image.size
    with Image.open(result.artifacts["clean"]) as clean:
        assert max(clean.size) > 1536
    native = result.analysis["native_resolution"]
    with Image.open(result.artifacts["native_master"]) as asset, Image.open(result.artifacts["native_cut"]) as cut:
        assert asset.size == cut.size == tuple(native["pixels"])
        assert asset.width > processor.profile.master_pixels
        assert asset.width / asset.info["dpi"][0] * 2.54 == pytest.approx(5.7, abs=.002)
        assert native["border_px"] * 25.4 / native["dpi"] == pytest.approx(30 * 25.4 / 300, abs=25.4/native["dpi"])
        assert cut.getbbox() is not None
        with Image.open(result.artifacts["native_printable_base"]) as base, Image.open(result.artifacts["clean"]) as clean:
            base_box = base.getbbox()
            design_left = native["design_offset"][0] + clean.getchannel("A").getbbox()[0]
            assert design_left - base_box[0] == pytest.approx(native["border_px"], abs=2)
            assert cut.getbbox()[0] - base_box[0] == pytest.approx(native["cut_inset_px"], abs=2)
    with Image.open(result.artifacts["thumbnail"]) as thumbnail:
        assert max(thumbnail.size) <= 256
    restored = ProcessingResult.from_metadata(result.artifacts["metadata"])
    assert restored.analysis["native_resolution"] == native
    assert restored.artifacts["native_master"] == result.artifacts["native_master"]


def test_low_resolution_does_not_create_native_detail(tmp_path):
    source = tmp_path / "small.png"
    source_image(source, (100, 80))
    result = StickerProcessor(tmp_path / "work", ProcessingProfile(nominal_size_cm=10)).process(source)
    assert result.analysis["native_resolution"]["source_to_native_scale"] == 1
    assert result.analysis["native_resolution"]["pixels"][0] < result.profile["master_size_cm"] * 300
    assert any(issue["code"] == "low_resolution" for issue in result.analysis["quality_report"]["warnings"])
    assert result.analysis["effective_content_dpi"] < 300
    assert "automatic_recovery" not in result.analysis


def test_manual_mask_scaling_preserves_semitransparency_and_reprocessing(tmp_path):
    source = tmp_path / "source.png"
    source_image(source, (400, 320))
    mask = Image.new("L", (200, 160))
    ImageDraw.Draw(mask).rectangle((30, 30, 170, 130), fill=120)
    mask_path = tmp_path / "manual.png"
    mask.save(mask_path)
    original_mask_bytes = mask_path.read_bytes()
    processor = StickerProcessor(tmp_path / "work")
    first = processor.process(source, mask_override=mask_path)
    second = processor.process(source, mask_override=mask_path)
    with Image.open(first.artifacts["mask_editable"]) as a, Image.open(second.artifacts["mask_editable"]) as b:
        assert a.size == (400, 320)
        assert a.getpixel((200, 160)) == 120
        assert a.tobytes() == b.tobytes()
    assert first.job_id != second.job_id
    assert "automatic_recovery" not in first.analysis
    assert mask_path.read_bytes() == original_mask_bytes


def test_cancellation_during_native_output_removes_current_run(tmp_path):
    source = tmp_path / "source.png"
    source_image(source)
    processor = StickerProcessor(tmp_path / "work")
    first = processor.process(source, automatic_recovery=False)
    original_master = Path(first.artifacts["master"]).read_bytes()
    def progress(_percent, message):
        if message == "Salida nativa guardada":
            raise ProcessingCancelled()
    with pytest.raises(ProcessingCancelled):
        processor.process(source, progress=progress)
    assert [item.name for item in processor.workspace.iterdir()] == [first.job_id]
    assert Path(first.artifacts["master"]).read_bytes() == original_master


def test_legacy_metadata_remains_readable(tmp_path):
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps({"job_id": "legacy", "source_path": "original.png", "artifacts": {}, "profile": {}}))
    result = ProcessingResult.from_metadata(path)
    assert result.job_id == "legacy"
    assert result.analysis == {}
    assert result.status == "Procesado"


def test_native_asset_and_metadata_survive_database_reopen_and_plancha(tmp_path):
    from app.database.database import ImageDatabase
    from app.planchas.model import PlanchaProject
    from app.planchas.production_geometry import production_min_for_nominal
    source = tmp_path / "source.png"
    source_image(source)
    result = StickerProcessor(tmp_path / "work", ProcessingProfile(nominal_size_cm=8)).process(source)
    path = tmp_path / "catalog.db"
    database = ImageDatabase(path)
    database.save_sticker_processing(result)
    published = database.approve_processed_sticker(result)
    database.connection.close()
    reopened = ImageDatabase(path)
    row = next(item for item in reopened.sticker_processing_jobs() if item["id"] == result.job_id)
    assert row["status"] == "Confirmado"
    artifacts = json.loads(row["artifacts"])
    assert artifacts["master"] == published["path"]
    assert Path(artifacts["master"]).exists()
    assert artifacts["native_master"] == result.artifacts["native_master"]
    restored = ProcessingResult.from_metadata(artifacts["metadata"])
    assert restored.status == "Confirmado"
    assert restored.artifacts["master"] == published["path"]
    assert json.loads(row["analysis"])["native_resolution"] == result.analysis["native_resolution"]
    project = PlanchaProject.from_images([{"path": artifacts["native_master"], "quantity": 1,
                                          "size_cm": 8., "order_size_cm": 8., "order_id": 77}])
    item = project.items[0]
    assert max(item.production_width_cm, item.production_height_cm) == pytest.approx(production_min_for_nominal(8.))
    reopened.connection.close()


def test_cancelled_alternative_leaves_no_partial_history(tmp_path):
    processor = StickerProcessor(tmp_path / "work")
    calls = []
    def process(_source, **options):
        result = fake_result(processor.workspace, options["_run_id"])
        calls.append(result)
        if len(calls) == 2:
            raise ProcessingCancelled()
        return result
    with patch.object(processor, "_process_impl", side_effect=process):
        with pytest.raises(ProcessingCancelled):
            processor.process("source.png")
    assert len(calls) == 2
    assert list(processor.workspace.iterdir()) == []


def test_order_publication_keeps_native_assets_and_privacy(tmp_path):
    from app.database.database import ImageDatabase
    source = tmp_path / "source.png"
    source_image(source)
    result = StickerProcessor(tmp_path / "work").process(source)
    database = ImageDatabase(tmp_path / "orders.db")
    order_id = database.create_order("Nativo", jobs=[{"title": "Sticker", "subtotal": 100}])
    database.save_sticker_processing(result)
    published = database.approve_processed_sticker_for_order(result, order_id)
    row = next(item for item in database.sticker_processing_jobs() if item["id"] == result.job_id)
    artifacts = json.loads(row["artifacts"])
    assert Path(artifacts["native_cut"]).exists()
    assert artifacts["master"] == published["path"]
    flags = database.connection.execute("SELECT is_private, is_reusable FROM images WHERE path = ?",
                                        (published["path"],)).fetchone()
    assert tuple(flags) == (1, 0)
    database.connection.close()


def fake_result(directory, name, warnings=1, shift=0):
    output = directory / name
    output.mkdir()
    mask = Image.new("L", (100, 100))
    ImageDraw.Draw(mask).rectangle((10+shift, 10, 89, 89), fill=255)
    mask_path = output / "mask.png"
    mask.save(mask_path)
    metadata = output / "metadata.json"
    metadata.write_text(json.dumps({"job_id": name, "source_path": "source.png", "analysis": {}}))
    return ProcessingResult(name, "source.png", str(output), "Procesado", "Revisar", [],
        {"quality_report": {"errors": [], "warnings": [{"code": "small_components"}] * warnings}},
        {"mask_editable": str(mask_path), "mask_segmentation_raw": str(mask_path), "metadata": str(metadata)}, {})


def test_automatic_recovery_is_bounded_and_keeps_both_results(tmp_path):
    processor = StickerProcessor(tmp_path / "work")
    produced = []
    def process(_source, **options):
        result = fake_result(processor.workspace, options["_run_id"], warnings=1 if not produced else 0)
        produced.append(result)
        return result
    with patch.object(processor, "_process_impl", side_effect=process) as impl:
        result = processor.process("source.png")
    assert impl.call_count == 2
    assert result.job_id == produced[1].job_id
    assert result.analysis["automatic_recovery"]["attempts"] == 1
    assert all(Path(item.artifacts["metadata"]).exists() for item in produced)
    restored = ProcessingResult.from_metadata(result.artifacts["metadata"])
    assert restored.analysis["automatic_recovery"]["selected_job_id"] == result.job_id


@pytest.mark.parametrize("options", [{"mask_override": "manual.png"}, {"cut_mask_override": "cut.png"},
                                      {"approved_result": True}, {"preserve_full_image": True},
                                      {"selected_component_ids": [1]}])
def test_recovery_never_changes_manual_or_approved_intent(tmp_path, options):
    result = fake_result(tmp_path, "protected")
    assert not recovery_allowed(result, options)


def test_different_silhouette_requires_comparison(tmp_path):
    primary = fake_result(tmp_path, "first", warnings=2)
    alternative = fake_result(tmp_path, "second", warnings=0, shift=30)
    assert not compare_recovery(primary, alternative)["select_alternative"]
