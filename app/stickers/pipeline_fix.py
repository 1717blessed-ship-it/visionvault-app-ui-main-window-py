"""Función corregida para _uniform_background_alpha"""

# Esta función reemplaza el método _uniform_background_alpha en StickerProcessor
# Colocar este código en la línea 1218 de pipeline.py, reemplazando la función existente

@staticmethod
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
        return StickerProcessor._grow_perimeter_background_alpha(image, tolerance)
