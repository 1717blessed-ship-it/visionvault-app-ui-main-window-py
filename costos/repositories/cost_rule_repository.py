from __future__ import annotations

from typing import Any

from ..models.cost_component import CostComponent
from ..models.cost_rule import CostRule


class CostRuleRepository:
    """Repositorio en memoria de reglas de costo."""

    def __init__(self, rules: list[CostRule] | None = None) -> None:
        self._rules = list(rules or [])

    def add(self, rule: CostRule) -> CostRule:
        if rule.id is None:
            rule.id = len(self._rules) + 1
        self._rules.append(rule)
        return rule

    def list(self) -> list[CostRule]:
        return list(self._rules)

    def get(self, rule_id: int) -> CostRule | None:
        for rule in self._rules:
            if rule.id == rule_id:
                return rule
        return None

    def update(self, rule_id: int, **updates: Any) -> CostRule | None:
        rule = self.get(rule_id)
        if rule is None:
            return None
        for key, value in updates.items():
            if key == "components" and value is not None:
                rule.components = [CostComponent(**c) if isinstance(c, dict) else c for c in value]
            else:
                setattr(rule, key, value)
        return rule

    def delete(self, rule_id: int) -> bool:
        for index, rule in enumerate(self._rules):
            if rule.id == rule_id:
                del self._rules[index]
                return True
        return False
