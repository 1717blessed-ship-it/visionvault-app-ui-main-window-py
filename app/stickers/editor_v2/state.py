"""Estado de sesión independiente de los artefactos del pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


VIEW_MODES = ("Original", "Máscara", "Resultado", "Final")


@dataclass(slots=True)
class CanvasState:
    mode: str = "Final"
    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0
    fitted: bool = True
    show_cut: bool = False
    compare: bool = False

    def set_zoom(self, value: float) -> float:
        self.zoom = max(0.05, min(16.0, float(value)))
        self.fitted = False
        return self.zoom


@dataclass
class StudioSessionState:
    """Conserva navegación por trabajo sin modificar imágenes ni resultados."""

    views: dict[str, CanvasState] = field(default_factory=dict)
    selected_key: str | None = None

    @staticmethod
    def job_key(job: dict, index: int = 0) -> str:
        # El source_path es estable durante reprocesamientos. El sufijo sólo
        # distingue trabajos derivados que compartan el mismo original.
        source = str(Path(job.get("source_path", "")).resolve())
        child = job.get("parent_object_id", "root")
        return f"{source}::{child}::{index if not source else ''}"

    def select(self, job: dict, index: int = 0) -> CanvasState:
        key = self.job_key(job, index)
        self.selected_key = key
        return self.views.setdefault(key, CanvasState())

    def current(self) -> CanvasState:
        if self.selected_key is None:
            return CanvasState()
        return self.views.setdefault(self.selected_key, CanvasState())

    def discard_missing(self, jobs: list[dict]) -> None:
        valid = {self.job_key(job, index) for index, job in enumerate(jobs)}
        self.views = {key: value for key, value in self.views.items() if key in valid}
        if self.selected_key not in valid:
            self.selected_key = None
