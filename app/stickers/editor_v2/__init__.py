"""Interfaz 2.0 del creador de stickers.

La implementación es deliberadamente una capa de presentación: el editor
clásico continúa siendo la fuente de los comandos y del pipeline A/B/C/D.
"""

from .window import StickerStudioV2

__all__ = ["StickerStudioV2"]
