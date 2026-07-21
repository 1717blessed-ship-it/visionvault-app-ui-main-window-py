import tempfile
import time
from pathlib import Path
from PIL import Image

import app.stickers.editor as editor

# Crear imagen temporal
with tempfile.TemporaryDirectory() as tmp:
    tmpdir = Path(tmp)
    img_path = tmpdir / "test_image.png"
    img = Image.new("RGBA", (400, 300), (255, 0, 0, 255))
    img.save(img_path)

    # Preparar job simulado
    job = {
        "source_path": str(img_path),
        "status": "Pendiente",
        "result": None,
        "force": False,
        "is_png": True,
        "protection_zones": [],
    }

    # Oriented image (PIL Image)
    oriented_image = Image.open(img_path).convert("RGBA")

    # Crear objeto "fake" con los mínimos métodos/atributos usados
    class FakeStatus:
        def set(self, message):
            print("STATUS:", message)

    class FakeStudio:
        def __init__(self, inbox):
            self.inbox = inbox
            self.status = FakeStatus()
        def refresh_queue(self):
            print("refresh_queue called")
        def process_queue(self):
            print("process_queue called")

    studio = FakeStudio(tmpdir)

    # Selección de ejemplo
    box = (20, 15, 220, 200)
    mode = "selection"

    # Llamar al método no enlazado pasando la instancia fake explícitamente
    editor.StickerStudio._apply_area_selection(studio, job, box, oriented_image, mode)

    # Verificar efectos
    assert "processing_source_path" in job, "processing_source_path not set"
    assert "selection_box" in job and job["selection_box"] == tuple(box), "selection_box incorrect"
    assert job["selection_mode"] == mode, "selection_mode incorrect"

    print("Verification passed. Job fields:")
    for k in ("processing_source_path", "selection_box", "selection_mode", "status"):
        print(k, job.get(k))
