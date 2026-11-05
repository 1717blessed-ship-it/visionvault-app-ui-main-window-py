"""Recuperación acotada sobre la extracción existente, sin cambiar intención."""
from PIL import Image
import numpy as np


FIXABLE_CODES = {"small_components", "surface_loss", "pipeline_review"}


def recovery_allowed(result, options):
    # Replaying the same extraction as a manual alpha cannot resolve a variable
    # background. It would only hide its source-context warning and look better.
    if result.analysis.get("complex_background_unresolved"):
        return False
    if result.analysis.get("grey_halo_review", {}).get("requires_review"):
        return False  # Replaying alpha cannot certify an ambiguous exterior halo.
    if (options.get("mask_override") or options.get("cut_mask_override")
            or options.get("preserve_full_image") or options.get("selected_component_ids")
            or options.get("creation_mode") in {"Sticker de imagen completa", "Sticker de múltiples objetos"}
            or options.get("approved_result")
            or result.status in {"Aprobado", "Confirmado", "Exportado"}):
        return False
    features = result.analysis.get("classification_features", {})
    if features.get("real_transparency"):
        return False
    report = result.analysis.get("quality_report", {})
    issues = report.get("errors", []) + report.get("warnings", [])
    # La falta de resolución no mejora repitiendo segmentación.
    return any(item.get("code") in FIXABLE_CODES and (
        item.get("code") != "pipeline_review"
        or any(word in item.get("message", "").lower() for word in ("borde blanco", "componente")))
        for item in issues)


def compare_recovery(primary, alternative):
    """Solo selecciona automáticamente mejoras casi equivalentes de silueta."""
    with Image.open(primary.artifacts["mask_editable"]) as first, Image.open(alternative.artifacts["mask_editable"]) as second:
        if first.size != second.size:
            return {"select_alternative": False, "reason": "coordinate_mismatch"}
        a = np.asarray(first.convert("L")) > 12
        b = np.asarray(second.convert("L")) > 12
    intersection = int((a & b).sum())
    union = int((a | b).sum())
    overlap = intersection / max(union, 1)
    area_ratio = int(b.sum()) / max(int(a.sum()), 1)
    old = primary.analysis.get("quality_report", {})
    new = alternative.analysis.get("quality_report", {})
    def severity(report):
        return (len(report.get("errors", [])), len(report.get("warnings", [])))
    improved = severity(new) < severity(old)
    safe = overlap >= .985 and .97 <= area_ratio <= 1.03 and not new.get("errors")
    return {"select_alternative": bool(improved and safe), "iou": overlap,
            "area_ratio": area_ratio, "improved": improved,
            "reason": "equivalent_improvement" if improved and safe else "manual_comparison_required"}
