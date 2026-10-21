"""Validación de artefactos de producción; separa errores de indicios."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import cv2
import numpy as np


@dataclass
class QualityReport:
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def status(self):
        return "ERROR" if self.errors else "REVISAR" if self.warnings else "APROBADO"

    def to_dict(self):
        return {**asdict(self), "status": self.status, "version": 1}


def validate_sticker(*, design_alpha, master, cut_mask, expected_pixels,
                     dpi, target_cm, source_size, expect_transparency=True,
                     reference_alpha=None, intentional_components=False,
                     manual_mask=False, source_content_size=None,
                     target_content_size=None, printable_base=None):
    """Las sospechas no impiden aprobar; solo los errores técnicos bloquean.

    No presupone que los huecos o las piezas desconectadas sean defectos.
    La comparación de superficie solo es válida entre máscaras alineadas.
    """
    report = QualityReport()
    alpha = np.asarray(design_alpha.convert("L"), dtype=np.uint8)
    final_alpha = np.asarray(master.getchannel("A"), dtype=np.uint8)
    cut = np.asarray(cut_mask.convert("L"), dtype=np.uint8)
    foreground = (alpha > 12).astype(np.uint8)
    def issue(bucket, code, message):
        bucket.append({"code": code, "message": message})
    if not foreground.any():
        issue(report.errors, "empty_design", "La máscara del diseño está vacía. Corregí la silueta.")
    if not (final_alpha > 0).any():
        issue(report.errors, "empty_master", "El maestro está vacío.")
    if expect_transparency and final_alpha.min() == 255:
        issue(report.errors, "opaque_master", "El maestro perdió el margen transparente.")
    if master.size != (expected_pixels, expected_pixels):
        issue(report.errors, "master_dimensions", "Las dimensiones del maestro no corresponden al perfil.")
    if cut_mask.size != master.size:
        issue(report.errors, "cut_dimensions", "El troquel y el maestro tienen dimensiones diferentes.")
    if printable_base is not None and printable_base.size == cut_mask.size:
        base = (np.asarray(printable_base.convert("L")) > 127).astype(np.uint8)
        # One raster pixel of tolerance, not a physical recalibration.
        supported = cv2.dilate(base, np.ones((3, 3), dtype=np.uint8)) > 0
        outside = (cut > 127) & ~supported
        report.metrics["manual_cut_outside_base_px"] = int(outside.sum())
        if outside.any():
            issue(report.errors, "cut_outside_base", "El corte manual sale de la base imprimible. Corregí el corte antes de confirmar.")
    if dpi <= 0 or abs(expected_pixels / max(dpi, 1) * 2.54 - target_cm) > 2.54 / max(dpi, 1):
        issue(report.errors, "physical_dimensions", "El tamaño físico y la resolución son incompatibles.")
    contours, _ = cv2.findContours((cut > 127).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    valid = [c for c in contours if len(c) >= 3 and cv2.contourArea(c) > 1]
    if not valid or len(valid) != len(contours):
        issue(report.errors, "degenerate_cut", "El troquel contiene un contorno vacío o degenerado.")
    # El formato de corte actual es raster: findContours genera ciclos
    # cerrados. No se afirman validaciones de autointersecciones vectoriales.
    count, _, stats, _ = cv2.connectedComponentsWithStats(foreground, connectivity=8)
    areas = sorted((int(v) for v in stats[1:, cv2.CC_STAT_AREA]), reverse=True)
    if len(areas) > 1 and not intentional_components:
        small = sum(area for area in areas[1:] if area < max(24, areas[0] * .005))
        if small:
            issue(report.warnings, "small_components", "Hay piezas pequeñas separadas; verificá si pertenecen al diseño.")
    effective_dpi = None
    if source_content_size is not None and target_content_size is not None:
        scale = max(target_content_size) / max(max(source_content_size), 1)
        effective_dpi = dpi / max(scale, 1e-12)
        insufficient = scale > 1.001
    else:
        insufficient = min(source_size) < expected_pixels * .5
    if insufficient:
        issue(report.warnings, "low_resolution", "La fuente tiene poca resolución para el tamaño solicitado.")
    loss = None
    if reference_alpha is not None and reference_alpha.size == design_alpha.size:
        reference = np.asarray(reference_alpha.convert("L")) > 12
        if reference.any():
            loss = float((reference & ~foreground.astype(bool)).sum() / reference.sum())
            if loss > .25 and not manual_mask:
                issue(report.warnings, "surface_loss", "Se perdió más del 25 % de la superficie de referencia; revisá la silueta.")
    report.metrics.update(
        design_area_px=int(foreground.sum()), component_count=count - 1,
        partial_alpha_px=int(((alpha > 0) & (alpha < 255)).sum()),
        cut_contours=len(valid), reference_surface_loss=loss,
        physical_size_cm=round(expected_pixels / max(dpi, 1) * 2.54, 4),
        effective_content_dpi=effective_dpi,
    )
    return report
