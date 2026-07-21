"""Modelo editable y no destructivo para una plancha A4."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


A4_WIDTH_CM = 21.0
A4_HEIGHT_CM = 29.7
PRINT_MARGIN_CM = 0.15
# Cinco filas de 5,75 cm más separaciones y límite de impresión: aprovecha el
# A4 prácticamente completo sin comprometer el corte preciso del plotter.
SIZE_OFFSET_CM = 0.70
FIVE_ROW_SIZE_CM = 5.0 + SIZE_OFFSET_CM
STANDARD_SIZE_CM = FIVE_ROW_SIZE_CM
MAX_SIZE_CM = 29.70
CLIENT_COLORS = ("#3b82f6", "#a855f7", "#f97316", "#16a34a", "#db2777", "#0891b2", "#ca8a04")


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
    locked: bool = False
    rotation_allowed: bool = False
    client_color: str = "#7a7a7a"
    group_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    copy_number: int = 1
    item_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PlanchaItem":
        return cls(**data)


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


class PlanchaProject:
    """Proyecto A4: solo guarda referencias y posiciones, nunca altera imágenes."""

    def __init__(self, items: list[PlanchaItem] | None = None, margin_cm: float = PRINT_MARGIN_CM, gap_cm: float = 0.05):
        self.items = items or []
        self.margin_cm = float(margin_cm)
        self.gap_cm = float(gap_cm)

    @classmethod
    def from_images(cls, images: list[dict]) -> "PlanchaProject":
        items = []
        for image in images:
            # Obtener cantidad desde el pedido (order_quantity) o usar 1 por defecto
            quantity = int(image.get("order_quantity", 1) or 1)
            
            # Obtener tamaño desde el pedido (order_size_cm) si está disponible
            if image.get("order_size_cm"):
                requested_size = float(image.get("order_size_cm"))
                if image.get("visible_width") and image.get("visible_height"):
                    width, height = size_from_visible_dimensions(
                        image["visible_width"], 
                        image["visible_height"], 
                        requested_size
                    )
                else:
                    width, height = size_for_image(image["path"], requested_size)
            else:
                # Sin tamaño específico del pedido, usar el cálculo normal
                if image.get("visible_width") and image.get("visible_height"):
                    width, height = size_from_visible_dimensions(image["visible_width"], image["visible_height"])
                else:
                    width, height = size_for_image(image["path"])
            
            # Crear múltiples items según la cantidad solicitada
            for copy_num in range(1, quantity + 1):
                items.append(PlanchaItem(
                    path=image["path"], 
                    name=image.get("name") or Path(image["path"]).name, 
                    width_cm=width, 
                    height_cm=height,
                    quantity=1,  # Cada item representa 1 unidad
                    copy_number=copy_num  # Número de copia (1, 2, 3, ...)
                ))
        return cls(items)

    @property
    def usable_width(self) -> float:
        return A4_WIDTH_CM - self.margin_cm * 2

    @property
    def usable_height(self) -> float:
        return A4_HEIGHT_CM - self.margin_cm * 2

    def keep_inside_print_area(self) -> None:
        """Evita que una posiciÃ³n guardada o bloqueada recorte el sticker al exportar."""
        for item in self.items:
            max_x = max(self.margin_cm, A4_WIDTH_CM - self.margin_cm - item.width_cm)
            max_y = max(self.margin_cm, A4_HEIGHT_CM - self.margin_cm - item.height_cm)
            item.x_cm = round(min(max(self.margin_cm, item.x_cm), max_x), 3)
            item.y_cm = round(min(max(self.margin_cm, item.y_cm), max_y), 3)

    def optimize(self, progress=None) -> list[PlanchaItem]:
        return self._optimize_row_first(progress)

        # ImplementaciÃ³n anterior: conservada debajo como referencia de proyecto.
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
        row_count = 5
        left, top = self.margin_cm, self.margin_cm
        gap = self.gap_cm
        band_height = self.usable_height / row_count
        content_height = band_height - gap
        overflow: list[PlanchaItem] = []
        rows: list[list[PlanchaItem]] = [[] for _ in range(row_count)]
        widths = [0.0] * row_count

        # Locked stickers preserve their manual location and reserve their row.
        for item in self.items:
            if not item.locked:
                continue
            row_index = min(row_count - 1, max(0, int((item.y_cm - top) / band_height)))
            rows[row_index].append(item)
            widths[row_index] = max(widths[row_index], item.x_cm + item.width_cm - left + gap)

        current_row = 0
        sequence = [item for item in self.items if not item.locked]
        total = max(1, len(sequence))
        if progress:
            progress(0, total, "Organizando las 5 franjas")

        def place_in_row(item: PlanchaItem) -> int | None:
            nonlocal current_row
            if item.height_cm > content_height + 0.0001 or item.width_cm > self.usable_width + 0.0001:
                return None
            for row_index in range(current_row, row_count):
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
            y = top + row_index * band_height + (content_height - tallest) / 2
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
        """Compacta cinco filas y justifica únicamente el espacio que reste.

        Se prueban varias combinaciones de cada fila. Así, un diseño angosto
        posterior puede completar el hueco que deja uno ancho; la lectura final
        sigue siendo de arriba a abajo y de izquierda a derecha.
        """
        if any(item.locked for item in self.items):
            return self._optimize_locked_five_bands(progress)

        row_count = 5
        left, top = self.margin_cm, self.margin_cm
        gap = self.gap_cm
        capacity = self.usable_width
        band_height = self.usable_height / row_count
        max_height = band_height - gap
        indexed = list(enumerate(self.items))

        def choices(item: PlanchaItem) -> list[tuple[float, float, bool]]:
            options: list[tuple[float, float, bool]] = []
            if item.width_cm <= capacity + 0.0001 and item.height_cm <= max_height + 0.0001:
                options.append((item.width_cm, item.height_cm, False))
            if item.rotation_allowed and item.height_cm <= capacity + 0.0001 and item.width_cm <= max_height + 0.0001:
                options.append((item.height_cm, item.width_cm, True))
            return options

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
                return (-(width * height), -width, index)

            sequence = sorted(indexed, key=ordering)
            for index, item in sequence:
                best: tuple[tuple[float, float, int], int, float, float, bool] | None = None
                for width, height, rotated in choices(item):
                    for row_index in range(row_count):
                        required = width + (gap if rows[row_index] else 0.0)
                        if widths[row_index] + required > capacity + 0.0001:
                            continue
                        remaining = capacity - widths[row_index] - required
                        # Mejor ajuste: deja el menor remanente posible. Para
                        # empates se prefiere la franja superior y más llena.
                        candidate = ((remaining, -widths[row_index], row_index), row_index, width, height, rotated)
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

        strategies = ("área", "ancho", "alto", "cadena")
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

        # Antes de abrir las separaciones de una fila, se vuelve a revisar el
        # sobrante. Si alguno entra en un hueco real, se privilegia sumarlo a
        # la plancha: un sticker adicional aprovecha mejor el vinilo que una
        # línea blanca más pareja. La estética se aplica recién después, al
        # repartir únicamente el remanente que ya no admite otro diseño.
        remaining_overflow = list(best_overflow)
        while remaining_overflow:
            candidate_choice: tuple[tuple[float, float, int, int], int, int, PlanchaItem, float, float, bool] | None = None
            for overflow_index, item in enumerate(remaining_overflow):
                for width, height, rotated in choices(item):
                    for row_index, row in enumerate(best_rows):
                        used_width = sum(entry[2] for entry in row) + gap * max(0, len(row) - 1)
                        required = width + (gap if row else 0.0)
                        remainder = capacity - used_width - required
                        if remainder < -0.0001:
                            continue
                        # Mejor encastre: menor sobrante; ante empate, usa el
                        # diseño de mayor superficie y la fila superior.
                        score = (round(remainder, 6), -(width * height), row_index, overflow_index)
                        if candidate_choice is None or score < candidate_choice[0]:
                            candidate_choice = (score, row_index, overflow_index, item, width, height, rotated)
            if candidate_choice is None:
                break
            _score, row_index, overflow_index, item, width, height, rotated = candidate_choice
            original_index = next(index for index, current in indexed if current.item_id == item.item_id)
            best_rows[row_index].append((original_index, item, width, height, rotated))
            remaining_overflow.pop(overflow_index)
        best_overflow = remaining_overflow

        for row_index, row in enumerate(best_rows):
            if not row:
                continue
            # El orden visual mantiene la secuencia original dentro de la
            # fila, aun cuando el optimizador eligió la combinación por área.
            row.sort(key=lambda entry: entry[0])
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
            y = top + row_index * band_height + max(0.0, (band_height - row_height) / 2)
            for _index, item, width, height, rotated in row:
                if rotated:
                    item.width_cm, item.height_cm = width, height
                    item.rotation = (item.rotation + 90) % 360
                item.x_cm = round(x, 3)
                item.y_cm = round(y + (row_height - height) / 2, 3)
                x += width + row_gap

        self.keep_inside_print_area()
        return best_overflow

    def _optimize_row_first(self, progress=None) -> list[PlanchaItem]:
        return self._optimize_five_bands(progress)
        """Acomodo veloz de producciÃ³n: arriba→derecha y luego la fila siguiente.

        Los diseÃ±os de tamaÃ±o especial se reservan primero. Los predeterminados
        conservan el orden en que fueron elegidos, por lo que se leen y cortan
        naturalmente de izquierda a derecha. Solo rota un diseÃ±o si el usuario
        autorizÃ³ la rotaciÃ³n y asÃ­ entra en un espacio disponible.
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
            "items": [item.to_dict() for item in self.items],
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "PlanchaProject":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        # Todas las planchas usan el límite de impresión interno, aun si el
        # proyecto fue creado en una versión que ocupaba el A4 completo.
        return cls([PlanchaItem.from_dict(item) for item in data.get("items", [])], PRINT_MARGIN_CM, 0.05)
