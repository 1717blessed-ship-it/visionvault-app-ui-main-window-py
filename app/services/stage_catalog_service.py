"""Servicio de catálogo de etapas y workflows para API móvil.

Este servicio adapta los datos oficiales de app/workflow/timeline.py
al formato JSON que requiere la API móvil, sin redefinir reglas de negocio.
"""

from __future__ import annotations

from typing import Final

from app.workflow.timeline import (
    GENERAL_WORKFLOW,
    VINYL_WORKFLOW,
    TEXTILE_WORKFLOW,
    FINISHING_WORKFLOW,
)


# Mapeo de etapas a metadatos de UI (colores, descripciones)
STAGE_METADATA: Final[dict[str, dict[str, str]]] = {
    "Recibido": {
        "category": "inicio",
        "description": "Trabajo recibido, en cola de producción",
        "color": "#9E9E9E",
    },
    "Esperando archivos": {
        "category": "inicio",
        "description": "Pendiente de recibir archivos del cliente",
        "color": "#FF9800",
    },
    "Diseños confirmados": {
        "category": "preprensa",
        "description": "Diseños aprobados, listo para producción",
        "color": "#2196F3",
    },
    "Listo para armado de planchas": {
        "category": "preprensa",
        "description": "Preparación de planchas para impresión",
        "color": "#00BCD4",
    },
    "En armado de planchas": {
        "category": "preprensa",
        "description": "Armado de planchas en proceso",
        "color": "#00BCD4",
    },
    "Armado de plancha": {
        "category": "preprensa",
        "description": "Preparación de plancha para impresión",
        "color": "#00BCD4",
    },
    "Listo para imprimir": {
        "category": "preprensa",
        "description": "Archivos procesados, listo para imprimir",
        "color": "#00BCD4",
    },
    "Impresión": {
        "category": "produccion",
        "description": "En proceso de impresión",
        "color": "#4CAF50",
    },
    "Sublimado / Laminado": {
        "category": "produccion",
        "description": "Proceso de sublimado o laminado",
        "color": "#00BCD4",
    },
    "Laminado": {
        "category": "produccion",
        "description": "Aplicación de laminado protector",
        "color": "#00BCD4",
    },
    "Sublimado": {
        "category": "produccion",
        "description": "Proceso de sublimación en textil",
        "color": "#00BCD4",
    },
    "Corte": {
        "category": "produccion",
        "description": "Proceso de corte y acabado",
        "color": "#795548",
    },
    "Corte plotter": {
        "category": "produccion",
        "description": "Corte de precisión en plotter",
        "color": "#795548",
    },
    "Preparación": {
        "category": "produccion",
        "description": "Preparación de materiales",
        "color": "#607D8B",
    },
    "Producción": {
        "category": "produccion",
        "description": "En proceso de producción",
        "color": "#4CAF50",
    },
    "Terminación": {
        "category": "produccion",
        "description": "Proceso de terminación final",
        "color": "#795548",
    },
    "Control de calidad": {
        "category": "produccion",
        "description": "Revisión de calidad final",
        "color": "#9C27B0",
    },
    "Finalizado": {
        "category": "cierre",
        "description": "Trabajo finalizado, listo para entrega",
        "color": "#4CAF50",
    },
    "Empaquetado": {
        "category": "cierre",
        "description": "Empaquetado para entrega",
        "color": "#4CAF50",
    },
    "Entregado": {
        "category": "cierre",
        "description": "Entregado al cliente",
        "color": "#8BC34A",
    },
}


def get_all_stages_for_mobile() -> list[dict[str, str]]:
    """Obtiene todas las etapas únicas de todos los workflows con metadatos."""
    # Recolectar etapas únicas de todos los workflows
    all_stages = set()
    for workflow in (GENERAL_WORKFLOW, VINYL_WORKFLOW, TEXTILE_WORKFLOW, FINISHING_WORKFLOW):
        all_stages.update(stage for stage, _ in workflow)
    
    # Convertir a lista con metadatos
    stages = []
    for stage in sorted(all_stages):
        metadata = STAGE_METADATA.get(stage, {
            "category": "produccion",
            "description": stage,
            "color": "#607D8B",
        })
        stages.append({
            "key": stage,
            "label": stage,
            "category": metadata["category"],
            "description": metadata["description"],
            "color": metadata["color"],
        })
    
    return stages


def get_workflows_for_mobile() -> dict[str, dict[str, str | list[str]]]:
    """Obtiene los workflows oficiales adaptados para API móvil."""
    return {
        "general": {
            "name": "Flujo general",
            "stages": [stage for stage, _ in GENERAL_WORKFLOW],
        },
        "vinilo": {
            "name": "Vinilo adhesivo",
            "stages": [stage for stage, _ in VINYL_WORKFLOW],
        },
        "textil": {
            "name": "Textil / Sublimación",
            "stages": [stage for stage, _ in TEXTILE_WORKFLOW],
        },
        "acabado": {
            "name": "Acabados especiales",
            "stages": [stage for stage, _ in FINISHING_WORKFLOW],
        },
    }
