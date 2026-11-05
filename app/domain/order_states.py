"""Fuente única de verdad para estados y transiciones de pedidos."""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from contextlib import nullcontext
from datetime import datetime
from typing import Any, Iterable


WORKFLOW_STAGES = (
    "Recibido", "Esperando archivos", "Diseños confirmados",
    "Listo para armado de planchas", "En armado de planchas",
    "Armado de plancha", "Listo para imprimir", "Impresión",
    "Sublimado / Laminado", "Sublimación", "Sublimado", "Laminado",
    "Corte", "Corte plotter", "Preparación", "Producción", "Terminación",
    "Control de calidad", "Empaquetado", "Finalizado", "Entregado",
)
BLOCKING_STATES = ("Esperando aprobación", "Esperando pago", "Pendiente", "Bloqueado")
ORDER_SUMMARY_STATES = ("En producción",)
TERMINAL_STATES = frozenset({"Entregado", "Terminado", "Completado", "Cancelado"})


def _key(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").strip().casefold())
    return "".join(character for character in text if unicodedata.category(character) != "Mn")


_ALIASES = {
    "": "Recibido",
    "nuevo": "Recibido",
    "en revision": "Esperando archivos",
    "en diseno": "Esperando archivos",
    "esperando aprobacion": "Esperando aprobación",
    "esperando pago": "Esperando pago",
    "pendiente": "Pendiente",
    "bloqueado": "Bloqueado",
    "recibado": "Recibido",
    "listo para armado de planchas": "Listo para armado de planchas",
    "en armado de planchas": "En armado de planchas",
    "listo para plancha": "Listo para armado de planchas",
    "en produccion": "En producción",
    "impreso": "Impresión",
    "aprobado": "Diseños confirmados",
    "presupuesto enviado": "Recibido",
    "rechazado": "Recibido",
    "finalizado": "Finalizado",
    "entregado": "Entregado",
    "terminado": "Terminado",
    "completado": "Completado",
    "cancelado": "Cancelado",
}
for _stage in WORKFLOW_STAGES + BLOCKING_STATES:
    _ALIASES.setdefault(_key(_stage), _stage)


def normalize_status(value: Any) -> str:
    """Normaliza aliases históricos sin inventar estados desconocidos."""
    raw = str(value or "").strip()
    return _ALIASES.get(_key(raw), raw or "Recibido")


def valid_status(value: Any) -> bool:
    normalized = normalize_status(value)
    return normalized in set(WORKFLOW_STAGES) | set(BLOCKING_STATES) | set(ORDER_SUMMARY_STATES) | set(TERMINAL_STATES)


def is_terminal(value: Any) -> bool:
    return normalize_status(value) in TERMINAL_STATES


def validate_transition(current: Any, target: Any, *, force: bool = False) -> tuple[bool, str]:
    current_status, target_status = normalize_status(current), normalize_status(target)
    if not valid_status(target_status):
        return False, f"Estado destino no reconocido: {target!s}"
    if not force and is_terminal(current_status) and target_status != current_status:
        return False, f"El pedido está cerrado como '{current_status}' y no puede volver a abrirse sin una corrección administrativa."
    return True, ""


def derive_order_status_from_jobs(job_statuses: Iterable[Any], current_status: Any = "Recibido") -> str:
    """Deriva el resumen del pedido con reglas idénticas para móvil y escritorio."""
    current = normalize_status(current_status)
    if is_terminal(current):
        return current
    stages = [normalize_status(status) for status in job_statuses]
    if not stages:
        return current
    if all(stage == "Cancelado" for stage in stages):
        return "Cancelado"
    if all(stage == "Entregado" for stage in stages):
        return "Entregado"
    if all(stage in {"Finalizado", "Entregado", "Empaquetado"} for stage in stages):
        return "Finalizado"
    if all(stage in {"Recibido", "Pendiente", "Esperando pago"} for stage in stages):
        return "Pendiente"
    productive = set(WORKFLOW_STAGES) - {"Recibido", "Esperando archivos", "Entregado"}
    if any(stage in productive for stage in stages):
        return "En producción"
    if any(stage == "Esperando archivos" for stage in stages):
        return "Esperando archivos"
    return "Recibido"


class OrderStateService:
    """Actualiza, sincroniza y audita una transición en una única operación."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def transition(
        self, order_id: int, new_status: str, *, actor: str = "", source: str = "desktop",
        reason: str = "", force: bool = False, sync_related: bool = False,
        commit: bool = True, record_event: bool = True,
    ) -> dict[str, Any]:
        row = self.connection.execute("SELECT id,status FROM orders WHERE id=?", (int(order_id),)).fetchone()
        if not row:
            raise ValueError(f"Pedido #{order_id} no encontrado.")
        previous = str(row["status"] if isinstance(row, sqlite3.Row) else row[1])
        target = normalize_status(new_status)
        allowed, message = validate_transition(previous, target, force=force)
        if not allowed:
            raise ValueError(message)
        # Un alias histórico equivalente (p. ej. Nuevo → Recibido) igualmente
        # debe escribirse para sanear el dato persistido.
        if previous.strip() == target and not sync_related:
            return {"order_id": int(order_id), "previous_status": previous, "new_status": target, "changed": False}
        now = datetime.now().isoformat(timespec="seconds")
        terminal = is_terminal(target)
        context = self.connection if commit else nullcontext()
        with context:
            if target.casefold() in {"entregado", "terminado", "completado"} and normalize_status(previous) != target:
                from app.services.delivery_readiness import assert_deliverable
                self.connection.execute("UPDATE orders SET id=id WHERE id=?", (int(order_id),))
                assert_deliverable(self.connection, order_id)
            order_columns = {str(column[1]) for column in self.connection.execute("PRAGMA table_info(orders)")}
            assignments, parameters = ["status=?", "updated_at=?"], [target, now]
            if "print_priority" in order_columns and terminal:
                assignments.append("print_priority=0")
            if "delivery_date" in order_columns and target in {"Entregado", "Terminado", "Completado"}:
                assignments.append("delivery_date=CASE WHEN COALESCE(delivery_date,'')='' THEN ? ELSE delivery_date END")
                parameters.append(now[:10])
            parameters.append(int(order_id))
            self.connection.execute(
                f"UPDATE orders SET {', '.join(assignments)} WHERE id=?",
                parameters,
            )
            if sync_related and terminal:
                related_status = "Cancelado" if target == "Cancelado" else "Entregado"
                if self._table_exists("order_jobs"):
                    self.connection.execute(
                        "UPDATE order_jobs SET status=?,updated_at=? WHERE order_id=? AND status<>?",
                        (related_status, now, int(order_id), related_status),
                    )
                if self._table_exists("order_designs"):
                    self.connection.execute(
                        "UPDATE order_designs SET status=? WHERE order_id=? AND status<>'Cancelado'",
                        (related_status, int(order_id)),
                    )
                if self._table_exists("plancha_projects"):
                    plancha_status = "cancelado" if target == "Cancelado" else "entregado"
                    self.connection.execute(
                        "UPDATE plancha_projects SET production_status=?,updated_at=? WHERE order_id=?",
                        (plancha_status, now, int(order_id)),
                    )
            if self._table_exists("order_state_history"):
                self.connection.execute(
                    """INSERT INTO order_state_history(order_id,previous_status,new_status,actor,source,reason,changed_at)
                       VALUES(?,?,?,?,?,?,?)""",
                    (int(order_id), previous, target, str(actor).strip(), str(source).strip(), str(reason).strip(), now),
                )
            if record_event and self._table_exists("order_events"):
                payload = json.dumps({"old_stage": previous, "new_stage": target, "actor": actor, "source": source, "reason": reason}, ensure_ascii=False)
                self.connection.execute(
                    """INSERT INTO order_events(order_id,event_type,message,data_json,created_at)
                       VALUES(?,'Estado',?,?,?)""",
                    (int(order_id), f"Estado actualizado a: {target}.", payload, now),
                )
        return {"order_id": int(order_id), "previous_status": previous, "new_status": target, "changed": previous != target}

    def _table_exists(self, name: str) -> bool:
        return bool(self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone())
