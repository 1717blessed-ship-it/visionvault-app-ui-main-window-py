"""Test para verificar la consistencia de selección de elementos de diferentes tamaños."""

import tkinter as tk
from pathlib import Path
import tempfile
from PIL import Image


import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.planchas.poster_print_editor import PosterPrintEditor, MixedElement
from app.planchas.poster_packing import Orientation


def create_test_image(path: Path, size: tuple = (100, 100)):
    """Crea una imagen de prueba."""
    img = Image.new("RGB", size, color="white")
    img.save(path)


def test_consecutive_selection():
    """Prueba que seleccionar consecutivamente elementos de diferentes tamaños muestre los valores correctos."""

    # Crear ventana temporal
    root = tk.Tk()
    root.withdraw()

    try:
        # Crear editor
        editor = PosterPrintEditor(root)

        # Crear imágenes de prueba
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Crear 3 imágenes
            img1_path = tmpdir / "test1.png"
            img2_path = tmpdir / "test2.png"
            img3_path = tmpdir / "test3.png"

            create_test_image(img1_path)
            create_test_image(img2_path)
            create_test_image(img3_path)

            # Agregar elementos con diferentes tamaños
            editor.mixed_elements = [
                MixedElement(
                    path=img1_path,
                    width_mm=105.0,
                    height_mm=148.0,
                    quantity=1,
                    orientation=Orientation.AUTOMATIC,
                    allow_rotation=True,
                    preset=None,
                ),
                MixedElement(
                    path=img2_path,
                    width_mm=148.0,
                    height_mm=210.0,
                    quantity=2,
                    orientation=Orientation.PORTRAIT,
                    allow_rotation=False,
                    preset=None,
                ),
                MixedElement(
                    path=img3_path,
                    width_mm=74.0,
                    height_mm=105.0,
                    quantity=3,
                    orientation=Orientation.LANDSCAPE,
                    allow_rotation=True,
                    preset=None,
                ),
            ]

            # Cambiar a modo mixto
            editor.mode_var.set("mixed")
            editor.on_mode_change()

            # Esperar a que se actualice la UI
            editor.update()

            # Seleccionar primer elemento (105x148)
            editor.tree.selection_set("0")
            editor.on_mixed_selection(None)
            editor.update()

            # Verificar valores del primer elemento
            assert editor.width_var.get() == "105.0", f"Esperado 105.0, got {editor.width_var.get()}"
            assert editor.height_var.get() == "148.0", f"Esperado 148.0, got {editor.height_var.get()}"
            assert editor.quantity_var.get() == 1, f"Esperado 1, got {editor.quantity_var.get()}"
            assert editor.orientation_var.get() == Orientation.AUTOMATIC.value
            assert editor.allow_rotation_var.get() == True

            # Aplicar cambios desde el editor mixto debe persistir todos los
            # campos editables en el elemento seleccionado.
            editor.width_var.set("106.0")
            editor.height_var.set("149.0")
            editor.quantity_var.set(4)
            editor.orientation_var.set(Orientation.PORTRAIT.value)
            editor.allow_rotation_var.set(False)
            editor.btn_apply.invoke()
            updated_first = editor.mixed_elements[0]
            assert updated_first.width_mm == 106.0
            assert updated_first.height_mm == 149.0
            assert updated_first.quantity == 4
            assert updated_first.orientation == Orientation.PORTRAIT
            assert updated_first.allow_rotation is False

            print("✓ Primer elemento (105×148) seleccionado correctamente")

            # Seleccionar segundo elemento (148x210)
            editor.tree.selection_set("1")
            editor.on_mixed_selection(None)
            editor.update()

            # Verificar valores del segundo elemento
            assert editor.width_var.get() == "148.0", f"Esperado 148.0, got {editor.width_var.get()}"
            assert editor.height_var.get() == "210.0", f"Esperado 210.0, got {editor.height_var.get()}"
            assert editor.quantity_var.get() == 2, f"Esperado 2, got {editor.quantity_var.get()}"
            assert editor.orientation_var.get() == Orientation.PORTRAIT.value
            assert editor.allow_rotation_var.get() == False

            print("✓ Segundo elemento (148×210) seleccionado correctamente")

            # Seleccionar tercer elemento (74x105)
            editor.tree.selection_set("2")
            editor.on_mixed_selection(None)
            editor.update()

            # Verificar valores del tercer elemento
            assert editor.width_var.get() == "74.0", f"Esperado 74.0, got {editor.width_var.get()}"
            assert editor.height_var.get() == "105.0", f"Esperado 105.0, got {editor.height_var.get()}"
            assert editor.quantity_var.get() == 3, f"Esperado 3, got {editor.quantity_var.get()}"
            assert editor.orientation_var.get() == Orientation.LANDSCAPE.value
            assert editor.allow_rotation_var.get() == True

            print("✓ Tercer elemento (74×105) seleccionado correctamente")

            # Volver al primer elemento
            editor.tree.selection_set("0")
            editor.on_mixed_selection(None)
            editor.update()

            # Verificar que vuelva a mostrar los valores del primer elemento
            assert editor.width_var.get() == "106.0", f"Esperado 106.0, got {editor.width_var.get()}"
            assert editor.height_var.get() == "149.0", f"Esperado 149.0, got {editor.height_var.get()}"
            assert editor.quantity_var.get() == 4, f"Esperado 4, got {editor.quantity_var.get()}"

            print("✓ Vuelta al primer elemento (105×148) correcta")

            # Deseleccionar
            editor.tree.selection_remove(editor.tree.selection())
            editor.on_mixed_selection(None)
            editor.update()

            # Verificar que el editor se limpie
            assert editor.width_var.get() == "", f"Esperado vacío, got {editor.width_var.get()}"
            assert editor.height_var.get() == "", f"Esperado vacío, got {editor.height_var.get()}"
            assert editor.quantity_var.get() == 1, f"Esperado 1 (default), got {editor.quantity_var.get()}"

            print("✓ Deselección limpia el editor correctamente")

            editor.destroy()

        print("\n✅ Todas las pruebas de consistencia de selección pasaron exitosamente")
    finally:
        root.destroy()


if __name__ == "__main__":
    test_consecutive_selection()
