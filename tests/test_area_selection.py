import tkinter as tk
import tempfile
from pathlib import Path
from PIL import Image
import time


from app.stickers.editor import AreaSelectionEditor


def make_event(x, y):
    class E:
        pass
    e = E()
    e.x = x
    e.y = y
    return e


def test_area_selection_draw_and_confirm(tmp_path):
    # Preparar imagen
    img_path = tmp_path / "img.png"
    Image.new("RGBA", (400, 300), (120, 140, 160, 255)).save(img_path)

    # Captura de callback
    captured = {}

    def on_selected(box, image, mode):
        captured['box'] = box
        captured['mode'] = mode
        captured['image_size'] = image.size if image is not None else None

    # Crear root y editor
    root = tk.Tk()
    root.withdraw()
    editor = AreaSelectionEditor(root, img_path, on_selected)

    # Forzar render para calcular offsets y scale
    editor.update_idletasks()
    editor.render()
    editor.update_idletasks()

    # Simular dibujo: empezar en (50,40) imagen coords y terminar en (250,200)
    x1_img, y1_img = 50, 40
    x2_img, y2_img = 250, 200
    ox, oy = editor.display_offset
    s = editor.display_scale
    # Convertir a coords de canvas
    x1_canvas = int(ox + x1_img * s)
    y1_canvas = int(oy + y1_img * s)
    x2_canvas = int(ox + x2_img * s)
    y2_canvas = int(oy + y2_img * s)

    # Llamar a handlers
    editor.start_selection(make_event(x1_canvas, y1_canvas))
    editor.update_selection(make_event(x2_canvas, y2_canvas))
    editor.finish_selection(make_event(x2_canvas, y2_canvas))

    # Confirmar selección
    editor.confirm_selection('selection')

    # Esperar callback
    time.sleep(0.1)

    assert 'box' in captured
    bx = captured['box']
    # Box debe aproximarse a los coords de imagen dados
    assert abs(bx[0] - x1_img) <= 2 and abs(bx[1] - y1_img) <= 2
    assert abs(bx[2] - x2_img) <= 2 and abs(bx[3] - y2_img) <= 2
    assert captured['mode'] == 'selection'
    assert captured['image_size'] == (400, 300)

    # Cerrar root
    try:
        editor.destroy()
    except Exception:
        pass
    root.destroy()
