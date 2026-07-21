"""Modelo no destructivo para el modo Plantilla regular.

Las casillas guardan solo una referencia a la imagen original y sus ajustes de
encuadre. Ninguna acción copia, mueve o renombra el archivo fuente.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


# Patrones regulares basados en A4 vertical. Cada caso replica los usos más
# comunes del taller: círculos grandes, retratos, piezas finas y formatos
# horizontales. Las celdas se calculan con el margen y la separación reales,
# nunca con porcentajes visuales aproximados.
REGULAR_PATTERNS: dict[str, dict[str, object]] = {
    "circular_4x5": {"title": "Circular / cuadrado", "detail": "4 columnas · 5 filas", "columns": 4, "rows": 5},
    "vertical_5x5": {"title": "Vertical estándar", "detail": "5 columnas · 5 filas", "columns": 5, "rows": 5},
    "vertical_6x5": {"title": "Vertical fino", "detail": "6 columnas · 5 filas", "columns": 6, "rows": 5},
    "vertical_8x5": {"title": "Vertical extra fino", "detail": "8 columnas · 5 filas", "columns": 8, "rows": 5},
    "retrato_7x8": {"title": "Retrato compacto", "detail": "7 columnas · 8 filas", "columns": 7, "rows": 8},
    "horizontal_3x5": {"title": "Horizontal", "detail": "3 columnas · 5 filas", "columns": 3, "rows": 5},
    "panoramico_2x5": {"title": "Panorámico", "detail": "2 columnas · 5 filas", "columns": 2, "rows": 5},
}

A4_WIDTH_CM = 21.0
A4_HEIGHT_CM = 29.7
# Las planchas regulares reservan un poco más de tolerancia que las libres.
# Es una protección física para el desvío del plotter, no un margen visual.
REGULAR_MARGIN_CM = 0.20
REGULAR_GAP_CM = 0.08


@dataclass
class TemplateResource:
    path: str
    name: str
    width_px: int = 0
    height_px: int = 0
    modified: float = 0.0
    resource_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TemplateResource":
        return cls(**data)


@dataclass
class TemplateCell:
    x: float
    y: float
    width: float
    height: float
    cell_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    resource_id: str | None = None
    frame_mode: str = "Rellenar"
    zoom: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    rotation: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TemplateCell":
        return cls(**data)


class RegularTemplateProject:
    """Plantilla editable formada por casillas y referencias compartidas."""

    VERSION = 2

    def __init__(self, cells: list[TemplateCell] | None = None, resources: list[TemplateResource] | None = None,
                 name: str = "Plantilla regular", pattern_id: str = "circular_4x5"):
        self.name = name
        self.pattern_id = pattern_id if pattern_id in REGULAR_PATTERNS else "circular_4x5"
        self.cells = cells if cells is not None else self.pattern_cells(self.pattern_id)
        self.resources = resources or []
        self.modified = ""

    @staticmethod
    def test_cells(rows: int = 5, columns: int = 4) -> list[TemplateCell]:
        """Compatibilidad con plantillas anteriores, usando medidas reales A4."""
        return RegularTemplateProject.cells_for(rows, columns)

    @staticmethod
    def cells_for(rows: int, columns: int, margin_cm: float = REGULAR_MARGIN_CM,
                  gap_cm: float = REGULAR_GAP_CM) -> list[TemplateCell]:
        """Crea una grilla que ocupa todo el rango imprimible de A4.

        La cuenta usa 21 × 29,7 cm, margen de seguridad de 0,20 cm y una
        separación de 0,08 cm. Así la última celda llega exactamente al
        límite seguro sin recortes ni franjas ocultas.
        """
        usable_width = A4_WIDTH_CM - margin_cm * 2 - gap_cm * (columns - 1)
        usable_height = A4_HEIGHT_CM - margin_cm * 2 - gap_cm * (rows - 1)
        cell_width_cm = usable_width / columns
        cell_height_cm = usable_height / rows
        return [
            TemplateCell(
                x=(margin_cm + column * (cell_width_cm + gap_cm)) / A4_WIDTH_CM,
                y=(margin_cm + row * (cell_height_cm + gap_cm)) / A4_HEIGHT_CM,
                width=cell_width_cm / A4_WIDTH_CM,
                height=cell_height_cm / A4_HEIGHT_CM,
            )
            for row in range(rows)
            for column in range(columns)
        ]

    @classmethod
    def pattern_cells(cls, pattern_id: str) -> list[TemplateCell]:
        pattern = REGULAR_PATTERNS.get(pattern_id, REGULAR_PATTERNS["circular_4x5"])
        return cls.cells_for(int(pattern["rows"]), int(pattern["columns"]))

    @staticmethod
    def cell_ratio(pattern_id: str) -> float:
        pattern = REGULAR_PATTERNS.get(pattern_id, REGULAR_PATTERNS["circular_4x5"])
        columns, rows = int(pattern["columns"]), int(pattern["rows"])
        width = (A4_WIDTH_CM - REGULAR_MARGIN_CM * 2 - REGULAR_GAP_CM * (columns - 1)) / columns
        height = (A4_HEIGHT_CM - REGULAR_MARGIN_CM * 2 - REGULAR_GAP_CM * (rows - 1)) / rows
        return width / height

    @classmethod
    def recommended_pattern_report(cls, resources: list[TemplateResource]) -> dict[str, object]:
        """Propone un patrón y explica la confianza sin aplicarlo solo."""
        ratios = [resource.width_px / resource.height_px for resource in resources if resource.width_px and resource.height_px]
        if not ratios:
            return {"pattern_id": "circular_4x5", "confidence": 0.0, "auto_suitable": False,
                    "reason": "No hay medidas suficientes para comparar los diseños."}
        ratios.sort()
        ratio = ratios[len(ratios) // 2]
        ranked = sorted(
            (abs(math.log(max(0.01, ratio) / cls.cell_ratio(pattern_id))), pattern_id)
            for pattern_id in REGULAR_PATTERNS
        )
        best_distance, pattern_id = ranked[0]
        second_distance = ranked[1][0] if len(ranked) > 1 else best_distance + 1.0
        dispersion = max(abs(math.log(max(0.01, value) / ratio)) for value in ratios)
        separation = max(0.0, second_distance - best_distance)
        confidence = max(0.0, min(1.0, (separation / (second_distance + 0.08)) / (1.0 + dispersion * 2.5)))
        auto_suitable = confidence >= 0.72 and dispersion <= 0.18
        return {
            "pattern_id": pattern_id, "confidence": round(confidence, 3),
            "auto_suitable": auto_suitable, "dispersion": round(dispersion, 3),
            "reason": ("Las proporciones son homogéneas y coinciden claramente con este patrón."
                       if auto_suitable else
                       "Hay proporciones mixtas o dos patrones con un ajuste parecido; conviene revisarlo."),
        }

    @classmethod
    def recommended_pattern(cls, resources: list[TemplateResource]) -> str:
        """Compatibilidad: devuelve solo el identificador de la propuesta."""
        return str(cls.recommended_pattern_report(resources)["pattern_id"])

    @classmethod
    def from_images(cls, images: list[dict], apply_recommendation: bool = True) -> "RegularTemplateProject":
        project = cls(cells=[], resources=[])
        for image in images:
            path = image.get("path", "")
            if path:
                project.add_resource(path, image.get("name"))
        if apply_recommendation:
            project.pattern_id = project.recommended_pattern(project.resources)
        project.cells = project.pattern_cells(project.pattern_id)
        project.assign_resources_to_pattern()
        return project

    def resource(self, resource_id: str | None) -> TemplateResource | None:
        return next((item for item in self.resources if item.resource_id == resource_id), None)

    def cell(self, cell_id: str | None) -> TemplateCell | None:
        return next((item for item in self.cells if item.cell_id == cell_id), None)

    def add_resource(self, path: str, name: str | None = None) -> TemplateResource:
        source = Path(path)
        normalized = str(source)
        existing = next((item for item in self.resources if item.path.casefold() == normalized.casefold()), None)
        if existing:
            return existing
        width = height = 0
        modified = 0.0
        try:
            modified = source.stat().st_mtime
            from PIL import Image
            with Image.open(source) as image:
                width, height = image.size
        except Exception:
            pass
        resource = TemplateResource(
            path=normalized,
            name=name or source.name,
            width_px=width,
            height_px=height,
            modified=modified,
        )
        self.resources.append(resource)
        return resource

    def usage_count(self, resource_id: str) -> int:
        return sum(cell.resource_id == resource_id for cell in self.cells)

    def assign(self, cell_ids: set[str], resource_id: str) -> None:
        for cell in self.cells:
            if cell.cell_id in cell_ids:
                cell.resource_id = resource_id
                cell.frame_mode = "Rellenar"
                cell.zoom = 1.0
                cell.offset_x = cell.offset_y = 0.0
                cell.rotation = 0

    @property
    def pattern(self) -> dict[str, object]:
        return REGULAR_PATTERNS.get(self.pattern_id, REGULAR_PATTERNS["circular_4x5"])

    def apply_pattern(self, pattern_id: str, preserve_content: bool = True) -> None:
        """Cambia el patrón sin perder los recursos ni los archivos originales."""
        if pattern_id not in REGULAR_PATTERNS:
            raise ValueError("El patrón elegido no existe.")
        previous = [cell.resource_id for cell in self.cells if cell.resource_id]
        self.pattern_id = pattern_id
        self.cells = self.pattern_cells(pattern_id)
        if preserve_content and previous:
            for index, cell in enumerate(self.cells):
                cell.resource_id = previous[index % len(previous)]
                cell.frame_mode = "Ajustar"
        elif self.resources:
            self.assign_resources_to_pattern()

    def assign_resources_to_pattern(self) -> None:
        """Completa el patrón en cadena con los recursos del trabajo.

        Si hay un único diseño, se repite en todas las casillas. Si hay varios,
        alternan en el orden recibido para no dejar sectores vacíos.
        """
        if not self.resources:
            return
        resource_ids = [resource.resource_id for resource in self.resources]
        for index, cell in enumerate(self.cells):
            cell.resource_id = resource_ids[index % len(resource_ids)]
            cell.frame_mode = "Ajustar"
            cell.zoom = 1.0
            cell.offset_x = cell.offset_y = 0.0
            cell.rotation = 0

    def to_free_project(self):
        """Convierte las casillas ocupadas a un proyecto libre, sin reescalar.

        Las hitboxes se copian con las medidas físicas exactas de las casillas.
        El editor libre conserva la ubicación; a partir de ahí el operario puede
        mover o ajustar cada diseño sin que se modifique el original.
        """
        from app.planchas.model import PlanchaItem, PlanchaProject

        items: list[PlanchaItem] = []
        for position, cell in enumerate(self.cells, start=1):
            resource = self.resource(cell.resource_id)
            if not resource:
                continue
            items.append(
                PlanchaItem(
                    path=resource.path,
                    name=resource.name,
                    # La conversión conserva exactamente la geometría física.
                    width_cm=cell.width * A4_WIDTH_CM,
                    height_cm=cell.height * A4_HEIGHT_CM,
                    x_cm=cell.x * A4_WIDTH_CM,
                    y_cm=cell.y * A4_HEIGHT_CM,
                    rotation=cell.rotation,
                    source="Plancha regular",
                    copy_number=position,
                    quantity=1,
                )
            )
        return PlanchaProject(items, margin_cm=REGULAR_MARGIN_CM, gap_cm=REGULAR_GAP_CM)

    def clear(self, cell_ids: set[str]) -> None:
        for cell in self.cells:
            if cell.cell_id in cell_ids:
                cell.resource_id = None
                cell.zoom = 1.0
                cell.offset_x = cell.offset_y = 0.0
                cell.rotation = 0

    def to_dict(self) -> dict:
        return {
            "version": self.VERSION,
            "mode": "Plantilla regular",
            "name": self.name,
            "pattern_id": self.pattern_id,
            "resources": [item.to_dict() for item in self.resources],
            "cells": [item.to_dict() for item in self.cells],
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "RegularTemplateProject":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("mode") != "Plantilla regular":
            raise ValueError("El archivo no es un proyecto de Plantilla regular.")
        return cls(
            cells=[TemplateCell.from_dict(item) for item in data.get("cells", [])],
            resources=[TemplateResource.from_dict(item) for item in data.get("resources", [])],
            name=data.get("name", "Plantilla de prueba"),
            pattern_id=data.get("pattern_id", "circular_4x5"),
        )
