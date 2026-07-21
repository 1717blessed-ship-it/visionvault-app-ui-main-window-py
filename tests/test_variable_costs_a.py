"""Pruebas unitarias de la Etapa A: modelos, calculador y validador de costos variables."""

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from costos.models.calculation_mode import (
    CalculationMode,
    PercentageBase,
    CALCULATION_MODE_LABELS,
    DIRECT_CALCULATION_MODES,
)
from costos.models.variable_cost_component import VariableCostComponent
from costos.models.variable_cost_model import VariableCostModel, build_product_key
from costos.services.variable_cost_calculator import VariableCostCalculator, VariableCostSummary
from costos.validators.variable_cost_validator import VariableCostValidator


# ---------------------------------------------------------------------------
# build_product_key
# ---------------------------------------------------------------------------

class TestBuildProductKey:
    def test_basic_combination(self):
        key = build_product_key("Plancha sublimada", "Vinilo sublimable", "A4")
        assert key == "plancha_sublimada|vinilo_sublimable|a4"

    def test_with_variant(self):
        key = build_product_key("Plancha", "Vinilo", "A4", "22x30")
        assert key == "plancha|vinilo|a4|22x30"

    def test_normalizes_whitespace_and_case(self):
        key = build_product_key("  PLANCHA  SUB ", " VINILO ", " a4 ")
        assert key == "plancha_sub|vinilo|a4"

    def test_empty_fields(self):
        key = build_product_key("", "", "")
        assert key == "||"


# ---------------------------------------------------------------------------
# CalculationMode
# ---------------------------------------------------------------------------

class TestCalculationMode:
    def test_all_modes_have_labels(self):
        for mode in CalculationMode:
            assert mode.value in CALCULATION_MODE_LABELS

    def test_direct_modes_do_not_include_percentage(self):
        assert CalculationMode.PERCENTAGE not in DIRECT_CALCULATION_MODES

    def test_all_direct_modes_are_in_enum(self):
        for mode in DIRECT_CALCULATION_MODES:
            assert mode in CalculationMode


# ---------------------------------------------------------------------------
# VariableCostComponent
# ---------------------------------------------------------------------------

