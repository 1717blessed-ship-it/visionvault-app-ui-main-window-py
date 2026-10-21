"""Contrato persistente de revisión y exportación de Sticker Studio V2."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path


def master_path(job: dict) -> Path | None:
    result = job.get("result")
    artifacts = getattr(result, "artifacts", {}) or {}
    raw = artifacts.get("master") or artifacts.get("print")
    path = Path(raw) if raw else None
    return path if path and path.is_file() else None


def master_fingerprint(job: dict) -> str | None:
    path = master_path(job)
    return sha256(path.read_bytes()).hexdigest() if path else None


def review_is_current(job: dict) -> bool:
    fingerprint = master_fingerprint(job)
    return bool(fingerprint and job.get("reviewed_master_sha256") == fingerprint)


def mark_reviewed(job: dict) -> str:
    fingerprint = master_fingerprint(job)
    if not fingerprint:
        raise FileNotFoundError("No existe un master para revisar.")
    job["review_state"] = "Revisado"
    job["reviewed_master_sha256"] = fingerprint
    job["reviewed_at"] = datetime.now().isoformat(timespec="seconds")
    return fingerprint


def invalidate_review(job: dict, reason: str = "master_changed") -> None:
    if job.get("reviewed_master_sha256"):
        job["review_state"] = "Revisión requerida"
        job["review_invalidated_reason"] = reason
    job.pop("reviewed_master_sha256", None)
    job.pop("reviewed_at", None)
    # Un master modificado todavía no fue enviado, aunque una versión anterior
    # del mismo trabajo sí figure en Últimos Procesados.
    job["sent_to_processed"] = False
    job.pop("sent_to_processed_at", None)


def mark_sent(job: dict) -> None:
    job["sent_to_processed"] = True
    job["sent_to_processed_at"] = datetime.now().isoformat(timespec="seconds")


def record_export(job: dict, destination: str | Path) -> None:
    exports = list(job.get("exports") or [])
    exports.append({
        "path": str(Path(destination).resolve()),
        "master_sha256": master_fingerprint(job),
        "exported_at": datetime.now().isoformat(timespec="seconds"),
    })
    job["exports"] = exports[-50:]
    job["export_count"] = int(job.get("export_count") or 0) + 1
