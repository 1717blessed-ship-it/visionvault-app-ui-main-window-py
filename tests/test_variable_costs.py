import sys
from pathlib import Path
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from costos.models.calculation_mode import CalculationMode, PercentageBase
from costos.models.variable_cost_component import VariableCostComponent
from costos.models.variable_cost_model import VariableCostModel
from costos.repositories.variable_cost_repository import VariableCostRepository
from costos.services.variable_cost_service import VariableCostService
from costos.validators.variable_cost_validator import VariableCostValidator


def test_variable_cost_component_per_unit_evaluation():
    comp = VariableCostComponent(
        name="Vinilo", calculation_mode=CalculationMode.PER_UNIT,
        quantity=Decimal("2"), unit_value=Decimal("150"), waste_pct=Decimal("0")
    )
    comp.recalculate()
    assert comp.calculated_amount == Decimal("300.00")


def test_variable_cost_component_with_waste():
    comp = VariableCostComponent(
        name="Papel", calculation_mode=CalculationMode.PER_UNIT,
        quantity=Decimal("1"), unit_value=Decimal("100"), waste_pct=Decimal("10")
    )
    comp.recalculate()
    assert comp.calculated_amount == Decimal("110.00")


def test_variable_cost_component_percentage():
    comp = VariableCostComponent(
        name="Comisión", calculation_mode=CalculationMode.PERCENTAGE,
        quantity=Decimal("0"), unit_value=Decimal("5"),
        percentage_base=PercentageBase.SALE_PRICE
    )
    comp.recalculate(sale_price=Decimal("1000"))
    assert comp.calculated_amount == Decimal("50.00")


def test_variable_cost_component_fixed_evaluation():
    comp = VariableCostComponent(
        name="Diseño", calculation_mode=CalculationMode.FIXED_PRODUCTION,
        quantity=Decimal("1"), unit_value=Decimal("500")
    )
    comp.recalculate()
    assert comp.calculated_amount == Decimal("500.00")


def test_variable_cost_component_disabled_returns_zero():
    comp = VariableCostComponent(
        name="Inactivo", calculation_mode=CalculationMode.PER_UNIT,
        quantity=Decimal("5"), unit_value=Decimal("10"), active=False
    )
    comp.recalculate()
    assert comp.calculated_amount == Decimal("0")


def test_variable_cost_component_negative_quantity_clamped():
    comp = VariableCostComponent(
        name="Test", calculation_mode=CalculationMode.PER_UNIT,
        quantity=Decimal("-3"), unit_value=Decimal("10")
    )
    comp.recalculate()
    assert comp.calculated_amount == Decimal("0.00")


def test_variable_cost_model_total_variable_cost():
    model = VariableCostModel(name="Modelo Test")
    c1 = VariableCostComponent(
        name="Vinilo", calculation_mode=CalculationMode.PER_UNIT,
        quantity=Decimal("2"), unit_value=Decimal("100")
    )
    c1.recalculate()
    c2 = VariableCostComponent(
        name="Tinta", calculation_mode=CalculationMode.PER_UNIT,
        quantity=Decimal("1"), unit_value=Decimal("50"), waste_pct=Decimal("10")
    )
    c2.recalculate()
    model.components = [c1, c2]
    total = model.total_variable_cost()
    assert total == Decimal("255.00")


def test_variable_cost_model_contribution_margin():
    model = VariableCostModel(name="Test Margen")
    c = VariableCostComponent(
        name="Costo", calculation_mode=CalculationMode.PER_UNIT,
        quantity=Decimal("1"), unit_value=Decimal("1700")
    )
    c.recalculate()
    model.components = [c]
    sale_price = Decimal("5000")
    model.recalculate_all(sale_price=sale_price)
    assert model.total_variable_cost() == Decimal("1700.00")
    margin = sale_price - model.total_variable_cost()
    assert margin == Decimal("3300.00")


def test_variable_cost_model_contribution_percentage():
    model = VariableCostModel(name="Test %")
    c = VariableCostComponent(
        name="Costo", calculation_mode=CalculationMode.PER_UNIT,
        quantity=Decimal("1"), unit_value=Decimal("1700")
    )
    c.recalculate()
    model.components = [c]
    sale_price = Decimal("5000")
    model.recalculate_all(sale_price=sale_price)
    margin_pct = (sale_price - model.total_variable_cost()) / sale_price * 100
    assert margin_pct == Decimal("66.000")


