import tempfile
from pathlib import Path
from PIL import Image
import app.stickers.editor as editor


def make_fake_studio(inbox_dir: Path):
    class FakeStatus:
        def __init__(self):
            self._v = ""
        def set(self, message):
            self._v = message
    class FakeStudio:
        def __init__(self, inbox):
            self.inbox = inbox
            self.status = FakeStatus()
            self._refreshed = False
            self._processed = False
        def refresh_queue(self):
            self._refreshed = True
        def process_queue(self):
            self._processed = True
    return FakeStudio(inbox_dir)


def test_apply_area_selection_creates_cropped_file(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    img_path = tmp_path / "test.png"
    Image.new("RGBA", (400, 300), (10, 20, 30, 255)).save(img_path)

    job = {"source_path": str(img_path), "status": "Pendiente", "result": None, "force": False, "is_png": True, "protection_zones": []}
    oriented_image = Image.open(img_path).convert("RGBA")
    studio = make_fake_studio(inbox)

    box = (20, 15, 220, 200)
    mode = "selection"

    # Call the bound method implementation directly
    editor.StickerStudio._apply_area_selection(studio, job, box, oriented_image, mode)

    assert job.get("processing_source_path") is not None
    assert Path(job["processing_source_path"]).exists()
    assert tuple(job.get("selection_box")) == tuple(box)
    assert job.get("selection_mode") == mode
    assert job.get("status") == "Reprocesar"


def test_use_full_image_restores_original(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    img_path = tmp_path / "test2.png"
    Image.new("RGBA", (100, 80), (200, 10, 50, 255)).save(img_path)

    job = {"source_path": str(img_path), "status": "Pendiente", "result": None}
    oriented_image = Image.open(img_path).convert("RGBA")
    studio = make_fake_studio(inbox)

    # Simulate using full image (box=None, mode='full')
    editor.StickerStudio._apply_area_selection(studio, job, None, None, "full")

    assert "processing_source_path" not in job
    assert "selection_box" not in job
    assert "selection_mode" not in job
    assert job.get("status") == "Reprocesar"
