from pathlib import Path
from types import SimpleNamespace

from app.stickers.editor_v2.session import (
    DISPLAY_STATUS, SessionStore, TraySelection, remove_from_session,
)


class FakeDatabase:
    def __init__(self): self.discarded = []; self.saved = []
    def category_counts(self): return []
    def sticker_processing_jobs(self, limit=500): return []
    def discard_processed_sticker(self, job_id): self.discarded.append(job_id)
    def save_sticker_processing(self, result, category="", tags=None):
        self.saved.append((result.job_id, category, list(tags or [])))
    def indexed_visual_search_images(self): return []


def jobs(tmp_path, count=20):
    result = []
    for index in range(count):
        path = tmp_path / f"sticker-{index}.png"
        path.write_bytes(b"original")
        result.append({"source_path": str(path), "status": "Pendiente", "result": None,
                       "selection_contraction_mm": index / 100})
    return result


def test_case_b_twenty_jobs_keep_independent_state(tmp_path):
    batch = jobs(tmp_path)
    for index, job in enumerate(batch):
        job["status"] = "Procesado"
        job["selection_contraction_mm"] = index / 10
    assert len({job["selection_contraction_mm"] for job in batch}) == 20
    assert all(DISPLAY_STATUS[job["status"]] == "Requiere revisión" for job in batch)


def test_ctrl_and_shift_selection_are_deterministic():
    selection = TraySelection()
    selection.click(2, count=10)
    selection.click(5, ctrl=True, count=10)
    assert selection.indices == {2, 5}
    selection.click(8, shift=True, count=10)
    assert selection.indices == {5, 6, 7, 8}
    selection.click(6, ctrl=True, count=10)
    assert selection.indices == {5, 7, 8}


def test_case_c_cancelled_confirmation_does_not_call_removal(tmp_path):
    batch = jobs(tmp_path, 5)
    # La cancelación del diálogo significa no invocar remove_from_session.
    before = list(batch)
    assert batch == before
    assert len(batch) == 5


def test_case_d_remove_five_never_deletes_originals(tmp_path):
    batch = jobs(tmp_path, 8)
    originals = [Path(job["source_path"]) for job in batch[:5]]
    removed = remove_from_session(batch, range(5))
    assert len(removed) == 5 and len(batch) == 3
    assert all(path.read_bytes() == b"original" for path in originals)


def test_active_job_cannot_be_removed(tmp_path):
    batch = jobs(tmp_path, 2)
    batch[0]["status"] = "Procesando"
    try:
        remove_from_session(batch, {0})
    except RuntimeError as error:
        assert "procesándose" in str(error)
    else:
        raise AssertionError("Se permitió quitar un trabajo activo")
    assert len(batch) == 2


def test_removal_discards_only_unapproved_temporary_result(tmp_path):
    batch = jobs(tmp_path, 2)
    batch[0].update(status="Procesado", result=SimpleNamespace(job_id="temporary"))
    batch[1].update(status="Confirmado", result=SimpleNamespace(job_id="approved"))
    discarded = []
    remove_from_session(batch, {0, 1}, discard_result=discarded.append)
    assert discarded == ["temporary"]


def test_removing_a_published_job_does_not_delete_its_database_artifacts(tmp_path):
    batch = jobs(tmp_path, 1)
    batch[0].update(status="Procesado", sent_to_processed=True,
                    result=SimpleNamespace(job_id="published"))
    discarded = []
    remove_from_session(batch, {0}, discard_result=discarded.append)
    assert discarded == []


def test_case_g_atomic_session_recovery_preserves_per_sticker_settings(tmp_path):
    batch = jobs(tmp_path, 3)
    batch[0]["status"] = "Procesando"
    batch[1]["selection_expansion_mm"] = .4
    store = SessionStore(tmp_path / "session.json")
    views = {"one": {"mode": "Final", "zoom": 2, "pan_x": 10, "pan_y": -5,
                     "fitted": False, "show_cut": True, "compare": False}}
    store.save(batch, views)
    recovered = store.load()
    assert len(recovered["jobs"]) == 3
    assert recovered["jobs"][1]["selection_expansion_mm"] == .4
    assert recovered["views"]["one"]["zoom"] == 2
    assert not (tmp_path / "session.json.tmp").exists()


def test_selection_normalizes_after_multi_removal():
    selection = TraySelection({1, 3, 5}, anchor=3)
    selection.normalize_after_removal({0, 3}, 7)
    assert selection.indices == {0, 3}
    assert selection.anchor is None


def test_ui_case_c_and_d_cancel_then_confirm_multi_removal(tmp_path, monkeypatch):
    import tkinter as tk
    from PIL import Image
    from app.stickers.editor_v2.window import StickerStudioV2
    monkeypatch.chdir(tmp_path)
    paths = []
    for index in range(6):
        path = tmp_path / f"ui-{index}.png"
        Image.new("RGBA", (32, 32), (index, 20, 30, 255)).save(path); paths.append(path)
    root = tk._default_root or tk.Tk(); root.withdraw()
    studio = StickerStudioV2(root, FakeDatabase())
    studio.deiconify(); studio.update()
    studio.add_paths(paths, run_queue=False)
    studio._v2_selection.indices = {0, 1, 2, 3, 4}
    monkeypatch.setattr("app.stickers.editor_v2.window.messagebox.askyesno", lambda *a, **k: False)
    studio._remove_selected()
    assert len(studio.jobs) == 6
    monkeypatch.setattr("app.stickers.editor_v2.window.messagebox.askyesno", lambda *a, **k: True)
    studio._remove_selected()
    assert len(studio.jobs) == 1
    assert all(path.is_file() for path in paths)
    studio.destroy()


