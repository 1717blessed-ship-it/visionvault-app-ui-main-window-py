"""Bus de eventos central de Doccione Studio."""

from __future__ import annotations

import logging
from typing import Callable

from app.events.event_repository import EventRepository
from app.events.event_types import (
    PRIORITY_HIGH,
    PRIORITY_NORMAL,
    ORDER_CREATED,
    PAYMENT_RECEIVED,
    PRODUCTION_COMPLETED,
    PRODUCTION_ERROR,
    EVENT_TYPE_LABELS,
    EVENT_ICONS,
)

logger = logging.getLogger(__name__)


class EventBus:
    """Publica eventos y coordina su propagación.

    Este es el punto de entrada único para que cualquier parte de la
    aplicación genere un evento sin conocer los consumidores.
    """

    def __init__(self, repo: EventRepository):
        self.repo = repo
        self._listeners: list[Callable] = []

    def on_event(self, callback: Callable) -> None:
        """Registra un callback que se ejecuta después de cada evento."""
        self._listeners.append(callback)

    def publish(
        self,
        event_type: str,
        title: str,
        message: str,
        priority: str = PRIORITY_NORMAL,
        entity_type: str | None = None,
        entity_id: int | None = None,
        payload: dict | None = None,
    ) -> str:
        """Publica un evento y notifica a los listeners."""
        event_uuid = self.repo.publish_event(
            event_type=event_type,
            priority=priority,
            title=title,
            message=message,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
        )
        logger.info("Evento publicado: %s [%s] uuid=%s", event_type, priority, event_uuid)
        for listener in self._listeners:
            try:
                listener(event_uuid, event_type, title, message, priority)
            except Exception as exc:
                logger.error("Listener falló para evento %s: %s", event_uuid, exc)
        return event_uuid

    def publish_order_created(self, order_id: int, client_name: str, total: float) -> str:
        icon = EVENT_ICONS.get(ORDER_CREATED, "")
        return self.publish(
            event_type=ORDER_CREATED,
            title=f"{icon} Nuevo pedido",
            message=f"Pedido #{order_id} · {client_name} · ${total:,.0f}",
            priority=PRIORITY_HIGH,
            entity_type="order",
            entity_id=order_id,
            payload={"client_name": client_name, "total": total},
        )

    def publish_payment_received(self, order_id: int, amount: float, method: str = "") -> str:
        icon = EVENT_ICONS.get(PAYMENT_RECEIVED, "")
        detail = f" · {method}" if method else ""
        return self.publish(
            event_type=PAYMENT_RECEIVED,
            title=f"{icon} Pago registrado",
            message=f"Pedido #{order_id} · ${amount:,.0f}{detail}",
            priority=PRIORITY_HIGH,
            entity_type="order",
            entity_id=order_id,
            payload={"amount": amount, "method": method},
        )

    def publish_production_completed(self, order_id: int, detail: str = "") -> str:
        icon = EVENT_ICONS.get(PRODUCTION_COMPLETED, "")
        return self.publish(
            event_type=PRODUCTION_COMPLETED,
            title=f"{icon} Producción terminada",
            message=f"Pedido #{order_id} está listo para entregar" + (f" · {detail}" if detail else ""),
            priority=PRIORITY_NORMAL,
            entity_type="order",
            entity_id=order_id,
            payload={"detail": detail},
        )

    def publish_production_error(self, order_id: int, error_detail: str) -> str:
        icon = EVENT_ICONS.get(PRODUCTION_ERROR, "")
        return self.publish(
            event_type=PRODUCTION_ERROR,
            title=f"{icon} Error de producción",
            message=f"Pedido #{order_id} · {error_detail}",
            priority=PRIORITY_HIGH,
            entity_type="order",
            entity_id=order_id,
            payload={"error": error_detail},
        )
