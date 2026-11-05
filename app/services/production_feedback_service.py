"""Resumen operativo accionable construido sólo desde demanda y asignaciones."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.production_batch_service import ProductionBatchService


@dataclass
class QuantityBreakdown:
    units: float = 0
    sheets: float = 0

    def add(self, unit_kind: str, quantity: float) -> None:
        if unit_kind == "sheet":
            self.sheets += float(quantity or 0)
        else:
            self.units += float(quantity or 0)

    def to_dict(self) -> dict[str, float]:
        return {"units": self.units, "sheets": self.sheets}


@dataclass
class FeedbackGroup:
    items: list[dict] = field(default_factory=list)
    quantities: QuantityBreakdown = field(default_factory=QuantityBreakdown)

    def to_dict(self) -> dict:
        return {
            "items": self.items,
            "work_count": len(self.items),
            "quantities": self.quantities.to_dict(),
        }


class ProductionFeedbackService:
    """Calcula el próximo trabajo sin usar resúmenes productivos de cabecera."""

    def __init__(self, database):
        self.database = database
        self.connection = database.connection

    @staticmethod
    def _priority_key(item: dict) -> tuple:
        return (-int(item.get("urgency") or 0), item.get("delivery_date") or "9999-12-31", int(item.get("order_id") or 0))

    def summary(self) -> dict:
        available = FeedbackGroup()
        blocked = FeedbackGroup()
        batch = ProductionBatchService(self.database)
        known_job_ids = set()

        for job in batch.job_candidates():
            known_job_ids.add(job.order_job_id)
            base = {
                "order_id": job.order_id,
                "order_job_id": job.order_job_id,
                "order_number": job.order_number,
                "client": job.client,
                "product": job.product,
                "material": job.material,
                "delivery_date": job.delivery_date,
                "urgency": job.urgency,
            }
            if job.blocked_reason:
                blocked.items.append({**base, "reason": job.blocked_reason})
                continue
            quantities = QuantityBreakdown()
            for line in job.lines:
                if line.blocked_reason or line.available <= 0:
                    continue
                quantities.add(line.unit_kind, line.available)
                available.quantities.add(line.unit_kind, line.available)
            if quantities.units or quantities.sheets:
                available.items.append({**base, "quantities": quantities.to_dict()})

        # Un trabajo sin línea de demanda no aparece en el selector de tandas;
        # aquí se expone como bloqueo en lugar de desaparecer del resumen.
        for row in self.connection.execute(
            """SELECT j.id AS order_job_id,j.order_id,j.title,j.material,
                      o.client,o.delivery_date,o.print_priority
                 FROM order_jobs j JOIN orders o ON o.id=j.order_id
                WHERE COALESCE(o.is_archived,0)=0
                  AND NOT EXISTS (
                      SELECT 1 FROM order_design_demand_lines l WHERE l.order_job_id=j.id
                  )"""
        ):
            if int(row["order_job_id"]) in known_job_ids:
                continue
            blocked.items.append({
                "order_id": int(row["order_id"]),
                "order_job_id": int(row["order_job_id"]),
                "order_number": f"#{int(row['order_id'])}",
                "client": str(row["client"] or ""),
                "product": str(row["title"] or "Trabajo"),
                "material": str(row["material"] or ""),
                "delivery_date": str(row["delivery_date"] or ""),
                "urgency": int(row["print_priority"] or 0),
                "reason": "No tiene diseños ni líneas de demanda vinculadas.",
            })

        available.items.sort(key=self._priority_key)
        blocked.items.sort(key=self._priority_key)
        prepared = self._assignment_group("prepared")
        printed = self._assignment_group("printed")
        return {
            "available": available.to_dict(),
            "prepared": prepared.to_dict(),
            "printed": printed.to_dict(),
            "blocked": blocked.to_dict(),
        }

    def _assignment_group(self, state: str) -> FeedbackGroup:
        group = FeedbackGroup()
        rows = self.connection.execute(
            """SELECT pp.id AS plancha_id,pp.name,pp.material,
                      GROUP_CONCAT(DISTINCT pia.order_id) AS order_ids,
                      GROUP_CONCAT(DISTINCT COALESCE(o.client,'')) AS clients,
                      GROUP_CONCAT(DISTINCT COALESCE(j.title,'')) AS products,
                      MAX(COALESCE(o.print_priority,0)) AS urgency,
                      MIN(NULLIF(o.delivery_date,'')) AS delivery_date,
                      COALESCE(SUM(CASE WHEN pia.unit_kind='sheet' THEN pia.quantity ELSE 0 END),0) AS sheets,
                      COALESCE(SUM(CASE WHEN pia.unit_kind<>'sheet' THEN pia.quantity ELSE 0 END),0) AS units
                 FROM plancha_item_assignments pia
                 JOIN plancha_projects pp ON pp.id=pia.plancha_id
                 LEFT JOIN orders o ON o.id=pia.order_id
                 LEFT JOIN order_jobs j ON j.id=pia.order_job_id
                WHERE pia.state=?
                GROUP BY pp.id,pp.name,pp.material
                ORDER BY urgency DESC,COALESCE(delivery_date,'9999-12-31'),pp.id""",
            (state,),
        ).fetchall()
        for row in rows:
            units, sheets = float(row["units"] or 0), float(row["sheets"] or 0)
            group.quantities.units += units
            group.quantities.sheets += sheets
            group.items.append({
                "plancha_id": int(row["plancha_id"]),
                "name": str(row["name"] or f"Plancha #{row['plancha_id']}"),
                "material": str(row["material"] or ""),
                "order_ids": str(row["order_ids"] or ""),
                "clients": str(row["clients"] or ""),
                "products": str(row["products"] or ""),
                "delivery_date": str(row["delivery_date"] or ""),
                "urgency": int(row["urgency"] or 0),
                "quantities": {"units": units, "sheets": sheets},
            })
        return group