class TestVariableCostComponent:
    def test_recalculate_per_unit_without_waste(self):
        comp = VariableCostComponent(
            name="Vinilo",
            calculation_mode=CalculationMode.PER_UNIT,
            quantity=Decimal("3"),
            unit_value=Decimal("500"),
            waste_pct=Decimal("0"),
        )
        result = comp.recalculate()
        assert result == Decimal("1500.00")

    def test_recalculate_per_unit_with_waste(self):
        comp = VariableCostComponent(
            name="Vinilo",
            calculation_mode=CalculationMode.PER_UNIT,
            quantity=Decimal("3"),
            unit_value=Decimal("500"),
            waste_pct=Decimal("10"),
        )
        result = comp.recalculate()
        # 3 * 500 * 1.10 = 1650
        assert result == Decimal("1650.00")

    def test_recalculate_percentage_on_sale_price(self):
        comp = VariableCostComponent(
            name="Comisión",
            calculation_mode=CalculationMode.PERCENTAGE,
            unit_value=Decimal("15"),
            percentage_base=PercentageBase.SALE_PRICE,
        )
        result = comp.recalculate(sale_price=Decimal("5000"))
        # 5000 * 15 / 100 = 750
        assert result == Decimal("750.00")

    def test_recalculate_percentage_on_raw_material(self):
        comp = VariableCostComponent(
            name="Impuesto MP",
            calculation_mode=CalculationMode.PERCENTAGE,
            unit_value=Decimal("10"),
            percentage_base=PercentageBase.RAW_MATERIAL,
        )
        result = comp.recalculate(raw_material_subtotal=Decimal("2000"))
        assert result == Decimal("200.00")

    def test_recalculate_percentage_on_previous_components(self):
        comp = VariableCostComponent(
            name="Gastos generales",
            calculation_mode=CalculationMode.PERCENTAGE,
            unit_value=Decimal("20"),
            percentage_base=PercentageBase.PREVIOUS_COMPONENTS,
        )
        result = comp.recalculate(previous_components_total=Decimal("1000"))
        assert result == Decimal("200.00")

    def test_inactive_component_returns_zero(self):
        comp = VariableCostComponent(
            name="Inactivo",
            calculation_mode=CalculationMode.PER_UNIT,
            quantity=Decimal("5"),
            unit_value=Decimal("100"),
            active=False,
        )
        result = comp.recalculate()
        assert result == Decimal("0")

    def test_zero_quantity(self):
        comp = VariableCostComponent(
            name="Zero qty",
            calculation_mode=CalculationMode.PER_UNIT,
            quantity=Decimal("0"),
            unit_value=Decimal("100"),
        )
        result = comp.recalculate()
        assert result == Decimal("0.00")

    def test_fixed_production_ignores_quantity(self):
        comp = VariableCostComponent(
            name="Fijo",
            calculation_mode=CalculationMode.FIXED_PRODUCTION,
            quantity=Decimal("10"),
            unit_value=Decimal("500"),
        )
        result = comp.recalculate()
        # Fixed: qty * unit_value = 10 * 500 = 5000
        assert result == Decimal("5000.00")

    def test_serialization_round_trip(self):
        comp = VariableCostComponent(
            name="Test",
            calculation_mode=CalculationMode.PER_SHEET,
            quantity=Decimal("2.5"),
            unit_value=Decimal("120.50"),
            waste_pct=Decimal("5"),
            unit="hoja",
        )
        comp.recalculate()
        data = comp.to_dict()
        restored = VariableCostComponent.from_dict(data)
        assert restored.name == "Test"
        assert restored.calculation_mode == CalculationMode.PER_SHEET
        assert restored.quantity == Decimal("2.5")
        assert restored.unit_value == Decimal("120.50")
        assert restored.waste_pct == Decimal("5")
        assert restored.calculated_amount == comp.calculated_amount

    def test_quantize_rounds_to_two_decimals(self):
        comp = VariableCostComponent(
            name="Tinta",
            calculation_mode=CalculationMode.PER_MILLILITER,
            quantity=Decimal("3"),
            unit_value=Decimal("100.333"),
            waste_pct=Decimal("0"),
        )
        result = comp.recalculate()
        assert result == Decimal("301.00")


# ---------------------------------------------------------------------------
# VariableCostModel
# ---------------------------------------------------------------------------

