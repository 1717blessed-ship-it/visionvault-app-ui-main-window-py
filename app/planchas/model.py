"""Modelo editable y no destructivo para una plancha A4."""

from __future__ import annotations

import json
import uuid
import ntpath
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from app.planchas.production_geometry import production_max_for_nominal, proportional_production_size


A4_WIDTH_CM = 21.0
A4_HEIGHT_CM = 29.7
PRINT_MARGIN_CM = 0.15
# A5 se vende como media A4 y necesita aprovechar el borde útil para que la
# media franja admita los stickers finos sin alterar la seguridad de A4.
A5_PRINT_MARGIN_CM = 0.05
# En A5 se toma un mínimo del aire de seguridad de las dos franjas completas
# para que la media franja final admita stickers finos sin escalar su diseño.
A5_FINE_BAND_EXTRA_CM = 0.24
# Cinco filas de 5,75 cm más separaciones y límite de impresión: aprovecha el
# A4 prácticamente completo sin comprometer el corte preciso del plotter.
SIZE_OFFSET_CM = 0.70
FIVE_ROW_SIZE_CM = 5.0 + SIZE_OFFSET_CM
STANDARD_SIZE_CM = FIVE_ROW_SIZE_CM
MAX_SIZE_CM = 29.70
STANDARD_FIVE_BANDS = "standard_five_bands"
SPECIAL_GEOMETRIC = "special_geometric"
PLANCHA_GROUP_NAMESPACE = uuid.UUID("5af32483-cc44-54c6-a6f2-f05e1c4cf68e")
PLANCHA_ITEM_NAMESPACE = uuid.UUID("36c55ccd-e986-5ef4-b8c2-4a1602e7b4f8")
REQUESTED_UNIT_NAMESPACE = uuid.UUID("d5b8c2c4-6a37-4d76-a822-9dc44ef3f784")
GROUP_ID_VERSION = "plancha-group-v1"
ITEM_ID_VERSION = "plancha-item-v1"
CLIENT_COLORS = ("#3b82f6", "#a855f7", "#f97316", "#16a34a", "#db2777", "#0891b2", "#ca8a04")

# El material sigue siendo una A4: estos formatos delimitan la mesa de trabajo
# que se vende/corta dentro de ella.  De este modo A5 y franja no requieren
# cambiar de impresora ni generan un PNG con medidas inesperadas.
WORKSPACE_FORMATS = {
    "a4": ("A4 completa", 1.0),
    "a5": ("A5 (media A4)", 1 / 2),
    "franja": ("Franja horizontal (1/5 A4)", 1 / 5),
}


@dataclass
class PlanchaItem:
    path: str
    name: str
    width_cm: float
    height_cm: float
    x_cm: float = 0.0
    y_cm: float = 0.0
    quantity: int = 1
    rotation: int = 0
    source: str = "Stock"
    client: str = ""
    order_number: str = ""
    order_job_title: str = ""
    locked: bool = False
    rotation_allowed: bool = False
    client_color: str = "#7a7a7a"
    group_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    copy_number: int = 1
    item_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    remove_inner_white_border: bool = False
    order_id: int | None = None
    order_job_id: int | None = None
    order_design_line_id: str = ""
    requested_unit_key: str = ""
    production_unit_kind: str = "item"
    nominal_size_cm: float | None = None
    # Snapshot del tamaño comercial del pedido; el proyecto libre puede diferir
    # sin reescribir order_designs.
    order_nominal_size_cm: float | None = None
    layout_width_cm: float | None = None
    layout_height_cm: float | None = None

    @property
    def production_width_cm(self) -> float:
        """Alias explícito: ``width_cm`` persiste el tamaño productivo."""
        return self.width_cm

    @production_width_cm.setter
    def production_width_cm(self, value: float) -> None:
        self.width_cm = float(value)

    @property
    def production_height_cm(self) -> float:
        """Alias explícito: ``height_cm`` persiste el tamaño productivo."""
        return self.height_cm

    @production_height_cm.setter
    def production_height_cm(self, value: float) -> None:
        self.height_cm = float(value)

    @property
    def reserved_width_cm(self) -> float:
        return self.layout_width_cm if self.layout_width_cm is not None else self.width_cm

    @property
    def reserved_height_cm(self) -> float:
        return self.layout_height_cm if self.layout_height_cm is not None else self.height_cm

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PlanchaItem":
        return cls(**data)


def packing_mode_for_order_designs(designs: Iterable[dict]) -> str:
    """Decide una vez por pedido usando sólo tamaños nominales."""
    sizes = [float(design.get("size_cm", 5.0) or 5.0) for design in designs]
    return STANDARD_FIVE_BANDS if all(size == 5.0 for size in sizes) else SPECIAL_GEOMETRIC


def normalize_new_packing_mode(mode: str | None) -> str | None:
    """Convierte el nombre geométrico histórico al motor moderno al crear."""
    return "sticker_mixed" if mode == SPECIAL_GEOMETRIC else mode


def normalize_identity_path(path: str) -> str:
    """Normalización textual Windows, sin requerir que el archivo exista."""
    value = str(path or "").strip().replace("/", "\\")
    return ntpath.normpath(value).replace("\\", "/").casefold()


def order_design_group_id(
    order_id: int, image_path: str, order_job_id: int | None = None,
    nominal_size_cm: float | None = None, rotation: int = 0,
) -> str:
    # Los parámetros opcionales conservan la identidad de proyectos históricos,
    # pero los nuevos armados distinguen trabajo y configuración comercial.
    key = f"{GROUP_ID_VERSION}|{int(order_id)}|{normalize_identity_path(image_path)}"
    if order_job_id is not None:
        key += f"|job:{int(order_job_id)}|size:{float(nominal_size_cm or 0):.6f}|rotation:{int(rotation) % 360}"
    return uuid.uuid5(PLANCHA_GROUP_NAMESPACE, key).hex


def order_design_item_id(group_id: str, copy_number: int) -> str:
    key = f"{ITEM_ID_VERSION}|{group_id}|{int(copy_number)}"
    return uuid.uuid5(PLANCHA_ITEM_NAMESPACE, key).hex


def requested_unit_key(
    order_id: int,
    order_job_id: int,
    image_path: str = "",
    nominal_size_cm: float = 0,
    rotation: int = 0,
    copy_number: int = 1,
    *,
    design_line_id: str = "",
) -> str:
    """Identidad estable de una unidad solicitada, no sólo del archivo.

    Una línea nueva usa su identificador persistente, independiente de ruta,
    tamaño, rotación y colocación. La rama v1 conserva compatibilidad con los
    proyectos que todavía no poseen identidad de línea.
    """
    if str(design_line_id or "").strip():
        key = "|".join((
            "requested-unit-v2", str(int(order_id)), str(int(order_job_id)),
            str(design_line_id).strip(), str(int(copy_number)),
        ))
        return uuid.uuid5(REQUESTED_UNIT_NAMESPACE, key).hex
    key = "|".join((
        "requested-unit-v1", str(int(order_id)), str(int(order_job_id)),
        normalize_identity_path(image_path), f"{float(nominal_size_cm):.6f}",
        str(int(rotation) % 360), str(int(copy_number)),
    ))
    return uuid.uuid5(REQUESTED_UNIT_NAMESPACE, key).hex


