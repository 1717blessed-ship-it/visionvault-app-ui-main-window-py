"""Persistencia y reglas del Centro de ventas.

El módulo vive sobre la misma conexión SQLite que pedidos y productos. Sus
migraciones son aditivas e idempotentes: una instalación existente no pierde
ni reescribe datos comerciales anteriores.
"""

from __future__ import annotations

import base64
import html
import json
import mimetypes
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable


LEAD_STAGES = ("Nueva", "Contactada", "Calificada", "Presupuestada", "Ganada", "Perdida")
QUOTE_STATUSES = ("Borrador", "Enviado", "Aceptado", "Rechazado", "Vencido")
DELIVERY_STATUSES = ("Sin coordinar", "Coordinada", "En camino", "Lista para retirar", "Entregada")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class SellerRepository:
    """API transaccional de CRM, presupuestos y posventa."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.create_tables()

    def create_tables(self) -> None:
        ddl = (
            """CREATE TABLE IF NOT EXISTS sales_leads (
                id INTEGER PRIMARY KEY, client_id INTEGER, client_name TEXT NOT NULL,
                whatsapp TEXT DEFAULT '', source TEXT DEFAULT '', stage TEXT NOT NULL DEFAULT 'Nueva',
                probability INTEGER NOT NULL DEFAULT 20, expected_value REAL NOT NULL DEFAULT 0,
                assigned_to TEXT DEFAULT '', next_action TEXT DEFAULT '', next_action_at TEXT DEFAULT '',
                notes TEXT DEFAULT '', loss_reason TEXT DEFAULT '', quote_id INTEGER, order_id INTEGER,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, closed_at TEXT DEFAULT '')""",
            """CREATE TABLE IF NOT EXISTS sales_quotes (
                id INTEGER PRIMARY KEY, quote_number TEXT NOT NULL UNIQUE, lead_id INTEGER, client_id INTEGER,
                client_name TEXT NOT NULL, whatsapp TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'Borrador',
                valid_until TEXT DEFAULT '', subtotal REAL NOT NULL DEFAULT 0,
                discount_percent REAL NOT NULL DEFAULT 0, discount_reason TEXT DEFAULT '',
                total REAL NOT NULL DEFAULT 0, notes TEXT DEFAULT '', delivery_terms TEXT DEFAULT '',
                payment_terms TEXT DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
                approval_status TEXT NOT NULL DEFAULT 'No requerida', approved_by TEXT DEFAULT '',
                converted_order_id INTEGER, sent_at TEXT DEFAULT '', accepted_at TEXT DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS sales_quote_items (
                id INTEGER PRIMARY KEY, quote_id INTEGER NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0,
                product_id INTEGER, product_name TEXT NOT NULL, material TEXT DEFAULT '', size TEXT DEFAULT '',
                quantity INTEGER NOT NULL DEFAULT 1, unit_price REAL NOT NULL DEFAULT 0,
                subtotal REAL NOT NULL DEFAULT 0, notes TEXT DEFAULT '',
                FOREIGN KEY(quote_id) REFERENCES sales_quotes(id))""",
            """CREATE TABLE IF NOT EXISTS sales_quote_versions (
                id INTEGER PRIMARY KEY, quote_id INTEGER NOT NULL, version INTEGER NOT NULL,
                snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(quote_id, version))""",
            """CREATE TABLE IF NOT EXISTS sales_tasks (
                id INTEGER PRIMARY KEY, lead_id INTEGER, quote_id INTEGER, order_id INTEGER, client_id INTEGER,
                kind TEXT NOT NULL DEFAULT 'Seguimiento', title TEXT NOT NULL, due_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pendiente', message_template TEXT DEFAULT '',
                completed_at TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS sales_deliveries (
                id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL UNIQUE, method TEXT DEFAULT 'Retiro',
                address TEXT DEFAULT '', city TEXT DEFAULT '', shipping_cost REAL NOT NULL DEFAULT 0,
                scheduled_at TEXT DEFAULT '', time_window TEXT DEFAULT '', tracking_code TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Sin coordinar', received_at TEXT DEFAULT '',
                notes TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS client_commercial_profiles (
                client_id INTEGER PRIMARY KEY, email TEXT DEFAULT '', birthday TEXT DEFAULT '',
                preferred_channel TEXT DEFAULT 'WhatsApp', tags TEXT DEFAULT '', notes TEXT DEFAULT '',
                last_contact_at TEXT DEFAULT '', updated_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS sales_settings (
                key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS sales_promotions (
                id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE COLLATE NOCASE, name TEXT NOT NULL,
                description TEXT DEFAULT '', discount_percent REAL NOT NULL DEFAULT 0,
                starts_at TEXT DEFAULT '', ends_at TEXT DEFAULT '', audience TEXT DEFAULT 'Todos',
                active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
        )
        indexes = (
            "CREATE INDEX IF NOT EXISTS idx_sales_leads_stage ON sales_leads(stage, next_action_at)",
            "CREATE INDEX IF NOT EXISTS idx_sales_quotes_status ON sales_quotes(status, valid_until)",
            "CREATE INDEX IF NOT EXISTS idx_sales_tasks_due ON sales_tasks(status, due_at)",
            "CREATE INDEX IF NOT EXISTS idx_sales_deliveries_status ON sales_deliveries(status, scheduled_at)",
        )
        with self.connection:
            for statement in ddl + indexes:
                self.connection.execute(statement)
            quote_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(sales_quotes)")}
            for column, definition in (
                ("promotion_code", "TEXT DEFAULT ''"),
                ("promotion_discount_percent", "REAL NOT NULL DEFAULT 0"),
            ):
                if column not in quote_columns:
                    self.connection.execute(f"ALTER TABLE sales_quotes ADD COLUMN {column} {definition}")
            defaults = {
                "max_discount_without_approval": "10",
                "wholesale_min_quantity": "20",
                "quote_valid_days": "7",
                "followup_days": "2",
                "dormant_customer_days": "60",
                "business_whatsapp": "",
            }
            now = _now()
            for key, value in defaults.items():
                self.connection.execute(
                    "INSERT OR IGNORE INTO sales_settings(key, value, updated_at) VALUES(?, ?, ?)",
                    (key, value, now),
                )

    # ------------------------------------------------------------------ CRM
    def create_lead(
        self, *, client_name: str, whatsapp: str = "", source: str = "",
        stage: str = "Nueva", probability: int = 20, expected_value: float = 0,
        assigned_to: str = "", next_action: str = "", next_action_at: str = "",
        notes: str = "", client_id: int | None = None,
    ) -> int:
        name = str(client_name or "").strip()
        if not name:
            raise ValueError("Ingresá el nombre del contacto.")
        stage = stage if stage in LEAD_STAGES else "Nueva"
        now = _now()
        with self.connection:
            cursor = self.connection.execute(
                """INSERT INTO sales_leads(client_id, client_name, whatsapp, source, stage,
                   probability, expected_value, assigned_to, next_action, next_action_at, notes,
                   created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (client_id, name, str(whatsapp).strip(), str(source).strip(), stage,
                 min(100, max(0, int(probability))), max(0.0, float(expected_value or 0)),
                 str(assigned_to).strip(), str(next_action).strip(), str(next_action_at).strip(),
                 str(notes).strip(), now, now),
            )
            lead_id = int(cursor.lastrowid)
            if next_action and next_action_at:
                self._replace_followup_task(lead_id, name, next_action, next_action_at)
        return lead_id

    def update_lead(self, lead_id: int, **values: Any) -> None:
        current = self.lead(lead_id)
        if not current:
            raise ValueError("La oportunidad ya no existe.")
        allowed = {
            "client_id", "client_name", "whatsapp", "source", "stage", "probability",
            "expected_value", "assigned_to", "next_action", "next_action_at", "notes", "loss_reason",
        }
        merged = {**current, **{key: value for key, value in values.items() if key in allowed}}
        if not str(merged["client_name"] or "").strip():
            raise ValueError("Ingresá el nombre del contacto.")
        if merged["stage"] not in LEAD_STAGES:
            raise ValueError("El estado comercial no es válido.")
        merged["probability"] = min(100, max(0, int(merged.get("probability") or 0)))
        merged["expected_value"] = max(0.0, float(merged.get("expected_value") or 0))
        closed_at = _now() if merged["stage"] in {"Ganada", "Perdida"} else ""
        with self.connection:
            self.connection.execute(
                """UPDATE sales_leads SET client_id=?, client_name=?, whatsapp=?, source=?, stage=?,
                   probability=?, expected_value=?, assigned_to=?, next_action=?, next_action_at=?,
                   notes=?, loss_reason=?, closed_at=?, updated_at=? WHERE id=?""",
                (merged.get("client_id"), str(merged["client_name"]).strip(), str(merged.get("whatsapp") or "").strip(),
                 str(merged.get("source") or "").strip(), merged["stage"], merged["probability"],
                 merged["expected_value"], str(merged.get("assigned_to") or "").strip(),
                 str(merged.get("next_action") or "").strip(), str(merged.get("next_action_at") or "").strip(),
                 str(merged.get("notes") or "").strip(), str(merged.get("loss_reason") or "").strip(),
                 closed_at, _now(), int(lead_id)),
            )
            self._replace_followup_task(
                int(lead_id), str(merged["client_name"]), str(merged.get("next_action") or ""),
                str(merged.get("next_action_at") or ""),
            )

    def _replace_followup_task(self, lead_id: int, client_name: str, action: str, due_at: str) -> None:
        now = _now()
        self.connection.execute(
            "UPDATE sales_tasks SET status='Cancelada', updated_at=? WHERE lead_id=? AND kind='Seguimiento' AND status='Pendiente'",
            (now, lead_id),
        )
        if action.strip() and due_at.strip():
            self.connection.execute(
                """INSERT INTO sales_tasks(lead_id, kind, title, due_at, message_template,
                   created_at, updated_at) VALUES(?, 'Seguimiento', ?, ?, ?, ?, ?)""",
                (lead_id, action.strip(), due_at.strip(),
                 f"Hola {client_name}, te escribo para continuar con tu consulta. ¿Pudiste revisar la información?",
                 now, now),
            )

    def lead(self, lead_id: int) -> dict[str, Any] | None:
        return _row(self.connection.execute("SELECT * FROM sales_leads WHERE id=?", (int(lead_id),)).fetchone())

    def leads(self, *, stage: str = "", query: str = "") -> list[dict[str, Any]]:
        clauses, params = [], []
        if stage and stage != "Todas":
            clauses.append("l.stage=?"); params.append(stage)
        if query.strip():
            term = f"%{query.strip().lower()}%"
            clauses.append("(LOWER(l.client_name) LIKE ? OR LOWER(l.whatsapp) LIKE ? OR LOWER(l.source) LIKE ?)")
            params.extend((term, term, term))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.connection.execute(
            """SELECT l.*, q.quote_number FROM sales_leads l
               LEFT JOIN sales_quotes q ON q.id=l.quote_id""" + where +
            " ORDER BY CASE l.stage WHEN 'Nueva' THEN 0 WHEN 'Contactada' THEN 1 WHEN 'Calificada' THEN 2 WHEN 'Presupuestada' THEN 3 ELSE 4 END, COALESCE(NULLIF(l.next_action_at,''), l.updated_at), l.id DESC",
            params,
        ).fetchall()
        return [dict(item) for item in rows]

    # ----------------------------------------------------------- Presupuestos
    def next_quote_number(self) -> str:
        prefix = datetime.now().strftime("P-%Y%m-")
        row = self.connection.execute(
            "SELECT quote_number FROM sales_quotes WHERE quote_number LIKE ? ORDER BY id DESC LIMIT 1",
            (prefix + "%",),
        ).fetchone()
        sequence = int(str(row[0]).rsplit("-", 1)[-1]) + 1 if row else 1
        return f"{prefix}{sequence:04d}"

    def create_quote(
        self, *, client_name: str, whatsapp: str = "", items: Iterable[dict[str, Any]],
        client_id: int | None = None, lead_id: int | None = None, valid_until: str = "",
        discount_percent: float = 0, discount_reason: str = "", notes: str = "",
        delivery_terms: str = "", payment_terms: str = "", promotion_code: str = "",
    ) -> int:
        name = str(client_name or "").strip()
        if not name:
            raise ValueError("Ingresá el cliente del presupuesto.")
        cleaned = self._clean_quote_items(items)
        if not cleaned:
            raise ValueError("Agregá al menos un producto.")
        discount = min(100.0, max(0.0, float(discount_percent or 0)))
        if discount and not str(discount_reason or "").strip():
            raise ValueError("Indicá el motivo del descuento.")
        subtotal = round(sum(item["subtotal"] for item in cleaned), 2)
        promotion = self.resolve_promotion(promotion_code) if str(promotion_code).strip() else None
        promotion_discount = float(promotion.get("discount_percent") or 0) if promotion else 0.0
        total = round(subtotal * (1 - discount / 100) * (1 - promotion_discount / 100), 2)
        limit = float(self.setting("max_discount_without_approval", "10"))
        approval = "Pendiente" if discount > limit else "No requerida"
        if not valid_until:
            valid_until = (date.today() + timedelta(days=int(float(self.setting("quote_valid_days", "7"))))).isoformat()
        now = _now()
        with self.connection:
            cursor = self.connection.execute(
                """INSERT INTO sales_quotes(quote_number, lead_id, client_id, client_name, whatsapp,
                   valid_until, subtotal, discount_percent, discount_reason, total, notes,
                   delivery_terms, payment_terms, approval_status, promotion_code,
                   promotion_discount_percent, created_at, updated_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (self.next_quote_number(), lead_id, client_id, name, str(whatsapp).strip(), valid_until,
                 subtotal, discount, str(discount_reason).strip(), total, str(notes).strip(),
                 str(delivery_terms).strip(), str(payment_terms).strip(), approval,
                 str(promotion.get("code") if promotion else ""), promotion_discount, now, now),
            )
            quote_id = int(cursor.lastrowid)
            self._write_quote_items(quote_id, cleaned)
            self._snapshot_quote(quote_id)
            if lead_id:
                self.connection.execute(
                    "UPDATE sales_leads SET quote_id=?, stage='Presupuestada', probability=60, expected_value=?, updated_at=? WHERE id=?",
                    (quote_id, total, now, int(lead_id)),
                )
            days = int(float(self.setting("followup_days", "2")))
            due = (datetime.now() + timedelta(days=days)).isoformat(timespec="minutes")
            self.connection.execute(
                """INSERT INTO sales_tasks(lead_id, quote_id, client_id, kind, title, due_at,
                   message_template, created_at, updated_at) VALUES(?, ?, ?, 'Presupuesto', ?, ?, ?, ?, ?)""",
                (lead_id, quote_id, client_id, f"Seguimiento de {self.quote_label(quote_id)}",
                 due, f"Hola {name}, ¿pudiste revisar el presupuesto que te envié? Quedo atento/a a tus dudas.", now, now),
            )
        return quote_id

    def revise_quote(
        self, quote_id: int, *, client_name: str, whatsapp: str = "",
        items: Iterable[dict[str, Any]], valid_until: str = "", discount_percent: float = 0,
        discount_reason: str = "", notes: str = "", delivery_terms: str = "",
        payment_terms: str = "", promotion_code: str = "",
    ) -> int:
        """Guarda una nueva versión conservando número, historial y vínculos."""
        current = self.quote(quote_id)
        if not current:
            raise ValueError("El presupuesto ya no existe.")
        name = str(client_name or "").strip()
        cleaned = self._clean_quote_items(items)
        if not name or not cleaned:
            raise ValueError("Ingresá el cliente y al menos un producto.")
        discount = min(100.0, max(0.0, float(discount_percent or 0)))
        if discount and not str(discount_reason or "").strip():
            raise ValueError("Indicá el motivo del descuento.")
        promotion = self.resolve_promotion(promotion_code) if str(promotion_code).strip() else None
        promotion_discount = float(promotion.get("discount_percent") or 0) if promotion else 0.0
        subtotal = round(sum(item["subtotal"] for item in cleaned), 2)
        total = round(subtotal * (1 - discount / 100) * (1 - promotion_discount / 100), 2)
        limit = float(self.setting("max_discount_without_approval", "10"))
        approval = "Pendiente" if discount > limit else "No requerida"
        version = int(current.get("version") or 1) + 1
        with self.connection:
            self.connection.execute(
                """UPDATE sales_quotes SET client_name=?,whatsapp=?,status='Borrador',valid_until=?,
                   subtotal=?,discount_percent=?,discount_reason=?,total=?,notes=?,delivery_terms=?,
                   payment_terms=?,version=?,approval_status=?,approved_by='',promotion_code=?,
                   promotion_discount_percent=?,sent_at='',accepted_at='',updated_at=? WHERE id=?""",
                (name, str(whatsapp).strip(), str(valid_until).strip(), subtotal, discount,
                 str(discount_reason).strip(), total, str(notes).strip(), str(delivery_terms).strip(),
                 str(payment_terms).strip(), version, approval, str(promotion.get("code") if promotion else ""),
                 promotion_discount, _now(), int(quote_id)),
            )
            self._write_quote_items(int(quote_id), cleaned)
            self._snapshot_quote(int(quote_id))
        return int(quote_id)

    @staticmethod
    def _clean_quote_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        cleaned = []
        for position, raw in enumerate(items):
            name = str(raw.get("product_name") or raw.get("title") or "").strip()
            if not name:
                continue
            quantity = max(1, int(raw.get("quantity") or 1))
            unit = max(0.0, float(raw.get("unit_price") or 0))
            subtotal = max(0.0, float(raw.get("subtotal") if raw.get("subtotal") is not None else unit * quantity))
            cleaned.append({
                "sort_order": position, "product_id": raw.get("product_id"), "product_name": name,
                "material": str(raw.get("material") or "").strip(), "size": str(raw.get("size") or "").strip(),
                "quantity": quantity, "unit_price": round(unit, 2), "subtotal": round(subtotal, 2),
                "notes": str(raw.get("notes") or "").strip(),
            })
        return cleaned

    def _write_quote_items(self, quote_id: int, items: list[dict[str, Any]]) -> None:
        self.connection.execute("DELETE FROM sales_quote_items WHERE quote_id=?", (quote_id,))
        self.connection.executemany(
            """INSERT INTO sales_quote_items(quote_id, sort_order, product_id, product_name,
               material, size, quantity, unit_price, subtotal, notes) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(quote_id, item["sort_order"], item["product_id"], item["product_name"], item["material"],
              item["size"], item["quantity"], item["unit_price"], item["subtotal"], item["notes"])
             for item in items],
        )

    def _snapshot_quote(self, quote_id: int) -> None:
        quote = self.quote(quote_id)
        if not quote:
            return
        payload = {**quote, "items": self.quote_items(quote_id)}
        self.connection.execute(
            "INSERT OR REPLACE INTO sales_quote_versions(quote_id, version, snapshot_json, created_at) VALUES(?, ?, ?, ?)",
            (quote_id, int(quote["version"]), json.dumps(payload, ensure_ascii=False), _now()),
        )

    def quote(self, quote_id: int) -> dict[str, Any] | None:
        return _row(self.connection.execute("SELECT * FROM sales_quotes WHERE id=?", (int(quote_id),)).fetchone())

    def quote_items(self, quote_id: int) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM sales_quote_items WHERE quote_id=? ORDER BY sort_order, id", (int(quote_id),)
        )]

    def quotes(self, *, status: str = "", query: str = "") -> list[dict[str, Any]]:
        with self.connection:
            self.connection.execute(
                """UPDATE sales_quotes SET status='Vencido',updated_at=?
                   WHERE status IN ('Borrador','Enviado') AND valid_until<>'' AND valid_until<?""",
                (_now(), date.today().isoformat()),
            )
        clauses, params = [], []
        if status and status != "Todos": clauses.append("q.status=?"); params.append(status)
        if query.strip():
            term = f"%{query.strip().lower()}%"
            clauses.append("(LOWER(q.client_name) LIKE ? OR LOWER(q.quote_number) LIKE ?)")
            params.extend((term, term))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.connection.execute(
            "SELECT q.*, COUNT(i.id) AS item_count FROM sales_quotes q LEFT JOIN sales_quote_items i ON i.quote_id=q.id" +
            where + " GROUP BY q.id ORDER BY q.id DESC", params,
        ).fetchall()
        return [dict(item) for item in rows]

    def quote_label(self, quote_id: int) -> str:
        quote = self.quote(quote_id)
        return str(quote["quote_number"]) if quote else f"presupuesto #{quote_id}"

    def set_quote_status(self, quote_id: int, status: str) -> None:
        if status not in QUOTE_STATUSES:
            raise ValueError("El estado del presupuesto no es válido.")
        now = _now()
        fields = ["status=?", "updated_at=?"]
        params: list[Any] = [status, now]
        if status == "Enviado": fields.append("sent_at=?"); params.append(now)
        if status == "Aceptado": fields.append("accepted_at=?"); params.append(now)
        params.append(int(quote_id))
        with self.connection:
            self.connection.execute(f"UPDATE sales_quotes SET {', '.join(fields)} WHERE id=?", params)

    def approve_quote(self, quote_id: int, approved_by: str) -> None:
        if not str(approved_by or "").strip():
            raise ValueError("Indicá quién aprueba el descuento.")
        with self.connection:
            self.connection.execute(
                "UPDATE sales_quotes SET approval_status='Aprobado', approved_by=?, updated_at=? WHERE id=?",
                (str(approved_by).strip(), _now(), int(quote_id)),
            )

    def quote_message(self, quote_id: int) -> str:
        quote = self.quote(quote_id)
        if not quote:
            raise ValueError("El presupuesto ya no existe.")
        lines = [f"*PRESUPUESTO {quote['quote_number']}*", f"Cliente: {quote['client_name']}", ""]
        for index, item in enumerate(self.quote_items(quote_id), 1):
            variant = " · ".join(part for part in (item["material"], item["size"]) if part)
            lines.append(f"{index}. {item['product_name']}" + (f" ({variant})" if variant else ""))
            lines.append(f"   {item['quantity']} × ${float(item['unit_price']):,.2f} = ${float(item['subtotal']):,.2f}")
        if float(quote["discount_percent"] or 0):
            lines.extend(["", f"Descuento: {float(quote['discount_percent']):g}% ({quote['discount_reason']})"])
        if float(quote.get("promotion_discount_percent") or 0):
            lines.append(f"Promoción {quote.get('promotion_code')}: {float(quote['promotion_discount_percent']):g}%")
        lines.extend(["", f"*TOTAL: ${float(quote['total']):,.2f}*", f"Válido hasta: {quote['valid_until'] or 'consultar'}"])
        if quote["payment_terms"]: lines.append(f"Pago: {quote['payment_terms']}")
        if quote["delivery_terms"]: lines.append(f"Entrega: {quote['delivery_terms']}")
        return "\n".join(lines)

    def convert_quote_to_order(self, quote_id: int, create_order: Callable[..., int]) -> int:
        quote = self.quote(quote_id)
        if not quote:
            raise ValueError("El presupuesto ya no existe.")
        if quote.get("converted_order_id"):
            return int(quote["converted_order_id"])
        if quote.get("approval_status") == "Pendiente":
            raise ValueError("El descuento requiere aprobación antes de convertir el presupuesto.")
        items = self.quote_items(quote_id)
        if not items:
            raise ValueError("El presupuesto no contiene productos.")
        factor = (float(quote["total"] or 0) / float(quote["subtotal"] or 1)) if float(quote["subtotal"] or 0) else 1
        jobs = []
        for item in items:
            jobs.append({
                "title": item["product_name"], "product_id": item["product_id"],
                "material": item["material"], "size": item["size"], "quantity": item["quantity"],
                "subtotal": round(float(item["subtotal"] or 0) * factor, 2), "notes": item["notes"],
            })
        order_id = int(create_order(
            quote["client_name"], quote["whatsapp"], jobs=jobs, status="Nuevo",
            observations=f"Convertido desde {quote['quote_number']}. {quote['notes']}".strip(),
            order_concept=f"Presupuesto {quote['quote_number']}",
        ))
        now = _now()
        with self.connection:
            self.connection.execute(
                "UPDATE sales_quotes SET status='Aceptado', accepted_at=?, converted_order_id=?, updated_at=? WHERE id=?",
                (now, order_id, now, int(quote_id)),
            )
            if quote.get("lead_id"):
                self.connection.execute(
                    "UPDATE sales_leads SET stage='Ganada', probability=100, order_id=?, closed_at=?, updated_at=? WHERE id=?",
                    (order_id, now, now, int(quote["lead_id"])),
                )
            self.connection.execute(
                "UPDATE sales_tasks SET status='Completada', completed_at=?, updated_at=? WHERE quote_id=? AND status='Pendiente'",
                (now, now, int(quote_id)),
            )
        return order_id

    # ------------------------------------------------------- Agenda y cobros
    def tasks(self, *, include_completed: bool = False, limit: int = 200) -> list[dict[str, Any]]:
        where = "" if include_completed else "WHERE t.status='Pendiente'"
        rows = self.connection.execute(
            f"""SELECT t.*, COALESCE(l.client_name, q.client_name, o.client, c.name, '') AS client_name,
                       COALESCE(l.whatsapp, q.whatsapp, o.whatsapp, c.whatsapp, '') AS whatsapp
                  FROM sales_tasks t LEFT JOIN sales_leads l ON l.id=t.lead_id
                  LEFT JOIN sales_quotes q ON q.id=t.quote_id LEFT JOIN orders o ON o.id=t.order_id
                  LEFT JOIN clients c ON c.id=t.client_id {where}
                 ORDER BY CASE WHEN t.status='Pendiente' THEN 0 ELSE 1 END, t.due_at, t.id LIMIT ?""",
            (int(limit),),
        ).fetchall()
        return [dict(item) for item in rows]

    def complete_task(self, task_id: int) -> None:
        now = _now()
        with self.connection:
            self.connection.execute(
                "UPDATE sales_tasks SET status='Completada', completed_at=?, updated_at=? WHERE id=?",
                (now, now, int(task_id)),
            )

    def receivables(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT o.id AS order_id, COALESCE(c.name,o.client) AS client_name, o.whatsapp,
                      COALESCE(o.budget_total,o.price,0) AS total,
                      COALESCE((SELECT SUM(p.amount) FROM order_payments p WHERE p.order_id=o.id AND COALESCE(p.cancelled_at,'')=''),0) AS paid,
                      COALESCE(NULLIF(o.delivery_date,''), o.order_date, o.created_at) AS due_at,
                      o.status
                 FROM orders o LEFT JOIN clients c ON c.id=o.client_id
                WHERE COALESCE(o.is_archived,0)=0
                  AND COALESCE(o.budget_total,o.price,0) > COALESCE((SELECT SUM(p.amount) FROM order_payments p WHERE p.order_id=o.id AND COALESCE(p.cancelled_at,'')=''),0)
                ORDER BY due_at, o.id"""
        ).fetchall()
        result = []
        today = date.today().isoformat()
        for row in rows:
            item = dict(row)
            item["pending"] = round(float(item["total"] or 0) - float(item["paid"] or 0), 2)
            item["overdue"] = bool(str(item["due_at"] or "")[:10] and str(item["due_at"])[:10] < today)
            item["message"] = (
                f"Hola {item['client_name']}, te recuerdo que queda un saldo de ${item['pending']:,.2f} "
                f"del pedido #{item['order_id']}. Avisame cuando realices el pago. ¡Gracias!"
            )
            result.append(item)
        return result

    # -------------------------------------------------------------- Entregas
    def upsert_delivery(self, order_id: int, **values: Any) -> None:
        status = str(values.get("status") or "Sin coordinar")
        if status not in DELIVERY_STATUSES:
            raise ValueError("El estado de entrega no es válido.")
        now = _now()
        received = now if status == "Entregada" else str(values.get("received_at") or "")
        with self.connection:
            if status == "Entregada":
                from app.services.delivery_readiness import assert_deliverable
                self.connection.execute("UPDATE orders SET id=id WHERE id=?", (order_id,))
                assert_deliverable(self.connection, order_id)
            self.connection.execute(
                """INSERT INTO sales_deliveries(order_id, method, address, city, shipping_cost,
                   scheduled_at, time_window, tracking_code, status, received_at, notes, created_at, updated_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(order_id) DO UPDATE SET method=excluded.method, address=excluded.address,
                   city=excluded.city, shipping_cost=excluded.shipping_cost, scheduled_at=excluded.scheduled_at,
                   time_window=excluded.time_window, tracking_code=excluded.tracking_code,
                   status=excluded.status, received_at=excluded.received_at, notes=excluded.notes,
                   updated_at=excluded.updated_at""",
                (int(order_id), str(values.get("method") or "Retiro").strip(), str(values.get("address") or "").strip(),
                 str(values.get("city") or "").strip(), max(0.0, float(values.get("shipping_cost") or 0)),
                 str(values.get("scheduled_at") or "").strip(), str(values.get("time_window") or "").strip(),
                 str(values.get("tracking_code") or "").strip(), status, received,
                 str(values.get("notes") or "").strip(), now, now),
            )
            if status == "Entregada":
                from app.domain.order_states import OrderStateService
                OrderStateService(self.connection).transition(
                    int(order_id), "Terminado", source="sales.delivery",
                    reason="Recepción confirmada desde Entregas", sync_related=True, commit=False,
                )

    def delivery(self, order_id: int) -> dict[str, Any] | None:
        return _row(self.connection.execute("SELECT * FROM sales_deliveries WHERE order_id=?", (int(order_id),)).fetchone())

    def deliveries(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT o.id AS order_id, COALESCE(c.name,o.client) AS client_name, o.whatsapp,
                      o.status AS order_status, o.delivery_date, d.*
                 FROM orders o LEFT JOIN clients c ON c.id=o.client_id
                 LEFT JOIN sales_deliveries d ON d.order_id=o.id
                WHERE COALESCE(o.is_archived,0)=0
                ORDER BY CASE COALESCE(d.status,'Sin coordinar') WHEN 'Sin coordinar' THEN 0 WHEN 'Coordinada' THEN 1 WHEN 'En camino' THEN 2 WHEN 'Lista para retirar' THEN 3 ELSE 4 END,
                         COALESCE(NULLIF(d.scheduled_at,''),NULLIF(o.delivery_date,''),o.order_date),o.id"""
        ).fetchall()
        return [dict(item) for item in rows]

    # ----------------------------------------------------- Clientes/campañas
    def save_client_profile(self, client_id: int, **values: Any) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT INTO client_commercial_profiles(client_id,email,birthday,preferred_channel,tags,notes,last_contact_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(client_id) DO UPDATE SET email=excluded.email,
                   birthday=excluded.birthday,preferred_channel=excluded.preferred_channel,tags=excluded.tags,
                   notes=excluded.notes,last_contact_at=excluded.last_contact_at,updated_at=excluded.updated_at""",
                (int(client_id), str(values.get("email") or "").strip(), str(values.get("birthday") or "").strip(),
                 str(values.get("preferred_channel") or "WhatsApp").strip(), str(values.get("tags") or "").strip(),
                 str(values.get("notes") or "").strip(), str(values.get("last_contact_at") or "").strip(), _now()),
            )

    def customer_segments(self) -> list[dict[str, Any]]:
        dormant_days = int(float(self.setting("dormant_customer_days", "60")))
        rows = self.connection.execute(
            """SELECT c.id,c.name,c.whatsapp,c.client_type,p.email,p.birthday,p.tags,p.preferred_channel,
                      COUNT(o.id) AS order_count,COALESCE(SUM(COALESCE(o.budget_total,o.price,0)),0) AS total_billed,
                      MAX(COALESCE(NULLIF(o.order_date,''),o.created_at)) AS last_order_at
                 FROM clients c LEFT JOIN orders o ON o.client_id=c.id
                 LEFT JOIN client_commercial_profiles p ON p.client_id=c.id
                GROUP BY c.id ORDER BY total_billed DESC,c.name COLLATE NOCASE"""
        ).fetchall()
        today = date.today()
        result = []
        for row in rows:
            item = dict(row)
            last_text = str(item.get("last_order_at") or "")[:10]
            try: days = (today - date.fromisoformat(last_text)).days
            except ValueError: days = 99999
            if str(item.get("client_type") or "").casefold() == "vip" or float(item["total_billed"] or 0) >= 100000:
                segment = "VIP"
            elif int(item["order_count"] or 0) >= 2 and days <= dormant_days:
                segment = "Recurrente"
            elif int(item["order_count"] or 0) and days > dormant_days:
                segment = "Inactivo"
            elif int(item["order_count"] or 0):
                segment = "Nuevo"
            else:
                segment = "Sin compra"
            item.update(segment=segment, days_since_order=days)
            result.append(item)
        return result

    @staticmethod
    def campaign_message(customer: dict[str, Any], campaign: str = "Reactivación") -> str:
        name = str(customer.get("name") or "").split()[0] or "¿cómo estás?"
        segment = customer.get("segment")
        if campaign == "Fidelización" or segment == "VIP":
            return f"Hola {name}, gracias por seguir eligiendo Doccione. Tenemos novedades y beneficios especiales para vos. ¿Querés que te los muestre?"
        if campaign == "Recompra" or segment == "Recurrente":
            return f"Hola {name}, llegaron nuevas opciones que combinan con tus pedidos anteriores. ¿Querés que te pase el catálogo actualizado?"
        return f"Hola {name}, hace un tiempo que no hablamos. En Doccione tenemos productos y diseños nuevos; si querés, te preparo opciones sin compromiso."

    # ------------------------------------------------- Reglas y promociones
    def setting(self, key: str, default: str = "") -> str:
        row = self.connection.execute("SELECT value FROM sales_settings WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row else default

    def settings(self) -> dict[str, str]:
        return {str(row[0]): str(row[1]) for row in self.connection.execute("SELECT key,value FROM sales_settings")}

    def save_settings(self, values: dict[str, Any]) -> None:
        now = _now()
        with self.connection:
            for key, value in values.items():
                self.connection.execute(
                    """INSERT INTO sales_settings(key,value,updated_at) VALUES(?,?,?)
                       ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
                    (str(key), str(value).strip(), now),
                )

    def save_promotion(self, *, code: str, name: str, discount_percent: float, description: str = "",
                       starts_at: str = "", ends_at: str = "", audience: str = "Todos", active: bool = True) -> int:
        code, name = str(code or "").strip().upper(), str(name or "").strip()
        if not code or not name:
            raise ValueError("Ingresá el código y el nombre de la promoción.")
        discount = min(100.0, max(0.0, float(discount_percent or 0)))
        now = _now()
        with self.connection:
            cursor = self.connection.execute(
                """INSERT INTO sales_promotions(code,name,description,discount_percent,starts_at,ends_at,audience,active,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET name=excluded.name,
                   description=excluded.description,discount_percent=excluded.discount_percent,
                   starts_at=excluded.starts_at,ends_at=excluded.ends_at,audience=excluded.audience,
                   active=excluded.active,updated_at=excluded.updated_at""",
                (code, name, str(description).strip(), discount, str(starts_at).strip(), str(ends_at).strip(),
                 str(audience).strip() or "Todos", int(bool(active)), now, now),
            )
        row = self.connection.execute("SELECT id FROM sales_promotions WHERE code=?", (code,)).fetchone()
        return int(row[0] if row else cursor.lastrowid)

    def promotions(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        where = " WHERE active=1" if active_only else ""
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM sales_promotions" + where + " ORDER BY active DESC,ends_at,id DESC"
        )]

    def resolve_promotion(self, code: str) -> dict[str, Any]:
        cleaned = str(code or "").strip().upper()
        row = self.connection.execute(
            "SELECT * FROM sales_promotions WHERE code=? COLLATE NOCASE AND active=1", (cleaned,)
        ).fetchone()
        if not row:
            raise ValueError("El código promocional no existe o está pausado.")
        promotion = dict(row)
        today = date.today().isoformat()
        if promotion.get("starts_at") and str(promotion["starts_at"])[:10] > today:
            raise ValueError("La promoción todavía no está vigente.")
        if promotion.get("ends_at") and str(promotion["ends_at"])[:10] < today:
            raise ValueError("La promoción está vencida.")
        return promotion

    # ---------------------------------------------------------- Indicadores
    def dashboard_metrics(self) -> dict[str, Any]:
        order = self.connection.execute(
            """SELECT COUNT(*) AS orders,COALESCE(SUM(COALESCE(budget_total,price,0)),0) AS sales,
                      COALESCE(AVG(NULLIF(COALESCE(budget_total,price,0),0)),0) AS average_ticket,
                      COALESCE(SUM(COALESCE(margin,0)),0) AS margin
                 FROM orders WHERE COALESCE(is_archived,0)=0"""
        ).fetchone()
        collected = float(self.connection.execute("SELECT COALESCE(SUM(amount),0) FROM order_payments WHERE COALESCE(cancelled_at,'')=''").fetchone()[0] or 0)
        leads = self.connection.execute(
            "SELECT COUNT(*) AS total,SUM(CASE WHEN stage='Ganada' THEN 1 ELSE 0 END) AS won FROM sales_leads"
        ).fetchone()
        quotes = self.connection.execute(
            "SELECT COUNT(*) AS total,SUM(CASE WHEN status='Aceptado' THEN 1 ELSE 0 END) AS accepted FROM sales_quotes"
        ).fetchone()
        outstanding = sum(float(item["pending"]) for item in self.receivables())
        tasks_due = int(self.connection.execute(
            "SELECT COUNT(*) FROM sales_tasks WHERE status='Pendiente' AND substr(due_at,1,10)<=?", (date.today().isoformat(),)
        ).fetchone()[0])
        repeat = int(self.connection.execute(
            "SELECT COUNT(*) FROM (SELECT client_id FROM orders WHERE client_id IS NOT NULL GROUP BY client_id HAVING COUNT(*)>1)"
        ).fetchone()[0])
        return {
            "orders": int(order["orders"] or 0), "sales": float(order["sales"] or 0),
            "collected": collected, "outstanding": outstanding,
            "average_ticket": float(order["average_ticket"] or 0), "margin": float(order["margin"] or 0),
            "leads": int(leads["total"] or 0), "won_leads": int(leads["won"] or 0),
            "lead_conversion": round((int(leads["won"] or 0) / int(leads["total"] or 1)) * 100, 1),
            "quotes": int(quotes["total"] or 0), "accepted_quotes": int(quotes["accepted"] or 0),
            "quote_conversion": round((int(quotes["accepted"] or 0) / int(quotes["total"] or 1)) * 100, 1),
            "tasks_due": tasks_due, "repeat_customers": repeat,
        }

    def top_products(self, limit: int = 8) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT COALESCE(NULLIF(product_name_snapshot,''),NULLIF(title,''),'Producto') AS product,
                      SUM(quantity) AS quantity,SUM(subtotal) AS sales
                 FROM order_jobs GROUP BY product ORDER BY sales DESC LIMIT ?""", (int(limit),)
        ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------ Catálogo público
    def export_catalog_html(self, destination: str | Path, *, title: str = "Catálogo Doccione") -> Path:
        destination = Path(destination)
        whatsapp = "".join(character for character in self.setting("business_whatsapp", "") if character.isdigit())
        call_to_action = (
            f'<a class="cta" href="https://wa.me/{whatsapp}?text=Hola%20Doccione%2C%20quiero%20consultar%20por%20un%20producto">Consultar por WhatsApp</a>'
            if whatsapp else '<span class="cta disabled">Consultanos para pedir</span>'
        )
        products = [dict(row) for row in self.connection.execute(
            """SELECT p.*,COALESCE(p.base_price,MIN(pr.price),0) AS display_price
                 FROM products p LEFT JOIN price_rules pr ON pr.product_id=p.id AND pr.active=1
                WHERE p.active=1 GROUP BY p.id ORDER BY p.category,p.name COLLATE NOCASE"""
        )]
        cards = []
        for product in products:
            image = self._image_data_uri(product.get("image_path"))
            picture = f'<img src="{image}" alt="{html.escape(str(product["name"]))}">' if image else '<div class="placeholder">DOCCIONE</div>'
            price = float(product.get("display_price") or 0)
            cards.append(f"""<article class="card">{picture}<div class="copy">
                <small>{html.escape(str(product.get('category') or 'Producto'))}</small>
                <h2>{html.escape(str(product['name']))}</h2>
                <p>{html.escape(str(product.get('description') or 'Consultá variantes y disponibilidad.'))}</p>
                <strong>{'Desde $' + format(price, ',.2f') if price else 'Consultar precio'}</strong>
                </div></article>""")
        generated = datetime.now().strftime("%d/%m/%Y %H:%M")
        body = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>{html.escape(title)}</title><style>
        :root{{--wine:#7f1734;--ink:#17151a;--paper:#f7f3f1;--muted:#6d6468}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:Arial,sans-serif}}
        header{{padding:48px clamp(20px,6vw,90px);background:linear-gradient(135deg,#481020,var(--wine));color:white}}header h1{{font-size:clamp(34px,6vw,68px);margin:0}}header p{{max-width:620px;line-height:1.6}}.cta{{display:inline-block;margin-top:10px;padding:12px 18px;border-radius:999px;background:white;color:var(--wine);font-weight:bold;text-decoration:none}}.cta.disabled{{opacity:.75}}
        main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:22px;padding:32px clamp(20px,6vw,90px) 70px}}.card{{overflow:hidden;background:white;border-radius:18px;box-shadow:0 8px 26px #3b152018}}
        img,.placeholder{{width:100%;height:220px;object-fit:cover;background:#251e22;display:flex;align-items:center;justify-content:center;color:#c9aab3;font-weight:bold;letter-spacing:3px}}.copy{{padding:20px}}small{{color:var(--wine);font-weight:bold;text-transform:uppercase}}h2{{margin:8px 0}}p{{color:var(--muted);line-height:1.45;min-height:44px}}strong{{font-size:20px;color:var(--wine)}}footer{{padding:24px;text-align:center;color:var(--muted)}}
        </style></head><body><header><h1>{html.escape(title)}</h1><p>Productos, opciones y precios de referencia. Consultanos para confirmar disponibilidad, personalización y plazo de entrega.</p>{call_to_action}</header>
        <main>{''.join(cards) if cards else '<p>No hay productos activos para mostrar.</p>'}</main><footer>Actualizado el {generated} · Doccione</footer></body></html>"""
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(body, encoding="utf-8")
        return destination

    @staticmethod
    def _image_data_uri(raw_path: Any) -> str:
        path = Path(str(raw_path or ""))
        try:
            if not path.is_file() or path.stat().st_size > 4_000_000:
                return ""
            mime = mimetypes.guess_type(path.name)[0] or "image/png"
            return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
        except OSError:
            return ""
