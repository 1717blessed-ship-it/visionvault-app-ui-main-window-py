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


@dataclass(slots=True)
class ProductivePlanchaAnalysis:
    """Desglose productivo/comercial para una plancha A4.

    Es un contrato de cálculo: no persiste ni decide cómo se muestra en UI.
    """

    quantity: int = 1
    unique_designs: int = 1
    production_mode: str = "individual"
    classification: str = "estandar"
    estimated_design_minutes: float = 0.0
    estimated_print_minutes: float = 0.0
    estimated_cut_minutes: float = 0.0
    estimated_total_minutes: float = 0.0
    base_price: float = 0.0
    base_price_source: str = ""
    base_price_rule_id: int | None = None
    base_price_version: str = ""
    design_surcharge: float = 0.0
    productive_surcharge: float = 0.0
    additional_services: float = 0.0
    authorized_discount: float = 0.0
    suggested_price: float = 0.0
    applied_price: float | None = None
    manual_price: float | None = None
    price_source: str = "suggested"
    productive_cost: float = 0.0
    raw_material_cost: float = 0.0
    labor_cost: float = 0.0
    overhead_cost: float = 0.0
    internal_incident_cost: float = 0.0
    commercial_cost: float = 0.0
    final_cost: float = 0.0
    productive_profit: float = 0.0
    final_profit: float = 0.0
    productive_margin_percentage: float = 0.0
    final_margin_percentage: float = 0.0
    applied_productive_profit: float | None = None
    applied_final_profit: float | None = None
    applied_productive_margin_percentage: float | None = None
    applied_final_margin_percentage: float | None = None
    standard_productive_cost: float = 0.0
    quantity_adjusted_productive_cost: float = 0.0
    estimated_batch_savings: float = 0.0
    markup_percentage: float = 0.0
    profitability_status: str = "loss"
    warnings: list[str] = field(default_factory=list)
