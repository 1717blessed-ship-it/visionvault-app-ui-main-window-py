"""Operaciones puras de procesamiento de imágenes.

Todas las funciones en este módulo son *puras*: no conocen Tkinter,
no guardan archivos y no dependen del estado de la aplicación.
Operan exclusamente sobre arrays numpy / imágenes PIL y devuelven
resultados nuevos sin mutar los argumentos.

Convención de máscaras
----------------------
    255  o  True  →  conservar diseño (foreground)
     0  o  False  →  eliminar fondo (background)
"""

from __future__ import annotations

from typing import Any

import numpy as np


# ══════════════════════════════════════════════════════════════════════════════
# Utilidades de conversión
# ══════════════════════════════════════════════════════════════════════════════

def to_numpy(image: Any) -> np.ndarray:
    """Convierte una imagen PIL o array a numpy uint8."""
    if isinstance(image, np.ndarray):
        return image.astype(np.uint8)
    return np.asarray(image, dtype=np.uint8)


def to_pil_mask(arr: np.ndarray) -> Any:
    """Convierte un array numpy a imagen PIL modo 'L'."""
    from PIL import Image
    return Image.fromarray(arr.astype(np.uint8), mode="L")


def ensure_binary_mask(mask: np.ndarray) -> np.ndarray:
    """Normaliza una máscara a 0/255 uint8."""
    arr = to_numpy(mask)
    return np.where(arr > 127, 255, 0).astype(np.uint8)


# ══════════════════════════════════════════════════════════════════════════════
# Operaciones morfológicas básicas
# ══════════════════════════════════════════════════════════════════════════════

def dilate_mask(mask: np.ndarray, radius: int = 3) -> np.ndarray:
    """Dilata la máscara usando un elemento estructurante elíptico."""
    if radius <= 0:
        return ensure_binary_mask(mask)
    try:
        import cv2
        arr = ensure_binary_mask(mask)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
        return cv2.dilate(arr, k)
    except ImportError:
        from PIL import Image, ImageFilter
        pil = to_pil_mask(mask)
        return to_numpy(pil.filter(ImageFilter.MaxFilter(radius * 2 + 1)))


def erode_mask(mask: np.ndarray, radius: int = 3) -> np.ndarray:
    """Eróde la máscara usando un elemento estructurante elíptico."""
    if radius <= 0:
        return ensure_binary_mask(mask)
    try:
        import cv2
        arr = ensure_binary_mask(mask)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
        return cv2.erode(arr, k)
    except ImportError:
        from PIL import Image, ImageFilter
        pil = to_pil_mask(mask)
        return to_numpy(pil.filter(ImageFilter.MinFilter(radius * 2 + 1)))


def open_mask(mask: np.ndarray, radius: int = 3) -> np.ndarray:
    """Apertura: erosión seguida de dilatación. Elimina partículas pequeñas."""
    return dilate_mask(erode_mask(mask, radius), radius)


def close_mask(mask: np.ndarray, radius: int = 3) -> np.ndarray:
    """Cierre: dilatación seguida de erosión. Cierra huecos pequeños."""
    return erode_mask(dilate_mask(mask, radius), radius)


def smooth_mask(mask: np.ndarray, radius: int = 3) -> np.ndarray:
    """Suaviza los bordes de la máscara con un desenfoque gaussiano."""
    if radius <= 0:
        return ensure_binary_mask(mask)
    try:
        import cv2
        arr = ensure_binary_mask(mask).astype(np.float32) / 255.0
        k = max(1, radius * 2 + 1)
        blurred = cv2.GaussianBlur(arr, (k, k), 0)
        return (blurred > 0.5).astype(np.uint8) * 255
    except ImportError:
        from PIL import Image, ImageFilter
        pil = to_pil_mask(mask)
        blurred = pil.filter(ImageFilter.GaussianBlur(radius))
        return ensure_binary_mask(to_numpy(blurred))


# ══════════════════════════════════════════════════════════════════════════════
# Análisis de componentes conectados y contornos
# ══════════════════════════════════════════════════════════════════════════════

def find_connected_components(mask: np.ndarray, connectivity: int = 8) -> tuple:
    """Encuentra componentes conectados en una máscara binaria.

    Returns:
        (num_labels, labels, stats, centroids)
    """
    arr = ensure_binary_mask(mask)
    try:
        import cv2
        return cv2.connectedComponentsWithStats(arr, connectivity=connectivity)
    except ImportError:
        from scipy import ndimage
        struct = np.ones((3, 3)) if connectivity == 8 else np.eye(3)
        labeled, num = ndimage.label(arr > 127, structure=struct)
        h, w = arr.shape
        stats = np.zeros((num + 1, 5), dtype=np.int32)
        centroids = np.zeros((num + 1, 2), dtype=np.float64)
        for i in range(1, num + 1):
            ys, xs = np.where(labeled == i)
            if len(xs) == 0:
                continue
            stats[i] = [xs.min(), ys.min(), xs.max() - xs.min() + 1,
                        ys.max() - ys.min() + 1, len(xs)]
            centroids[i] = [xs.mean(), ys.mean()]
        return num, labeled, stats, centroids


