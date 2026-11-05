"""Service for calculating Fotocopias y terminaciones prices."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class FotocopiaPriceCalculation:
    """Result of a Fotocopias y terminaciones price calculation."""
    base_price: float
    discount_amount: float
    discount_percent: float
    surcharge_amount: float
    surcharge_percent: float
    final_price: float
    calculation_details: dict[str, Any]
    is_urgent: bool
    manual_price: float | None = None


class FotocopiaPricingService:
    """Calculates prices for Fotocopias y terminaciones with discounts and surcharges."""

    PHOTOCOPY_PRODUCT_CODES = frozenset({
        "fotocopia_bn_simple",
        "fotocopia_bn_doble",
        "fotocopia_color_simple",
        "fotocopia_color_doble",
    })

    PRODUCT_CODE_BY_TITLE = {
        "fotocopia b/n simple": "fotocopia_bn_simple",
        "fotocopia b/n doble faz": "fotocopia_bn_doble",
        "fotocopia color simple": "fotocopia_color_simple",
        "fotocopia color doble faz": "fotocopia_color_doble",
    }

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def get_urgent_surcharge_percent(self) -> float:
        """Get the configured urgent surcharge percentage (default 30%)."""
        row = self.connection.execute(
            "SELECT urgent_surcharge_percent FROM fotocopia_config WHERE id = 1"
        ).fetchone()
        return float(row["urgent_surcharge_percent"] if row else 30.0)

    def get_quantity_discount(self, product_type: str, quantity: int) -> float:
        """Get discount percentage for a given product type and quantity."""
        row = self.connection.execute(
            """SELECT discount_percent FROM fotocopia_quantity_discounts
               WHERE product_type = ? AND active = 1
               AND min_quantity <= ?
               AND (max_quantity IS NULL OR max_quantity >= ?)
               ORDER BY min_quantity DESC LIMIT 1""",
            (product_type, quantity, quantity)
        ).fetchone()
        return float(row["discount_percent"] if row else 0.0)

    @classmethod
    def product_code_for_title(cls, title: str) -> str | None:
        """Return the photocopy code for a displayed product title."""
        normalized = " ".join(str(title or "").casefold().split())
        return cls.PRODUCT_CODE_BY_TITLE.get(normalized)

    def calculate_for_product(
        self,
        product_type: str,
        physical_sheets: int,
        copies: int = 1,
        *,
        is_urgent: bool = False,
        manual_price: float | None = None,
    ) -> FotocopiaPriceCalculation:
        """Calculate a photocopy using its product code and active catalog price.

        This intentionally avoids generic material lookups: every photocopy
        uses ``Papel A4``, but each mode has a different unit price.
        """
        if product_type not in self.PHOTOCOPY_PRODUCT_CODES:
            raise ValueError(f"Producto de fotocopia no válido: {product_type!r}")
        return self.calculate_fotocopia(
            product_type=product_type,
            unit_price=self._get_unit_price(product_type),
            physical_sheets=physical_sheets,
            copies=copies,
            is_urgent=is_urgent,
            manual_price=manual_price,
        )

    def calculate_fotocopia(
        self,
        product_type: str,
        unit_price: float,
        physical_sheets: int,
        copies: int,
        is_urgent: bool = False,
        manual_price: float | None = None,
    ) -> FotocopiaPriceCalculation:
        """Calculate price for photocopies and photographic printing.

        Args:
            product_type: Type of photocopy (e.g., 'fotocopia_bn_simple')
            unit_price: Price per physical sheet
            physical_sheets: Number of physical sheets
            copies: Number of copies/games
            is_urgent: Whether urgent surcharge applies
            manual_price: Optional manual price override
        """
        # Special handling for photographic printing products (fixed price per unit)
        if product_type in ("impresion_fotografica_1_unidad", "folletos_fotograficos_4_unidades", "tarjetas_presentacion_fotograficas_10_unidades"):
            # For these products, unit_price is the fixed price per unit
            # physical_sheets represents quantity of units
            base_price = unit_price * physical_sheets
            total_quantity = physical_sheets
        else:
            # Standard photocopy calculation
            base_price = unit_price * physical_sheets * copies
            total_quantity = physical_sheets * copies

        # Get quantity discount (applied to total quantity)
        discount_percent = self.get_quantity_discount(product_type, total_quantity)
        discount_amount = base_price * (discount_percent / 100.0)

        # Calculate price after discount
        price_after_discount = base_price - discount_amount

        # Apply urgent surcharge (after discount)
        surcharge_percent = self.get_urgent_surcharge_percent() if is_urgent else 0.0
        surcharge_amount = price_after_discount * (surcharge_percent / 100.0)

        # Final price
        final_price = price_after_discount + surcharge_amount

        # Manual price override
        if manual_price is not None:
            final_price = manual_price

        calculation_details = {
            "product_type": product_type,
            "unit_price": unit_price,
            "physical_sheets": physical_sheets,
            "copies": copies,
            "total_quantity": total_quantity,
            "base_price": base_price,
            "discount_percent": discount_percent,
            "discount_amount": discount_amount,
            "price_after_discount": price_after_discount,
            "is_urgent": is_urgent,
            "surcharge_percent": surcharge_percent,
            "surcharge_amount": surcharge_amount,
            "manual_price": manual_price,
        }

        return FotocopiaPriceCalculation(
            base_price=round(base_price, 2),
            discount_amount=round(discount_amount, 2),
            discount_percent=round(discount_percent, 2),
            surcharge_amount=round(surcharge_amount, 2),
            surcharge_percent=round(surcharge_percent, 2),
            final_price=round(final_price, 2),
            calculation_details=calculation_details,
            is_urgent=is_urgent,
            manual_price=manual_price,
        )

    def calculate_anillado(
        self,
        sheets: int,
        quantity: int = 1,
        is_urgent: bool = False,
        manual_price: float | None = None,
    ) -> FotocopiaPriceCalculation:
        """Calculate price for binding (anillado).

        Args:
            sheets: Number of sheets in the document
            quantity: Number of binding units
            is_urgent: Whether urgent surcharge applies
            manual_price: Optional manual price override
        """
        # Determine binding size based on sheet count
        if sheets <= 50:
            product_type = "anillado_chico"
            unit_price = self._get_unit_price("anillado_chico")
        elif sheets <= 150:
            product_type = "anillado_mediano"
            unit_price = self._get_unit_price("anillado_mediano")
        elif sheets <= 300:
            product_type = "anillado_grande"
            unit_price = self._get_unit_price("anillado_grande")
        else:
            # Beyond supported range - use grande price but warn
            product_type = "anillado_grande"
            unit_price = self._get_unit_price("anillado_grande")

        # Base price (includes covers)
        base_price = unit_price * quantity

        # Get quantity discount
        discount_percent = self.get_quantity_discount(product_type, quantity)
        discount_amount = base_price * (discount_percent / 100.0)

        # Price after discount
        price_after_discount = base_price - discount_amount

        # Apply urgent surcharge
        surcharge_percent = self.get_urgent_surcharge_percent() if is_urgent else 0.0
        surcharge_amount = price_after_discount * (surcharge_percent / 100.0)

        # Final price
        final_price = price_after_discount + surcharge_amount

        # Manual price override
        if manual_price is not None:
            final_price = manual_price

        calculation_details = {
            "product_type": product_type,
            "sheets": sheets,
            "quantity": quantity,
            "unit_price": unit_price,
            "includes_covers": True,
            "base_price": base_price,
            "discount_percent": discount_percent,
            "discount_amount": discount_amount,
            "price_after_discount": price_after_discount,
            "is_urgent": is_urgent,
            "surcharge_percent": surcharge_percent,
            "surcharge_amount": surcharge_amount,
            "manual_price": manual_price,
            "beyond_limit": sheets > 300,
        }

        return FotocopiaPriceCalculation(
            base_price=round(base_price, 2),
            discount_amount=round(discount_amount, 2),
            discount_percent=round(discount_percent, 2),
            surcharge_amount=round(surcharge_amount, 2),
            surcharge_percent=round(surcharge_percent, 2),
            final_price=round(final_price, 2),
            calculation_details=calculation_details,
            is_urgent=is_urgent,
            manual_price=manual_price,
        )

    def calculate_plastificado(
        self,
        quantity: int,
        is_urgent: bool = False,
        manual_price: float | None = None,
    ) -> FotocopiaPriceCalculation:
        """Calculate price for laminating (plastificado).

        Args:
            quantity: Number of A4 units to laminate
            is_urgent: Whether urgent surcharge applies
            manual_price: Optional manual price override
        """
        product_type = "plastificado_a4"
        unit_price = self._get_unit_price(product_type)

        # Base price
        base_price = unit_price * quantity

        # Get quantity discount
        discount_percent = self.get_quantity_discount(product_type, quantity)
        discount_amount = base_price * (discount_percent / 100.0)

        # Price after discount
        price_after_discount = base_price - discount_amount

        # Apply urgent surcharge
        surcharge_percent = self.get_urgent_surcharge_percent() if is_urgent else 0.0
        surcharge_amount = price_after_discount * (surcharge_percent / 100.0)

        # Final price
        final_price = price_after_discount + surcharge_amount

        # Manual price override
        if manual_price is not None:
            final_price = manual_price

        calculation_details = {
            "product_type": product_type,
            "size": "A4",
            "quantity": quantity,
            "unit_price": unit_price,
            "base_price": base_price,
            "discount_percent": discount_percent,
            "discount_amount": discount_amount,
            "price_after_discount": price_after_discount,
            "is_urgent": is_urgent,
            "surcharge_percent": surcharge_percent,
            "surcharge_amount": surcharge_amount,
            "manual_price": manual_price,
        }

        return FotocopiaPriceCalculation(
            base_price=round(base_price, 2),
            discount_amount=round(discount_amount, 2),
            discount_percent=round(discount_percent, 2),
            surcharge_amount=round(surcharge_amount, 2),
            surcharge_percent=round(surcharge_percent, 2),
            final_price=round(final_price, 2),
            calculation_details=calculation_details,
            is_urgent=is_urgent,
            manual_price=manual_price,
        )

    def _get_unit_price(self, product_code: str) -> float:
        """Get unit price from price_rules for a product code."""
        row = self.connection.execute(
            """SELECT pr.price FROM price_rules pr
               JOIN products p ON pr.product_id = p.id
               WHERE p.code = ? AND pr.active = 1
               ORDER BY pr.min_quantity ASC LIMIT 1""",
            (product_code,)
        ).fetchone()
        if row:
            return float(row["price"])

        # Fallback: try to get from catalog_key directly (catalog_key matches product_code)
        row = self.connection.execute(
            """SELECT price FROM price_rules
               WHERE catalog_key = ? AND active = 1
               LIMIT 1""",
            (product_code,)
        ).fetchone()
        return float(row["price"] if row else 0.0)

    def save_price_snapshot(
        self,
        order_job_id: int,
        calculation: FotocopiaPriceCalculation,
    ) -> None:
        """Save price calculation snapshot to order_jobs."""
        now = datetime.now().isoformat(timespec="seconds")

        self.connection.execute(
            """UPDATE order_jobs
               SET base_price = ?,
                   discount_amount = ?,
                   surcharge_amount = ?,
                   final_price = ?,
                   is_urgent = ?,
                   manual_price = ?,
                   price_calculation_json = ?,
                   updated_at = ?
               WHERE id = ?""",
            (
                calculation.base_price,
                calculation.discount_amount,
                calculation.surcharge_amount,
                calculation.final_price,
                1 if calculation.is_urgent else 0,
                calculation.manual_price,
                json.dumps(calculation.calculation_details),
                now,
                order_job_id,
            )
        )
