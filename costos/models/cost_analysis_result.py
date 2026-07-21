from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class CostComponentResult:
    """Resultado calculado para un componente específico de una regla de costo."""

    name: str = ""
    code: str = ""
    value_type: str = "percentage"
    value: float = 0.0
    amount: float = 0.0


@dataclass(slots=True)
class CostAnalysisResult:
    """Contrato unificado para cualquier análisis de costo, precio o rentabilidad."""

    rule_name: str = ""
    rule_id: int | None = None
    product_type: str = ""
    suggested_price: float = 0.0
    cost_total: float = 0.0
    gross_profit: float = 0.0
    margin_percentage: float = 0.0
    markup_percentage: float = 0.0
    profitability_status: str = "loss"
    warnings: list[str] = field(default_factory=list)
    components: list[CostComponentResult] = field(default_factory=list)
