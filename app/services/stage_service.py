"""Servicio para gestión de métricas y datos del tablero de producción por etapas.

Este servicio proporciona:
- Pedidos agrupados por etapa actual
- Métricas agregadas por etapa (count, urgentes, antigüedad)
- Datos completos de pedidos para visualización

Diseñado para ser consumido por múltiples vistas de producción.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.workflow.timeline import get_current_stage, get_workflow


@dataclass
class StageMetrics:
    """Métricas agregadas para una etapa de producción."""
    
    stage: str
    total_orders: int
    total_jobs: int
    urgent_count: int  # Pedidos con print_priority >= 3
    oldest_order_days: float | None  # Días desde el pedido más antiguo en esta etapa
    oldest_order_id: int | None


@dataclass
class OrderSummary:
    """Resumen de un pedido para visualización en tiles."""
    
    order_id: int
    client_name: str
    order_date: str
    current_stage: str
    material: str
    quantity: int
    jobs_count: int
    priority: int  # 0-4
    is_urgent: bool
    delivery_date: str
    age_days: float
    jobs: list[dict]  # Lista de trabajos con su información


class StageService:
    """Servicio para obtener datos del tablero de producción por etapas."""
    
    def __init__(self, connection: sqlite3.Connection):
        self.conn = connection
        self.conn.row_factory = sqlite3.Row
    
    def get_all_stages(self) -> list[str]:
        """Obtiene todas las etapas únicas presentes en pedidos activos.
        
        Retorna las etapas en el orden del workflow general.
        """
        from app.workflow.timeline import GENERAL_WORKFLOW
        
        # Obtener etapas únicas de todos los jobs activos
        rows = self.conn.execute(
            """SELECT DISTINCT status 
               FROM order_jobs 
               WHERE order_id IN (
                   SELECT id FROM orders WHERE COALESCE(is_archived, 0) = 0
               )
               ORDER BY status"""
        ).fetchall()
        
        active_stages = {row["status"] for row in rows}
        
        # Ordenar según workflow general
        workflow_order = [stage for stage, _ in GENERAL_WORKFLOW]
        ordered_stages = [stage for stage in workflow_order if stage in active_stages]
        
        # Agregar etapas no estándar al final
        for stage in sorted(active_stages):
            if stage not in ordered_stages:
                ordered_stages.append(stage)
        
        return ordered_stages
    
    def get_stage_metrics(self, stage: str | None = None) -> list[StageMetrics]:
        """Obtiene métricas agregadas por etapa.
        
        Si stage es None, retorna métricas para todas las etapas.
        Si stage es especificado, retorna solo métricas de esa etapa.
        
        Métricas incluidas:
        - total_orders: cantidad de pedidos en la etapa
        - total_jobs: cantidad de trabajos en la etapa
        - urgent_count: pedidos con prioridad >= 3
        - oldest_order_days: días desde el pedido más antiguo
        - oldest_order_id: ID del pedido más antiguo
        """
        now = datetime.now()
        
        # Query para obtener pedidos con sus jobs
        query = """
            SELECT 
                o.id,
                o.order_date,
                o.print_priority,
                o.created_at,
                COUNT(j.id) as jobs_count
            FROM orders o
            LEFT JOIN order_jobs j ON j.order_id = o.id
            WHERE COALESCE(o.is_archived, 0) = 0
            GROUP BY o.id
        """
        
        orders = [dict(row) for row in self.conn.execute(query).fetchall()]
        
        # Agrupar por etapa y calcular métricas
        stage_data: dict[str, list[dict]] = {}
        
        for order in orders:
            # Obtener jobs del pedido
            jobs = [dict(j) for j in self.conn.execute(
                "SELECT * FROM order_jobs WHERE order_id = ?", (order["id"],)
            ).fetchall()]
            
            order["jobs"] = jobs
            
            # Determinar etapa actual del pedido (basado en sus jobs)
            if jobs:
                # Usar la etapa más avanzada de los jobs
                current_stage = self._get_order_current_stage(order)
            else:
                current_stage = "Recibido"
            
            if current_stage not in stage_data:
                stage_data[current_stage] = []
            
            stage_data[current_stage].append(order)
        
        # Construir métricas por etapa
        metrics_list = []
        
        stages_to_process = [stage] if stage else stage_data.keys()
        
        for stage_name in stages_to_process:
            orders_in_stage = stage_data.get(stage_name, [])
            
            if not orders_in_stage:
                if stage:  # Si se solicita una etapa específica, incluirla aunque esté vacía
                    metrics_list.append(StageMetrics(
                        stage=stage_name,
                        total_orders=0,
                        total_jobs=0,
                        urgent_count=0,
                        oldest_order_days=None,
                        oldest_order_id=None,
                    ))
                continue
            
            # Calcular métricas
            total_orders = len(orders_in_stage)
            total_jobs = sum(order["jobs_count"] for order in orders_in_stage)
            urgent_count = sum(1 for o in orders_in_stage if int(o.get("print_priority", 0) or 0) >= 3)
            
            # Encontrar pedido más antiguo
            oldest_order = min(orders_in_stage, key=lambda o: o["order_date"] or o["created_at"])
            oldest_date_str = oldest_order["order_date"] or oldest_order["created_at"]
            
            try:
                # Intentar parsear la fecha
                if "T" in oldest_date_str:
                    oldest_date = datetime.fromisoformat(oldest_date_str.replace("Z", "+00:00"))
                else:
                    oldest_date = datetime.strptime(oldest_date_str[:10], "%Y-%m-%d")
                
                oldest_days = (now - oldest_date).total_seconds() / 86400
            except (ValueError, TypeError):
                oldest_days = 0.0
            
            metrics_list.append(StageMetrics(
                stage=stage_name,
                total_orders=total_orders,
                total_jobs=total_jobs,
                urgent_count=urgent_count,
                oldest_order_days=round(oldest_days, 1),
                oldest_order_id=oldest_order["id"],
            ))
        
        return sorted(metrics_list, key=lambda m: m.stage)
    
    def get_orders_by_stage(self, stage: str, limit: int | None = None) -> list[OrderSummary]:
        """Obtiene pedidos de una etapa específica con información completa.
        
        Los pedidos se ordenan por prioridad (desc) y antigüedad (asc).
        """
        now = datetime.now()
        
        # Obtener pedidos activos
        query = """
            SELECT 
                o.*,
                COALESCE(c.name, o.client) AS client_name,
                COUNT(j.id) as jobs_count
            FROM orders o
            LEFT JOIN clients c ON c.id = o.client_id
            LEFT JOIN order_jobs j ON j.order_id = o.id
            WHERE COALESCE(o.is_archived, 0) = 0
            GROUP BY o.id
            ORDER BY o.print_priority DESC, o.order_date ASC
        """
        
        if limit:
            query += f" LIMIT {limit}"
        
        orders = [dict(row) for row in self.conn.execute(query).fetchall()]
        
        # Filtrar por etapa y construir OrderSummary
        summaries = []
        
        for order in orders:
            # Obtener jobs
            jobs = [dict(j) for j in self.conn.execute(
                "SELECT * FROM order_jobs WHERE order_id = ? ORDER BY sort_order, id",
                (order["id"],)
            ).fetchall()]
            
            order["jobs"] = jobs
            
            # Determinar etapa actual
            current_stage = self._get_order_current_stage(order)
            
            # Filtrar por etapa solicitada
            if current_stage != stage:
                continue
            
            # Calcular antigüedad
            order_date_str = order["order_date"] or order["created_at"]
            try:
                if "T" in order_date_str:
                    order_date = datetime.fromisoformat(order_date_str.replace("Z", "+00:00"))
                else:
                    order_date = datetime.strptime(order_date_str[:10], "%Y-%m-%d")
                age_days = (now - order_date).total_seconds() / 86400
            except (ValueError, TypeError):
                age_days = 0.0
            
            priority = int(order.get("print_priority", 0) or 0)
            
            summaries.append(OrderSummary(
                order_id=order["id"],
                client_name=order["client_name"],
                order_date=order["order_date"] or order["created_at"],
                current_stage=current_stage,
                material=order.get("material", ""),
                quantity=int(order.get("quantity", 0) or 0),
                jobs_count=len(jobs),
                priority=priority,
                is_urgent=priority >= 3,
                delivery_date=order.get("delivery_date", ""),
                age_days=round(age_days, 1),
                jobs=jobs,
            ))
        
        return summaries
    
    def _get_order_current_stage(self, order: dict) -> str:
        """Determina la etapa actual de un pedido basado en sus jobs.
        
        Usa la etapa más avanzada de todos los jobs del pedido.
        """
        jobs = order.get("jobs", [])
        
        if not jobs:
            return "Recibido"
        
        # Obtener workflow del pedido
        workflow = get_workflow(order)
        stage_order = {stage: idx for idx, (stage, _) in enumerate(workflow)}
        
        # Encontrar la etapa más avanzada
        max_stage = "Recibido"
        max_idx = -1
        
        for job in jobs:
            job_stage = job.get("status", "Recibido")
            job_idx = stage_order.get(job_stage, 0)
            
            if job_idx > max_idx:
                max_idx = job_idx
                max_stage = job_stage
        
        return max_stage
    
    def get_all_stages_with_metrics(self) -> list[tuple[str, StageMetrics]]:
        """Obtiene todas las etapas activas con sus métricas.
        
        Retorna lista de tuplas (stage_name, metrics) ordenadas por workflow.
        """
        stages = self.get_all_stages()
        metrics_by_stage = {m.stage: m for m in self.get_stage_metrics()}
        
        result = []
        for stage in stages:
            metrics = metrics_by_stage.get(stage, StageMetrics(
                stage=stage,
                total_orders=0,
                total_jobs=0,
                urgent_count=0,
                oldest_order_days=None,
                oldest_order_id=None,
            ))
            result.append((stage, metrics))
        
        return result
