from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any


class InsufficientStockError(RuntimeError):
    """Raised when reserved/physical stock is insufficient for an order."""


@dataclass(slots=True)
class PriceSuggestion:
    unit_cost: float
    current_price: float
    suggested_price: float
    margin_pct: float


class StockCostPriceService:
    """Syncs stock, material costs and price rules around the existing DB schema."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                unit TEXT DEFAULT '',
                physical_stock REAL DEFAULT 0,
                reserved_stock REAL DEFAULT 0,
                min_stock REAL DEFAULT 0,
                unit_cost REAL DEFAULT 0,
                supplier TEXT DEFAULT '',
                purchase_price REAL DEFAULT 0,
                purchase_link TEXT DEFAULT '',
                sale_quantity REAL DEFAULT 1,
                sale_unit_price REAL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        # Keep installations created before the commercial material form compatible.
        existing_columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(materials)").fetchall()
        }
        for column, definition in (
            ("purchase_price", "REAL DEFAULT 0"),
            ("purchase_link", "TEXT DEFAULT ''"),
            ("sale_quantity", "REAL DEFAULT 1"),
            ("sale_unit_price", "REAL DEFAULT 0"),
        ):
            if column not in existing_columns:
                self.connection.execute(f"ALTER TABLE materials ADD COLUMN {column} {definition}")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS material_stock_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_id INTEGER NOT NULL,
                movement_type TEXT NOT NULL,
                quantity REAL NOT NULL DEFAULT 0,
                unit_cost REAL DEFAULT 0,
                reference TEXT DEFAULT '',
                details TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(material_id) REFERENCES materials(id)
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS material_component_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_id INTEGER NOT NULL,
                component_id INTEGER NOT NULL,
                sync_unit_cost INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                UNIQUE(material_id, component_id)
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS material_purchase_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_id INTEGER NOT NULL,
                quantity REAL NOT NULL,
                total_cost REAL NOT NULL,
                unit_cost REAL NOT NULL,
                reference TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(material_id) REFERENCES materials(id)
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS material_price_policies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                price_rule_id INTEGER NOT NULL UNIQUE,
                mode TEXT NOT NULL DEFAULT 'review',
                calculation_type TEXT NOT NULL DEFAULT 'margin',
                target_percentage REAL DEFAULT 0,
                rounding_step REAL DEFAULT 0,
                minimum_price REAL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS order_stock_reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_job_id INTEGER NOT NULL UNIQUE,
                material_id INTEGER NOT NULL,
                component_id INTEGER DEFAULT NULL,
                quantity REAL NOT NULL DEFAULT 0,
                reserved_at TEXT NOT NULL,
                consumed_at TEXT DEFAULT ''
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_order_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_job_id INTEGER NOT NULL,
                price_rule_id INTEGER DEFAULT NULL,
                material_id INTEGER DEFAULT NULL,
                production_quantity REAL DEFAULT 0,
                sale_total REAL DEFAULT 0,
                unit_cost REAL DEFAULT 0,
                current_price REAL DEFAULT 0,
                suggested_price REAL DEFAULT 0,
                gross_profit REAL DEFAULT 0,
                margin_pct REAL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(order_job_id)
            )
            """
        )
        self.connection.commit()

    def create_material(
        self,
        *,
        name: str,
        unit: str = "",
        physical_stock: float = 0,
        min_stock: float = 0,
        unit_cost: float = 0,
        supplier: str = "",
        purchase_price: float = 0,
        purchase_link: str = "",
        sale_quantity: float = 1,
        sale_unit_price: float = 0,
    ) -> int:
        now = self._now()
        cursor = self.connection.execute(
            """
            INSERT INTO materials (
                name, unit, physical_stock, reserved_stock, min_stock, unit_cost, supplier,
                purchase_price, purchase_link, sale_quantity, sale_unit_price, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name.strip(), unit.strip(), float(physical_stock), 0.0, float(min_stock), float(unit_cost),
                supplier.strip(), float(purchase_price), purchase_link.strip(), float(sale_quantity),
                float(sale_unit_price), now, now,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def get_material(self, material_id: int) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM materials WHERE id = ?",
            (material_id,),
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["available_stock"] = float(data.get("physical_stock", 0) or 0) - float(data.get("reserved_stock", 0) or 0)
        return data

    def dashboard_metrics(self) -> dict[str, float | int]:
        """Return the operational and commercial indicators shown in Stock."""
        inventory = self.connection.execute(
            """
            SELECT
                COUNT(*) AS material_count,
                COALESCE(SUM(physical_stock * unit_cost), 0) AS inventory_value,
                COALESCE(SUM(reserved_stock * unit_cost), 0) AS reserved_value,
                COALESCE(SUM(CASE WHEN physical_stock <= min_stock THEN 1 ELSE 0 END), 0) AS low_stock_count
            FROM materials
            """
        ).fetchone()
        sales = self.connection.execute(
            """
            SELECT
                COALESCE(SUM(sale_total), 0) AS sales_total,
                COALESCE(SUM(gross_profit), 0) AS gross_profit,
                COUNT(*) AS process_count
            FROM stock_order_snapshots
            """
        ).fetchone()
        movements = self.connection.execute(
            """
            SELECT COUNT(*) AS movement_count
            FROM material_stock_movements
            WHERE created_at >= datetime('now', '-30 days')
            """
        ).fetchone()
        def value(row: Any, key: str, index: int) -> Any:
            return row[key] if isinstance(row, sqlite3.Row) else row[index]

        sales_total = float(value(sales, "sales_total", 0) or 0)
        gross_profit = float(value(sales, "gross_profit", 1) or 0)
        return {
            "material_count": int(value(inventory, "material_count", 0) or 0),
            "inventory_value": float(value(inventory, "inventory_value", 1) or 0),
            "reserved_value": float(value(inventory, "reserved_value", 2) or 0),
            "low_stock_count": int(value(inventory, "low_stock_count", 3) or 0),
            "sales_total": sales_total,
            "gross_profit": gross_profit,
            "margin_pct": (gross_profit / sales_total * 100.0) if sales_total else 0.0,
            "process_count": int(value(sales, "process_count", 2) or 0),
            "movement_count": int(value(movements, "movement_count", 0) or 0),
        }

    def register_purchase(self, *, material_id: int, quantity: float, total_cost: float, reference: str = "") -> float:
        material = self.get_material(material_id)
        if not material:
            raise ValueError("Material no encontrado")
        qty = max(float(quantity), 0.0)
        total = max(float(total_cost), 0.0)
        if qty <= 0:
            raise ValueError("La cantidad debe ser mayor a cero")
        current_stock = float(material.get("physical_stock", 0) or 0)
        current_cost = float(material.get("unit_cost", 0) or 0)
        new_stock = current_stock + qty
        if current_stock <= 0 or current_cost <= 0:
            new_cost = total / qty
        else:
            new_cost = ((current_stock * current_cost) + total) / new_stock
        now = self._now()
        self.connection.execute(
            """
            INSERT INTO material_stock_movements (
                material_id, movement_type, quantity, unit_cost, reference, details, created_at
            ) VALUES (?, 'purchase', ?, ?, ?, ?, ?)
            """,
            (material_id, qty, new_cost, reference.strip(), f"Compra {reference or material_id}", now),
        )
        self.connection.execute(
            """
            INSERT INTO material_purchase_history (
                material_id, quantity, total_cost, unit_cost, reference, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (material_id, qty, total, new_cost, reference.strip(), now),
        )
        self.connection.execute(
            """
            UPDATE materials
            SET physical_stock = ?, unit_cost = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_stock, new_cost, now, material_id),
        )
        self.connection.commit()
        self._sync_material_component_costs(material_id)
        return float(new_cost)

    def link_component_to_material(self, *, component_id: int, material_id: int, sync_unit_cost: bool = True) -> None:
        self.connection.execute(
            """
            INSERT OR IGNORE INTO material_component_links (
                material_id, component_id, sync_unit_cost, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (material_id, component_id, int(sync_unit_cost), self._now()),
        )
        self.connection.commit()
        if sync_unit_cost:
            self._sync_component_unit_value(component_id, material_id)

    def _sync_component_unit_value(self, component_id: int, material_id: int) -> None:
        material = self.get_material(material_id)
        if not material:
            return
        self.connection.execute(
            "UPDATE variable_cost_components SET unit_value = ? WHERE id = ?",
            (float(material.get("unit_cost", 0) or 0), component_id),
        )
        self.connection.commit()

    def _sync_material_component_costs(self, material_id: int) -> None:
        for link in self._component_links(material_id):
            if bool(link.get("sync_unit_cost", 1)):
                self._sync_component_unit_value(int(link["component_id"]), material_id)

    def _component_links(self, material_id: int) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM material_component_links WHERE material_id = ?",
            (material_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def configure_price_policy(
        self,
        *,
        price_rule_id: int,
        mode: str = "review",
        calculation_type: str = "margin",
        target_percentage: float = 0,
        rounding_step: float = 0,
        minimum_price: float = 0,
    ) -> None:
        now = self._now()
        self.connection.execute(
            """
            INSERT INTO material_price_policies (
                price_rule_id, mode, calculation_type, target_percentage, rounding_step, minimum_price, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(price_rule_id) DO UPDATE SET
                mode = excluded.mode,
                calculation_type = excluded.calculation_type,
                target_percentage = excluded.target_percentage,
                rounding_step = excluded.rounding_step,
                minimum_price = excluded.minimum_price,
                updated_at = excluded.updated_at
            """,
            (price_rule_id, mode, calculation_type, float(target_percentage), float(rounding_step), float(minimum_price), now, now),
        )
        self.connection.commit()

    def price_suggestion(self, price_rule_id: int) -> PriceSuggestion:
        rule = self._get_price_rule(price_rule_id)
        if not rule:
            raise ValueError("Regla de precio no encontrada")
        material = self._material_from_rule(rule)
        unit_cost = float(material.get("unit_cost", 0) or 0) if material else 0.0
        current_price = float(rule.get("price", 0) or 0)
        policy = self._get_policy(price_rule_id) or {}
        target_percentage = float(policy.get("target_percentage", 0) or 0)
        if target_percentage <= 0:
            target_percentage = 45.0
        suggested_price = self._calculate_price(unit_cost, target_percentage, policy)
        return PriceSuggestion(
            unit_cost=unit_cost,
            current_price=current_price,
            suggested_price=suggested_price,
            margin_pct=target_percentage,
        )

    def apply_suggested_price(self, price_rule_id: int) -> float:
        suggestion = self.price_suggestion(price_rule_id)
        self.connection.execute(
            "UPDATE price_rules SET price = ?, outdated = 0, last_synced_at = ? WHERE id = ?",
            (suggestion.suggested_price, self._now(), price_rule_id),
        )
        self.connection.commit()
        return float(suggestion.suggested_price)

    def reserve_for_order(
        self,
        *,
        order_job_id: int,
        cost_model_id: int,
        production_quantity: float,
        commit: bool = True,
    ) -> bool:
        """Reserva material para un trabajo.

        ``commit=False`` permite que un workflow que comparte esta conexión
        incluya la reserva en una transacción mayor. Devuelve ``False`` cuando
        el modelo no tiene un material enlazado; no se inventa un consumo.
        """
        material_id = self._material_id_from_model(cost_model_id)
        if material_id is None:
            return False
        qty = max(float(production_quantity), 0.0)
        if qty <= 0:
            raise ValueError("La cantidad debe ser mayor a cero")
        material = self.get_material(material_id)
        if not material:
            raise ValueError("Material no encontrado")
        required_qty = self._required_material_quantity(material_id, cost_model_id, qty)
        available = float(material.get("available_stock", 0) or 0)
        if available < required_qty:
            raise InsufficientStockError(f"Stock insuficiente para {required_qty} unidades. Disponibles: {available}")
        now = self._now()
        existing = self.connection.execute(
            "SELECT quantity FROM order_stock_reservations WHERE order_job_id = ?",
            (order_job_id,),
        ).fetchone()
        if existing is not None:
            current_qty = float(existing[0] or 0)
            delta_qty = required_qty - current_qty
            if delta_qty <= 0:
                self.connection.execute(
                    "UPDATE order_stock_reservations SET consumed_at = '' WHERE order_job_id = ?",
                    (order_job_id,),
                )
                if commit:
                    self.connection.commit()
                return True
            self.connection.execute(
                """
                UPDATE order_stock_reservations
                SET material_id = ?, component_id = NULL, quantity = ?, reserved_at = ?, consumed_at = ''
                WHERE order_job_id = ?
                """,
                (material_id, required_qty, now, order_job_id),
            )
            self.connection.execute(
                """
                UPDATE materials
                SET reserved_stock = reserved_stock + ?, updated_at = ?
                WHERE id = ?
                """,
                (delta_qty, now, material_id),
            )
            if commit:
                self.connection.commit()
            return True
        self.connection.execute(
            """
            INSERT INTO order_stock_reservations (
                order_job_id, material_id, component_id, quantity, reserved_at
            ) VALUES (?, ?, NULL, ?, ?)
            """,
            (order_job_id, material_id, required_qty, now),
        )
        self.connection.execute(
            """
            UPDATE materials
            SET reserved_stock = reserved_stock + ?, updated_at = ?
            WHERE id = ?
            """,
            (required_qty, now, material_id),
        )
        if commit:
            self.connection.commit()
        return True

    def sync_order_job_stock(
        self,
        *,
        order_job_id: int,
        state: str,
        cost_model_id: int,
        production_quantity: float,
        previous_state: str | None = None,
    ) -> None:
        normalized_state = (state or "").strip().lower()
        normalized_previous = (previous_state or "").strip().lower()
        if normalized_state in {"reserved", "reserve", "pending", "confirmado", "confirmada", "diseño", "en revisión", "esperando archivos", "en producción", "listo para armado de planchas", "listo para imprimir", "impresión", "sublimado / laminado", "corte", "control de calidad", "bloqueado"}:
            if normalized_previous in {"cancelado", "cancelled", "cancel", "rechazado", "released", "liberado"}:
                self.release_order_reservation(order_job_id)
            elif normalized_previous in {"completed", "complete", "done", "consumed", "finished", "entregado"}:
                self.consume_order_reservations(order_job_id)
            else:
                self.reserve_for_order(order_job_id=order_job_id, cost_model_id=cost_model_id, production_quantity=production_quantity)
            return
        if normalized_state in {"completed", "complete", "done", "consumed", "finished", "entregado", "finalizado"}:
            self.consume_order_reservations(order_job_id)
            return
        if normalized_state in {"canceled", "cancelled", "released", "release", "cancel", "cancelado", "rechazado", "liberado"}:
            self.release_order_reservation(order_job_id)
            return

    def adjust_stock(self, *, material_id: int, delta: float, reference: str = "", details: str = "") -> None:
        material = self.get_material(material_id)
        if not material:
            raise ValueError("Material no encontrado")
        delta_value = float(delta or 0)
        if delta_value == 0:
            return
        now = self._now()
        self.connection.execute(
            """
            INSERT INTO material_stock_movements (
                material_id, movement_type, quantity, unit_cost, reference, details, created_at
            ) VALUES (?, 'adjustment', ?, ?, ?, ?, ?)
            """,
            (material_id, delta_value, float(material.get("unit_cost", 0) or 0), reference.strip(), details.strip(), now),
        )
        self.connection.execute(
            """
            UPDATE materials
            SET physical_stock = physical_stock + ?, updated_at = ?
            WHERE id = ?
            """,
            (delta_value, now, material_id),
        )
        self.connection.commit()

    def consume_order_reservations(self, order_job_id: int) -> None:
        reservation = self.connection.execute(
            "SELECT * FROM order_stock_reservations WHERE order_job_id = ?",
            (order_job_id,),
        ).fetchone()
        if not reservation:
            return
        consumed_at_value = reservation["consumed_at"] if isinstance(reservation, sqlite3.Row) else reservation.get("consumed_at")
        consumed_at = str(consumed_at_value or "").strip()
        if consumed_at:
            return
        material_id = int(reservation["material_id"])
        qty = float(reservation["quantity"] or 0)
        self.connection.execute(
            """
            UPDATE materials
            SET physical_stock = physical_stock - ?, reserved_stock = reserved_stock - ?, updated_at = ?
            WHERE id = ?
            """,
            (qty, qty, self._now(), material_id),
        )
        self.connection.execute(
            "UPDATE order_stock_reservations SET consumed_at = ? WHERE order_job_id = ?",
            (self._now(), order_job_id),
        )
        self.connection.commit()

    def release_order_reservation(self, order_job_id: int) -> None:
        reservation = self.connection.execute(
            "SELECT * FROM order_stock_reservations WHERE order_job_id = ?",
            (order_job_id,),
        ).fetchone()
        if not reservation:
            return
        consumed_at_value = reservation["consumed_at"] if isinstance(reservation, sqlite3.Row) else reservation.get("consumed_at")
        consumed_at = str(consumed_at_value or "").strip()
        if consumed_at:
            return
        material_id = int(reservation["material_id"])
        qty = float(reservation["quantity"] or 0)
        self.connection.execute(
            """
            UPDATE materials
            SET reserved_stock = reserved_stock - ?, updated_at = ?
            WHERE id = ?
            """,
            (qty, self._now(), material_id),
        )
        self.connection.execute("DELETE FROM order_stock_reservations WHERE order_job_id = ?", (order_job_id,))
        self.connection.commit()

    def save_order_snapshot(
        self,
        *,
        order_job_id: int,
        price_rule_id: int | None = None,
        production_quantity: float = 0,
        sale_total: float = 0,
    ) -> None:
        rule = self._get_price_rule(price_rule_id) if price_rule_id is not None else None
        material = self._material_from_rule(rule) if rule else None
        unit_cost = float(material.get("unit_cost", 0) or 0) if material else 0.0
        current_price = float(rule.get("price", 0) or 0) if rule else 0.0
        suggestion = self.price_suggestion(price_rule_id) if price_rule_id is not None else None
        suggested_price = float(suggestion.suggested_price) if suggestion else 0.0
        production_qty = max(float(production_quantity or 0), 0.0)
        gross_profit = float(sale_total or 0) - (production_qty * unit_cost)
        margin_pct = (gross_profit / float(sale_total or 0) * 100.0) if float(sale_total or 0) else 0.0
        self.connection.execute(
            """
            INSERT INTO stock_order_snapshots (
                order_job_id, price_rule_id, material_id, production_quantity, sale_total,
                unit_cost, current_price, suggested_price, gross_profit, margin_pct, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(order_job_id) DO UPDATE SET
                price_rule_id = excluded.price_rule_id,
                material_id = excluded.material_id,
                production_quantity = excluded.production_quantity,
                sale_total = excluded.sale_total,
                unit_cost = excluded.unit_cost,
                current_price = excluded.current_price,
                suggested_price = excluded.suggested_price,
                gross_profit = excluded.gross_profit,
                margin_pct = excluded.margin_pct,
                created_at = excluded.created_at
            """,
            (
                order_job_id,
                price_rule_id,
                int(material["id"]) if material and material.get("id") is not None else None,
                float(production_quantity or 0),
                float(sale_total or 0),
                unit_cost,
                current_price,
                suggested_price,
                gross_profit,
                margin_pct,
                self._now(),
            ),
        )
        self.connection.commit()

    def _calculate_price(self, unit_cost: float, target_percentage: float, policy: dict[str, Any] | None) -> float:
        price = unit_cost / (1 - (target_percentage / 100.0)) if target_percentage < 100 else unit_cost * 2
        if policy:
            minimum_price = float(policy.get("minimum_price", 0) or 0)
            if minimum_price > 0 and price < minimum_price:
                price = minimum_price
        return float(price)

    def _required_material_quantity(self, material_id: int, cost_model_id: int, production_quantity: float) -> float:
        rows = self.connection.execute(
            """
            SELECT c.quantity
            FROM material_component_links l
            JOIN variable_cost_components c ON c.id = l.component_id
            WHERE l.material_id = ? AND c.model_id = ?
            """,
            (material_id, cost_model_id),
        ).fetchall()
        if not rows:
            return max(float(production_quantity), 0.0)
        required = 0.0
        for row in rows:
            component_quantity = float(row[0] or 0)
            if component_quantity <= 0:
                component_quantity = 1.0
            required += production_quantity * component_quantity
        return required

    def _get_price_rule(self, price_rule_id: int) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM price_rules WHERE id = ?", (price_rule_id,)).fetchone()
        return dict(row) if row else None

    def _get_policy(self, price_rule_id: int) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM material_price_policies WHERE price_rule_id = ?", (price_rule_id,)).fetchone()
        return dict(row) if row else None

    def _material_from_rule(self, rule: dict[str, Any] | None) -> dict[str, Any] | None:
        if not rule:
            return None
        material_name = str(rule.get("material") or "").strip()
        if not material_name:
            return None
        row = self.connection.execute("SELECT * FROM materials WHERE name = ?", (material_name,)).fetchone()
        return dict(row) if row else None

    def _material_id_from_model(self, cost_model_id: int) -> int | None:
        row = self.connection.execute(
            "SELECT m.id FROM materials m JOIN material_component_links l ON l.material_id = m.id JOIN variable_cost_components c ON c.id = l.component_id WHERE c.model_id = ? LIMIT 1",
            (cost_model_id,),
        ).fetchone()
        return int(row[0]) if row else None

    def delete_material(self, material_id: int) -> None:
        """Delete a material and its related data."""
        # Delete related records first (foreign key constraints)
        self.connection.execute("DELETE FROM material_stock_movements WHERE material_id = ?", (material_id,))
        self.connection.execute("DELETE FROM material_purchase_history WHERE material_id = ?", (material_id,))
        self.connection.execute("DELETE FROM material_component_links WHERE material_id = ?", (material_id,))
        self.connection.execute("DELETE FROM material_price_policies WHERE price_rule_id IN (SELECT id FROM price_rules WHERE material = (SELECT name FROM materials WHERE id = ?))", (material_id,))
        self.connection.execute("DELETE FROM order_stock_reservations WHERE material_id = ?", (material_id,))
        self.connection.execute("DELETE FROM stock_order_snapshots WHERE material_id = ?", (material_id,))
        # Delete the material itself
        self.connection.execute("DELETE FROM materials WHERE id = ?", (material_id,))
        self.connection.commit()

    def _now(self) -> str:
        return datetime.now().isoformat(timespec="seconds")
