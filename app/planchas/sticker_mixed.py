"""Packing automático multipágina para planchas mixtas de stickers.

Este módulo pertenece exclusivamente al Creador de Planchas. No reutiliza los
modelos ni el render de fotos/pósters: recibe ``PlanchaItem`` y produce
``PlanchaProject`` listos para la misma vista previa y ``render_sheet()``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.planchas.model import (
    HITBOX_INNER_CLEARANCE_CM,
    PlanchaItem,
    PlanchaProject,
    Rect,
    intersects,
    maximize_special_multipage,
    optimize_multipage,
    printable_area,
)
from app.planchas.production_geometry import proportional_production_size


@dataclass(frozen=True)
class StickerMixedLayout:
    """Resultado no destructivo del packing mixto de stickers."""

    projects: list[PlanchaProject]
    baseline_page_count: int
    scale_factor: float
    impossible_items: list[dict]

    @property
    def page_count(self) -> int:
        return len(self.projects)


class StickerMixedPacker:
    """Empaqueta stickers por su geometría productiva, no por marcos de foto."""

    def __init__(self, *, margin_cm: float = 0.15, allow_rotation: bool = True):
        self.margin_cm = float(margin_cm)
        self.allow_rotation = bool(allow_rotation)

    def pack(self, items: Sequence[PlanchaItem]) -> StickerMixedLayout:
        """Genera páginas A4 desde copias de ``PlanchaItem``.

        El baseline usa el mínimo productivo de cada nominal; después reutiliza
        la maximización geométrica existente, que no aumenta sus páginas y
        limita el crecimiento por ``production_max_for_nominal``.
        """
        source = [self._baseline_item(item) for item in items]
        self._validate_groups(source)

        can_rotate = self.allow_rotation and all(item.rotation_allowed for item in source)
        baseline = optimize_multipage(
            source, margin_cm=self.margin_cm, allow_rotation=can_rotate,
        )
        if baseline.impossible or not can_rotate:
            packed, scale = baseline, 1.0
        else:
            packed, scale = maximize_special_multipage(source, margin_cm=self.margin_cm)
        # MaxRects encuentra una solución válida, pero puede dejar escalones y
        # huecos visibles. Compactar no altera tamaños ni rotaciones.
        for page in packed.pages:
            self._compact_page(page.placed)
        projects = [self._project_from_page(page.placed) for page in packed.pages]
        return StickerMixedLayout(
            projects=projects,
            baseline_page_count=len(baseline.pages),
            scale_factor=scale,
            impossible_items=list(packed.impossible),
        )

    @staticmethod
    def _baseline_item(item: PlanchaItem) -> PlanchaItem:
        if item.nominal_size_cm is None:
            raise ValueError(f"El sticker «{item.name}» no tiene tamaño nominal definido.")
        width, height = proportional_production_size(
            item.nominal_size_cm, item.width_cm, item.height_cm,
        )
        # ``width_cm``/``height_cm`` ya expresan la orientación actual; si el
        # item estaba rotado, invertirlos otra vez deformaría su geometría.
        clone = PlanchaItem.from_dict(item.to_dict())
        clone.width_cm = width
        clone.height_cm = height
        clone.layout_width_cm = width + 2 * HITBOX_INNER_CLEARANCE_CM
        clone.layout_height_cm = height + 2 * HITBOX_INNER_CLEARANCE_CM
        return clone

    @staticmethod
    def _validate_groups(items: Sequence[PlanchaItem]) -> None:
        """Las copias de un grupo deben tener idéntica geometría base."""
        geometry_by_group: dict[str, tuple[float, float, float]] = {}
        for item in items:
            signature = (
                round(float(item.nominal_size_cm or 0), 8),
                round(max(item.width_cm, item.height_cm), 8),
                round(min(item.width_cm, item.height_cm), 8),
            )
            previous = geometry_by_group.setdefault(item.group_id, signature)
            if previous != signature:
                raise ValueError(
                    f"El grupo «{item.group_id}» contiene copias con geometrías incompatibles."
                )

    def _compact_page(self, placed: list[dict]) -> None:
        """Elimina huecos desplazando hitboxes sin cambiar el packing válido."""
        printable = printable_area(self.margin_cm)

        def rect(data: dict) -> Rect:
            return Rect(
                float(data["x_cm"]), float(data["y_cm"]),
                float(data["layout_width_cm"]), float(data["layout_height_cm"]),
            )

        # Un movimiento sólo puede mejorar la lectura: más arriba y, ante la
        # misma altura, más a la izquierda. Repetir aprovecha el hueco que
        # liberó otro elemento en la pasada anterior.
        for _ in range(len(placed)):
            changed = False
            for current in sorted(placed, key=lambda item: (float(item["y_cm"]), float(item["x_cm"]))):
                current_rect = rect(current)
                others = [rect(item) for item in placed if item is not current]
                xs = {printable.x}
                ys = {printable.y}
                for other in others:
                    xs.add(other.right)
                    ys.add(other.bottom)

                best = current_rect
                for y in sorted(value for value in ys if value <= current_rect.y + 1e-9):
                    for x in sorted(value for value in xs if value <= current_rect.x + 1e-9):
                        candidate = Rect(x, y, current_rect.width, current_rect.height)
                        if candidate.right > printable.right + 1e-9 or candidate.bottom > printable.bottom + 1e-9:
                            continue
                        if any(intersects(candidate, other) for other in others):
                            continue
                        if (candidate.y, candidate.x) < (best.y, best.x):
                            best = candidate
                if best != current_rect:
                    current["x_cm"] = best.x
                    current["y_cm"] = best.y
                    changed = True
            if not changed:
                break

    def _project_from_page(self, placed: Sequence[dict]) -> PlanchaProject:
        page_items: list[PlanchaItem] = []
        for data in placed:
            item = PlanchaItem.from_dict({
                key: value for key, value in data.items()
                if key in PlanchaItem.__dataclass_fields__
            })
            width = float(data["cut_width_cm"])
            height = float(data["cut_height_cm"])
            if data.get("rotated"):
                width, height = height, width
                item.rotation = (item.rotation + 90) % 360
            item.width_cm = width
            item.height_cm = height
            item.layout_width_cm = float(data["layout_width_cm"])
            item.layout_height_cm = float(data["layout_height_cm"])
            item.x_cm = float(data["x_cm"])
            item.y_cm = float(data["y_cm"])
            page_items.append(item)
        return PlanchaProject(
            page_items, margin_cm=self.margin_cm, layout_mode="special", workspace_format="a4",
            project_type="sticker_mixed",
        )
