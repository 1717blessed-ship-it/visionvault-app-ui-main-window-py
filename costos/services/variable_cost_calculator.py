from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..models.variable_cost_component import VariableCostComponent
from ..models.variable_cost_model import VariableCostModel


@dataclass(slots=True)
class VariableCostSummary:
    """Resultado del cálculo de costo variable para un modelo."""

    model_id: int | None = None
    model_name: str = ""
    product_key: str = ""
    product_name: str = ""
    category: str = ""
    unit_variable_cost: Decimal = Decimal("0")
    sale_price: Decimal = Decimal("0")
    contribution_margin: Decimal = Decimal("0")
    contribution_pct: Decimal = Decimal("0")
    component_count: int = 0
    active: bool = True
    outdated: bool = False
    warnings: list[str] = field(default_factory=list)


class VariableCostCalculator:
    """Calcula el costo variable unitario de un modelo de forma independiente de la UI.

    No mezcla costos fijos. No modifica la base de datos.
    """

    @staticmethod
    def calculate(
        model: VariableCostModel,
        sale_price: Decimal = Decimal("0"),
    ) -> VariableCostSummary:
        """Calcula el resumen completo de un modelo de costo variable.

        Args:
            model: Modelo con componentes cargados.
            sale_price: Precio de venta para la simulación (no modifica price_rules).

        Returns:
            VariableCostSummary con todos los valores calculados.
        """
        warnings: list[str] = []

        if not model.active:
            warnings.append("El modelo está inactivo")

        if not model.components:
            warnings.append("Sin componentes configurados")

        unit_cost = model.recalculate_all(sale_price=sale_price)
        sale_price = max(sale_price, Decimal("0"))

        margin = sale_price - unit_cost if sale_price > 0 else Decimal("0")
        margin_pct = (margin / sale_price * Decimal("100")).quantize(Decimal("0.01")) if sale_price > 0 else Decimal("0")

        if sale_price > 0 and unit_cost > sale_price:
            warnings.append("El costo variable supera el precio de venta")

        active_count = sum(1 for c in model.components if c.active)

        return VariableCostSummary(
            model_id=model.id,
            model_name=model.name,
            product_key=model.product_key,
            product_name=model.product_name,
            category=model.category,
            unit_variable_cost=unit_cost,
            sale_price=sale_price,
            contribution_margin=margin,
            contribution_pct=margin_pct,
            component_count=active_count,
            active=model.active,
            outdated=model.outdated,
            warnings=warnings,
        )

    @staticmethod
    def calculate_component_amount(
        component: VariableCostComponent,
        *,
        sale_price: Decimal = Decimal("0"),
        raw_material_subtotal: Decimal = Decimal("0"),
        labor_subtotal: Decimal = Decimal("0"),
        previous_components_total: Decimal = Decimal("0"),
        selected_subtotal: Decimal = Decimal("0"),
    ) -> Decimal:
        """Calcula el importe de un componente individual.

        Útil para la UI cuando cambia un solo valor y se necesita
        recalcular solo esa fila.
        """
        return component.recalculate(
            sale_price=sale_price,
            raw_material_subtotal=raw_material_subtotal,
            labor_subtotal=labor_subtotal,
            previous_components_total=previous_components_total,
            selected_subtotal=selected_subtotal,
        )