def test_variable_cost_model_percentage_component_base():
    model = VariableCostModel(name="Test Base")
    c1 = VariableCostComponent(
        name="Materia prima", calculation_mode=CalculationMode.PER_UNIT,
        quantity=Decimal("1"), unit_value=Decimal("1000")
    )
    c1.recalculate()
    c2 = VariableCostComponent(
        name="Comisión", calculation_mode=CalculationMode.PERCENTAGE,
        unit_value=Decimal("10"),
        percentage_base=PercentageBase.RAW_MATERIAL
    )
    model.components = [c1, c2]
    model.recalculate_all()
    assert model.total_variable_cost() == Decimal("1100.00")


def test_repository_add_and_get():
    repo = VariableCostRepository()
    model = VariableCostModel(name="Repo Test")
    c = VariableCostComponent(name="Comp 1", calculation_mode=CalculationMode.PER_UNIT,
                              quantity=Decimal("1"), unit_value=Decimal("50"))
    model.components = [c]
    repo.add(model)
    assert model.id is not None
    fetched = repo.get(model.id)
    assert fetched is not None
    assert fetched.name == "Repo Test"


def test_repository_list_and_delete():
    repo = VariableCostRepository()
    m1 = VariableCostModel(name="A", active=True)
    m2 = VariableCostModel(name="B", active=False)
    repo.add(m1)
    repo.add(m2)
    all_models = repo.list()
    assert len(all_models) == 2
    active_only = repo.list(active_only=True)
    assert len(active_only) == 1
    repo.delete(m1.id)
    assert repo.get(m1.id) is None


def test_service_calculate_totals():
    service = VariableCostService()
    model = VariableCostModel(name="Svc Test")
    c = VariableCostComponent(
        name="Componente", calculation_mode=CalculationMode.PER_UNIT,
        quantity=Decimal("3"), unit_value=Decimal("100"), waste_pct=Decimal("0")
    )
    c.recalculate()
    model.components = [c]
    service.add_model(model)
    assert model.total_variable_cost() == Decimal("300.00")
    sale_price = Decimal("500")
    model.recalculate_all(sale_price=sale_price)
    assert service.calculate_margin(model, sale_price=sale_price) == Decimal("200.00")


def test_validator_catches_missing_name():
    model = VariableCostModel(name="")
    errors = VariableCostValidator.validate(model)
    assert any("nombre" in e.lower() for e in errors)


def test_validator_catches_negative_quantity():
    model = VariableCostModel(name="Valid", product_name="Test")
    model.components = [VariableCostComponent(
        name="Comp", calculation_mode=CalculationMode.PER_UNIT,
        quantity=Decimal("-1"), unit_value=Decimal("10")
    )]
    errors = VariableCostValidator.validate(model)
    assert any("cantidad" in e.lower() for e in errors)


def test_validator_catches_negative_value():
    model = VariableCostModel(name="Valid", product_name="Test")
    model.components = [VariableCostComponent(
        name="Comp", calculation_mode=CalculationMode.PER_UNIT,
        quantity=Decimal("1"), unit_value=Decimal("-5")
    )]
    errors = VariableCostValidator.validate(model)
    assert any("valor" in e.lower() for e in errors)


def test_validator_catches_waste_out_of_range():
    model = VariableCostModel(name="Valid", product_name="Test")
    model.components = [VariableCostComponent(
        name="Comp", calculation_mode=CalculationMode.PER_UNIT,
        quantity=Decimal("1"), unit_value=Decimal("10"), waste_pct=Decimal("150")
    )]
    errors = VariableCostValidator.validate(model)
    assert any("desperdicio" in e.lower() for e in errors)


def test_validator_catches_percentage_without_base():
    model = VariableCostModel(name="Valid", product_name="Test")
    model.components = [VariableCostComponent(
        name="Comp", calculation_mode=CalculationMode.PERCENTAGE,
        unit_value=Decimal("10"), percentage_base=PercentageBase.SALE_PRICE
    )]
    errors = VariableCostValidator.validate(model)
    assert not any("base" in e.lower() for e in errors)


