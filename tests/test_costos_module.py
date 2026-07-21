import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from costos.models.cost_analysis_result import CostAnalysisResult
from costos.models.cost_component import CostComponent
from costos.models.cost_condition import CostCondition
from costos.models.cost_rule import CostRule
from costos.repositories.cost_rule_repository import CostRuleRepository
from costos.services.cost_calculator import CostCalculator
from costos.services.cost_rule_service import CostRuleService
from costos.validators.cost_rule_validator import CostRuleValidator


def test_calculator_returns_typed_financial_metrics_and_status():
    rule = CostRule(name="Regla de ejemplo", minimum_margin=15.0)
    rule.add_component(CostComponent(name="Materia prima", code="mp", value_type="percentage", value=10.0))
    rule.add_component(CostComponent(name="Mano de obra", code="mo", value_type="per_unit", value=2.0))
    rule.add_component(CostComponent(name="Publicidad", code="ads", value_type="fixed", value=4.0))

    result = CostCalculator.calculate(rule, sale_price=100.0, quantity=3, hours=2.0, surface=4.0)

    assert isinstance(result, CostAnalysisResult)
    assert result.cost_total == 20.0
    assert result.gross_profit == 80.0
    assert result.margin_percentage == 80.0
    assert result.markup_percentage == 400.0
    assert result.profitability_status == "profitable"
    assert any(component.code == "mp" and component.amount == 10.0 for component in result.components)
    assert any(component.code == "mo" and component.amount == 6.0 for component in result.components)
    assert any(component.code == "ads" and component.amount == 4.0 for component in result.components)


def test_recommended_price_uses_target_margin_formula():
    rule = CostRule(name="Precio sugerido")
    rule.add_component(CostComponent(name="Costo fijo", code="fixed", value_type="fixed", value=20.0))

    recommended = CostCalculator.recommended_price(rule, quantity=1, hours=1.0, surface=1.0, target_margin=20.0)

    assert recommended == 25.0


def test_zero_cost_total_returns_no_markup_and_explicit_status():
    rule = CostRule(name="Sin costos", minimum_margin=15.0)

    result = CostCalculator.calculate(rule, sale_price=100.0, quantity=1, hours=1.0, surface=1.0)

    assert result.cost_total == 0.0
    assert result.gross_profit == 100.0
    assert result.margin_percentage == 100.0
    assert result.markup_percentage == 0.0
    assert result.profitability_status == "no_costs"


def test_repository_and_service_work_together():
    repo = CostRuleRepository()
    service = CostRuleService(repo)
    rule = CostRule(name="Regla de servicio", product_type="Vinilo")
    rule.add_component(CostComponent(name="Carga", code="cf", value_type="fixed", value=15.0))
    service.add_rule(rule)

    assert service.get_rule(1).name == "Regla de servicio"
    assert service.list_rules()[0].product_type == "Vinilo"


def test_validator_detects_missing_name_and_invalid_component_type():
    rule = CostRule(name="")
    rule.add_component(CostComponent(name="", code="empty", value_type="unsupported", value=5.0))

    errors = CostRuleValidator.validate(rule)

    assert "El nombre de la regla es obligatorio" in errors
    assert "El tipo de cálculo no es válido" in errors
