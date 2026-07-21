from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CalculationType = Literal["percentage", "fixed", "per_unit", "per_hour", "per_square_meter"]


@dataclass(slots=True)
class CostComponent:
    """Representa un componente de costo dentro de una regla."""

    id: int | None = None
    name: str = ""
    code: str = ""
    value_type: CalculationType = "percentage"
    value: float = 0.0
    enabled: bool = True
    order: int = 0

    def evaluate(self, sale_price: float = 0.0, quantity: int = 1, hours: float = 0.0, surface: float = 0.0) -> float:
        quantity = max(int(quantity or 1), 1)
        hours = max(float(hours or 0), 0.0)
        surface = max(float(surface or 0), 0.0)

        if not self.enabled:
            return 0.0

        if self.value_type == "percentage":
            return round(sale_price * self.value / 100.0, 2)
        if self.value_type == "fixed":
            return round(self.value, 2)
        if self.value_type == "per_unit":
            return round(self.value * quantity, 2)
        if self.value_type == "per_hour":
            return round(self.value * hours, 2)
        if self.value_type == "per_square_meter":
            return round(self.value * surface, 2)
        raise ValueError(f"Tipo de cálculo no soportado: {self.value_type}")
