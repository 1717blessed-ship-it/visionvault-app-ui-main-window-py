"""Adaptador de sólo lectura entre jobs legacy y la interfaz 2.0."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image
import shutil


@dataclass(frozen=True, slots=True)
class PreviewSource:
    path: str | None
    mask_path: str | None = None
    cut_path: str | None = None


class PipelineViewAdapter:
    """Normaliza rutas y métricas sin procesar ni reescribir artefactos."""

    @staticmethod
    def artifacts(job: dict) -> dict:
        result = job.get("result")
        return dict(getattr(result, "artifacts", {}) or {})

    @classmethod
    def preview_source(cls, job: dict, mode: str) -> PreviewSource:
        artifacts = cls.artifacts(job)
        original = job.get("source_path")
        mask = artifacts.get("mask_editable") or artifacts.get("mask")
        cut = job.get("cut_mask_override") or artifacts.get("cut")
        if mode == "Original":
            path = original
        elif mode == "Máscara":
            path = mask
        elif mode == "Resultado":
            path = artifacts.get("design_layer") or artifacts.get("source_editable") or original
        else:
            path = artifacts.get("master") or artifacts.get("print") or original
        return PreviewSource(path if path and Path(path).exists() else None, mask, cut)

    @classmethod
    def metrics(cls, job: dict, fallback_dpi: int = 300) -> dict:
        source = cls.preview_source(job, "Final").path or job.get("source_path")
        width = height = 0
        dpi_x = dpi_y = float(fallback_dpi)
        if source and Path(source).exists():
            with Image.open(source) as image:
                width, height = image.size
                raw_dpi = image.info.get("dpi") or (fallback_dpi, fallback_dpi)
                try:
                    dpi_x, dpi_y = float(raw_dpi[0]), float(raw_dpi[1])
                except (TypeError, ValueError, IndexError):
                    dpi_x = dpi_y = float(fallback_dpi)
        dpi_x = dpi_x if dpi_x > 1 else float(fallback_dpi)
        dpi_y = dpi_y if dpi_y > 1 else float(fallback_dpi)
        return {
            "pixels": (width, height),
            "millimeters": (width / dpi_x * 25.4, height / dpi_y * 25.4),
            "dpi": (dpi_x, dpi_y),
        }

    @staticmethod
    def export_final(source: str | Path, destination: str | Path) -> Path:
        """Copia byte a byte el master; no renderiza una vista ni cambia DPI."""
        source_path, destination_path = Path(source), Path(destination)
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        if destination_path.suffix.lower() != ".png":
            raise ValueError("La exportación final debe ser PNG.")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, destination_path)
        return destination_path
