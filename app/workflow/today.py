"""Resumen operativo para iniciar la jornada en una única vista."""

from __future__ import annotations

from datetime import date
from typing import Any


def operational_snapshot(database) -> dict[str, Any]:
    """Devuelve solo señales accionables; no altera pedidos ni stock."""
    orders = [o for o in database.orders() if o.get("status") not in {"Finalizado", "Entregado", "Terminado", "Archivado", "Cancelado"}]
    today = date.today().isoformat()
    due = [o for o in orders if str(o.get("delivery_date") or "")[:10] and str(o["delivery_date"])[:10] <= today]
    pending_payment = [o for o in orders if float(o.get("budget_total") or o.get("price") or 0) > float(o.get("paid_amount") or 0)]
    urgent = [o for o in orders if int(o.get("print_priority") or 0) >= 3]
    rows = database.connection.execute(
        """SELECT id, name, physical_stock, reserved_stock, min_stock
           FROM materials WHERE physical_stock - reserved_stock <= min_stock ORDER BY name COLLATE NOCASE"""
    ).fetchall()
    low_stock = [dict(row) for row in rows]
    actions = []
    actions.extend({"kind": "delivery", "order": order, "label": "Resolver entrega"} for order in due)
    actions.extend({"kind": "payment", "order": order, "label": "Solicitar cobro"} for order in pending_payment if order not in due)
    actions.extend({"kind": "priority", "order": order, "label": "Priorizar producción"} for order in urgent if order not in due)
    return {
        "metrics": {"active_orders": len(orders), "due_orders": len(due), "pending_payments": len(pending_payment), "low_stock": len(low_stock)},
        "actions": actions[:12], "low_stock_items": low_stock[:8],
    }
