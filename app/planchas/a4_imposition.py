"""Acoplado no destructivo de planchas Franjas/A5 en hojas A4."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


FORMAT_SLOTS = {"franja": 5, "a5": 2, "a4": 1}


@dataclass(frozen=True)
class A4Sheet:
    """Una hoja A4 propuesta, formada por planchas originales existentes."""

    format: str
    planchas: tuple[dict, ...]

    @property
    def label(self) -> str:
        labels = {"franja": "Franjas", "a5": "A5", "a4": "A4"}
        return f"{len(self.planchas)} {labels[self.format]} → A4"


def propose_a4_sheets(planchas: Iterable[dict]) -> tuple[list[A4Sheet], list[dict]]:
    """Propone hojas completas y devuelve aparte los formatos incompletos.

    No mezcla formatos: 5 Franjas, 2 A5 o una A4 por hoja. El material no
    participa del agrupado porque se define recién al imprimir.
    """
    groups = {key: [] for key in FORMAT_SLOTS}
    for plancha in planchas:
        key = str(plancha.get("workspace_format") or "a4").lower()
        groups.get(key, groups["a4"]).append(plancha)
    sheets: list[A4Sheet] = []
    pending: list[dict] = []
    for key in ("a4", "a5", "franja"):
        capacity = FORMAT_SLOTS[key]
        items = groups[key]
        for start in range(0, len(items), capacity):
            batch = items[start:start + capacity]
            if len(batch) == capacity:
                sheets.append(A4Sheet(key, tuple(batch)))
            else:
                pending.extend(batch)
    return sheets, pending


def render_a4_sheet(sheet: A4Sheet, output: str | Path, dpi: int = 300) -> Path:
    """Crea un PNG A4 compuesto recortando solo el área útil de cada origen."""
    from PIL import Image

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    width = round(21 / 2.54 * dpi)
    height = round(29.7 / 2.54 * dpi)
    page = Image.new("RGBA", (width, height), "white")
    slots = FORMAT_SLOTS[sheet.format]
    for index, plancha in enumerate(sheet.planchas):
        source_path = Path(plancha.get("final_png_path") or "")
        if not source_path.is_file():
            raise FileNotFoundError(f"No se encontró el PNG de «{plancha.get('name', 'plancha')}».")
        with Image.open(source_path) as source:
            image = source.convert("RGBA")
            # Cada PNG conserva el lienzo A4; la zona útil del formato está en
            # la parte superior y se recorta antes de acomodarla en la hoja.
            crop_height = max(1, round(image.height / slots))
            top = round(index * height / slots)
            bottom = round((index + 1) * height / slots)
            image = image.crop((0, 0, image.width, crop_height)).resize(
                (width, bottom - top), Image.Resampling.LANCZOS,
            )
        page.alpha_composite(image, (0, top))
    page.save(output, "PNG", dpi=(dpi, dpi), compress_level=3)
    return output
