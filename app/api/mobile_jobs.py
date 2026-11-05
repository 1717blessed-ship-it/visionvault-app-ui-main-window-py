"""API HTTP para Operador Móvil - Gestión de jobs de producción.

Endpoints:
- GET /api/mobile/jobs - Listar jobs con filtros y paginación
- GET /api/mobile/jobs/{id} - Obtener detalle de un job
- POST /api/mobile/jobs/{id}/stage - Cambiar etapa de un job

Autenticación: Bearer token (session token generado durante vinculación)
"""

from __future__ import annotations

import json
import sqlite3
import hashlib
import ipaddress
import os
import tempfile
from pathlib import Path
from uuid import uuid4
import logging
import ssl
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Final
from urllib.parse import parse_qs, urlparse
from collections import defaultdict

from app.events.event_repository import EventRepository
from app.services.production_stage_service import ProductionStageService
from app.services.stage_catalog_service import (
    get_all_stages_for_mobile,
    get_workflows_for_mobile,
)
from app.services.sync_cursor_service import SyncCursorService
from app.services.mobile_runtime_config_service import (
    DEFAULT_ORDER_STATUSES,
    MobileRuntimeConfigService,
)
from app.security.mobile_access import MobileAccessRepository
from app.security.mobile_users import MobileUserRepository
from app.workflow.timeline import (
    get_current_stage,
    get_stage_progress,
    get_workflow,
    workflow_stages,
)

logger = logging.getLogger(__name__)

# Se conserva este nombre interno para integraciones que reemplazan HTTPServer
# durante pruebas; la implementación real atiende previews en paralelo.
HTTPServer = ThreadingHTTPServer

# ── Rate Limiting para seguridad ─────────────────────────────────────────
_rate_limit_store: defaultdict[str, list[datetime]] = defaultdict(list)
_rate_limit_lock = threading.Lock()
_RATE_LIMIT_REQUESTS = 100  # Máximo de requests por ventana
_RATE_LIMIT_WINDOW = timedelta(minutes=1)  # Ventana de tiempo

# Compatibilidad para integraciones que importaban estas funciones antes de
# que cada servidor recibiera su propio controlador de acceso.
_compat_access_control: MobileAccessRepository | None = None
_compat_access_lock = threading.Lock()


def load_ip_whitelist(conn) -> MobileAccessRepository:
    """Carga la configuración conservando la API histórica del módulo."""
    global _compat_access_control
    with _compat_access_lock:
        if (
            _compat_access_control is None
            or _compat_access_control.connection is not conn
        ):
            _compat_access_control = MobileAccessRepository(conn)
        else:
            _compat_access_control.reload()
        return _compat_access_control


def check_ip_whitelist(client_ip: str, endpoint: str = "") -> bool:
    """Verifica IP/CIDR usando el controlador cargado por compatibilidad."""
    with _compat_access_lock:
        if _compat_access_control is None:
            return True
        return _compat_access_control.is_allowed(client_ip, endpoint)

# ── Helpers para routing de ordenes ─────────────────────────────────────────
# /api/v1/mobile/orders/{id}/status  →  (order_id, "/status")
_ORDER_V1_PREFIX = "/api/v1/mobile/orders/"
_LOCAL_CREDENTIAL_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "10.0.0.0/8",
        "100.64.0.0/10",  # Redes VPN como Tailscale.
        "172.16.0.0/12",
        "192.168.0.0/16",
        "fc00::/7",
    )
)

def _match_order_route(path: str, suffix: str) -> bool:
    return path.startswith(_ORDER_V1_PREFIX) and path.endswith(suffix)

def _extract_order_id(path: str, suffix: str) -> int | None:
    """Extrae el order_id de una ruta /api/v1/mobile/orders/{id}/<suffix>."""
    prefix_len = len(_ORDER_V1_PREFIX)
    remainder = path[prefix_len:]                       # "{id}/suffix"
    parts = remainder.split("/")
    if len(parts) == 2 and parts[0].isdigit() and parts[1] == suffix[1:]:
        return int(parts[0])
    return None

def _match_order_job_route(path: str) -> bool:
    """True si path = /api/v1/mobile/orders/{oid}/jobs/{jid}."""
    if not path.startswith(_ORDER_V1_PREFIX):
        return False
    remainder = path[len(_ORDER_V1_PREFIX):]
    parts = remainder.split("/")
    return len(parts) == 3 and parts[1] == "jobs" and parts[0].isdigit() and parts[2].isdigit()

def _extract_order_job_ids(path: str) -> tuple[int, int] | None:
    remainder = path[len(_ORDER_V1_PREFIX):]
    parts = remainder.split("/")
    if len(parts) == 3 and parts[1] == "jobs" and parts[0].isdigit() and parts[2].isdigit():
        return int(parts[0]), int(parts[2])
    return None


# Whitelist de tipos de eventos permitidos para preferencias de notificaciones
ALLOWED_NOTIFICATION_EVENT_TYPES: Final[frozenset[str]] = frozenset({
    "job_stage_changed",
    "job_created",
    "job_assigned",
    "order_updated",
    "order_priority_changed",
    "urgent_notification",
})

def _check_rate_limit(client_ip: str) -> bool:
    """Verifica si el cliente excedió el límite de requests."""
    with _rate_limit_lock:
        now = datetime.now()
        # Limpiar requests antiguos fuera de la ventana
        _rate_limit_store[client_ip] = [
            ts for ts in _rate_limit_store[client_ip]
            if now - ts < _RATE_LIMIT_WINDOW
        ]

        # Verificar límite
        if len(_rate_limit_store[client_ip]) >= _RATE_LIMIT_REQUESTS:
            logger.warning("Rate limit exceeded for IP: %s", client_ip)
            return False

        # Registrar este request
        _rate_limit_store[client_ip].append(now)
        return True

def _get_client_ip(handler: BaseHTTPRequestHandler) -> str:
    """Obtiene la IP del socket sin confiar en cabeceras falsificables."""
    client_address = getattr(handler, "client_address", ("127.0.0.1", 0))
    return str(client_address[0])


