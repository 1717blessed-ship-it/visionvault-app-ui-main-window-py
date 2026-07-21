from __future__ import annotations

from decimal import Decimal

from ..models.variable_cost_model import VariableCostModel
from ..repositories.variable_cost_repository import VariableCostRepository


class VariableCostService:
    """Servicio de alto nivel para modelos de costo variable."""

    def __init__(self, repository: VariableCostRepository | None = None) -> None:
        self.repository = repository or VariableCostRepository()

    def add_model(self, model: VariableCostModel) -> VariableCostModel:
        return self.repository.add(model)

    def get_model(self, model_id: int) -> VariableCostModel | None:
        return self.repository.get(model_id)

    def list_models(self, active_only: bool = False) -> list[VariableCostModel]:
        return self.repository.list(active_only=active_only)

    def update_model(self, model: VariableCostModel) -> VariableCostModel:
        return self.repository.update(model)

    def delete_model(self, model_id: int) -> bool:
        return self.repository.delete(model_id)

    def calculate_total(self, model: VariableCostModel, sale_price: Decimal = Decimal("0")) -> Decimal:
        model.recalculate_all(sale_price=sale_price)
        return model.total_variable_cost()

    def calculate_margin(self, model: VariableCostModel, sale_price: Decimal = Decimal("0")) -> Decimal:
        model.recalculate_all(sale_price=sale_price)
        return sale_price - model.total_variable_cost()

    def calculate_margin_pct(self, model: VariableCostModel, sale_price: Decimal = Decimal("0")) -> Decimal:
        model.recalculate_all(sale_price=sale_price)
        total = model.total_variable_cost()
        if sale_price <= 0:
            return Decimal("0")
        return ((sale_price - total) / sale_price * 100).quantize(Decimal("0.01"))