def find_contours(mask: np.ndarray, external_only: bool = False) -> list:
    """Encuentra contornos en una máscara binaria."""
    arr = ensure_binary_mask(mask)
    try:
        import cv2
        mode = cv2.RETR_EXTERNAL if external_only else cv2.RETR_CCOMP
        contours, _ = cv2.findContours(arr, mode, cv2.CHAIN_APPROX_NONE)
        return contours
    except ImportError:
        from skimage import measure
        return [np.array(c, dtype=np.int32).reshape(-1, 1, 2)
                for c in measure.find_contours(arr.astype(float), 127.5)]


def largest_connected_component(mask: np.ndarray) -> np.ndarray:
    """Devuelve una máscara con solo el componente conectado más grande."""
    arr = ensure_binary_mask(mask)
    num_labels, labels, stats, _ = find_connected_components(arr)
    if num_labels <= 1:
        return arr
    largest = 1 + int(np.argmax(stats[1:, 4]))
    return (labels == largest).astype(np.uint8) * 255


# ══════════════════════════════════════════════════════════════════════════════
# Relleno de huecos internos
# ══════════════════════════════════════════════════════════════════════════════

def fill_internal_holes(mask: np.ndarray, max_hole_size: int = 20_000) -> np.ndarray:
    """Rellena huecos internos completamente encerrados por la silueta.

    Un hueco es una región de fondo (0) que no toca el borde de la imagen
    y está rodeada por foreground (255).
    """
    arr = ensure_binary_mask(mask)
    h, w = arr.shape
    inverted = np.where(arr > 127, 0, 255).astype(np.uint8)
    try:
        import cv2
        flooded = inverted.copy()
        fm = np.zeros((h + 2, w + 2), np.uint8)
        for x in range(w):
            if flooded[0, x]:
                cv2.floodFill(flooded, fm, (x, 0), 128)
            if flooded[h - 1, x]:
                cv2.floodFill(flooded, fm, (x, h - 1), 128)
        for y in range(1, h - 1):
            if flooded[y, 0]:
                cv2.floodFill(flooded, fm, (0, y), 128)
            if flooded[y, w - 1]:
                cv2.floodFill(flooded, fm, (w - 1, y), 128)
        holes = (flooded == 255).astype(np.uint8)
        if max_hole_size > 0:
            num_labels, labels, stats, _ = find_connected_components(holes)
            result = arr.copy()
            for i in range(1, num_labels):
                if stats[i, 4] <= max_hole_size:
                    result[labels == i] = 255
            return result
        return np.where(holes > 0, 255, arr)
    except ImportError:
        from PIL import Image, ImageDraw
        pil_inv = to_pil_mask(inverted)
        for x in range(w):
            if pil_inv.getpixel((x, 0)) == 255:
                ImageDraw.floodfill(pil_inv, (x, 0), 128, thresh=0)
            if pil_inv.getpixel((x, h - 1)) == 255:
                ImageDraw.floodfill(pil_inv, (x, h - 1), 128, thresh=0)
        for y in range(h):
            if pil_inv.getpixel((0, y)) == 255:
                ImageDraw.floodfill(pil_inv, (0, y), 128, thresh=0)
            if pil_inv.getpixel((w - 1, y)) == 255:
                ImageDraw.floodfill(pil_inv, (w - 1, y), 128, thresh=0)
        return np.where(to_numpy(pil_inv) == 255, 255, arr)


def closed_interior_mask(alpha: Any) -> np.ndarray:
    """Devuelve una máscara de huecos internos cerrados."""
    arr = ensure_binary_mask(alpha)
    h, w = arr.shape
    inverted = np.where(arr > 127, 0, 255).astype(np.uint8)
    try:
        import cv2
        flooded = inverted.copy()
        fm = np.zeros((h + 2, w + 2), np.uint8)
        for x in range(w):
            if flooded[0, x]:
                cv2.floodFill(flooded, fm, (x, 0), 128)
            if flooded[h - 1, x]:
                cv2.floodFill(flooded, fm, (x, h - 1), 128)
        for y in range(1, h - 1):
            if flooded[y, 0]:
                cv2.floodFill(flooded, fm, (0, y), 128)
            if flooded[y, w - 1]:
                cv2.floodFill(flooded, fm, (w - 1, y), 128)
        return (flooded == 255).astype(np.uint8) * 255
    except ImportError:
        from PIL import Image, ImageDraw
        pil_inv = to_pil_mask(inverted)
        for x in range(w):
            if pil_inv.getpixel((x, 0)) == 255:
                ImageDraw.floodfill(pil_inv, (x, 0), 128, thresh=0)
            if pil_inv.getpixel((x, h - 1)) == 255:
                ImageDraw.floodfill(pil_inv, (x, h - 1), 128, thresh=0)
        for y in range(h):
            if pil_inv.getpixel((0, y)) == 255:
                ImageDraw.floodfill(pil_inv, (0, y), 128, thresh=0)
            if pil_inv.getpixel((w - 1, y)) == 255:
                ImageDraw.floodfill(pil_inv, (w - 1, y), 128, thresh=0)
                return to_numpy(pil_inv.point(lambda v: 255 if v == 255 else 0))


