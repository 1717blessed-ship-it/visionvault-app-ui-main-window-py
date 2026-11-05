"""Tandas productivas trazables sobre los motores de plancha existentes."""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.planchas.model import PlanchaProject, packing_mode_for_order_designs, WORKSPACE_FORMATS, requested_unit_key
from app.domain.order_states import normalize_status, TERMINAL_STATES


def _norm(value) -> str:
    text = unicodedata.normalize("NFD", str(value or "").casefold())
    return " ".join("".join(c for c in text if unicodedata.category(c) != "Mn").split())


@dataclass
class BatchCandidate:
    design_line_id: str
    order_id: int
    order_job_id: int
    order_number: str
    client: str
    product: str
    material: str
    requested: int
    available: int
    delivery_date: str
    urgency: int
    image_path: str
    size_cm: float
    rotation: int
    unit_kind: str
    packing_mode: str
    workspace_format: str
    blocked_reason: str = ""


@dataclass
class BatchJobCandidate:
    selection_key: str
    order_id: int
    order_job_id: int
    order_number: str
    client: str
    product: str
    material: str
    available: int
    delivery_date: str
    urgency: int
    blocked_reason: str
    lines: list[BatchCandidate]


@dataclass
class BatchGroupPreview:
    key: str
    material: str
    packing_mode: str
    workspace_format: str
    projects: list[PlanchaProject]
    selections: list[dict]


@dataclass
class BatchPreview:
    groups: list[BatchGroupPreview] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)

    @property
    def plancha_count(self) -> int:
        return sum(len(group.projects) for group in self.groups)