def visible_bbox(image):
    """Caja de la silueta visible, incluso en PNG/JPG con fondo blanco opaco."""
    rgba = image.convert("RGBA")
    alpha_box = rgba.getchannel("A").getbbox()
    if alpha_box and (alpha_box[2] - alpha_box[0] < rgba.width * 0.98 or alpha_box[3] - alpha_box[1] < rgba.height * 0.98):
        return _padded_box(alpha_box, rgba.size)

    # Algunos stickers se guardaron con un lienzo blanco totalmente opaco.
    # En ese caso se toma el color de las esquinas como fondo y se descarta.
    from PIL import Image, ImageChops

    corners = [rgba.getpixel((x, y))[:3] for x, y in ((0, 0), (rgba.width - 1, 0), (0, rgba.height - 1), (rgba.width - 1, rgba.height - 1))]
    background = tuple(sorted(color[channel] for color in corners)[len(corners) // 2] for channel in range(3))
    difference = ImageChops.difference(rgba.convert("RGB"), Image.new("RGB", rgba.size, background)).convert("L")
    # 20 tolera compresión JPG y antialias, sin incluir el fondo uniforme.
    mask = difference.point(lambda value: 255 if value > 20 else 0)
    content_box = mask.getbbox()
    if content_box and (content_box[2] - content_box[0] < rgba.width * 0.96 or content_box[3] - content_box[1] < rgba.height * 0.96):
        return _padded_box(content_box, rgba.size)
    return (0, 0, rgba.width, rgba.height)


def _padded_box(box, size):
    """Conserva un borde mínimo para no cortar contornos blancos del sticker."""
    left, top, right, bottom = box
    padding = max(3, round(min(size) * 0.018))
    return max(0, left - padding), max(0, top - padding), min(size[0], right + padding), min(size[1], bottom + padding)


def size_from_visible_dimensions(width: int | float, height: int | float, requested_size_cm: float = STANDARD_SIZE_CM) -> tuple[float, float]:
    """Convierte dimensiones visibles ya conocidas a centímetros de plancha."""
    width, height = float(width), float(height)
    if width <= 0 or height <= 0:
        width = height = 1
    requested_size_cm = min(max(float(requested_size_cm), 0.5), MAX_SIZE_CM)
    if width >= height:
        return requested_size_cm, round(requested_size_cm * height / width, 3)
    return round(requested_size_cm * width / height, 3), requested_size_cm


def size_for_image(path: str, requested_size_cm: float = STANDARD_SIZE_CM) -> tuple[float, float]:
    """Devuelve medidas de la silueta, sin abrir ni modificar el original."""
    try:
        from PIL import Image

        with Image.open(path) as image:
            left, top, right, bottom = visible_bbox(image)
            width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            raise ValueError
    except Exception:
        width, height = 1, 1
    return size_from_visible_dimensions(width, height, requested_size_cm)


# ============================================================
# GEOMÉTRICA DE PACKING (motor paralelo experimental)
# ============================================================

DEFAULT_MARGIN_CM = 0.5
DEFAULT_EXTRA_LAYOUT_CM = 0.75
# Sólo para special_geometric: aire interno entre producción y borde de la
# hitbox, no separación física entre stickers.
HITBOX_INNER_CLEARANCE_CM = 0.01
SPECIAL_LAYOUT_EXTRA_CM = HITBOX_INNER_CLEARANCE_CM * 2
TARGET_OCCUPANCY = 0.90
EPSILON = 1e-9


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass(frozen=True)
class LayoutSize:
    width_cm: float
    height_cm: float

    @property
    def area_cm2(self) -> float:
        return self.width_cm * self.height_cm

    @property
    def longest_side_cm(self) -> float:
        return max(self.width_cm, self.height_cm)


@dataclass(frozen=True)
class PlacementCandidate:
    x_cm: float
    y_cm: float
    layout_width_cm: float
    layout_height_cm: float
    rotated: bool
    waste_cm2: float
    short_side_waste_cm: float
    long_side_waste_cm: float


@dataclass
class PackingResult:
    placed: list[dict]
    overflow: list[Any]
    free_rectangles: list[Rect]
    packing_occupancy: float
    cut_occupancy: float
    strategy: str
    allow_rotation: bool


@dataclass
class BatchPackingResult:
    """Resultado de una simulación geométrica completa de un pedido A4."""
    pages: list[PackingResult]
    impossible: list[Any]
    strategy: str

    @property
    def total_placed(self) -> int:
        return sum(len(page.placed) for page in self.pages)

    @property
    def total_overflow(self) -> int:
        # El overflow intermedio se convierte en entrada de la página siguiente;
        # al terminar solo quedan los imposibles, almacenados por separado.
        return 0

    @property
    def rotations(self) -> int:
        return sum(1 for page in self.pages for item in page.placed if item.get("rotated"))

    @property
    def last_page_largest_free_rect_area(self) -> float:
        if not self.pages:
            return 0.0
        return max((rect.area for rect in self.pages[-1].free_rectangles), default=0.0)


def printable_area(margin_cm: float = DEFAULT_MARGIN_CM) -> Rect:
    width = A4_WIDTH_CM - (margin_cm * 2)
    height = A4_HEIGHT_CM - (margin_cm * 2)
    if width <= 0 or height <= 0:
        raise ValueError(f"Margen inválido: {margin_cm} cm.")
    return Rect(x=margin_cm, y=margin_cm, width=width, height=height)


def item_cut_size(item) -> tuple[float, float]:
    if isinstance(item, dict):
        width = float(item["cut_width_cm"])
        raw_height = item.get("cut_height_cm")
        height = width if raw_height is None else float(raw_height)
    else:
        width = float(item.width_cm)
        raw_height = getattr(item, "height_cm", None)
        height = width if raw_height is None else float(raw_height)

    if width <= 0 or height <= 0:
        raise ValueError(f"Tamaño inválido: {width} x {height} cm")
    return width, height


def effective_layout_size(cut_width_cm: float, cut_height_cm: float, extra_cm: float = DEFAULT_EXTRA_LAYOUT_CM) -> LayoutSize:
    return LayoutSize(width_cm=cut_width_cm + extra_cm, height_cm=cut_height_cm + extra_cm)


def item_layout_size(item, extra_cm: float = DEFAULT_EXTRA_LAYOUT_CM) -> LayoutSize:
    cut_w, cut_h = item_cut_size(item)
    return effective_layout_size(cut_w, cut_h, extra_cm)


def fits_in_printable_area(layout: LayoutSize, *, margin_cm: float = DEFAULT_MARGIN_CM, allow_rotation: bool = True) -> bool:
    printable = printable_area(margin_cm)
    normal = layout.width_cm <= printable.width + EPSILON and layout.height_cm <= printable.height + EPSILON
    if normal:
        return True
    if not allow_rotation:
        return False
    rotated = layout.height_cm <= printable.width + EPSILON and layout.width_cm <= printable.height + EPSILON
    return rotated


def intersects(a: Rect, b: Rect) -> bool:
    return not (
        b.x >= a.right - EPSILON
        or b.right <= a.x + EPSILON
        or b.y >= a.bottom - EPSILON
        or b.bottom <= a.y + EPSILON
    )


def contains(outer: Rect, inner: Rect, *, epsilon: float = EPSILON) -> bool:
    return (
        inner.x >= outer.x - epsilon
        and inner.y >= outer.y - epsilon
        and inner.right <= outer.right + epsilon
        and inner.bottom <= outer.bottom + epsilon
    )


def same_rect(a: Rect, b: Rect, *, epsilon: float = EPSILON) -> bool:
    return (
        abs(a.x - b.x) <= epsilon
        and abs(a.y - b.y) <= epsilon
        and abs(a.width - b.width) <= epsilon
        and abs(a.height - b.height) <= epsilon
    )


def split_free_rectangle(free: Rect, used: Rect) -> list[Rect]:
    if not intersects(free, used):
        return [free]

    result: list[Rect] = []

    if used.x > free.x + EPSILON:
        result.append(Rect(x=free.x, y=free.y, width=used.x - free.x, height=free.height))

    if used.right < free.right - EPSILON:
        result.append(Rect(x=used.right, y=free.y, width=free.right - used.right, height=free.height))

    if used.y > free.y + EPSILON:
        result.append(Rect(x=free.x, y=free.y, width=free.width, height=used.y - free.y))

    if used.bottom < free.bottom - EPSILON:
        result.append(Rect(x=free.x, y=used.bottom, width=free.width, height=free.bottom - used.bottom))

    return [rect for rect in result if rect.width > EPSILON and rect.height > EPSILON]


def prune_free_rectangles(rectangles: Sequence[Rect]) -> list[Rect]:
    clean = [rect for rect in rectangles if rect.width > EPSILON and rect.height > EPSILON]
    result: list[Rect] = []

    for i, rect in enumerate(clean):
        discard = False

        for j, other in enumerate(clean):
            if i == j:
                continue

            if same_rect(rect, other):
                if j < i:
                    discard = True
                    break
                continue

            if contains(other, rect):
                discard = True
                break

        if not discard:
            result.append(rect)

    return result


def update_free_rectangles(free_rectangles: Sequence[Rect], used: Rect) -> list[Rect]:
    updated: list[Rect] = []
    for free in free_rectangles:
        updated.extend(split_free_rectangle(free, used))
    return prune_free_rectangles(updated)


def find_best_free_rectangle(layout: LayoutSize, free_rectangles: Sequence[Rect], *, allow_rotation: bool = True) -> PlacementCandidate | None:
    orientations = [(layout.width_cm, layout.height_cm, False)]
    if allow_rotation and abs(layout.width_cm - layout.height_cm) > EPSILON:
        orientations.append((layout.height_cm, layout.width_cm, True))

    best: PlacementCandidate | None = None
    best_score: tuple[float, float, float] | None = None

    for free in free_rectangles:
        for width, height, rotated in orientations:
            if width > free.width + EPSILON or height > free.height + EPSILON:
                continue

            waste = free.area - (width * height)
            remaining_w = free.width - width
            remaining_h = free.height - height
            short_side = min(remaining_w, remaining_h)
            long_side = max(remaining_w, remaining_h)
            score = (waste, short_side, long_side)

            if best_score is None or score < best_score:
                best_score = score
                best = PlacementCandidate(
                    x_cm=free.x,
                    y_cm=free.y,
                    layout_width_cm=width,
                    layout_height_cm=height,
                    rotated=rotated,
                    waste_cm2=waste,
                    short_side_waste_cm=short_side,
                    long_side_waste_cm=long_side,
                )

    return best


def sort_items(items: Iterable, strategy: str, *, extra_cm: float = DEFAULT_EXTRA_LAYOUT_CM) -> list:
    items = list(items)

    def geometry(item):
        cut_w, cut_h = item_cut_size(item)
        layout = effective_layout_size(cut_w, cut_h, extra_cm)
        return cut_w, cut_h, layout

    if strategy == "area_desc":
        return sorted(
            items,
            key=lambda item: (geometry(item)[2].area_cm2, geometry(item)[2].longest_side_cm),
            reverse=True,
        )

    if strategy == "longest_side_desc":
        return sorted(
            items,
            key=lambda item: (geometry(item)[2].longest_side_cm, geometry(item)[2].area_cm2),
            reverse=True,
        )

    raise ValueError(f"Estrategia desconocida: {strategy}")


def _placed_rect(item):
    if isinstance(item, dict):
        x = float(item.get("x_cm", 0.0))
        y = float(item.get("y_cm", 0.0))
        width = float(item.get("layout_width_cm", item.get("width_cm", 0.0)))
        height = float(item.get("layout_height_cm", item.get("height_cm", 0.0)))
        return Rect(x=x, y=y, width=width, height=height)

    x = float(getattr(item, "x_cm", 0.0))
    y = float(getattr(item, "y_cm", 0.0))
    width = float(getattr(item, "layout_width_cm", getattr(item, "width_cm", 0.0)))
    height = float(getattr(item, "layout_height_cm", getattr(item, "height_cm", 0.0)))
    return Rect(x=x, y=y, width=width, height=height)


def validate_no_overlaps(items: Sequence) -> bool:
    rects = [_placed_rect(item) for item in items]
    for i, rect_a in enumerate(rects):
        for j in range(i + 1, len(rects)):
            if intersects(rect_a, rects[j]):
                return False
    return True


def validate_package_geometry(items: Sequence) -> bool:
    printable = printable_area(DEFAULT_MARGIN_CM)
    for item in items:
        rect = _placed_rect(item)
        if rect.width <= 0 or rect.height <= 0:
            return False
        if rect.x < printable.x - EPSILON or rect.y < printable.y - EPSILON:
            return False
        if rect.right > printable.right + EPSILON or rect.bottom > printable.bottom + EPSILON:
            return False
    return True


def validate_overflow(placed: Sequence, overflow: Sequence) -> bool:
    return bool(overflow) and not placed


def validate_free_rectangles(free_rectangles: Sequence[Rect], placed_items: Sequence, *, margin_cm: float = DEFAULT_MARGIN_CM) -> bool:
    printable = printable_area(margin_cm)
    placed_rects = [_placed_rect(item) for item in placed_items]
    for rect in free_rectangles:
        if rect.width <= EPSILON or rect.height <= EPSILON:
            return False
        if not contains(printable, rect):
            return False
        if any(intersects(rect, placed) for placed in placed_rects):
            return False
    return True


def pack_layout(
    items: Iterable,
    *,
    strategy: str = "area_desc",
    preserve_order: bool = False,
    margin_cm: float = DEFAULT_MARGIN_CM,
    extra_cm: float = DEFAULT_EXTRA_LAYOUT_CM,
    allow_rotation: bool = True,
) -> PackingResult:
    printable = printable_area(margin_cm)
    free_rectangles: list[Rect] = [printable]

    if preserve_order:
        ordered = list(items)
    else:
        ordered = sort_items(items, strategy, extra_cm=extra_cm)

    placed: list[dict] = []
    overflow: list[Any] = []

    total_layout_area = 0.0
    total_cut_area = 0.0

    for item in ordered:
        cut_w, cut_h = item_cut_size(item)
        layout = effective_layout_size(cut_w, cut_h, extra_cm)

        if not fits_in_printable_area(layout, margin_cm=margin_cm, allow_rotation=allow_rotation):
            overflow.append(item)
            continue

        candidate = find_best_free_rectangle(layout, free_rectangles, allow_rotation=allow_rotation)
        if candidate is None:
            overflow.append(item)
            continue

        used = Rect(
            x=candidate.x_cm,
            y=candidate.y_cm,
            width=candidate.layout_width_cm,
            height=candidate.layout_height_cm,
        )

        placed_item = {
            **(item if isinstance(item, dict) else item.to_dict()),
            "cut_width_cm": cut_w,
            "cut_height_cm": cut_h,
            "x_cm": candidate.x_cm,
            "y_cm": candidate.y_cm,
            "layout_width_cm": candidate.layout_width_cm,
            "layout_height_cm": candidate.layout_height_cm,
            "rotated": candidate.rotated,
        }
        placed.append(placed_item)

        total_layout_area += candidate.layout_width_cm * candidate.layout_height_cm
        total_cut_area += cut_w * cut_h

        free_rectangles = update_free_rectangles(free_rectangles, used)

    printable_area_cm2 = printable.area
    packing_occupancy = total_layout_area / printable_area_cm2 if printable_area_cm2 else 0.0
    cut_occupancy = total_cut_area / printable_area_cm2 if printable_area_cm2 else 0.0

    return PackingResult(
        placed=placed,
        overflow=overflow,
        free_rectangles=free_rectangles,
        packing_occupancy=packing_occupancy,
        cut_occupancy=cut_occupancy,
        strategy=strategy,
        allow_rotation=allow_rotation,
    )


def result_score(result: PackingResult) -> tuple[int, float, float]:
    return (
        len(result.placed),
        result.packing_occupancy,
        result.cut_occupancy,
    )


def optimize_layout(items: Iterable, *, margin_cm: float = DEFAULT_MARGIN_CM, extra_cm: float = DEFAULT_EXTRA_LAYOUT_CM, target_occupancy: float = TARGET_OCCUPANCY) -> PackingResult:
    items = list(items)

    if not items:
        return pack_layout([], margin_cm=margin_cm, extra_cm=extra_cm)

    primary_order = sort_items(items, "area_desc", extra_cm=extra_cm)
    primary = pack_layout(primary_order, strategy="area_desc", preserve_order=True, margin_cm=margin_cm, extra_cm=extra_cm, allow_rotation=True)

    if not primary.overflow and primary.packing_occupancy >= target_occupancy:
        return primary

    longest_order = sort_items(items, "longest_side_desc", extra_cm=extra_cm)
    longest = pack_layout(longest_order, strategy="longest_side_desc", preserve_order=True, margin_cm=margin_cm, extra_cm=extra_cm, allow_rotation=True)

    no_rotation = pack_layout(primary_order, strategy="area_desc", preserve_order=True, margin_cm=margin_cm, extra_cm=extra_cm, allow_rotation=False)

    candidates = [primary, longest, no_rotation]
    return max(candidates, key=result_score)


def geometric_pack(items: Iterable, *, extra_cm: float = SPECIAL_LAYOUT_EXTRA_CM, allow_rotation: bool = True, strategy: str = "area_desc") -> PackingResult:
    ordered = sort_items(items, strategy, extra_cm=extra_cm)
    return pack_layout(ordered, strategy=strategy, preserve_order=False, margin_cm=DEFAULT_MARGIN_CM, extra_cm=extra_cm, allow_rotation=allow_rotation)


def _packing_item(item: Any) -> dict[str, Any]:
    """Convierte un item de plancha sin cambiar su tamaño físico."""
    data = item.to_dict() if isinstance(item, PlanchaItem) else dict(item)
    data["cut_width_cm"] = float(data["cut_width_cm"] if "cut_width_cm" in data else data["width_cm"])
    data["cut_height_cm"] = float(data["cut_height_cm"] if "cut_height_cm" in data else data["height_cm"])
    return data


def pack_all_pages(
    items: Iterable,
    *,
    strategy: str,
    margin_cm: float = DEFAULT_MARGIN_CM,
    extra_cm: float = DEFAULT_EXTRA_LAYOUT_CM,
    allow_rotation: bool = True,
) -> BatchPackingResult:
    """Empaqueta un pedido completo con una única estrategia por lote.

    Cada página vuelve a partir de una mesa A4 vacía. Los ítems imposibles se
    separan antes de iterar para evitar un bucle sobre el mismo overflow.
    """
    remaining: list[dict[str, Any]] = []
    impossible: list[dict[str, Any]] = []
    for item in items:
        data = _packing_item(item)
        layout = effective_layout_size(data["cut_width_cm"], data["cut_height_cm"], extra_cm)
        if fits_in_printable_area(layout, margin_cm=margin_cm, allow_rotation=allow_rotation):
            remaining.append(data)
        else:
            printable = printable_area(margin_cm)
            cut_w, cut_h = data["cut_width_cm"], data["cut_height_cm"]
            production_fits = (
                (cut_w <= printable.width + EPSILON and cut_h <= printable.height + EPSILON)
                or (allow_rotation and cut_h <= printable.width + EPSILON and cut_w <= printable.height + EPSILON)
            )
            data["impossible_reason"] = (
                "La producción mínima requerida excede el área imprimible A4."
                if not production_fits else
                "La hitbox requerida no entra en el área imprimible A4."
            )
            impossible.append(data)

    pages: list[PackingResult] = []
    while remaining:
        ordered = sort_items(remaining, strategy, extra_cm=extra_cm)
        page = pack_layout(
            ordered,
            strategy=strategy,
            preserve_order=True,
            margin_cm=margin_cm,
            extra_cm=extra_cm,
            allow_rotation=allow_rotation,
        )
        if not page.placed:
            impossible.extend(page.overflow)
            break
        pages.append(page)
        remaining = list(page.overflow)
    return BatchPackingResult(pages=pages, impossible=impossible, strategy=strategy)


def optimize_multipage(
    items: Iterable,
    *,
    margin_cm: float = DEFAULT_MARGIN_CM,
    extra_cm: float = SPECIAL_LAYOUT_EXTRA_CM,
    allow_rotation: bool = True,
) -> BatchPackingResult:
    """Elige una estrategia global para todo el pedido, no por página."""
    source = [_packing_item(item) for item in items]
    area = pack_all_pages(source, strategy="area_desc", margin_cm=margin_cm, extra_cm=extra_cm, allow_rotation=allow_rotation)
    longest = pack_all_pages(source, strategy="longest_side_desc", margin_cm=margin_cm, extra_cm=extra_cm, allow_rotation=allow_rotation)

    def score(candidate: BatchPackingResult) -> tuple[int, int, float, int, int]:
        # El último término mantiene area_desc ante un empate total.
        return (
            len(candidate.impossible),
            len(candidate.pages),
            -candidate.last_page_largest_free_rect_area,
            candidate.rotations,
            0 if candidate.strategy == "area_desc" else 1,
        )

    return min((area, longest), key=score)


def maximize_special_multipage(items: Iterable, *, margin_cm: float, tolerance: float = 0.0001) -> tuple[BatchPackingResult, float]:
    """Maximiza con una escala global sin superar las páginas baseline.

    MaxRects sigue intacto: sólo recibe rectángulos candidatos ya escalados.
    """
    source = [_packing_item(item) for item in items]
    baseline = optimize_multipage(source, margin_cm=margin_cm)
    if baseline.impossible or not baseline.pages:
        return baseline, 1.0
    baseline_pages = len(baseline.pages)
    printable = printable_area(margin_cm)
    physical_high = min(
        max(printable.width / max(data["cut_width_cm"], 1e-9), printable.height / max(data["cut_height_cm"], 1e-9))
        for data in source
    )
    commercial_high = min(
        production_max_for_nominal(float(data.get("nominal_size_cm") or max(data["cut_width_cm"], data["cut_height_cm"])))
        / max(data["cut_width_cm"], data["cut_height_cm"])
        for data in source
    )
    high = min(physical_high, commercial_high)
    low = 1.0

    def candidate(scale: float):
        return [{**data, "cut_width_cm": data["cut_width_cm"] * scale,
                 "cut_height_cm": data["cut_height_cm"] * scale,
                 "width_cm": data["cut_width_cm"] * scale,
                 "height_cm": data["cut_height_cm"] * scale} for data in source]

    best = baseline
    while high - low > tolerance:
        mid = (low + high) / 2
        result = optimize_multipage(candidate(mid), margin_cm=margin_cm)
        if not result.impossible and len(result.pages) <= baseline_pages and sum(len(p.placed) for p in result.pages) == len(source):
            low, best = mid, result
        else:
            high = mid
    return best, low


class PlanchaProject:
    """Proyecto A4: solo guarda referencias y posiciones, nunca altera imágenes."""

    def __init__(self, items: list[PlanchaItem] | None = None, margin_cm: float = PRINT_MARGIN_CM,
                 gap_cm: float = 0.05, layout_mode: str = "classic", workspace_format: str = "a4",
                 project_type: str = "legacy", manual_from_mixed: bool = False):
        self.items = items or []
        self.margin_cm = float(margin_cm)
        self.gap_cm = float(gap_cm)
        self.layout_mode = "special" if layout_mode == "special" else "classic"
        self.workspace_format = workspace_format if workspace_format in WORKSPACE_FORMATS else "a4"
        self.project_type = project_type if project_type in {"sticker_standard", "sticker_mixed", "sticker_free", "legacy"} else "legacy"
        self.manual_from_mixed = bool(manual_from_mixed)

    @classmethod
    def from_images(cls, images: list[dict]) -> "PlanchaProject":
        items = []
        for image in images:
            # Obtener cantidad desde el pedido (order_quantity) o usar 1 por defecto
            quantity = int(image.get("order_quantity", 1) or 1)
            
            # Obtener tamaño desde el pedido (order_size_cm) si está disponible
            if image.get("order_size_cm"):
                nominal_size = float(image.get("order_size_cm"))
                requested_size = nominal_size
                if image.get("visible_width") and image.get("visible_height"):
                    width, height = proportional_production_size(
                        requested_size, image["visible_width"], image["visible_height"],
                    )
                else:
                    width, height = size_for_image(image["path"], requested_size)
                    # Sin dimensiones indexadas se conserva el aspecto que
                    # devolvió el archivo y se lleva su lado mayor a producción.
                    major = max(width, height)
                    factor = proportional_production_size(requested_size, 1, 1)[0] / major
                    width, height = width * factor, height * factor
            else:
                # Sin tamaño específico del pedido, usar el cálculo normal
                nominal_size = 5.0
                if image.get("visible_width") and image.get("visible_height"):
                    width, height = proportional_production_size(nominal_size, image["visible_width"], image["visible_height"])
                else:
                    width, height = size_for_image(image["path"], nominal_size)
                    major = max(width, height)
                    production_major = proportional_production_size(nominal_size, 1, 1)[0]
                    width, height = width * production_major / major, height * production_major / major
            
            # Crear múltiples items según la cantidad solicitada
            order_id = image.get("order_id")
            order_job_id = image.get("order_job_id")
            if image.get("order_packing_mode") == STANDARD_FIVE_BANDS:
                # El slot clásico no cambia: sólo se aprovecha hasta dejar el
                # clearance interno y sin superar el máximo comercial.
                production_major = min(production_max_for_nominal(nominal_size), FIVE_ROW_SIZE_CM - 0.02)
                current_major = max(width, height)
                width, height = width * production_major / current_major, height * production_major / current_major
            
            # Conservar la orientación física del diseño. El empaquetador
            # puede rotar una copia cuando sea conveniente, pero la creación
            # del item no debe alterar el ancho/alto ni la rotación original.
            rotation = int(image.get("rotation", 0) or 0) % 360
            design_line_id = str(image.get("order_design_line_id") or "").strip()
            
            group_id = order_design_group_id(
                order_id, image["path"], order_job_id, nominal_size, rotation,
            ) if order_id is not None else uuid.uuid4().hex
            copy_numbers = image.get("order_copy_numbers")
            if copy_numbers is None:
                copy_numbers = range(1, quantity + 1)
            else:
                copy_numbers = [max(1, int(value)) for value in copy_numbers]
            for copy_num in copy_numbers:
                item_id = order_design_item_id(group_id, copy_num) if order_id is not None else uuid.uuid4().hex
                unit_key = ""
                if order_id is not None and order_job_id is not None:
                    unit_key = requested_unit_key(
                        int(order_id), int(order_job_id), image["path"], nominal_size,
                        rotation, copy_num, design_line_id=design_line_id,
                    )
                items.append(PlanchaItem(
                    path=image["path"], 
                    name=image.get("name") or Path(image["path"]).name, 
                    width_cm=width, 
                    height_cm=height,
                    quantity=1,  # Cada item representa 1 unidad
                    copy_number=copy_num,
                    group_id=group_id,
                    item_id=item_id,
                    order_id=order_id,
                    order_job_id=int(order_job_id) if order_job_id is not None else None,
                    client=str(image.get("client") or ""),
                    order_number=str(image.get("order_number") or ""),
                    order_job_title=str(image.get("order_job_title") or ""),
                    order_design_line_id=design_line_id,
                    requested_unit_key=unit_key,
                    production_unit_kind=str(image.get("production_unit_kind") or "item"),
                    nominal_size_cm=nominal_size,
                    order_nominal_size_cm=nominal_size if order_id is not None else None,
                    rotation=rotation,
                    rotation_allowed=True,  # Permitir rotación adicional para optimizar packing
                    # En estándar 5,70 cm es el lado mayor productivo + la
                    # guarda, no una celda cuadrada: un diseño 2:1 conserva
                    # su lado corto real y puede aprovechar la franja.
                    layout_width_cm=(width + 2 * HITBOX_INNER_CLEARANCE_CM)
                    if image.get("order_packing_mode") == STANDARD_FIVE_BANDS else width,
                    layout_height_cm=(height + 2 * HITBOX_INNER_CLEARANCE_CM)
                    if image.get("order_packing_mode") == STANDARD_FIVE_BANDS else height,
                ))
        return cls(items)

    @property
    def usable_width(self) -> float:
        return A4_WIDTH_CM - self.margin_cm * 2

    @property
    def usable_height(self) -> float:
        return (A4_HEIGHT_CM - self.margin_cm * 2) * self.workspace_ratio

    @property
    def workspace_ratio(self) -> float:
        return WORKSPACE_FORMATS[self.workspace_format][1]

    @property
    def workspace_label(self) -> str:
        return WORKSPACE_FORMATS[self.workspace_format][0]

    @property
    def workspace_bottom_cm(self) -> float:
        return self.margin_cm + self.usable_height

    def production_band_heights(self) -> list[float]:
        """Filas reales del formato de venta, siempre medidas desde una A4."""
        full_band = (A4_HEIGHT_CM - self.margin_cm * 2) / 5
        if self.workspace_format == "a5":
            # A5 apaisada: dos franjas A4 completas y la media franja restante
            # reservada para diseños finos horizontales. El ajuste reparte
            # 0,24 cm de borde de seguridad de las filas superiores hacia la
            # franja fina; nunca cambia la proporción ni escala del sticker.
            recovered = min(A5_FINE_BAND_EXTRA_CM, max(0.0, full_band - 0.10))
            return [full_band - recovered / 2, full_band - recovered / 2,
                    self.usable_height - full_band * 2 + recovered]
        if self.workspace_format == "franja":
            return [self.usable_height]
        return [full_band] * 5

    def band_index_for_y(self, y_cm: float) -> int:
        offset = max(0.0, y_cm - self.margin_cm)
        total = 0.0
        for index, height in enumerate(self.production_band_heights()):
            total += height
            if offset < total:
                return index
        return len(self.production_band_heights()) - 1

    def keep_inside_print_area(self) -> None:
        """Evita que una posición guardada o bloqueada recorte el sticker al exportar."""
        for item in self.items:
            max_x = max(self.margin_cm, A4_WIDTH_CM - self.margin_cm - item.reserved_width_cm)
            max_y = max(self.margin_cm, self.workspace_bottom_cm - item.reserved_height_cm)
            item.x_cm = round(min(max(self.margin_cm, item.x_cm), max_x), 3)
            item.y_cm = round(min(max(self.margin_cm, item.y_cm), max_y), 3)

    def optimize(self, progress=None) -> list[PlanchaItem]:
        if self.layout_mode == "special":
            return self._optimize_special(progress)
        return self._optimize_five_bands(progress)

        # Implementación anterior: conservada debajo como referencia de proyecto.
        """Elige la mejor combinación posible, incluso si debe reemplazar diseños.

        Se prueban varios órdenes de acomodo con *todos* los stickers, incluidos
        los que habían quedado afuera. De esta forma un diseño grande puede salir
        de la plancha si dos o más de los sobrantes aprovechan mejor el área.
        """
        best_project: PlanchaProject | None = None
        best_overflow: list[PlanchaItem] = []
        best_score = (-1.0, -1)

        strategies = ("area", "alto", "ancho", "equilibrado")
        if progress:
            progress(0, len(strategies), "Preparando combinaciones")
        for index, strategy in enumerate(strategies, start=1):
            trial_items = [PlanchaItem.from_dict(item.to_dict()) for item in self.items]
            trial = PlanchaProject(trial_items, self.margin_cm, self.gap_cm)
            overflow = trial._optimize_single(strategy)
            overflow_ids = {item.item_id for item in overflow}
            used_area = sum(
                item.width_cm * item.height_cm
                for item in trial.items
                if item.item_id not in overflow_ids
            )
            # Ante la misma superficie, conviene conservar más diseños en la hoja.
            score = (round(used_area, 6), len(trial.items) - len(overflow))
            if score > best_score:
                best_project, best_overflow, best_score = trial, overflow, score
            if progress:
                progress(index, len(strategies), f"Probando distribución {index} de {len(strategies)}")

        if best_project is None:
            return []

        best_by_id = {item.item_id: item for item in best_project.items}
        for item in self.items:
            result = best_by_id[item.item_id]
            item.x_cm = result.x_cm
            item.y_cm = result.y_cm
        self.keep_inside_print_area()

        original_by_id = {item.item_id: item for item in self.items}
        return [original_by_id[item.item_id] for item in best_overflow]

    def _optimize_locked_five_bands(self, progress=None) -> list[PlanchaItem]:
        """Respeta posiciones bloqueadas usando el acomodo lineal tradicional."""
        band_heights = self.production_band_heights()
        row_count = len(band_heights)
        left, top = self.margin_cm, self.margin_cm
        gap = self.gap_cm
        overflow: list[PlanchaItem] = []
        rows: list[list[PlanchaItem]] = [[] for _ in range(row_count)]
        widths = [0.0] * row_count

        # Locked stickers preserve their manual location and reserve their row.
        for item in self.items:
            if not item.locked:
                continue
            row_index = self.band_index_for_y(item.y_cm)
            rows[row_index].append(item)
            widths[row_index] = max(widths[row_index], item.x_cm + item.width_cm - left + gap)

        current_row = 0
        sequence = [item for item in self.items if not item.locked]
        total = max(1, len(sequence))
        if progress:
            progress(0, total, "Organizando las 5 franjas")

        def place_in_row(item: PlanchaItem) -> int | None:
            nonlocal current_row
            if item.width_cm > self.usable_width + 0.0001:
                return None
            for row_index in range(current_row, row_count):
                if item.height_cm > band_heights[row_index] - gap + 0.0001:
                    continue
                required = item.width_cm if not rows[row_index] else item.width_cm + gap
                if widths[row_index] + required <= self.usable_width + 0.0001:
                    current_row = row_index
                    return row_index
            return None

        for index, item in enumerate(sequence, start=1):
            row_index = place_in_row(item)
            if row_index is None and item.rotation_allowed:
                item.width_cm, item.height_cm = item.height_cm, item.width_cm
                row_index = place_in_row(item)
                if row_index is not None:
                    item.rotation = (item.rotation + 90) % 360
                else:
                    item.width_cm, item.height_cm = item.height_cm, item.width_cm
            if row_index is None:
                overflow.append(item)
            else:
                rows[row_index].append(item)
                widths[row_index] += item.width_cm if widths[row_index] <= 0 else item.width_cm + gap
            if progress and (index == total or index % 4 == 0):
                progress(index, total, f"Completando franja {min(current_row + 1, row_count)} de {row_count}")

        # Justify each row independently. It removes the visible unused strip
        # on either side without moving a sticker into another band.
        for row_index, row in enumerate(rows):
            if not row:
                continue
            if any(item.locked for item in row):
                continue
            row.sort(key=lambda item: self.items.index(item))
            used_width = sum(item.width_cm for item in row)
            tallest = max(item.height_cm for item in row)
            y = top + sum(band_heights[:row_index]) + (band_heights[row_index] - gap - tallest) / 2
            if len(row) == 1:
                row[0].x_cm = round(left + (self.usable_width - used_width) / 2, 3)
            else:
                row_gap = max(gap, (self.usable_width - used_width) / (len(row) - 1))
                x = left
                for item in row:
                    item.x_cm = round(x, 3)
                    x += item.width_cm + row_gap
            for item in row:
                item.y_cm = round(y + (tallest - item.height_cm) / 2, 3)

        self.keep_inside_print_area()
        return overflow

    def _optimize_five_bands(self, progress=None) -> list[PlanchaItem]:
        """Arma cinco franjas estrictas, de arriba hacia abajo.

        Cada franja comparte una única coordenada ``y``: las hitboxes nunca
        quedan escalonadas. Se ordenan por superficie descendente y se llena
        primero la fila superior donde entre cada diseño (first-fit decreasing),
        para conservar una lectura y corte claros de izquierda a derecha.
        """
        if any(item.locked for item in self.items):
            return self._optimize_locked_five_bands(progress)

        band_heights = self.production_band_heights()
        row_count = len(band_heights)
        left, top = self.margin_cm, self.margin_cm
        gap = self.gap_cm
        capacity = self.usable_width
        indexed = list(enumerate(self.items))

        def choices(item: PlanchaItem) -> list[tuple[float, float, bool]]:
            options: list[tuple[float, float, bool]] = []
            if item.reserved_width_cm <= capacity + 0.0001 and item.reserved_height_cm <= max(band_heights) - gap + 0.0001:
                options.append((item.reserved_width_cm, item.reserved_height_cm, False))
            a5_fine_portrait = (
                self.workspace_format == "a5"
                and item.reserved_height_cm > item.reserved_width_cm
                and item.reserved_width_cm <= band_heights[-1] + 0.0001
            )
            if (item.rotation_allowed or a5_fine_portrait) and item.reserved_height_cm <= capacity + 0.0001 and item.reserved_width_cm <= max(band_heights) - gap + 0.0001:
                options.append((item.reserved_height_cm, item.reserved_width_cm, True))
            return options

        def row_safety(row_index: int) -> float:
            # La media franja A5 es el único caso donde se permite usar el
            # borde de aire de la hitbox para los diseños finos.
            return 0.0 if self.workspace_format == "a5" and row_index == row_count - 1 else gap

        def pack(strategy: str):
            rows: list[list[tuple[int, PlanchaItem, float, float, bool]]] = [[] for _ in range(row_count)]
            widths = [0.0] * row_count
            overflow: list[PlanchaItem] = []

            def ordering(entry: tuple[int, PlanchaItem]):
                index, item = entry
                options = choices(item)
                if not options:
                    return (0.0, 0.0, index)
                width, height, _rotated = max(options, key=lambda option: option[0] * option[1])
                if strategy == "ancho":
                    return (-width, -height, index)
                if strategy == "alto":
                    return (-height, -width, index)
                if strategy == "cadena":
                    return (index, 0.0, 0.0)
                is_a5_fine = self.workspace_format == "a5" and any(
                    option_width > option_height and option_height <= band_heights[-1] + 0.0001
                    for option_width, option_height, _rotated in options
                )
                return (1 if is_a5_fine else 0, -(width * height), -width, index)

            # La superficie mayor define primero el aprovechamiento de la
            # plancha. El índice conserva un resultado estable en empates.
            sequence = sorted(indexed, key=ordering)
            for index, item in sequence:
                best: tuple[tuple[int, int], int, float, float, bool] | None = None
                item_has_a5_fine_orientation = self.workspace_format == "a5" and any(
                    option_width > option_height and option_height <= band_heights[-1] + 0.0001
                    for option_width, option_height, _rotated in choices(item)
                )
                for width, height, rotated in choices(item):
                    is_a5_fine = (
                        self.workspace_format == "a5"
                        and width > height
                        and height <= band_heights[-1] + 0.0001
                    )
                    allowed_rows = (row_count - 1,) if item_has_a5_fine_orientation else range(row_count - 1 if self.workspace_format == "a5" else row_count)
                    for row_index in allowed_rows:
                        if self.workspace_format == "a5" and row_index == row_count - 1 and len(rows[row_index]) >= 3:
                            continue
                        if height > band_heights[row_index] - row_safety(row_index) + 0.0001:
                            continue
                        required = width + (gap if rows[row_index] else 0.0)
                        if widths[row_index] + required > capacity + 0.0001:
                            continue
                        # Orden estricto: la primera franja que admita el
                        # diseño es la elegida. No se salta una fila superior
                        # para completar una inferior.
                        candidate = ((row_index, 1 if rotated else 0), row_index, width, height, rotated)
                        if best is None or candidate[0] < best[0]:
                            best = candidate
                if best is None:
                    overflow.append(item)
                    continue
                _score, row_index, width, height, rotated = best
                rows[row_index].append((index, item, width, height, rotated))
                widths[row_index] += width + (gap if len(rows[row_index]) > 1 else 0.0)

            area = sum(width * height for row in rows for _index, _item, width, height, _rotated in row)
            remainder = sum((capacity - width) ** 2 for width in widths)
            return rows, overflow, (round(area, 6), sum(len(row) for row in rows), -round(remainder, 6))

        # Una sola estrategia evita que un resultado equivalente cambie el
        # orden visual de las cinco franjas.
        strategies = ("área",)
        best_rows: list[list[tuple[int, PlanchaItem, float, float, bool]]] = []
        best_overflow: list[PlanchaItem] = list(self.items)
        best_score = (-1.0, -1, float("-inf"))
        if progress:
            progress(0, len(strategies), "Buscando la distribución más compacta")
        for step, strategy in enumerate(strategies, start=1):
            rows, overflow, score = pack(strategy)
            if score > best_score:
                best_rows, best_overflow, best_score = rows, overflow, score
            if progress:
                progress(step, len(strategies), f"Probando distribución {step} de {len(strategies)}")

        def fill_percent(row_index: int) -> float:
            row = best_rows[row_index]
            used_area = sum(width * height for _index, _item, width, height, _rotated in row)
            available_area = capacity * band_heights[row_index]
            return used_area / available_area if available_area else 0.0

        # El corte se lee arriba → abajo: primero se muestra la franja con
        # mayor aprovechamiento. En A5, la media franja de finos queda última.
        if self.workspace_format == "a5":
            regular_order = sorted(range(row_count - 1), key=fill_percent, reverse=True)
            best_rows = [best_rows[index] for index in regular_order] + [best_rows[-1]]
            band_heights = [band_heights[index] for index in regular_order] + [band_heights[-1]]
        else:
            order = sorted(range(row_count), key=fill_percent, reverse=True)
            best_rows = [best_rows[index] for index in order]
            band_heights = [band_heights[index] for index in order]

        for row_index, row in enumerate(best_rows):
            if not row:
                continue
            # La fila conserva el orden de prioridad por superficie con el que
            # se llenó. Así la lectura visual es siempre izquierda → derecha.
            used_width = sum(width for _index, _item, width, _height, _rotated in row)
            row_height = max(height for _index, _item, _width, height, _rotated in row)
            if len(row) == 1:
                x = left + (capacity - used_width) / 2
                row_gap = gap
            else:
                # Primero se compactan junto al sticker anterior; después el
                # sobrante de la línea se reparte parejo entre todos los pares.
                row_gap = max(gap, (capacity - used_width) / (len(row) - 1))
                x = left
            # Coordenada Y única por franja: todas las hitboxes de la línea
            # arrancan exactamente en el mismo lugar.
            y = top + sum(band_heights[:row_index]) + max(0.0, (band_heights[row_index] - row_height) / 2)
            for _index, item, width, height, rotated in row:
                if rotated:
                    item.width_cm, item.height_cm = item.height_cm, item.width_cm
                    item.layout_width_cm, item.layout_height_cm = width, height
                    item.rotation = (item.rotation + 90) % 360
                item.x_cm = round(x, 3)
                # Los finos de la media franja A5 se centran respecto del más
                # alto de su hilera; así no quedan pegados arriba ni abajo.
                vertical_offset = (row_height - height) / 2 if self.workspace_format == "a5" and row_index == row_count - 1 else 0.0
                item.y_cm = round(y + vertical_offset, 3)
                x += width + row_gap

        self.keep_inside_print_area()
        return best_overflow

    def _optimize_geometric(self, progress=None) -> list[PlanchaItem]:
        items = [item.to_dict() for item in self.items]
        result = geometric_pack(items, extra_cm=SPECIAL_LAYOUT_EXTRA_CM, allow_rotation=True, strategy="area_desc")

        placed_by_id = {item["item_id"]: item for item in result.placed if "item_id" in item}
        overflow_ids = {item["item_id"] for item in result.overflow if isinstance(item, dict) and "item_id" in item}

        for original in self.items:
            placed = placed_by_id.get(original.item_id)
            if placed is None:
                continue

            cut_w = float(placed["cut_width_cm"])
            cut_h = float(placed["cut_height_cm"])
            if placed.get("rotated"):
                original.width_cm = cut_h
                original.height_cm = cut_w
                original.rotation = (original.rotation + 90) % 360
            else:
                original.width_cm = cut_w
                original.height_cm = cut_h

            original.x_cm = round(float(placed["x_cm"]) + DEFAULT_EXTRA_LAYOUT_CM / 2, 3)
            original.y_cm = round(float(placed["y_cm"]) + DEFAULT_EXTRA_LAYOUT_CM / 2, 3)

        self.keep_inside_print_area()
        return [item for item in self.items if item.item_id in overflow_ids]

    def _optimize_row_first(self, progress=None) -> list[PlanchaItem]:
        return self._optimize_five_bands(progress)
        """Acomodo veloz de producción: arriba→derecha y luego la fila siguiente.

        Los diseños de tamaño especial se reservan primero. Los predeterminados
        conservan el orden en que fueron elegidos, por lo que se leen y cortan
        naturalmente de izquierda a derecha. Solo rota un diseño si el usuario
        autorizó la rotación y así entra en un espacio disponible.
        """
        self.keep_inside_print_area()
        left, top = self.margin_cm, self.margin_cm
        right, bottom = A4_WIDTH_CM - self.margin_cm, A4_HEIGHT_CM - self.margin_cm
        gap = self.gap_cm
        overflow: list[PlanchaItem] = []
        placed = [item for item in self.items if item.locked]
        ordered = [(index, item) for index, item in enumerate(self.items) if not item.locked]
        # Los grandes fijan la estructura; el resto completa los huecos en el
        # mismo orden con el que llegó a la plancha.
        large = [(index, item) for index, item in ordered if max(item.width_cm, item.height_cm) > STANDARD_SIZE_CM + 0.02]
        standard = [(index, item) for index, item in ordered if max(item.width_cm, item.height_cm) <= STANDARD_SIZE_CM + 0.02]
        sequence = [item for _index, item in large] + [item for _index, item in standard]

        def fits(item: PlanchaItem, x: float, y: float) -> bool:
            if x < left or y < top or x + item.width_cm > right + 0.0001 or y + item.height_cm > bottom + 0.0001:
                return False
            for other in placed:
                if not (
                    x + item.width_cm + gap <= other.x_cm + 0.0001
                    or other.x_cm + other.width_cm + gap <= x + 0.0001
                    or y + item.height_cm + gap <= other.y_cm + 0.0001
                    or other.y_cm + other.height_cm + gap <= y + 0.0001
                ):
                    return False
            return True

        def first_position(item: PlanchaItem):
            xs, ys = {left}, {top}
            for other in placed:
                xs.add(round(other.x_cm + other.width_cm + gap, 3))
                ys.add(round(other.y_cm + other.height_cm + gap, 3))
            for y in sorted(ys):
                for x in sorted(xs):
                    if fits(item, x, y):
                        return round(x, 3), round(y, 3)
            return None

        total = max(1, len(sequence))
        if progress:
            progress(0, total, "Acomodando stickers por filas")
        for index, item in enumerate(sequence, start=1):
            position = first_position(item)
            if position is None and item.rotation_allowed:
                item.width_cm, item.height_cm = item.height_cm, item.width_cm
                rotated_position = first_position(item)
                if rotated_position is not None:
                    item.rotation = (item.rotation + 90) % 360
                    position = rotated_position
                else:
                    item.width_cm, item.height_cm = item.height_cm, item.width_cm
            if position is None:
                overflow.append(item)
            else:
                item.x_cm, item.y_cm = position
                placed.append(item)
            if progress and (index == total or index % 4 == 0):
                progress(index, total, "Completando filas de la plancha")

        self.keep_inside_print_area()
        return overflow

    def _optimize_special(self, progress=None) -> list[PlanchaItem]:
        """Acomoda tamaños variados sin la restricción de cinco franjas.

        Las filas se crean según el alto real de los stickers: es la segunda
        plancha para formatos especiales y conserva siempre sus medidas.
        """
        left, top = self.margin_cm, self.margin_cm
        gap = self.gap_cm
        rows: list[dict] = []
        overflow: list[PlanchaItem] = []
        sequence = sorted(
            self.items,
            key=lambda item: (-(item.width_cm * item.height_cm), -item.height_cm, -item.width_cm, item.item_id),
        )
        total = max(1, len(sequence))
        if progress:
            progress(0, total, "Organizando tamaños especiales")

        for index, item in enumerate(sequence, start=1):
            options = [(item.width_cm, item.height_cm, False)]
            if item.rotation_allowed:
                options.append((item.height_cm, item.width_cm, True))
            choice = None
            for width, height, rotated in options:
                if width > self.usable_width + 0.0001 or height > self.usable_height + 0.0001:
                    continue
                for row in rows:
                    required = width + (gap if row["items"] else 0.0)
                    if height <= row["height"] + 0.0001 and row["width"] + required <= self.usable_width + 0.0001:
                        choice = (row, width, height, rotated)
                        break
                if choice is not None:
                    break
                used_height = sum(row["height"] for row in rows) + gap * len(rows)
                if used_height + height <= self.usable_height + 0.0001:
                    row = {"y": top + used_height, "height": height, "width": 0.0, "items": []}
                    rows.append(row)
                    choice = (row, width, height, rotated)
                    break
            if choice is None:
                overflow.append(item)
            else:
                row, width, height, rotated = choice
                x = left + row["width"] + (gap if row["items"] else 0.0)
                if rotated:
                    item.width_cm, item.height_cm = width, height
                    item.rotation = (item.rotation + 90) % 360
                item.x_cm, item.y_cm = round(x, 3), round(row["y"], 3)
                row["width"] += width + (gap if row["items"] else 0.0)
                row["items"].append(item)
            if progress and (index == total or index % 4 == 0):
                progress(index, total, "Completando plancha especial")

        self.keep_inside_print_area()
        return overflow

    def _optimize_single(self, strategy: str) -> list[PlanchaItem]:
        """Ejecuta una alternativa de acomodo para que ``optimize`` la compare."""
        self.keep_inside_print_area()
        left = self.margin_cm
        top = self.margin_cm
        right = A4_WIDTH_CM - self.margin_cm
        bottom = A4_HEIGHT_CM - self.margin_cm
        gap = self.gap_cm
        overflow: list[PlanchaItem] = []
        placed = [item for item in self.items if item.locked]

        def fits(item: PlanchaItem, x: float, y: float) -> bool:
            if x < left or y < top or x + item.width_cm > right + 0.0001 or y + item.height_cm > bottom + 0.0001:
                return False
            for other in placed:
                separate = (
                    x + item.width_cm + gap <= other.x_cm + 0.0001
                    or other.x_cm + other.width_cm + gap <= x + 0.0001
                    or y + item.height_cm + gap <= other.y_cm + 0.0001
                    or other.y_cm + other.height_cm + gap <= y + 0.0001
                )
                if not separate:
                    return False
            return True

        # Primero las cajas grandes; cada una prueba los vértices de las cajas
        # ya ubicadas. Así también ocupa huecos laterales e intermedios.
        movable = [item for item in self.items if not item.locked]

        def order(candidate: PlanchaItem) -> tuple:
            priority = candidate.source != "Pedido"
            if strategy == "alto":
                return (priority, -candidate.height_cm, -candidate.width_cm)
            if strategy == "ancho":
                return (priority, -candidate.width_cm, -candidate.height_cm)
            if strategy == "equilibrado":
                return (priority, -max(candidate.width_cm, candidate.height_cm), -min(candidate.width_cm, candidate.height_cm))
            return (priority, -(candidate.width_cm * candidate.height_cm), -max(candidate.width_cm, candidate.height_cm))

        movable.sort(key=order)
        for item in movable:
            xs = {left}
            ys = {top}
            for other in placed:
                xs.add(round(other.x_cm + other.width_cm + gap, 3))
                ys.add(round(other.y_cm + other.height_cm + gap, 3))
            candidates = [(x, y) for y in ys for x in xs if fits(item, x, y)]
            if not candidates:
                overflow.append(item)
                continue
            # Lectura de producción por filas: comienza arriba a la izquierda,
            # completa hacia la derecha y recién después continúa abajo.
            x, y = min(candidates, key=lambda point: (point[1], point[0]))
            item.x_cm, item.y_cm = round(x, 3), round(y, 3)
            placed.append(item)
        self.justify_rows(placed)
        return overflow

    def justify_rows(self, items: list[PlanchaItem] | None = None) -> None:
        """Reparte cada fila al ancho útil, manteniendo la separación segura."""
        items = self.items if items is None else items
        if len(items) < 2:
            return
        tolerance = 0.02
        rows: list[list[PlanchaItem]] = []
        for item in sorted(items, key=lambda candidate: (candidate.y_cm, candidate.x_cm)):
            row = next((group for group in rows if abs(group[0].y_cm - item.y_cm) <= tolerance), None)
            if row is None:
                rows.append([item])
            else:
                row.append(item)

        for row in rows:
            if len(row) < 2 or any(item.locked for item in row):
                continue
            row.sort(key=lambda item: item.x_cm)
            used_width = sum(item.width_cm for item in row)
            available_gap = (self.usable_width - used_width) / (len(row) - 1)
            if available_gap < self.gap_cm - 0.0001:
                continue
            outside = [item for item in items if item not in row]
            # Prueba de mayor a menor separación: si un diseño de otra fila
            # ocupa un hueco, conserva la distribución equitativa más amplia
            # que siga siendo físicamente válida.
            chosen = None
            for step in range(100, -1, -1):
                row_gap = self.gap_cm + (available_gap - self.gap_cm) * step / 100
                proposed = []
                x = self.margin_cm
                for item in row:
                    proposed.append((item, round(x, 3)))
                    x += item.width_cm + row_gap
                valid = True
                for item, x in proposed:
                    for other in outside:
                        separated = (
                            x + item.width_cm + self.gap_cm <= other.x_cm + 0.0001
                            or other.x_cm + other.width_cm + self.gap_cm <= x + 0.0001
                            or item.y_cm + item.height_cm + self.gap_cm <= other.y_cm + 0.0001
                            or other.y_cm + other.height_cm + self.gap_cm <= item.y_cm + 0.0001
                        )
                        if not separated:
                            valid = False
                            break
                    if not valid:
                        break
                if valid:
                    chosen = proposed
                    break
            if chosen:
                for item, x in chosen:
                    item.x_cm = x

        # Cuando hay filas reales, reparte el sobrante verticalmente entre
        # ellas. El límite de impresión queda intacto y desaparece la franja
        # vacía al pie de la plancha.
        ordered_rows = sorted(rows, key=lambda group: group[0].y_cm)
        if len(ordered_rows) > 1 and not any(item.locked for group in ordered_rows for item in group):
            row_heights = [max(item.height_cm for item in group) for group in ordered_rows]
            vertical_gap = (self.usable_height - sum(row_heights)) / (len(ordered_rows) - 1)
            if vertical_gap >= self.gap_cm - 0.0001:
                y = self.margin_cm
                for row, height in zip(ordered_rows, row_heights):
                    for item in row:
                        item.y_cm = round(y, 3)
                    y += height + vertical_gap

    def group_items(self, item: PlanchaItem) -> list[PlanchaItem]:
        return [candidate for candidate in self.items if candidate.group_id == item.group_id]

    def set_quantity(self, item_id: str, quantity: int) -> PlanchaItem | None:
        """Convierte una cantidad solicitada en copias físicas independientes."""
        item = next((candidate for candidate in self.items if candidate.item_id == item_id), None)
        if not item:
            return None
        quantity = max(1, int(quantity))
        original_group = self.group_items(item)
        template = original_group[0]
        self.items = [candidate for candidate in self.items if candidate.group_id != template.group_id]
        created = []
        for copy_number in range(1, quantity + 1):
            data = template.to_dict()
            data.update({"item_id": uuid.uuid4().hex, "quantity": quantity, "copy_number": copy_number})
            created.append(PlanchaItem.from_dict(data))
        self.items.extend(created)
        return created[0]

    def client_color(self, client: str) -> str:
        client = client.strip()
        if not client:
            return "#7a7a7a"
        known = {item.client.casefold(): item.client_color for item in self.items if item.client}
        if client.casefold() in known:
            return known[client.casefold()]
        return CLIENT_COLORS[len(known) % len(CLIENT_COLORS)]

    def legend(self) -> list[tuple[str, str, str, int]]:
        groups: dict[tuple[str, str, str], int] = {}
        for item in self.items:
            key = (item.client or "Stock", item.order_number, item.client_color if item.client else "#7a7a7a")
            groups[key] = groups.get(key, 0) + 1
        return [(color, client, order, count) for (client, order, color), count in groups.items()]

    def occupancy(self) -> float:
        area = sum(item.width_cm * item.height_cm for item in self.items)
        usable_area = self.usable_width * self.usable_height
        return min(100.0, area * 100 / usable_area) if usable_area else 0.0

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "paper": "A4 vertical",
            "width_cm": A4_WIDTH_CM,
            "height_cm": A4_HEIGHT_CM,
            "margin_cm": self.margin_cm,
            "gap_cm": self.gap_cm,
            "layout_mode": self.layout_mode,
            "workspace_format": self.workspace_format,
            "project_type": self.project_type,
            "manual_from_mixed": self.manual_from_mixed,
            "items": [item.to_dict() for item in self.items],
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def from_dict(cls, data: dict) -> "PlanchaProject":
        workspace_format = data.get("workspace_format", "a4")
        return cls(
            [PlanchaItem.from_dict(item) for item in data.get("items", [])],
            A5_PRINT_MARGIN_CM if workspace_format == "a5" else PRINT_MARGIN_CM, 0.05,
            data.get("layout_mode", "classic"), workspace_format,
            data.get("project_type", "legacy"), data.get("manual_from_mixed", False),
        )

    @staticmethod
    def calculate_pagination(all_items: list[PlanchaItem], margin_cm: float = PRINT_MARGIN_CM,
                            gap_cm: float = 0.05, layout_mode: str = "classic", 
                            workspace_format: str = "a4", progress=None) -> list["PlanchaProject"]:
        """Calcula automáticamente la paginación de stickers en múltiples planchas.
        
        Reutiliza el algoritmo de optimización existente para distribuir stickers
        en tantas planchas como sean necesarias.
        
        Args:
            all_items: Lista completa de stickers a distribuir
            margin_cm: Margen de impresión en cm
            gap_cm: Separación entre stickers en cm
            layout_mode: Modo de distribución ("classic" o "special")
            workspace_format: Formato de trabajo ("a4", "a5", "franja")
            progress: Callback opcional para reportar progreso
            
        Returns:
            Lista de proyectos PlanchaProject, uno por plancha
        """
        projects = []
        remaining_items = all_items.copy()
        plancha_number = 1
        
        while remaining_items:
            # Crear proyecto para esta plancha
            current_project = PlanchaProject(
                remaining_items.copy(),
                margin_cm=margin_cm,
                gap_cm=gap_cm,
                layout_mode=layout_mode,
                workspace_format=workspace_format
            )
            
            # Optimizar esta plancha
            overflow = current_project.optimize(progress=progress)
            
            # Los items que quedaron en el proyecto van a esta plancha
            overflow_ids = {item.item_id for item in overflow}
            placed_items = [item for item in current_project.items if item.item_id not in overflow_ids]
            
            if not placed_items:
                # Si ningún item entra, romper para evitar loop infinito
                break
                
            # Actualizar el proyecto con solo los items colocados
            current_project.items = placed_items
            projects.append(current_project)
            
            # Los items que no entraron pasan a la siguiente plancha
            remaining_items = overflow
            
            if progress:
                progress(len(projects), len(projects) + 1, f"Generando plancha {plancha_number}")
            
            plancha_number += 1
        
        return projects

    @classmethod
    def load(cls, path: str | Path) -> "PlanchaProject":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
