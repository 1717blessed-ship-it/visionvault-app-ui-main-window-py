"""Manejadores de eventos reactivos."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def on_order_created(event_uuid: str, event_type: str, title: str, message: str, priority: str) -> None:
    """Handler para nuevo pedido."""
    logger.info("Handler order_created: %s", message)


def on_payment_received(event_uuid: str, event_type: str, title: str, message: str, priority: str) -> None:
    """Handler para pago registrado."""
    logger.info("Handler payment_received: %s", message)


def on_production_completed(event_uuid: str, event_type: str, title: str, message: str, priority: str) -> None:
    """Handler para producción terminada."""
    logger.info("Handler production_completed: %s", message)


def on_production_error(event_uuid: str, event_type: str, title: str, message: str, priority: str) -> None:
    """Handler para error de producción."""
    logger.warning("Handler production_error: %s", message)


DEFAULT_HANDLERS = {
    "order.created": on_order_created,
    "payment.received": on_payment_received,
    "production.completed": on_production_completed,
    "production.error": on_production_error,
}
