"""Bloques de sublimación para las pruebas de alimentación continua.

Este módulo no modifica el flujo histórico de ``ContinuousProduction``.  Un
bloque es una página personalizada para el driver: mide 210 mm de ancho y
1188 mm de largo por omisión (cuatro A4); puede extenderse hasta 1200 mm.
Las secciones se posicionan con bordes de píxel compartidos: no se añade una
línea, margen ni espacio entre ellas.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


ROLL_WIDTH_MM = 210
DEFAULT_BLOCK_LENGTH_MM = 1188
MAX_BLOCK_LENGTH_MM = 1200
SECTION_LENGTH_MM = 297
PRINT_DPI = 300
MAX_SECTIONS_PER_BLOCK = DEFAULT_BLOCK_LENGTH_MM // SECTION_LENGTH_MM


def mm_to_pixels(mm: float, dpi: int = PRINT_DPI) -> int:
    """Convierte una medida física a píxeles, con un único redondeo final."""
    return round(float(mm) / 25.4 * int(dpi))


@dataclass(frozen=True)
class ExperimentalRollBlock:
    """Descripción inmutable de un bloque antes de renderizarlo."""

    paths: tuple[str, ...]
    length_mm: int = DEFAULT_BLOCK_LENGTH_MM

    def __post_init__(self) -> None:
        if not self.paths:
            raise ValueError("El bloque necesita al menos una plancha A4.")
        if len(self.paths) > MAX_SECTIONS_PER_BLOCK:
            raise ValueError(f"Un bloque admite hasta {MAX_SECTIONS_PER_BLOCK} planchas A4.")
        if not DEFAULT_BLOCK_LENGTH_MM <= int(self.length_mm) <= MAX_BLOCK_LENGTH_MM:
            raise ValueError(
                f"El largo experimental debe estar entre {DEFAULT_BLOCK_LENGTH_MM} y {MAX_BLOCK_LENGTH_MM} mm."
            )

    @property
    def pixel_size(self) -> tuple[int, int]:
        return mm_to_pixels(ROLL_WIDTH_MM), mm_to_pixels(self.length_mm)


def make_roll_blocks(paths: Iterable[str | Path], length_mm: int = DEFAULT_BLOCK_LENGTH_MM) -> list[ExperimentalRollBlock]:
    """Parte una lista ordenada de A4 en bloques, preservando su orden."""
    normalized = tuple(str(Path(path)) for path in paths)
    return [
        ExperimentalRollBlock(normalized[index:index + MAX_SECTIONS_PER_BLOCK], length_mm)
        for index in range(0, len(normalized), MAX_SECTIONS_PER_BLOCK)
    ]


def render_roll_block(block: ExperimentalRollBlock, output: str | Path) -> Path:
    """Renderiza un bloque con secciones contiguas, sin separadores artificiales.

    Las coordenadas de inicio y fin se calculan desde el largo total. Esto
    evita que el redondeo por cada A4 produzca una fila vacía o superpuesta.
    El remanente opcional (12 mm como máximo) queda únicamente al final del
    bloque, nunca entre planchas.
    """
    from PIL import Image

    output = Path(output)
    width, height = block.pixel_size
    section_count = len(block.paths)
    content_height = min(height, mm_to_pixels(section_count * SECTION_LENGTH_MM))
    canvas = Image.new("RGBA", (width, height), (255, 255, 255, 255))

    for index, source_path in enumerate(block.paths):
        start = round(index * content_height / section_count)
        end = round((index + 1) * content_height / section_count)
        with Image.open(source_path) as source:
            section = source.convert("RGBA").resize((width, end - start), Image.Resampling.LANCZOS)
        canvas.alpha_composite(section, (0, start))

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, "PNG", dpi=(PRINT_DPI, PRINT_DPI), compress_level=3)
    return output


def validate_roll_block_png(path: str | Path) -> tuple[bool, str]:
    """Comprueba que el PNG pueda enviarse como bloque experimental."""
    from PIL import Image

    path = Path(path)
    if not path.exists():
        return False, "El archivo del bloque no existe."
    try:
        with Image.open(path) as image:
            width, height = image.size
            dpi = image.info.get("dpi", (0, 0))
    except Exception:
        return False, "El archivo del bloque no se puede leer."
    expected_width = mm_to_pixels(ROLL_WIDTH_MM)
    min_height = mm_to_pixels(DEFAULT_BLOCK_LENGTH_MM)
    max_height = mm_to_pixels(MAX_BLOCK_LENGTH_MM)
    if width != expected_width or not min_height <= height <= max_height:
        return False, "El bloque debe medir 210 × 1188–1200 mm a 300 DPI."
    if not dpi or abs(float(dpi[0]) - PRINT_DPI) > 2 or abs(float(dpi[1]) - PRINT_DPI) > 2:
        return False, "El bloque no conserva la resolución de 300 DPI."
    return True, "Bloque experimental validado."