def test_database_persistence_variable_cost_models(tmp_path):
    from app.database.database import ImageDatabase

    db = ImageDatabase(tmp_path / "test_var_costs.db")

    model_id = db.save_variable_cost_model(
        name="Modelo Vinilo",
        product_name="Vinilo Full Color",
        category="Vinilos",
        active=True,
        components=[
            {
                "name": "Vinilo sublimable", "category": "Materia prima",
                "origin": "manual", "calc_mode": "per_unit",
                "quantity": 1.0, "unit_value": 200.0, "waste_pct": 5.0,
                "unit": "hoja", "percentage_base": "", "amount": 210.0,
                "sort_order": 0, "active": 1,
            },
            {
                "name": "Tinta", "category": "Insumo",
                "origin": "manual", "calc_mode": "per_unit",
                "quantity": 0.5, "unit_value": 100.0, "waste_pct": 0.0,
                "unit": "ml", "percentage_base": "", "amount": 50.0,
                "sort_order": 1, "active": 1,
            },
        ],
    )
    assert model_id > 0

    model = db.variable_cost_model(model_id)
    assert model is not None
    assert model["name"] == "Modelo Vinilo"
    assert model["product_name"] == "Vinilo Full Color"

    components = db.variable_cost_model_components(model_id)
    assert len(components) == 2
    assert components[0]["name"] == "Vinilo sublimable"
    assert components[1]["unit_value"] == 100.0


def test_database_update_variable_cost_model(tmp_path):
    from app.database.database import ImageDatabase

    db = ImageDatabase(tmp_path / "test_var_update.db")

    model_id = db.save_variable_cost_model(
        name="Original", product_name="Test", category="",
        components=[
            {"name": "A", "calc_mode": "per_unit", "quantity": 1, "unit_value": 10,
             "sort_order": 0, "active": 1},
        ],
    )
    updated = db.update_variable_cost_model(
        model_id, name="Actualizado", product_name="Test 2", category="Cat",
        components=[
            {"name": "B", "calc_mode": "fixed", "quantity": 1, "unit_value": 50,
             "sort_order": 0, "active": 1},
            {"name": "C", "calc_mode": "per_unit", "quantity": 2, "unit_value": 25,
             "sort_order": 1, "active": 1},
        ],
    )
    assert updated

    model = db.variable_cost_model(model_id)
    assert model["name"] == "Actualizado"
    assert model["product_name"] == "Test 2"

    components = db.variable_cost_model_components(model_id)
    assert len(components) == 2
    assert components[0]["name"] == "B"


def test_database_remove_variable_cost_model(tmp_path):
    from app.database.database import ImageDatabase

    db = ImageDatabase(tmp_path / "test_var_delete.db")

    model_id = db.save_variable_cost_model(
        name="Para borrar", product_name="X",
        components=[{"name": "Comp", "calc_mode": "per_unit", "quantity": 1, "unit_value": 5, "sort_order": 0, "active": 1}],
    )
    db.remove_variable_cost_model(model_id)
    assert db.variable_cost_model(model_id) is None
    assert len(db.variable_cost_model_components(model_id)) == 0


def test_database_duplicate_variable_cost_model(tmp_path):
    from app.database.database import ImageDatabase

    db = ImageDatabase(tmp_path / "test_var_dup.db")

    model_id = db.save_variable_cost_model(
        name="Original", product_name="P",
        components=[{"name": "X", "calc_mode": "per_unit", "quantity": 1, "unit_value": 100, "sort_order": 0, "active": 1}],
    )
    new_id = db.duplicate_variable_cost_model(model_id)
    assert new_id is not None
    assert new_id != model_id

    new_model = db.variable_cost_model(new_id)
    assert new_model["name"] == "Original (copia)"

    new_comps = db.variable_cost_model_components(new_id)
    assert len(new_comps) == 1
    assert new_comps[0]["name"] == "X"


def test_fixed_costs_not_modified(tmp_path):
    from app.database.database import ImageDatabase

    db = ImageDatabase(tmp_path / "test_no_modify.db")

    rule_id = db.save_cost_rule(
        name="Regla Fija",
        cost_mp_percent=30.0,
        cost_mo_percent=20.0,
        cost_cf_percent=10.0,
    )

    model_id = db.save_variable_cost_model(
        name="Variable Test",
        product_name="Producto X",
        components=[{"name": "Comp", "calc_mode": "per_unit", "quantity": 1, "unit_value": 50, "sort_order": 0, "active": 1}],
    )

    original_rule = db.cost_rule(rule_id)
    assert original_rule["cost_mp_percent"] == 30.0
    assert original_rule["cost_mo_percent"] == 20.0
    assert original_rule["cost_cf_percent"] == 10.0

    db.save_variable_cost_model(
        name="Segundo Variable",
        product_name="Producto Y",
        components=[{"name": "Otro", "calc_mode": "fixed", "quantity": 1, "unit_value": 1000, "sort_order": 0, "active": 1}],
    )

    rule_after = db.cost_rule(rule_id)
    assert rule_after["cost_mp_percent"] == 30.0
    assert rule_after["cost_mo_percent"] == 20.0
    assert rule_after["cost_cf_percent"] == 10.0
