from __future__ import annotations

from typing import Any


class ConditionEvaluator:
    """Evalúa condiciones simples sobre un contexto."""

    @staticmethod
    def matches(context: dict[str, Any], field: str, operator: str = "eq", value: Any = None) -> bool:
        actual = context.get(field)
        if operator == "eq":
            return actual == value
        if operator == "in":
            return actual in value if isinstance(value, (list, tuple, set)) else False
        if operator == "contains":
            return str(actual).lower().find(str(value).lower()) >= 0 if actual is not None else False
        if operator == "gt":
            return float(actual or 0) > float(value or 0)
        if operator == "lt":
            return float(actual or 0) < float(value or 0)
        raise ValueError(f"Operador no soportado: {operator}")
