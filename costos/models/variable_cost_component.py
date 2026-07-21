from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .calculation_mode import CalculationMode, PercentageBase


@dataclass(slots=True)
class VariableCostComponent:
    """Componente individual dentro de un modelo de costo variable.

    El importe calculado se deriva siempre de:
        cantidad × valor_unitario × (1 + desperdicio/100)
    o, en modo porcentaje:
        base × porcentaje / 100

    ``calculated_amount`` se almacena como caché pero NUNCA se
    toma como fuente primaria al recalcular.
    """

    id: int | None = None
    model_id: int | None = None
    name: str = ""
    origin: str = "manual"
    source_id: str | None = None
    calculation_mode: CalculationMode = CalculationMode.PER_UNIT
    quantity: Decimal = Decimal("1")
    unit_value: Decimal = Decimal("0")
    waste_pct: Decimal = Decimal("0")
    unit: str = ""
    percentage_base: PercentageBase = PercentageBase.SALE_PRICE
    calculated_amount: Decimal = Decimal("0")
    order: int = 0
    active: bool = True

    # Campos de sincronización
    source_updated_at: str | None = None
    last_synced_at: str | None = None
    manually_overridden: bool = False

    created_at: str = ""
    updated_at: str = ""

    def recalculate(
        self,
        *,
        sale_price: Decimal = Decimal("0"),
        raw_material_subtotal: Decimal = Decimal("0"),
        labor_subtotal: Decimal = Decimal("0"),
        previous_components_total: Decimal = Decimal("0"),
        selected_subtotal: Decimal = Decimal("0"),
    ) -> Decimal:
        """Recalcula ``calculated_amount`` desde los campos del componente.

        Returns:
            El importe calculado.
        """
        if not self.active:
            self.calculated_amount = Decimal("0")
            return self.calculated_amount

        if self.calculation_mode == CalculationMode.PERCENTAGE:
            base = self._resolve_percentage_base(
                sale_price=sale_price,
                raw_material_subtotal=raw_material_subtotal,
                labor_subtotal=labor_subtotal,
                previous_components_total=previous_components_total,
                selected_subtotal=selected_subtotal,
            )
            self.calculated_amount = (base * self.unit_value / Decimal("100")).quantize(Decimal("0.01"))
        else:
            qty = max(self.quantity, Decimal("0"))
            cost = qty * self.unit_value
            if self.waste_pct > Decimal("0"):
                cost = cost * (Decimal("1") + self.waste_pct / Decimal("100"))
            self.calculated_amount = cost.quantize(Decimal("0.01"))

        return self.calculated_amount

    def _resolve_percentage_base(
        self,
        *,
        sale_price: Decimal,
        raw_material_subtotal: Decimal,
        labor_subtotal: Decimal,
        previous_components_total: Decimal,
        selected_subtotal: Decimal,
    ) -> Decimal:
        bases = {
            PercentageBase.SALE_PRICE: sale_price,
            PercentageBase.RAW_MATERIAL: raw_material_subtotal,
            PercentageBase.LABOR: labor_subtotal,
            PercentageBase.PREVIOUS_COMPONENTS: previous_components_total,
            PercentageBase.SELECTED_SUBTOTAL: selected_subtotal,
        }
        return bases.get(self.percentage_base, sale_price)

    def to_dict(self) -> dict:
        """Serializa el componente a un diccionario persistible."""
        return {
            "id": self.id,
            "model_id": self.model_id,
            "name": self.name,
            "origin": self.origin,
            "source_id": self.source_id,
            "calculation_mode": self.calculation_mode.value,
            "quantity": str(self.quantity),
            "unit_value": str(self.unit_value),
            "waste_pct": str(self.waste_pct),
            "unit": self.unit,
            "percentage_base": self.percentage_base.value,
            "calculated_amount": str(self.calculated_amount),
            "order": self.order,
            "active": self.active,
            "source_updated_at": self.source_updated_at,
            "last_synced_at": self.last_synced_at,
            "manually_overridden": self.manually_overridden,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> VariableCostComponent:
        """Reconstruye un componente desde un diccionario de la base de datos."""
        return cls(
            id=data.get("id"),
            model_id=data.get("model_id"),
            name=str(data.get("name") or ""),
            origin=str(data.get("origin") or "manual"),
            source_id=data.get("source_id"),
            calculation_mode=CalculationMode(str(data.get("calculation_mode") or "per_unit")),
            quantity=Decimal(str(data.get("quantity") or "1")),
            unit_value=Decimal(str(data.get("unit_value") or "0")),
            waste_pct=Decimal(str(data.get("waste_pct") or "0")),
            unit=str(data.get("unit") or ""),
            percentage_base=PercentageBase(str(data.get("percentage_base") or "sale_price")),
            calculated_amount=Decimal(str(data.get("calculated_amount") or "0")),
            order=int(data.get("order") or 0),
            active=bool(data.get("active", True)),
            source_updated_at=data.get("source_updated_at"),
            last_synced_at=data.get("last_synced_at"),
            manually_overridden=bool(data.get("manually_overridden", False)),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )
