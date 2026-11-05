"""
Estimador de tiempo de trabajo restante para pedidos.
Calcula cuánto tiempo falta para terminar cada pedido.
"""

from datetime import date, datetime, timedelta


# Tiempos base estimados por tarea (en minutos)
TIME_ESTIMATES = {
    "assign_design": 2,          # Asignar un diseño al pedido
    "confirm_design": 3,         # Confirmar un diseño
    "prepare_photoshop": 15,     # Editar en Photoshop
    "create_plancha": 20,        # Armar una plancha
    "review_plancha": 5,         # Revisar plancha armada
    "print_plancha": 5,          # Imprimir una plancha
    "finish_order": 2,           # Marcar como finalizado
    "payment": 3,                # Registrar pago
}


def estimate_remaining_work(order: dict) -> int:
    """
    Estima el tiempo de trabajo restante en minutos.

    Args:
        order: Diccionario con datos del pedido

    Returns:
        Minutos estimados de trabajo restante
    """
    from app.workflow.timeline import get_current_stage

    total_minutes = 0
    stage = get_current_stage(order)

    # Datos del pedido
    quantity = int(order.get("quantity", 0))
    design_count = int(order.get("design_count", 0))
    confirmed_count = int(order.get("confirmed_count", 0))
    plancha_count = int(order.get("plancha_count", 0))
    payment_status = str(order.get("payment_status", "Pendiente"))

    # Pago pendiente
    if payment_status == "Pendiente":
        total_minutes += TIME_ESTIMATES["payment"]

    # Diseños por asignar
    if quantity > 0 and design_count < quantity:
        missing_designs = quantity - design_count
        total_minutes += missing_designs * TIME_ESTIMATES["assign_design"]

    # Diseños por confirmar
    unconfirmed = max(0, design_count - confirmed_count)
    if unconfirmed > 0:
        total_minutes += unconfirmed * TIME_ESTIMATES["confirm_design"]

    # Planchas por armar
    if stage in ("Listo para Armado de Planchas", "En Armado de Planchas"):
        if plancha_count == 0:
            # Estimamos cuántas planchas necesita según cantidad
            # Una plancha A4 puede tener ~20 stickers de 6cm
            expected_planchas = max(1, (quantity + 19) // 20)
            total_minutes += expected_planchas * TIME_ESTIMATES["create_plancha"]
        else:
            # Ya tiene planchas, pero puede necesitar revisión
            total_minutes += TIME_ESTIMATES["review_plancha"]

    # Impresión
    if stage == "Listo para imprimir":
        planchas_to_print = max(1, plancha_count)
        total_minutes += planchas_to_print * TIME_ESTIMATES["print_plancha"]

    # Finalización
    if stage in ("Impreso", "Listo para imprimir", "En Armado de Planchas"):
        total_minutes += TIME_ESTIMATES["finish_order"]

    return total_minutes


def estimate_completion_time(order: dict) -> datetime | None:
    """
    Estima cuándo se completará el pedido si se trabaja continuamente.

    Returns:
        Fecha y hora estimada de finalización, o None si no se puede calcular
    """
    minutes = estimate_remaining_work(order)
    if minutes > 0:
        return datetime.now() + timedelta(minutes=minutes)
    return None


def _coerce_datetime(value) -> datetime | None:
    """Normaliza fechas recibidas como texto, datetime o date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        # Una fecha sin hora representa el cierre de esa jornada, no su
        # comienzo; así "entrega mañana" no aparece como vencida a medianoche.
        return datetime.combine(value, datetime.max.time())
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace(" ", "T"))
        except ValueError:
            try:
                return datetime.fromisoformat(text)
            except ValueError:
                return None
    return None


def get_time_pressure(order: dict) -> tuple[str, float]:
    """
    Calcula la presión de tiempo: relación entre tiempo disponible y trabajo restante.

    Returns:
        (descripción, ratio) donde ratio es trabajo/disponible
        - ratio > 1.0: no alcanza el tiempo
        - ratio 0.8-1.0: riesgo de atraso
        - ratio < 0.5: tiempo cómodo
    """
    delivery = _coerce_datetime(order.get("delivery_date", ""))
    if delivery is None:
        return ("Sin fecha de entrega", 0.0)

    now = datetime.now()

    if delivery < now:
        return ("Fecha pasada", 999.0)

    minutes_available = (delivery - now).total_seconds() / 60
    minutes_work = estimate_remaining_work(order)

    if minutes_available <= 0:
        return ("Sin tiempo disponible", 999.0)

    ratio = minutes_work / minutes_available

    if ratio >= 1.0:
        return ("⚠ No alcanza el tiempo", ratio)
    elif ratio >= 0.8:
        return ("⚠ Riesgo de atraso", ratio)
    elif ratio >= 0.5:
        return ("Tiempo ajustado", ratio)
    else:
        return ("Sin riesgo", ratio)


def format_time_remaining(order: dict) -> str:
    """Formatea el tiempo restante hasta la entrega de forma legible."""
    delivery = _coerce_datetime(order.get("delivery_date", ""))
    if delivery is None:
        return "Sin fecha de entrega"

    now = datetime.now()
    delta = delivery - now

    # Check if order is delivered - normalize status for comparison
    status = str(order.get("status", "")).strip().lower()
    is_delivered = status in ("entregado", "finalizado", "terminado")

    if delta.total_seconds() < 0:
        # Only show "Atrasado" for orders that are NOT delivered
        if is_delivered:
            # Delivered orders don't show "Atrasado" - they're done
            return "Entregado"
        else:
            # Not delivered yet, show as late
            hours_late = abs(delta.total_seconds()) / 3600
            if hours_late < 24:
                return f"Atrasado {int(hours_late)} horas"
            else:
                return f"Atrasado {int(hours_late / 24)} días"

    total_hours = delta.total_seconds() / 3600

    if total_hours < 1:
        return f"{int(delta.total_seconds() / 60)} minutos"
    elif total_hours < 24:
        return f"{int(total_hours)} horas"
    else:
        days = int(total_hours / 24)
        remaining_hours = int(total_hours % 24)
        if remaining_hours > 0:
            return f"{days} días {remaining_hours} horas"
        else:
            return f"{days} días"


def format_work_time(minutes: int) -> str:
    """Formatea el tiempo de trabajo en formato legible."""
    if minutes < 1:
        return "< 1 minuto"
    elif minutes < 60:
        return f"{minutes} minutos"
    else:
        hours = minutes // 60
        remaining_minutes = minutes % 60
        if remaining_minutes > 0:
            return f"{hours} h {remaining_minutes} min"
        else:
            return f"{hours} hora{'s' if hours != 1 else ''}"