class ProductionBatchService:
    def __init__(self, database):
        self.database = database
        self.connection = database.connection

    def candidates(self) -> list[BatchCandidate]:
        rows = self.connection.execute(
            """SELECT lines.*,jobs.title,jobs.material AS job_material,jobs.size AS job_size,
                      jobs.quantity AS job_quantity,jobs.production_mode,
                      COALESCE(NULLIF(lines.unit_kind,''),NULLIF(jobs.unit_kind,''),'') AS effective_unit_kind,
                      orders.client,orders.delivery_date,orders.print_priority,orders.status AS order_status,
                      jobs.status AS job_status,jobs.unit_kind AS job_unit_kind,
                      images.name,images.visible_width,images.visible_height
               FROM order_design_demand_lines lines
               JOIN order_jobs jobs ON jobs.id=lines.order_job_id
               JOIN orders ON orders.id=lines.order_id
               LEFT JOIN images ON images.path=lines.image_path
               WHERE COALESCE(orders.is_archived,0)=0
               ORDER BY orders.print_priority DESC,orders.delivery_date,lines.order_id,lines.id"""
        ).fetchall()
        path_counts = {}
        distributed_by_job = {}
        for row in rows:
            key = (int(row["order_job_id"]), _norm(row["image_path"]))
            path_counts[key] = path_counts.get(key, 0) + 1
            distributed_by_job[int(row["order_job_id"])] = distributed_by_job.get(int(row["order_job_id"]), 0) + int(row["quantity"] or 0)
        result = []
        for row in rows:
            line_id = str(row["design_line_id"])
            active = int(self.connection.execute(
                """SELECT COALESCE(SUM(quantity),0) FROM plancha_item_assignments
                   WHERE order_design_line_id=? AND state<>'released'""", (line_id,),
            ).fetchone()[0] or 0)
            legacy = self.connection.execute(
                """SELECT COALESCE(SUM(quantity),0) AS total,COUNT(*) AS rows_count
                   FROM plancha_item_assignments
                   WHERE order_job_id=? AND COALESCE(order_design_line_id,'')=''
                     AND LOWER(REPLACE(image_path,'\\','/'))=LOWER(REPLACE(?,'\\','/'))
                     AND state<>'released'""",
                (int(row["order_job_id"]), row["image_path"]),
            ).fetchone()
            blocked = ""
            if int(legacy["rows_count"] or 0):
                if path_counts[(int(row["order_job_id"]), _norm(row["image_path"]))] == 1:
                    active += int(legacy["total"] or 0)
                else:
                    blocked = "Historial v1 ambiguo para varias líneas con el mismo archivo."
            unit_kind = str(row["effective_unit_kind"] or "").strip()
            descriptive = _norm(f"{row['title']} {row['job_material']} {row['job_size']}")
            if not unit_kind:
                if "plancha" not in descriptive and not re.search(r"\ba4\b|\ba5\b", descriptive):
                    if any(token in descriptive for token in ("sticker", "vinilo", "calco")):
                        unit_kind = "item"
            if not unit_kind:
                blocked = blocked or "Falta configurar la correspondencia de unidad productiva."
            if not row["name"]:
                blocked = blocked or "El diseño no está disponible en la biblioteca."
            if not str(row["job_material"] or "").strip():
                blocked = blocked or "Falta indicar el material del trabajo."
            if str(row["workspace_format"] or "a4") not in WORKSPACE_FORMATS:
                blocked = blocked or "El formato de producción no está configurado correctamente."
            if normalize_status(row["order_status"]) in TERMINAL_STATES or normalize_status(row["job_status"]) in TERMINAL_STATES:
                blocked = blocked or "El pedido o trabajo está cerrado; requiere revisión antes de producir."
            if row["job_unit_kind"] and unit_kind != row["job_unit_kind"]:
                blocked = blocked or "La unidad de la demanda no coincide con la del trabajo."
            distributed = distributed_by_job[int(row["order_job_id"])]
            committed = float(self.connection.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM plancha_item_assignments WHERE order_job_id=? AND state<>'released'",
                (row["order_job_id"],),
            ).fetchone()[0])
            if distributed > int(row["job_quantity"] or 0) or committed > int(row["job_quantity"] or 0):
                blocked = blocked or "Las cantidades históricas superan lo solicitado."
            mode = str(row["packing_mode"] or "") or packing_mode_for_order_designs([{"size_cm": row["size_cm"]}])
            if mode not in {"standard_five_bands", "sticker_mixed", "special_geometric"}:
                blocked = blocked or f"El modo {mode or 'sin configurar'} todavía no admite tandas."
            available = max(0, int(row["quantity"] or 0) - active)
            result.append(BatchCandidate(
                line_id, int(row["order_id"]), int(row["order_job_id"]), f"#{int(row['order_id'])}",
                str(row["client"] or ""), str(row["title"] or "Trabajo"), str(row["job_material"] or ""),
                int(row["quantity"] or 0), available, str(row["delivery_date"] or ""),
                int(row["print_priority"] or 0), str(row["image_path"]), float(row["size_cm"] or 5),
                int(row["rotation"] or 0), unit_kind, mode, str(row["workspace_format"] or "a4"), blocked,
            ))
        return result

    def job_candidates(self) -> list[BatchJobCandidate]:
        grouped: dict[int, list[BatchCandidate]] = {}
        for line in self.candidates():
            grouped.setdefault(line.order_job_id, []).append(line)
        jobs = []
        for job_id, lines in grouped.items():
            first = lines[0]
            reasons = sorted({line.blocked_reason for line in lines if line.blocked_reason})
            jobs.append(BatchJobCandidate(
                f"job:{job_id}", first.order_id, job_id, first.order_number, first.client,
                first.product, first.material, sum(line.available for line in lines if not line.blocked_reason),
                first.delivery_date, first.urgency, " · ".join(reasons), lines,
            ))
        return jobs

    def preview_jobs(self, requested: dict[int, int]) -> BatchPreview:
        by_job = {item.order_job_id: item for item in self.job_candidates()}
        line_request: dict[str, int] = {}
        excluded = []
        for raw_job_id, raw_quantity in requested.items():
            job_id, quantity = int(raw_job_id), max(0, int(raw_quantity or 0))
            job = by_job.get(job_id)
            if not job:
                excluded.append({"order_job_id": job_id, "reason": "El trabajo ya no existe."})
                continue
            if job.blocked_reason:
                excluded.append({"order_job_id": job_id, "reason": job.blocked_reason})
                continue
            if quantity < 1 or quantity > job.available:
                excluded.append({"order_job_id": job_id, "reason": f"Cantidad disponible: {job.available}."})
                continue
            remaining = quantity
            for line in job.lines:
                take = min(remaining, line.available)
                if take:
                    line_request[line.design_line_id] = take
                    remaining -= take
                if not remaining:
                    break
        preview = self.preview(line_request)
        preview.excluded.extend(excluded)
        return preview

    def configure_job_unit(self, order_job_id: int, unit_kind: str) -> None:
        unit_kind = str(unit_kind or "").strip().casefold()
        if unit_kind not in {"item", "sheet"}:
            raise ValueError("La unidad debe ser 'item' o 'sheet'.")
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE order_design_demand_lines SET unit_kind=? WHERE order_job_id=?",
                (unit_kind, int(order_job_id)),
            )
            if not cursor.rowcount:
                raise ValueError("El trabajo no tiene líneas de demanda configurables.")

    def preview(self, requested: dict[str, int]) -> BatchPreview:
        candidates = {item.design_line_id: item for item in self.candidates()}
        grouped: dict[str, list[tuple[BatchCandidate, int]]] = {}
        preview = BatchPreview()
        for line_id, raw_quantity in requested.items():
            candidate = candidates.get(str(line_id))
            quantity = max(0, int(raw_quantity or 0))
            if not candidate:
                preview.excluded.append({"design_line_id": line_id, "reason": "La línea ya no existe."})
                continue
            if candidate.blocked_reason:
                preview.excluded.append({"design_line_id": line_id, "reason": candidate.blocked_reason})
                continue
            if quantity < 1 or quantity > candidate.available:
                preview.excluded.append({"design_line_id": line_id, "reason": f"Cantidad disponible: {candidate.available}."})
                continue
            key = "|".join((_norm(candidate.material), candidate.workspace_format, candidate.packing_mode, candidate.unit_kind))
            grouped.setdefault(key, []).append((candidate, quantity))
        for key, entries in grouped.items():
            images = []
            selections = []
            for candidate, quantity in entries:
                copy_numbers = self.database.available_requested_copy_numbers(
                    order_id=candidate.order_id, order_job_id=candidate.order_job_id,
                    image_path=candidate.image_path, nominal_size_cm=candidate.size_cm,
                    rotation=candidate.rotation, requested_quantity=candidate.requested,
                    design_line_id=candidate.design_line_id,
                )[:quantity]
                found = self.database.images_by_paths([candidate.image_path])
                image = dict(found[0]) if found else {}
                images.append({
                    **image, "path": candidate.image_path, "name": image.get("name") or candidate.image_path,
                    "visible_width": image.get("visible_width") or 100,
                    "visible_height": image.get("visible_height") or 100,
                    "order_id": candidate.order_id, "order_job_id": candidate.order_job_id,
                    "order_number": candidate.order_number, "client": candidate.client,
                    "order_job_title": candidate.product,
                    "order_design_line_id": candidate.design_line_id,
                    "order_quantity": len(copy_numbers), "order_copy_numbers": copy_numbers,
                    "order_size_cm": candidate.size_cm, "rotation": candidate.rotation,
                    "production_unit_kind": candidate.unit_kind,
                    "order_packing_mode": candidate.packing_mode,
                })
                selections.append({"design_line_id": candidate.design_line_id, "quantity": len(copy_numbers),
                                   "order_id": candidate.order_id, "order_job_id": candidate.order_job_id})
            items = PlanchaProject.from_images(images).items
            if entries[0][0].unit_kind == "sheet":
                # Correspondencia explícita 1 unidad comercial = 1 hoja física.
                # Nunca se deduce una hoja por cada imagen de un armado interno.
                projects = [PlanchaProject([item], workspace_format=entries[0][0].workspace_format) for item in items]
            else:
                projects = PlanchaProject.calculate_pagination(
                    items, layout_mode="special" if entries[0][0].packing_mode != "standard_five_bands" else "classic",
                    workspace_format=entries[0][0].workspace_format,
                )
            preview.groups.append(BatchGroupPreview(
                key, entries[0][0].material, entries[0][0].packing_mode,
                entries[0][0].workspace_format, projects, selections,
            ))
        return preview

    def save(self, preview: BatchPreview, name: str = "Tanda de producción") -> int:
        if not preview.groups or preview.plancha_count < 1:
            raise ValueError("La tanda no contiene planchas para guardar.")
        now = datetime.now().isoformat(timespec="seconds")
        batch_key = uuid.uuid4().hex
        with self.connection:
            # Bloqueo de escritura antes de revalidar: otra instancia no puede
            # reservar entre la comprobación y la inserción de las planchas.
            self.connection.execute("BEGIN IMMEDIATE")
            # La demanda puede cambiar mientras el operador revisa la vista previa.
            current = {c.design_line_id: c for c in self.candidates()}
            selected_counts: dict[str, int] = {}
            available_copies = {}
            for group in preview.groups:
                for project in group.projects:
                    for item in project.items:
                        candidate = current.get(str(item.order_design_line_id or ""))
                        if not candidate or candidate.blocked_reason:
                            raise ValueError("La demanda cambió o está bloqueada. Actualizá la vista previa.")
                        if (item.order_id != candidate.order_id or item.order_job_id != candidate.order_job_id
                                or item.path != candidate.image_path or item.production_unit_kind != candidate.unit_kind
                                or group.material != candidate.material or group.workspace_format != candidate.workspace_format
                                or project.workspace_format != candidate.workspace_format
                                or group.packing_mode != candidate.packing_mode
                                or item.requested_unit_key != requested_unit_key(
                                    candidate.order_id, candidate.order_job_id, candidate.image_path,
                                    candidate.size_cm, candidate.rotation, item.copy_number,
                                    design_line_id=candidate.design_line_id)):
                            raise ValueError("La configuración de producción cambió. Actualizá la vista previa.")
                        if candidate.design_line_id not in available_copies:
                            available_copies[candidate.design_line_id] = set(self.database.available_requested_copy_numbers(
                                order_id=candidate.order_id, order_job_id=candidate.order_job_id,
                                image_path=candidate.image_path, nominal_size_cm=candidate.size_cm,
                                rotation=candidate.rotation, requested_quantity=candidate.requested,
                                design_line_id=candidate.design_line_id,
                            ))
                        valid_copies = available_copies[candidate.design_line_id]
                        if item.copy_number not in valid_copies:
                            raise ValueError("Una unidad ya está reservada o dejó de estar solicitada. Actualizá la vista previa.")
                        selected_counts[candidate.design_line_id] = selected_counts.get(candidate.design_line_id, 0) + 1
                        if selected_counts[candidate.design_line_id] > candidate.available:
                            raise ValueError("La cantidad solicitada cambió. Actualizá la vista previa.")
            # La vista previa no reserva: todas las claves se revalidan juntas.
            keys = [item.requested_unit_key for group in preview.groups for project in group.projects for item in project.items]
            if len(keys) != len(set(keys)):
                raise ValueError("La tanda contiene una unidad solicitada repetida.")
            if keys:
                placeholders = ",".join("?" for _ in keys)
                conflict = self.connection.execute(
                    f"SELECT requested_unit_key,plancha_id FROM plancha_item_assignments WHERE state<>'released' AND requested_unit_key IN ({placeholders}) LIMIT 1",
                    keys,
                ).fetchone()
                if conflict:
                    raise ValueError(f"Una unidad fue reservada por la plancha #{int(conflict['plancha_id'])}. Actualizá la vista previa.")
            batch_cursor = self.connection.execute(
                "INSERT INTO production_batches(batch_key,name,status,created_at,updated_at) VALUES(?,?,'prepared',?,?)",
                (batch_key, name.strip() or "Tanda de producción", now, now),
            )
            batch_id = int(batch_cursor.lastrowid)
            total = sum(len(group.projects) for group in preview.groups)
            number = 0
            for group in preview.groups:
                for project in group.projects:
                    number += 1
                    payload = json.dumps(project.to_dict(), ensure_ascii=False)
                    cursor = self.connection.execute(
                        """INSERT INTO plancha_projects(order_id,name,material,project_json,project_path,
                               workspace_format,plancha_set_id,plancha_number,total_planchas,created_at,updated_at)
                           VALUES(NULL,?,?,?,?,?,?,?,?,?,?)""",
                        (f"{name} · {number}/{total}", group.material, payload, "", group.workspace_format,
                         batch_key, number, total, now, now),
                    )
                    plancha_id = int(cursor.lastrowid)
                    self.database._sync_plancha_assignments(plancha_id, [item.to_dict() for item in project.items], now)
                    self.connection.execute(
                        "INSERT INTO production_batch_planchas(batch_id,plancha_id,group_key,plancha_number) VALUES(?,?,?,?)",
                        (batch_id, plancha_id, group.key, number),
                    )
            for order_id in {item.order_id for group in preview.groups for project in group.projects for item in project.items}:
                self.connection.execute(
                    "INSERT INTO order_events(order_id,event_type,message,data_json,created_at) VALUES(?,?,?,?,?)",
                    (order_id, "production.batch.prepared", f"Tanda #{batch_id} preparada desde demanda guardada.",
                     json.dumps({"batch_id": batch_id}), now),
                )
            return batch_id

    def batches(self) -> list[dict]:
        return [dict(row) for row in self.connection.execute(
            """SELECT batches.*,COUNT(links.plancha_id) AS plancha_count
               FROM production_batches batches LEFT JOIN production_batch_planchas links ON links.batch_id=batches.id
               GROUP BY batches.id ORDER BY batches.id DESC"""
        )]

    def cancel(self, batch_id: int) -> dict[str, int]:
        """Cancela reservas pendientes y devuelve un resumen verificable.

        Las unidades impresas/terminadas y sus planchas se conservan. El
        resultado permite que la interfaz explique una cancelación parcial sin
        confundir liberación de reservas con pérdida de producción.
        """
        now = datetime.now().isoformat(timespec="seconds")
        summary = {
            "released_units": 0, "preserved_units": 0,
            "removed_planchas": 0, "preserved_planchas": 0,
        }
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            batch = self.connection.execute("SELECT status FROM production_batches WHERE id=?", (int(batch_id),)).fetchone()
            if not batch:
                raise ValueError("La tanda no existe.")
            if batch["status"] == "cancelled":
                return summary
            order_ids = {int(row[0]) for row in self.connection.execute(
                """SELECT DISTINCT a.order_id FROM plancha_item_assignments a
                   JOIN production_batch_planchas p ON p.plancha_id=a.plancha_id WHERE p.batch_id=?""", (batch_id,))}
            planchas = [int(row[0]) for row in self.connection.execute(
                "SELECT plancha_id FROM production_batch_planchas WHERE batch_id=?", (int(batch_id),)
            )]
            for plancha_id in planchas:
                counts = self.connection.execute(
                    """SELECT
                         COALESCE(SUM(CASE WHEN state='prepared' THEN quantity ELSE 0 END),0) AS releasable,
                         COALESCE(SUM(CASE WHEN state IN ('printed','finished') THEN quantity ELSE 0 END),0) AS produced
                       FROM plancha_item_assignments WHERE plancha_id=?""",
                    (plancha_id,),
                ).fetchone()
                releasable = int(counts["releasable"] or 0)
                produced = int(counts["produced"] or 0)
                summary["released_units"] += releasable
                summary["preserved_units"] += produced
                self.connection.execute(
                    """UPDATE plancha_item_assignments SET state='released',released_at=?,updated_at=?
                       WHERE plancha_id=? AND state='prepared'""", (now, now, plancha_id),
                )
                if produced:
                    summary["preserved_planchas"] += 1
                else:
                    summary["removed_planchas"] += 1
                    # Retiro lógico: conservar liberaciones y vínculos para la auditoría del pedido.
                    self.connection.execute(
                        "UPDATE plancha_projects SET production_status='Cancelada',updated_at=? WHERE id=?", (now, plancha_id),
                    )
            self.connection.execute(
                "UPDATE production_batches SET status='cancelled',cancelled_at=?,updated_at=? WHERE id=?",
                (now, now, int(batch_id)),
            )
            for order_id in order_ids:
                self.connection.execute(
                    "INSERT INTO order_events(order_id,event_type,message,data_json,created_at) VALUES(?,?,?,?,?)",
                    (order_id, "production.batch.cancelled", f"Tanda #{batch_id} cancelada; producción impresa conservada.",
                     json.dumps({"batch_id": batch_id, **summary}), now),
                )
        return summary
