"""API HTTP para Operador Móvil - Gestión de jobs de producción.

Endpoints:
- GET /api/mobile/jobs - Listar jobs con filtros y paginación
- GET /api/mobile/jobs/{id} - Obtener detalle de un job
- POST /api/mobile/jobs/{id}/stage - Cambiar etapa de un job

Autenticación: Bearer token (session token generado durante vinculación)
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.events.event_repository import EventRepository
from app.services.production_stage_service import ProductionStageService
from app.workflow.timeline import (
    get_current_stage,
    get_stage_progress,
    get_workflow,
    workflow_stages,
)

logger = logging.getLogger(__name__)


class MobileJobsHandler(BaseHTTPRequestHandler):
    """Handler HTTP para API de jobs móviles."""

    def __init__(self, *args, event_repo: EventRepository, event_bus, **kwargs):
        self.event_repo = event_repo
        self.event_bus = event_bus
        self.stage_service = ProductionStageService(event_repo.connection, event_bus)
        super().__init__(*args, **kwargs)

    def _send_json_response(self, status_code: int, data: dict[str, Any]) -> None:
        """Envía una respuesta JSON."""
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

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
            self._send_error(401, "Authorization header missing")
            return None
        
        device = self.event_repo.validate_session_token(token)
        if not device:
            self._send_error(401, "Invalid or expired session token")
            return None
        
        return device

    def _parse_url_params(self) -> dict[str, str]:
        """Parsea parámetros de la URL."""
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        return {k: v[0] if v else "" for k, v in params.items()}

    def do_GET(self) -> None:
        """Maneja requests GET."""
        parsed = urlparse(self.path)
        
        # Validar autenticación
        device = self._validate_auth()
        if not device:
            return
        
        if parsed.path == "/api/mobile/jobs":
            self._list_jobs(device)
        elif parsed.path.startswith("/api/mobile/jobs/"):
            job_id = parsed.path.split("/")[-1]
            if job_id.isdigit():
                self._get_job_detail(int(job_id), device)
            else:
                self._send_error(400, "Invalid job ID")
        else:
            self._send_error(404, "Endpoint not found")

    def do_POST(self) -> None:
        """Maneja requests POST."""
        parsed = urlparse(self.path)
        
        # Validar autenticación
        device = self._validate_auth()
        if not device:
            return
        
        if parsed.path.startswith("/api/mobile/jobs/") and parsed.path.endswith("/stage"):
            job_id = parsed.path.split("/")[-2]
            if job_id.isdigit():
                self._change_job_stage(int(job_id), device)
            else:
                self._send_error(400, "Invalid job ID")
        else:
            self._send_error(404, "Endpoint not found")

    def _list_jobs(self, device: dict[str, Any]) -> None:
        """Lista jobs con filtros y paginación."""
        params = self._parse_url_params()
        
        # Filtros
        filter_type = params.get("filter", "")  # pending, production, ready
        limit = min(100, max(1, int(params.get("limit", "20"))))
        offset = max(0, int(params.get("offset", "0")))
        
        # Construir query base
        query = """
            SELECT j.id, j.order_id, j.title, j.material, j.size, j.quantity,
                   j.status, j.notes, j.sort_order, j.created_at, j.updated_at,
                   o.client, o.delivery_date, o.print_priority
            FROM order_jobs j
            JOIN orders o ON j.order_id = o.id
            WHERE o.is_archived = 0
        """
        params_list = []
        
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
            })
            
        except Exception as e:
            logger.error("Error listing jobs: %s", e)
            self._send_error(500, f"Error listing jobs: {e}")

    def _get_job_detail(self, job_id: int, device: dict[str, Any]) -> None:
        """Obtiene detalle de un job específico."""
        try:
            row = self.event_repo.conn.execute(
                """SELECT j.id, j.order_id, j.title, j.material, j.size, j.quantity,
                   j.status, j.notes, j.sort_order, j.created_at, j.updated_at,
                   o.client, o.whatsapp, o.delivery_date, o.print_priority, o.observations
                   FROM order_jobs j
                   JOIN orders o ON j.order_id = o.id
                   WHERE j.id = ?""",
                (job_id,),
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
            # Leer body
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode("utf-8"))
            
            new_stage = data.get("stage")
            if not new_stage:
                self._send_error(400, "stage field is required")
                return
            
            notes = data.get("notes", "")
            
            # Cambiar etapa usando el servicio
            success, message, job_data = self.stage_service.change_job_stage(
                job_id=job_id,
                new_stage=new_stage,
                device_id=device["id"],
                device_name=device["device_name"],
                operator_name=data.get("operator_name", ""),
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

    def log_message(self, format, *args):
        """Override para evitar logging default de HTTPServer."""
        logger.info("%s - %s", self.address_string(), format % args)


class MobileJobsServer:
    """Servidor HTTP para API de jobs móviles."""

    def __init__(self, event_repo: EventRepository, event_bus, port: int = 8766):
        self.event_repo = event_repo
        self.event_bus = event_bus
        self.port = port
        self.server: HTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()

    def start(self) -> None:
        """Inicia el servidor HTTP en segundo plano sin bloquear Tkinter."""
        with self._lifecycle_lock:
            if self._server_thread is not None and self._server_thread.is_alive():
                logger.debug("Mobile Jobs API server is already running on port %d", self.port)
                return

            def handler(*args, **kwargs):
                return MobileJobsHandler(
                    *args,
                    event_repo=self.event_repo,
                    event_bus=self.event_bus,
                    **kwargs,
                )

            try:
                server = HTTPServer(("localhost", self.port), handler)
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
