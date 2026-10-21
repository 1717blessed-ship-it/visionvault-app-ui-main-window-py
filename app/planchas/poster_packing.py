"""Motor de packing para composicion mixta de posters en hojas A4.

Implementa algoritmos de distribucion de rectangulos (MaxRects, Guillotine)
con multiples estrategias de optimizacion y politicas de tamano.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


# ============================================================================
# CONSTANTES DE TAMANOS ISO (en milimetros)
# ============================================================================

class PaperSize(Enum):
    """Tamanos de papel ISO estandar."""
    A4 = "A4"
    A5 = "A5"
    A6 = "A6"
    A7 = "A7"


# Dimensiones exactas en milimetros (ISO 216)
PAPER_SIZES_MM = {
    PaperSize.A4: (210.0, 297.0),
    PaperSize.A5: (148.0, 210.0),
    PaperSize.A6: (105.0, 148.0),
    PaperSize.A7: (74.0, 105.0),
}


# ============================================================================
# POLITICAS DE TAMANO
# ============================================================================

class SizePolicy(Enum):
    """Politica para manejar elementos que no caben en el area imprimible."""
    EXACTO = "exacto"
    AJUSTAR_AL_AREA_IMPRIMIBLE = "ajustar"


# ============================================================================
# ORIENTACION
# ============================================================================

class Orientation(Enum):
    """Orientacion de un elemento."""
    AUTOMATIC = "automatic"
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


# ============================================================================
# CONFIGURACION DE MARGENES Y SEPARACION
# ============================================================================

@dataclass
class MarginConfig:
    """Configuracion de margenes y separaciones en milimetros."""
    top: float = 5.0
    bottom: float = 5.0
    left: float = 5.0
    right: float = 5.0
    horizontal_gap: float = 2.0
    vertical_gap: float = 2.0

    @property
    def horizontal_total(self) -> float:
        return self.left + self.right

    @property
    def vertical_total(self) -> float:
        return self.top + self.bottom


DEFAULT_MARGINS = MarginConfig()


# ============================================================================
# MODELOS DE DATOS
# ============================================================================

@dataclass
class MixedPosterItem:
    """Un elemento de poster para composicion mixta con dimensiones personalizables."""
    id: str
    source_path: str
    width_mm: float
    height_mm: float
    quantity: int = 1
    orientation: Orientation = Orientation.AUTOMATIC
    allow_rotation: bool = True
    paper_size: PaperSize | None = None  # Opcional, solo para referencia/presets

    def __post_init__(self):
        """Validar las dimensiones después de la inicialización."""
        self._validate_dimensions()

    def _validate_dimensions(self):
        """Valida que las dimensiones sean válidas."""
        if self.width_mm <= 0:
            raise ValueError(f"width_mm debe ser mayor que 0, se recibió {self.width_mm}")
        if self.height_mm <= 0:
            raise ValueError(f"height_mm debe ser mayor que 0, se recibió {self.height_mm}")
        if self.quantity <= 0:
            raise ValueError(f"quantity debe ser mayor que 0, se recibió {self.quantity}")
        if self.width_mm > 1000 or self.height_mm > 1000:
            raise ValueError(f"Dimensiones demasiado grandes: {self.width_mm}x{self.height_mm} mm")

    @classmethod
    def from_preset(
        cls,
        preset: PaperSize,
        id: str,
        source_path: str,
        quantity: int = 1,
        orientation: Orientation = Orientation.AUTOMATIC,
        allow_rotation: bool = True,
    ) -> "MixedPosterItem":
        """Crea un MixedPosterItem desde un preset ISO."""
        width_mm, height_mm = PAPER_SIZES_MM[preset]
        return cls(
            id=id,
            source_path=source_path,
            width_mm=width_mm,
            height_mm=height_mm,
            quantity=quantity,
            orientation=orientation,
            allow_rotation=allow_rotation,
            paper_size=preset,
        )

    def get_dimensions(self, rotated: bool = False) -> tuple[float, float]:
        if rotated:
            return self.height_mm, self.width_mm
        return self.width_mm, self.height_mm


@dataclass
class PosterPlacement:
    """Ubicacion de una copia de un elemento en una hoja."""
    item_id: str
    copy_index: int
    page_index: int
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    rotation: bool = False
    scale_factor: float = 1.0


@dataclass
class FreeRectangle:
    """Rectangulo libre en una hoja."""
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float


@dataclass
class PackedPosterPage:
    """Una hoja A4 con elementos colocados."""
    placements: list[PosterPlacement] = field(default_factory=list)
    free_rectangles: list[FreeRectangle] = field(default_factory=list)
    occupied_area_mm2: float = 0.0
    printable_area_mm2: float = 0.0
    utilization_percent: float = 0.0

    @property
    def free_area_mm2(self) -> float:
        return self.printable_area_mm2 - self.occupied_area_mm2


@dataclass
class PackingResult:
    """Resultado completo del proceso de packing."""
    pages: list[PackedPosterPage] = field(default_factory=list)
    unplaced_items: list[str] = field(default_factory=list)
    scale_factor: float = 1.0
    total_utilization_percent: float = 0.0
    warnings: list[str] = field(default_factory=list)
    policy_used: SizePolicy = SizePolicy.EXACTO
    nominal_size_mm: tuple[float, float] = (210.0, 297.0)
    printed_size_mm: tuple[float, float] = (210.0, 297.0)

    @property
    def total_pages(self) -> int:
        return len(self.pages)

    @property
    def total_placements(self) -> int:
        return sum(len(page.placements) for page in self.pages)


# ============================================================================
# UTILIDADES DE PRECISION NUMERICA
# ============================================================================

UNITS_PER_MM = 10


def mm_to_units(mm: float) -> int:
    return int(round(mm * UNITS_PER_MM))


def units_to_mm(units: int) -> float:
    return units / UNITS_PER_MM


def area_units_to_mm2(area_units: int) -> float:
    return area_units / (UNITS_PER_MM * UNITS_PER_MM)


# ============================================================================
# ALGORITMO MAXRECTS
# ============================================================================

class FitHeuristic(Enum):
    """Heuristica para seleccionar el mejor rectangulo libre."""
    BEST_AREA_FIT = "best_area_fit"
    BEST_SHORT_SIDE_FIT = "best_short_side_fit"
    BEST_LONG_SIDE_FIT = "best_long_side_fit"


@dataclass
class Rect:
    """Rectangulo en unidades internas."""
    x: int
    y: int
    width: int
    height: int

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def can_contain(self, other: "Rect") -> bool:
        return self.width >= other.width and self.height >= other.height

    def intersects(self, other: "Rect") -> bool:
        return not (
            self.right <= other.x or
            other.right <= self.x or
            self.bottom <= other.y or
            other.bottom <= self.y
        )

    def __repr__(self) -> str:
        return f"Rect(x={self.x}, y={self.y}, w={self.width}, h={self.height})"


class MaxRectsPacker:
    """Implementacion del algoritmo MaxRects para packing de rectangulos."""

    def __init__(
        self,
        bin_width: int,
        bin_height: int,
        heuristic: FitHeuristic = FitHeuristic.BEST_SHORT_SIDE_FIT,
    ):
        self.bin_width = bin_width
        self.bin_height = bin_height
        self.heuristic = heuristic
        self.free_rectangles: list[Rect] = [
            Rect(0, 0, bin_width, bin_height)
        ]
        self.used_rectangles: list[Rect] = []

    def insert(self, width: int, height: int, allow_rotation: bool = True) -> tuple[Rect, bool] | None:
        best_node = self._find_best_position(width, height)
        if best_node:
            self._place_rectangle(best_node)
            return best_node, False

        if allow_rotation and width != height:
            best_node = self._find_best_position(height, width)
            if best_node:
                self._place_rectangle(best_node)
                return Rect(best_node.x, best_node.y, height, width), True

        return None

    def _find_best_position(self, width: int, height: int) -> Rect | None:
        """Encuentra la mejor posición probando múltiples puntos candidatos."""
        best_node = None
        best_area = float('inf')
        best_short_side = float('inf')
        best_long_side = float('inf')

        # Generar puntos candidatos adicionales además de las esquinas de rectángulos libres
        candidate_positions = self._generate_candidate_positions(width, height)

        for candidate in candidate_positions:
            # Verificar si el candidato cabe dentro del bin
            if candidate.x + width > self.bin_width or candidate.y + height > self.bin_height:
                continue

            # Verificar si el candidato no se superpone con rectángulos usados
            candidate_rect = Rect(candidate.x, candidate.y, width, height)
            if any(candidate_rect.intersects(used) for used in self.used_rectangles):
                continue

            # Calcular métricas para este candidato
            # El área "libre" efectiva es el área del rectángulo libre más cercano
            area = width * height
            short_side = min(width, height)
            long_side = max(width, height)

            if self.heuristic == FitHeuristic.BEST_AREA_FIT:
                if area < best_area or (area == best_area and short_side < best_short_side):
                    best_area = area
                    best_short_side = short_side
                    best_node = candidate_rect

            elif self.heuristic == FitHeuristic.BEST_SHORT_SIDE_FIT:
                if short_side < best_short_side or (short_side == best_short_side and long_side < best_long_side):
                    best_short_side = short_side
                    best_long_side = long_side
                    best_node = candidate_rect

            elif self.heuristic == FitHeuristic.BEST_LONG_SIDE_FIT:
                if long_side < best_long_side or (long_side == best_long_side and short_side < best_short_side):
                    best_long_side = long_side
                    best_short_side = short_side
                    best_node = candidate_rect

        # Fallback al método original si no se encontró candidato
        if best_node is None:
            for free_rect in self.free_rectangles:
                if free_rect.width >= width and free_rect.height >= height:
                    area = free_rect.area
                    short_side = min(free_rect.width, free_rect.height)
                    long_side = max(free_rect.width, free_rect.height)

                    if self.heuristic == FitHeuristic.BEST_AREA_FIT:
                        if area < best_area or (area == best_area and short_side < best_short_side):
                            best_area = area
                            best_short_side = short_side
                            best_node = free_rect

                    elif self.heuristic == FitHeuristic.BEST_SHORT_SIDE_FIT:
                        if short_side < best_short_side or (short_side == best_short_side and long_side < best_long_side):
                            best_short_side = short_side
                            best_long_side = long_side
                            best_node = free_rect

                    elif self.heuristic == FitHeuristic.BEST_LONG_SIDE_FIT:
                        if long_side < best_long_side or (long_side == best_long_side and short_side < best_short_side):
                            best_long_side = long_side
                            best_short_side = short_side
                            best_node = free_rect

        if best_node:
            return Rect(best_node.x, best_node.y, width, height)
        return None

    def _generate_candidate_positions(self, width: int, height: int) -> list[Rect]:
        """Genera puntos candidatos adicionales para colocación."""
        candidates = []

        # 1. Esquinas de rectángulos libres (método original)
        for free_rect in self.free_rectangles:
            if free_rect.width >= width and free_rect.height >= height:
                candidates.append(Rect(free_rect.x, free_rect.y, width, height))

        # 2. Bordes derechos de rectángulos colocados
        for used in self.used_rectangles:
            # Probar posición a la derecha del rectángulo usado
            x = used.right
            y = used.y
            candidates.append(Rect(x, y, width, height))

            # Probar posición alineada abajo del rectángulo usado
            x = used.x
            y = used.bottom
            candidates.append(Rect(x, y, width, height))

        # 3. Esquinas combinadas (intersecciones de bordes)
        for used1 in self.used_rectangles:
            for used2 in self.used_rectangles:
                if used1 is used2:
                    continue

                # Esquina superior derecha de used1 alineada con used2
                x = used1.right
                y = used2.y
                candidates.append(Rect(x, y, width, height))

                # Esquina inferior izquierda de used1 alineada con used2
                x = used1.x
                y = used2.bottom
                candidates.append(Rect(x, y, width, height))

        return candidates

    def _place_rectangle(self, rect: Rect) -> None:
        self.used_rectangles.append(rect)

        new_free_rects: list[Rect] = []
        for free_rect in self.free_rectangles:
            if free_rect.intersects(rect):
                new_free_rects.extend(self._split_free_rectangle(free_rect, rect))
            else:
                new_free_rects.append(free_rect)

        self.free_rectangles = self._prune_free_rectangles(new_free_rects)

    def _split_free_rectangle(self, free_rect: Rect, placed_rect: Rect) -> list[Rect]:
        new_rects: list[Rect] = []

        if placed_rect.y > free_rect.y:
            new_rects.append(Rect(
                free_rect.x,
                free_rect.y,
                free_rect.width,
                placed_rect.y - free_rect.y
            ))

        if placed_rect.bottom < free_rect.bottom:
            new_rects.append(Rect(
                free_rect.x,
                placed_rect.bottom,
                free_rect.width,
                free_rect.bottom - placed_rect.bottom
            ))

        if placed_rect.x > free_rect.x:
            new_rects.append(Rect(
                free_rect.x,
                free_rect.y,
                placed_rect.x - free_rect.x,
                free_rect.height
            ))

        if placed_rect.right < free_rect.right:
            new_rects.append(Rect(
                placed_rect.right,
                free_rect.y,
                free_rect.right - placed_rect.right,
                free_rect.height
            ))

        return new_rects

    def _prune_free_rectangles(self, rects: list[Rect]) -> list[Rect]:
        pruned: list[Rect] = []

        for rect in rects:
            if rect.width <= 0 or rect.height <= 0:
                continue

            is_contained = False
            for other in rects:
                if rect is other:
                    continue
                if (other.x <= rect.x and other.y <= rect.y and
                    other.right >= rect.right and other.bottom >= rect.bottom):
                    is_contained = True
                    break

            if not is_contained:
                pruned.append(rect)

        return pruned

    @property
    def occupancy(self) -> float:
        used_area = sum(r.area for r in self.used_rectangles)
        total_area = self.bin_width * self.bin_height
        return (used_area / total_area) * 100 if total_area > 0 else 0


# ============================================================================
# MOTOR DE PACKING PRINCIPAL
# ============================================================================

class PosterPacker:
    """Motor principal para composicion mixta de posters."""

    def __init__(
        self,
        margins: MarginConfig = DEFAULT_MARGINS,
        size_policy: SizePolicy = SizePolicy.EXACTO,
    ):
        self.margins = margins
        self.size_policy = size_policy
        self.a4_width_mm, self.a4_height_mm = PAPER_SIZES_MM[PaperSize.A4]

    def pack(
        self,
        items: list[MixedPosterItem],
        heuristics: list[FitHeuristic] | None = None,
        max_alternatives: int = 5,
    ) -> PackingResult:
        if heuristics is None:
            heuristics = [
                FitHeuristic.BEST_SHORT_SIDE_FIT,
                FitHeuristic.BEST_AREA_FIT,
                FitHeuristic.BEST_LONG_SIDE_FIT,
            ]

        scale_factor = self._calculate_scale_factor(items)
        all_copies = self._expand_items(items, scale_factor)

        total_copies = sum(item.quantity for item in items)
        use_exhaustive = total_copies <= 8

        if use_exhaustive:
            best_result = self._exhaustive_search(all_copies, heuristics, max_alternatives, scale_factor)
        else:
            best_result = self._heuristic_search(all_copies, heuristics, scale_factor)

        if self.size_policy == SizePolicy.AJUSTAR_AL_AREA_IMPRIMIBLE and scale_factor < 1.0:
            best_result.warnings.append(
                f"Composicion escalada al {scale_factor:.1%} para ajustar al area imprimible. "
                f"Tamano nominal: {self.a4_width_mm:.1f}x{self.a4_height_mm:.1f} mm, "
                f"Tamano impreso: {self.a4_width_mm * scale_factor:.1f}x{self.a4_height_mm * scale_factor:.1f} mm"
            )

        return best_result

    def _calculate_scale_factor(self, items: list[MixedPosterItem]) -> float:
        if self.size_policy == SizePolicy.EXACTO:
            return 1.0

        printable_width = self.a4_width_mm - self.margins.horizontal_total
        printable_height = self.a4_height_mm - self.margins.vertical_total

        if not items:
            return 1.0

        total_area = sum(
            item.width_mm * item.height_mm * item.quantity
            for item in items
        )

        printable_area = printable_width * printable_height

        if total_area <= printable_area:
            return 1.0

        # Calcular escala basada en área
        scale = math.sqrt(printable_area / total_area)
        
        # Verificar que la escala no haga que ningún elemento exceda el área imprimible
        # individualmente. Usar el factor más restrictivo.
        max_item_width = max(item.width_mm for item in items)
        max_item_height = max(item.height_mm for item in items)
        
        scale_by_width = printable_width / max_item_width if max_item_width > 0 else 1.0
        scale_by_height = printable_height / max_item_height if max_item_height > 0 else 1.0
        
        # Usar el mínimo de: escala por área, escala por ancho, escala por alto
        scale = min(scale, scale_by_width, scale_by_height)
        
        return min(scale, 1.0)

    def _expand_items(self, items: list[MixedPosterItem], scale_factor: float) -> list[tuple[MixedPosterItem, int]]:
        expanded = []
        for item in items:
            for copy_idx in range(item.quantity):
                expanded.append((item, copy_idx))
        return expanded

    def _exhaustive_search(
        self,
        copies: list[tuple[MixedPosterItem, int]],
        heuristics: list[FitHeuristic],
        max_alternatives: int,
        scale_factor: float,
    ) -> PackingResult:
        best_result = None
        best_score = float('-inf')

        import itertools

        # Generar todas las permutaciones únicas (deduplicando elementos idénticos)
        orders = self._generate_unique_permutations(copies)

        # Generar variantes de rotación independientes por elemento
        rotation_variants = self._generate_independent_rotation_variants(copies)

        for heuristic in heuristics:
            # Probar todas las permutaciones
            for order in orders:
                result = self._pack_with_heuristic(order, heuristic, scale_factor)

                score = self._score_result(result)
                if score > best_score:
                    best_score = score
                    best_result = result

            # Probar variantes con rotación independiente
            for rotated_copies in rotation_variants:
                for order in self._generate_unique_permutations(rotated_copies):
                    result = self._pack_with_heuristic(order, heuristic, scale_factor)

                    score = self._score_result(result)
                    if score > best_score:
                        best_score = score
                        best_result = result

        return best_result or self._create_empty_result(scale_factor)

    def _generate_unique_permutations(self, copies: list[tuple[MixedPosterItem, int]]) -> list[list[tuple[MixedPosterItem, int]]]:
        """Genera permutaciones únicas deduplicando elementos idénticos."""
        import itertools
        
        # Crear clave para identificar elementos idénticos (mismo tamaño y orientación)
        def element_key(item_copy):
            item, copy_idx = item_copy
            return (item.paper_size, item.orientation, item.allow_rotation)
        
        # Agrupar elementos por clave
        from collections import defaultdict
        groups = defaultdict(list)
        for i, item_copy in enumerate(copies):
            key = element_key(item_copy)
            groups[key].append((i, item_copy))
        
        # Generar permutaciones únicas usando itertools.permutations con deduplicación
        # Para casos pequeños (<= 8 elementos), generar todas las permutaciones
        if len(copies) <= 8:
            all_perms = list(itertools.permutations(copies))
            # Deduplicar permutaciones equivalentes
            unique_perms = []
            seen = set()
            
            for perm in all_perms:
                # Crear firma de la permutación basada en las claves de elementos
                signature = tuple(element_key(p) for p in perm)
                if signature not in seen:
                    seen.add(signature)
                    unique_perms.append(list(perm))
            
            return unique_perms
        else:
            # Para casos más grandes, usar orden por área descendente
            return [sorted(copies, key=lambda x: x[0].width_mm * x[0].height_mm, reverse=True)]

    def _generate_independent_rotation_variants(self, copies: list[tuple[MixedPosterItem, int]]) -> list[list[tuple[MixedPosterItem, int]]]:
        """Genera variantes con rotación independiente por elemento.
        
        Para cada elemento con orientación AUTOMATIC y allow_rotation=True,
        genera variantes donde ese elemento específico está rotado.
        """
        from dataclasses import replace
        variants = []
        
        # Identificar índices de elementos que pueden rotar
        rotatable_indices = [
            i for i, (item, copy_idx) in enumerate(copies)
            if item.allow_rotation and item.orientation == Orientation.AUTOMATIC
        ]
        
        if not rotatable_indices:
            return variants
        
        # Generar variantes rotando cada elemento rotable individualmente
        for idx in rotatable_indices:
            rotated = list(copies)
            item, copy_idx = rotated[idx]
            rotated_item = replace(item, orientation=Orientation.LANDSCAPE)
            rotated[idx] = (rotated_item, copy_idx)
            variants.append(rotated)
        
        # Generar variantes rotando pares de elementos (para casos pequeños)
        if len(rotatable_indices) >= 2 and len(copies) <= 6:
            import itertools
            for i, j in itertools.combinations(rotatable_indices, 2):
                rotated = list(copies)
                item_i, copy_idx_i = rotated[i]
                item_j, copy_idx_j = rotated[j]
                rotated_i = replace(item_i, orientation=Orientation.LANDSCAPE)
                rotated_j = replace(item_j, orientation=Orientation.LANDSCAPE)
                rotated[i] = (rotated_i, copy_idx_i)
                rotated[j] = (rotated_j, copy_idx_j)
                variants.append(rotated)
        
        return variants

    def _heuristic_search(
        self,
        copies: list[tuple[MixedPosterItem, int]],
        heuristics: list[FitHeuristic],
        scale_factor: float,
    ) -> PackingResult:
        best_result = None
        best_score = float('-inf')

        sorted_copies = sorted(copies, key=lambda x: x[0].width_mm * x[0].height_mm, reverse=True)

        for heuristic in heuristics:
            result = self._pack_with_heuristic(sorted_copies, heuristic, scale_factor)
            
            score = self._score_result(result)
            if score > best_score:
                best_score = score
                best_result = result

        return best_result or self._create_empty_result(scale_factor)

    def _pack_with_heuristic(
        self,
        copies: list[tuple[MixedPosterItem, int]],
        heuristic: FitHeuristic,
        scale_factor: float,
    ) -> PackingResult:
        result = PackingResult(scale_factor=scale_factor, policy_used=self.size_policy)

        printable_width = (self.a4_width_mm - self.margins.horizontal_total) * scale_factor
        printable_height = (self.a4_height_mm - self.margins.vertical_total) * scale_factor

        bin_w = mm_to_units(printable_width)
        bin_h = mm_to_units(printable_height)

        packer = MaxRectsPacker(bin_w, bin_h, heuristic)
        current_page = PackedPosterPage()
        current_page.printable_area_mm2 = printable_width * printable_height
        page_index = 0

        for item, copy_index in copies:
            # Determinar dimensiones iniciales según orientación
            if item.orientation == Orientation.LANDSCAPE:
                item_w = item.height_mm * scale_factor
                item_h = item.width_mm * scale_factor
                is_pre_rotated = True
            else:
                item_w = item.width_mm * scale_factor
                item_h = item.height_mm * scale_factor
                is_pre_rotated = False

            w = mm_to_units(item_w)
            h = mm_to_units(item_h)

            # Solo permitir rotación dinámica si la orientación es AUTOMATIC
            allow_rotation = item.allow_rotation and item.orientation == Orientation.AUTOMATIC

            # Verificar si el elemento cabe en el bin (incluso con rotación)
            fits_normal = w <= bin_w and h <= bin_h
            fits_rotated = allow_rotation and h <= bin_w and w <= bin_h
            
            if not fits_normal and not fits_rotated:
                # El elemento no cabe en ninguna orientación
                result.unplaced_items.append(item.id)
                continue

            placement = packer.insert(w, h, allow_rotation)

            if placement is None:
                result.pages.append(current_page)
                page_index += 1
                packer = MaxRectsPacker(bin_w, bin_h, heuristic)
                current_page = PackedPosterPage()
                current_page.printable_area_mm2 = printable_width * printable_height

                placement = packer.insert(w, h, allow_rotation)
                if placement is None:
                    result.unplaced_items.append(item.id)
                    continue

            rect, was_rotated = placement

            # Calcular rotación final: si fue pre-rotada por orientación LANDSCAPE
            # o rotada dinámicamente por el algoritmo
            final_rotation = was_rotated or is_pre_rotated

            poster_placement = PosterPlacement(
                item_id=item.id,
                copy_index=copy_index,
                page_index=page_index,
                x_mm=units_to_mm(rect.x) + self.margins.left,
                y_mm=units_to_mm(rect.y) + self.margins.top,
                width_mm=units_to_mm(rect.width),
                height_mm=units_to_mm(rect.height),
                rotation=final_rotation,
                scale_factor=scale_factor,
            )

            current_page.placements.append(poster_placement)
            current_page.occupied_area_mm2 += poster_placement.width_mm * poster_placement.height_mm

        if current_page.placements:
            result.pages.append(current_page)

        for page in result.pages:
            page.utilization_percent = (page.occupied_area_mm2 / page.printable_area_mm2) * 100

        total_occupied = sum(p.occupied_area_mm2 for p in result.pages)
        total_printable = sum(p.printable_area_mm2 for p in result.pages)
        result.total_utilization_percent = (total_occupied / total_printable) * 100 if total_printable > 0 else 0

        # Validación posterior al escalado: verificar que todos los elementos
        # estén dentro del área imprimible cuando se usa AJUSTAR_AL_AREA_IMPRIMIBLE
        if self.size_policy == SizePolicy.AJUSTAR_AL_AREA_IMPRIMIBLE and scale_factor < 1.0:
            for page in result.pages:
                for placement in page.placements:
                    x_end = placement.x_mm + placement.width_mm
                    y_end = placement.y_mm + placement.height_mm
                    
                    # El área imprimible va desde (margins.left, margins.top) 
                    # hasta (margins.left + printable_width, margins.top + printable_height)
                    max_x = self.margins.left + printable_width
                    max_y = self.margins.top + printable_height
                    
                    if x_end > max_x + 0.1 or y_end > max_y + 0.1:
                        result.warnings.append(
                            f"Elemento {placement.item_id} excede el área imprimible "
                            f"después del escalado: ({x_end:.1f}, {y_end:.1f}) > ({max_x:.1f}, {max_y:.1f})"
                        )

        return result

    def _score_result(self, result: PackingResult) -> float:
        # Penalizar fuertemente elementos sin colocar, pero no descartar completamente
        unplaced_penalty = len(result.unplaced_items) * 50000
        
        score = 10000 - (len(result.pages) * 1000) - unplaced_penalty

        for i, page in enumerate(result.pages):
            weight = 1.0 / (i + 1)
            score += page.utilization_percent * weight

        return score

    def _create_empty_result(self, scale_factor: float) -> PackingResult:
        return PackingResult(
            scale_factor=scale_factor,
            policy_used=self.size_policy,
            warnings=["No se pudo empaquetar ningun elemento"],
        )


def pack_mixed_posters(
    items: list[MixedPosterItem],
    margins: MarginConfig = DEFAULT_MARGINS,
    size_policy: SizePolicy = SizePolicy.EXACTO,
) -> PackingResult:
    packer = PosterPacker(margins=margins, size_policy=size_policy)
    return packer.pack(items)
