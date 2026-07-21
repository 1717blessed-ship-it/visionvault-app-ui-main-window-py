"""Tipos de evento soportados por Doccione Studio."""

from __future__ import annotations

ORDER_CREATED = "order.created"
ORDER_COMPLETED = "order.completed"
PAYMENT_RECEIVED = "payment.received"
PRODUCTION_STARTED = "production.started"
PRODUCTION_COMPLETED = "production.completed"
PRODUCTION_ERROR = "production.error"
STOCK_LOW = "stock.low"

PRIORITY_HIGH = "high"
PRIORITY_NORMAL = "normal"
PRIORITY_LOW = "low"

EVENT_TYPE_LABELS: dict[str, str] = {
    ORDER_CREATED: "Nuevo pedido",
    ORDER_COMPLETED: "Pedido completado",
    PAYMENT_RECEIVED: "Pago registrado",
    PRODUCTION_STARTED: "Producción iniciada",
    PRODUCTION_COMPLETED: "Producción terminada",
    PRODUCTION_ERROR: "Error de producción",
    STOCK_LOW: "Stock bajo",
}

PRIORITY_LABELS: dict[str, str] = {
    PRIORITY_HIGH: "Alta",
    PRIORITY_NORMAL: "Normal",
    PRIORITY_LOW: "Baja",
}

EVENT_ICONS: dict[str, str] = {
    ORDER_CREATED: "🛒",
    ORDER_COMPLETED: "✅",
    PAYMENT_RECEIVED: "💰",
    PRODUCTION_STARTED: "🖨️",
    PRODUCTION_COMPLETED: "✅",
    PRODUCTION_ERROR: "⚠️",
    STOCK_LOW: "📦",
}
