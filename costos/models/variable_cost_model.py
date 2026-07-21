from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .variable_cost_component import VariableCostComponent


def build_product_key(category: str, material: str, size: str, variant: str = "") -> str:
    """Genera una clave estable para identificar un producto en el catálogo.

    Normaliza los componentes a minúsculas, sin espacios extra y
    separados por '|'.  Esto evita duplicados por diferencias de
    escritura en títulos de order_jobs.

    Example:
        >>> build_product_key("Plancha sublimada", "Vinilo sublimable", "A4", "22x30")
        'plancha_sublimada|vinilo_sublimable|a4|22x30'
    """
    import re

    def _norm(v: str) -> str:
        return re.sub(r"\s+", "_", str(v or "").strip().lower())

    parts = [_norm(category), _norm(material), _norm(size)]
    if variant:
        parts.append(_norm(variant))
    return "|".join(parts)


@dataclass(slots=True)
class VariableCostModel:
    """Modelo de costo variable unitario para un producto del catálogo.

    Cada product_key puede tener como máximo UN modelo activo.
    Los modelos inactivos se conservan como historial.
    """

    id: int | None = None
    name: str = ""
    product_key: str = ""
    product_name: str = ""
    category: str = ""
    active: bool = True
    outdated: bool = False
    created_at: str = ""
    updated_at: str = ""
    components: list[VariableCostComponent] = field(default_factory=list)

    def total_variable_cost(self) -> Decimal:
        """Suma de los importes calculados de todos los componentes activos."""
        return sum(
            (c.calculated_amount for c in self.components if c.active),
            Decimal("0"),
        )

    def recalculate_all(
        self,
        *,
        sale_price: Decimal = Decimal("0"),
    ) -> Decimal:
        """Recalcula todos los componentes y retorna el costo variable unitario.

        Procesa primero los componentes directos (por unidad, por hoja, etc.)
        y luego los porcentuales, acumulando subtotales de forma segura
        para evitar referencias circulares.
        """
        ordered = sorted(self.components, key=lambda c: c.order)

        # Paso 1: calcular componentes directos y acumular subtotales
        raw_material_total = Decimal("0")
        labor_total = Decimal("0")
        direct_total = Decimal("0")

        for component in ordered:
            if not component.active:
                continue
            if component.calculation_mode.value == "percentage":
                continue
            component.recalculate(sale_price=sale_price)
            direct_total += component.calculated_amount

        # Clasificar subtotales aproximados para bases porcentuales
        for component in ordered:
            if not component.active:
                continue
            if component.calculation_mode.value == "percentage":
                continue
            name_lower = component.name.lower()
            if any(kw in name_lower for kw in ("materia prima", "vinilo", "papel", "tinta", "insumo")):
                raw_material_total += component.calculated_amount
            if any(kw in name_lower for kw in ("mano de obra", "diseño", "producción")):
                labor_total += component.calculated_amount

        # Paso 2: calcular componentes porcentuales con subtotales acumulados.
        # previous_components_total incluye TODOS los componentes calculados
        # antes del actual (directos + ya procesados porcentuales).
        all_previous_total = direct_total
        for component in ordered:
            if not component.active:
                continue
            if component.calculation_mode.value != "percentage":
                continue
            component.recalculate(
                sale_price=sale_price,
                raw_material_subtotal=raw_material_total,
                labor_subtotal=labor_total,
                previous_components_total=all_previous_total,
            )
            all_previous_total += component.calculated_amount

        return self.total_variable_cost()

    def component_by_id(self, component_id: int) -> VariableCostComponent | None:
        for c in self.components:
            if c.id == component_id:
                return c
        return None

    def active_components(self) -> list[VariableCostComponent]:
        return [c for c in self.components if c.active]

    def mark_outdated(self, source_id: str) -> None:
        """Marca el modelo como desactualizado si una fuente vinculada cambió."""
        for c in self.components:
            if c.source_id == source_id and not c.manually_overridden:
                self.outdated = True
                return

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "product_key": self.product_key,
            "product_name": self.product_name,
            "category": self.category,
            "active": self.active,
            "outdated": self.outdated,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict, components: list[VariableCostComponent] | None = None) -> VariableCostModel:
        return cls(
            id=data.get("id"),
            name=str(data.get("name") or ""),
            product_key=str(data.get("product_key") or ""),
            product_name=str(data.get("product_name") or ""),
            category=str(data.get("category") or ""),
            active=bool(data.get("active", True)),
            outdated=bool(data.get("outdated", False)),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            components=list(components or []),
        )
