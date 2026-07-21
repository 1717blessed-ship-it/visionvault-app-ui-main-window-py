"""Test para verificar la preservación del borde blanco original en imágenes con fondo oscuro."""

import pytest
import numpy as np
from PIL import Image
from pathlib import Path


def create_test_image_with_white_border():
    """Crea una imagen de prueba: fondo oscuro + diseño con borde blanco."""
    size = (400, 400)
    img = Image.new("RGB", size, (30, 30, 30))  # Fondo oscuro
    
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    
    # Diseño interior (flores/corazón simulado) en colores
    draw.ellipse([150, 150, 250, 250], fill=(255, 100, 150))  # Corazón rosado
    draw.ellipse([130, 130, 180, 180], fill=(200, 50, 50))    # Flor 1
    draw.ellipse([220, 130, 270, 180], fill=(200, 50, 50))    # Flor 2
    draw.ellipse([130, 220, 180, 270], fill=(50, 150, 50))    # Hoja 1
    draw.ellipse([220, 220, 270, 270], fill=(50, 150, 50))    # Hoja 2
    
    # Borde blanco alrededor del diseño (el que debe preservarse)
    # Este es el borde original que NO debe eliminarse
    draw.ellipse([115, 115, 285, 285], outline=(255, 255, 255), width=8)
    
    return img


def test_white_border_is_preserved():
    """Verifica que el borde blanco original se preserve después del procesamiento."""
    from app.stickers.pipeline import StickerProcessor, ProcessingProfile
    
    # Crear imagen de prueba
    test_img = create_test_image_with_white_border()
    
    # Contar píxeles blancos en el borde antes del procesamiento
    rgb = np.asarray(test_img, dtype=np.uint8)
    white_pixels_before = np.sum(
        (rgb[:,:,0] >= 225) & (rgb[:,:,1] >= 225) & (rgb[:,:,2] >= 225)
    )
    
    print(f"Píxeles blancos antes: {white_pixels_before}")
    
    # Guardar imagen de prueba temporalmente
    test_path = Path("test_white_border_input.png")
    test_img.save(test_path)
    
    try:
        # Procesar con el pipeline
        processor = StickerProcessor(
            workspace="test_output",
            profile=ProcessingProfile()
        )
        
        # Obtener la máscara después de la eliminación de fondo
        rgba_test = test_img.convert("RGBA")
        alpha_result = processor._uniform_background_alpha(rgba_test, tolerance=42)
        
        # Contar píxeles blancos del diseño que quedaron en la máscara
        mask_arr = np.asarray(alpha_result, dtype=np.uint8)
        design_pixels = np.sum(mask_arr > 127)
        
        # Contar píxeles blancos del diseño original que están en la máscara
        white_in_mask = np.sum(
            (rgb[:,:,0] >= 225) & (rgb[:,:,1] >= 225) & (rgb[:,:,2] >= 225) & (mask_arr > 127)
        )
        
        print(f"Píxeles blancos preservados: {white_in_mask}")
        print(f"Píxeles totales del diseño: {design_pixels}")
        
        # Calcular porcentaje de preservación del borde blanco
        preservation_rate = white_in_mask / max(white_pixels_before, 1)
        print(f"Tasa de preservación: {preservation_rate:.1%}")
        
        # El test pasa si se preserva al menos el 75% del borde blanco original
        assert preservation_rate >= 0.75, (
            f"Se perdió demasiado borde blanco: {preservation_rate:.1%} preservado "
            f"(esperado: >=75%)"
        )
        
        # Verificar que la máscara no está vacía
        assert design_pixels > 0, "La máscara quedó vacía"
        
        # Guardar resultado para inspección visual
        result_path = Path("test_white_border_output.png")
        alpha_result.save(result_path)
        print(f"Máscara guardada en: {result_path}")
        
    finally:
        # Limpiar archivos de prueba
        if test_path.exists():
            test_path.unlink()


def test_dark_background_detection():
    """Verifica que se detecte correctamente un fondo oscuro."""
    from app.stickers.pipeline import StickerProcessor
    
    # Imagen con fondo oscuro
    test_img = create_test_image_with_white_border()
    rgba_test = test_img.convert("RGBA")
    
    # Verificar que el método reconoce el fondo como oscuro
    # (esto debería activar la protección del borde blanco)
    alpha_result = StickerProcessor._uniform_background_alpha(rgba_test, tolerance=42)
    
    # Si la función está corregida, debe haber píxeles blancos preservados
    mask_arr = np.asarray(alpha_result, dtype=np.uint8)
    rgb = np.asarray(test_img, dtype=np.uint8)
    
    white_in_original = np.sum(
        (rgb[:,:,0] >= 225) & (rgb[:,:,1] >= 225) & (rgb[:,:,2] >= 225)
    )
    white_in_mask = np.sum(
        (rgb[:,:,0] >= 225) & (rgb[:,:,1] >= 225) & (rgb[:,:,2] >= 225) & (mask_arr > 127)
    )
    
    assert white_in_mask > 0, "No se preservó ningún píxel blanco del borde"
    assert white_in_mask >= white_in_original * 0.6, \
        "Se perdió más del 40% del borde blanco original"


def test_white_pixel_not_classified_as_background():
    """Verifica que píxeles blancos con baja saturación NO se clasifiquen como fondo."""
    from app.stickers.pipeline import StickerProcessor
    import numpy as np
    
    # Crear imagen simple: borde de fondo oscuro, interior con blanco puro
    size = (200, 200)
    img_arr = np.full((size[1], size[0], 3), 30, dtype=np.uint8)  # Fondo oscuro
    
    # Región blanca central (el diseño con borde blanco)
    img_arr[50:150, 50:150] = 255  # Blanco puro
    
    test_img = Image.fromarray(img_arr, mode="RGB")
    rgba_test = test_img.convert("RGBA")
    
    # Aplicar eliminación de fondo
    alpha_result = StickerProcessor._uniform_background_alpha(rgba_test, tolerance=42)
    mask_arr = np.asarray(alpha_result, dtype=np.uint8)
    
    # Verificar que la región blanca central se preservó
    white_region_preserved = mask_arr[50:150, 50:150]
    preserved_ratio = np.sum(white_region_preserved > 127) / white_region_preserved.size
    
    print(f"Región blanca preservada: {preserved_ratio:.1%}")
    
    assert preserved_ratio >= 0.95, \
        f"La región blanca se eliminó incorrectamente: solo {preserved_ratio:.1%} preservado"


if __name__ == "__main__":
    print("=" * 60)
    print("Test 1: Preservación del borde blanco")
    print("=" * 60)
    test_white_border_is_preserved()
    
    print("\n" + "=" * 60)
    print("Test 2: Detección de fondo oscuro")
    print("=" * 60)
    test_dark_background_detection()
    
    print("\n" + "=" * 60)
    print("Test 3: Píxeles blancos no clasificados como fondo")
    print("=" * 60)
    test_white_pixel_not_classified_as_background()
    
    print("\n" + "=" * 60)
    print("✓ Todos los tests pasaron exitosamente")
    print("=" * 60)
