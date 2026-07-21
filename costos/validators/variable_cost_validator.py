from __future__ import annotations

from decimal import Decimal, InvalidOperation

from ..models.calculation_mode import CalculationMode
from ..models.variable_cost_component import VariableCostComponent
from ..models.variable_cost_model import VariableCostModel


class VariableCostValidator:
    """Valida modelos y componentes de costo variable antes de persistir."""

    MAX_WASTE_PCT = Decimal("100")
    MIN_WASTE_PCT = Decimal("0")

    @classmethod
    def validate(cls, model: VariableCostModel) -> list[str]:
        """Alias backward-compatible. Delega a validate_model."""
        return cls.validate_model(model)

    @classmethod
    def validate_model(
        cls,
        model: VariableCostModel,
        existing_active_keys: set[str] | None = None,
    ) -> list[str]:
        errors: list[str] = []

        if not model.name.strip():
            errors.append("El nombre del modelo es obligatorio")

        has_identity = bool(model.product_key.strip()) or bool(
            getattr(model, "product_name", "").strip()
        )
        if not has_identity:
            errors.append("Debe existir un producto o categoría asociado")

        if not model.components:
            errors.append("Debe incluir al menos un componente de costo variable")

        for idx, component in enumerate(model.components, start=1):
            component_errors = cls.validate_component(component)
            for error in component_errors:
                errors.append(
                    f"Componente {idx} ({component.name or 'sin nombre'}): {error}"
                )

        if (
            model.active
            and existing_active_keys is not None
            and model.product_key
            and model.product_key in existing_active_keys
        ):
            errors.append(
                f"Ya existe un modelo activo para el producto "
                f"'{getattr(model, 'product_name', '') or model.product_key}'"
            )

        return errors

    @classmethod
    def validate_component(cls, component: VariableCostComponent) -> list[str]:
        errors: list[str] = []

        if not component.name.strip():
            errors.append("El nombre del componente es obligatorio")

        try:
            qty = Decimal(str(component.quantity))
        except (InvalidOperation, ValueError):
            errors.append("La cantidad no es un número válido")
            qty = None

        if qty is not None and qty < 0:
            errors.append("La cantidad no puede ser negativa")

        try:
            uv = Decimal(str(component.unit_value))
        except (InvalidOperation, ValueError):
            errors.append("El valor unitario no es un número válido")
            uv = None

        if uv is not None and uv < 0:
            errors.append("El valor unitario no puede ser negativo")

        try:
            waste = Decimal(str(component.waste_pct))
        except (InvalidOperation, ValueError):
            errors.append("El desperdicio no es un número válido")
            waste = None

        if waste is not None and (waste < cls.MIN_WASTE_PCT or waste > cls.MAX_WASTE_PCT):
            errors.append(
                f"El desperdicio debe estar entre {cls.MIN_WASTE_PCT}% y {cls.MAX_WASTE_PCT}%"
            )

        if component.calculation_mode not in CalculationMode:
            errors.append(f"Modo de cálculo no válido: {component.calculation_mode}")

        if (
            not component.unit.strip()
            and component.calculation_mode != CalculationMode.PERCENTAGE
        ):
            errors.append("La unidad es obligatoria para este modo de cálculo")

        return errors

    @classmethod
    def has_incomplete_components(cls, model: VariableCostModel) -> bool:
        for component in model.active_components():
            if cls.validate_component(component):
                return True
        return False
