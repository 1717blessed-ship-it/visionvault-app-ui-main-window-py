from __future__ import annotations

from ..models.cost_rule import CostRule
from ..repositories.cost_rule_repository import CostRuleRepository
from .cost_calculator import CostCalculator


class CostRuleService:
    """Servicio de alto nivel para aplicar reglas de costo."""

    def __init__(self, repository: CostRuleRepository | None = None) -> None:
        self.repository = repository or CostRuleRepository()

    def add_rule(self, rule: CostRule) -> CostRule:
        return self.repository.add(rule)

    def get_rule(self, rule_id: int) -> CostRule | None:
        return self.repository.get(rule_id)

    def list_rules(self) -> list[CostRule]:
        return self.repository.list()

    def calculate_for_context(self, context: dict, quantity: int = 1, subtotal: float = 0.0) -> list[dict]:
        results = []
        for rule in self.list_rules():
            if not rule.active:
                continue
            if rule.product_type and context.get("material") and rule.product_type.lower() != str(context.get("material")).lower():
                continue
            calculation = CostCalculator.calculate(
                rule,
                context=context,
                sale_price=float(context.get("sale_price") or subtotal or 0),
                quantity=quantity,
            )
            if calculation.cost_total > 0:
                results.append({"rule": rule.name, "cost_total": calculation.cost_total, "components": calculation.components})
        return results
