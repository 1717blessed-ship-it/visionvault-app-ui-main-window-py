from __future__ import annotations

from ..models.cost_component import CostComponent
from ..models.cost_rule import CostRule
from .cost_calculator import CostCalculator


class PriceRecommender:
    """Sugiere un precio de venta a partir de reglas de costo."""

    @staticmethod
    def recommend(rule: CostRule, quantity: int = 1, subtotal: float = 0.0, margin_percent: float = 20.0) -> float:
        if not rule.active:
            return 0.0
        calculation = CostCalculator.calculate(rule, quantity=quantity, subtotal=subtotal)
        cost_total = calculation["cost_total"]
        if cost_total <= 0:
            return 0.0
        margin_factor = 1 + (margin_percent / 100.0)
        return round(cost_total * margin_factor, 2)