class MobileJobsHandler(BaseHTTPRequestHandler):
    _catalog_path_cache: dict[str, str] = {}
    _catalog_path_cache_lock = threading.Lock()
    _catalog_path_cache_limit = 4096

    """Handler HTTP para API de jobs móviles."""

    def __init__(
        self,
        *args,
        event_repo: EventRepository,
        event_bus,
        access_control: MobileAccessRepository | None = None,
        mobile_users: MobileUserRepository | None = None,
        **kwargs,
    ):
        self.event_repo = event_repo
        self.event_bus = event_bus
        self.access_control = access_control or MobileAccessRepository(event_repo.conn)
        self.mobile_users = mobile_users or MobileUserRepository(event_repo.conn)
        self.stage_service = ProductionStageService(event_repo.conn, event_bus)
        super().__init__(*args, **kwargs)

    def _send_json_response(self, status_code: int, data: dict[str, Any]) -> None:
        """Envía una respuesta JSON con headers de seguridad."""
        encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(encoded)

    def _send_bytes_response(self, status_code: int, content_type: str, data: bytes) -> None:
        """Envía una vista previa binaria sin exponer archivos del equipo."""
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=86400")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(data)

    def _send_security_headers(self) -> None:
        """Agrega controles compatibles con respuestas JSON y binarias."""
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        )
        self.send_header("Referrer-Policy", "no-referrer")
        # HSTS solo tiene efecto seguro cuando esta conexión realmente usa TLS.
        if isinstance(getattr(self, "connection", None), ssl.SSLSocket):
            self.send_header(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

    def _send_error(self, status_code: int, message: str) -> None:
        """Envía un error JSON."""
        self._send_json_response(status_code, {"error": message})

    def _get_auth_token(self) -> str | None:
        """Extrae el Bearer token del header Authorization."""
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
        return None

    def _validate_auth(self) -> dict[str, Any] | None:
        """Valida la autenticación y retorna el dispositivo."""
        token = self._get_auth_token()
        if not token:
            self._audit_auth_failure("missing_token")
            self._send_error(401, "Authorization header missing")
            return None
        
        device = self.event_repo.validate_session_token(token)
        if not device:
            self._audit_auth_failure("invalid_or_expired_token")
            self._send_error(401, "Invalid or expired session token")
            return None
        
        return device

    def _mobile_access(self) -> MobileAccessRepository:
        """Devuelve el controlador compartido o crea uno para pruebas aisladas."""
        access_control = getattr(self, "access_control", None)
        if access_control is None:
            access_control = MobileAccessRepository(self.event_repo.conn)
            self.access_control = access_control
        return access_control

    def _mobile_user_repository(self) -> MobileUserRepository:
        users = getattr(self, "mobile_users", None)
        if users is None:
            users = MobileUserRepository(self.event_repo.conn)
            self.mobile_users = users
        return users

    def _allows_sensitive_credentials(self) -> bool:
        """Permite credenciales solo por TLS o desde una red no pública."""
        if isinstance(getattr(self, "connection", None), ssl.SSLSocket):
            return True
        try:
            client_ip = _get_client_ip(self).split("%", 1)[0]
            address = ipaddress.ip_address(client_ip)
        except ValueError:
            return False
        return (
            address.is_loopback
            or address.is_link_local
            or any(address in network for network in _LOCAL_CREDENTIAL_NETWORKS)
        )

    def _require_secure_credentials_transport(self) -> bool:
        if self._allows_sensitive_credentials():
            return True
        self._mobile_access().audit_event(
            "insecure_credentials_blocked",
            ip_address=_get_client_ip(self),
            endpoint=urlparse(getattr(self, "path", "")).path,
            details={"reason": "public_plain_http"},
        )
        self._send_error(
            426,
            "El inicio de sesión y el enlace requieren HTTPS fuera de la red local.",
        )
        return False

    def _audit_auth_failure(self, reason: str) -> None:
        self._mobile_access().audit_event(
            "authentication_failed",
            ip_address=_get_client_ip(self),
            endpoint=urlparse(getattr(self, "path", "")).path,
            details={"reason": reason},
        )

    def _authorize_network_request(
        self, method: str, *, rate_limit: bool = True
    ) -> str | None:
        """Aplica whitelist y rate limiting antes del routing o la autenticación."""
        client_ip = _get_client_ip(self)
        endpoint = urlparse(self.path).path
        access_control = self._mobile_access()
        if not access_control.is_allowed(client_ip, endpoint):
            self._send_error(403, "IP not authorized")
            logger.warning(
                "IP whitelist blocked %s from %s to %s",
                method,
                client_ip,
                endpoint,
            )
            return None
        if rate_limit and not _check_rate_limit(client_ip):
            access_control.audit_event(
                "rate_limit_blocked",
                ip_address=client_ip,
                endpoint=endpoint,
                details={"method": method},
            )
            self._send_error(429, "Too many requests")
            logger.warning(
                "Rate limit blocked %s from %s to %s",
                method,
                client_ip,
                endpoint,
            )
            return None
        return client_ip

    def _parse_url_params(self) -> dict[str, str]:
        """Parsea parámetros de la URL."""
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        return {k: v[0] if v else "" for k, v in params.items()}

    def _runtime_config(self) -> dict[str, Any]:
        return MobileRuntimeConfigService(self.event_repo.conn).snapshot()

    def _require_mobile_feature(self, feature: str) -> bool:
        enabled = bool(
            self._runtime_config().get("features", {}).get(feature, True)
        )
        if not enabled:
            self._send_error(
                503,
                "Esta función está temporalmente deshabilitada desde Studio.",
            )
        return enabled

    def _require_mobile_mutations(self) -> bool:
        maintenance = self._runtime_config().get("maintenance", {})
        if not maintenance.get("enabled", False):
            return True
        self._send_error(
            503,
            str(maintenance.get("message") or "Studio está en mantenimiento."),
        )
        return False

    def do_GET(self) -> None:
        if urlparse(self.path).path.startswith('/api/v1/mobile/order-sync/'):
            self._send_json_response(503, {'contract_version': 1, 'persisted': False,
                'error': {'code': 'order_sync_disabled'}})
            return
        """Maneja requests GET con rate limiting y whitelist."""
        parsed = urlparse(self.path)
        client_ip = self._authorize_network_request(
            "GET", rate_limit=parsed.path != "/api/v1/mobile/health"
        )
        if client_ip is None:
            return

        # Health check público — sin autenticación
        if parsed.path == "/api/v1/mobile/health":
            self._get_health()
            return

        # Validar autenticación
        device = self._validate_auth()
        if not device:
            logger.warning("Authentication failed for GET from %s to %s", client_ip, parsed.path)
            return
        
        # Rutas legacy (mantener compatibilidad)
        if parsed.path == "/api/mobile/jobs":
            self._list_jobs(device)
        elif parsed.path.startswith("/api/mobile/jobs/") and not parsed.path.endswith("/search"):
            job_id = parsed.path.split("/")[-1]
            if job_id.isdigit():
                self._get_job_detail(int(job_id), device)
            else:
                self._send_error(400, "Invalid job ID")
        # Rutas v1
        elif parsed.path == "/api/v1/mobile/jobs":
            self._list_jobs(device)
        elif parsed.path == "/api/v1/mobile/jobs/search":
            self._search_jobs(device)
        elif parsed.path.startswith("/api/v1/mobile/jobs/"):
            job_id = parsed.path.split("/")[-1]
            if job_id.isdigit():
                self._get_job_detail(int(job_id), device)
            else:
                self._send_error(400, "Invalid job ID")
        elif parsed.path == "/api/v1/mobile/reference/stages":
            self._get_stages()
        elif parsed.path == "/api/v1/mobile/reference/workflows":
            self._get_workflows()
        elif parsed.path == "/api/v1/mobile/reference/materials":
            self._get_materials()
        elif parsed.path == "/api/v1/mobile/device/status":
            self._get_device_status(device)
        elif parsed.path == "/api/v1/mobile/capabilities":
            self._get_capabilities()
        elif parsed.path == "/api/v1/mobile/sync/pull":
            self._sync_pull(device)
        elif parsed.path == "/api/v1/mobile/visits":
            self._list_visits(device)
        elif parsed.path == "/api/v1/mobile/visits/history":
            self._list_visit_history(device)
        elif parsed.path == "/api/v1/mobile/visits/attachments":
            self._list_visit_attachments(device)
        elif parsed.path.startswith("/api/v1/mobile/visits/attachments/"):
            self._get_visit_attachment(
                device, parsed.path.rsplit("/", 1)[-1]
            )
        elif parsed.path == "/api/v1/mobile/catalog/designs":
            if self._require_mobile_feature("design_catalog"):
                self._list_catalog_designs()
        elif parsed.path == "/api/v1/mobile/catalog/categories":
            if self._require_mobile_feature("design_catalog"):
                self._list_catalog_categories()
        elif parsed.path == "/api/v1/mobile/catalog/tags":
            if self._require_mobile_feature("design_catalog"):
                self._list_catalog_tags()
        elif parsed.path == "/api/v1/mobile/catalog/products":
            if self._require_mobile_feature("product_catalog"):
                self._list_catalog_products()
        elif parsed.path.startswith("/api/v1/mobile/catalog/previews/"):
            if self._require_mobile_feature("design_catalog"):
                self._get_catalog_preview(parsed.path.rsplit("/", 1)[-1])
        elif parsed.path.startswith("/api/v1/mobile/catalog/product-previews/"):
            if self._require_mobile_feature("product_catalog"):
                product_id = parsed.path.rsplit("/", 1)[-1]
                if product_id.isdigit():
                    self._get_product_preview(int(product_id))
                else:
                    self._send_error(400, "Invalid product ID")
        else:
            self._send_error(404, "Endpoint not found")

    def do_POST(self) -> None:
        if urlparse(self.path).path.startswith('/api/v1/mobile/order-sync/'):
            self._send_json_response(503, {'contract_version': 1, 'persisted': False,
                'error': {'code': 'order_sync_disabled'}})
            return
        """Maneja requests POST con rate limiting y whitelist."""
        parsed = urlparse(self.path)
        client_ip = self._authorize_network_request("POST")
        if client_ip is None:
            return

        # El login entrega un token temporal que solo autoriza el enlace.
        if parsed.path == "/api/v1/mobile/auth/login":
            self._login_mobile_user()
            return

        # El emparejamiento comparte el servidor de la API móvil para que la
        # app use una sola URL y un solo puerto.
        if parsed.path == "/api/pair/validate":
            self._pair_device()
            return
        if parsed.path == "/api/device/update-token":
            device = self._validate_auth()
            if device:
                self._update_device_token(device)
            return

        # Validar autenticación
        device = self._validate_auth()
        if not device:
            logger.warning("Authentication failed for POST from %s to %s", client_ip, parsed.path)
            return

        if parsed.path == "/api/v1/mobile/auth/logout":
            self._logout_mobile_device(device)
            return

        # Rutas legacy
        if parsed.path.startswith("/api/mobile/jobs/") and parsed.path.endswith("/stage"):
            if not self._require_mobile_mutations() or not self._require_mobile_feature("quick_edits"):
                return
            job_id = parsed.path.split("/")[-2]
            if job_id.isdigit():
                self._change_job_stage(int(job_id), device)
            else:
                self._send_error(400, "Invalid job ID")
        # Rutas v1
        elif parsed.path.startswith("/api/v1/mobile/jobs/") and parsed.path.endswith("/stage"):
            if not self._require_mobile_mutations() or not self._require_mobile_feature("quick_edits"):
                return
            job_id = parsed.path.split("/")[-2]
            if job_id.isdigit():
                self._change_job_stage(int(job_id), device)
            else:
                self._send_error(400, "Invalid job ID")
        elif parsed.path == "/api/v1/mobile/device/preferences":
            self._update_device_preferences(device)
        elif parsed.path == "/api/v1/mobile/visits":
            if self._require_mobile_mutations():
                self._upsert_visit(device)
        elif parsed.path == "/api/v1/mobile/visits/delete":
            if self._require_mobile_mutations():
                self._delete_visit(device)
        elif parsed.path == "/api/v1/mobile/visits/history":
            if self._require_mobile_mutations():
                self._upsert_visit_history(device)
        elif parsed.path == "/api/v1/mobile/visits/attachments":
            if self._require_mobile_mutations():
                self._upload_visit_attachment(device)
        elif _match_order_route(parsed.path, "/deliver"):
            if not self._require_mobile_mutations() or not self._require_mobile_feature("quick_edits"):
                return
            order_id = _extract_order_id(parsed.path, "/deliver")
            if order_id is not None:
                self._mark_delivered(order_id, device)
            else:
                self._send_error(400, "Invalid order ID")
        elif _match_order_route(parsed.path, "/payments"):
            if not self._require_mobile_mutations() or not self._require_mobile_feature("payments"):
                return
            order_id = _extract_order_id(parsed.path, "/payments")
            if order_id is not None:
                self._register_payment(order_id, device)
            else:
                self._send_error(400, "Invalid order ID")
        elif parsed.path == "/api/v1/mobile/catalog/quote":
            if self._require_mobile_feature("design_catalog"):
                self._quote_catalog_order()
        elif parsed.path == "/api/v1/mobile/catalog/product-orders":
            if (
                self._require_mobile_mutations()
                and self._require_mobile_feature("product_catalog")
            ):
                self._create_product_order(device)
        elif parsed.path == "/api/v1/mobile/catalog/product-quote":
            if self._require_mobile_feature("product_catalog"):
                self._quote_product_order()
        elif parsed.path == "/api/v1/mobile/catalog/orders":
            if (
                self._require_mobile_mutations()
                and self._require_mobile_feature("design_catalog")
            ):
                self._create_catalog_order(device)
        elif parsed.path == "/api/v1/mobile/sticker-orders/quote":
            if self._require_mobile_feature("sticker_orders"):
                self._quote_sticker_order()
        elif parsed.path == "/api/v1/mobile/sticker-orders":
            if (
                self._require_mobile_mutations()
                and self._require_mobile_feature("sticker_orders")
            ):
                self._create_sticker_order(device)
        elif parsed.path == "/api/v1/mobile/fotocopias/analyze-pdf":
            if self._require_mobile_feature("product_catalog"):
                self._analyze_fotocopia_pdf()
        else:
            self._send_error(404, "Endpoint not found")

    # ── Catálogo móvil ────────────────────────────────────────────────────

    @staticmethod
    def _valid_image_signature(payload: bytes, mime: str) -> bool:
        if mime == "image/jpeg":
            return payload.startswith(b"\xff\xd8\xff")
        if mime == "image/png":
            return payload.startswith(b"\x89PNG\r\n\x1a\n")
        if mime == "image/webp":
            return len(payload) >= 12 and payload.startswith(b"RIFF") and payload[8:12] == b"WEBP"
        return False

    def _read_multipart_images(self) -> tuple[dict[str, Any] | None, list[tuple[str, bytes, str]] | None, list[tuple[str, bytes, str]] | None]:
        """Reads a phone multipart upload without accepting device paths."""
        content_type = self.headers.get("Content-Type", "")
        if "boundary=" not in content_type:
            self._send_error(400, "multipart/form-data is required")
            return None, None, None
        boundary = content_type.split("boundary=", 1)[1].strip().strip('"').encode()
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length < 1 or length > 50 * 1024 * 1024:
            self._send_error(413, "El pedido admite hasta 50 MB de imágenes")
            return None, None, None
        metadata = None
        images: list[tuple[str, bytes, str]] = []
        reference_images: list[tuple[str, bytes, str]] = []
        for part in self.rfile.read(length).split(b"--" + boundary):
            if b"\r\n\r\n" not in part:
                continue
            raw_headers, value = part.split(b"\r\n\r\n", 1)
            value = value.rstrip(b"\r\n-")
            headers = raw_headers.decode("utf-8", errors="replace")
            if 'name="metadata"' in headers:
                try:
                    metadata = json.loads(value.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._send_error(400, "Los datos del pedido no son válidos")
                    return None, None, None
            elif 'name="images"' in headers and 'filename="' in headers:
                filename = headers.split('filename="', 1)[1].split('"', 1)[0]
                mime = next((line.split(":", 1)[1].strip().lower() for line in headers.split("\r\n") if line.lower().startswith("content-type:")), "image/jpeg")
                if mime not in {"image/jpeg", "image/png", "image/webp"} or not self._valid_image_signature(value, mime):
                    self._send_error(400, "Solo se admiten imágenes JPG, PNG o WEBP")
                    return None, None, None
                images.append((filename, value, mime))
            elif 'name="reference_images"' in headers and 'filename="' in headers:
                filename = headers.split('filename="', 1)[1].split('"', 1)[0]
                mime = next((line.split(":", 1)[1].strip().lower() for line in headers.split("\r\n") if line.lower().startswith("content-type:")), "image/jpeg")
                if mime not in {"image/jpeg", "image/png", "image/webp"} or not self._valid_image_signature(value, mime):
                    self._send_error(400, "Solo se admiten imágenes JPG, PNG o WEBP")
                    return None, None, None
                reference_images.append((filename, value, mime))
        if not isinstance(metadata, dict) or len(images) > 30 or len(reference_images) > 10:
            self._send_error(400, "El pedido debe incluir datos válidos y hasta 30 imágenes")
            return None, None, None
        return metadata, images, reference_images

    def _analyze_fotocopia_pdf(self) -> None:
        """Analiza un PDF enviado por el móvil con el mismo cotizador de Studio."""
        content_type = self.headers.get("Content-Type", "")
        if "boundary=" not in content_type:
            self._send_error(400, "multipart/form-data is required")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length < 1 or length > 50 * 1024 * 1024:
            self._send_error(413, "El PDF admite hasta 50 MB")
            return
        boundary = content_type.split("boundary=", 1)[1].strip().strip('"').encode()
        fields: dict[str, str] = {}
        pdf_data: bytes | None = None
        for part in self.rfile.read(length).split(b"--" + boundary):
            if b"\r\n\r\n" not in part:
                continue
            raw_headers, value = part.split(b"\r\n\r\n", 1)
            value = value.rstrip(b"\r\n-")
            headers = raw_headers.decode("utf-8", errors="replace")
            if 'name="pdf"' in headers and 'filename="' in headers:
                pdf_data = value
            elif 'name="' in headers:
                name = headers.split('name="', 1)[1].split('"', 1)[0]
                fields[name] = value.decode("utf-8", errors="replace")
        if not pdf_data or not pdf_data.lstrip().startswith(b"%PDF"):
            self._send_error(400, "Seleccioná un archivo PDF válido")
            return
        try:
            copies = max(1, min(9999, int(fields.get("copies", "1"))))
            duplex = fields.get("duplex", "false").lower() == "true"
        except ValueError:
            self._send_error(400, "La cantidad de copias no es válida")
            return
        path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp:
                temp.write(pdf_data)
                path = temp.name
            from app.services.fotocopia_pricing_service import FotocopiaPricingService
            from app.services.pdf_print_analysis_service import PdfPrintAnalysisService
            analyzer = PdfPrintAnalysisService()
            pages = analyzer.analyze(path)
            pricing = FotocopiaPricingService(self.event_repo.conn)
            codes = ("fotocopia_bn_simple", "fotocopia_bn_doble", "fotocopia_color_simple", "fotocopia_color_doble")
            quote = analyzer.quote(pages, copies=copies, duplex=duplex,
                                   unit_prices={code: pricing._get_unit_price(code) for code in codes})
        except Exception:
            logger.exception("No se pudo analizar el PDF de fotocopias")
            self._send_error(422, "No se pudo analizar el PDF. Verificá que no esté dañado o protegido.")
            return
        finally:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        self._send_json_response(200, {
            "pages": len(quote.pages), "color_pages": quote.color_pages,
            "copies": quote.copies, "duplex": quote.duplex,
            "quantities": quote.quantities, "total": quote.total,
            "page_analysis": [
                {
                    "page_number": page.page_number,
                    "is_color": page.is_color,
                    "color_coverage_percent": page.color_coverage_percent,
                    "ink_coverage_percent": page.ink_coverage_percent,
                }
                for page in quote.pages
            ],
        })

    def _sticker_quote(self, mode: Any, design_count: Any) -> tuple[dict[str, Any] | None, str | None]:
        """Cotiza el pedido móvil con las reglas comerciales de Studio.

        Los formatos de plancha se cotizan como una unidad. Los individuales
        usan la regla estándar de sticker de 5 cm y la cantidad de diseños.
        Los formatos sin una regla configurada se devuelven como pendientes de
        cotización en vez de inventar un importe en el teléfono.
        """
        mode = str(mode or "").strip()
        valid_modes = {"Plancha A4", "Plancha A5", "Franja", "Individuales"}
        if mode not in valid_modes:
            return None, "Indicá un formato válido"
        try:
            count = int(design_count)
        except (TypeError, ValueError):
            return None, "La cantidad de diseños no es válida"
        if count < 1 or count > 60:
            return None, "Agregá entre 1 y 60 diseños o imágenes"

        size = {"Plancha A4": "A4", "Plancha A5": "A5", "Franja": "Franja", "Individuales": "5cm"}[mode]
        billable_quantity = count if mode == "Individuales" else 1
        product_code = "sticker_troquelado" if mode == "Individuales" else "plancha_a4" if mode == "Plancha A4" else None
        params: list[Any] = [size, billable_quantity, billable_quantity]
        product_filter = ""
        if product_code:
            product_filter = " AND product_id = (SELECT id FROM products WHERE code = ?)"
            params.append(product_code)
        rows = [dict(row) for row in self.event_repo.conn.execute(
            """SELECT * FROM price_rules
               WHERE active = 1 AND size = ? COLLATE NOCASE
                 AND min_quantity <= ?
                 AND (max_quantity IS NULL OR max_quantity >= ?)""" + product_filter,
            params,
        )]
        if mode == "Plancha A4":
            standard = [row for row in rows if str(row.get("material") or "").casefold() == "vinilo estándar"]
            design_only = [row for row in rows if "diseño único" in str(row.get("material") or "").casefold()]
            rows = standard or design_only or rows
        if not rows:
            return {
                "mode": mode, "design_count": count, "matched": False, "subtotal": 0.0,
                "total": 0.0, "warning": "No hay una regla de precio configurada para este formato.",
            }, None
        rule = max(rows, key=lambda row: (int(row.get("priority") or 0), int(row.get("min_quantity") or 1), int(row["id"])))
        calculation_type = str(rule.get("price_mode") or "fijo").casefold()
        price = round(float(rule.get("price") or 0), 2)
        total = price if calculation_type in {"fijo", "pack"} else round(price * billable_quantity, 2)
        return {
            "mode": mode, "design_count": count, "matched": True,
            "rule_name": str(rule.get("rule_name") or rule.get("material") or "Regla de precio"),
            "subtotal": total, "total": total,
        }, None

    def _quote_sticker_order(self) -> None:
        data = self._read_json_body()
        if data is None:
            return
        quote, error = self._sticker_quote(data.get("mode"), data.get("design_count"))
        if error:
            self._send_error(400, error)
            return
        self._send_json_response(200, quote or {})

    def _create_sticker_order(self, device: dict[str, Any]) -> None:
        """Creates one Studio order that can mix catalog and phone designs."""
        data, uploaded, reference_images = self._read_multipart_images()
        if data is None or uploaded is None or reference_images is None:
            return
        client, mode = str(data.get("client") or "").strip()[:120], str(data.get("mode") or "").strip()
        valid_modes = {"Plancha A4", "Plancha A5", "Franja", "Individuales"}
        catalog_ids = data.get("catalog_design_ids") or []
        reference_metadata = data.get("reference_metadata") or []
        request_id = str(data.get("client_request_id") or "").strip()
        if not request_id or len(request_id) > 80:
            self._send_error(400, "client_request_id is required")
            return
        existing = self.event_repo.conn.execute(
            "SELECT id FROM orders WHERE creator_device_id = ? AND mobile_request_id = ? LIMIT 1",
            (device["id"], request_id),
        ).fetchone()
        if existing:
            self._send_json_response(200, {"success": True, "order_id": int(existing["id"]), "already_received": True})
            return
        if (not client or mode not in valid_modes or not isinstance(catalog_ids, list)
                or len(catalog_ids) > 30 or not isinstance(reference_metadata, list)
                or len(reference_metadata) != len(reference_images)):
            self._send_error(400, "Indicá cliente, formato y diseños válidos")
            return
        catalog_ids = list(dict.fromkeys(str(item) for item in catalog_ids))
        catalog_paths = []
        for design_id in catalog_ids:
            design = self._catalog_design_by_id(str(design_id))
            if not design:
                self._send_error(400, "Un diseño del catálogo ya no está disponible")
                return
            catalog_paths.append(str(design["path"]))
        if not catalog_paths and not uploaded:
            self._send_error(400, "Agregá al menos una imagen o un diseño del catálogo")
            return
        quote, quote_error = self._sticker_quote(mode, len(catalog_paths) + len(uploaded))
        if quote_error:
            self._send_error(400, quote_error)
            return
        now = datetime.now().isoformat(timespec="seconds")
        db_file = self.event_repo.conn.execute("PRAGMA database_list").fetchone()[2]
        upload_dir = Path(db_file).resolve().parent / "mobile_uploads"
        suffixes = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
        saved_paths: list[str] = []
        saved_reference_paths: list[str] = []
        saved_reference_entries: list[dict[str, Any]] = []
        try:
            upload_dir.mkdir(parents=True, exist_ok=True)
            for original_name, payload, mime in uploaded:
                name = Path(original_name).stem[:60] or "imagen"
                target = upload_dir / f"{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex}_{name}{suffixes[mime]}"
                target.write_bytes(payload)
                saved_paths.append(str(target))
            for reference_index, (original_name, payload, mime) in enumerate(reference_images):
                name = Path(original_name).stem[:60] or "mockup"
                target = upload_dir / f"mockup_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex}_{name}{suffixes[mime]}"
                target.write_bytes(payload)
                saved_reference_paths.append(str(target))
                raw_meta = reference_metadata[reference_index]
                if not isinstance(raw_meta, dict):
                    raw_meta = {}
                surface = str(raw_meta.get("surface") or "other")[:30]
                approval = str(raw_meta.get("approval") or "pending")[:30]
                try:
                    size_cm = float(raw_meta.get("size_cm") or 10)
                except (TypeError, ValueError):
                    size_cm = 10.0
                saved_reference_entries.append({
                    "path": str(target),
                    "name": target.name,
                    "design_id": str(raw_meta.get("design_id") or "")[:80],
                    "design_name": str(raw_meta.get("design_name") or "Diseño")[:120],
                    "size_cm": max(3.0, min(29.0, size_cm)),
                    "surface": surface if surface in {"floor", "wall", "notebook", "box", "glass", "bottle", "other"} else "other",
                    "surface_label": str(raw_meta.get("surface_label") or "Otra")[:40],
                    "material": str(raw_meta.get("material") or "Sin especificar")[:80],
                    "comment": str(raw_meta.get("comment") or "")[:500],
                    "approval": approval if approval in {"pending", "approved", "changesRequested"} else "pending",
                    "approval_label": str(raw_meta.get("approval_label") or "Pendiente")[:40],
                    "curved": bool(raw_meta.get("curved")),
                    "created_at": str(raw_meta.get("created_at") or now)[:40],
                })
            whatsapp = str(data.get("whatsapp") or "").strip()[:40]
            observations = str(data.get("observations") or "").strip()[:2000]
            total_designs = len(catalog_paths) + len(saved_paths)
            quoted_total = float((quote or {}).get("total") or 0)
            with self.event_repo.conn:
                row = self.event_repo.conn.execute("SELECT id FROM clients WHERE name = ? COLLATE NOCASE AND whatsapp = ? LIMIT 1", (client, whatsapp)).fetchone()
                client_id = int(row["id"]) if row else int(self.event_repo.conn.execute("INSERT INTO clients(name, whatsapp, created_at, updated_at) VALUES(?, ?, ?, ?)", (client, whatsapp, now, now)).lastrowid)
                order_id = int(self.event_repo.conn.execute("""INSERT INTO orders(client, whatsapp, client_id, order_date, status, material, size, quantity, price, budget_total, observations, order_concept, order_description, creator_device_id, mobile_request_id, created_at, updated_at, last_autosave_at)
                    VALUES(?, ?, ?, ?, 'Nuevo', 'Stickers', ?, ?, ?, ?, ?, 'Pedido de stickers móvil', ?, ?, ?, ?, ?, ?)""", (client, whatsapp, client_id, now, mode, total_designs, quoted_total, quoted_total, observations, f"{mode}: {len(catalog_paths)} de catálogo y {len(saved_paths)} del celular", device["id"], request_id, now, now, now)).lastrowid)
                self.event_repo.conn.execute("""INSERT INTO order_jobs(order_id, title, material, size, quantity, subtotal, final_price, status, notes, sort_order, created_at, updated_at)
                    VALUES(?, ?, 'Stickers', ?, ?, ?, ?, 'Recibido', 'Creado desde Doccione Mobile', 0, ?, ?)""", (order_id, mode, mode, total_designs, quoted_total, quoted_total, now, now))
                for path in saved_paths:
                    stat = os.stat(path)
                    self.event_repo.conn.execute("INSERT INTO images(path, name, extension, size, modified, caption) VALUES(?, ?, ?, ?, ?, ?) ON CONFLICT(path) DO NOTHING", (path, Path(path).name, Path(path).suffix.lower(), stat.st_size, stat.st_mtime, "Imagen recibida desde Doccione Mobile"))
                for path in catalog_paths:
                    self.event_repo.conn.execute(
                        """INSERT INTO order_designs(
                               order_id, image_path, quantity, size_cm, status, source
                           ) VALUES(?, ?, 1, 0, 'Pendiente', 'catalog')""",
                        (order_id, path),
                    )
                if saved_reference_paths:
                    self.event_repo.conn.execute("INSERT INTO order_events(order_id, event_type, message, data_json, created_at) VALUES(?, 'order.mockups.mobile', ?, ?, ?)", (order_id, f"{len(saved_reference_paths)} mockup(s) de referencia recibidos desde móvil", json.dumps({"paths": saved_reference_paths, "count": len(saved_reference_paths), "names": [Path(path).name for path in saved_reference_paths], "mockups": saved_reference_entries}, ensure_ascii=False), now))
                for path in saved_paths:
                    self.event_repo.conn.execute(
                        """INSERT INTO order_designs(
                               order_id, image_path, quantity, size_cm, status, source
                           ) VALUES(?, ?, 1, 0, 'Pendiente', 'mobile')""",
                        (order_id, path),
                    )
                self.event_repo.conn.execute("INSERT INTO order_events(order_id, event_type, message, data_json, created_at) VALUES(?, 'order.created.mobile_stickers', ?, ?, ?)", (order_id, "Pedido de stickers recibido desde móvil", json.dumps({"device_id": device["id"], "mode": mode, "catalog_designs": len(catalog_paths), "uploaded_images": len(saved_paths)}), now))
            self.event_bus.publish(event_type="order.created", priority="high", title="Nuevo pedido de stickers", message=f"Pedido #{order_id} · {client}", entity_type="order", entity_id=order_id, payload={"source": "mobile_stickers", "device_id": device["id"]})
            self._send_json_response(201, {"success": True, "order_id": order_id})
        except Exception as error:
            for path in saved_paths + saved_reference_paths:
                try: Path(path).unlink(missing_ok=True)
                except OSError: pass
            logger.exception("Error creating mobile sticker order")
            self._send_error(500, f"No se pudo crear el pedido: {error}")

    @staticmethod
    def _catalog_design_id(path: str) -> str:
        """Identificador opaco y estable: el móvil nunca recibe la ruta real."""
        return hashlib.sha256(path.encode("utf-8", errors="surrogatepass")).hexdigest()[:24]

    def _catalog_query(
        self,
        extra_where: str = "",
        params: list[Any] | None = None,
        recent: bool = False,
        random_order: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Obtiene diseños publicados según la configuración comercial de Studio."""
        mode_row = self.event_repo.conn.execute(
            "SELECT setting_value FROM app_settings WHERE setting_key = 'mobile_catalog.access_mode'"
        ).fetchone()
        access_mode = str(mode_row[0]) if mode_row else "all"
        visibility = "1 = 1" if access_mode == "all" else "images.is_reusable = 1 AND images.is_private = 0"
        sql = """
            SELECT images.path, images.name, images.category, images.caption,
                   images.modified, images.visible_width, images.visible_height,
                   (SELECT GROUP_CONCAT(catalog_tags.name, ' · ')
                      FROM image_tags AS catalog_links
                      JOIN tags AS catalog_tags ON catalog_tags.id = catalog_links.tag_id
                     WHERE catalog_links.image_path = images.path) AS tags
            FROM images
            WHERE """ + visibility
        if extra_where:
            sql += f" AND ({extra_where})"
        sql += " ORDER BY " + ("RANDOM()" if random_order else ("images.modified DESC" if recent else "images.name COLLATE NOCASE"))
        query_params = list(params or [])
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            query_params.extend((max(1, int(limit)), max(0, int(offset))))
        return [dict(row) for row in self.event_repo.conn.execute(sql, query_params)]

    @classmethod
    def _remember_catalog_path(cls, design_id: str, path: str) -> None:
        """Recuerda una ruta autorizada sin volver a recorrer toda la biblioteca."""
        with cls._catalog_path_cache_lock:
            cls._catalog_path_cache[design_id] = path
            while len(cls._catalog_path_cache) > cls._catalog_path_cache_limit:
                cls._catalog_path_cache.pop(next(iter(cls._catalog_path_cache)))

    def _catalog_design_for_path(self, path: str) -> dict[str, Any] | None:
        visibility = self._catalog_visibility_sql()
        row = self.event_repo.conn.execute(
            """SELECT images.path, images.name, images.category, images.caption,
                      images.modified, images.visible_width, images.visible_height,
                      (SELECT GROUP_CONCAT(catalog_tags.name, ' · ')
                         FROM image_tags AS catalog_links
                         JOIN tags AS catalog_tags ON catalog_tags.id = catalog_links.tag_id
                        WHERE catalog_links.image_path = images.path) AS tags
               FROM images
               WHERE images.path = ? AND """
            + visibility,
            (path,),
        ).fetchone()
        return dict(row) if row else None

    def _catalog_design_by_id(self, design_id: str) -> dict[str, Any] | None:
        if len(design_id) != 24 or any(char not in "0123456789abcdef" for char in design_id):
            return None
        with self._catalog_path_cache_lock:
            cached_path = self._catalog_path_cache.get(design_id)
        if cached_path:
            design = self._catalog_design_for_path(cached_path)
            if design:
                return design

        visibility = self._catalog_visibility_sql()
        rows = self.event_repo.conn.execute(
            "SELECT path FROM images WHERE " + visibility
        )
        for row in rows:
            path = str(row["path"])
            if self._catalog_design_id(path) == design_id:
                self._remember_catalog_path(design_id, path)
                return self._catalog_design_for_path(path)
        return None

    @staticmethod
    def _catalog_tags(raw_tags: str | None) -> list[str]:
        if not raw_tags:
            return []
        return [tag.strip() for tag in raw_tags.split(" · ") if tag.strip()]

    def _catalog_payload(self, design: dict[str, Any]) -> dict[str, Any]:
        design_id = self._catalog_design_id(str(design["path"]))
        self._remember_catalog_path(design_id, str(design["path"]))
        modified = float(design.get("modified") or 0)
        return {
            "id": design_id,
            "name": str(design.get("name") or "Diseño"),
            "category": str(design.get("category") or "Sin categoría"),
            "caption": str(design.get("caption") or ""),
            "tags": self._catalog_tags(design.get("tags")),
            "visible_width": int(design.get("visible_width") or 0),
            "visible_height": int(design.get("visible_height") or 0),
            "modified_ms": int(modified * 1000),
            "preview_url": (
                f"/api/v1/mobile/catalog/previews/{design_id}"
                f"?v={int(modified * 1000)}&render=2"
            ),
        }

    def _list_catalog_designs(self) -> None:
        params = self._parse_url_params()
        query = params.get("q", "").strip()
        category = params.get("category", "").strip()
        tag = params.get("tag", "").strip()
        recent = params.get("recent", "") == "1"
        random_order = params.get("random", "") == "1"
        runtime_config = MobileRuntimeConfigService(self.event_repo.conn)
        default_limit = runtime_config.catalog_page_size()
        try:
            limit = min(500, max(1, int(params.get("limit", str(default_limit)))))
            offset = max(0, int(params.get("offset", "0")))
        except ValueError:
            self._send_error(400, "limit and offset must be integers")
            return
        if len(query) > 100 or len(category) > 100 or len(tag) > 100:
            self._send_error(400, "Catalog filter is too long")
            return

        clauses: list[str] = []
        values: list[Any] = []
        if query:
            pattern = f"%{query}%"
            clauses.append(
                """(images.name LIKE ? OR images.caption LIKE ? OR images.category LIKE ?
                    OR EXISTS (
                        SELECT 1
                          FROM image_tags AS search_links
                          JOIN tags AS search_tags ON search_tags.id = search_links.tag_id
                         WHERE search_links.image_path = images.path
                           AND search_tags.name LIKE ?
                    ))"""
            )
            values.extend([pattern, pattern, pattern, pattern])
        if category:
            clauses.append("images.category = ?")
            values.append(category)
        if tag:
            clauses.append(
                """EXISTS (
                       SELECT 1
                         FROM image_tags AS filter_links
                         JOIN tags AS filter_tags ON filter_tags.id = filter_links.tag_id
                        WHERE filter_links.image_path = images.path
                          AND filter_tags.name = ?
                   )"""
            )
            values.append(tag)
        try:
            rows = self._catalog_query(
                " AND ".join(clauses),
                values,
                recent=recent,
                random_order=random_order,
                limit=limit + 1,
                offset=offset,
            )
            has_more = len(rows) > limit
            rows = rows[:limit]
            self._send_json_response(200, {
                "designs": [self._catalog_payload(row) for row in rows],
                "count": len(rows),
                "has_more": has_more,
                "next_offset": offset + len(rows) if has_more else None,
            })
        except Exception as error:
            logger.exception("Error listing mobile catalog")
            self._send_error(500, f"Error listing catalog: {error}")

    def _list_catalog_categories(self) -> None:
        try:
            visibility = self._catalog_visibility_sql()
            rows = self.event_repo.conn.execute(
                """SELECT category, COUNT(*) AS count FROM images
                   WHERE """ + visibility + """ AND category <> ''
                   GROUP BY category ORDER BY category COLLATE NOCASE"""
            ).fetchall()
            self._send_json_response(200, {"categories": [dict(row) for row in rows]})
        except Exception as error:
            logger.exception("Error listing catalog categories")
            self._send_error(500, f"Error listing categories: {error}")

    def _list_catalog_tags(self) -> None:
        try:
            visibility = self._catalog_visibility_sql()
            rows = self.event_repo.conn.execute(
                """SELECT tags.name, COUNT(*) AS count FROM tags
                   JOIN image_tags ON image_tags.tag_id = tags.id
                   JOIN images ON images.path = image_tags.image_path
                   WHERE """ + visibility + """
                   GROUP BY tags.id ORDER BY count DESC, tags.name COLLATE NOCASE LIMIT 100"""
            ).fetchall()
            self._send_json_response(200, {"tags": [dict(row) for row in rows]})
        except Exception as error:
            logger.exception("Error listing catalog tags")
            self._send_error(500, f"Error listing tags: {error}")

    def _list_catalog_products(self) -> None:
        """Publica todos los productos activos configurados por Studio.

        No mantiene una segunda lista para el teléfono: desactivar un producto
        en Studio lo quita inmediatamente del POS móvil.
        """
        try:
            rows = self.event_repo.conn.execute(
                """SELECT p.id, p.code, p.name, p.description, p.category, p.image_path, p.base_price,
                          COUNT(DISTINCT r.id) AS price_rules,
                          GROUP_CONCAT(DISTINCT NULLIF(r.material, '')) AS materials,
                          MIN(r.price) AS min_price,
                          MAX(r.price) AS max_price
                   FROM products p
                   LEFT JOIN price_rules r ON r.product_id = p.id AND r.active = 1
                   WHERE p.active = 1
                   GROUP BY p.id
                   ORDER BY p.name COLLATE NOCASE"""
            ).fetchall()
            products = []
            for row in rows:
                options = [dict(option) for option in self.event_repo.conn.execute(
                    """SELECT COALESCE(v.code, '') AS variant_code, COALESCE(v.name, '') AS variant_name,
                              COALESCE(r.material, '') AS material, COALESCE(r.size, '') AS size,
                              COALESCE(r.price, 0) AS price
                       FROM price_rules r LEFT JOIN product_variants v ON v.id = r.variant_id
                       WHERE r.product_id = ? AND r.active = 1
                       GROUP BY v.code, v.name, r.material, r.size, r.price
                       ORDER BY v.name, r.material, r.size""", (row["id"],)
                )]
                products.append({
                "id": int(row["id"]),
                "code": str(row["code"]),
                "name": str(row["name"]),
                "description": str(row["description"] or ""),
                "category": str(row["category"] or ""),
                "image_path": self._product_preview_url(
                    int(row["id"]), str(row["image_path"] or "")
                ),
                "base_price": float(row["base_price"] or 0),
                "price_rules": int(row["price_rules"] or 0),
                "materials": [value.strip() for value in str(row["materials"] or "").split(",") if value.strip()],
                "min_price": float(row["min_price"] or 0) if row["min_price"] else None,
                "max_price": float(row["max_price"] or 0) if row["max_price"] else None,
                "options": options,
                })
            self._send_json_response(200, {"products": products})
        except Exception as error:
            logger.exception("Error listing mobile catalog products")
            self._send_error(500, f"Error listing products: {error}")

    @staticmethod
    def _product_preview_url(product_id: int, image_path: str) -> str:
        if not image_path:
            return ""
        try:
            version = int(Path(image_path).stat().st_mtime_ns)
        except OSError:
            version = 0
        return (
            f"/api/v1/mobile/catalog/product-previews/{int(product_id)}"
            f"?v={version}&render=1"
        )

    def _get_product_preview(self, product_id: int) -> None:
        row = self.event_repo.conn.execute(
            "SELECT image_path FROM products WHERE id = ? AND active = 1",
            (int(product_id),),
        ).fetchone()
        image_path = str(row["image_path"] or "") if row else ""
        if not image_path or not Path(image_path).is_file():
            self._send_error(404, "Product preview is not available")
            return
        try:
            from app.indexer.thumbnails import thumbnail_png_bytes

            data = thumbnail_png_bytes(
                image_path,
                640,
                360,
                Path(image_path).stat().st_mtime,
                upscale=False,
                trim_transparency=False,
            )
            self._send_bytes_response(200, "image/png", data)
        except Exception as error:
            logger.warning(
                "Product preview unavailable for %s: %s", product_id, error
            )
            self._send_error(404, "Product preview is not available")

    def _catalog_visibility_sql(self) -> str:
        row = self.event_repo.conn.execute(
            "SELECT setting_value FROM app_settings WHERE setting_key = 'mobile_catalog.access_mode'"
        ).fetchone()
        return "images.is_reusable = 1 AND images.is_private = 0" if row and str(row[0]) == "selected" else "1 = 1"

    def _get_catalog_preview(self, design_id: str) -> None:
        design = self._catalog_design_by_id(design_id)
        if not design:
            self._send_error(404, "Catalog design not found")
            return
        try:
            from app.indexer.thumbnails import thumbnail_png_bytes

            data = thumbnail_png_bytes(
                str(design["path"]),
                320,
                320,
                float(design["modified"]),
                upscale=True,
                trim_transparency=True,
            )
            self._send_bytes_response(200, "image/png", data)
        except Exception as error:
            logger.warning("Catalog preview unavailable for %s: %s", design_id, error)
            self._send_error(404, "Preview is not available")

    def _prepare_catalog_items(self, items: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
        """Valida el carrito y vuelve a resolver los diseños autorizados en Studio."""
        if not isinstance(items, list) or not items or len(items) > 30:
            return None, "items must contain between 1 and 30 designs"
        prepared: list[dict[str, Any]] = []
        for position, item in enumerate(items):
            if not isinstance(item, dict):
                return None, "Invalid catalog item"
            design = self._catalog_design_by_id(str(item.get("design_id") or ""))
            if not design:
                return None, "A selected design is no longer available"
            try:
                quantity = int(item.get("quantity", 1))
            except (TypeError, ValueError):
                return None, "quantity must be a positive integer"
            if quantity < 1 or quantity > 10000:
                return None, "quantity must be between 1 and 10000"
            material = str(item.get("material") or "").strip()[:120]
            # El catálogo de stickers se cotiza por medida. Para compatibilidad
            # con carritos creados antes del POS, una medida vacía usa 5 cm.
            size = str(item.get("size") or "").strip()[:40] or "5cm"
            if not material:
                return None, "material is required for every design"
            prepared.append({
                "path": str(design["path"]), "name": str(design["name"]),
                "material": material, "size": size, "quantity": quantity, "position": position,
            })
        return prepared, None

    def _catalog_price(self, item: dict[str, Any]) -> dict[str, Any]:
        """Calcula el precio con price_rules; el importe del teléfono nunca es aceptado."""
        material, size, quantity = item["material"], item["size"], item["quantity"]
        rows = [dict(row) for row in self.event_repo.conn.execute(
            """SELECT * FROM price_rules WHERE active = 1
               AND (material = '' OR material = ? COLLATE NOCASE)
               AND (size = '' OR size = ? COLLATE NOCASE)""", (material, size)
        )]
        rows = [row for row in rows if int(row.get("min_quantity") or 1) <= quantity
                and (row.get("max_quantity") is None or quantity <= int(row["max_quantity"]))]
        regular = [row for row in rows if str(row.get("price_mode") or "fijo").casefold() != "pack"]
        packs = [row for row in rows if str(row.get("price_mode") or "").casefold() == "pack"
                 and int(row.get("pack_quantity") or 1) == quantity]
        candidates = regular or packs
        if not candidates:
            return {"matched": False, "warning": "No existe una regla de precio para esta selección."}
        rule = max(candidates, key=lambda row: (
            int(row.get("priority") or 0),
            int(bool(row.get("material"))), int(bool(row.get("size"))),
            int(row.get("min_quantity") or 1), int(row["id"]),
        ))
        mode = str(rule.get("price_mode") or "fijo").casefold()
        price = round(float(rule.get("price") or 0), 2)
        subtotal = price if mode in {"fijo", "pack"} else round(price * quantity, 2)
        discount = min(100.0, max(0.0, round(float(rule.get("discount_percent") or 0), 2)))
        discount_amount = round(subtotal * discount / 100, 2)
        return {
            "matched": True, "rule_id": int(rule["id"]),
            "rule_name": str(rule.get("rule_name") or rule.get("extra_service") or rule.get("material") or "Regla de precio"),
            "calculation_type": mode, "unit_price": price if mode == "unitario" else None,
            "fixed_total": price if mode in {"fijo", "pack"} else None,
            "subtotal": subtotal, "discount_percent": discount,
            "discount_amount": discount_amount,
            "total": round(subtotal - discount_amount, 2),
        }

    def _catalog_quote(
        self, items: Any, _ignored_discount_percent: Any = None
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Cotiza usando únicamente precios y descuentos configurados en Studio.

        El segundo argumento se conserva temporalmente para clientes y pruebas
        anteriores, pero nunca se usa como fuente de un descuento.
        """
        prepared, error = self._prepare_catalog_items(items)
        if error:
            return None, error
        lines, warnings = [], []
        for item in prepared or []:
            price = self._catalog_price(item)
            line = {"design_name": item["name"], "material": item["material"], "size": item["size"],
                    "quantity": item["quantity"], **price}
            lines.append(line)
            if not price["matched"]:
                warning = price["warning"]
                if warning not in warnings:
                    warnings.append(warning)
        subtotal = round(sum(float(line.get("subtotal") or 0) for line in lines), 2)
        discount_amount = round(sum(float(line.get("discount_amount") or 0) for line in lines), 2)
        total = round(sum(float(line.get("total") or 0) for line in lines), 2)
        effective_discount = round(discount_amount * 100 / subtotal, 2) if subtotal else 0.0
        return {"prepared": prepared, "items": lines, "subtotal": subtotal,
                "discount_percent": effective_discount,
                "discount_amount": discount_amount, "total": total,
                "warnings": warnings}, None

    def _quote_catalog_order(self) -> None:
        data = self._read_json_body()
        if data is None:
            return
        quote, error = self._catalog_quote(data.get("items"))
        if error:
            self._send_error(400, error)
            return
        self._send_json_response(200, {key: value for key, value in (quote or {}).items() if key != "prepared"})

    def _create_catalog_order(self, device: dict[str, Any]) -> None:
        """Confirma una venta del catálogo usando un presupuesto calculado por Studio."""
        data = self._read_json_body()
        if data is None:
            return
        client = str(data.get("client") or "").strip()[:120]
        whatsapp = str(data.get("whatsapp") or "").strip()[:40]
        observations = str(data.get("observations") or "").strip()[:2000]
        delivery_date = str(data.get("delivery_date") or "").strip()[:30]
        try:
            print_priority = min(4, max(0, int(data.get("print_priority") or 0)))
        except (TypeError, ValueError):
            self._send_error(400, "print_priority must be an integer between 0 and 4")
            return
        if not client:
            self._send_error(400, "client is required")
            return
        quote, error = self._catalog_quote(data.get("items"))
        if error:
            self._send_error(400, error)
            return
        if quote["warnings"]:
            self._send_error(422, "No se puede confirmar: " + " ".join(quote["warnings"]))
            return
        try:
            paid_amount = round(float(data.get("paid_amount") or 0), 2)
        except (TypeError, ValueError):
            self._send_error(400, "paid_amount must be a number")
            return
        if paid_amount < 0 or paid_amount > quote["total"] + 0.009:
            self._send_error(400, "paid_amount must be between 0 and the total")
            return
        if paid_amount > 0 and not self._require_mobile_feature("payments"):
            return
        payment_method = str(data.get("payment_method") or "").strip()[:50]
        payment_note = str(data.get("payment_note") or "").strip()[:200]
        prepared = quote.pop("prepared")

        now = datetime.now().isoformat(timespec="seconds")
        try:
            with self.event_repo.conn:
                client_row = self.event_repo.conn.execute(
                    "SELECT id FROM clients WHERE name = ? COLLATE NOCASE AND whatsapp = ? LIMIT 1",
                    (client, whatsapp),
                ).fetchone()
                if client_row:
                    client_id = int(client_row["id"])
                else:
                    cursor = self.event_repo.conn.execute(
                        "INSERT INTO clients(name, whatsapp, created_at, updated_at) VALUES(?, ?, ?, ?)",
                        (client, whatsapp, now, now),
                    )
                    client_id = int(cursor.lastrowid)
                first = prepared[0]
                cursor = self.event_repo.conn.execute(
                    """INSERT INTO orders(client, whatsapp, client_id, order_date, status, material, size,
                       quantity, price, discount_percent, budget_total, paid_amount, payment_status, delivery_date, print_priority, observations,
                       order_concept, order_description, creator_device_id, created_at, updated_at, last_autosave_at)
                       VALUES(?, ?, ?, ?, 'Nuevo', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Catálogo móvil', ?, ?, ?, ?, ?)""",
                    (client, whatsapp, client_id, now, first["material"], first["size"], first["quantity"],
                     quote["subtotal"], quote["discount_percent"], quote["total"], paid_amount,
                     "Pagado" if paid_amount >= quote["total"] and quote["total"] > 0 else ("Seña recibida" if paid_amount else "Pendiente"),
                     delivery_date, print_priority, observations, f"Venta creada desde el catálogo móvil ({len(prepared)} diseño(s))", device["id"], now, now, now),
                )
                order_id = int(cursor.lastrowid)
                for item, line in zip(prepared, quote["items"]):
                    self.event_repo.conn.execute(
                        """INSERT INTO order_jobs(order_id, title, material, size, quantity, subtotal, status,
                           discount_percent, final_price, notes, sort_order, created_at, updated_at)
                           VALUES(?, ?, ?, ?, ?, ?, 'Recibido', ?, ?, 'Seleccionado desde catálogo móvil', ?, ?, ?)""",
                        (order_id, item["name"], item["material"], item["size"], item["quantity"], line["subtotal"],
                         line["discount_percent"], line["total"],
                         item["position"], now, now),
                    )
                    self.event_repo.conn.execute(
                        """INSERT INTO order_designs(order_id, image_path, quantity, size_cm, status)
                           VALUES(?, ?, ?, ?, 'Pendiente')
                           ON CONFLICT(order_id, image_path) DO UPDATE SET quantity = excluded.quantity""",
                        (order_id, item["path"], item["quantity"], self._catalog_size_cm(item["size"])),
                    )
                if paid_amount > 0:
                    self.event_repo.conn.execute(
                        """INSERT INTO order_payments(order_id, amount, method, note, paid_at, created_at)
                           VALUES(?, ?, ?, ?, ?, ?)""",
                        (order_id, paid_amount, payment_method, payment_note, now, now),
                    )
                self.event_repo.conn.execute(
                    """INSERT INTO order_events(order_id, event_type, message, data_json, created_at)
                       VALUES(?, 'order.created.mobile_catalog', ?, ?, ?)""",
                    (order_id, "Venta creada desde catálogo móvil", json.dumps({"device_id": device["id"], "designs": len(prepared), "total": quote["total"], "paid_amount": paid_amount}), now),
                )
            try:
                self.event_bus.publish(
                    event_type="order.created", priority="high", title="Nuevo pedido móvil",
                    message=f"Pedido #{order_id} · {client}", entity_type="order", entity_id=order_id,
                    payload={"source": "mobile_catalog", "device_id": device["id"]},
                )
            except Exception:
                logger.exception("Could not publish mobile catalog order event")
            self._send_json_response(201, {"success": True, "order_id": order_id, "financials": {"subtotal": quote["subtotal"], "discount_percent": quote["discount_percent"], "total": quote["total"], "paid_amount": paid_amount}})
        except Exception as error:
            logger.exception("Error creating mobile catalog order")
            self._send_error(500, f"Could not create order: {error}")

    def _create_product_order(self, device: dict[str, Any]) -> None:
        """Venta POS de productos sin diseño; comparte las tablas de Pedidos."""
        data = self._read_json_body()
        if data is None:
            return
        client = str(data.get("client") or "").strip()[:120]
        items = data.get("items")
        if not isinstance(items, list) or not items or len(items) > 30:
            self._send_error(400, "between 1 and 30 items are required")
            return
        prepared: list[dict[str, Any]] = []
        for position, item in enumerate(items):
            if not isinstance(item, dict):
                self._send_error(400, "Invalid product item")
                return
            product = self.event_repo.conn.execute(
                "SELECT id, code, name FROM products WHERE code = ? AND active = 1", (str(item.get("product_code") or ""),)
            ).fetchone()
            if not product:
                self._send_error(400, "A selected product is no longer active")
                return
            try:
                quantity = int(item.get("quantity") or 1)
            except (TypeError, ValueError):
                self._send_error(400, "quantity must be a positive integer")
                return
            if quantity < 1 or quantity > 10000:
                self._send_error(400, "quantity must be between 1 and 10000")
                return
            variant_code = str(item.get("variant_code") or "").strip()
            rule = self.event_repo.conn.execute(
                """SELECT r.*, v.code AS variant_code, v.name AS variant_name
                   FROM price_rules r
                   LEFT JOIN product_variants v ON v.id = r.variant_id
                   WHERE r.product_id = ? AND r.active = 1
                     AND min_quantity <= ? AND (max_quantity IS NULL OR max_quantity >= ?)
                     AND (? = '' OR v.code = ?)
                   ORDER BY r.priority DESC, r.min_quantity DESC, r.id DESC LIMIT 1""",
                (product["id"], quantity, quantity, variant_code, variant_code),
            ).fetchone()
            if not rule:
                self._send_error(422, f"No existe una regla de precio para {product['name']}")
                return
            rule = dict(rule)
            mode, price = str(rule.get("price_mode") or "unitario").casefold(), float(rule.get("price") or 0)
            subtotal = price if mode in {"fijo", "pack"} else round(price * quantity, 2)
            title = str(rule.get("variant_name") or product["name"])
            prepared.append({"product": dict(product), "title": title, "quantity": quantity, "material": str(rule.get("material") or ""),
                             "size": str(rule.get("size") or ""), "subtotal": subtotal, "position": position})
        now = datetime.now().isoformat(timespec="seconds")
        whatsapp = str(data.get("whatsapp") or "").strip()[:40]
        observations = str(data.get("observations") or "").strip()[:2000]
        try:
            target_order_id = int(data["target_order_id"]) if data.get("target_order_id") is not None else None
        except (TypeError, ValueError):
            self._send_error(400, "target_order_id must be a valid order number")
            return
        if not client and target_order_id is None:
            self._send_error(400, "client is required when a product sale is not linked to an existing order")
            return
        total = round(sum(item["subtotal"] for item in prepared), 2)
        try:
            with self.event_repo.conn:
                if target_order_id is not None:
                    target = self.event_repo.conn.execute(
                        "SELECT id, client, price, budget_total, quantity FROM orders WHERE id = ? AND is_archived = 0",
                        (target_order_id,),
                    ).fetchone()
                    if not target:
                        self._send_error(404, "El pedido seleccionado no existe o está archivado")
                        return
                    for item in prepared:
                        self.event_repo.conn.execute(
                            """INSERT INTO order_jobs(order_id, title, material, size, quantity, subtotal, final_price, status, notes, sort_order, created_at, updated_at)
                               VALUES(?, ?, ?, ?, ?, ?, ?, 'Recibido', 'Producto agregado desde POS móvil', ?, ?, ?)""",
                            (target_order_id, item["title"], item["material"], item["size"], item["quantity"], item["subtotal"], item["subtotal"], item["position"], now, now),
                        )
                    updated_total = round(float(target["budget_total"] or target["price"] or 0) + total, 2)
                    updated_quantity = int(target["quantity"] or 0) + sum(item["quantity"] for item in prepared)
                    self.event_repo.conn.execute(
                        "UPDATE orders SET price = ?, budget_total = ?, quantity = ?, updated_at = ? WHERE id = ?",
                        (updated_total, updated_total, updated_quantity, now, target_order_id),
                    )
                    self.event_repo.conn.execute(
                        "INSERT INTO order_events(order_id, event_type, message, data_json, created_at) VALUES(?, 'order.updated.mobile_pos', ?, ?, ?)",
                        (target_order_id, "Productos agregados desde POS móvil", json.dumps({"device_id": device["id"], "total_added": total}), now),
                    )
                    self._send_json_response(201, {"success": True, "order_id": target_order_id, "total": updated_total, "linked": True})
                    return
                row = self.event_repo.conn.execute("SELECT id FROM clients WHERE name = ? COLLATE NOCASE AND whatsapp = ? LIMIT 1", (client, whatsapp)).fetchone()
                client_id = int(row["id"]) if row else int(self.event_repo.conn.execute("INSERT INTO clients(name, whatsapp, created_at, updated_at) VALUES(?, ?, ?, ?)", (client, whatsapp, now, now)).lastrowid)
                first = prepared[0]
                order_id = int(self.event_repo.conn.execute(
                    """INSERT INTO orders(client, whatsapp, client_id, order_date, status, material, size, quantity, price, budget_total, observations, order_concept, order_description, creator_device_id, created_at, updated_at, last_autosave_at)
                       VALUES(?, ?, ?, ?, 'Nuevo', ?, ?, ?, ?, ?, ?, 'POS móvil', ?, ?, ?, ?, ?)""",
                    (client, whatsapp, client_id, now, first["material"], first["size"], first["quantity"], total, total, observations, f"Venta de {len(prepared)} producto(s) desde móvil", device["id"], now, now, now)).lastrowid)
                for item in prepared:
                    self.event_repo.conn.execute(
                        """INSERT INTO order_jobs(order_id, title, material, size, quantity, subtotal, final_price, status, notes, sort_order, created_at, updated_at)
                           VALUES(?, ?, ?, ?, ?, ?, ?, 'Recibido', 'Producto vendido desde POS móvil', ?, ?, ?)""",
                        (order_id, item["title"], item["material"], item["size"], item["quantity"], item["subtotal"], item["subtotal"], item["position"], now, now))
                self.event_repo.conn.execute("INSERT INTO order_events(order_id, event_type, message, data_json, created_at) VALUES(?, 'order.created.mobile_pos', ?, ?, ?)",
                    (order_id, "Venta de productos creada desde POS móvil", json.dumps({"device_id": device["id"], "total": total}), now))
            self._send_json_response(201, {"success": True, "order_id": order_id, "total": total})
        except Exception as error:
            logger.exception("Error creating product order")
            self._send_error(500, f"Could not create product order: {error}")

    def _quote_product_order(self) -> None:
        """Cotiza productos activos sin crear un pedido."""
        data = self._read_json_body()
        if data is None:
            return
        items = data.get("items")
        if not isinstance(items, list) or not items or len(items) > 30:
            self._send_error(400, "items must contain between 1 and 30 products")
            return
        lines = []
        for item in items:
            if not isinstance(item, dict):
                self._send_error(400, "Invalid product item")
                return
            product = self.event_repo.conn.execute("SELECT id, name FROM products WHERE code = ? AND active = 1", (str(item.get("product_code") or ""),)).fetchone()
            quantity = int(item.get("quantity") or 0) if str(item.get("quantity") or "").isdigit() else 0
            if not product or quantity < 1:
                self._send_error(400, "Invalid active product or quantity")
                return
            variant_code = str(item.get("variant_code") or "").strip()
            rule = self.event_repo.conn.execute("""SELECT r.price, r.price_mode FROM price_rules r
                LEFT JOIN product_variants v ON v.id = r.variant_id
                WHERE r.product_id = ? AND r.active = 1
                AND r.min_quantity <= ? AND (r.max_quantity IS NULL OR r.max_quantity >= ?)
                AND (? = '' OR v.code = ?)
                ORDER BY r.priority DESC, r.min_quantity DESC, r.id DESC LIMIT 1""",
                (product["id"], quantity, quantity, variant_code, variant_code)).fetchone()
            if not rule:
                self._send_error(422, f"No existe una regla de precio para {product['name']}")
                return
            price = float(rule["price"] or 0)
            subtotal = price if str(rule["price_mode"] or "unitario").casefold() in {"fijo", "pack"} else round(price * quantity, 2)
            lines.append({"name": product["name"], "quantity": quantity, "subtotal": subtotal})
        subtotal = round(sum(line["subtotal"] for line in lines), 2)
        self._send_json_response(200, {"items": lines, "subtotal": subtotal, "total": subtotal})

    @staticmethod
    def _catalog_size_cm(size: str) -> float:
        try:
            return max(0.1, float(size.lower().replace("cm", "").strip()))
        except (TypeError, ValueError):
            return 0.0

    def _login_mobile_user(self) -> None:
        """POST /api/v1/mobile/auth/login — Autoriza temporalmente un enlace."""
        if not self._require_secure_credentials_transport():
            return
        data = self._read_json_body()
        if data is None:
            return
        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "")
        if not username or not password:
            self._send_error(400, "Ingresá usuario y contraseña")
            return

        result = self._mobile_user_repository().authenticate(username, password)
        client_ip = _get_client_ip(self)
        if not result.success or result.user is None:
            self._mobile_access().audit_event(
                "seller_login_failed",
                ip_address=client_ip,
                endpoint="/api/v1/mobile/auth/login",
                details={"username": username[:40], "reason": result.message},
            )
            self._send_error(401, result.message)
            return

        self._mobile_access().audit_event(
            "seller_login_success",
            ip_address=client_ip,
            endpoint="/api/v1/mobile/auth/login",
            details={"user_id": result.user.id, "username": result.user.username},
            throttle_seconds=0,
        )
        self._send_json_response(
            200,
            {
                "success": True,
                "link_token": result.link_token,
                "expires_in": result.expires_in,
                "user": {
                    "id": result.user.id,
                    "username": result.user.username,
                    "display_name": result.user.display_name,
                },
            },
        )

    def _pair_device(self) -> None:
        """POST /api/pair/validate — Requiere login y código de Studio."""
        if not self._require_secure_credentials_transport():
            return
        data = self._read_json_body()
        if data is None:
            return
        link_token = self._get_auth_token()
        if not link_token:
            self._send_error(401, "Primero iniciá sesión con tu usuario")
            return
        users = self._mobile_user_repository()
        pending_user = users.validate_link_token(link_token)
        if pending_user is None:
            self._send_error(
                401, "La autorización de enlace venció. Iniciá sesión nuevamente."
            )
            return
        code = str(data.get("code") or "").strip()
        push_token = str(data.get("push_token") or "").strip()
        if not code or not push_token:
            self._send_error(400, "Faltan campos requeridos: code, push_token")
            return
        if self.event_repo.validate_pairing_code(code) is None:
            self._mobile_access().audit_event(
                "pairing_failed",
                ip_address=_get_client_ip(self),
                endpoint="/api/pair/validate",
                details={"user_id": pending_user.id, "reason": "invalid_code"},
            )
            self._send_error(400, "Código inválido o expirado")
            return
        user = users.claim_link_token(link_token)
        if user is None:
            self._send_error(
                401, "La autorización de enlace ya fue utilizada o venció."
            )
            return
        try:
            success, message, device_id, session_token = self.event_repo.register_device_with_pairing(
                pairing_code=code, push_token=push_token,
                platform=str(data.get("platform") or "android")[:30],
                device_name=str(data.get("device_name") or "")[:120],
                app_version=str(data.get("app_version") or "")[:40],
                user_id=user.id,
            )
            if success:
                self._mobile_access().audit_event(
                    "seller_device_linked",
                    ip_address=_get_client_ip(self),
                    endpoint="/api/pair/validate",
                    details={
                        "user_id": user.id,
                        "username": user.username,
                        "device_id": device_id,
                    },
                    throttle_seconds=0,
                )
                self._send_json_response(200, {"success": True, "message": message,
                    "device_id": device_id, "session_token": session_token,
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "display_name": user.display_name,
                    }})
            else:
                self._send_error(400, message)
        except Exception as e:
            logger.exception("Error pairing mobile device")
            self._send_error(500, f"Error vinculando dispositivo: {e}")

    def _update_device_token(self, device: dict[str, Any]) -> None:
        """POST /api/device/update-token — Renueva el token FCM de un equipo."""
        data = self._read_json_body()
        if data is None:
            return
        new_token = str(data.get("new_token") or "").strip()
        if not new_token:
            self._send_error(400, "Falta el campo requerido: new_token")
            return
        try:
            self.event_repo.update_device_token(int(device["id"]), new_token)
            self._send_json_response(
                200, {"success": True, "message": "Token actualizado exitosamente"}
            )
        except Exception as e:
            logger.exception("Error updating device token")
            self._send_error(500, f"Error actualizando token: {e}")

    def _logout_mobile_device(self, device: dict[str, Any]) -> None:
        """Revoca el dispositivo actual y su sesión persistente."""
        device_id = int(device["id"])
        self.event_repo.deactivate_device(device_id)
        self._mobile_access().audit_event(
            "seller_logout",
            ip_address=_get_client_ip(self),
            endpoint="/api/v1/mobile/auth/logout",
            details={
                "device_id": device_id,
                "user_id": device.get("user_id"),
            },
            throttle_seconds=0,
        )
        self._send_json_response(200, {"success": True})

    def do_PATCH(self) -> None:
        """Maneja requests PATCH para actualizaciones parciales."""
        parsed = urlparse(self.path)
        if self._authorize_network_request("PATCH") is None:
            return

        device = self._validate_auth()
        if not device:
            return
        if (
            not self._require_mobile_mutations()
            or not self._require_mobile_feature("quick_edits")
        ):
            return

        if _match_order_route(parsed.path, "/status"):
            order_id = _extract_order_id(parsed.path, "/status")
            if order_id is not None:
                self._update_order_status(order_id, device)
            else:
                self._send_error(400, "Invalid order ID")
        elif _match_order_route(parsed.path, "/details"):
            order_id = _extract_order_id(parsed.path, "/details")
            if order_id is not None:
                self._update_order_details(order_id, device)
            else:
                self._send_error(400, "Invalid order ID")
        elif _match_order_route(parsed.path, "/priority"):
            order_id = _extract_order_id(parsed.path, "/priority")
            if order_id is not None:
                self._update_order_priority(order_id, device)
            else:
                self._send_error(400, "Invalid order ID")
        elif _match_order_job_route(parsed.path):
            ids = _extract_order_job_ids(parsed.path)
            if ids is not None:
                self._update_job_fields(*ids, device)
            else:
                self._send_error(400, "Invalid order or job ID")
        else:
            self._send_error(404, "Endpoint not found")

    def _list_jobs(self, device: dict[str, Any]) -> None:
        """Lista jobs con filtros y paginación."""
        params = self._parse_url_params()
        
        # Filtros con validación
        filter_type = params.get("filter", "")
        valid_filters = ["", "pending", "production", "ready"]
        if filter_type not in valid_filters:
            self._send_error(400, f"Invalid filter value. Valid options: {', '.join(valid_filters[1:])}")
            return

        # Validación de paginación
        try:
            limit = min(100, max(1, int(params.get("limit", "20"))))
        except ValueError:
            self._send_error(400, "Invalid limit value, must be an integer")
            return

        try:
            offset = max(0, int(params.get("offset", "0")))
        except ValueError:
            self._send_error(400, "Invalid offset value, must be an integer")
            return
        
        # Construir query base
        query = """
            SELECT j.id, j.order_id, j.title, j.material, j.size, j.quantity,
                   j.status, j.notes, j.sort_order, j.created_at, j.updated_at,
                   o.client, o.delivery_date, o.print_priority
            FROM order_jobs j
            JOIN orders o ON j.order_id = o.id
            WHERE o.is_archived = 0
              AND o.creator_device_id = ?
        """
        params_list = [device["id"]]
        
        # Aplicar filtro
        if filter_type == "pending":
            query += " AND j.status IN ('Recibido', 'Esperando archivos')"
        elif filter_type == "production":
            query += " AND j.status NOT IN ('Recibido', 'Esperando archivos', 'Finalizado', 'Entregado')"
        elif filter_type == "ready":
            query += " AND j.status IN ('Finalizado', 'Entregado')"
        
        query += " ORDER BY o.print_priority DESC, o.delivery_date ASC, j.sort_order ASC"
        query += " LIMIT ? OFFSET ?"
        params_list.extend([limit, offset])
        
        try:
            rows = self.event_repo.conn.execute(query, params_list).fetchall()
            jobs = []
            
            for row in rows:
                job_dict = dict(row)
                # Calcular progreso y timeline
                job_dict["progress"] = get_stage_progress(job_dict)
                job_dict["current_stage"] = get_current_stage(job_dict)
                job_dict["workflow_stages"] = workflow_stages(job_dict)
                job_dict["pending_stages"] = job_dict["workflow_stages"][
                    job_dict["workflow_stages"].index(job_dict["current_stage"]) + 1:
                ] if job_dict["current_stage"] in job_dict["workflow_stages"] else []
                jobs.append(job_dict)
            
            # Total count para paginación
            count_query = query.split("ORDER BY")[0].replace("SELECT j.id, j.order_id, j.title, j.material, j.size, j.quantity, j.status, j.notes, j.sort_order, j.created_at, j.updated_at, o.client, o.delivery_date, o.print_priority", "SELECT COUNT(*)")
            count_params = params_list[:-2]  # Remover limit y offset
            total = self.event_repo.conn.execute(count_query, count_params).fetchone()[0]
            
            self._send_json_response(200, {
                "jobs": jobs,
                "total": total,
                "limit": limit,
                "offset": offset,
                "filter": filter_type if filter_type else "all",
            })
            
        except Exception as e:
            logger.error("Error listing jobs: %s", e)
            self._send_error(500, f"Error listing jobs: {e}")

    def _search_jobs(self, device: dict[str, Any]) -> None:
        """Busca jobs por texto en título, cliente, material, notas."""
        params = self._parse_url_params()

        query_text = params.get("q", "").strip()
        if not query_text:
            self._send_error(400, "Query parameter 'q' is required")
            return

        if len(query_text) > 100:
            self._send_error(400, "Search query too long (max 100 characters)")
            return

        limit = min(50, max(1, int(params.get("limit", "20"))))
        offset = max(0, int(params.get("offset", "0")))

        try:
            # Búsqueda en múltiples campos
            search_pattern = f"%{query_text}%"
            query = """
                SELECT j.id, j.order_id, j.title, j.material, j.size, j.quantity,
                       j.status, j.notes, j.sort_order, j.created_at, j.updated_at,
                       o.client, o.delivery_date, o.print_priority
                FROM order_jobs j
                JOIN orders o ON j.order_id = o.id
                WHERE o.is_archived = 0
                  AND o.creator_device_id = ?
                  AND (j.title LIKE ? 
                       OR o.client LIKE ? 
                       OR j.material LIKE ? 
                       OR j.notes LIKE ?
                       OR CAST(j.id AS TEXT) LIKE ?
                       OR CAST(j.order_id AS TEXT) LIKE ?)
                ORDER BY o.print_priority DESC, o.delivery_date ASC, j.sort_order ASC
                LIMIT ? OFFSET ?
            """

            params_list = [device["id"]] + [search_pattern] * 6 + [limit, offset]
            rows = self.event_repo.conn.execute(query, params_list).fetchall()

            jobs = []
            for row in rows:
                job_dict = dict(row)
                # Calcular progreso y timeline
                job_dict["progress"] = get_stage_progress(job_dict)
                job_dict["current_stage"] = get_current_stage(job_dict)
                job_dict["workflow_stages"] = workflow_stages(job_dict)
                jobs.append(job_dict)

            # Total count
            count_query = """
                SELECT COUNT(*)
                FROM order_jobs j
                JOIN orders o ON j.order_id = o.id
                WHERE o.is_archived = 0
                  AND o.creator_device_id = ?
                  AND (j.title LIKE ? 
                       OR o.client LIKE ? 
                       OR j.material LIKE ? 
                       OR j.notes LIKE ?
                       OR CAST(j.id AS TEXT) LIKE ?
                       OR CAST(j.order_id AS TEXT) LIKE ?)
            """
            count_params = [device["id"]] + [search_pattern] * 6
            total = self.event_repo.conn.execute(count_query, count_params).fetchone()[0]

            self._send_json_response(200, {
                "jobs": jobs,
                "total": total,
                "limit": limit,
                "offset": offset,
                "query": query_text,
            })

        except Exception as e:
            logger.error("Error searching jobs: %s", e)
            self._send_error(500, f"Error searching jobs: {e}")

    def _get_job_detail(self, job_id: int, device: dict[str, Any]) -> None:
        """Obtiene detalle de un job específico."""
        try:
            row = self.event_repo.conn.execute(
                """SELECT j.id, j.order_id, j.title, j.material, j.size, j.quantity,
                   j.status, j.notes, j.sort_order, j.created_at, j.updated_at,
                   o.client, o.whatsapp, o.delivery_date, o.print_priority, o.observations
                   FROM order_jobs j
                   JOIN orders o ON j.order_id = o.id
                   WHERE j.id = ?
                     AND o.creator_device_id = ?""",
                (job_id, device["id"]),
            ).fetchone()
            
            if not row:
                self._send_error(404, "Job not found")
                return
            
            job_dict = dict(row)
            
            # Calcular progreso y timeline
            job_dict["progress"] = get_stage_progress(job_dict)
            job_dict["current_stage"] = get_current_stage(job_dict)
            job_dict["workflow_stages"] = workflow_stages(job_dict)
            job_dict["timeline"] = [
                {"stage": stage, "completed": stage in job_dict["workflow_stages"][:job_dict["workflow_stages"].index(job_dict["current_stage"])] + [job_dict["current_stage"]] if job_dict["current_stage"] in job_dict["workflow_stages"] else False}
                for stage in job_dict["workflow_stages"]
            ]
            
            # Historial de cambios de etapa
            history = self.event_repo.conn.execute(
                """SELECT old_stage, new_stage, device_name, operator_name, source, notes, changed_at
                   FROM production_stage_history
                   WHERE job_id = ?
                   ORDER BY changed_at DESC""",
                (job_id,),
            ).fetchall()
            
            job_dict["stage_history"] = [dict(row) for row in history]
            
            self._send_json_response(200, job_dict)
            
        except Exception as e:
            logger.error("Error getting job detail: %s", e)
            self._send_error(500, f"Error getting job detail: {e}")

    def _change_job_stage(self, job_id: int, device: dict[str, Any]) -> None:
        """Cambia la etapa de un job."""
        try:
            # Validar que el job existe antes de leer el body
            job_check = self.event_repo.conn.execute(
                """SELECT j.id
                   FROM order_jobs j
                   JOIN orders o ON o.id = j.order_id
                   WHERE j.id = ? AND o.creator_device_id = ?""",
                (job_id, device["id"]),
            ).fetchone()

            if not job_check:
                self._send_error(404, f"Job with ID {job_id} not found")
                return

            # Leer body
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self._send_error(400, "Request body is required")
                return

            if content_length > 10000:  # 10KB max
                self._send_error(413, "Request body too large (max 10KB)")
                return

            body = self.rfile.read(content_length)
            data = json.loads(body.decode("utf-8"))
            
            new_stage = data.get("stage", "").strip()
            if not new_stage:
                self._send_error(400, "stage field is required and cannot be empty")
                return

            # Validar longitud de la etapa
            if len(new_stage) > 100:
                self._send_error(400, "stage name too long (max 100 characters)")
                return
            
            notes = data.get("notes", "").strip()
            if len(notes) > 500:
                self._send_error(400, "notes too long (max 500 characters)")
                return

            operator_name = data.get("operator_name", "").strip()
            if len(operator_name) > 100:
                self._send_error(400, "operator_name too long (max 100 characters)")
                return
            
            # Cambiar etapa usando el servicio
            success, message, job_data = self.stage_service.change_job_stage(
                job_id=job_id,
                new_stage=new_stage,
                device_id=device["id"],
                device_name=device["device_name"],
                operator_name=operator_name,
                source="mobile",
                notes=notes,
            )
            
            if success:
                self._send_json_response(200, {
                    "success": True,
                    "message": message,
                    "job": job_data,
                })
            else:
                self._send_error(400, message)
                
        except json.JSONDecodeError:
            self._send_error(400, "Invalid JSON body")
        except Exception as e:
            logger.error("Error changing job stage: %s", e)
            self._send_error(500, f"Error changing job stage: {e}")

    # ── Quick-edit handlers ────────────────────────────────────────────────

    def _read_json_body(self) -> dict | None:
        """Lee y parsea el body JSON de un request, con validaciones comunes."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_error(400, "Request body is required")
            return None
        if content_length > 10000:
            self._send_error(413, "Request body too large (max 10KB)")
            return None
        try:
            return json.loads(self.rfile.read(content_length).decode("utf-8"))
        except json.JSONDecodeError:
            self._send_error(400, "Invalid JSON body")
            return None

    def _update_order_status(self, order_id: int, device: dict[str, Any]) -> None:
        """PATCH /api/v1/mobile/orders/{id}/status — Cambia el estado general."""
        data = self._read_json_body()
        if data is None:
            return
        new_status = data.get("status", "").strip()
        if not new_status:
            self._send_error(400, "status field is required")
            return
        if len(new_status) > 50:
            self._send_error(400, "status too long (max 50 characters)")
            return
        valid_statuses = set(
            self._runtime_config()
            .get("references", {})
            .get("order_statuses", DEFAULT_ORDER_STATUSES)
        )
        if new_status not in valid_statuses:
            self._send_error(400, f"Invalid status. Valid options: {', '.join(sorted(valid_statuses))}")
            return
        try:
            order_check = self.event_repo.conn.execute(
                """SELECT id, is_archived FROM orders
                   WHERE id = ? AND creator_device_id = ?""",
                (order_id, device["id"]),
            ).fetchone()
            if not order_check:
                self._send_error(404, f"Order {order_id} not found")
                return
            if order_check["is_archived"]:
                self._send_error(400, "Cannot modify an archived order")
                return
            self.event_repo.conn.execute(
                """UPDATE orders
                   SET status = ?,
                       print_priority = CASE
                           WHEN ? = 'Entregado' THEN 0
                           ELSE print_priority
                       END,
                       updated_at = datetime('now')
                   WHERE id = ?""",
                (new_status, new_status, order_id),
            )
            if new_status == "Cancelado":
                self.event_repo.conn.execute(
                    "UPDATE order_jobs SET status = 'Cancelado', updated_at = datetime('now') WHERE order_id = ?",
                    (order_id,),
                )
            self.event_repo.conn.execute(
                """INSERT INTO order_events(order_id, event_type, message, data_json, created_at)
                   VALUES(?, 'status.changed', ?, ?, datetime('now'))""",
                (order_id, f"Estado actualizado a: {new_status}", json.dumps({"source": "mobile", "device_id": device["id"]})),
            )
            self.event_repo.conn.commit()
            row = self.event_repo.conn.execute(
                "SELECT id, status, print_priority, updated_at FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
            self._send_json_response(200, {"success": True, "order": dict(row)})
        except sqlite3.IntegrityError as e:
            self.event_repo.conn.rollback()
            self._send_error(409, str(e))
        except Exception as e:
            self.event_repo.conn.rollback()
            logger.error("Error updating order status: %s", e)
            self._send_error(500, f"Error updating order status: {e}")

    def _update_order_priority(self, order_id: int, device: dict[str, Any]) -> None:
        """PATCH /api/v1/mobile/orders/{id}/priority — Cambia la prioridad."""
        data = self._read_json_body()
        if data is None:
            return
        priority = data.get("print_priority")
        if priority is None:
            self._send_error(400, "print_priority field is required")
            return
        try:
            priority = int(priority)
        except (TypeError, ValueError):
            self._send_error(400, "print_priority must be an integer (0-4)")
            return
        if priority < 0 or priority > 4:
            self._send_error(400, "print_priority must be between 0 and 4")
            return
        try:
            order_check = self.event_repo.conn.execute(
                """SELECT id, is_archived FROM orders
                   WHERE id = ? AND creator_device_id = ?""",
                (order_id, device["id"]),
            ).fetchone()
            if not order_check:
                self._send_error(404, f"Order {order_id} not found")
                return
            if order_check["is_archived"]:
                self._send_error(400, "Cannot modify an archived order")
                return
            self.event_repo.conn.execute(
                "UPDATE orders SET print_priority = ?, updated_at = datetime('now') WHERE id = ?",
                (priority, order_id),
            )
            self.event_repo.conn.execute(
                """INSERT INTO order_events(order_id, event_type, message, data_json, created_at)
                   VALUES(?, 'priority.changed', ?, ?, datetime('now'))""",
                (order_id, f"Prioridad actualizada a: {priority}", json.dumps({"source": "mobile", "device_id": device["id"]})),
            )
            self.event_repo.conn.commit()
            row = self.event_repo.conn.execute(
                "SELECT id, print_priority, updated_at FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
            self._send_json_response(200, {"success": True, "order": dict(row)})
        except Exception as e:
            logger.error("Error updating order priority: %s", e)
            self._send_error(500, f"Error updating order priority: {e}")

    def _update_order_details(self, order_id: int, device: dict[str, Any]) -> None:
        """PATCH /api/v1/mobile/orders/{id}/details — Edita datos operativos seguros."""
        data = self._read_json_body()
        if data is None:
            return
        allowed = {
            "material": ("material", 120),
            "size": ("size", 40),
            "delivery_date": ("delivery_date", 40),
            "observations": ("observations", 2000),
            "order_concept": ("order_concept", 300),
            "order_description": ("order_description", 3000),
            "extra_services": ("extra_services", 1000),
        }
        clauses: list[str] = []
        params: list[Any] = []
        changes: dict[str, Any] = {}
        for key, (column, max_length) in allowed.items():
            if key in data:
                value = str(data[key] or "").strip()[:max_length]
                clauses.append(f"{column} = ?")
                params.append(value)
                changes[key] = value
        if "quantity" in data:
            try:
                quantity = max(1, int(data["quantity"]))
            except (TypeError, ValueError):
                self._send_error(400, "quantity must be a positive integer")
                return
            clauses.append("quantity = ?")
            params.append(quantity)
            changes["quantity"] = quantity
        if not clauses:
            self._send_error(400, "No editable fields supplied")
            return
        try:
            order = self.event_repo.conn.execute(
                """SELECT id, is_archived FROM orders
                   WHERE id = ? AND creator_device_id = ?""",
                (order_id, device["id"]),
            ).fetchone()
            if not order:
                self._send_error(404, f"Order {order_id} not found")
                return
            if order["is_archived"]:
                self._send_error(400, "Cannot modify an archived order")
                return
            clauses.append("updated_at = datetime('now')")
            params.append(order_id)
            self.event_repo.conn.execute(
                f"UPDATE orders SET {', '.join(clauses)} WHERE id = ?", params,
            )
            self.event_repo.conn.execute(
                """INSERT INTO order_events(order_id, event_type, message, data_json, created_at)
                   VALUES(?, 'order.details_updated', ?, ?, datetime('now'))""",
                (order_id, "Datos operativos actualizados desde móvil",
                 json.dumps({"source": "mobile", "device_id": device["id"], "changes": changes})),
            )
            self.event_repo.conn.commit()
            updated = self.event_repo.conn.execute(
                "SELECT id, material, size, quantity, delivery_date, observations, order_concept, order_description, extra_services, updated_at FROM orders WHERE id = ?",
                (order_id,),
            ).fetchone()
            self._send_json_response(200, {"success": True, "order": dict(updated)})
        except Exception as e:
            logger.error("Error updating order details: %s", e)
            self._send_error(500, f"Error updating order details: {e}")

    def _update_job_fields(self, order_id: int, job_id: int, device: dict[str, Any]) -> None:
        """PATCH /api/v1/mobile/orders/{oid}/jobs/{jid} — Modifica cantidad/tamaño."""
        data = self._read_json_body()
        if data is None:
            return
        quantity = data.get("quantity")
        size = data.get("size")
        if quantity is None and size is None:
            self._send_error(400, "At least one of 'quantity' or 'size' is required")
            return
        try:
            order_check = self.event_repo.conn.execute(
                """SELECT id, is_archived FROM orders
                   WHERE id = ? AND creator_device_id = ?""",
                (order_id, device["id"]),
            ).fetchone()
            if not order_check:
                self._send_error(404, f"Order {order_id} not found")
                return
            if order_check["is_archived"]:
                self._send_error(400, "Cannot modify an archived order")
                return
            job_check = self.event_repo.conn.execute(
                "SELECT id FROM order_jobs WHERE id = ? AND order_id = ?", (job_id, order_id)
            ).fetchone()
            if not job_check:
                self._send_error(404, f"Job {job_id} not found in order {order_id}")
                return
            set_clauses, params = [], []
            if quantity is not None:
                q = max(1, int(quantity))
                set_clauses.append("quantity = ?")
                params.append(q)
            if size is not None:
                s = str(size).strip()[:20]
                set_clauses.append("size = ?")
                params.append(s)
            set_clauses.append("updated_at = datetime('now')")
            params.append(job_id)
            self.event_repo.conn.execute(
                f"UPDATE order_jobs SET {', '.join(set_clauses)} WHERE id = ?", params,
            )
            # Recalcular resumen del pedido
            jobs = [dict(r) for r in self.event_repo.conn.execute(
                "SELECT * FROM order_jobs WHERE order_id = ? ORDER BY sort_order, id", (order_id,)
            )]
            if jobs:
                total_qty = sum(max(1, int(j.get("quantity") or 1)) for j in jobs)
                self.event_repo.conn.execute(
                    "UPDATE orders SET quantity = ?, updated_at = datetime('now') WHERE id = ?",
                    (total_qty, order_id),
                )
            self.event_repo.conn.execute(
                """INSERT INTO order_events(order_id, event_type, message, data_json, created_at)
                   VALUES(?, 'job.updated', ?, ?, datetime('now'))""",
                (order_id, f"Trabajo #{job_id} actualizado", json.dumps({"source": "mobile", "job_id": job_id, "device_id": device["id"]})),
            )
            self.event_repo.conn.commit()
            row = self.event_repo.conn.execute(
                "SELECT id, quantity, size, updated_at FROM order_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            self._send_json_response(200, {"success": True, "job": dict(row)})
        except Exception as e:
            logger.error("Error updating job fields: %s", e)
            self._send_error(500, f"Error updating job: {e}")

    def _register_payment(self, order_id: int, device: dict[str, Any]) -> None:
        """POST /api/v1/mobile/orders/{id}/payments — Registra un cobro."""
        data = self._read_json_body()
        if data is None:
            return
        amount = data.get("amount")
        if amount is None:
            self._send_error(400, "amount field is required")
            return
        try:
            amount = round(float(amount), 2)
        except (TypeError, ValueError):
            self._send_error(400, "amount must be a number")
            return
        if amount <= 0:
            self._send_error(400, "amount must be greater than zero")
            return
        method = str(data.get("method", "")).strip()[:50]
        note = str(data.get("note", "")).strip()[:200]
        try:
            order_check = self.event_repo.conn.execute(
                """SELECT id, is_archived FROM orders
                   WHERE id = ? AND creator_device_id = ?""",
                (order_id, device["id"]),
            ).fetchone()
            if not order_check:
                self._send_error(404, f"Order {order_id} not found")
                return
            if order_check["is_archived"]:
                self._send_error(400, "Cannot modify an archived order")
                return
            now_str = datetime.now().isoformat(timespec="seconds")
            self.event_repo.conn.execute(
                """INSERT INTO order_payments(order_id, amount, method, note, paid_at, created_at)
                   VALUES(?, ?, ?, ?, ?, ?)""",
                (order_id, amount, method, note, now_str, now_str),
            )
            # Recalcular financials
            paid = self.event_repo.conn.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM order_payments WHERE order_id = ?", (order_id,)
            ).fetchone()[0]
            order_row = self.event_repo.conn.execute(
                "SELECT price, discount_percent, budget_total FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
            budget_total = float(order_row["budget_total"] or 0) if order_row else 0.0
            payment_status = "Pagado" if budget_total > 0 and (budget_total - float(paid)) <= 0.009 else ("Seña recibida" if paid else "Pendiente")
            self.event_repo.conn.execute(
                "UPDATE orders SET paid_amount = ?, payment_status = ?, updated_at = ? WHERE id = ?",
                (float(paid), payment_status, now_str, order_id),
            )
            self.event_repo.conn.execute(
                """INSERT INTO order_events(order_id, event_type, message, data_json, created_at)
                   VALUES(?, 'payment.received', ?, ?, ?)""",
                (order_id, f"Cobro registrado: ${amount:,.2f}" + (f" · {method}" if method else ""), json.dumps({"amount": amount, "method": method, "source": "mobile", "device_id": device["id"]}), now_str),
            )
            self.event_repo.conn.commit()
            self._send_json_response(200, {
                "success": True,
                "payment": {"amount": amount, "method": method, "paid_at": now_str},
                "financials": {"budget_total": budget_total, "paid_amount": float(paid), "payment_status": payment_status},
            })
        except Exception as e:
            logger.error("Error registering payment: %s", e)
            self._send_error(500, f"Error registering payment: {e}")

    def _mark_delivered(self, order_id: int, device: dict[str, Any]) -> None:
        """POST /api/v1/mobile/orders/{id}/deliver — Marca pedido como entregado."""
        try:
            order_check = self.event_repo.conn.execute(
                """SELECT id, status, is_archived FROM orders
                   WHERE id = ? AND creator_device_id = ?""",
                (order_id, device["id"]),
            ).fetchone()
            if not order_check:
                self._send_error(404, f"Order {order_id} not found")
                return
            if order_check["is_archived"]:
                self._send_error(400, "Cannot modify an archived order")
                return
            old_status = order_check["status"]
            now_str = datetime.now().isoformat(timespec="seconds")
            with self.event_repo.conn:
                self.event_repo.conn.execute(
                    "UPDATE order_jobs SET status = 'Entregado', updated_at = ? WHERE order_id = ?",
                    (now_str, order_id),
                )
                self.event_repo.conn.execute(
                    """UPDATE orders
                       SET status = 'Entregado', print_priority = 0, updated_at = ?
                       WHERE id = ?""",
                    (now_str, order_id),
                )
            self.event_repo.conn.execute(
                """INSERT INTO order_events(order_id, event_type, message, data_json, created_at)
                   VALUES(?, 'order.delivered', ?, ?, ?)""",
                (order_id, f"Pedido marcado como Entregado (anterior: {old_status})", json.dumps({"source": "mobile", "old_status": old_status, "device_id": device["id"]}), now_str),
            )
            self.event_repo.conn.commit()
            try:
                self.event_bus.publish(
                    event_type="order.delivered",
                    title="Pedido entregado",
                    message=f"Pedido #{order_id} marcado como Entregado",
                    priority="high",
                    entity_type="order",
                    entity_id=order_id,
                    payload={"old_status": old_status, "device_id": device["id"]},
                )
            except Exception:
                pass
            row = self.event_repo.conn.execute(
                "SELECT id, status, print_priority, updated_at FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
            self._send_json_response(200, {"success": True, "order": dict(row)})
        except sqlite3.IntegrityError as e:
            self._send_error(409, str(e))
        except Exception as e:
            logger.error("Error marking order delivered: %s", e)
            self._send_error(500, f"Error marking order delivered: {e}")

    def _get_stages(self) -> None:
        """Obtiene el catálogo completo de etapas desde fuente oficial."""
        try:
            stages = get_all_stages_for_mobile()
            self._send_json_response(200, {"stages": stages})
        except Exception as e:
            logger.error("Error getting stages: %s", e)
            self._send_error(500, f"Error getting stages: {e}")

    def _get_workflows(self) -> None:
        """Obtiene los flujos de trabajo desde fuente oficial."""
        try:
            workflows = get_workflows_for_mobile()
            self._send_json_response(200, {"workflows": workflows})
        except Exception as e:
            logger.error("Error getting workflows: %s", e)
            self._send_error(500, f"Error getting workflows: {e}")

    def _get_materials(self) -> None:
        """Obtiene el catálogo de materiales disponibles."""
        try:
            # Obtener materiales desde la base de datos
            rows = self.event_repo.conn.execute(
                """SELECT DISTINCT material 
                   FROM order_jobs 
                   WHERE material IS NOT NULL AND material != ''
                   ORDER BY material"""
            ).fetchall()

            materials = [row[0] for row in rows]

            # Si no hay materiales en DB, devolver lista predefinida
            if not materials:
                materials = [
                    "Vinilo",
                    "Lona",
                    "Banner",
                    "Microperforado",
                    "PVC",
                    "Acrílico",
                    "Foam",
                    "Tela",
                    "Canvas",
                ]

            self._send_json_response(200, {"materials": materials})

        except Exception as e:
            logger.error("Error getting materials: %s", e)
            self._send_error(500, f"Error getting materials: {e}")

    def _update_device_preferences(self, device: dict[str, Any]) -> None:
        """Actualiza las preferencias de notificaciones del dispositivo."""
        try:
            # Leer body
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode("utf-8"))

            preferences = data.get("preferences")
            if not isinstance(preferences, dict):
                self._send_error(400, "preferences field must be a dictionary")
                return

            # Validar event_types contra whitelist
            for event_type in preferences.keys():
                if event_type not in ALLOWED_NOTIFICATION_EVENT_TYPES:
                    self._send_error(400, f"Unknown event type: '{event_type}'")
                    return

            # Actualizar cada preferencia
            updated_count = 0
            for event_type, enabled in preferences.items():
                if not isinstance(enabled, bool):
                    self._send_error(400, f"Preference value for '{event_type}' must be boolean")
                    return

                self.event_repo.set_device_pref(device["id"], event_type, enabled)
                updated_count += 1

            # Obtener preferencias actualizadas
            updated_prefs = self.event_repo.get_device_prefs(device["id"])

            self._send_json_response(200, {
                "success": True,
                "message": f"{updated_count} preferences updated",
                "preferences": updated_prefs,
            })

        except json.JSONDecodeError:
            self._send_error(400, "Invalid JSON body")
        except Exception as e:
            logger.error("Error updating device preferences: %s", e)
            self._send_error(500, f"Error updating device preferences: {e}")

    def _get_device_status(self, device: dict[str, Any]) -> None:
        """Obtiene el estado actual del dispositivo."""
        try:
            # Obtener preferencias de notificaciones
            prefs = self.event_repo.get_device_prefs(device["id"])

            # Calcular estadísticas de uso
            stats = self.event_repo.conn.execute(
                """SELECT COUNT(*) as total_changes
                   FROM production_stage_history
                   WHERE device_id = ?""",
                (device["id"],),
            ).fetchone()

            total_changes = stats[0] if stats else 0

            # Última actividad
            last_activity = self.event_repo.conn.execute(
                """SELECT MAX(changed_at) as last_seen
                   FROM production_stage_history
                   WHERE device_id = ?""",
                (device["id"],),
            ).fetchone()

            last_seen = last_activity[0] if last_activity and last_activity[0] else device.get("registered_at")

            device_status = {
                "device_id": device["id"],
                "device_name": device["device_name"],
                "platform": device["platform"],
                "app_version": device.get("app_version", ""),
                "registered_at": device["registered_at"],
                "last_seen": last_seen,
                "is_paused": device.get("is_paused", 0) == 1,
                "notification_prefs": prefs,
                "stats": {
                    "total_stage_changes": total_changes,
                },
                "server_version": "1.0.0",  # Versión de la API
            }

            self._send_json_response(200, device_status)

        except Exception as e:
            logger.error("Error getting device status: %s", e)
            self._send_error(500, f"Error getting device status: {e}")

    def _get_capabilities(self) -> None:
        """Retorna capacidades del servidor para sincronización móvil."""
        runtime_config = MobileRuntimeConfigService(self.event_repo.conn).snapshot()
        capabilities = {
            "api_version": "1.0",
            "server_version": "1.0.0",
            "supported_types": sorted(SyncCursorService.SUPPORTED_TYPES),
            "max_limit": SyncCursorService.MAX_LIMIT,
            "cursor_version": SyncCursorService.CURSOR_VERSION,
            "supports_pull": True,
            "supports_push": False,
            "supports_deletions": False,
            "visit_sync": {"pull": True, "push": True},
            # Contrato aditivo: APK antiguos ignoran estas claves y las
            # versiones nuevas pueden cambiar opciones sin recompilar.
            "runtime_config": runtime_config,
        }
        self._send_json_response(200, capabilities)

    def _get_health(self) -> None:
        """Health check público del API móvil — sin autenticación."""
        self._send_json_response(200, {
            "status": "ok",
            "service": "doccione-studio",
            "api_version": "v1",
            "mobile_api": True,
        })

    def _ensure_visits_table(self) -> None:
        """Crea el almacenamiento de agenda compartida de forma aditiva."""
        self.event_repo.conn.execute(
            """CREATE TABLE IF NOT EXISTS mobile_visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_key TEXT NOT NULL,
                client_uuid TEXT NOT NULL,
                title TEXT NOT NULL,
                note TEXT,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                scheduled_at TEXT,
                client_id TEXT,
                client_phone TEXT,
                zone TEXT,
                result TEXT,
                last_contact_at TEXT,
                deleted INTEGER NOT NULL DEFAULT 0,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(owner_key, client_uuid)
            )"""
        )
        columns = {
            row[1]
            for row in self.event_repo.conn.execute(
                "PRAGMA table_info(mobile_visits)"
            )
        }
        additions = {
            "deleted": "deleted INTEGER NOT NULL DEFAULT 0",
            "version": "version INTEGER NOT NULL DEFAULT 1",
            "zone": "zone TEXT",
            "result": "result TEXT",
            "last_contact_at": "last_contact_at TEXT",
        }
        for column, definition in additions.items():
            if column not in columns:
                self.event_repo.conn.execute(
                    f"ALTER TABLE mobile_visits ADD COLUMN {definition}"
                )
        self.event_repo.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mobile_visits_owner_updated "
            "ON mobile_visits(owner_key, updated_at DESC)"
        )
        self.event_repo.conn.execute(
            """CREATE TABLE IF NOT EXISTS mobile_visit_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_key TEXT NOT NULL,
                event_uuid TEXT NOT NULL,
                client_uuid TEXT NOT NULL,
                action TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(owner_key, event_uuid)
            )"""
        )
        self.event_repo.conn.execute(
            """CREATE TABLE IF NOT EXISTS mobile_visit_attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_key TEXT NOT NULL,
                attachment_uuid TEXT NOT NULL,
                client_uuid TEXT NOT NULL,
                file_name TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                data BLOB NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(owner_key, attachment_uuid)
            )"""
        )
        self.event_repo.conn.commit()

    @staticmethod
    def _visit_owner_key(device: dict[str, Any]) -> str:
        # Las visitas pertenecen al vendedor, no a un teléfono concreto.
        return f"user:{device['user_id']}" if device.get("user_id") else f"device:{device['id']}"

    def _list_visits(self, device: dict[str, Any]) -> None:
        self._ensure_visits_table()
        rows = self.event_repo.conn.execute(
            """SELECT client_uuid, title, note, latitude, longitude, status,
                      scheduled_at, client_id, client_phone, zone, result,
                      last_contact_at, created_at, updated_at, deleted, version
                 FROM mobile_visits WHERE owner_key = ? ORDER BY updated_at DESC""",
            (self._visit_owner_key(device),),
        ).fetchall()
        self._send_json_response(200, {"visits": [dict(row) for row in rows]})

    def _upsert_visit(self, device: dict[str, Any]) -> None:
        data = self._read_json_body()
        if data is None:
            return
        try:
            client_uuid = str(data.get("client_uuid") or "").strip()
            title = str(data.get("title") or "").strip()
            status = str(data.get("status") or "pending").strip()
            latitude = float(data.get("latitude"))
            longitude = float(data.get("longitude"))
            base_version = int(data.get("server_version") or 0)
        except (TypeError, ValueError):
            self._send_error(400, "Invalid visit payload")
            return
        if not client_uuid or len(client_uuid) > 100 or not title or len(title) > 160:
            self._send_error(400, "client_uuid and title are required")
            return
        if status not in {"pending", "completed"} or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            self._send_error(400, "Invalid visit status or location")
            return
        for key, limit in (
            ("note", 2000),
            ("result", 2000),
            ("client_id", 100),
            ("client_phone", 50),
            ("scheduled_at", 40),
            ("last_contact_at", 40),
            ("zone", 100),
        ):
            if data.get(key) is not None and len(str(data[key])) > limit:
                self._send_error(400, f"{key} is too long")
                return
        self._ensure_visits_table()
        now = datetime.now().isoformat(timespec="seconds")
        owner_key = self._visit_owner_key(device)
        existing = self.event_repo.conn.execute(
            "SELECT * FROM mobile_visits WHERE owner_key = ? AND client_uuid = ?",
            (owner_key, client_uuid),
        ).fetchone()
        force = bool(data.get("force", False))
        if existing and not force and base_version != int(existing["version"] or 0):
            self._send_json_response(
                409,
                {
                    "error": "visit_conflict",
                    "visit": dict(existing),
                },
            )
            return
        values = (
            title,
            data.get("note"),
            latitude,
            longitude,
            status,
            data.get("scheduled_at"),
            data.get("client_id"),
            data.get("client_phone"),
            data.get("zone"),
            data.get("result"),
            data.get("last_contact_at"),
        )
        if existing:
            self.event_repo.conn.execute(
                """UPDATE mobile_visits SET title=?, note=?, latitude=?, longitude=?,
                       status=?, scheduled_at=?, client_id=?, client_phone=?, zone=?,
                       result=?, last_contact_at=?, updated_at=?, deleted=0,
                       version=version+1
                   WHERE owner_key=? AND client_uuid=?""",
                (*values, now, owner_key, client_uuid),
            )
        else:
            self.event_repo.conn.execute(
                """INSERT INTO mobile_visits(
                       owner_key, client_uuid, title, note, latitude, longitude,
                       status, scheduled_at, client_id, client_phone, zone, result,
                       last_contact_at, created_at, updated_at, deleted, version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1)""",
                (
                    owner_key,
                    client_uuid,
                    *values,
                    str(data.get("created_at") or now),
                    now,
                ),
            )
        self.event_repo.conn.commit()
        saved = self.event_repo.conn.execute(
            """SELECT client_uuid, title, note, latitude, longitude, status,
                      scheduled_at, client_id, client_phone, zone, result,
                      last_contact_at, created_at, updated_at, deleted, version
                 FROM mobile_visits WHERE owner_key = ? AND client_uuid = ?""",
            (owner_key, client_uuid),
        ).fetchone()
        self._send_json_response(200, {"ok": True, "visit": dict(saved)})

    def _delete_visit(self, device: dict[str, Any]) -> None:
        data = self._read_json_body()
        client_uuid = str((data or {}).get("client_uuid") or "").strip()
        if not client_uuid or len(client_uuid) > 100:
            self._send_error(400, "client_uuid is required")
            return
        self._ensure_visits_table()
        now = datetime.now().isoformat(timespec="seconds")
        self.event_repo.conn.execute(
            """INSERT INTO mobile_visits(owner_key, client_uuid, title, latitude,
                   longitude, status, created_at, updated_at, deleted)
               VALUES (?, ?, '[deleted]', 0, 0, 'pending', ?, ?, 1)
               ON CONFLICT(owner_key, client_uuid) DO UPDATE SET
                   deleted=1, updated_at=excluded.updated_at,
                   version=mobile_visits.version+1""",
            (self._visit_owner_key(device), client_uuid, now, now),
        )
        self.event_repo.conn.commit()
        self._send_json_response(200, {"ok": True})

    def _list_visit_history(self, device: dict[str, Any]) -> None:
        self._ensure_visits_table()
        rows = self.event_repo.conn.execute(
            """SELECT event_uuid, client_uuid, action, note, created_at
                 FROM mobile_visit_history WHERE owner_key = ?
                 ORDER BY created_at DESC""",
            (self._visit_owner_key(device),),
        ).fetchall()
        self._send_json_response(200, {"history": [dict(row) for row in rows]})

    def _upsert_visit_history(self, device: dict[str, Any]) -> None:
        data = self._read_json_body()
        if data is None:
            return
        event_uuid = str(data.get("event_uuid") or "").strip()
        client_uuid = str(data.get("client_uuid") or "").strip()
        action = str(data.get("action") or "").strip()
        note = data.get("note")
        if (
            not event_uuid
            or len(event_uuid) > 100
            or not client_uuid
            or len(client_uuid) > 100
            or not action
            or len(action) > 160
            or (note is not None and len(str(note)) > 2000)
        ):
            self._send_error(400, "Invalid visit history payload")
            return
        self._ensure_visits_table()
        self.event_repo.conn.execute(
            """INSERT OR IGNORE INTO mobile_visit_history(
                   owner_key, event_uuid, client_uuid, action, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                self._visit_owner_key(device),
                event_uuid,
                client_uuid,
                action,
                note,
                str(data.get("created_at") or datetime.now().isoformat(timespec="seconds")),
            ),
        )
        self.event_repo.conn.commit()
        self._send_json_response(200, {"ok": True})

    def _list_visit_attachments(self, device: dict[str, Any]) -> None:
        self._ensure_visits_table()
        params = self._parse_url_params()
        client_uuid = str(params.get("client_uuid") or "").strip()
        sql = """SELECT attachment_uuid, client_uuid, file_name, mime_type,
                        created_at FROM mobile_visit_attachments
                 WHERE owner_key = ?"""
        values: list[Any] = [self._visit_owner_key(device)]
        if client_uuid:
            sql += " AND client_uuid = ?"
            values.append(client_uuid)
        sql += " ORDER BY created_at DESC"
        rows = self.event_repo.conn.execute(sql, values).fetchall()
        self._send_json_response(
            200, {"attachments": [dict(row) for row in rows]}
        )

    def _upload_visit_attachment(self, device: dict[str, Any]) -> None:
        metadata, images, _reference_images = self._read_multipart_images()
        if metadata is None or images is None:
            return
        attachment_uuid = str(metadata.get("attachment_uuid") or "").strip()
        client_uuid = str(metadata.get("client_uuid") or "").strip()
        if (
            not attachment_uuid
            or len(attachment_uuid) > 100
            or not client_uuid
            or len(client_uuid) > 100
            or len(images) != 1
        ):
            self._send_error(400, "Invalid visit attachment payload")
            return
        file_name, payload, mime_type = images[0]
        if len(payload) > 12 * 1024 * 1024:
            self._send_error(413, "La foto admite hasta 12 MB")
            return
        self._ensure_visits_table()
        self.event_repo.conn.execute(
            """INSERT OR IGNORE INTO mobile_visit_attachments(
                   owner_key, attachment_uuid, client_uuid, file_name,
                   mime_type, data, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                self._visit_owner_key(device),
                attachment_uuid,
                client_uuid,
                file_name[:180],
                mime_type,
                payload,
                str(metadata.get("created_at") or datetime.now().isoformat(timespec="seconds")),
            ),
        )
        self.event_repo.conn.commit()
        self._send_json_response(200, {"ok": True})

    def _get_visit_attachment(
        self, device: dict[str, Any], attachment_uuid: str
    ) -> None:
        if not attachment_uuid or len(attachment_uuid) > 100:
            self._send_error(400, "Invalid attachment ID")
            return
        self._ensure_visits_table()
        row = self.event_repo.conn.execute(
            """SELECT mime_type, data FROM mobile_visit_attachments
                 WHERE owner_key = ? AND attachment_uuid = ?""",
            (self._visit_owner_key(device), attachment_uuid),
        ).fetchone()
        if not row:
            self._send_error(404, "Attachment not found")
            return
        self._send_bytes_response(200, str(row["mime_type"]), bytes(row["data"]))

    def _sync_pull(self, device: dict[str, Any]) -> None:
        """Sincronización incremental de solo lectura."""
        from app.services.sync_cursor_service import SyncCursorError

        params = self._parse_url_params()

        # Parsear y validar parámetros
        try:
            cursor_token = params.get("cursor")
            since = params.get("since")
            limit = int(params.get("limit", str(SyncCursorService.MAX_LIMIT)))
            types_str = params.get("types", "jobs,orders,clients")
            types = [t.strip() for t in types_str.split(",") if t.strip()]

            SyncCursorService.validate_limit(limit)
            SyncCursorService.validate_types(types)

            # Decodificar cursor si existe
            cursor_data = None
            if cursor_token:
                cursor_data = SyncCursorService.decode_cursor(cursor_token)
                # Validar compatibilidad con parámetros
                SyncCursorService.validate_cursor_compatibility(cursor_data, types, limit)
                # No aceptar since cuando hay cursor
                if since:
                    self._send_error(400, "Cannot use 'since' with cursor")
                    return
            elif since:
                # Validar timestamp when using since
                SyncCursorService._validate_timestamp(since)

            # Determinar snapshot_until
            if cursor_data:
                snapshot_until = cursor_data["snapshot_until"]
            else:
                snapshot_until = datetime.now().isoformat(timespec="seconds")

            # Inicializar cursores de entidad
            entity_cursors = {}
            if cursor_data:
                entity_cursors = cursor_data["entities"]
            else:
                for entity_type in types:
                    entity_cursors[entity_type] = SyncCursorService.create_initial_entity_cursor()

            # Consultar cada entidad
            entities_response = {}
            all_complete = True

            for entity_type in types:
                entity_cursor = entity_cursors[entity_type]

                # Si entidad está completa, no consultar
                if entity_cursor["complete"]:
                    entities_response[entity_type] = {"items": [], "has_more": False}
                    continue

                # Ejecutar query según tipo
                if entity_type == "jobs":
                    items, has_more = self._query_jobs(
                        entity_cursor, snapshot_until, limit, cursor_data is not None, device["id"]
                    )
                elif entity_type == "orders":
                    items, has_more = self._query_orders(
                        entity_cursor, snapshot_until, limit, cursor_data is not None, device["id"]
                    )
                elif entity_type == "clients":
                    items, has_more = self._query_clients(
                        entity_cursor, snapshot_until, limit, cursor_data is not None, device["id"]
                    )
                else:
                    continue

                # Actualizar cursor de entidad
                if items:
                    last_item = items[-1]
                    entity_cursors[entity_type] = SyncCursorService.update_entity_cursor(
                        entity_cursor, last_item["updated_at"], last_item["id"], has_more
                    )
                else:
                    entity_cursors[entity_type]["complete"] = True

                entities_response[entity_type] = {"items": items, "has_more": has_more}

                if not entity_cursors[entity_type]["complete"]:
                    all_complete = False

            # Construir next_cursor si hay más datos
            next_cursor = None
            if not all_complete:
                next_cursor = SyncCursorService.encode_cursor(
                    snapshot_until, set(types), limit, entity_cursors
                )

            response = {
                "server_time": datetime.now().isoformat(timespec="seconds"),
                "snapshot_until": snapshot_until,
                "scope_id": f"seller-device:{device['id']}",
                "complete": all_complete,
                "next_cursor": next_cursor,
                "entities": entities_response,
            }

            self._send_json_response(200, response)

        except SyncCursorError as e:
            logger.warning("Sync pull validation error: %s", e)
            self._send_error(400, str(e))
        except (ValueError, KeyError) as e:
            logger.error("Sync pull parameter error: %s", e)
            self._send_error(400, "Invalid parameters")
        except Exception as e:
            logger.error("Sync pull error: %s", e)
            self._send_error(500, "Internal server error")

    def _query_jobs(
        self, cursor: dict[str, Any], snapshot_until: str, limit: int, use_cursor: bool,
        device_id: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Consulta order_jobs con paginación por cursor."""
        limit_plus_one = limit + 1

        if use_cursor and cursor["updated_at"]:
            # Página posterior con cursor
            query = """
                SELECT j.id, j.order_id, j.title, j.material, j.size, j.quantity,
                       j.status, j.notes, j.sort_order, j.created_at, j.updated_at
                FROM order_jobs j
                JOIN orders o ON o.id = j.order_id
                WHERE o.creator_device_id = ?
                AND (j.updated_at, j.id) > (?, ?)
                AND j.updated_at <= ?
                ORDER BY j.updated_at ASC, j.id ASC
                LIMIT ?
            """
            params = (device_id, cursor["updated_at"], cursor["id"], snapshot_until, limit_plus_one)
        else:
            # Primera página (con since o sin since)
            if cursor["updated_at"]:
                # Con since (nueva ronda incremental)
                query = """
                    SELECT j.id, j.order_id, j.title, j.material, j.size, j.quantity,
                           j.status, j.notes, j.sort_order, j.created_at, j.updated_at
                    FROM order_jobs j
                    JOIN orders o ON o.id = j.order_id
                    WHERE o.creator_device_id = ?
                    AND j.updated_at >= ?
                    AND j.updated_at <= ?
                    ORDER BY j.updated_at ASC, j.id ASC
                    LIMIT ?
                """
                params = (device_id, cursor["updated_at"], snapshot_until, limit_plus_one)
            else:
                # Primera sync absoluta
                query = """
                    SELECT j.id, j.order_id, j.title, j.material, j.size, j.quantity,
                           j.status, j.notes, j.sort_order, j.created_at, j.updated_at
                    FROM order_jobs j
                    JOIN orders o ON o.id = j.order_id
                    WHERE o.creator_device_id = ?
                    AND j.updated_at <= ?
                    ORDER BY j.updated_at ASC, j.id ASC
                    LIMIT ?
                """
                params = (device_id, snapshot_until, limit_plus_one)

        rows = self.event_repo.conn.execute(query, params).fetchall()
        items = [dict(row) for row in rows[:limit]]
        has_more = len(rows) > limit
        return items, has_more

    def _query_orders(
        self, cursor: dict[str, Any], snapshot_until: str, limit: int, use_cursor: bool, device_id: int
    ) -> tuple[list[dict[str, Any]], bool]:
        """Consulta orders con paginación por cursor."""
        limit_plus_one = limit + 1

        if use_cursor and cursor["updated_at"]:
            query = """
                SELECT id, client, client_id, whatsapp, order_date, status,
                       material, size, quantity, delivery_date, print_priority,
                       is_archived, observations, order_concept, order_description,
                       created_at, updated_at
                FROM orders
                WHERE creator_device_id = ?
                AND (updated_at, id) > (?, ?)
                AND updated_at <= ?
                ORDER BY updated_at ASC, id ASC
                LIMIT ?
            """
            params = (device_id, cursor["updated_at"], cursor["id"], snapshot_until, limit_plus_one)
        else:
            if cursor["updated_at"]:
                query = """
                    SELECT id, client, client_id, whatsapp, order_date, status,
                           material, size, quantity, delivery_date, print_priority,
                           is_archived, observations, order_concept, order_description,
                           created_at, updated_at
                    FROM orders
                    WHERE creator_device_id = ?
                    AND updated_at >= ?
                    AND updated_at <= ?
                    ORDER BY updated_at ASC, id ASC
                    LIMIT ?
                """
                params = (device_id, cursor["updated_at"], snapshot_until, limit_plus_one)
            else:
                query = """
                    SELECT id, client, client_id, whatsapp, order_date, status,
                           material, size, quantity, delivery_date, print_priority,
                           is_archived, observations, order_concept, order_description,
                           created_at, updated_at
                    FROM orders
                    WHERE creator_device_id = ?
                    AND updated_at <= ?
                    ORDER BY updated_at ASC, id ASC
                    LIMIT ?
                """
                params = (device_id, snapshot_until, limit_plus_one)

        rows = self.event_repo.conn.execute(query, params).fetchall()
        items = [dict(row) for row in rows[:limit]]
        has_more = len(rows) > limit
        return items, has_more

    def _query_clients(
        self, cursor: dict[str, Any], snapshot_until: str, limit: int, use_cursor: bool,
        device_id: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Consulta clients con paginación por cursor."""
        limit_plus_one = limit + 1

        if use_cursor and cursor["updated_at"]:
            query = """
                SELECT id, name, whatsapp, client_type, created_at, updated_at
                FROM clients
                WHERE EXISTS (
                    SELECT 1 FROM orders
                    WHERE orders.client_id = clients.id
                      AND orders.creator_device_id = ?
                )
                AND (updated_at, id) > (?, ?)
                AND updated_at <= ?
                ORDER BY updated_at ASC, id ASC
                LIMIT ?
            """
            params = (device_id, cursor["updated_at"], cursor["id"], snapshot_until, limit_plus_one)
        else:
            if cursor["updated_at"]:
                query = """
                    SELECT id, name, whatsapp, client_type, created_at, updated_at
                    FROM clients
                    WHERE EXISTS (
                        SELECT 1 FROM orders
                        WHERE orders.client_id = clients.id
                          AND orders.creator_device_id = ?
                    )
                    AND updated_at >= ?
                    AND updated_at <= ?
                    ORDER BY updated_at ASC, id ASC
                    LIMIT ?
                """
                params = (device_id, cursor["updated_at"], snapshot_until, limit_plus_one)
            else:
                query = """
                    SELECT id, name, whatsapp, client_type, created_at, updated_at
                    FROM clients
                    WHERE EXISTS (
                        SELECT 1 FROM orders
                        WHERE orders.client_id = clients.id
                          AND orders.creator_device_id = ?
                    )
                    AND updated_at <= ?
                    ORDER BY updated_at ASC, id ASC
                    LIMIT ?
                """
                params = (device_id, snapshot_until, limit_plus_one)

        rows = self.event_repo.conn.execute(query, params).fetchall()
        items = [dict(row) for row in rows[:limit]]
        has_more = len(rows) > limit
        return items, has_more

    def log_message(self, format, *args):
        """Override para evitar logging default de HTTPServer."""
        logger.info("%s - %s", self.address_string(), format % args)


class MobileJobsServer:
    """Servidor HTTP para API de jobs móviles."""

    def __init__(self, event_repo: EventRepository, event_bus, port: int = 8765):
        self.event_repo = event_repo
        self.event_bus = event_bus
        self.port = port
        self.access_control = MobileAccessRepository(event_repo.conn)
        self.mobile_users = MobileUserRepository(event_repo.conn)
        self.server: HTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()

    def start(self) -> None:
        """Inicia el servidor HTTP en segundo plano sin bloquear Tkinter."""
        with self._lifecycle_lock:
            if self._server_thread is not None and self._server_thread.is_alive():
                logger.debug("Mobile Jobs API server is already running on port %d", self.port)
                return

            # Incorporar cambios hechos fuera del panel antes de escuchar.
            self.access_control.reload()

            def handler(*args, **kwargs):
                return MobileJobsHandler(
                    *args,
                    event_repo=self.event_repo,
                    event_bus=self.event_bus,
                    access_control=self.access_control,
                    mobile_users=self.mobile_users,
                    **kwargs,
                )

            try:
                server = HTTPServer(("0.0.0.0", self.port), handler)
            except OSError:
                logger.exception(
                    "Could not start Mobile Jobs API server on port %d",
                    self.port,
                )
                self.server = None
                self._server_thread = None
                return

            thread = threading.Thread(
                target=self._serve_forever,
                args=(server,),
                name=f"mobile-jobs-server-{self.port}",
                daemon=True,
            )
            self.server = server
            self._server_thread = thread
            thread.start()

        logger.info("Mobile Jobs API server started on port %d", self.port)

    def _serve_forever(self, server: HTTPServer) -> None:
        """Ejecuta el bucle HTTP dentro del hilo dedicado."""
        try:
            server.serve_forever(poll_interval=0.5)
        except Exception:
            logger.exception("Mobile Jobs API server stopped unexpectedly")
        finally:
            server.server_close()
            with self._lifecycle_lock:
                if self.server is server:
                    self.server = None
                if self._server_thread is threading.current_thread():
                    self._server_thread = None

    def stop(self, timeout: float = 3.0) -> None:
        """Detiene el servidor HTTP y espera brevemente a que termine su hilo."""
        with self._lifecycle_lock:
            server = self.server
            thread = self._server_thread

        if server is None:
            return

        logger.info("Stopping Mobile Jobs API server")
        try:
            server.shutdown()
        except Exception:
            logger.exception("Error while shutting down Mobile Jobs API server")
        finally:
            server.server_close()

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.warning(
                    "Mobile Jobs API server thread did not stop within %.1f seconds",
                    timeout,
                )

        with self._lifecycle_lock:
            if self.server is server:
                self.server = None
            if self._server_thread is thread:
                self._server_thread = None

    @property
    def is_running(self) -> bool:
        """Indica si el hilo del servidor sigue activo."""
        thread = self._server_thread
        return thread is not None and thread.is_alive()
