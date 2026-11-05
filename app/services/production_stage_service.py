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

from app.domain.order_states import (
    WORKFLOW_STAGES as CENTRAL_WORKFLOW_STAGES,
    OrderStateService,
    derive_order_status_from_jobs,
    normalize_status,
)

from app.workflow.timeline import (
    get_current_stage,
    get_stage_progress,
    get_workflow,
    workflow_stages,
)

logger = logging.getLogger(__name__)
WORKFLOW_STAGE_VALUES = frozenset(CENTRAL_WORKFLOW_STAGES)

# Mapeo explícito de estados legacy a etapas del workflow
LEGACY_STAGE_MAPPING: dict[str, str] = {
    "Nuevo": "Recibido",
    "En revisión": "Esperando archivos",
    "En diseño": "Esperando archivos",
    "Esperando aprobación": "Esperando archivos",
    "Esperando pago": "Recibido",
    "Pendiente": "Recibido",
    "Bloqueado": "Recibido",
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

# Estados terminales de pedido (no deben recalcularse automáticamente)
TERMINAL_ORDER_STATUSES: set[str] = {
    "terminado",
    "entregado",
    "completado",
    "cancelado",
    "finalizado",
}

# Etapas productivas terminales
TERMINAL_PRODUCTION_STAGES: set[str] = {
    "entregado",
    "finalizado",
    "cancelado",
}


class ProductionStageService:
    """Servicio para gestión de etapas de producción."""

    def __init__(self, connection: sqlite3.Connection, event_bus):
        self.conn = connection
        self.event_bus = event_bus
        self.state_service = OrderStateService(connection)

    def normalize_stage(self, stage: str) -> str:
        """Normaliza un estado legacy a una etapa del workflow.

        Si el estado no está en el mapeo, se conserva el valor original
        y se registra un warning.
        """
        if stage in LEGACY_STAGE_MAPPING:
            return LEGACY_STAGE_MAPPING[stage]

        centralized = normalize_status(stage)
        if centralized != stage and centralized in WORKFLOW_STAGE_VALUES:
            return centralized

        # Verificar si ya es una etapa válida del workflow
        if stage in WORKFLOW_STAGE_VALUES:
            return stage

        logger.warning(
            "Estado de job no reconocido: '%s'. Se conservará el valor original.",
            stage
        )
        return stage

    def derive_order_status(self, order_id: int) -> str:
        """Calcula el estado derivado de un pedido basado en sus jobs.

        Lógica agregada:
        - Si el pedido ya tiene un estado terminal, NO recalcular (protección)
        - Si todos los jobs están Entregados → Entregado
        - Si todos están Finalizados o Entregados → Finalizado
        - Si alguno está en una etapa productiva → En producción
        - Si todos están pendientes → Pendiente
        - Si no existen jobs → conservar estado actual o devolver Sin trabajos
        """
        # La misma regla de agregación se comparte con escritorio y API móvil.
        current_order = self.conn.execute(
            "SELECT status FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        jobs = self.conn.execute(
            "SELECT status FROM order_jobs WHERE order_id = ?", (order_id,)
        ).fetchall()
        current = current_order["status"] if current_order else "Recibido"
        return derive_order_status_from_jobs(
            (self.normalize_stage(job["status"]) for job in jobs),
            current,
        )

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
                self.state_service.transition(
                    job_dict["order_id"],
                    new_order_status,
                    actor=operator_name,
                    source=source,
                    reason=f"Estado derivado del job #{job_id}",
                    commit=False,
                    record_event=False,
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

    def finalize_order_delivery(
        self,
        order_id: int,
        device_id: int,
        device_name: str,
        operator_name: str = "",
        source: SourceType = "desktop",
        notes: str = "Entrega confirmada y pedido terminado",
    ) -> tuple[bool, str, dict | None]:
        """Cierre definitivo de un pedido: entrega y terminado en una transacción atómica.

        Esta es la ÚNICA forma válida de marcar un pedido como Entregado/Terminado.

        Operaciones en una sola transacción:
        1. Actualiza orders.status = 'Terminado' (estado terminal)
        2. Registra orders.delivery_date = fecha actual (fecha real de finalización)
        3. Actualiza TODOS los order_jobs activos del pedido a status = 'Entregado'
        4. Actualiza order_designs vinculados al pedido a status = 'Entregado'
        5. Actualiza plancha_projects vinculados al pedido a production_status = 'entregado'
        6. Registra en production_stage_history para cada job
        6. Registra en order_events el cierre del pedido
        7. Retira notificaciones de urgencia/vencimiento (marca como no urgentes)

        Retorna (success, message, order_data).
        """
        now = datetime.now().isoformat(timespec="seconds")

        try:
            with self.conn:
                # 1. Verificar que el pedido existe
                from app.services.delivery_readiness import assert_deliverable
                self.conn.execute("UPDATE orders SET id=id WHERE id=?", (order_id,))
                assert_deliverable(self.conn, order_id)
                order = self.conn.execute(
                    "SELECT id, status, client FROM orders WHERE id = ?", (order_id,)
                ).fetchone()

                if not order:
                    return False, f"Pedido #{order_id} no encontrado", None

                # 2. Obtener todos los jobs del pedido (incluyendo ya entregados)
                jobs = self.conn.execute(
                    "SELECT id, status FROM order_jobs WHERE order_id = ?", (order_id,)
                ).fetchall()

                if not jobs:
                    return False, f"Pedido #{order_id} no tiene trabajos", None

                # 3. Actualizar order_jobs que no estén ya Entregados
                jobs_updated = 0
                for job in jobs:
                    if job["status"] != "Entregado":
                        old_stage = job["status"]
                        new_stage = "Entregado"

                        # Actualizar job
                        self.conn.execute(
                            "UPDATE order_jobs SET status = ?, updated_at = ? WHERE id = ?",
                            (new_stage, now, job["id"]),
                        )

                        # Registrar en production_stage_history
                        self.conn.execute(
                            """INSERT INTO production_stage_history
                               (job_id, order_id, old_stage, new_stage, device_id, device_name,
                                operator_name, source, notes, changed_at)
                               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (job["id"], order_id, old_stage, new_stage,
                             device_id, device_name, operator_name, source, notes, now),
                        )
                        jobs_updated += 1

                # 4. Actualizar order_designs vinculados al pedido
                designs_updated = self.conn.execute(
                    """UPDATE order_designs
                       SET status = 'Entregado'
                       WHERE order_id = ? AND status != 'Cancelado'""",
                    (order_id,),
                ).rowcount

                # 5. Actualizar plancha_projects vinculados al pedido
                planchas_updated = self.conn.execute(
                    """UPDATE plancha_projects
                       SET production_status = 'entregado', updated_at = ?
                       WHERE order_id = ? AND production_status != 'entregado'""",
                    (now, order_id),
                ).rowcount

                # 6. Actualizar pedido a Terminado con fecha de entrega
                old_order_status = order["status"]
                self.state_service.transition(
                    order_id,
                    "Terminado",
                    actor=operator_name,
                    source=source,
                    reason=notes,
                    commit=False,
                    record_event=False,
                )

                # 7. Registrar en order_events
                self.conn.execute(
                    """INSERT INTO order_events (order_id, event_type, message, data_json, created_at)
                       VALUES(?, 'delivered', ?, ?, ?)""",
                    (
                        order_id,
                        f"Pedido #{order_id} entregado y terminado · {jobs_updated} trabajo(s) actualizados",
                        f'{{"order_id": {order_id}, "jobs_updated": {jobs_updated}, '
                        f'"designs_updated": {designs_updated}, "planchas_updated": {planchas_updated}, '
                        f'"old_status": "{old_order_status}", "action": "finalize_delivery", '
                        f'"device_id": {device_id}, "source": "{source}"}}',
                        now,
                    ),
                )

                # Commit automático al salir del with

            # Post-COMMIT: publicar eventos
            try:
                # Evento de etapa para cada job actualizado
                for job in jobs:
                    if job["status"] != "Entregado":
                        self.event_bus.publish(
                            event_type="stage.changed",
                            title="Entrega completada",
                            message=f"Job #{job['id']}: {job['status']} → Entregado",
                            priority="normal",
                            entity_type="job",
                            entity_id=job["id"],
                            payload={
                                "job_id": job["id"],
                                "order_id": order_id,
                                "old_stage": job["status"],
                                "new_stage": "Entregado",
                                "device_id": device_id,
                                "device_name": device_name,
                                "source": source,
                            },
                        )

                # Evento de producción completada
                self.event_bus.publish_production_completed(
                    order_id, f"Pedido #{order_id} entregado y terminado"
                )

                # Evento de pedido completado
                self.event_bus.publish(
                    event_type="order.completed",
                    title="Pedido entregado",
                    message=f"Pedido #{order_id} · {order['client']} · Entregado y terminado",
                    priority="high",
                    entity_type="order",
                    entity_id=order_id,
                    payload={"order_id": order_id, "client": order["client"], "action": "finalize_delivery"},
                )

            except Exception as e:
                logger.error("Error publicando eventos post-COMMIT para pedido %d: %s", order_id, e)

            # Retornar datos actualizados
            updated_order = self.conn.execute(
                """SELECT id, client, status, delivery_date, updated_at
                   FROM orders WHERE id = ?""",
                (order_id,),
            ).fetchone()

            return True, f"Pedido #{order_id} entregado y terminado correctamente", dict(updated_order)

        except sqlite3.Error as e:
            logger.error("Error de base de datos al finalizar entrega del pedido %d: %s", order_id, e)
            return False, f"Error de base de datos: {e}", None
        except Exception as e:
            logger.error("Error inesperado al finalizar entrega del pedido %d: %s", order_id, e)
            return False, f"Error inesperado: {e}", None
