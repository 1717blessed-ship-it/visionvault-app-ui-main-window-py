from __future__ import annotations

from ..models.cost_rule import CostRule
from ..models.cost_component import CostComponent


class CostRuleValidator:
    """Valida reglas de costo básicas antes de guardarlas."""

    @staticmethod
    def validate(rule: CostRule) -> list[str]:
        errors: list[str] = []
        if not rule.name.strip():
            errors.append("El nombre de la regla es obligatorio")
        if not rule.components:
            errors.append("Debe incluir al menos un componente de costo")
        for component in rule.components:
            if not component.name.strip():
                errors.append("Cada componente debe tener un nombre")
            if component.value_type not in {"percentage", "fixed", "per_unit", "per_hour", "per_square_meter"}:
                errors.append("El tipo de cálculo no es válido")
        return errors
