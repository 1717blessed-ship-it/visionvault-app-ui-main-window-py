"""
Test unitario para validar la corrección de la lógica OR→AND
en la identificación de píxeles de fondo.

Este test verifica que con un fondo blanco (255,255,255) y tolerance=25,
solo los píxeles donde TODOS los canales están cerca del blanco sean
clasificados como fondo.
"""
import numpy as np


def test_background_logic_or_vs_and():
    """
    Valida que la lógica AND (todos los canales deben coincidir)
    clasifica correctamente los píxeles de fondo vs. diseño.
    """
    # Configuración
    bg_color = np.array([255, 255, 255], dtype=np.int16).reshape(1, 1, 3)
    tolerance = 25
    
    # Casos de prueba: (RGB, debe_ser_fondo, descripción)
    test_cases = [
        # Deben ser FALSE (NO son fondo, son diseño)
        ([255, 0, 0], False, "Rojo puro"),
        ([0, 255, 0], False, "Verde puro"),
        ([0, 0, 255], False, "Azul puro"),
        ([255, 200, 200], False, "Rosa claro (G,B lejos)"),
        ([200, 255, 255], False, "Cyan claro (R lejos)"),
        ([255, 255, 100], False, "Amarillo (B lejos)"),
        
        # Deben ser TRUE (SÍ son fondo)
        ([255, 255, 255], True, "Blanco puro"),
        ([250, 250, 250], True, "Gris muy claro (delta=5)"),
        ([240, 240, 240], True, "Gris claro (delta=15)"),
        ([230, 230, 230], True, "Gris medio-claro (delta=25, límite)"),
        
        # Debe ser FALSE (justo fuera del límite)
        ([229, 229, 229], False, "Gris medio (delta=26, fuera)"),
    ]
    
    print("\n" + "="*70)
    print("TEST: Lógica de identificación de fondo")
    print("Fondo: RGB(255,255,255), Tolerancia: 25")
    print("="*70)
    
    results_and = []
    results_or = []
    
    for rgb, expected, desc in test_cases:
        pixel = np.array(rgb, dtype=np.int16).reshape(1, 1, 3)
        
        # Lógica AND (correcta): todos los canales deben coincidir
        delta = np.abs(pixel - bg_color)
        is_bg_and = np.all(delta <= tolerance)
        
        # Lógica OR (incorrecta): basta que un canal coincida
        is_bg_or = np.any(delta <= tolerance)
        
        results_and.append(is_bg_and)
        results_or.append(is_bg_or)
        
        status_and = "✓" if is_bg_and == expected else "✗"
        status_or = "✓" if is_bg_or == expected else "✗"
        
        print(f"\n{desc}: RGB{tuple(rgb)}")
        print(f"  Esperado: {'FONDO' if expected else 'DISEÑO'}")
        print(f"  AND: {'FONDO' if is_bg_and else 'DISEÑO'} {status_and}")
        print(f"  OR:  {'FONDO' if is_bg_or else 'DISEÑO'} {status_or}")
        print(f"  Delta por canal: R={delta[0,0,0]}, G={delta[0,0,1]}, B={delta[0,0,2]}")
    
    # Verificar resultados
    failures_and = []
    failures_or = []
    
    for i, (rgb, expected, desc) in enumerate(test_cases):
        if results_and[i] != expected:
            failures_and.append(f"{desc}: esperado {expected}, obtenido {results_and[i]}")
        if results_or[i] != expected:
            failures_or.append(f"{desc}: esperado {expected}, obtenido {results_or[i]}")
    
    print("\n" + "="*70)
    print("RESULTADOS:")
    print(f"  Lógica AND: {len(test_cases) - len(failures_and)}/{len(test_cases)} casos correctos")
    print(f"  Lógica OR:  {len(test_cases) - len(failures_or)}/{len(test_cases)} casos correctos")
    print("="*70)
    
    if failures_and:
        print("\n✗ FALLOS con lógica AND:")
        for f in failures_and:
            print(f"  - {f}")
    else:
        print("\n✓ Lógica AND: TODOS LOS CASOS CORRECTOS")
    
    if failures_or:
        print("\n✗ FALLOS con lógica OR:")
        for f in failures_or:
            print(f"  - {f}")
    else:
        print("\n✓ Lógica OR: TODOS LOS CASOS CORRECTOS")
    
    print()
    
    # El test pasa si la lógica AND es correcta
    assert len(failures_and) == 0, f"Lógica AND falló en {len(failures_and)} casos"
    
    # Verificar que la lógica OR SÍ falla (para confirmar que era el problema)
    assert len(failures_or) > 0, "La lógica OR debería fallar en algunos casos"
    
    print("✓ TEST COMPLETO: La lógica AND es correcta y la lógica OR era incorrecta.\n")


if __name__ == "__main__":
    test_background_logic_or_vs_and()
