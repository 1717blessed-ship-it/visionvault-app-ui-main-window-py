"""
Motor de priorización automática de pedidos.
Calcula la urgencia basándose en múltiples factores.
"""

from datetime import datetime, timedelta
from typing import Literal

from app.ui.theme import PRIORITY_STYLES, normalize_order_style_key

PriorityLevel = Literal["Sin prisa", "Baja", "Media", "Alta", "Urgente"]
PRIORITY_RANK = {"Sin prisa": 0, "Baja": 1, "Media": 2, "Alta": 3, "Urgente": 4}


def calculate_priority(order: dict, estimated_work_minutes: int = 0) -> tuple[PriorityLevel, int, str]:
    """
    Calcula la prioridad automática de un pedido.
    
    Args:
        order: Diccionario con datos del pedido
        estimated_work_minutes: Tiempo estimado de trabajo restante
    
    Returns:
        (nivel_prioridad, score_numerico, razón_principal)
    """
    status = str(order.get("status") or "").strip().casefold()
    if status in {"entregado", "terminado"}:
        return "Sin prisa", 0, "Pedido entregado"

    score = 0
    reasons = []
    delivery_level: PriorityLevel | None = None
    
    # Factor 1: Tiempo hasta la entrega
    delivery_date = order.get("delivery_date", "")
    if delivery_date:
        try:
            delivery = datetime.fromisoformat(delivery_date.replace("T", " "))
            now = datetime.now()
            hours_remaining = (delivery - now).total_seconds() / 3600
            
            if hours_remaining < 0:
                score += 100
                reasons.append("¡Fecha de entrega pasada!")
                delivery_level = "Urgente"
            elif hours_remaining < 12:
                score += 90
                reasons.append(f"Entrega en menos de 12 horas")
                delivery_level = "Urgente"
            elif hours_remaining < 24:
                score += 70
                reasons.append(f"Entrega hoy en {int(hours_remaining)} horas")
                delivery_level = "Alta"
            elif hours_remaining < 48:
                score += 40
                reasons.append("Entrega mañana")
                delivery_level = "Media"
            elif hours_remaining < 72:
                score += 15
                reasons.append("Entrega en 48 a 72 horas")
                delivery_level = "Baja"
            else:
                days = int(hours_remaining / 24)
                reasons.append(f"Entrega en {days} días (sin prisa)")
                delivery_level = "Sin prisa"
        except (ValueError, TypeError):
            pass
    
    # Factor 2: Estado de pago
    payment_status = str(order.get("payment_status", "Pendiente"))
    if payment_status == "Pagado":
        score += 15
        reasons.append("Pagado completo")
    elif payment_status == "Seña recibida":
        score += 10
        reasons.append("Seña recibida")
    elif payment_status == "Pendiente":
        score -= 5
    
    # Factor 3: Etapas pendientes
    from app.workflow.timeline import get_current_stage, WORKFLOW_STAGES
    
    current_stage = get_current_stage(order)
    try:
        current_index = WORKFLOW_STAGES.index(current_stage)
        remaining_stages = len(WORKFLOW_STAGES) - current_index - 1
        
        if remaining_stages >= 5:
            score += 25
            reasons.append(f"{remaining_stages} etapas pendientes")
        elif remaining_stages >= 3:
            score += 15
            reasons.append(f"{remaining_stages} etapas pendientes")
    except ValueError:
        pass
    
    # Factor 4: Diseños sin confirmar
    design_count = int(order.get("design_count", 0))
    confirmed_count = int(order.get("confirmed_count", 0))
    unconfirmed = design_count - confirmed_count
    
    if unconfirmed > 0:
        score += min(20, unconfirmed * 5)
        reasons.append(f"{unconfirmed} diseño(s) sin confirmar")
    
    # Factor 5: Cantidad de planchas (trabajo pendiente)
    plancha_count = int(order.get("plancha_count", 0))
    quantity = int(order.get("quantity", 0))
    
    if plancha_count == 0 and quantity > 0:
        score += 15
        reasons.append("Sin planchas armadas")
    
    # Factor 6: Prioridad manual
    manual_priority = int(order.get("print_priority", 0))
    if manual_priority > 0:
        score += manual_priority * 10
        reasons.append(f"Prioridad manual: {manual_priority}")
    
    # Factor 7: Relación tiempo disponible vs tiempo de trabajo
    if delivery_date and estimated_work_minutes > 0:
        try:
            delivery = datetime.fromisoformat(delivery_date.replace("T", " "))
            now = datetime.now()
            minutes_remaining = (delivery - now).total_seconds() / 60
            
            if minutes_remaining > 0:
                ratio = estimated_work_minutes / minutes_remaining
                
                if ratio > 1.0:
                    score += 50
                    reasons.append("⚠ Riesgo alto de atraso")
                elif ratio > 0.8:
                    score += 30
                    reasons.append("⚠ Riesgo de atraso")
                elif ratio > 0.5:
                    score += 15
                    reasons.append("Tiempo ajustado")
        except (ValueError, TypeError):
            pass
    
    # Factor 8: Pedido bloqueado
    pending_reason = str(order.get("pending_reason", "")).strip()
    if pending_reason:
        score -= 20
        reasons.insert(0, f"Bloqueado: {pending_reason}")
    
    # La fecha define el nivel operativo; la prioridad manual solo puede elevarlo.
    if delivery_level:
        level: PriorityLevel = delivery_level
    elif score >= 80:
        level: PriorityLevel = "Urgente"
    elif score >= 50:
        level = "Alta"
    elif score >= 25:
        level = "Media"
    elif score >= 10:
        level = "Baja"
    else:
        level = "Sin prisa"

    manual_level = {1: "Baja", 2: "Media", 3: "Alta", 4: "Urgente"}.get(manual_priority, "Sin prisa")
    if PRIORITY_RANK[manual_level] > PRIORITY_RANK[level]:
        level = manual_level
    
    # Razón principal
    main_reason = reasons[0] if reasons else "Sin información de urgencia"
    
    return level, score, main_reason


def get_priority_color(level: PriorityLevel) -> str:
    """Devuelve el color hexadecimal para cada nivel de prioridad."""
    style = PRIORITY_STYLES.get(normalize_order_style_key(level), PRIORITY_STYLES["default"])
    return style.get("accent", "#00BCD4")


def get_priority_emoji(level: PriorityLevel) -> str:
    """Devuelve un emoji representativo del nivel de prioridad."""
    emojis = {
        "Sin prisa": "🔵",
        "Baja": "🟢",
        "Media": "🟡",
        "Alta": "🟠",
        "Urgente": "🔴",
    }
    return emojis.get(level, "🔵")


def sort_orders_by_priority(orders: list[dict]) -> list[dict]:
    """
    Ordena una lista de pedidos por prioridad calculada.
    
    Los pedidos más urgentes aparecen primero.
    """
    from app.workflow.estimator import estimate_remaining_work
    
    orders_with_priority = []
    for order in orders:
        estimated_minutes = estimate_remaining_work(order)
        level, score, reason = calculate_priority(order, estimated_minutes)
        orders_with_priority.append({
            **order,
            "_priority_level": level,
            "_priority_score": score,
            "_priority_reason": reason,
            "_estimated_work_minutes": estimated_minutes,
        })
    
    # Ordenar por score descendente (más urgente primero)
    return sorted(orders_with_priority, key=lambda o: o["_priority_score"], reverse=True)
