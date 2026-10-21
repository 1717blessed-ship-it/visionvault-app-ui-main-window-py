"""Variaciones cromáticas sutiles para stickers demasiado parecidos."""

from __future__ import annotations

from pathlib import Path


def apply_subtle_color_variant(path: str | Path, hue_shift: int = 4) -> int:
    """Desplaza levemente el tono de las zonas de color de un PNG.

    El blanco del borde, grises, negros y transparencia se conservan. Devuelve
    la cantidad de píxeles modificados para poder auditar la acción.
    """
    from PIL import Image
    import numpy as np

    target = Path(path)
    with Image.open(target) as source:
        image = source.convert("RGBA")
        dpi = source.info.get("dpi", (300, 300))

    rgba = np.asarray(image, dtype=np.uint8).copy()
    rgb = rgba[:, :, :3]
    alpha = rgba[:, :, 3]
    maximum = rgb.max(axis=2).astype(np.int16)
    minimum = rgb.min(axis=2).astype(np.int16)
    saturated = (maximum - minimum >= 36) & (maximum >= 70) & (alpha >= 200)
    if not saturated.any():
        return 0

    hsv = np.asarray(Image.fromarray(rgb, mode="RGB").convert("HSV"), dtype=np.uint8).copy()
    hsv[:, :, 0][saturated] = (hsv[:, :, 0][saturated].astype(np.int16) + hue_shift) % 256
    recolored = np.asarray(Image.fromarray(hsv, mode="HSV").convert("RGB"), dtype=np.uint8)
    rgb[saturated] = recolored[saturated]
    Image.fromarray(rgba, mode="RGBA").save(target, dpi=dpi, optimize=False)
    return int(saturated.sum())
