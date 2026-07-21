from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CostCondition:
    """Condición simple para aplicar una regla de costo."""

    field: str = ""
    operator: str = "eq"
    value: Any = None
