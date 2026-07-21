from __future__ import annotations

from enum import Enum


class CalculationMode(str, Enum):
    """Modos de cálculo para componentes de costo variable.

    Cada modo define cómo se interpreta cantidad × valor_unitario
    para derivar el importe del componente.
    """

    PER_UNIT = "per_unit"
    PER_SHEET = "per_sheet"
    PER_PLATE = "per_plate"
    PER_METER = "per_meter"
    PER_SQUARE_METER = "per_square_meter"
    PER_MILLILITER = "per_milliliter"
    PER_GRAM = "per_gram"
    PER_IMPRESSION = "per_impression"
    PER_MINUTE = "per_minute"
    PER_HOUR = "per_hour"
    FIXED_PRODUCTION = "fixed_production"
    PERCENTAGE = "percentage"


CALCULATION_MODE_LABELS: dict[str, str] = {
    CalculationMode.PER_UNIT: "Por unidad",
    CalculationMode.PER_SHEET: "Por hoja",
    CalculationMode.PER_PLATE: "Por plancha",
    CalculationMode.PER_METER: "Por metro",
    CalculationMode.PER_SQUARE_METER: "Por metro cuadrado",
    CalculationMode.PER_MILLILITER: "Por mililitro",
    CalculationMode.PER_GRAM: "Por gramo",
    CalculationMode.PER_IMPRESSION: "Por impresión",
    CalculationMode.PER_MINUTE: "Por minuto",
    CalculationMode.PER_HOUR: "Por hora",
    CalculationMode.FIXED_PRODUCTION: "Fijo por producción",
    CalculationMode.PERCENTAGE: "Porcentaje",
}

CALCULATION_MODE_KEYS: dict[str, str] = {label: key for key, label in CALCULATION_MODE_LABELS.items()}

DIRECT_CALCULATION_MODES: frozenset[CalculationMode] = frozenset({
    CalculationMode.PER_UNIT,
    CalculationMode.PER_SHEET,
    CalculationMode.PER_PLATE,
    CalculationMode.PER_METER,
    CalculationMode.PER_SQUARE_METER,
    CalculationMode.PER_MILLILITER,
    CalculationMode.PER_GRAM,
    CalculationMode.PER_IMPRESSION,
    CalculationMode.PER_MINUTE,
    CalculationMode.PER_HOUR,
    CalculationMode.FIXED_PRODUCTION,
})


class PercentageBase(str, Enum):
    """Base sobre la cual se calcula un componente porcentual.

    Permite evitar referencias circulares limitando las bases
    a valores precalculados o acumulados de forma segura.
    """

    SALE_PRICE = "sale_price"
    RAW_MATERIAL = "raw_material"
    LABOR = "labor"
    PREVIOUS_COMPONENTS = "previous_components"
    SELECTED_SUBTOTAL = "selected_subtotal"


PERCENTAGE_BASE_LABELS: dict[str, str] = {
    PercentageBase.SALE_PRICE: "Precio de venta",
    PercentageBase.RAW_MATERIAL: "Materia prima",
    PercentageBase.LABOR: "Mano de obra",
    PercentageBase.PREVIOUS_COMPONENTS: "Subtotal componentes anteriores",
    PercentageBase.SELECTED_SUBTOTAL: "Subtotal seleccionado",
}

PERCENTAGE_BASE_KEYS: dict[str, str] = {label: key for key, label in PERCENTAGE_BASE_LABELS.items()}