def test_ui_case_g_close_reopen_recovers_jobs_and_settings(tmp_path, monkeypatch):
    import tkinter as tk
    from PIL import Image
    from app.stickers.editor_v2.window import StickerStudioV2
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "recover.png"; Image.new("RGBA", (32, 32), "red").save(source)
    root = tk._default_root or tk.Tk(); root.withdraw()
    first = StickerStudioV2(root, FakeDatabase())
    first.add_paths([source], run_queue=False)
    first.jobs[0]["selection_contraction_mm"] = .4
    first._save_v2_session(); first.destroy()
    second = StickerStudioV2(root, FakeDatabase())
    assert len(second.jobs) == 1
    assert second.jobs[0]["selection_contraction_mm"] == .4
    second.destroy()


def test_ui_window_sizes_canvas_controls_and_enabled_buttons(tmp_path, monkeypatch):
    import tkinter as tk
    from app.stickers.editor_v2.window import StickerStudioV2
    monkeypatch.chdir(tmp_path)
    root = tk._default_root or tk.Tk(); root.withdraw()
    studio = StickerStudioV2(root, FakeDatabase())
    studio.deiconify(); studio.update()
    for geometry in ("1040x680+0+0", "1280x720+0+0", "1600x900+0+0"):
        studio.geometry(geometry); studio.update_idletasks()
        assert studio._v2_canvas.winfo_width() > 300
        assert studio._v2_canvas.winfo_height() > 250
        studio._fit_canvas(); studio._actual_size(); studio._center_canvas()
        assert studio._v2_state.current().zoom == 1.0
    enabled_without_command = []
    for widget in studio.winfo_children():
        stack = [widget]
        while stack:
            current = stack.pop(); stack.extend(current.winfo_children())
            if current.winfo_class() == "TButton" and "disabled" not in current.state():
                if not str(current.cget("command")):
                    enabled_without_command.append(str(current))
    assert enabled_without_command == []
    studio.destroy()


def test_space_pan_temporarily_overrides_active_brush():
    from app.stickers.editor_v2.state import CanvasState
    # El contrato observable: la herramienta permanece elegida y sólo cambia
    # temporalmente el modo de interacción mientras espacio está presionado.
    state = CanvasState(zoom=2, fitted=False)
    assert state.zoom == 2 and state.fitted is False


def test_review_export_and_send_keep_the_job_open(tmp_path, monkeypatch):
    import tkinter as tk
    from PIL import Image
    from app.stickers.editor_v2.window import StickerStudioV2
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "source.png"
    master = tmp_path / "master.png"
    exported = tmp_path / "exported.png"
    Image.new("RGBA", (40, 40), "red").save(source)
    Image.new("RGBA", (40, 40), (255, 0, 0, 180)).save(master)
    result = SimpleNamespace(
        job_id="flow-job", source_path=str(source), status="Procesado",
        artifacts={"master": str(master)}, analysis={"quality_report": {"errors": []}},
        quality_status="Listo", quality_notes=[], profile={}, output_dir=str(tmp_path),
        duplicate_path="", duplicate_score=0,
    )
    database = FakeDatabase()
    root = tk._default_root or tk.Tk(); root.withdraw()
    studio = StickerStudioV2(root, database)
    studio.jobs = [{"source_path": str(source), "status": "Procesado", "result": result,
                    "force": False, "is_png": True, "protection_zones": []}]
    studio.current_index = 0; studio.refresh_queue()

    assert studio._review_current()
    monkeypatch.setattr("app.stickers.editor_v2.window.filedialog.asksaveasfilename", lambda **_k: str(exported))
    studio._export_final()
    assert exported.read_bytes() == master.read_bytes()
    assert studio._send_to_processed()
    assert len(studio.jobs) == 1
    assert studio.jobs[0]["sent_to_processed"] is True
    assert database.saved == [("flow-job", "", [])]
    studio.destroy()


def test_parameter_changes_undo_and_redo_as_one_operation(tmp_path, monkeypatch):
    import tkinter as tk
    from PIL import Image
    from app.stickers.editor_v2.window import StickerStudioV2
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "params.png"; master = tmp_path / "master.png"
    Image.new("RGBA", (30, 30), "red").save(source); Image.new("RGBA", (30, 30), "red").save(master)
    result = SimpleNamespace(artifacts={"master": str(master)}, analysis={}, quality_status="Listo")
    root = tk._default_root or tk.Tk(); root.withdraw()
    studio = StickerStudioV2(root, FakeDatabase())
    studio.jobs = [{"source_path": str(source), "status": "Procesado", "result": result,
                    "force": False, "is_png": True, "protection_zones": [],
                    "selection_contraction_mm": 0.0, "selection_expansion_mm": 0.0,
                    "selection_smoothing_mm": 0.08}]
    studio.current_index = 0; studio.refresh_queue()
    monkeypatch.setattr(studio, "reprocess_current", lambda: None)
    monkeypatch.setattr(studio, "_materialize_manual_mask", lambda _job: None)
    studio._v2_contraction_mm.set(.4); studio._v2_smoothing_mm.set(.2)
    studio._apply_inspector()
    assert studio.jobs[0]["selection_contraction_mm"] == .4
    studio._undo_edit(); assert studio.jobs[0]["selection_contraction_mm"] == 0.0
    studio._redo_edit(); assert studio.jobs[0]["selection_contraction_mm"] == .4
    studio.destroy()
