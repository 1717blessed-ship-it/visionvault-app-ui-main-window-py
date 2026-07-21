"""Servicio transaccional para cambios de etapa de producción.

Este servicio centraliza la lógica de transición de etapas, asegurando:
- Validación de transiciones usando timeline.py
- Estado derivado de orders desde order_jobs
- Auditoría completa en production_stage_history
- Publicación de eventos post-COMMIT
- Manejo de estados legacy sin fallback silencioso
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Literal

from app.workflow.timeline import (
    get_current_stage,
    get_stage_progress,
    get_workflow,
    workflow_stages,
)

logger = logging.getLogger(__name__)

# Mapeo explícito de estados legacy a etapas del workflow
LEGACY_STAGE_MAPPING: dict[str, str] = {
    "Nuevo": "Recibido",
    "En revisión": "Esperando archivos",
    "En diseño": "Esperando archivos",
    "Esperando aprobación": "Esperando archivos",
    "Esperando pago": "Recibido",
    "Pendiente": "Recibido",
    "Bloqueado": "Recibado",
    "Listo para Armado de Planchas": "Listo para armado de planchas",
    "En Armado de Planchas": "En armado de planchas",
    "Listo para plancha": "Listo para armado de planchas",
    "En producción": "En armado de planchas",
    "Impreso": "Impresión",
    "Aprobado": "Diseños confirmados",
    "Presupuesto enviado": "Recibido",
    "Rechazado": "Recibido",
}

# Fuentes válidas para cambios de etapa
SourceType = Literal["mobile", "desktop", "automation", "migration"]


class ProductionStageService:
    """Servicio para gestión de etapas de producción."""

    def __init__(self, connection: sqlite3.Connection, event_bus):
        self.conn = connection
        self.event_bus = event_bus

    def normalize_stage(self, stage: str) -> str:
        """Normaliza un estado legacy a una etapa del workflow.
        
        Si el estado no está en el mapeo, se conserva el valor original
        y se registra un warning.
        """
        if stage in LEGACY_STAGE_MAPPING:
            return LEGACY_STAGE_MAPPING[stage]
        
        # Verificar si ya es una etapa válida del workflow
        valid_stages = [
            "Recibido", "Esperando archivos", "Diseños confirmados",
            "Listo para armado de planchas", "En armado de planchas",
            "Listo para imprimir", "Impresión", "Sublimado / Laminado",
            "Corte", "Control de calidad", "Finalizado", "Entregado",
            "Armado de plancha", "Laminado", "Corte plotter",
            "Sublimado", "Empaquetado", "Preparación", "Producción", "Terminación",
        ]
        
        if stage in valid_stages:
            return stage
        
        logger.warning(
            "Estado de job no reconocido: '%s'. Se conservará el valor original.",
            stage
        )
        return stage

    def derive_order_status(self, order_id: int) -> str:
        """Calcula el estado derivado de un pedido basado en sus jobs.
        
        Lógica agregada:
        - Si todos los jobs están Entregados → Entregado
        - Si todos están Finalizados o Entregados → Finalizado
        - Si alguno está en una etapa productiva → En producción
        - Si todos están pendientes → Pendiente
        - Si no existen jobs → conservar estado actual o devolver Sin trabajos
        """
        # Obtener todos los jobs del pedido
        jobs = self.conn.execute(
            "SELECT status FROM order_jobs WHERE order_id = ?", (order_id,)
        ).fetchall()
        
        if not jobs:
            # No hay jobs, intentar conservar estado actual
            current = self.conn.execute(
                "SELECT status FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
            return current["status"] if current else "Sin trabajos"
        
        # Normalizar todos los estados
        normalized_stages = [self.normalize_stage(job["status"]) for job in jobs]
        
        # Verificar si todos están Entregados
        if all(stage == "Entregado" for stage in normalized_stages):
            return "Entregado"
        
        # Verificar si todos están Finalizados o Entregados
        if all(stage in ("Finalizado", "Entregado") for stage in normalized_stages):
            return "Finalizado"
        
        # Verificar si alguno está en etapa productiva
        productive_stages = {
            "Diseños confirmados", "Listo para armado de planchas", "En armado de planchas",
            "Listo para imprimir", "Impresión", "Sublimado / Laminado", "Corte",
            "Control de calidad", "Armado de plancha", "Laminado", "Corte plotter",
            "Sublimado", "Preparación", "Producción", "Terminación",
        }
        if any(stage in productive_stages for stage in normalized_stages):
            return "En producción"
        
        # Si todos están pendientes
        if all(stage == "Recibido" for stage in normalized_stages):
            return "Pendiente"
        
        # Caso por defecto
        return "En producción"

    def calculate_order_progress(self, order_id: int) -> float:
        """Calcula el progreso del pedido basado en el progreso de sus jobs."""
        jobs = self.conn.execute(
            "SELECT id, material, status FROM order_jobs WHERE order_id = ?", (order_id,)
        ).fetchall()
        
        if not jobs:
            return 0.0
        
        total_progress = 0.0
        for job in jobs:
            # Crear dict mínimo para get_stage_progress
            job_dict = {"id": job["id"], "material": job["material"], "status": job["status"]}
            total_progress += get_stage_progress(job_dict)
        
        return total_progress / len(jobs)

    def validate_transition(
        self, job: dict, new_stage: str
    ) -> tuple[bool, str]:
        """Valida si una transición de etapa es válida.
        
        Retorna (is_valid, error_message).
        """
        current_stage = self.normalize_stage(job.get("status", "Recibido"))
        new_stage_normalized = self.normalize_stage(new_stage)
        
        # Obtener workflow apropiado
        workflow = get_workflow(job)
        stages = [stage for stage, _ in workflow]
        
        # Verificar que ambas etapas existan en el workflow
        if current_stage not in stages:
            return False, f"Etapa actual '{current_stage}' no está en el workflow"
        
        if new_stage_normalized not in stages:
            return False, f"Etapa destino '{new_stage_normalized}' no está en el workflow"
        
        # Permitir cualquier transición (avanzar o retroceder)
        # La UI debe confirmar transiciones importantes
        return True, ""

    def change_job_stage(
        self,
        job_id: int,
        new_stage: str,
        device_id: int,
        device_name: str,
        operator_name: str = "",
        source: SourceType = "mobile",
        notes: str = "",
    ) -> tuple[bool, str, dict | None]:
        """Cambia la etapa de un job de forma transaccional.
        
        Flujo transaccional:
        1. Validar sesión y dispositivo activo
        2. Obtener el job y el pedido
        3. Validar transición
        4. Actualizar order_jobs.status
        5. Insertar production_stage_history
        6. Recalcular orders.status
        7. Actualizar orders.updated_at
        8. Registrar order_events
        COMMIT
        9. Publicar event_bus (post-COMMIT)
        10. Generar notificaciones si corresponde
        
        Retorna (success, message, job_data).
        """
        now = datetime.now().isoformat(timespec="seconds")
        
        try:
            # Iniciar transacción
            with self.conn:
                # Obtener el job
                job = self.conn.execute(
                    """SELECT id, order_id, title, material, size, quantity, status
                       FROM order_jobs WHERE id = ?""",
                    (job_id,),
                ).fetchone()
                
                if not job:
                    return False, "Job no encontrado", None
                
                job_dict = dict(job)
                
                # Validar transición
                is_valid, error_msg = self.validate_transition(job_dict, new_stage)
                if not is_valid:
                    return False, error_msg, None
                
                old_stage = job_dict["status"]
                new_stage_normalized = self.normalize_stage(new_stage)
                
                # Actualizar job
                self.conn.execute(
                    "UPDATE order_jobs SET status = ?, updated_at = ? WHERE id = ?",
                    (new_stage_normalized, now, job_id),
                )
                
                # Insertar historial
                self.conn.execute(
                    """INSERT INTO production_stage_history
                       (job_id, order_id, old_stage, new_stage, device_id, device_name,
                        operator_name, source, notes, changed_at)
                       VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (job_id, job_dict["order_id"], old_stage, new_stage_normalized,
                     device_id, device_name, operator_name, source, notes, now),
                )
                
                # Recalcular estado del pedido
                new_order_status = self.derive_order_status(job_dict["order_id"])
                self.conn.execute(
                    "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
                    (new_order_status, now, job_dict["order_id"]),
                )
                
                # Registrar evento en order_events
                self.conn.execute(
                    """INSERT INTO order_events (order_id, event_type, message, data_json, created_at)
                       VALUES(?, 'stage.changed', ?, ?, ?)""",
                    (
                        job_dict["order_id"],
                        f"Job #{job_id}: {old_stage} → {new_stage_normalized}",
                        f'{{"job_id": {job_id}, "old_stage": "{old_stage}", "new_stage": "{new_stage_normalized}", "device_id": {device_id}, "source": "{source}"}}',
                        now,
                    ),
                )
                
                # Commit automático al salir del with
            
            # Post-COMMIT: publicar eventos
            try:
                self.event_bus.publish(
                    event_type="stage.changed",
                    title=f"Etapa actualizada",
                    message=f"Job #{job_id}: {old_stage} → {new_stage_normalized}",
                    priority="normal",
                    entity_type="job",
                    entity_id=job_id,
                    payload={
                        "job_id": job_id,
                        "order_id": job_dict["order_id"],
                        "old_stage": old_stage,
                        "new_stage": new_stage_normalized,
                        "device_id": device_id,
                        "device_name": device_name,
                        "source": source,
                    },
                )
                
                # Si la etapa es Finalizado o Entregado, publicar producción completada
                if new_stage_normalized in ("Finalizado", "Entregado"):
                    self.event_bus.publish_production_completed(
                        job_dict["order_id"], f"Job #{job_id} completado"
                    )
                
            except Exception as e:
                logger.error("Error publicando evento post-COMMIT para job %d: %s", job_id, e)
                # No revertir la transacción ya confirmada
            
            # Retornar datos actualizados del job
            updated_job = self.conn.execute(
                """SELECT id, order_id, title, material, size, quantity, status, updated_at
                   FROM order_jobs WHERE id = ?""",
                (job_id,),
            ).fetchone()
            
            return True, "Etapa actualizada correctamente", dict(updated_job)
            
        except sqlite3.Error as e:
            logger.error("Error de base de datos al cambiar etapa del job %d: %s", job_id, e)
            return False, f"Error de base de datos: {e}", None
        except Exception as e:
            logger.error("Error inesperado al cambiar etapa del job %d: %s", job_id, e)
            return False, f"Error inesperado: {e}", None
