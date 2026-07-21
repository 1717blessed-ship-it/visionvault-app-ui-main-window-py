"""Envío de notificaciones push vía Firebase Cloud Messaging."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_firebase_initialized = False


# ── Clasificación de errores FCM ─────────────────────────────────────────────

RETRYABLE_ERRORS: set[str] = {
    "internal-error",
    "server-unavailable",
    "quota-exceeded",
    "service-unavailable",
    "sender-id-mismatch",
}

PERMANENT_ERRORS: set[str] = {
    "registration-token-not-registered",
    "invalid-registration-token",
    "invalid-argument",
    "invalid-recipient",
    "invalid-sender",
    "invalid-registration",
    "invalid-apns-credential",
    "third-party-auth-error",
    "unregistered",
}


@dataclass
class SendResult:
    """Resultado de un intento de envío push."""
    success: bool = False
    message_id: str = ""
    error: str = ""
    is_permanent: bool = False
    is_retryable: bool = False
    raw_error: str = ""


@dataclass
class SendPayload:
    """Datos estructurados que viajan en el mensaje FCM."""
    event_uuid: str = ""
    event_type: str = ""
    entity_type: str = ""
    entity_id: str = ""
    priority: str = "normal"
    route: str = ""


# ── Canales Android ──────────────────────────────────────────────────────────

CHANNEL_URGENT = "doccione_urgent"
CHANNEL_ORDERS = "doccione_orders"
CHANNEL_PRODUCTION = "doccione_production"

_EVENT_CHANNEL_MAP: dict[str, str] = {
    "production.error": CHANNEL_URGENT,
    "order.deadline_near": CHANNEL_URGENT,
    "order.created": CHANNEL_ORDERS,
    "payment.received": CHANNEL_ORDERS,
    "production.completed": CHANNEL_PRODUCTION,
    "order.completed": CHANNEL_PRODUCTION,
    "stock.low": CHANNEL_PRODUCTION,
}


def _channel_for_event(event_type: str, priority: str = "normal") -> str:
    if priority == "high":
        return CHANNEL_URGENT
    return _EVENT_CHANNEL_MAP.get(event_type, CHANNEL_ORDERS)


def _priority_config(priority: str):
    """Devuelve el string de prioridad FCM-compatible."""
    if priority == "high":
        return "high"
    return "normal"


# ── Inicialización ──────────────────────────────────────────────────────────

def initialize_firebase(service_account_path: str | Path | None = None) -> bool:
    """Inicializa Firebase Admin SDK con la cuenta de servicio.

    Busca credenciales en este orden:
    1. service_account_path explícito
    2. Variable de entorno GOOGLE_APPLICATION_CREDENTIALS
    3. Archivo secrets/firebase-service-account.json relativo al proyecto

    Returns True si se inicializó correctamente, False si no está disponible.
    """
    global _firebase_initialized
    if _firebase_initialized:
        return True

    try:
        import firebase_admin
        from firebase_admin import credentials

        resolved_path = None

        if service_account_path is not None:
            resolved_path = Path(service_account_path)
        else:
            env_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
            if env_path:
                resolved_path = Path(env_path)
            else:
                resolved_path = Path(__file__).parents[2] / "secrets" / "firebase-service-account.json"

        if not resolved_path or not resolved_path.exists():
            logger.warning("Credenciales de Firebase no encontradas en: %s", resolved_path)
            return False

        cred = credentials.Certificate(str(resolved_path))
        firebase_admin.initialize_app(cred)
        _firebase_initialized = True
        logger.info("Firebase Admin SDK inicializado correctamente")
        return True
    except ImportError:
        logger.warning("firebase-admin no instalado. Ejecutá: pip install firebase-admin")
        return False
    except Exception as exc:
        logger.error("Error inicializando Firebase: %s", exc)
        return False


# ── Envío ───────────────────────────────────────────────────────────────────

def send_push(
    token: str,
    title: str,
    body: str,
    data: SendPayload | None = None,
    priority: str = "normal",
    event_type: str = "",
    collapse_key: str | None = None,
) -> SendResult:
    """Envía un mensaje push vía FCM con datos estructurados y manejo de errores.

    Args:
        token: Token FCM del dispositivo destino.
        title: Título de la notificación.
        body: Cuerpo del mensaje.
        data: Payload estructurado con routing info.
        priority: 'high' o 'normal'.
        event_type: Tipo de evento (para seleccionar canal).
        collapse_key: Clave de colapso para Android.

    Returns:
        SendResult con éxito/error y clasificación.
    """
    if not _firebase_initialized:
        return SendResult(success=False, error="Firebase no inicializado")

    try:
        from firebase_admin import messaging
    except ImportError:
        return SendResult(success=False, error="firebase-admin no instalado")

    payload_dict: dict[str, str] = {}
    if data:
        payload_dict = {
            k: str(v)
            for k, v in {
                "event_uuid": data.event_uuid,
                "event_type": data.event_type,
                "entity_type": data.entity_type,
                "entity_id": data.entity_id,
                "priority": data.priority,
                "route": data.route,
            }.items()
            if v
        }

    channel = _channel_for_event(event_type, priority)
    fcm_priority = _priority_config(priority)

    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=payload_dict,
            token=token,
            android=messaging.AndroidConfig(
                priority=fcm_priority,
                collapse_key=collapse_key,
                notification=messaging.AndroidNotification(
                    channel_id=channel,
                    sound="default",
                ),
            ),
        )
        message_id = messaging.send(message)
        logger.info("Push enviado: %s → %s... msg_id=%s", title, token[:12], message_id)
        return SendResult(success=True, message_id=message_id)

    except Exception as exc:
        raw_error = str(exc)
        is_permanent = _is_permanent_error(raw_error)
        is_retryable = _is_retryable_error(raw_error) and not is_permanent

        if is_permanent:
            logger.error("Error permanente FCM: %s — %s", title, raw_error)
        elif is_retryable:
            logger.warning("Error reintentable FCM: %s — %s", title, raw_error)
        else:
            logger.error("Error FCM desconocido: %s — %s", title, raw_error)

        return SendResult(
            success=False,
            error=raw_error,
            is_permanent=is_permanent,
            is_retryable=is_retryable,
            raw_error=raw_error,
        )


def _is_permanent_error(error_msg: str) -> bool:
    lower = error_msg.lower()
    return any(perm in lower for perm in PERMANENT_ERRORS)


def _is_retryable_error(error_msg: str) -> bool:
    lower = error_msg.lower()
    return any(ret in lower for ret in RETRYABLE_ERRORS)
