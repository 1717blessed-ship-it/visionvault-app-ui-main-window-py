"""Flujos de produccion y linea de tiempo de los pedidos."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Final


BLOCKING_STATES: Final[tuple[str, ...]] = (
    "Esperando aprobacion",
    "Esperando pago",
    "Pendiente",
    "Bloqueado",
)

GENERAL_WORKFLOW: Final[tuple[tuple[str, int], ...]] = (
    ("Recibido", 5),
    ("Esperando archivos", 10),
    ("Diseños confirmados", 20),
    ("Listo para armado de planchas", 30),
    ("En armado de planchas", 40),
    ("Listo para imprimir", 50),
    ("Impresión", 60),
    ("Sublimado / Laminado", 70),
    ("Corte", 80),
    ("Control de calidad", 90),
    ("Finalizado", 95),
    ("Entregado", 100),
)

VINYL_WORKFLOW: Final[tuple[tuple[str, int], ...]] = (
    ("Recibido", 5),
    ("Esperando archivos", 10),
    ("Diseños confirmados", 20),
    ("Armado de plancha", 30),
    ("Impresión", 60),
    ("Laminado", 65),
    ("Sublimación", 70),
    ("Corte plotter", 80),
    ("Control de calidad", 90),
    ("Empaquetado", 95),
    ("Entregado", 100),
)

TEXTILE_WORKFLOW: Final[tuple[tuple[str, int], ...]] = (
    ("Recibido", 5),
    ("Esperando archivos", 10),
    ("Diseños confirmados", 20),
    ("Listo para imprimir", 50),
    ("Impresión", 60),
    ("Sublimado", 70),
    ("Control de calidad", 90),
    ("Empaquetado", 95),
    ("Entregado", 100),
)

FINISHING_WORKFLOW: Final[tuple[tuple[str, int], ...]] = (
    ("Recibido", 5),
    ("Esperando archivos", 10),
    ("Diseños confirmados", 20),
    ("Preparación", 30),
    ("Producción", 60),
    ("Terminación", 80),
    ("Control de calidad", 90),
    ("Empaquetado", 95),
    ("Entregado", 100),
)

# Compatibilidad para modulos que aun importan la constante anterior.
WORKFLOW_STAGES: Final[list[str]] = [stage for stage, _ in GENERAL_WORKFLOW]

_LEGACY_STATUS_TO_STAGE: Final[dict[str, str]] = {
    "Nuevo": "Recibido",
    "En revisión": "Esperando archivos",
    "En diseño": "Esperando archivos",
    "Esperando aprobación": "Esperando archivos",
    "Esperando pago": "Recibido",
    "Pendiente": "Recibido",
    "Bloqueado": "Recibido",
    "Listo para Armado de Planchas": "Listo para armado de planchas",
    "En Armado de Planchas": "En armado de planchas",
    "Listo para plancha": "Listo para armado de planchas",
    "En producción": "En armado de planchas",
    "Impreso": "Impresión",
    "Aprobado": "Diseños confirmados",
    "Presupuesto enviado": "Recibido",
    "Rechazado": "Recibido",
}


def get_workflow(order: dict) -> tuple[tuple[str, int], ...]:
    """Devuelve el flujo apropiado según el material de sus trabajos."""
    materials = [str(order.get("material", "") or "")]
    materials.extend(str(job.get("material", "") or "") for job in order.get("jobs", []) if isinstance(job, dict))
    descriptor = " ".join(materials).casefold()
    if any(word in descriptor for word in ("vinilo", "sticker", "plotter")):
        return VINYL_WORKFLOW
    if any(word in descriptor for word in ("remera", "textil", "sublim")):
        return TEXTILE_WORKFLOW
    if any(word in descriptor for word in ("doming", "resina", "cuadro", "lienzo")):
        return FINISHING_WORKFLOW
    return GENERAL_WORKFLOW


def workflow_stages(order: dict) -> list[str]:
    return [stage for stage, _ in get_workflow(order)]


def order_statuses(order: dict | None = None) -> tuple[str, ...]:
    """Estados disponibles: exactamente las etapas del flujo mas bloqueos."""
    return tuple(workflow_stages(order or {})) + BLOCKING_STATES


def get_current_stage(order: dict) -> str:
    workflow = get_workflow(order)
    stages = [stage for stage, _ in workflow]
    status = str(order.get("status", "Recibido") or "Recibido")
    status = _LEGACY_STATUS_TO_STAGE.get(status, status)
    if workflow is VINYL_WORKFLOW:
        status = {
            "Listo para armado de planchas": "Armado de plancha",
            "En armado de planchas": "Armado de plancha",
            "Listo para imprimir": "Impresión",
            "Sublimado / Laminado": "Sublimación",
            # Los pedidos creados antes del cambio conservan su etapa válida.
            "Laminado": "Sublimación",
            "Corte": "Corte plotter",
            "Finalizado": "Empaquetado",
        }.get(status, status)
    elif workflow is TEXTILE_WORKFLOW:
        status = {
            "Listo para armado de planchas": "Listo para imprimir",
            "En armado de planchas": "Listo para imprimir",
            "Sublimado / Laminado": "Sublimado",
            "Finalizado": "Empaquetado",
        }.get(status, status)
    elif workflow is FINISHING_WORKFLOW:
        status = {
            "Listo para armado de planchas": "Preparación",
            "En armado de planchas": "Preparación",
            "Listo para imprimir": "Producción",
            "Impresión": "Producción",
            "Sublimado / Laminado": "Terminación",
            "Corte": "Terminación",
            "Finalizado": "Empaquetado",
        }.get(status, status)
    if status in stages:
        return status
    return "Recibido"


def get_stage_progress(order: dict) -> float:
    """Porcentaje del flujo asociado a la etapa actual."""
    current = get_current_stage(order)
    return next(progress / 100 for stage, progress in get_workflow(order) if stage == current)


def get_completed_stages(order: dict) -> list[str]:
    stages = workflow_stages(order)
    return stages[:stages.index(get_current_stage(order))]


def get_pending_stages(order: dict) -> list[str]:
    stages = workflow_stages(order)
    return stages[stages.index(get_current_stage(order)) + 1:]


def get_next_action(order: dict) -> tuple[str, str, int]:
    current = get_current_stage(order)
    stages = workflow_stages(order)
    index = stages.index(current)
    if current == "Entregado":
        return ("complete", "Pedido entregado", 0)
    return ("advance", f"Avanzar a: {stages[index + 1]}", 5)


def timeline_stage_times(order: dict, events: list[dict]) -> dict[str, tuple[datetime, datetime | None]]:
    """Indica cuándo se entró y salió de cada etapa del flujo."""
    def parse_date(value: object) -> datetime | None:
        try:
            return datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None

    initial_at = parse_date(order.get("created_at") or order.get("order_date") or order.get("updated_at")) or datetime.now()
    entries: list[tuple[str, datetime]] = [("Recibido", initial_at)]
    for event in sorted(events, key=lambda item: str(item.get("created_at") or "")):
        raw_stage = ""
        try:
            raw_stage = str(json.loads(event.get("data_json") or "{}").get("new_stage") or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        if not raw_stage and event.get("event_type") == "Estado":
            prefix = "Estado actualizado a: "
            message = str(event.get("message") or "")
            if message.startswith(prefix):
                raw_stage = message[len(prefix):].rstrip(".")
        if not raw_stage:
            continue
        stage = get_current_stage({**order, "status": raw_stage})
        changed_at = parse_date(event.get("created_at"))
        if changed_at and stage != entries[-1][0]:
            entries.append((stage, changed_at))

    current = get_current_stage(order)
    if current != entries[-1][0]:
        entries.append((current, parse_date(order.get("updated_at")) or datetime.now()))
    result: dict[str, tuple[datetime, datetime | None]] = {}
    for index, (stage, entered_at) in enumerate(entries):
        result[stage] = (entered_at, entries[index + 1][1] if index + 1 < len(entries) else None)
    return result


def format_stage_elapsed(started_at: datetime, ended_at: datetime | None = None) -> str:
    """Formato compacto en español para los contadores de la línea de tiempo."""
    now = datetime.now(started_at.tzinfo) if started_at.tzinfo else datetime.now()
    seconds = max(0, int(((ended_at or now) - started_at).total_seconds()))
    days, seconds = divmod(seconds, 86_400)
    hours, seconds = divmod(seconds, 3_600)
    minutes = seconds // 60
    if days:
        return f"{days} d {hours} h"
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min"


def format_timeline(order: dict) -> list[tuple[str, str]]:
    current = get_current_stage(order)
    current_index = workflow_stages(order).index(current)
    return [
        (stage, "●" if index <= current_index else "○")
        for index, stage in enumerate(workflow_stages(order))
    ]