# ══════════════════════════════════════════════════════════════════════════════
# Aplicación de máscara a imágenes RGBA
# ══════════════════════════════════════════════════════════════════════════════

def apply_mask_to_rgba(rgba: Any, mask: np.ndarray) -> Any:
    """Aplica una máscara binaria al canal alpha de una imagen RGBA.

    Convención: 255 = conservar, 0 = eliminar.
    """
    from PIL import Image
    if not isinstance(rgba, Image.Image):
        rgba = Image.fromarray(to_numpy(rgba))
    result = rgba.convert("RGBA").copy()
    alpha = ensure_binary_mask(mask)
    result.putalpha(to_pil_mask(alpha))
    return result


def paste_color_on_mask(rgba: Any, mask: np.ndarray, color: tuple) -> Any:
    """Pega un color sobre la imagen donde la máscara es 255."""
    from PIL import Image
    if not isinstance(rgba, Image.Image):
        rgba = Image.fromarray(to_numpy(rgba))
    result = rgba.convert("RGBA").copy()
    pil_mask = to_pil_mask(ensure_binary_mask(mask))
    result.paste(color, mask=pil_mask)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Generación de bordes
# ══════════════════════════════════════════════════════════════════════════════

def generate_white_border(mask: np.ndarray, width: int = 30, dpi: int = 300) -> np.ndarray:
    """Genera un borde blanco alrededor del diseño.

    El borde se coloca en la capa de impresión: dilata la máscara
    y rellena la zona entre el diseño original y la dilatación.
    """
    if width <= 0:
        return ensure_binary_mask(mask)
    arr = ensure_binary_mask(mask)
    return dilate_mask(arr, width)


def generate_black_border(mask: np.ndarray, width: int = 2) -> np.ndarray:
    """Genera un borde negro de registro alrededor del diseño."""
    if width <= 0:
        return ensure_binary_mask(mask)
    arr = ensure_binary_mask(mask)
    dilated = dilate_mask(arr, width)
    border = (dilated > 127) & (arr <= 127)
    result = arr.copy()
    result[border] = 255
    return result


def build_white_inner_border(mask: np.ndarray, width: int = 10) -> np.ndarray:
    """Construye un borde blanco interno para cubrir tonos grises residuales."""
    return generate_white_border(mask, width)


# ══════════════════════════════════════════════════════════════════════════════
# Utilidades de recorte y redimensionamiento
# ══════════════════════════════════════════════════════════════════════════════

def crop_to_bbox(rgba: Any, mask: np.ndarray, inset: int = 0) -> Any:
    """Recorta la imagen al bounding box de la máscara, con margen opcional."""
    from PIL import Image
    if not isinstance(rgba, Image.Image):
        rgba = Image.fromarray(to_numpy(rgba))
    arr = ensure_binary_mask(mask)
    pil_mask = to_pil_mask(arr)
    bbox = pil_mask.getbbox()
    if bbox is None:
        return rgba
    if inset > 0:
        bbox = (
            max(0, bbox[0] - inset),
            max(0, bbox[1] - inset),
            min(rgba.width, bbox[2] + inset),
            min(rgba.height, bbox[3] + inset),
        )
    return rgba.crop(bbox)


def resize_to_pixels(rgba: Any, target_pixels: int) -> Any:
    """Redimensiona manteniendo proporción al cuadrado objetivo."""
    from PIL import Image
    if not isinstance(rgba, Image.Image):
        rgba = Image.fromarray(to_numpy(rgba))
    rgba.thumbnail((target_pixels, target_pixels), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (target_pixels, target_pixels), (0, 0, 0, 0))
    offset = ((target_pixels - rgba.width) // 2, (target_pixels - rgba.height) // 2)
    canvas.paste(rgba, offset)
    return canvas


def rotate_to_vertical(rgba: Any, mask: np.ndarray) -> tuple:
    """Rota la imagen 90° si el lado mayor es horizontal.

    Returns:
        (imagen_rotada, fue_rotada)
    """
    from PIL import Image
    if not isinstance(rgba, Image.Image):
        rgba = Image.fromarray(to_numpy(rgba))
    arr = ensure_binary_mask(mask)
    pil_mask = to_pil_mask(arr)
    bbox = pil_mask.getbbox()
    if bbox is None:
        return rgba, False
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    if w > h:
        return rgba.rotate(90, expand=True), True
    return rgba, False