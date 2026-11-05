"""Service for linking Fotocopias y terminaciones to stock materials.

This service prepares the infrastructure for stock consumption recipes without
automatically deducting stock. Consumption recipes can be configured later.
"""

from __future__ import annotations

import sqlite3
from typing import Any


class FotocopiaStockService:
    """Manages stock linkage for Fotocopias y terminaciones products."""

    # Material codes for fotocopia products
    MATERIALS = {
        "papel_a4": "Papel A4",
        "tinta_negra": "Tinta negra",
        "tinta_color": "Tintas color",
        "espiral_chico": "Espiral Chico",
        "espiral_mediano": "Espiral Mediano",
        "espiral_grande": "Espiral Grande",
        "tapa_transparente": "Tapa transparente",
        "contratapa": "Contratapa",
        "lamina_a4": "Lámina A4",
        "sobre_plastificado_a4": "Sobre plastificado A4",
        "papel_fotografico_a4": "Papel fotográfico A4",
    }

    # Default consumption recipes (can be overridden via configuration)
    DEFAULT_RECIPES = {
        "fotocopia_bn_simple": {
            "papel_a4": 1,  # 1 sheet per photocopy
            "tinta_negra": 0.01,  # Minimal ink consumption
        },
        "fotocopia_bn_doble": {
            "papel_a4": 1,
            "tinta_negra": 0.02,  # More ink for double-sided
        },
        "fotocopia_color_simple": {
            "papel_a4": 1,
            "tinta_color": 0.02,
        },
        "fotocopia_color_doble": {
            "papel_a4": 1,
            "tinta_color": 0.04,
        },
        "anillado_chico": {
            "espiral_chico": 1,
            "tapa_transparente": 1,
            "contratapa": 1,
        },
        "anillado_mediano": {
            "espiral_mediano": 1,
            "tapa_transparente": 1,
            "contratapa": 1,
        },
        "anillado_grande": {
            "espiral_grande": 1,
            "tapa_transparente": 1,
            "contratapa": 1,
        },
        "plastificado_a4": {
            "lamina_a4": 1,
        },
        "impresion_fotografica_1_unidad": {
            "papel_fotografico_a4": 1,
        },
        "folletos_fotograficos_4_unidades": {
            "papel_fotografico_a4": 1,
        },
        "tarjetas_presentacion_fotograficas_10_unidades": {
            "papel_fotografico_a4": 1,
        },
    }

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def ensure_materials_exist(self) -> int:
        """Ensure all fotocopia materials exist in the materials table.

        Returns the number of materials created.
        """
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")

        created = 0
        for code, name in self.MATERIALS.items():
            # Check if material exists
            existing = self.connection.execute(
                "SELECT id FROM materials WHERE code = ?", (code,)
            ).fetchone()

            if not existing:
                self.connection.execute(
                    """INSERT INTO materials(code, name, unit, active, created_at, updated_at)
                       VALUES(?, ?, 'unidad', 1, ?, ?)""",
                    (code, name, now, now)
                )
                created += 1

        self.connection.commit()
        return created

    def get_consumption_recipe(self, product_type: str) -> dict[str, float]:
        """Get the consumption recipe for a product type.

        Returns a dictionary mapping material codes to quantities.
        """
        # First check if there's a custom recipe in the database
        custom_recipe = self.connection.execute(
            """SELECT material_code, quantity FROM fotocopia_consumption_recipes
               WHERE product_type = ? AND active = 1""",
            (product_type,)
        ).fetchall()

        if custom_recipe:
            return {row["material_code"]: row["quantity"] for row in custom_recipe}

        # Fall back to default recipe
        return self.DEFAULT_RECIPES.get(product_type, {})

    def calculate_material_requirements(
        self,
        product_type: str,
        quantity: int,
        **kwargs: Any,
    ) -> dict[str, float]:
        """Calculate material requirements for a job.

        Args:
            product_type: Type of fotocopia product
            quantity: Quantity of units
            **kwargs: Additional parameters (e.g., sheets for anillado)

        Returns a dictionary mapping material codes to required quantities.
        """
        recipe = self.get_consumption_recipe(product_type)
        requirements = {}

        for material_code, base_quantity in recipe.items():
            # Adjust quantity based on product-specific logic
            if product_type.startswith("anillado"):
                # For anillado, quantity is the number of bindings
                required = base_quantity * quantity
            elif product_type.startswith("fotocopia"):
                # For photocopies, quantity is sheets * copies
                physical_sheets = kwargs.get("physical_sheets", 1)
                copies = kwargs.get("copies", 1)
                total_sheets = physical_sheets * copies
                required = base_quantity * total_sheets
            else:
                # Default: simple multiplication
                required = base_quantity * quantity

            requirements[material_code] = required

        return requirements

    def check_material_availability(
        self,
        product_type: str,
        quantity: int,
        **kwargs: Any,
    ) -> dict[str, dict[str, Any]]:
        """Check if required materials are available in stock.

        Returns a dictionary with material availability status.
        """
        requirements = self.calculate_material_requirements(product_type, quantity, **kwargs)
        availability = {}

        for material_code, required_qty in requirements.items():
            # Get current stock
            row = self.connection.execute(
                """SELECT current_stock FROM material_stock
                   WHERE material_id = (SELECT id FROM materials WHERE code = ?)""",
                (material_code,)
            ).fetchone()

            current_stock = row["current_stock"] if row else 0

            availability[material_code] = {
                "required": required_qty,
                "available": current_stock,
                "sufficient": current_stock >= required_qty,
                "shortage": max(0, required_qty - current_stock),
            }

        return availability

    def save_consumption_recipe(
        self,
        product_type: str,
        recipe: dict[str, float],
    ) -> None:
        """Save a custom consumption recipe for a product type.

        Args:
            product_type: Type of fotocopia product
            recipe: Dictionary mapping material codes to quantities
        """
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")

        # Delete existing recipe for this product
        self.connection.execute(
            "DELETE FROM fotocopia_consumption_recipes WHERE product_type = ?",
            (product_type,)
        )

        # Insert new recipe
        for material_code, quantity in recipe.items():
            self.connection.execute(
                """INSERT INTO fotocopia_consumption_recipes
                   (product_type, material_code, quantity, active, created_at, updated_at)
                   VALUES(?, ?, ?, 1, ?, ?)""",
                (product_type, material_code, quantity, now, now)
            )

        self.connection.commit()

    def create_consumption_recipes_table(self) -> None:
        """Create the fotocopia_consumption_recipes table if it doesn't exist."""
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS fotocopia_consumption_recipes (
                id INTEGER PRIMARY KEY,
                product_type TEXT NOT NULL,
                material_code TEXT NOT NULL,
                quantity REAL NOT NULL,
                active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(product_type, material_code)
            )"""
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_fotocopia_recipes_product ON fotocopia_consumption_recipes(product_type)"
        )
        self.connection.commit()
