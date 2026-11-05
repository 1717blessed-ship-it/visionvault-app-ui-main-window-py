"""Script auxiliar para validación visual de la interfaz del editor de pósters."""

import tkinter as tk
from pathlib import Path
import tempfile
from PIL import Image

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.planchas.poster_print_editor import PosterPrintEditor, MixedElement, DistributionMode
from app.planchas.poster_packing import Orientation


def create_test_image(path: Path, size: tuple = (100, 100), color: str = "white"):
    """Crea una imagen de prueba."""
    img = Image.new("RGB", size, color=color)
    img.save(path)


def setup_visual_validation():
    """Abre el editor en diferentes estados para validación visual."""
    
    root = tk.Tk()
    root.title("Validación Visual - Editor de Pósters")
    
    try:
        editor = PosterPrintEditor(root)
        
        # Crear imágenes de prueba
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            
            # Crear imágenes variadas
            images = [
                ("imagen_a6.png", (105, 148), "lightblue"),
                ("imagen_a5.png", (148, 210), "lightgreen"),
                ("imagen_a7.png", (74, 105), "lightyellow"),
                ("imagen_custom.png", (120, 180), "lightcoral"),
                ("whatsapp_long_name_12345678901234567890.png", (100, 150), "lavender"),
            ]
            
            for filename, size, color in images:
                img_path = tmpdir / filename
                create_test_image(img_path, size, color)
            
            # Agregar elementos mixtos
            editor.mixed_elements = [
                MixedElement(
                    path=tmpdir / "imagen_a6.png",
                    width_mm=105.0,
                    height_mm=148.0,
                    quantity=2,
                    orientation=Orientation.AUTOMATIC,
                    allow_rotation=True,
                    preset=None,
                ),
                MixedElement(
                    path=tmpdir / "imagen_a5.png",
                    width_mm=148.0,
                    height_mm=210.0,
                    quantity=1,
                    orientation=Orientation.PORTRAIT,
                    allow_rotation=False,
                    preset=None,
                ),
                MixedElement(
                    path=tmpdir / "imagen_a7.png",
                    width_mm=74.0,
                    height_mm=105.0,
                    quantity=3,
                    orientation=Orientation.LANDSCAPE,
                    allow_rotation=True,
                    preset=None,
                ),
                MixedElement(
                    path=tmpdir / "imagen_custom.png",
                    width_mm=120.0,
                    height_mm=180.0,
                    quantity=1,
                    orientation=Orientation.AUTOMATIC,
                    allow_rotation=True,
                    preset=None,
                ),
                MixedElement(
                    path=tmpdir / "whatsapp_long_name_12345678901234567890.png",
                    width_mm=100.0,
                    height_mm=150.0,
                    quantity=1,
                    orientation=Orientation.AUTOMATIC,
                    allow_rotation=True,
                    preset=None,
                ),
            ]
            
            # Cambiar a modo mixto
            editor.mode_var.set(DistributionMode.MIXED.value)
            editor.on_mode_change()
            
            # Instrucciones para el usuario
            instructions = tk.Toplevel(root)
            instructions.title("Instrucciones de Validación Visual")
            instructions.geometry("500x400")
            
            tk.Label(instructions, text="Instrucciones para Validación Visual", 
                    font=("Arial", 14, "bold")).pack(pady=10)
            
            instr_text = """
Para validar las correcciones de interfaz, realiza las siguientes capturas:

1. COMPOSICIÓN MIXTA SIN SELECCIÓN
   - Asegúrate de que no haya ninguna fila seleccionada
   - Verifica que el editor central muestre "Seleccioná una imagen para editarla"
   - Verifica que los campos estén vacíos/deshabilitados
   - Verifica que Duplicar y Aplicar cambios estén deshabilitados

2. ELEMENTO 105×148 SELECCIONADO
   - Selecciona la primera fila (imagen_a6.png)
   - Verifica que el editor muestre: Ancho 105.0, Alto 148.0, Cant 2
   - Verifica que la fila esté resaltada
   - Verifica que Duplicar y Aplicar cambios estén habilitados

3. ELEMENTO DE OTRO TAMAÑO SELECCIONADO
   - Selecciona la segunda fila (imagen_a5.png)
   - Verifica que el editor muestre: Ancho 148.0, Alto 210.0, Cant 1
   - Verifica que los valores cambiaron correctamente

4. VISTA PREVIA CON VARIAS HOJAS
   - Agrega más elementos para generar varias hojas
   - Verifica la navegación en el footer
   - Verifica que los controles no estén cortados

5. FOOTER COMPLETO
   - Verifica que todos los controles de navegación sean visibles
   - Verifica que el texto sea legible
   - Ajusta el zoom de Windows a 125% si es posible para verificar

6. ANCHOS DE PANELES
   - Verifica que los paneles tengan las proporciones correctas
   - Intenta ajustar los separadores si usas PanedWindow

7. NOMBRES LARGOS
   - Pasa el cursor sobre el nombre largo de WhatsApp
   - Verifica que aparezca el tooltip con el nombre completo
            """
            
            tk.Label(instructions, text=instr_text, justify="left", wraplength=450).pack(padx=20, pady=10)
            
            tk.Label(instructions, text="Presiona el botón para cerrar ambas ventanas", 
                    fg="gray").pack(pady=10)
            tk.Button(instructions, text="Cerrar Validación", 
                     command=lambda: (instructions.destroy(), editor.destroy(), root.destroy())).pack(pady=5)
            
            root.mainloop()
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        root.destroy()


if __name__ == "__main__":
    print("Iniciando validación visual...")
    print("Sigue las instrucciones en la ventana que aparecerá.")
    setup_visual_validation()