class TestVariableCostModel:
    def _make_model(self) -> VariableCostModel:
        return VariableCostModel(
            name="Modelo A",
            product_key="plancha|vinilo|a4",
            product_name="Vinilo A4",
            category="Plancha",
            components=[
                VariableCostComponent(
                    name="Vinilo",
                    calculation_mode=CalculationMode.PER_UNIT,
                    quantity=Decimal("1"),
                    unit_value=Decimal("500"),
                    waste_pct=Decimal("0"),
                    order=1,
                ),
                VariableCostComponent(
                    name="Tinta",
                    calculation_mode=CalculationMode.PER_SHEET,
                    quantity=Decimal("2"),
                    unit_value=Decimal("100"),
                    waste_pct=Decimal("5"),
                    order=2,
                ),
            ],
        )

    def test_total_variable_cost(self):
        model = self._make_model()
        model.recalculate_all()
        # Vinilo: 1 * 500 = 500
        # Tinta: 2 * 100 * 1.05 = 210
        assert model.total_variable_cost() == Decimal("710.00")

    def test_recalculate_all_with_percentage(self):
        model = VariableCostModel(
            name="Con porcentaje",
            product_key="test",
            components=[
                VariableCostComponent(
                    name="Vinilo",
                    calculation_mode=CalculationMode.PER_UNIT,
                    quantity=Decimal("1"),
                    unit_value=Decimal("1000"),
                    order=1,
                ),
                VariableCostComponent(
                    name="Comisión",
                    calculation_mode=CalculationMode.PERCENTAGE,
                    unit_value=Decimal("15"),
                    percentage_base=PercentageBase.SALE_PRICE,
                    order=2,
                ),
            ],
        )
        total = model.recalculate_all(sale_price=Decimal("5000"))
        # Vinilo: 1000, Comisión: 5000 * 15% = 750
        assert total == Decimal("1750.00")

    def test_percentage_previous_components_accumulates(self):
        model = VariableCostModel(
            name="Acumulativo",
            product_key="test",
            components=[
                VariableCostComponent(
                    name="MP",
                    calculation_mode=CalculationMode.PER_UNIT,
                    quantity=Decimal("1"),
                    unit_value=Decimal("1000"),
                    order=1,
                ),
                VariableCostComponent(
                    name="MO",
                    calculation_mode=CalculationMode.PER_UNIT,
                    quantity=Decimal("1"),
                    unit_value=Decimal("500"),
                    order=2,
                ),
                VariableCostComponent(
                    name="Gastos sobre anteriores",
                    calculation_mode=CalculationMode.PERCENTAGE,
                    unit_value=Decimal("10"),
                    percentage_base=PercentageBase.PREVIOUS_COMPONENTS,
                    order=3,
                ),
            ],
        )
        total = model.recalculate_all()
        # MP: 1000, MO: 500, Gastos: (1000+500) * 10% = 150
        assert total == Decimal("1650.00")

    def test_empty_model_returns_zero(self):
        model = VariableCostModel(name="Vacío", product_key="test")
        total = model.recalculate_all()
        assert total == Decimal("0")

    def test_inactive_components_excluded(self):
        model = VariableCostModel(
            name="Con inactivo",
            product_key="test",
            components=[
                VariableCostComponent(
                    name="Activo",
                    calculation_mode=CalculationMode.PER_UNIT,
                    quantity=Decimal("1"),
                    unit_value=Decimal("100"),
                    active=True,
                    order=1,
                ),
                VariableCostComponent(
                    name="Inactivo",
                    calculation_mode=CalculationMode.PER_UNIT,
                    quantity=Decimal("1"),
                    unit_value=Decimal("999"),
                    active=False,
                    order=2,
                ),
            ],
        )
        total = model.recalculate_all()
        assert total == Decimal("100.00")

    def test_component_by_id(self):
        model = self._make_model()
        model.components[0].id = 42
        assert model.component_by_id(42) is model.components[0]
        assert model.component_by_id(999) is None

    def test_mark_outdated(self):
        model = VariableCostModel(
            name="Test",
            product_key="test",
            components=[
                VariableCostComponent(
                    name="Vinculado",
                    source_id="pr_123",
                    manually_overridden=False,
                ),
            ],
        )
        model.mark_outdated("pr_123")
        assert model.outdated is True

    def test_mark_outdated_ignores_manual_override(self):
        model = VariableCostModel(
            name="Test",
            product_key="test",
            components=[
                VariableCostComponent(
                    name="Manual",
                    source_id="pr_123",
                    manually_overridden=True,
                ),
            ],
        )
        model.mark_outdated("pr_123")
        assert model.outdated is False

    def test_serialization_round_trip(self):
        model = self._make_model()
        model.id = 1
        model.recalculate_all()
        data = model.to_dict()
        restored = VariableCostModel.from_dict(data, model.components)
        assert restored.name == "Modelo A"
        assert restored.product_key == "plancha|vinilo|a4"
        assert len(restored.components) == 2
        assert restored.total_variable_cost() == model.total_variable_cost()


# ---------------------------------------------------------------------------
# VariableCostCalculator
# ---------------------------------------------------------------------------

