from __future__ import annotations

from ..models.variable_cost_component import VariableCostComponent
from ..models.variable_cost_model import VariableCostModel


class VariableCostRepository:
    """Repositorio en memoria de modelos de costo variable."""

    def __init__(self) -> None:
        self._models: list[VariableCostModel] = []

    def add(self, model: VariableCostModel) -> VariableCostModel:
        if model.id is None:
            model.id = max((m.id or 0) for m in self._models) + 1 if self._models else 1
        self._models.append(model)
        return model

    def get(self, model_id: int) -> VariableCostModel | None:
        for m in self._models:
            if m.id == model_id:
                return m
        return None

    def list(self, active_only: bool = False) -> list[VariableCostModel]:
        if active_only:
            return [m for m in self._models if m.active]
        return list(self._models)

    def update(self, model: VariableCostModel) -> VariableCostModel:
        for i, existing in enumerate(self._models):
            if existing.id == model.id:
                self._models[i] = model
                return model
        return model

    def delete(self, model_id: int) -> bool:
        for i, m in enumerate(self._models):
            if m.id == model_id:
                del self._models[i]
                return True
        return False
