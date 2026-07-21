#!/usr/bin/env python3
"""Script para aplicar la corrección del borde blanco en pipeline.py"""

import re
from pathlib import Path

# La función corregida
NEW_FUNCTION = '''    @staticmethod
    def _uniform_background_alpha(image, tolerance: int):
        """Elimina el fondo a partir del borde exterior por similitud de color.
        
        Preserva los bordes blancos existentes del diseño mediante:
        1. Estimación del color de fondo desde las esquinas y perímetro.
        2. Flood fill solo por píxeles similares al fondo oscuro detectado.
        3. Detención obligatoria al encontrar píxeles claros (L >= 225).
        4. No clasificar blancos poco saturados como fondo.
        """
        try:
            import numpy as np
            from PIL import Image

            rgb_img = image.convert("RGB")
            rgb = np.asarray(rgb_img, dtype=np.uint8)
            h, w = rgb.shape[:2]
            pixels = rgb_img.load()
            background_colors = StickerProcessor._sample_perimeter_background_colors(
                pixels, w, h, tolerance)
            if not background_colors:
                background_colors = [pixels[x, y] for x, y in (
                    (0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)
                )]

            # Estimamos el fondo predominante del marco exterior
            bg_arr = np.array(background_colors, dtype=np.int16)
            bg_mean = tuple(int(bg_arr.mean(axis=0)[i]) for i in range(3))
            
            # Detectar si el fondo es oscuro (promedio < 100)
            bg_luminosity = 0.299 * bg_mean[0] + 0.587 * bg_mean[1] + 0.114 * bg_mean[2]
            bg_is_dark = bg_luminosity < 100
            
            # Calcular luminosidad y saturación para cada píxel
            r, g, b = rgb[:,:,0], rgb[:,:,1], rgb[:,:,2]
            luminosity = (0.299 * r + 0.587 * g + 0.114 * b).astype(np.float32)
            
            # Saturación HSV simplificada
            rgb_max = rgb.max(axis=2).astype(np.float32)
            rgb_min = rgb.min(axis=2).astype(np.float32)
            saturation = np.zeros_like(luminosity)
            nonzero = rgb_max > 0
            saturation[nonzero] = ((rgb_max[nonzero] - rgb_min[nonzero]) / rgb_max[nonzero]) * 255.0

            visited = np.zeros((h, w), dtype=bool)
            from collections import deque
            queue = deque()

            def color_distance(pixel, bg):
                """Distancia euclidiana en RGB (Delta E simplificado)."""
                return float(np.sqrt(np.sum((np.asarray(pixel, dtype=np.float32) - 
                                             np.asarray(bg, dtype=np.float32))**2)))

            def is_bg_similar(pixel, lum, sat):
                """Determina si un píxel pertenece al fondo exterior.
                
                Condiciones:
                - Debe ser similar al color de fondo detectado (distancia <= tolerance*1.5)
                - Si el fondo es oscuro y el píxel es blanco claro (L>=225, S<=45):
                  NO es fondo, es el borde blanco del sticker
                """
                # Protección explícita para blancos del sticker
                if lum >= 225 and sat <= 45:
                    # Es un blanco puro/casi puro → puede ser el borde blanco
                    # Solo considerarlo fondo si el fondo también es blanco
                    if bg_luminosity < 200:
                        return False  # Detener crecimiento: es el borde blanco
                
                # Similitud de color con el fondo
                dist = color_distance(pixel, bg_mean)
                return dist <= tolerance * 1.5

            # Sembrar desde los bordes del canvas
            for x in range(w):
                pix = tuple(rgb[0, x])
                lum, sat = luminosity[0, x], saturation[0, x]
                if is_bg_similar(pix, lum, sat):
                    visited[0, x] = True
                    queue.append((x, 0))
                
                pix = tuple(rgb[h - 1, x])
                lum, sat = luminosity[h-1, x], saturation[h-1, x]
                if is_bg_similar(pix, lum, sat):
                    visited[h - 1, x] = True
                    queue.append((x, h - 1))
                    
            for y in range(1, h - 1):
                pix = tuple(rgb[y, 0])
                lum, sat = luminosity[y, 0], saturation[y, 0]
                if is_bg_similar(pix, lum, sat):
                    visited[y, 0] = True
                    queue.append((0, y))
                
                pix = tuple(rgb[y, w - 1])
                lum, sat = luminosity[y, w-1], saturation[y, w-1]
                if is_bg_similar(pix, lum, sat):
                    visited[y, w - 1] = True
                    queue.append((w - 1, y))

            # Flood fill con detención en bordes blancos
            neighbors = ((1, 0), (-1, 0), (0, 1), (0, -1),
                         (1, 1), (1, -1), (-1, 1), (-1, -1))
            while queue:
                x, y = queue.popleft()
                for dx, dy in neighbors:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx]:
                        pixel = tuple(rgb[ny, nx])
                        lum = luminosity[ny, nx]
                        sat = saturation[ny, nx]
                        
                        if is_bg_similar(pixel, lum, sat):
                            visited[ny, nx] = True
                            queue.append((nx, ny))

            # La máscara es la inversa: lo no visitado es el sticker
            alpha = np.where(visited, np.uint8(0), np.uint8(255))
            return Image.fromarray(alpha, mode="L")
        except (ImportError, ModuleNotFoundError):
            return StickerProcessor._grow_perimeter_background_alpha(image, tolerance)'''


