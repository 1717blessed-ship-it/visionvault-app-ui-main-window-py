"""
Ejemplos y casos de prueba para descontaminación de halo gris.

Este módulo contiene funciones auxiliares para generar imágenes de test
que demuestran diferentes escenarios de halo gris en stickers.
"""

from PIL import Image, ImageDraw
import numpy as np
from typing import Tuple


def create_test_sticker_with_grey_halo(
    size: int = 200,
    design_color: Tuple[int, int, int] = (255, 255, 255),
    halo_color: Tuple[int, int, int] = (150, 150, 150),
    halo_width: int = 5
) -> Image.Image:
    """Crea un sticker de prueba con halo gris perimetral.
    
    Args:
        size: Tamaño de la imagen en píxeles
        design_color: Color RGB del diseño principal
        halo_color: Color RGB del halo gris
        halo_width: Ancho del halo en píxeles
    
    Returns:
        PIL Image en modo RGBA con halo gris
    
    Example:
        >>> image = create_test_sticker_with_grey_halo()
        >>> # Sticker blanco con halo gris de 5px
    """
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # Diseño principal (círculo blanco)
    center = size // 2
    radius = size // 3
    draw.ellipse(
        (center - radius, center - radius, center + radius, center + radius),
        fill=(*design_color, 255)
    )
    
    # Halo gris alrededor
    for i in range(halo_width):
        offset = i + 1
        draw.ellipse(
            (center - radius - offset, center - radius - offset,
             center + radius + offset, center + radius + offset),
            outline=(*halo_color, 255),
            width=1
        )
    
    return image


def create_star_sticker_with_fine_points(
    size: int = 200,
    num_points: int = 5,
    with_halo: bool = True
) -> Image.Image:
    """Crea un sticker en forma de estrella con puntas finas.
    
    Este es un test crítico: las puntas NO deben redondearse durante
    la descontaminación del halo.
    
    Args:
        size: Tamaño de la imagen
        num_points: Número de puntas de la estrella
        with_halo: Si incluir halo gris o no
    
    Returns:
        PIL Image en modo RGBA
    
    Example:
        >>> star = create_star_sticker_with_fine_points(num_points=8)
        >>> # Estrella de 8 puntas con halo gris
    """
    import math
    
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    center_x, center_y = size // 2, size // 2
    outer_radius = size // 3
    inner_radius = size // 6
    
    # Calcular puntos de la estrella
    star_points = []
    for i in range(num_points * 2):
        angle = (i * 180 / num_points - 90) * math.pi / 180
        radius = outer_radius if i % 2 == 0 else inner_radius
        x = center_x + radius * math.cos(angle)
        y = center_y + radius * math.sin(angle)
        star_points.append((x, y))
    
    # Dibujar estrella blanca
    draw.polygon(star_points, fill=(255, 255, 255, 255))
    
    # Agregar halo gris si se solicita
    if with_halo:
        for offset in range(1, 6):
            halo_points = []
            for i in range(num_points * 2):
                angle = (i * 180 / num_points - 90) * math.pi / 180
                radius = (outer_radius if i % 2 == 0 else inner_radius) + offset
                x = center_x + radius * math.cos(angle)
                y = center_y + radius * math.sin(angle)
                halo_points.append((x, y))
            
            grey = 150 - offset * 5
            draw.polygon(halo_points, outline=(grey, grey, grey, 255), width=1)
    
    return image


