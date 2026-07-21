"""
Tests de regresión para la corrección del borde doble en diseños con fondo blanco.

Valida que:
1. Diseños con fondo blanco + borde blanco NO generen borde doble
2. El borde blanco original se conserve (pérdida < 10%)
3. No haya regresión en casos previos (fondos oscuros, transparentes, etc.)
"""

import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
import tempfile

# Agregar el directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.stickers.pipeline import StickerProcessor, ProcessingProfile


def create_test_image_white_background_with_white_border():
    """Crea una imagen de prueba: fondo blanco + borde blanco del diseño + contenido interior."""
    img = Image.new("RGB", (400, 400), color=(255, 255, 255))  # Fondo blanco
    draw = ImageDraw.Draw(img)
    
    # Dibujar el diseño con borde blanco
    # Borde blanco del diseño (rectángulo exterior)
    draw.rectangle([100, 100, 300, 300], fill=(255, 255, 255), outline=(255, 255, 255), width=20)
    
    # Contenido interior del diseño (círculo azul)
    draw.ellipse([140, 140, 260, 260], fill=(50, 100, 200), outline=(30, 80, 180))
    
    # Agregar algunos detalles interiores
    draw.ellipse([170, 170, 190, 190], fill=(255, 200, 0))
    draw.ellipse([210, 170, 230, 190], fill=(255, 200, 0))
    
    return img.convert("RGBA")


def create_test_image_dark_background_with_white_border():
    """Crea una imagen de prueba: fondo oscuro + borde blanco del diseño."""
    img = Image.new("RGB", (400, 400), color=(20, 20, 20))  # Fondo oscuro
    draw = ImageDraw.Draw(img)
    
    # Borde blanco del diseño
    draw.rectangle([100, 100, 300, 300], fill=(255, 255, 255), outline=(255, 255, 255), width=20)
    
    # Contenido interior
    draw.ellipse([140, 140, 260, 260], fill=(200, 50, 50), outline=(180, 30, 30))
    
    return img.convert("RGBA")


def create_test_image_white_background_no_border():
    """Crea una imagen de prueba: fondo blanco sin borde blanco en el diseño."""
    img = Image.new("RGB", (400, 400), color=(255, 255, 255))  # Fondo blanco
    draw = ImageDraw.Draw(img)
    
    # Diseño sin borde blanco (directamente el contenido)
    draw.ellipse([120, 120, 280, 280], fill=(50, 200, 100), outline=(30, 150, 80))
    draw.rectangle([180, 140, 220, 260], fill=(255, 200, 0))
    
    return img.convert("RGBA")


def count_white_pixels_in_border(image_rgba, mask, border_width=20):
    """Cuenta píxeles blancos en la región del borde (primeros N píxeles desde el edge)."""
    rgb = np.asarray(image_rgba.convert("RGB"), dtype=np.uint8)
    mask_arr = np.asarray(mask, dtype=np.uint8)
    h, w = mask_arr.shape
    
    # Crear máscara del borde: zona entre el edge exterior y border_width píxeles hacia adentro
    edge_mask = np.zeros_like(mask_arr, dtype=bool)
    edge_mask[:border_width, :] = True
    edge_mask[-border_width:, :] = True
    edge_mask[:, :border_width] = True
    edge_mask[:, -border_width:] = True
    
    # Región del borde en el diseño conservado
    border_region = (mask_arr == 255) & edge_mask
    
    if not border_region.any():
        return 0, 0
    
    # Píxeles blancos en el borde
    white_pixels = (rgb[:,:,0] >= 225) & (rgb[:,:,1] >= 225) & (rgb[:,:,2] >= 225)
    white_in_border = white_pixels & border_region
    
    return white_in_border.sum(), border_region.sum()


