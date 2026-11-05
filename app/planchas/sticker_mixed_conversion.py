"""Conversión no destructiva de páginas mixtas de stickers a modo Libre."""

from __future__ import annotations

from collections.abc import Sequence

from app.planchas.model import PlanchaProject


def convert_sticker_mixed_projects_to_free(projects: Sequence[PlanchaProject]) -> list[PlanchaProject]:
    """Congela páginas mixtas sin modificar ninguno de sus ``PlanchaItem``.

    Cambia exclusivamente el estado de edición del proyecto. Los objetos se
    devuelven por referencia deliberadamente: clonar implicaría el riesgo de
    alterar posición, identidad o geometría durante la conversión.
    """
    result = list(projects)
    if not result:
        raise ValueError("No hay páginas mixtas para convertir.")
    if any(project.project_type != "sticker_mixed" for project in result):
        raise ValueError("Solo se pueden convertir proyectos sticker_mixed.")
    for project in result:
        project.project_type = "sticker_free"
        project.manual_from_mixed = True
    return result