class TestVariableCostCalculator:
    def test_calculate_summary(self):
        model = VariableCostModel(
            name="Modelo Test",
            product_key="test|vinilo|a4",
            product_name="Vinilo A4",
            category="Test",
            active=True,
            components=[
                VariableCostComponent(
                    name="Vinilo",
                    calculation_mode=CalculationMode.PER_UNIT,
                    quantity=Decimal("1"),
                    unit_value=Decimal("500"),
                    order=1,
                ),
                VariableCostComponent(
                    name="Comisión",
                    calculation_mode=CalculationMode.PERCENTAGE,
                    unit_value=Decimal("10"),
                    percentage_base=PercentageBase.SALE_PRICE,
                    order=2,
                ),
            ],
        )
        summary = VariableCostCalculator.calculate(model, sale_price=Decimal("5000"))
        # Vinilo: 500, Comisión: 5000*10% = 500, Total: 1000
        assert summary.unit_variable_cost == Decimal("1000.00")
        assert summary.sale_price == Decimal("5000")
        assert summary.contribution_margin == Decimal("4000.00")
        assert summary.contribution_pct == Decimal("80.00")
        assert summary.component_count == 2
        assert summary.active is True

    def test_calculate_inactive_model(self):
        model = VariableCostModel(name="Inactivo", product_key="test", active=False)
        summary = VariableCostCalculator.calculate(model)
        assert summary.active is False
        assert any("inactivo" in w.lower() for w in summary.warnings)

    def test_calculate_empty_model(self):
        model = VariableCostModel(name="Vacío", product_key="test")
        summary = VariableCostCalculator.calculate(model)
        assert summary.unit_variable_cost == Decimal("0")
        assert any("sin componentes" in w.lower() for w in summary.warnings)

    def test_calculate_cost_exceeds_price_warning(self):
        model = VariableCostModel(
            name="Caro",
            product_key="test",
            components=[
                VariableCostComponent(
                    name="Caro",
                    calculation_mode=CalculationMode.PER_UNIT,
                    quantity=Decimal("1"),
                    unit_value=Decimal("5000"),
                    order=1,
                ),
            ],
        )
        summary = VariableCostCalculator.calculate(model, sale_price=Decimal("2000"))
        assert summary.unit_variable_cost == Decimal("5000.00")
        assert summary.contribution_margin < 0
        assert any("supera" in w.lower() for w in summary.warnings)

    def test_summary_is_instance(self):
        model = VariableCostModel(name="Test", product_key="test")
        summary = VariableCostCalculator.calculate(model)
        assert isinstance(summary, VariableCostSummary)

    def test_zero_sale_price(self):
        model = VariableCostModel(
            name="Test",
            product_key="test",
            components=[
                VariableCostComponent(
                    name="Item",
                    calculation_mode=CalculationMode.PER_UNIT,
                    quantity=Decimal("1"),
                    unit_value=Decimal("100"),
                    order=1,
                ),
            ],
        )
        summary = VariableCostCalculator.calculate(model, sale_price=Decimal("0"))
        assert summary.contribution_margin == Decimal("0")
        assert summary.contribution_pct == Decimal("0")


# ---------------------------------------------------------------------------
# VariableCostValidator
# ---------------------------------------------------------------------------

