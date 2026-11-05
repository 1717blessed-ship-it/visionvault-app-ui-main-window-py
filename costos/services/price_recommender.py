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
        return CostCalculator.recommended_price(
            rule,
            quantity=quantity,
            target_margin=margin_percent,
        )