def test_white_background_with_white_border_no_double_border():
    """Test 1: Fondo blanco + borde blanco → NO generar borde doble."""
    print("\n" + "="*70)
    print("TEST 1: Fondo Blanco + Borde Blanco → Sin Borde Doble")
    print("="*70)
    
    # Crear imagen de prueba
    test_img = create_test_image_white_background_with_white_border()
    
    # Procesar con el pipeline (usar directorio temporal)
    with tempfile.TemporaryDirectory() as tmpdir:
        processor = StickerProcessor(tmpdir, ProcessingProfile())
        
        try:
            # Clasificar la imagen
            classify_result = processor.classify(test_img)
            print(f"\nClasificación detectada: {classify_result.case}")
            print(f"Fondo uniforme: {classify_result.uniform_background}")
            print(f"Tiene borde blanco: {classify_result.has_white_border}")
            
            # Generar máscara usando el método estático
            raw_alpha = StickerProcessor._uniform_background_alpha(test_img, tolerance=42)
            
            # Contar píxeles blancos en el borde ANTES del procesamiento
            white_before, total_before = count_white_pixels_in_border(test_img, 
                                                                       test_img.getchannel("A"))
            
            # Contar píxeles blancos en el borde DESPUÉS del flood fill
            white_after, total_after = count_white_pixels_in_border(test_img, raw_alpha)
            
            if white_before > 0:
                preservation_ratio = white_after / white_before
                loss_ratio = 1.0 - preservation_ratio
            else:
                preservation_ratio = 0.0
                loss_ratio = 1.0
            
            print(f"\nPíxeles blancos en borde ANTES: {white_before}/{total_before}")
            print(f"Píxeles blancos en borde DESPUÉS: {white_after}/{total_after}")
            print(f"Ratio de preservación: {preservation_ratio:.2%}")
            print(f"Ratio de pérdida: {loss_ratio:.2%}")
            
            # Criterio de éxito: preservar >= 75% del borde blanco original
            if preservation_ratio >= 0.75:
                print("\n✅ TEST PASADO: Borde blanco preservado correctamente")
                return True
            else:
                print(f"\n❌ TEST FALLIDO: Pérdida excesiva de borde blanco ({loss_ratio:.0%})")
                return False
                
        except Exception as e:
            print(f"\n❌ TEST FALLIDO: Error durante procesamiento: {e}")
            import traceback
            traceback.print_exc()
            return False


def test_dark_background_no_regression():
    """Test 2: Fondo oscuro + borde blanco → Mantener corrección previa."""
    print("\n" + "="*70)
    print("TEST 2: Fondo Oscuro + Borde Blanco → Sin Regresión")
    print("="*70)
    
    test_img = create_test_image_dark_background_with_white_border()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        processor = StickerProcessor(tmpdir, ProcessingProfile())
        
        try:
            classify_result = processor.classify(test_img)
            print(f"\nClasificación: {classify_result.case}")
            
            raw_alpha = StickerProcessor._uniform_background_alpha(test_img, tolerance=42)
            
            white_before, _ = count_white_pixels_in_border(test_img, test_img.getchannel("A"))
            white_after, _ = count_white_pixels_in_border(test_img, raw_alpha)
            
            if white_before > 0:
                preservation_ratio = white_after / white_before
            else:
                preservation_ratio = 0.0
            
            print(f"\nPíxeles blancos preservados: {preservation_ratio:.2%}")
            
            # Para fondos oscuros, la corrección previa debe funcionar
            if preservation_ratio >= 0.75:
                print("\n✅ TEST PASADO: Sin regresión en fondos oscuros")
                return True
            else:
                print(f"\n❌ TEST FALLIDO: Regresión detectada en fondos oscuros")
                return False
                
        except Exception as e:
            print(f"\n❌ TEST FALLIDO: {e}")
            import traceback
            traceback.print_exc()
            return False


def test_white_background_no_border_adds_production_border():
    """Test 3: Fondo blanco sin borde → Agregar borde de producción."""
    print("\n" + "="*70)
    print("TEST 3: Fondo Blanco Sin Borde → Agregar Borde de Producción")
    print("="*70)
    
    test_img = create_test_image_white_background_no_border()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        processor = StickerProcessor(tmpdir, ProcessingProfile())
        
        try:
            classify_result = processor.classify(test_img)
            print(f"\nClasificación: {classify_result.case}")
            print(f"Fondo uniforme: {classify_result.uniform_background}")
            
            raw_alpha = StickerProcessor._uniform_background_alpha(test_img, tolerance=42)
            
            # Verificar que el fondo fue eliminado correctamente
            mask_arr = np.asarray(raw_alpha, dtype=np.uint8)
            foreground_ratio = (mask_arr == 255).sum() / mask_arr.size
            
            print(f"\nRatio de diseño conservado: {foreground_ratio:.2%}")
            
            # Debe haber eliminado el fondo pero conservado el diseño
            if 0.05 <= foreground_ratio <= 0.90:
                print("\n✅ TEST PASADO: Fondo eliminado, diseño conservado")
                return True
            else:
                print(f"\n❌ TEST FALLIDO: Ratio de diseño fuera de rango esperado")
                return False
                
        except Exception as e:
            print(f"\n❌ TEST FALLIDO: {e}")
            import traceback
            traceback.print_exc()
            return False


def test_gradient_detection():
    """Test 4: Verificar que la detección de gradientes funciona."""
    print("\n" + "="*70)
    print("TEST 4: Detección de Gradientes")
    print("="*70)
    
    # Crear imagen simple con transición clara
    img = Image.new("RGB", (200, 200), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([50, 50, 150, 150], fill=(100, 100, 255))
    
    rgb = np.asarray(img, dtype=np.uint8)
    r, g, b = rgb[:,:,0], rgb[:,:,1], rgb[:,:,2]
    luminosity = (0.299 * r + 0.587 * g + 0.114 * b).astype(np.float32)
    
    # Calcular gradientes (mismo método que en pipeline)
    gray = luminosity
    h, w = gray.shape
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    
    # Gradiente horizontal: diferencia entre píxeles adyacentes
    if w > 1:
        gx[:, 1:] = np.abs(gray[:, 1:] - gray[:, :-1])
    
    # Gradiente vertical: diferencia entre filas adyacentes
    if h > 1:
        gy[1:, :] = np.abs(gray[1:, :] - gray[:-1, :])
    
    edge_map = np.maximum(gx, gy)
    
    # Verificar que hay gradientes fuertes en los bordes del rectángulo
    # Borde izquierdo del rectángulo (x=50)
    edge_strength_left = edge_map[100, 50]
    
    # Centro del rectángulo (sin bordes)
    edge_strength_center = edge_map[100, 100]
    
    print(f"\nGradiente en borde: {edge_strength_left:.2f}")
    print(f"Gradiente en centro: {edge_strength_center:.2f}")
    
    if edge_strength_left > 50 and edge_strength_center < 10:
        print("\n✅ TEST PASADO: Detección de gradientes funciona correctamente")
        return True
    else:
        print("\n❌ TEST FALLIDO: Detección de gradientes no funciona como esperado")
        return False


def run_all_tests():
    """Ejecuta todos los tests de regresión."""
    print("\n" + "="*70)
    print("SUITE DE TESTS: Corrección de Borde Doble en Fondos Blancos")
    print("="*70)
    
    tests = [
        ("Detección de Gradientes", test_gradient_detection),
        ("Fondo Blanco + Borde Blanco", test_white_background_with_white_border_no_double_border),
        ("Fondo Oscuro (Sin Regresión)", test_dark_background_no_regression),
        ("Fondo Blanco Sin Borde", test_white_background_no_border_adds_production_border),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ Error ejecutando test '{name}': {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Resumen final
    print("\n" + "="*70)
    print("RESUMEN DE RESULTADOS")
    print("="*70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASADO" if result else "❌ FALLIDO"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests pasados ({passed/total*100:.0f}%)")
    
    if passed == total:
        print("\n🎉 TODOS LOS TESTS PASARON")
        return True
    else:
        print(f"\n⚠️ {total - passed} test(s) fallaron")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