def apply_fix():
    """Aplica la corrección al archivo pipeline.py"""
    pipeline_path = Path("app/stickers/pipeline.py")
    
    if not pipeline_path.exists():
        print(f"❌ Error: No se encontró el archivo {pipeline_path}")
        return False
    
    # Leer el contenido actual
    content = pipeline_path.read_text(encoding="utf-8")
    
    # Patrón para encontrar la función completa
    # Busca desde @staticmethod hasta el return de la función
    pattern = r'(\s+@staticmethod\s+def _uniform_background_alpha\(image, tolerance: int\):.*?return StickerProcessor\._grow_perimeter_background_alpha\(image, tolerance\))'
    
    # Verificar que la función existe
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        print("❌ Error: No se encontró la función _uniform_background_alpha")
        print("    Verifica que el archivo no haya sido modificado")
        return False
    
    print(f"✓ Función encontrada en el archivo")
    print(f"  Inicio: posición {match.start()}")
    print(f"  Fin: posición {match.end()}")
    print(f"  Longitud: {len(match.group(1))} caracteres")
    
    # Crear backup
    backup_path = pipeline_path.with_suffix(".py.backup")
    backup_path.write_text(content, encoding="utf-8")
    print(f"✓ Backup creado: {backup_path}")
    
    # Reemplazar la función
    new_content = re.sub(pattern, NEW_FUNCTION, content, count=1, flags=re.DOTALL)
    
    # Verificar que se hizo el reemplazo
    if new_content == content:
        print("❌ Error: El reemplazo no se realizó")
        return False
    
    # Guardar el archivo modificado
    pipeline_path.write_text(new_content, encoding="utf-8")
    print(f"✓ Corrección aplicada exitosamente")
    print(f"  Archivo actualizado: {pipeline_path}")
    
    # Verificar que la nueva función está en el archivo
    if "bg_luminosity" in new_content and "is_bg_similar" in new_content:
        print("✓ Verificación: La nueva función contiene las protecciones esperadas")
        return True
    else:
        print("⚠ Advertencia: La función puede no haberse actualizado correctamente")
        return False


def main():
    print("=" * 70)
    print("APLICANDO CORRECCIÓN: Preservación de Borde Blanco")
    print("=" * 70)
    print()
    
    success = apply_fix()
    
    print()
    print("=" * 70)
    if success:
        print("✅ CORRECCIÓN APLICADA EXITOSAMENTE")
        print()
        print("Próximos pasos:")
        print("  1. Revisar el archivo app/stickers/pipeline.py")
        print("  2. Ejecutar tests: python tests/test_white_border_preservation.py")
        print("  3. Validar con imágenes reales de prueba")
        print()
        print("Restaurar backup si es necesario:")
        print("  mv app/stickers/pipeline.py.backup app/stickers/pipeline.py")
    else:
        print("❌ ERROR AL APLICAR LA CORRECCIÓN")
        print()
        print("Opciones:")
        print("  1. Aplicar el cambio manualmente usando pipeline_fix.py como referencia")
        print("  2. Revisar INSTRUCCIONES_CORRECCION_BORDE_BLANCO.md")
    print("=" * 70)
    
    return 0 if success else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
