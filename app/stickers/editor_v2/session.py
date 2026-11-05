"""Estado operativo persistente de Sticker Studio V2."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


DISPLAY_STATUS = {
    "Pendiente": "Pendiente", "Reprocesar": "Pendiente",
    "Procesando": "Procesando", "Procesado": "Requiere revisión",
    "Confirmado": "Aprobado", "Exportado": "Exportado",
    "Error": "Error", "Cancelado": "Cancelado", "Rechazado": "Rechazado",
}
REMOVABLE_CLEAN_STATES = {"Confirmado", "Exportado", "Error", "Cancelado", "Rechazado"}


@dataclass
class TraySelection:
    indices: set[int] = field(default_factory=set)
    anchor: int | None = None

    def click(self, index: int, *, ctrl=False, shift=False, count: int | None = None):
        if count is not None and not 0 <= index < count:
            return set(self.indices)
        if shift and self.anchor is not None:
            start, end = sorted((self.anchor, index))
            selected = set(range(start, end + 1))
            self.indices = self.indices | selected if ctrl else selected
        elif ctrl:
            self.indices.symmetric_difference_update({index})
            self.anchor = index
        else:
            self.indices = {index}
            self.anchor = index
        return set(self.indices)

    def normalize_after_removal(self, removed: set[int], old_count: int):
        mapping = {}
        new_index = 0
        for old_index in range(old_count):
            if old_index not in removed:
                mapping[old_index] = new_index
                new_index += 1
        self.indices = {mapping[i] for i in self.indices if i in mapping}
        self.anchor = mapping.get(self.anchor)


def remove_from_session(jobs: list[dict], indices, *, discard_result=None):
    """Quita filas sin borrar originales ni artefactos; bloquea trabajos activos."""
    selected = sorted({int(i) for i in indices if 0 <= int(i) < len(jobs)})
    busy = [i for i in selected if jobs[i].get("status") == "Procesando"]
    if busy:
        raise RuntimeError("No se puede quitar un sticker mientras está procesándose.")
    removed = []
    for index in reversed(selected):
        job = jobs[index]
        result = job.get("result")
        already_published = bool(job.get("sent_to_processed"))
        if (result is not None and job.get("status") != "Confirmado"
                and not already_published and discard_result):
            discard_result(result.job_id)
        removed.append(jobs.pop(index))
    removed.reverse()
    return removed


class SessionStore:
    FIELDS = (
        "source_path", "status", "mask_override", "selection_protection_mask",
        "selection_contraction_mm", "selection_expansion_mm", "selection_smoothing_mm",
        "v2_border_mm", "v2_quality", "border_treatment", "v2_mask_base_path",
        "v2_mask_document_path", "approved_mask_reference", "error",
        "review_state", "reviewed_master_sha256", "reviewed_at",
        "review_invalidated_reason", "sent_to_processed", "sent_to_processed_at",
        "exports", "export_count",
        "v2_operation_undo", "v2_operation_redo",
    )

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def save(self, jobs: list[dict], views: dict | None = None):
        payload = {"schema": 1, "jobs": [], "views": views or {}}
        for job in jobs:
            row = {key: job.get(key) for key in self.FIELDS if job.get(key) is not None}
            result = job.get("result")
            metadata = getattr(result, "artifacts", {}).get("metadata") if result else None
            if not metadata and result:
                output_dir = getattr(result, "output_dir", None)
                candidate = Path(output_dir) / "metadata.json" if output_dir else None
                metadata = str(candidate) if candidate and candidate.is_file() else None
            if metadata:
                row["result_metadata"] = metadata
            payload["jobs"].append(row)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def load(self):
        if not self.path.is_file():
            return {"schema": 1, "jobs": [], "views": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {"schema": 1, "jobs": [], "views": {}}
        if payload.get("schema") != 1 or not isinstance(payload.get("jobs"), list):
            return {"schema": 1, "jobs": [], "views": {}}
        payload["jobs"] = [row for row in payload["jobs"]
                           if isinstance(row, dict) and Path(row.get("source_path", "")).is_file()]
        return payload
