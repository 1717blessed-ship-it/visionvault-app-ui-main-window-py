from pathlib import Path
import hashlib

from PIL import Image

from app.stickers.editor_v2.adapter import PipelineViewAdapter
from app.stickers.editor_v2.state import CanvasState, StudioSessionState
from app.stickers.editor_v2.canvas import StickerCanvas
from app.stickers.editor_v2.review import (
    invalidate_review, mark_reviewed, mark_sent, record_export, review_is_current,
)


class _Result:
    def __init__(self, artifacts, quality_status="Revisar"):
        self.artifacts = artifacts
        self.quality_status = quality_status


def test_canvas_state_clamps_zoom_and_preserves_flags():
    state = CanvasState(show_cut=True, compare=True)
    assert state.set_zoom(0) == 0.05
    assert state.set_zoom(99) == 16.0
    assert state.show_cut is True
    assert state.compare is True


def test_session_keeps_independent_view_per_job(tmp_path):
    first = {"source_path": str(tmp_path / "a.png")}
    second = {"source_path": str(tmp_path / "b.png")}
    session = StudioSessionState()
    session.select(first).set_zoom(2.5)
    session.select(second).set_zoom(0.75)
    assert session.select(first).zoom == 2.5
    assert session.select(second).zoom == 0.75


def test_adapter_selects_existing_artifacts_without_mutating_job(tmp_path):
    original = tmp_path / "original.png"
    mask = tmp_path / "mask.png"
    master = tmp_path / "master.png"
    Image.new("RGB", (30, 20), "red").save(original, dpi=(300, 300))
    Image.new("L", (30, 20), 255).save(mask)
    Image.new("RGBA", (30, 20), (255, 0, 0, 255)).save(master, dpi=(300, 300))
    job = {"source_path": str(original), "result": _Result({"mask": str(mask), "master": str(master)})}
    before = dict(job)

    assert PipelineViewAdapter.preview_source(job, "Original").path == str(original)
    assert PipelineViewAdapter.preview_source(job, "Máscara").path == str(mask)
    assert PipelineViewAdapter.preview_source(job, "Final").path == str(master)
    assert job == before


def test_adapter_reports_real_pixels_and_physical_size(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGBA", (300, 150), (0, 0, 0, 0)).save(source, dpi=(300, 300))
    metrics = PipelineViewAdapter.metrics({"source_path": str(source)})
    assert metrics["pixels"] == (300, 150)
    assert abs(metrics["millimeters"][0] - 25.4) < 0.1
    assert abs(metrics["millimeters"][1] - 12.7) < 0.1


def test_discard_missing_view_states(tmp_path):
    first = {"source_path": str(tmp_path / "a.png")}
    second = {"source_path": str(tmp_path / "b.png")}
    session = StudioSessionState()
    session.select(first)
    session.select(second)
    session.discard_missing([second])
    assert len(session.views) == 1
    assert session.selected_key in session.views


def test_final_preview_and_export_are_the_exact_pipeline_master(tmp_path):
    master = tmp_path / "master.png"
    exported = tmp_path / "exported.png"
    Image.new("RGBA", (37, 29), (20, 30, 40, 137)).save(master, dpi=(217, 217))
    job = {"source_path": str(master), "result": _Result({"master": str(master)})}
    assert PipelineViewAdapter.preview_source(job, "Final").path == str(master)
    PipelineViewAdapter.export_final(master, exported)
    digest = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
    assert digest(exported) == digest(master)


def test_preview_modes_map_to_real_pipeline_artifacts(tmp_path):
    paths = {}
    for name, mode in (("original", "RGBA"), ("mask", "L"),
                       ("design", "RGBA"), ("master", "RGBA")):
        path = tmp_path / f"{name}.png"
        Image.new(mode, (12, 9), 255 if mode == "L" else (1, 2, 3, 4)).save(path)
        paths[name] = str(path)
    job = {"source_path": paths["original"], "result": _Result({
        "mask": paths["mask"], "design_layer": paths["design"],
        "master": paths["master"]})}
    assert PipelineViewAdapter.preview_source(job, "Original").path == paths["original"]
    assert PipelineViewAdapter.preview_source(job, "Máscara").path == paths["mask"]
    assert PipelineViewAdapter.preview_source(job, "Resultado").path == paths["design"]
    assert PipelineViewAdapter.preview_source(job, "Final").path == paths["master"]


def test_review_allows_export_without_publication_and_tracks_it(tmp_path):
    master = tmp_path / "master.png"
    exported = tmp_path / "exported.png"
    Image.new("RGBA", (32, 24), (20, 30, 40, 180)).save(master)
    job = {"source_path": str(master), "status": "Procesado",
           "result": _Result({"master": str(master)})}

    mark_reviewed(job)
    assert review_is_current(job)
    PipelineViewAdapter.export_final(master, exported)
    record_export(job, exported)

    assert job["status"] == "Procesado"
    assert job.get("sent_to_processed") is None
    assert job["export_count"] == 1
    assert exported.read_bytes() == master.read_bytes()


def test_master_change_invalidates_review_and_requires_a_new_one(tmp_path):
    master = tmp_path / "master.png"
    Image.new("RGBA", (20, 20), "red").save(master)
    job = {"source_path": str(master), "result": _Result({"master": str(master)})}
    mark_reviewed(job)
    assert review_is_current(job)

    Image.new("RGBA", (20, 20), "blue").save(master)
    assert not review_is_current(job)
    invalidate_review(job, "mask_edited")
    assert job["review_state"] == "Revisión requerida"


def test_sending_is_independent_from_review_and_export(tmp_path):
    master = tmp_path / "master.png"
    Image.new("RGBA", (12, 12), "green").save(master)
    job = {"source_path": str(master), "result": _Result({"master": str(master)})}
    mark_reviewed(job)
    mark_sent(job)
    assert review_is_current(job)
    assert job["sent_to_processed"] is True


def test_editing_after_send_requires_review_and_send_again(tmp_path):
    master = tmp_path / "master.png"
    Image.new("RGBA", (12, 12), "green").save(master)
    job = {"source_path": str(master), "result": _Result({"master": str(master)})}
    mark_reviewed(job)
    mark_sent(job)

    invalidate_review(job, "parameters_changed")

    assert not review_is_current(job)
    assert job["sent_to_processed"] is False
    assert "sent_to_processed_at" not in job


def test_export_counter_survives_bounded_history(tmp_path):
    master = tmp_path / "master.png"
    Image.new("RGBA", (12, 12), "green").save(master)
    job = {"source_path": str(master), "result": _Result({"master": str(master)}),
           "export_count": 50, "exports": [{"path": str(master)}] * 50}
    record_export(job, tmp_path / "copy.png")
    assert len(job["exports"]) == 50
    assert job["export_count"] == 51


def test_preview_border_policy_never_duplicates_a_preserved_border():
    preserve = {"border_treatment": "Conservar y limpiar"}
    replace = {"border_treatment": "Reemplazar"}
    automatic = {"result": type("R", (), {"analysis": {
        "border_treatment": {"effective": "Conservar y limpiar"}}})()}
    assert not StickerCanvas.preview_adds_border(preserve)
    assert StickerCanvas.preview_adds_border(replace)
    assert not StickerCanvas.preview_adds_border(automatic)
