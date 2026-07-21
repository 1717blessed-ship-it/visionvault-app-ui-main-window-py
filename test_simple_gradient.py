"""
Test simple y rápido de la corrección de gradientes.
Prueba directamente la función _uniform_background_alpha sin overhead del pipeline.
"""

import numpy as np
from PIL import Image, ImageDraw
import sys
from pathlib import Path

# Agregar el directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent))

from app.stickers.pipeline import StickerProcessor


def test_gradient_calculation():
    """Test 1: Verificar que el cálculo de gradientes funciona correctamente."""
    print("\n" + "="*70)
    print("TEST 1: Cálculo de Gradientes")
    print("="*70)
    
    # Crear imagen simple: blanco con cuadrado azul
    img = Image.new("RGB", (100, 100), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([25, 25, 75, 75], fill=(100, 100, 255))
    
    rgb = np.asarray(img, dtype=np.uint8)
    r, g, b = rgb[:,:,0], rgb[:,:,1], rgb[:,:,2]
    luminosity = (0.299 * r + 0.587 * g + 0.114 * b).astype(np.float32)
    
    # Calcular gradientes
    gray = luminosity
    h, w = gray.shape
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    
    if w > 1:
        gx[:, 1:] = np.abs(gray[:, 1:] - gray[:, :-1])
    if h > 1:
        gy[1:, :] = np.abs(gray[1:, :] - gray[:-1, :])
    
    edge_map = np.maximum(gx, gy)
    
    # Verificar gradientes
    # El borde izquierdo del cuadrado está en x=25
    # Buscamos el gradiente justo después del borde
    edge_at_border = edge_map[50, 25]  # Borde izquierdo del cuadrado
    edge_at_center = edge_map[50, 50]  # Centro del cuadrado
    edge_in_background = edge_map[10, 10]  # Fondo blanco
    
    print(f"Gradiente en borde del cuadrado: {edge_at_border:.2f}")
    print(f"Gradiente en centro del cuadrado: {edge_at_center:.2f}")
    print(f"Gradiente en fondo: {edge_in_background:.2f}")
    
    if edge_at_border > 50 and edge_at_center < 5 and edge_in_background < 5:
        print("✅ PASADO: Detección de gradientes funciona")
        return True
    else:
        print("❌ FALLIDO: Gradientes incorrectos")
        print(f"  Esperado: borde > 50, centro < 5, fondo < 5")
        return False


def test_white_background_flood_fill():
    """Test 2: Verificar que el flood fill se detiene en bordes detectados por gradiente."""
    print("\n" + "="*70)
    print("TEST 2: Flood Fill con Fondo Blanco")
    print("="*70)
    
    # Crear imagen: fondo blanco + rectángulo blanco (borde) + contenido azul
    img = Image.new("RGBA", (200, 200), color=(255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    
    # Rectángulo blanco (simula el borde del diseño)
    draw.rectangle([50, 50, 150, 150], fill=(255, 255, 255), outline=(255, 255, 255))
    
    # Contenido interior azul
    draw.ellipse([70, 70, 130, 130], fill=(100, 100, 200))
    
    print("\nProcesando imagen de prueba...")
    
    try:
        # Llamar directamente a la función estática (más rápido)
        mask = StickerProcessor._uniform_background_alpha(img, tolerance=42)
        
        mask_arr = np.asarray(mask, dtype=np.uint8)
        
        # Verificar que el fondo fue eliminado (esquinas)
        corner_eliminated = mask_arr[10, 10] == 0
        
        # Verificar que el diseño se conservó (centro)
        design_preserved = mask_arr[100, 100] == 255
        
        # Calcular ratio de área conservada
        area_ratio = (mask_arr == 255).sum() / mask_arr.size
        
        print(f"\nEsquina (fondo) eliminada: {corner_eliminated}")
        print(f"Centro (diseño) conservado: {design_preserved}")
        print(f"Ratio de diseño conservado: {area_ratio:.2%}")
        
        if corner_eliminated and design_preserved and 0.05 < area_ratio < 0.90:
            print("✅ PASADO: Flood fill funciona correctamente")
            return True
        else:
            print("❌ FALLIDO: Flood fill no funciona como esperado")
            print(f"  Esquina eliminada: {corner_eliminated} (esperado: True)")
            print(f"  Centro conservado: {design_preserved} (esperado: True)")
            print(f"  Ratio en rango: {0.05 < area_ratio < 0.90} (esperado: True, actual: {area_ratio:.2%})")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_dark_background_still_works():
    """Test 3: Verificar que fondos oscuros siguen funcionando (sin regresión)."""
    print("\n" + "="*70)
    print("TEST 3: Fondo Oscuro (Sin Regresión)")
    print("="*70)
    
    # Crear imagen: fondo oscuro + borde blanco + contenido rojo
    img = Image.new("RGBA", (200, 200), color=(20, 20, 20, 255))
    draw = ImageDraw.Draw(img)
    
    # Borde blanco
    draw.rectangle([50, 50, 150, 150], fill=(255, 255, 255), outline=(255, 255, 255))
    
    # Contenido interior rojo
    draw.ellipse([70, 70, 130, 130], fill=(200, 50, 50))
    
    print("\nProcesando imagen con fondo oscuro...")
    
    try:
        mask = StickerProcessor._uniform_background_alpha(img, tolerance=42)
        mask_arr = np.asarray(mask, dtype=np.uint8)
        
        # Verificar que el fondo oscuro fue eliminado
        corner_eliminated = mask_arr[10, 10] == 0
        
        # Verificar que el borde blanco se conservó
        white_border_preserved = mask_arr[60, 60] == 255
        
        # Calcular ratio
        area_ratio = (mask_arr == 255).sum() / mask_arr.size
        
        print(f"\nFondo oscuro eliminado: {corner_eliminated}")
        print(f"Borde blanco conservado: {white_border_preserved}")
        print(f"Ratio de diseño conservado: {area_ratio:.2%}")
        
        if corner_eliminated and white_border_preserved and area_ratio > 0.15:
            print("✅ PASADO: Sin regresión en fondos oscuros")
            return True
        else:
            print("❌ FALLIDO: Regresión detectada")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Ejecuta los tests rápidos."""
    print("\n" + "="*70)
    print("TESTS RÁPIDOS: Corrección de Borde Doble")
    print("="*70)
    
    tests = [
        ("Cálculo de Gradientes", test_gradient_calculation),
        ("Flood Fill Fondo Blanco", test_white_background_flood_fill),
        ("Sin Regresión Fondo Oscuro", test_dark_background_still_works),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ Error en test '{name}': {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Resumen
    print("\n" + "="*70)
    print("RESUMEN")
    print("="*70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅" if result else "❌"
        print(f"{status} {name}")
    
    print(f"\nTotal: {passed}/{total} tests pasados ({passed/total*100:.0f}%)")
    
    if passed == total:
        print("\n🎉 TODOS LOS TESTS PASARON")
        return True
    else:
        print(f"\n⚠️ {total - passed} test(s) fallaron")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
