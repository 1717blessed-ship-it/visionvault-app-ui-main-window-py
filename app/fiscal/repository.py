"""Persistencia inmutable para comprobantes fiscales.

Este módulo no emite comprobantes por sí mismo: conserva los datos necesarios
para una futura integración ARCA y evita que una factura autorizada sea
alterada al editar el pedido original.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any


class FiscalRepository:
    """Almacena perfiles fiscales, receptores y comprobantes de pedidos."""

    DRAFT = "Borrador"
    PENDING = "Pendiente de emisión"
    AUTHORIZED = "Autorizado"
    REJECTED = "Rechazado"
    CANCELLED = "Anulado"

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.create_tables()

    def create_tables(self) -> None:
        with self.connection:
            self.connection.execute(
                """CREATE TABLE IF NOT EXISTS fiscal_profiles (
                    id INTEGER PRIMARY KEY,
                    legal_name TEXT NOT NULL DEFAULT '', cuit TEXT NOT NULL DEFAULT '',
                    iva_condition TEXT NOT NULL DEFAULT '', point_of_sale INTEGER,
                    environment TEXT NOT NULL DEFAULT 'homologacion', active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )"""
            )
            self.connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_fiscal_profiles_active "
                "ON fiscal_profiles(active) WHERE active = 1"
            )
            self.connection.execute(
                """CREATE TABLE IF NOT EXISTS client_tax_profiles (
                    client_id INTEGER PRIMARY KEY, document_type TEXT NOT NULL DEFAULT 'Consumidor final',
                    document_number TEXT NOT NULL DEFAULT '', legal_name TEXT NOT NULL DEFAULT '',
                    iva_condition TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL, FOREIGN KEY(client_id) REFERENCES clients(id)
                )"""
            )
            self.connection.execute(
                """CREATE TABLE IF NOT EXISTS fiscal_invoices (
                    id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL,
                    profile_id INTEGER, invoice_type TEXT NOT NULL,
                    point_of_sale INTEGER, voucher_number INTEGER,
                    status TEXT NOT NULL DEFAULT 'Borrador', currency TEXT NOT NULL DEFAULT 'ARS',
                    total REAL NOT NULL, receiver_snapshot_json TEXT NOT NULL DEFAULT '{}',
                    lines_snapshot_json TEXT NOT NULL DEFAULT '[]', cae TEXT NOT NULL DEFAULT '',
                    cae_expires_at TEXT NOT NULL DEFAULT '', pdf_path TEXT NOT NULL DEFAULT '',
                    external_reference TEXT NOT NULL DEFAULT '', error_detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, authorized_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
                    FOREIGN KEY(order_id) REFERENCES orders(id),
                    FOREIGN KEY(profile_id) REFERENCES fiscal_profiles(id)
                )"""
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_fiscal_invoices_order ON fiscal_invoices(order_id, id DESC)"
            )
            self.connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_fiscal_invoice_number "
                "ON fiscal_invoices(point_of_sale, invoice_type, voucher_number) "
                "WHERE voucher_number IS NOT NULL"
            )

    def save_profile(self, *, legal_name: str, cuit: str, iva_condition: str,
                     point_of_sale: int | None, environment: str = "homologacion") -> int:
        if environment not in {"homologacion", "produccion"}:
            raise ValueError("El entorno fiscal debe ser homologacion o produccion.")
        if not legal_name.strip() or not cuit.strip() or not iva_condition.strip():
            raise ValueError("Razón social, CUIT y condición IVA son obligatorios.")
        now = _now()
        with self.connection:
            self.connection.execute("UPDATE fiscal_profiles SET active = 0 WHERE active = 1")
            cursor = self.connection.execute(
                """INSERT INTO fiscal_profiles(legal_name, cuit, iva_condition, point_of_sale, environment, active, created_at, updated_at)
                   VALUES(?, ?, ?, ?, ?, 1, ?, ?)""",
                (legal_name.strip(), _digits(cuit), iva_condition.strip(), point_of_sale, environment, now, now),
            )
        return int(cursor.lastrowid)

    def active_profile(self) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM fiscal_profiles WHERE active = 1 LIMIT 1").fetchone()
        return dict(row) if row else None

    def upsert_client_profile(self, client_id: int, **values: str) -> None:
        now = _now()
        with self.connection:
            self.connection.execute(
                """INSERT INTO client_tax_profiles(client_id, document_type, document_number, legal_name, iva_condition, address, updated_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(client_id) DO UPDATE SET document_type = excluded.document_type,
                     document_number = excluded.document_number, legal_name = excluded.legal_name,
                     iva_condition = excluded.iva_condition, address = excluded.address, updated_at = excluded.updated_at""",
                (client_id, values.get("document_type", "Consumidor final"), _digits(values.get("document_number", "")),
                 values.get("legal_name", "").strip(), values.get("iva_condition", "").strip(), values.get("address", "").strip(), now),
            )

    def create_invoice_draft(self, order_id: int, invoice_type: str, *, profile_id: int | None = None) -> int:
        order = self.connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not order:
            raise ValueError(f"Pedido #{order_id} inexistente.")
        profile = self.active_profile() if profile_id is None else self.connection.execute(
            "SELECT * FROM fiscal_profiles WHERE id = ?", (profile_id,)
        ).fetchone()
        if not profile:
            raise ValueError("Configurá un perfil fiscal antes de crear un comprobante.")
        profile_data = dict(profile)
        client = self.connection.execute("SELECT * FROM clients WHERE id = ?", (order["client_id"],)).fetchone() if order["client_id"] else None
        tax = self.connection.execute("SELECT * FROM client_tax_profiles WHERE client_id = ?", (client["id"],)).fetchone() if client else None
        lines = self.connection.execute("SELECT title, quantity, subtotal FROM order_jobs WHERE order_id = ? ORDER BY sort_order, id", (order_id,)).fetchall()
        now = _now()
        with self.connection:
            cursor = self.connection.execute(
                """INSERT INTO fiscal_invoices(order_id, profile_id, invoice_type, point_of_sale, status, total,
                   receiver_snapshot_json, lines_snapshot_json, created_at, updated_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (order_id, profile_data["id"], invoice_type.strip(), profile_data["point_of_sale"], self.DRAFT,
                 float(order["budget_total"] or order["price"] or 0),
                 json.dumps(dict(tax) if tax else {"legal_name": (dict(client).get("name") if client else order["client"])}, ensure_ascii=False),
                 json.dumps([dict(line) for line in lines], ensure_ascii=False), now, now),
            )
        return int(cursor.lastrowid)

    def invoices_for_order(self, order_id: int) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT * FROM fiscal_invoices WHERE order_id = ? ORDER BY id DESC", (order_id,))
        return [dict(row) for row in rows]

    def mark_authorized(self, invoice_id: int, *, voucher_number: int, cae: str, cae_expires_at: str, pdf_path: str = "") -> None:
        if not cae.strip() or voucher_number <= 0:
            raise ValueError("Número de comprobante y CAE son obligatorios para autorizar.")
        now = _now()
        with self.connection:
            changed = self.connection.execute(
                """UPDATE fiscal_invoices SET status = ?, voucher_number = ?, cae = ?, cae_expires_at = ?,
                   pdf_path = ?, authorized_at = ?, updated_at = ? WHERE id = ? AND status IN (?, ?)""",
                (self.AUTHORIZED, voucher_number, cae.strip(), cae_expires_at, pdf_path, now, now, invoice_id, self.DRAFT, self.PENDING),
            ).rowcount
        if not changed:
            raise ValueError("El comprobante no existe o ya fue procesado.")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _digits(value: str) -> str:
    return "".join(char for char in str(value) if char.isdigit())