class TestVariableCostValidator:
    def _valid_model(self) -> VariableCostModel:
        return VariableCostModel(
            name="Modelo válido",
            product_key="plancha|vinilo|a4",
            product_name="Vinilo A4",
            category="Plancha",
            components=[
                VariableCostComponent(
                    name="Vinilo",
                    calculation_mode=CalculationMode.PER_UNIT,
                    quantity=Decimal("1"),
                    unit_value=Decimal("500"),
                    unit="unidad",
                    order=1,
                ),
            ],
        )

    def test_valid_model_passes(self):
        model = self._valid_model()
        errors = VariableCostValidator.validate_model(model)
        assert errors == []

    def test_missing_name(self):
        model = self._valid_model()
        model.name = ""
        errors = VariableCostValidator.validate_model(model)
        assert any("nombre" in e.lower() for e in errors)

    def test_missing_product_key(self):
        model = self._valid_model()
        model.product_key = ""
        model.product_name = ""
        errors = VariableCostValidator.validate_model(model)
        assert any("producto" in e.lower() for e in errors)

    def test_no_components(self):
        model = self._valid_model()
        model.components = []
        errors = VariableCostValidator.validate_model(model)
        assert any("componente" in e.lower() for e in errors)

    def test_duplicate_active_model_rejected(self):
        model = self._valid_model()
        existing = {"plancha|vinilo|a4"}
        errors = VariableCostValidator.validate_model(model, existing_active_keys=existing)
        assert any("ya existe" in e.lower() for e in errors)

    def test_inactive_model_not_rejected_on_duplicate(self):
        model = self._valid_model()
        model.active = False
        existing = {"plancha|vinilo|a4"}
        errors = VariableCostValidator.validate_model(model, existing_active_keys=existing)
        assert not any("ya existe" in e.lower() for e in errors)

    def test_negative_quantity_rejected(self):
        comp = VariableCostComponent(
            name="Malo",
            calculation_mode=CalculationMode.PER_UNIT,
            quantity=Decimal("-1"),
            unit_value=Decimal("100"),
            unit="unidad",
        )
        errors = VariableCostValidator.validate_component(comp)
        assert any("negativ" in e.lower() for e in errors)

    def test_negative_unit_value_rejected(self):
        comp = VariableCostComponent(
            name="Malo",
            calculation_mode=CalculationMode.PER_UNIT,
            quantity=Decimal("1"),
            unit_value=Decimal("-50"),
            unit="unidad",
        )
        errors = VariableCostValidator.validate_component(comp)
        assert any("negativ" in e.lower() for e in errors)

    def test_waste_over_100_rejected(self):
        comp = VariableCostComponent(
            name="Malo",
            calculation_mode=CalculationMode.PER_UNIT,
            quantity=Decimal("1"),
            unit_value=Decimal("100"),
            waste_pct=Decimal("150"),
            unit="unidad",
        )
        errors = VariableCostValidator.validate_component(comp)
        assert any("desperdicio" in e.lower() for e in errors)

    def test_waste_exactly_100_accepted(self):
        comp = VariableCostComponent(
            name="OK",
            calculation_mode=CalculationMode.PER_UNIT,
            quantity=Decimal("1"),
            unit_value=Decimal("100"),
            waste_pct=Decimal("100"),
            unit="unidad",
        )
        errors = VariableCostValidator.validate_component(comp)
        assert errors == []

    def test_percentage_mode_requires_no_unit(self):
        comp = VariableCostComponent(
            name="Comisión",
            calculation_mode=CalculationMode.PERCENTAGE,
            unit_value=Decimal("15"),
        )
        errors = VariableCostValidator.validate_component(comp)
        assert errors == []

    def test_missing_unit_on_direct_mode(self):
        comp = VariableCostComponent(
            name="Sin unidad",
            calculation_mode=CalculationMode.PER_UNIT,
            quantity=Decimal("1"),
            unit_value=Decimal("100"),
            unit="",
        )
        errors = VariableCostValidator.validate_component(comp)
        assert any("unidad" in e.lower() for e in errors)

    def test_has_incomplete_components(self):
        model = self._valid_model()
        assert not VariableCostValidator.has_incomplete_components(model)
        model.components[0].name = ""
        assert VariableCostValidator.has_incomplete_components(model)


# ---------------------------------------------------------------------------
# Persistencia Decimal — verificación de que no se usan float
# ---------------------------------------------------------------------------

class TestDecimalPrecision:
    def test_no_float_in_calculations(self):
        comp = VariableCostComponent(
            name="Test",
            calculation_mode=CalculationMode.PER_UNIT,
            quantity=Decimal("3"),
            unit_value=Decimal("333.33"),
            waste_pct=Decimal("7.5"),
        )
        result = comp.recalculate()
        # 3 * 333.33 = 999.99 * 1.075 = 1074.98925 → 1074.99
        assert result == Decimal("1074.99")
        assert isinstance(result, Decimal)

    def test_percentage_decimal_precision(self):
        comp = VariableCostComponent(
            name="Test",
            calculation_mode=CalculationMode.PERCENTAGE,
            unit_value=Decimal("15.5"),
            percentage_base=PercentageBase.SALE_PRICE,
        )
        result = comp.recalculate(sale_price=Decimal("3333.33"))
        # 3333.33 * 15.5 / 100 = 516.66615 → 516.67
        assert result == Decimal("516.67")
        assert isinstance(result, Decimal)

    def test_sum_uses_decimal(self):
        model = VariableCostModel(
            name="Test",
            product_key="test",
            components=[
                VariableCostComponent(
                    name="A",
                    calculation_mode=CalculationMode.PER_UNIT,
                    quantity=Decimal("1"),
                    unit_value=Decimal("0.1"),
                    order=1,
                ),
                VariableCostComponent(
                    name="B",
                    calculation_mode=CalculationMode.PER_UNIT,
                    quantity=Decimal("1"),
                    unit_value=Decimal("0.2"),
                    order=2,
                ),
            ],
        )
        total = model.recalculate_all()
        assert total == Decimal("0.30")
        assert isinstance(total, Decimal)
