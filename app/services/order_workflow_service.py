"""Atomic workflows that span orders, production and inventory."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from typing import Any

from app.domain.order_states import OrderStateService
from app.events.event_bus import EventBus
from app.services.stock_cost_price_service import StockCostPriceService

logger = logging.getLogger(__name__)


class OrderWorkflowService:
    """Coordinates existing repositories without replacing their responsibilities."""

    ACCEPTED_STATUS = "Recibido"
    ACCEPTABLE_STATUSES = {"nuevo", "pendiente", "recibido"}

    def __init__(
        self,
        connection: sqlite3.Connection,
        stock_service: StockCostPriceService,
        event_bus: EventBus | None = None,
    ) -> None:
        self.connection = connection
        self.stock_service = stock_service
        self.event_bus = event_bus
        self.state_service = OrderStateService(connection)

    def accept_order(
        self,
        order_id: int,
        *,
        actor: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Accept an order, reserve configured materials and publish after commit.

        Existing jobs are reused. If an old order has no jobs, one compatible
        primary job is inserted inside the same transaction. Orders that do not
        resolve to a cost model/material remain acceptable but explicitly report
        ``stock_not_configured`` rather than creating a guessed reservation.
        """
        now = datetime.now().isoformat(timespec="seconds")
        actor_value = (actor or "").strip()
        notes_value = (notes or "").strip()

        try:
            with self.connection:
                order_row = self.connection.execute(
                    "SELECT * FROM orders WHERE id = ? AND COALESCE(is_archived, 0) = 0",
                    (order_id,),
                ).fetchone()
                if not order_row:
                    raise ValueError(f"Pedido #{order_id} no encontrado.")
                order = dict(order_row)
                previous_status = str(order.get("status") or "")

                accepted_event = self.connection.execute(
                    "SELECT id FROM order_events WHERE order_id = ? AND event_type = 'order.accepted' LIMIT 1",
                    (order_id,),
                ).fetchone()
                if accepted_event:
                    jobs = self.connection.execute(
                        "SELECT id FROM order_jobs WHERE order_id = ? ORDER BY sort_order, id", (order_id,)
                    ).fetchall()
                    return self._result(order_id, previous_status, previous_status, [int(row[0]) for row in jobs], 0, 0, False, True)

                if previous_status.strip().casefold() not in self.ACCEPTABLE_STATUSES:
                    raise ValueError(
                        f"El pedido #{order_id} está en estado '{previous_status}' y no puede aceptarse."
                    )

                jobs = self.connection.execute(
                    "SELECT * FROM order_jobs WHERE order_id = ? ORDER BY sort_order, id", (order_id,)
                ).fetchall()
                jobs_created = 0
                if not jobs:
                    cursor = self.connection.execute(
                        """INSERT INTO order_jobs(order_id, title, material, size, quantity, subtotal,
                           discount_percent, extra_services, status, notes, sort_order,
                           cost_mp, cost_mo, cost_cf, cost_total, created_at, updated_at)
                           VALUES(?, 'Trabajo principal', ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)""",
                        (
                            order_id, order.get("material", ""), order.get("size", ""),
                            max(1, int(order.get("quantity") or 1)), float(order.get("price") or 0),
                            float(order.get("discount_percent") or 0), order.get("extra_services", ""),
                            self.ACCEPTED_STATUS, order.get("observations", ""),
                            float(order.get("cost_mp") or 0), float(order.get("cost_mo") or 0),
                            float(order.get("cost_cf") or 0), float(order.get("cost_total") or 0), now, now,
                        ),
                    )
                    jobs = [self.connection.execute("SELECT * FROM order_jobs WHERE id = ?", (cursor.lastrowid,)).fetchone()]
                    jobs_created = 1

                stock_reserved = False
                stock_not_configured = 0
                jobs_updated = 0
                job_ids: list[int] = []
                for job_row in jobs:
                    job = dict(job_row)
                    job_id = int(job["id"])
                    job_ids.append(job_id)
                    model_id = self._cost_model_id_for_job(job)
                    if model_id is None:
                        stock_not_configured += 1
                    else:
                        stock_reserved = self.stock_service.reserve_for_order(
                            order_job_id=job_id,
                            cost_model_id=model_id,
                            production_quantity=max(1, int(job.get("quantity") or 1)),
                            commit=False,
                        ) or stock_reserved
                        if not stock_reserved:
                            stock_not_configured += 1
                    if job.get("status") != self.ACCEPTED_STATUS:
                        self.connection.execute(
                            "UPDATE order_jobs SET status = ?, updated_at = ? WHERE id = ?",
                            (self.ACCEPTED_STATUS, now, job_id),
                        )
                        jobs_updated += 1

                self.state_service.transition(
                    order_id,
                    self.ACCEPTED_STATUS,
                    actor=actor_value,
                    source="order.acceptance",
                    reason=notes_value or "Pedido aceptado para producción",
                    commit=False,
                    record_event=False,
                )
                payload = {
                    "actor": actor_value,
                    "notes": notes_value,
                    "job_ids": job_ids,
                    "stock_reserved": stock_reserved,
                    "stock_not_configured_jobs": stock_not_configured,
                }
                self.connection.execute(
                    """INSERT INTO order_events(order_id, event_type, message, data_json, created_at)
                       VALUES(?, 'order.accepted', ?, ?, ?)""",
                    (
                        order_id,
                        f"Pedido aceptado para producción · {len(job_ids)} trabajo(s).",
                        json.dumps(payload, ensure_ascii=False),
                        now,
                    ),
                )
                result = self._result(order_id, previous_status, self.ACCEPTED_STATUS, job_ids, jobs_created, jobs_updated, stock_reserved, False)
                result["stock_not_configured_jobs"] = stock_not_configured

        except sqlite3.Error as exc:
            raise RuntimeError(f"No se pudo aceptar el pedido #{order_id}: {exc}") from exc

        self._publish_accepted(result)
        return result

    def _cost_model_id_for_job(self, job: dict[str, Any]) -> int | None:
        material = str(job.get("material") or "").strip()
        if not material:
            return None
        row = self.connection.execute(
            """SELECT variable_cost_model_id FROM price_rules
               WHERE material = ? AND active = 1 AND variable_cost_model_id IS NOT NULL
               ORDER BY id DESC LIMIT 1""",
            (material,),
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    @staticmethod
    def _result(order_id: int, previous_status: str, new_status: str, job_ids: list[int], jobs_created: int, jobs_updated: int, stock_reserved: bool, already_processed: bool) -> dict[str, Any]:
        return {"success": True, "order_id": order_id, "previous_status": previous_status,
                "new_status": new_status, "job_ids": job_ids, "jobs_created": jobs_created,
                "jobs_updated": jobs_updated, "stock_reserved": stock_reserved,
                "already_processed": already_processed}

    def _publish_accepted(self, result: dict[str, Any]) -> None:
        if not self.event_bus:
            return
        try:
            self.event_bus.publish(
                event_type="order.accepted",
                title="Pedido aceptado",
                message=f"Pedido #{result['order_id']} aceptado para producción",
                priority="high",
                entity_type="order",
                entity_id=result["order_id"],
                payload={"order_id": result["order_id"], "job_ids": result["job_ids"],
                         "affected_modules": ["orders", "production", "stock"]},
            )
        except Exception:
            logger.exception("El pedido %s fue aceptado, pero no se pudo publicar order.accepted", result["order_id"])
