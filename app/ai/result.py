"""Validación del resultado que se puede conservar de un análisis de IA."""

from __future__ import annotations

from typing import Any


def has_usable_analysis(result: dict[str, Any] | None) -> bool:
    """Indica si un resultado aporta algo que valga la pena mostrar en caché.

    Un resultado técnicamente exitoso pero sin texto, descripción, etiquetas,
    nombres ni referencias suele ser un corte transitorio del proveedor. No se
    debe guardar ni reutilizar porque impide que el usuario pueda reintentarlo.
    """
    if not isinstance(result, dict):
        return False
    if any(str(result.get(field) or "").strip() for field in ("text", "caption", "category")):
        return True
    return any(bool(result.get(field)) for field in ("suggestions", "names", "references"))
