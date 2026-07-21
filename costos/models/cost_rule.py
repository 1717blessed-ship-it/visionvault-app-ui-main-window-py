from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .cost_component import CostComponent
from .cost_condition import CostCondition


@dataclass(slots=True)
class CostRule:
    """Regla de costo con componentes y condiciones de aplicación."""

    id: int | None = None
    name: str = ""
    product_type: str = ""
    minimum_margin: float = 0.0
    active: bool = True
    components: list[CostComponent] = field(default_factory=list)
    conditions: list[CostCondition] = field(default_factory=list)

    def add_component(self, component: CostComponent) -> None:
        self.components.append(component)

    def add_condition(self, condition: CostCondition) -> None:
        self.conditions.append(condition)
