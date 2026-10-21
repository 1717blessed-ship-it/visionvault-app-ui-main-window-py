"""Edición no destructiva y persistente de máscaras alfa."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .mask_contraction import offset_alpha_signed_distance


EDIT_TOOLS = {"restore", "erase", "protect", "refine"}


@dataclass(frozen=True)
class MaskStroke:
    tool: str
    points: tuple[tuple[float, float], ...]
    size_px: float
    hardness: float = 1.0
    opacity: float = 1.0

    def __post_init__(self):
        if self.tool not in EDIT_TOOLS:
            raise ValueError(f"Herramienta de máscara desconocida: {self.tool}")
        if not self.points or self.size_px <= 0:
            raise ValueError("El trazo requiere puntos y un tamaño positivo.")
        if not 0 <= self.hardness <= 1 or not 0 <= self.opacity <= 1:
            raise ValueError("Dureza y opacidad deben estar entre 0 y 1.")

    @classmethod
    def from_dict(cls, value):
        return cls(value["tool"], tuple(tuple(map(float, p)) for p in value["points"]),
                   float(value["size_px"]), float(value.get("hardness", 1)),
                   float(value.get("opacity", 1)))


@dataclass
class MaskEditDocument:
    width: int
    height: int
    base_sha256: str
    operations: list[MaskStroke] = field(default_factory=list)
    redo_operations: list[MaskStroke] = field(default_factory=list)
    version: int = 1

    @classmethod
    def for_base(cls, alpha: Image.Image):
        source = alpha.convert("L")
        return cls(source.width, source.height, sha256(source.tobytes()).hexdigest())

    def compatible(self, alpha: Image.Image) -> bool:
        source = alpha.convert("L")
        return (source.size == (self.width, self.height)
                and sha256(source.tobytes()).hexdigest() == self.base_sha256)

    def add(self, stroke: MaskStroke):
        self.operations.append(stroke)
        self.redo_operations.clear()

    def undo(self) -> bool:
        if not self.operations:
            return False
        self.redo_operations.append(self.operations.pop())
        return True

    def redo(self) -> bool:
        if not self.redo_operations:
            return False
        self.operations.append(self.redo_operations.pop())
        return True

    def reset(self):
        self.operations.clear()
        self.redo_operations.clear()

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        payload["operations"] = [MaskStroke.from_dict(v) for v in payload.get("operations", [])]
        payload["redo_operations"] = [MaskStroke.from_dict(v) for v in payload.get("redo_operations", [])]
        return cls(**payload)

    def render_manual(self, base: Image.Image) -> tuple[Image.Image, Image.Image]:
        source = base.convert("L")
        if not self.compatible(source):
            raise ValueError("La máscara base cambió; las correcciones no pueden aplicarse con seguridad.")
        alpha = np.asarray(source, dtype=np.float32).copy()
        protected = np.zeros((self.height, self.width), dtype=np.float32)
        for stroke in self.operations:
            coverage = _stroke_coverage(source.size, stroke)
            amount = coverage * stroke.opacity
            if stroke.tool == "protect":
                protected = np.maximum(protected, amount)
            elif stroke.tool == "restore":
                alpha += (255.0 - alpha) * amount
            elif stroke.tool == "erase":
                alpha *= 1.0 - amount
            else:
                smooth = cv2.GaussianBlur(alpha, (0, 0), max(.35, stroke.size_px / 8))
                alpha = alpha * (1.0 - amount) + smooth * amount
        return (Image.fromarray(np.rint(np.clip(alpha, 0, 255)).astype(np.uint8), "L"),
                Image.fromarray(np.rint(protected * 255).astype(np.uint8), "L"))

    def render(self, base: Image.Image, offset_mm: float, dpi: float,
               smoothing_mm: float = .08):
        manual, protection = self.render_manual(base)
        adjusted, report = offset_alpha_signed_distance(manual, offset_mm, dpi, smoothing_mm)
        if abs(offset_mm) > 1e-9:
            p = np.asarray(protection, dtype=np.float32) / 255.0
            a = np.asarray(adjusted, dtype=np.float32)
            m = np.asarray(manual, dtype=np.float32)
            adjusted = Image.fromarray(np.rint(a * (1-p) + m * p).astype(np.uint8), "L")
        return adjusted, protection, report


def _stroke_coverage(size: tuple[int, int], stroke: MaskStroke) -> np.ndarray:
    scale = 4
    mask = Image.new("L", (size[0] * scale, size[1] * scale), 0)
    draw = ImageDraw.Draw(mask)
    points = [(round(x * scale), round(y * scale)) for x, y in stroke.points]
    width = max(1, round(stroke.size_px * scale))
    if len(points) == 1:
        x, y = points[0]
        radius = width / 2
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=255)
    else:
        draw.line(points, fill=255, width=width, joint="curve")
        radius = width / 2
        for x, y in (points[0], points[-1]):
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=255)
    mask = mask.resize(size, Image.Resampling.LANCZOS)
    if stroke.hardness < 1:
        radius = max(.01, stroke.size_px * (1-stroke.hardness) / 2)
        mask = mask.filter(ImageFilter.GaussianBlur(radius))
    return np.asarray(mask, dtype=np.float32) / 255.0


def save_approved_reference(mask: Image.Image, source_path: str | Path,
                            destination: str | Path, approved_by: str = "usuario") -> dict:
    """Guarda una referencia sólo como consecuencia de aprobación explícita UI."""
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    alpha = mask.convert("L")
    alpha.save(target)
    source = Path(source_path)
    manifest = {
        "approved": True, "approved_by": approved_by,
        "source_path": str(source.resolve()),
        "source_sha256": sha256(source.read_bytes()).hexdigest(),
        "mask_path": str(target.resolve()),
        "mask_sha256": sha256(target.read_bytes()).hexdigest(),
        "dimensions": list(alpha.size),
    }
    manifest_path = target.with_suffix(".approval.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def compare_masks(automatic: Image.Image, reference: Image.Image,
                  output_path: str | Path | None = None) -> dict:
    """Compara geometría, borde y alfa; opcionalmente guarda evidencia ampliada."""
    auto = np.asarray(automatic.convert("L"), dtype=np.uint8)
    ref_image = reference.convert("L")
    if ref_image.size != automatic.size:
        raise ValueError("La referencia debe coincidir exactamente con la máscara automática.")
    ref = np.asarray(ref_image, dtype=np.uint8)
    a, r = auto > 127, ref > 127
    intersection, union = int((a & r).sum()), int((a | r).sum())
    components = lambda value: max(0, cv2.connectedComponents(
        value.astype(np.uint8), connectivity=8)[0]-1)
    edge_a = cv2.morphologyEx(a.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 0
    edge_r = cv2.morphologyEx(r.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 0
    metrics = {
        "iou": intersection / max(1, union),
        "different_pixels": int(np.count_nonzero(auto != ref)),
        "alpha_mae": float(np.abs(auto.astype(np.int16)-ref.astype(np.int16)).mean()),
        "automatic_area_px": int(a.sum()), "reference_area_px": int(r.sum()),
        "lost_detail_pixels": int((a & ~r).sum()),
        "restored_detail_pixels": int((r & ~a).sum()),
        "automatic_components": components(a), "reference_components": components(r),
        "boundary_different_pixels": int(np.count_nonzero(edge_a ^ edge_r)),
    }
    if output_path:
        target = Path(output_path); target.parent.mkdir(parents=True, exist_ok=True)
        scale = 3
        panels = [Image.fromarray(auto, "L").convert("RGB"), ref_image.convert("RGB")]
        diff = Image.new("RGB", automatic.size, "black")
        pixels = np.zeros((auto.shape[0], auto.shape[1], 3), dtype=np.uint8)
        pixels[a & ~r] = (255, 50, 50)
        pixels[r & ~a] = (50, 220, 255)
        pixels[a & r] = (235, 235, 235)
        diff = Image.fromarray(pixels, "RGB")
        panels.append(diff)
        sheet = Image.new("RGB", (automatic.width*len(panels)*scale, automatic.height*scale), "white")
        for index, panel in enumerate(panels):
            sheet.paste(panel.resize((automatic.width*scale, automatic.height*scale), Image.Resampling.NEAREST),
                        (index*automatic.width*scale, 0))
        sheet.save(target)
        metrics["visual_comparison"] = str(target)
        metrics_path = target.with_suffix(".json")
        metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        metrics["metrics_path"] = str(metrics_path)
    return metrics
