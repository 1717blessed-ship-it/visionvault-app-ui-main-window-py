"""Lectura productiva por pedido sobre demanda y reservas existentes."""
from __future__ import annotations

from app.services.production_batch_service import ProductionBatchService


class OrderProductionService:
    def __init__(self, database):
        self.database = database
        self.connection = database.connection

    def snapshot(self, order_id: int) -> dict:
        """Snapshot consistente; las etapas actuales nunca se suman como acumulados."""
        self.connection.execute("SAVEPOINT order_production_snapshot")
        try:
            return self._snapshot(int(order_id))
        finally:
            self.connection.execute("RELEASE SAVEPOINT order_production_snapshot")

    def _snapshot(self, order_id: int) -> dict:
        order = self.database.order(order_id)
        if not order:
            raise ValueError("El pedido no existe o está archivado.")
        candidates = {j.order_job_id: j for j in ProductionBatchService(self.database).job_candidates()
                      if j.order_id == order_id}
        jobs = []
        for job in self.database.order_jobs(order_id):
            job_id = int(job["id"])
            lines = self.connection.execute(
                "SELECT * FROM order_design_demand_lines WHERE order_id=? AND order_job_id=?",
                (order_id, job_id),
            ).fetchall()
            distribution_source = "demand"
            if not lines:
                lines = self.connection.execute(
                    "SELECT * FROM order_design_job_links WHERE order_id=? AND order_job_id=?",
                    (order_id, job_id),
                ).fetchall()
                distribution_source = "legacy" if lines else "none"
            assigned = sum(float(line["quantity"] or 0) for line in lines)
            totals = {row["state"]: float(row["total"] or 0) for row in self.connection.execute(
                """SELECT state,SUM(quantity) AS total FROM plancha_item_assignments
                   WHERE order_id=? AND order_job_id=? GROUP BY state""", (order_id, job_id))}
            prepared, printed, finished, released = (totals.get(s, 0) for s in ("prepared", "printed", "finished", "released"))
            committed = sum(q for state, q in totals.items() if state != "released")
            requested = float(job["quantity"] or 0)
            candidate = candidates.get(job_id)
            reason = candidate.blocked_reason if candidate else "Sin líneas de demanda preparables; vinculá los diseños al trabajo."
            available = candidate.available if candidate and not reason else 0
            unit = job.get("unit_kind") or (candidate.lines[0].unit_kind if candidate else "")
            unknown = sorted(set(totals) - {"prepared", "printed", "finished", "released"})
            if unknown:
                reason = "Estado productivo histórico sin correspondencia: " + ", ".join(unknown)
                available = 0
            if assigned > requested or committed > requested:
                reason = "Las cantidades históricas superan lo solicitado; revisá el trabajo antes de preparar."
                available = 0
            variant = self.connection.execute("SELECT name FROM product_variants WHERE id=?", (job.get("variant_id"),)).fetchone()
            jobs.append({
                "order_job_id": job_id, "product": job["title"],
                "variant": job.get("variant_name_snapshot") or (variant[0] if variant else ""),
                "material": job["material"], "unit_kind": unit,
                "requested": requested, "design_count": len(lines), "distributed": assigned,
                "undistributed": max(0, requested-assigned), "distribution_source": distribution_source,
                "prepared_current": prepared, "printed_current": printed, "finished": finished,
                "prepared_accumulated": prepared+printed+finished,
                "printed_accumulated": printed+finished, "released": released,
                "committed": committed, "assigned_unprepared": max(0, assigned-committed),
                "available": min(available, max(0, requested-committed)),
                "pending_print": max(0, requested-printed-finished),
                "pending_finish": max(0, requested-finished),
                "delivered": None, "blocked_reason": reason,
            })
        batches = [dict(row) for row in self.connection.execute(
            """SELECT b.id,b.name,b.status,b.created_at,COUNT(DISTINCT p.plancha_id) AS plancha_count,
                      GROUP_CONCAT(DISTINCT p.plancha_id) AS plancha_ids
                 FROM production_batches b JOIN production_batch_planchas p ON p.batch_id=b.id
                 JOIN plancha_item_assignments a ON a.plancha_id=p.plancha_id
                 WHERE a.order_id=? GROUP BY b.id ORDER BY b.id DESC""", (order_id,))]
        from app.services.delivery_readiness import readiness
        anomalies = []
        if str(order["status"]).strip().casefold() in {"entregado", "terminado", "completado"}:
            for row in readiness(self.connection, order_id):
                if not row["deliverable"]:
                    anomalies.append(f"Histórico inconsistente: trabajo #{row['job_id']} cerrado con {row['pending']:g} pendientes o sin origen verificado.")
        return {"order_id": order_id, "jobs": jobs, "batches": batches, "anomalies": anomalies,
                "delivery_status": order["status"],
                "delivery_note": "No hay cantidades de entrega independientes por trabajo."}

    def preview(self, order_id: int, requested: dict[int, int]):
        jobs = {j["order_job_id"]: j for j in self.snapshot(order_id)["jobs"]}
        for job_id, quantity in requested.items():
            job = jobs.get(int(job_id))
            if not job:
                raise ValueError("Seleccioná trabajos del pedido guardado.")
            if job["blocked_reason"]:
                raise ValueError(job["blocked_reason"])
            if int(quantity) != quantity or quantity <= 0 or quantity > job["available"]:
                raise ValueError(f"Cantidad disponible del trabajo #{job_id}: {job['available']:g}.")
        return ProductionBatchService(self.database).preview_jobs(requested)
