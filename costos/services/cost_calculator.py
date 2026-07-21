from __future__ import annotations

from ..models.cost_analysis_result import CostAnalysisResult, CostComponentResult
from ..models.cost_component import CostComponent
from ..models.cost_rule import CostRule
from ..models.cost_condition import CostCondition
from .condition_evaluator import ConditionEvaluator


class CostCalculator:
    """Calcula métricas financieras para una regla de costo de forma independiente de la interfaz."""

    @staticmethod
    def calculate(rule: CostRule, sale_price: float = 0.0, quantity: int = 1, hours: float = 0.0, surface: float = 0.0, suggested_price: float | None = None) -> CostAnalysisResult:
        if not rule.active:
            return CostAnalysisResult(
                rule_name=rule.name,
                product_type=rule.product_type,
                suggested_price=float(suggested_price or 0.0),
                profitability_status="loss",
                warnings=["La regla está inactiva"],
            )

        sale_price = max(float(sale_price or 0), 0.0)
        quantity = max(int(quantity or 1), 1)
        hours = max(float(hours or 0), 0.0)
        surface = max(float(surface or 0), 0.0)
        suggested_price = float(suggested_price or sale_price or 0.0)

        components: list[CostComponentResult] = []
        total = 0.0
        for component in rule.components:
            if not component.enabled:
                continue
            amount = component.evaluate(sale_price=sale_price, quantity=quantity, hours=hours, surface=surface)
            total += amount
            components.append(
                CostComponentResult(
                    name=component.name,
                    code=component.code or component.name,
                    value_type=component.value_type,
                    value=component.value,
                    amount=round(amount, 2),
                )
            )

        gross_profit = round(suggested_price - total, 2)
        margin_percentage = round((gross_profit / suggested_price * 100) if suggested_price else 0.0, 2)
        markup_percentage = round((gross_profit / total * 100) if total > 0 else 0.0, 2)

        profitability_status = "loss"
        warnings: list[str] = []
        if total <= 0:
            profitability_status = "no_costs" if gross_profit > 0 else "loss"
            if total <= 0:
                warnings.append("Sin costos configurados")
        elif margin_percentage >= rule.minimum_margin:
            profitability_status = "profitable"
        elif margin_percentage > 0:
            profitability_status = "margin_low"
            warnings.append("Margen por debajo del mínimo esperado")
        else:
            warnings.append("El precio no cubre los costos")

        return CostAnalysisResult(
            rule_name=rule.name,
            rule_id=rule.id,
            product_type=rule.product_type,
            suggested_price=suggested_price,
            cost_total=round(total, 2),
            gross_profit=gross_profit,
            margin_percentage=margin_percentage,
            markup_percentage=markup_percentage,
            profitability_status=profitability_status,
            warnings=warnings,
            components=components,
        )

    @staticmethod
    def recommended_price(rule: CostRule, quantity: int = 1, hours: float = 0.0, surface: float = 0.0, target_margin: float = 20.0) -> float:
        cost_total = CostCalculator.calculate(rule, sale_price=0.0, quantity=quantity, hours=hours, surface=surface).cost_total
        if cost_total <= 0:
            return 0.0
        return round(float(cost_total) / (1 - (target_margin / 100.0)), 2)