def create_connected_shapes_sticker(
    size: int = 200,
    with_halo: bool = True
) -> Image.Image:
    """Crea un sticker con formas conectadas por líneas finas.
    
    Test crítico: las conexiones finas NO deben romperse durante
    la descontaminación.
    
    Args:
        size: Tamaño de la imagen
        with_halo: Si incluir halo gris
    
    Returns:
        PIL Image en modo RGBA
    
    Example:
        >>> connected = create_connected_shapes_sticker()
        >>> # Tres círculos conectados por líneas finas
    """
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # Tres círculos conectados
    positions = [
        (size // 4, size // 2),      # Izquierda
        (size // 2, size // 4),      # Arriba
        (3 * size // 4, size // 2)   # Derecha
    ]
    
    # Dibujar círculos blancos
    radius = size // 10
    for cx, cy in positions:
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            fill=(255, 255, 255, 255)
        )
    
    # Dibujar conexiones finas (3px de ancho)
    draw.line([positions[0], positions[1]], fill=(255, 255, 255, 255), width=3)
    draw.line([positions[1], positions[2]], fill=(255, 255, 255, 255), width=3)
    draw.line([positions[2], positions[0]], fill=(255, 255, 255, 255), width=3)
    
    # Agregar halo gris
    if with_halo:
        # Obtener máscara del diseño
        alpha = image.getchannel("A")
        alpha_arr = np.array(alpha)
        
        # Expandir para crear halo
        import cv2
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
        expanded = cv2.dilate(alpha_arr, kernel, iterations=1)
        
        # Crear imagen con halo
        halo_image = image.copy()
        halo_rgba = np.array(halo_image)
        
        # Agregar píxeles grises en la expansión
        halo_mask = (expanded > 0) & (alpha_arr == 0)
        halo_rgba[halo_mask] = [140, 140, 140, 255]
        
        return Image.fromarray(halo_rgba, mode="RGBA")
    
    return image


def create_text_like_sticker(
    size: int = 200,
    with_halo: bool = True
) -> Image.Image:
    """Crea un sticker similar a texto con bordes rectos.
    
    Test crítico: los bordes rectos NO deben redondearse.
    
    Args:
        size: Tamaño de la imagen
        with_halo: Si incluir halo gris
    
    Returns:
        PIL Image en modo RGBA
    
    Example:
        >>> text = create_text_like_sticker()
        >>> # Sticker rectangular con bordes rectos
    """
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # Rectángulo blanco principal
    margin = size // 4
    draw.rectangle(
        (margin, margin, size - margin, size - margin),
        fill=(255, 255, 255, 255)
    )
    
    # Agregar "texto" simulado (barras negras)
    bar_height = 8
    bar_margin = margin + 20
    for i in range(5):
        y = margin + 30 + i * 20
        draw.rectangle(
            (bar_margin, y, size - bar_margin, y + bar_height),
            fill=(0, 0, 0, 255)
        )
    
    # Agregar halo gris
    if with_halo:
        for offset in range(1, 8):
            grey = 145
            draw.rectangle(
                (margin - offset, margin - offset,
                 size - margin + offset, size - margin + offset),
                outline=(grey, grey, grey, 255),
                width=1
            )
    
    return image


def create_gradient_grey_halo_sticker(
    size: int = 200
) -> Image.Image:
    """Crea un sticker con halo gris gradiente (más difícil de detectar).
    
    Test de robustez: el algoritmo debe manejar halos con gradientes.
    
    Args:
        size: Tamaño de la imagen
    
    Returns:
        PIL Image en modo RGBA
    
    Example:
        >>> gradient = create_gradient_grey_halo_sticker()
        >>> # Halo gris que se desvanece gradualmente
    """
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # Diseño principal (hexágono blanco)
    import math
    center_x, center_y = size // 2, size // 2
    radius = size // 3
    
    hexagon_points = []
    for i in range(6):
        angle = (i * 60 - 30) * math.pi / 180
        x = center_x + radius * math.cos(angle)
        y = center_y + radius * math.sin(angle)
        hexagon_points.append((x, y))
    
    draw.polygon(hexagon_points, fill=(255, 255, 255, 255))
    
    # Agregar halo gris con gradiente (oscuro → claro)
    for offset in range(1, 15):
        # Gradiente: de 120 (oscuro) a 200 (claro)
        grey_value = 120 + int((offset / 15) * 80)
        
        halo_points = []
        for i in range(6):
            angle = (i * 60 - 30) * math.pi / 180
            x = center_x + (radius + offset) * math.cos(angle)
            y = center_y + (radius + offset) * math.sin(angle)
            halo_points.append((x, y))
        
        draw.polygon(
            halo_points,
            outline=(grey_value, grey_value, grey_value, 255),
            width=1
        )
    
    return image


def visualize_detection_zones(
    image: Image.Image,
    outer_band_width: int = 8
) -> Image.Image:
    """Visualiza las zonas de detección del algoritmo.
    
    Útil para debugging: muestra dónde el algoritmo busca el halo gris.
    
    Args:
        image: Imagen de entrada
        outer_band_width: Ancho de la banda externa
    
    Returns:
        PIL Image con zonas coloreadas para visualización
    
    Example:
        >>> test_image = create_test_sticker_with_grey_halo()
        >>> zones = visualize_detection_zones(test_image)
        >>> # Rojo: zona donde se busca halo
        >>> # Verde: zona protegida (interior)
        >>> # Azul: zona externa (fuera del sticker)
    """
    import cv2
    
    # Obtener canal alfa
    alpha = image.getchannel("A")
    alpha_arr = np.array(alpha, dtype=np.uint8)
    
    # Máscara opaca
    opaque_mask = (alpha_arr > 127).astype(np.uint8)
    
    # Definir zonas
    kernel_size = max(3, min(5, outer_band_width // 2))
    kernel_outer = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    kernel_inner = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (outer_band_width, outer_band_width))
    
    opaque_expanded = cv2.dilate(opaque_mask * 255, kernel_outer, iterations=1)
    opaque_contracted = cv2.erode(opaque_mask * 255, kernel_inner, iterations=1)
    
    # Zona de detección (banda externa)
    detection_zone = (opaque_expanded > 127) & (opaque_contracted == 0)
    
    # Zona protegida (interior)
    protected_zone = (opaque_contracted > 127)
    
    # Crear visualización
    viz = np.array(image.convert("RGBA"))
    
    # Rojo: zona de detección
    viz[detection_zone, :3] = [255, 0, 0]
    viz[detection_zone, 3] = 128  # Semi-transparente
    
    # Verde: zona protegida
    viz[protected_zone, :3] = [0, 255, 0]
    viz[protected_zone, 3] = 64  # Más transparente
    
    return Image.fromarray(viz, mode="RGBA")


# Constantes para casos de test
TEST_CASES = {
    "basic": "Sticker básico con halo gris uniforme",
    "star": "Estrella con puntas finas que deben preservarse",
    "connected": "Formas conectadas con líneas finas",
    "text": "Sticker tipo texto con bordes rectos",
    "gradient": "Halo gris con gradiente (caso difícil)",
}


if __name__ == "__main__":
    # Demo rápida de los generadores
    import sys
    from pathlib import Path
    
    output_dir = Path("test_images_grey_halo")
    output_dir.mkdir(exist_ok=True)
    
    print("Generando imágenes de test...")
    
    # Caso 1: Básico
    basic = create_test_sticker_with_grey_halo()
    basic.save(output_dir / "01_basic.png")
    print("✓ 01_basic.png")
    
    # Caso 2: Estrella
    star = create_star_sticker_with_fine_points(num_points=5)
    star.save(output_dir / "02_star.png")
    print("✓ 02_star.png")
    
    # Caso 3: Conectado
    try:
        connected = create_connected_shapes_sticker()
        connected.save(output_dir / "03_connected.png")
        print("✓ 03_connected.png")
    except ImportError:
        print("⚠ 03_connected.png (requiere opencv)")
    
    # Caso 4: Texto
    text = create_text_like_sticker()
    text.save(output_dir / "04_text.png")
    print("✓ 04_text.png")
    
    # Caso 5: Gradiente
    gradient = create_gradient_grey_halo_sticker()
    gradient.save(output_dir / "05_gradient.png")
    print("✓ 05_gradient.png")
    
    print(f"\nImágenes guardadas en: {output_dir.absolute()}")
