"""Pruebas unitarias para el motor de packing de pósters mixtos.

Estas pruebas no dependen de Tkinter ni de una impresora real.
Validan el algoritmo de packing y las políticas de tamaño.
"""

import pytest
from pathlib import Path

from app.planchas.poster_packing import (
    PaperSize,
    SizePolicy,
    Orientation,
    MarginConfig,
    MixedPosterItem,
    PosterPlacement,
    PackedPosterPage,
    PackingResult,
    FitHeuristic,
    pack_mixed_posters,
    mm_to_units,
    units_to_mm,
    PAPER_SIZES_MM,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_a5_item():
    """Item A5 de ejemplo."""
    return MixedPosterItem.from_preset(
        preset=PaperSize.A5,
        id="a5_1",
        source_path="/fake/a5.png",
        quantity=1,
        orientation=Orientation.AUTOMATIC,
        allow_rotation=True,
    )


@pytest.fixture
def sample_a6_item():
    """Item A6 de ejemplo."""
    return MixedPosterItem.from_preset(
        preset=PaperSize.A6,
        id="a6_1",
        source_path="/fake/a6.png",
        quantity=1,
        orientation=Orientation.AUTOMATIC,
        allow_rotation=True,
    )


@pytest.fixture
def sample_a7_item():
    """Item A7 de ejemplo."""
    return MixedPosterItem.from_preset(
        preset=PaperSize.A7,
        id="a7_1",
        source_path="/fake/a7.png",
        quantity=1,
        orientation=Orientation.AUTOMATIC,
        allow_rotation=True,
    )


@pytest.fixture
def no_margins():
    """Configuración sin márgenes ni separación."""
    return MarginConfig(top=0, bottom=0, left=0, right=0, horizontal_gap=0, vertical_gap=0)


@pytest.fixture
def standard_margins():
    """Configuración con márgenes estándar de impresión."""
    return MarginConfig(top=5, bottom=5, left=5, right=5, horizontal_gap=2, vertical_gap=2)


# ============================================================================
# PRUEBAS DE CONVERSIÓN DE UNIDADES
# ============================================================================

def test_mm_to_units_conversion():
    """Prueba la conversión entre milímetros y unidades internas."""
    assert mm_to_units(1.0) == 10
    assert mm_to_units(0.1) == 1
    assert mm_to_units(10.5) == 105
    assert units_to_mm(10) == 1.0
    assert units_to_mm(1) == 0.1
    assert units_to_mm(105) == 10.5


def test_paper_sizes_iso():
    """Verifica que los tamaños ISO sean correctos."""
    assert PAPER_SIZES_MM[PaperSize.A4] == (210.0, 297.0)
    assert PAPER_SIZES_MM[PaperSize.A5] == (148.0, 210.0)
    assert PAPER_SIZES_MM[PaperSize.A6] == (105.0, 148.0)
    assert PAPER_SIZES_MM[PaperSize.A7] == (74.0, 105.0)


# ============================================================================
# PRUEBA 1: 1 A5 + 2 A6 con área A4 completa y separación cero
# ============================================================================

def test_1_a5_2_a6_no_margins(sample_a5_item, sample_a6_item, no_margins):
    """1 A5 + 2 A6 debe caber en una hoja A4 sin márgenes."""
    items = [
        sample_a5_item,
        MixedPosterItem.from_preset(id="a6_2", source_path="/fake/a6_2.png", preset=PaperSize.A6, quantity=1),
        sample_a6_item,
    ]

    result = pack_mixed_posters(items, margins=no_margins, size_policy=SizePolicy.EXACTO)

    # Verificar que no haya elementos sin colocar
    assert len(result.unplaced_items) == 0, f"Elementos sin colocar: {result.unplaced_items}"

    # Verificar que quepa en una hoja
    assert result.total_pages == 1, f"Se esperaba 1 hoja, se obtuvieron {result.total_pages}"

    # Verificar que se colocaron 3 elementos
    assert result.total_placements == 3, f"Se esperaban 3 placements, se obtuvieron {result.total_placements}"

    # Verificar ocupación razonable (debe ser alta)
    assert result.total_utilization_percent > 90, \
        f"Ocupación baja: {result.total_utilization_percent:.1f}%"


# ============================================================================
# PRUEBA 2: 3 A6 + 2 A7 con área A4 completa y separación cero
# ============================================================================

def test_3_a6_2_a7_no_margins(sample_a6_item, sample_a7_item, no_margins):
    """3 A6 + 2 A7 debe caber en una hoja A4 sin márgenes (distribución válida conocida)."""
    items = [
        MixedPosterItem.from_preset(id=f"a6_{i}", source_path=f"/fake/a6_{i}.png", preset=PaperSize.A6, quantity=1)
        for i in range(3)
    ] + [
        MixedPosterItem.from_preset(id=f"a7_{i}", source_path=f"/fake/a7_{i}.png", preset=PaperSize.A7, quantity=1)
        for i in range(2)
    ]

    result = pack_mixed_posters(items, margins=no_margins, size_policy=SizePolicy.EXACTO)

    # Verificar que no haya elementos sin colocar
    assert len(result.unplaced_items) == 0, f"Elementos sin colocar: {result.unplaced_items}"

    # Verificar que se colocaron 5 elementos
    assert result.total_placements == 5, f"Se esperaban 5 placements, se obtuvieron {result.total_placements}"

    # Esta combinación tiene una distribución válida conocida en una hoja A4
    # Distribución: 3 A6 (105x148) + 2 A7 rotados (105x74) = 210x296 mm total
    # Ocupación: 62160 / 62370 = 99.66%
    assert result.total_pages == 1, f"Se esperaba 1 hoja, se obtuvieron {result.total_pages}"

    # Verificar ocupación alta (debe ser aproximadamente 99.66%)
    assert result.total_utilization_percent > 95, \
        f"Ocupación inesperadamente baja: {result.total_utilization_percent:.1f}%"


def test_3_a6_2_a7_regression_detailed(no_margins):
    """Prueba de regresión específica para 3 A6 + 2 A7 con validaciones detalladas."""
    items = [
        MixedPosterItem.from_preset(id=f"a6_{i}", source_path=f"/fake/a6_{i}.png",
                                    preset=PaperSize.A6, quantity=1,
                                    orientation=Orientation.AUTOMATIC, allow_rotation=True)
        for i in range(3)
    ] + [
        MixedPosterItem.from_preset(id=f"a7_{i}", source_path=f"/fake/a7_{i}.png",
                                    preset=PaperSize.A7, quantity=1,
                                    orientation=Orientation.AUTOMATIC, allow_rotation=True)
        for i in range(2)
    ]

    result = pack_mixed_posters(items, margins=no_margins, size_policy=SizePolicy.EXACTO)

    # Validaciones básicas
    assert len(result.unplaced_items) == 0, f"Elementos sin colocar: {result.unplaced_items}"
    assert result.total_placements == 5, f"Se esperaban 5 placements, se obtuvieron {result.total_placements}"
    assert result.total_pages == 1, f"Se esperaba 1 hoja, se obtuvieron {result.total_pages}"

    # Validar ocupación aproximada de 99.66%
    expected_utilization = 99.66
    assert abs(result.total_utilization_percent - expected_utilization) < 5, \
        f"Ocupación {result.total_utilization_percent:.1f}% muy diferente de {expected_utilization}%"

    # Validar que no haya superposiciones
    page = result.pages[0]
    placements = page.placements
    for i, p1 in enumerate(placements):
        for p2 in placements[i + 1:]:
            assert not _rectangles_overlap(
                p1.x_mm, p1.y_mm, p1.width_mm, p1.height_mm,
                p2.x_mm, p2.y_mm, p2.width_mm, p2.height_mm
            ), f"Superposición entre {p1.item_id} y {p2.item_id}"

    # Validar que todos los elementos estén dentro de los límites A4 (210x297 mm)
    for placement in placements:
        assert placement.x_mm >= 0, f"x={placement.x_mm} < 0"
        assert placement.y_mm >= 0, f"y={placement.y_mm} < 0"
        assert placement.x_mm + placement.width_mm <= 210.0 + 0.1, \
            f"x+w={placement.x_mm + placement.width_mm} > 210"
        assert placement.y_mm + placement.height_mm <= 297.0 + 0.1, \
            f"y+h={placement.y_mm + placement.height_mm} > 297"

    # Validar que los A7 puedan rotarse (deben aparecer rotados en la solución óptima)
    a7_placements = [p for p in placements if p.item_id.startswith("a7")]
    # Al menos un A7 debe estar rotado para lograr la distribución óptima
    assert any(p.rotation for p in a7_placements), \
        "Ningún A7 está rotado; la distribución óptima requiere A7 rotados"


# ============================================================================
# PRUEBA 3: Mismas combinaciones con márgenes reales
# ============================================================================

def test_1_a5_2_a6_with_margins(sample_a5_item, sample_a6_item, standard_margins):
    """1 A5 + 2 A6 con márgenes reales."""
    items = [
        sample_a5_item,
        MixedPosterItem.from_preset(id="a6_2", source_path="/fake/a6_2.png", preset=PaperSize.A6, quantity=1),
        sample_a6_item,
    ]

    result = pack_mixed_posters(items, margins=standard_margins, size_policy=SizePolicy.EXACTO)

    # Con márgenes, puede requerir más de una hoja
    assert len(result.unplaced_items) == 0
    assert result.total_placements == 3

    # Verificar que todas las coordenadas estén dentro del área imprimible
    printable_width = 210.0 - standard_margins.horizontal_total
    printable_height = 297.0 - standard_margins.vertical_total

    for page in result.pages:
        for placement in page.placements:
            # La posición debe estar dentro del área imprimible
            assert placement.x_mm >= standard_margins.left, \
                f"x={placement.x_mm} < margen izquierdo={standard_margins.left}"
            assert placement.y_mm >= standard_margins.top, \
                f"y={placement.y_mm} < margen superior={standard_margins.top}"
            assert placement.x_mm + placement.width_mm <= standard_margins.left + printable_width, \
                f"x+w={placement.x_mm + placement.width_mm} > límite derecho={standard_margins.left + printable_width}"
            assert placement.y_mm + placement.height_mm <= standard_margins.top + printable_height, \
                f"y+h={placement.y_mm + placement.height_mm} > límite inferior={standard_margins.top + printable_height}"


def test_3_a6_2_a7_with_margins(sample_a6_item, sample_a7_item, standard_margins):
    """3 A6 + 2 A7 con márgenes reales."""
    items = [
        MixedPosterItem.from_preset(id=f"a6_{i}", source_path=f"/fake/a6_{i}.png", preset=PaperSize.A6, quantity=1)
        for i in range(3)
    ] + [
        MixedPosterItem.from_preset(id=f"a7_{i}", source_path=f"/fake/a7_{i}.png", preset=PaperSize.A7, quantity=1)
        for i in range(2)
    ]

    result = pack_mixed_posters(items, margins=standard_margins, size_policy=SizePolicy.EXACTO)

    assert len(result.unplaced_items) == 0
    assert result.total_placements == 5


# ============================================================================
# PRUEBA 4: Comparación entre política exacta y ajustar al área imprimible
# ============================================================================

def test_size_policy_comparison(sample_a5_item, sample_a6_item, standard_margins):
    """Compara política EXACTO vs AJUSTAR_AL_AREA_IMPRIMIBLE."""
    items = [
        sample_a5_item,
        MixedPosterItem.from_preset(id="a6_2", source_path="/fake/a6_2.png", preset=PaperSize.A6, quantity=2),
    ]

    # Política EXACTO
    result_exact = pack_mixed_posters(items, margins=standard_margins, size_policy=SizePolicy.EXACTO)

    # Política AJUSTAR
    result_adjust = pack_mixed_posters(items, margins=standard_margins, size_policy=SizePolicy.AJUSTAR_AL_AREA_IMPRIMIBLE)

    # Ambos deben colocar todos los elementos
    assert len(result_exact.unplaced_items) == 0
    assert len(result_adjust.unplaced_items) == 0

    # EXACTO debe tener scale_factor = 1.0
    assert result_exact.scale_factor == 1.0

    # AJUSTAR puede tener scale_factor <= 1.0
    assert result_adjust.scale_factor <= 1.0

    # Si AJUSTAR redujo, debe tener advertencia
    if result_adjust.scale_factor < 1.0:
        assert len(result_adjust.warnings) > 0
        # Verificar que la advertencia contenga informacion de escalado
        warning_lower = result_adjust.warnings[0].lower()
        assert any(word in warning_lower for word in ["escalado", "escala", "scale"])


# ============================================================================
# PRUEBA 5: Rotación automática activada y desactivada
# ============================================================================

def test_rotation_enabled(sample_a5_item, no_margins):
    """Rotación automática activada."""
    sample_a5_item.allow_rotation = True
    sample_a5_item.orientation = Orientation.AUTOMATIC

    result = pack_mixed_posters([sample_a5_item], margins=no_margins, size_policy=SizePolicy.EXACTO)

    assert len(result.unplaced_items) == 0
    assert result.total_placements == 1


def test_rotation_disabled(sample_a5_item, no_margins):
    """Rotación automática desactivada."""
    sample_a5_item.allow_rotation = False
    sample_a5_item.orientation = Orientation.PORTRAIT

    result = pack_mixed_posters([sample_a5_item], margins=no_margins, size_policy=SizePolicy.EXACTO)

    assert len(result.unplaced_items) == 0
    assert result.total_placements == 1

    # Verificar que no se rotó
    placement = result.pages[0].placements[0]
    assert placement.rotation == False


def test_forced_landscape(sample_a5_item, no_margins):
    """Orientación forzada a horizontal."""
    sample_a5_item.allow_rotation = False
    sample_a5_item.orientation = Orientation.LANDSCAPE

    result = pack_mixed_posters([sample_a5_item], margins=no_margins, size_policy=SizePolicy.EXACTO)

    assert len(result.unplaced_items) == 0
    assert result.total_placements == 1


# ============================================================================
# PRUEBA 6: Combinación que necesita varias hojas
# ============================================================================

def test_multiple_pages_needed(sample_a5_item, no_margins):
    """Combinación que requiere múltiples hojas."""
    items = [
        MixedPosterItem.from_preset(id=f"a5_{i}", source_path=f"/fake/a5_{i}.png", preset=PaperSize.A5, quantity=1)
        for i in range(10)
    ]

    result = pack_mixed_posters(items, margins=no_margins, size_policy=SizePolicy.EXACTO)

    assert len(result.unplaced_items) == 0
    assert result.total_placements == 10
    assert result.total_pages > 1, "Se esperaban múltiples hojas"


# ============================================================================
# PRUEBA 7: Cantidades grandes
# ============================================================================

def test_large_quantities(sample_a6_item, no_margins):
    """Prueba con cantidades grandes."""
    items = [
        MixedPosterItem.from_preset(
            preset=PaperSize.A6,
            id="a6_large",
            source_path="/fake/a6.png",
            quantity=50,
            orientation=Orientation.AUTOMATIC,
            allow_rotation=True,
        )
    ]

    result = pack_mixed_posters(items, margins=no_margins, size_policy=SizePolicy.EXACTO)

    assert len(result.unplaced_items) == 0
    assert result.total_placements == 50
    assert result.total_pages > 0


# ============================================================================
# PRUEBA 8: Resultado sin superposiciones
# ============================================================================

def test_no_overlaps(sample_a5_item, sample_a6_item, no_margins):
    """Verifica que no haya superposiciones entre elementos."""
    items = [
        sample_a5_item,
        sample_a6_item,
        MixedPosterItem.from_preset(id="a6_2", source_path="/fake/a6_2.png", preset=PaperSize.A6, quantity=1),
    ]

    result = pack_mixed_posters(items, margins=no_margins, size_policy=SizePolicy.EXACTO)

    assert len(result.unplaced_items) == 0

    # Verificar que no haya superposiciones en cada hoja
    for page in result.pages:
        placements = page.placements
        for i, p1 in enumerate(placements):
            for p2 in placements[i + 1:]:
                # Verificar que no se superpongan
                assert not _rectangles_overlap(
                    p1.x_mm, p1.y_mm, p1.width_mm, p1.height_mm,
                    p2.x_mm, p2.y_mm, p2.width_mm, p2.height_mm
                ), f"Superposición detectada entre {p1.item_id} y {p2.item_id}"


def _rectangles_overlap(x1, y1, w1, h1, x2, y2, w2, h2):
    """Verifica si dos rectángulos se superponen."""
    return not (
        x1 + w1 <= x2 or
        x2 + w2 <= x1 or
        y1 + h1 <= y2 or
        y2 + h2 <= y1
    )


# ============================================================================
# PRUEBA 9: Coordenadas siempre dentro del área imprimible
# ============================================================================

def test_coordinates_within_printable_area(sample_a5_item, sample_a6_item, standard_margins):
    """Verifica que todas las coordenadas estén dentro del área imprimible."""
    items = [sample_a5_item, sample_a6_item]

    result = pack_mixed_posters(items, margins=standard_margins, size_policy=SizePolicy.EXACTO)

    printable_width = 210.0 - standard_margins.horizontal_total
    printable_height = 297.0 - standard_margins.vertical_total

    for page in result.pages:
        for placement in page.placements:
            assert placement.x_mm >= standard_margins.left - 0.1, \
                f"x={placement.x_mm} < margen izquierdo={standard_margins.left}"
            assert placement.y_mm >= standard_margins.top - 0.1, \
                f"y={placement.y_mm} < margen superior={standard_margins.top}"
            assert placement.x_mm + placement.width_mm <= standard_margins.left + printable_width + 0.1, \
                f"x={placement.x_mm}, w={placement.width_mm} excede límite derecho"
            assert placement.y_mm + placement.height_mm <= standard_margins.top + printable_height + 0.1, \
                f"y={placement.y_mm}, h={placement.height_mm} excede límite inferior"


# ============================================================================
# PRUEBA 10: Resultado determinista en ejecuciones repetidas
# ============================================================================

def test_deterministic_result(sample_a5_item, sample_a6_item, no_margins):
    """El mismo input debe producir el mismo output."""
    items = [
        sample_a5_item,
        sample_a6_item,
        MixedPosterItem.from_preset(id="a6_2", source_path="/fake/a6_2.png", preset=PaperSize.A6, quantity=1),
    ]

    result1 = pack_mixed_posters(items, margins=no_margins, size_policy=SizePolicy.EXACTO)
    result2 = pack_mixed_posters(items, margins=no_margins, size_policy=SizePolicy.EXACTO)

    # Mismo número de hojas
    assert result1.total_pages == result2.total_pages

    # Mismo número de placements
    assert result1.total_placements == result2.total_placements

    # Misma ocupación
    assert abs(result1.total_utilization_percent - result2.total_utilization_percent) < 0.1


# ============================================================================
# PRUEBA 11: Ningún elemento perdido o duplicado
# ============================================================================

def test_no_lost_or_duplicated_items(sample_a5_item, sample_a6_item, no_margins):
    """Verifica que no se pierdan ni dupliquen elementos."""
    items = [
        MixedPosterItem.from_preset(id=f"item_{i}", source_path=f"/fake/item_{i}.png", preset=PaperSize.A6, quantity=1)
        for i in range(5)
    ]

    result = pack_mixed_posters(items, margins=no_margins, size_policy=SizePolicy.EXACTO)

    # No debe haber elementos sin colocar
    assert len(result.unplaced_items) == 0

    # Contar cuántas veces aparece cada item_id
    item_counts = {}
    for page in result.pages:
        for placement in page.placements:
            item_counts[placement.item_id] = item_counts.get(placement.item_id, 0) + 1

    # Cada item debe aparecer exactamente una vez
    for item in items:
        assert item_counts.get(item.id, 0) == 1, \
            f"Item {item.id} aparece {item_counts.get(item.id, 0)} veces, se esperaba 1"


# ============================================================================
# PRUEBA 12: Suma de copias colocadas igual a suma de cantidades solicitadas
# ============================================================================

def test_placement_count_equals_quantity(sample_a5_item, sample_a6_item, no_margins):
    """La suma de placements debe igualar la suma de quantities."""
    items = [
        MixedPosterItem.from_preset(id="a5_1", source_path="/fake/a5.png", preset=PaperSize.A5, quantity=2),
        MixedPosterItem.from_preset(id="a6_1", source_path="/fake/a6.png", preset=PaperSize.A6, quantity=3),
        MixedPosterItem.from_preset(id="a7_1", source_path="/fake/a7.png", preset=PaperSize.A7, quantity=1),
    ]

    total_requested = sum(item.quantity for item in items)

    result = pack_mixed_posters(items, margins=no_margins, size_policy=SizePolicy.EXACTO)

    assert result.total_placements == total_requested, \
        f"Placements={result.total_placements}, solicitados={total_requested}"


# ============================================================================
# PRUEBA 13: Factor de escala nunca superior a 1
# ============================================================================

def test_scale_factor_never_exceeds_1(sample_a5_item, sample_a6_item, no_margins):
    """El factor de escala nunca debe ser superior a 1."""
    items = [sample_a5_item, sample_a6_item]

    # Probar con ambas políticas
    for policy in [SizePolicy.EXACTO, SizePolicy.AJUSTAR_AL_AREA_IMPRIMIBLE]:
        result = pack_mixed_posters(items, margins=no_margins, size_policy=policy)
        assert result.scale_factor <= 1.0, \
            f"scale_factor={result.scale_factor} > 1.0 con política {policy}"


# ============================================================================
# PRUEBA 14: Algoritmo selecciona la menor cantidad de hojas
# ============================================================================

def test_minimizes_page_count(sample_a5_item, sample_a6_item, no_margins):
    """El algoritmo debe minimizar la cantidad de hojas."""
    items = [
        MixedPosterItem.from_preset(id=f"a6_{i}", source_path=f"/fake/a6_{i}.png", preset=PaperSize.A6, quantity=1)
        for i in range(8)
    ]

    result = pack_mixed_posters(items, margins=no_margins, size_policy=SizePolicy.EXACTO)

    # 8 A6 deben caber en 2 hojas A4 (4 por hoja)
    # Con separación 0, 4 A6 de 105x148 mm caben en 210x297 mm
    assert result.total_pages <= 2, f"Se esperaban máximo 2 hojas, se obtuvieron {result.total_pages}"


# ============================================================================
# PRUEBAS ADICIONALES DE VALIDACIÓN
# ============================================================================

def test_empty_items_list(no_margins):
    """Prueba con lista vacía de items."""
    result = pack_mixed_posters([], margins=no_margins, size_policy=SizePolicy.EXACTO)

    assert result.total_pages == 0
    assert result.total_placements == 0
    assert result.scale_factor == 1.0


def test_single_item_fits(sample_a5_item, no_margins):
    """Un solo item debe caber en una hoja."""
    result = pack_mixed_posters([sample_a5_item], margins=no_margins, size_policy=SizePolicy.EXACTO)

    assert result.total_pages == 1
    assert result.total_placements == 1
    assert len(result.unplaced_items) == 0


def test_impossible_fit(sample_a5_item, standard_margins):
    """Item que no cabe por márgenes excesivos."""
    huge_margins = MarginConfig(top=100, bottom=100, left=100, right=100, horizontal_gap=10, vertical_gap=10)

    result = pack_mixed_posters([sample_a5_item], margins=huge_margins, size_policy=SizePolicy.EXACTO)

    # Con política EXACTO, puede no caber
    # Con política AJUSTAR, debe escalar
    result_adjust = pack_mixed_posters([sample_a5_item], margins=huge_margins, size_policy=SizePolicy.AJUSTAR_AL_AREA_IMPRIMIBLE)

    assert result_adjust.scale_factor < 1.0, "Debe escalar para que quepa"


# ============================================================================
# PRUEBAS DE DIMENSIONES PERSONALIZADAS (NUEVAS)
# ============================================================================

def test_custom_dimensions_no_preset(no_margins):
    """Constructor sin PaperSize con dimensiones personalizadas (137.5 × 192 mm)."""
    item = MixedPosterItem(
        id="custom_1",
        source_path="/fake/custom.png",
        width_mm=137.5,
        height_mm=192.0,
        quantity=1,
        orientation=Orientation.AUTOMATIC,
        allow_rotation=True,
    )

    result = pack_mixed_posters([item], margins=no_margins, size_policy=SizePolicy.EXACTO)

    assert len(result.unplaced_items) == 0
    assert result.total_placements == 1
    assert result.total_pages == 1

    # Verificar que las dimensiones se mantuvieron exactas
    placement = result.pages[0].placements[0]
    assert abs(placement.width_mm - 137.5) < 0.1, f"Ancho incorrecto: {placement.width_mm}"
    assert abs(placement.height_mm - 192.0) < 0.1, f"Alto incorrecto: {placement.height_mm}"


def test_custom_non_iso_dimensions(no_margins):
    """Medidas no ISO (140×200, 65×90, 45×60) sin conversión a formatos estándar."""
    items = [
        MixedPosterItem(id="custom_1", source_path="/fake/c1.png", width_mm=140, height_mm=200, quantity=1),
        MixedPosterItem(id="custom_2", source_path="/fake/c2.png", width_mm=65, height_mm=90, quantity=2),
        MixedPosterItem(id="custom_3", source_path="/fake/c3.png", width_mm=45, height_mm=60, quantity=3),
    ]

    result = pack_mixed_posters(items, margins=no_margins, size_policy=SizePolicy.EXACTO)

    assert len(result.unplaced_items) == 0
    assert result.total_placements == 6

    # Verificar que las dimensiones se mantuvieron exactas
    for placement in result.pages[0].placements:
        if placement.item_id == "custom_1":
            assert abs(placement.width_mm - 140) < 0.1 and abs(placement.height_mm - 200) < 0.1
        elif placement.item_id == "custom_2":
            assert abs(placement.width_mm - 65) < 0.1 and abs(placement.height_mm - 90) < 0.1
        elif placement.item_id == "custom_3":
            assert abs(placement.width_mm - 45) < 0.1 and abs(placement.height_mm - 60) < 0.1


def test_custom_decimal_dimensions(no_margins):
    """Decimales (137.5×192, 72.3×104.8, 48.6×67.4) manteniendo precisión."""
    items = [
        MixedPosterItem(id="dec_1", source_path="/fake/d1.png", width_mm=137.5, height_mm=192.0, quantity=1),
        MixedPosterItem(id="dec_2", source_path="/fake/d2.png", width_mm=72.3, height_mm=104.8, quantity=1),
        MixedPosterItem(id="dec_3", source_path="/fake/d3.png", width_mm=48.6, height_mm=67.4, quantity=1),
    ]

    result = pack_mixed_posters(items, margins=no_margins, size_policy=SizePolicy.EXACTO)

    assert len(result.unplaced_items) == 0
    assert result.total_placements == 3

    # Verificar precisión de decimales (tolerancia de 0.1 mm)
    for placement in result.pages[0].placements:
        if placement.item_id == "dec_1":
            assert abs(placement.width_mm - 137.5) < 0.1, f"Ancho dec_1: {placement.width_mm}"
            assert abs(placement.height_mm - 192.0) < 0.1, f"Alto dec_1: {placement.height_mm}"
        elif placement.item_id == "dec_2":
            assert abs(placement.width_mm - 72.3) < 0.1, f"Ancho dec_2: {placement.width_mm}"
            assert abs(placement.height_mm - 104.8) < 0.1, f"Alto dec_2: {placement.height_mm}"
        elif placement.item_id == "dec_3":
            assert abs(placement.width_mm - 48.6) < 0.1, f"Ancho dec_3: {placement.width_mm}"
            assert abs(placement.height_mm - 67.4) < 0.1, f"Alto dec_3: {placement.height_mm}"


def test_custom_individual_rotation(no_margins):
    """Rotación individual con medidas personalizadas."""
    items = [
        MixedPosterItem(
            id="rot_1", source_path="/fake/r1.png",
            width_mm=100, height_mm=150, quantity=1,
            orientation=Orientation.AUTOMATIC, allow_rotation=True
        ),
        MixedPosterItem(
            id="rot_2", source_path="/fake/r2.png",
            width_mm=100, height_mm=150, quantity=1,
            orientation=Orientation.AUTOMATIC, allow_rotation=True
        ),
    ]

    result = pack_mixed_posters(items, margins=no_margins, size_policy=SizePolicy.EXACTO)

    assert len(result.unplaced_items) == 0
    assert result.total_placements == 2


def test_custom_too_large_element(no_margins):
    """Elemento demasiado grande (220×300 mm) con política EXACTO."""
    item = MixedPosterItem(
        id="too_large", source_path="/fake/large.png",
        width_mm=220, height_mm=300, quantity=1,
        orientation=Orientation.AUTOMATIC, allow_rotation=True
    )

    result = pack_mixed_posters([item], margins=no_margins, size_policy=SizePolicy.EXACTO)

    # Debe quedar sin colocar
    assert len(result.unplaced_items) == 1
    assert result.unplaced_items[0] == "too_large"
    assert result.total_placements == 0
    # No debe crear hojas vacías
    assert result.total_pages == 0


def test_custom_multiple_pages(no_margins):
    """Varias hojas con rectángulos personalizados."""
    items = [
        MixedPosterItem(id=f"rect_{i}", source_path=f"/fake/rect_{i}.png",
                       width_mm=80, height_mm=120, quantity=1)
        for i in range(10)
    ]

    result = pack_mixed_posters(items, margins=no_margins, size_policy=SizePolicy.EXACTO)

    assert len(result.unplaced_items) == 0
    assert result.total_placements == 10
    assert result.total_pages > 1

    # Verificar que no haya duplicados ni perdidos
    item_counts = {}
    for page in result.pages:
        for placement in page.placements:
            item_counts[placement.item_id] = item_counts.get(placement.item_id, 0) + 1

    for item in items:
        assert item_counts.get(item.id, 0) == 1, f"Item {item.id} aparece {item_counts.get(item.id, 0)} veces"


def test_preset_vs_direct_compatibility(no_margins):
    """Compatibilidad: A6 via preset vs directo debe producir mismo resultado."""
    # Via preset
    item_preset = MixedPosterItem.from_preset(
        preset=PaperSize.A6, id="a6_preset", source_path="/fake/a6_preset.png"
    )

    # Directo
    item_direct = MixedPosterItem(
        id="a6_direct", source_path="/fake/a6_direct.png",
        width_mm=105, height_mm=148
    )

    result_preset = pack_mixed_posters([item_preset], margins=no_margins, size_policy=SizePolicy.EXACTO)
    result_direct = pack_mixed_posters([item_direct], margins=no_margins, size_policy=SizePolicy.EXACTO)

    # Ambos deben tener el mismo resultado
    assert result_preset.total_pages == result_direct.total_pages
    assert result_preset.total_placements == result_direct.total_placements

    placement_preset = result_preset.pages[0].placements[0]
    placement_direct = result_direct.pages[0].placements[0]

    assert abs(placement_preset.width_mm - placement_direct.width_mm) < 0.1
    assert abs(placement_preset.height_mm - placement_direct.height_mm) < 0.1


def test_custom_dimension_validation():
    """Validación de dimensiones personalizadas."""
    # Ancho inválido
    with pytest.raises(ValueError, match="width_mm debe ser mayor que 0"):
        MixedPosterItem(id="bad", source_path="/fake.png", width_mm=0, height_mm=100)

    # Alto inválido
    with pytest.raises(ValueError, match="height_mm debe ser mayor que 0"):
        MixedPosterItem(id="bad", source_path="/fake.png", width_mm=100, height_mm=0)

    # Cantidad inválida
    with pytest.raises(ValueError, match="quantity debe ser mayor que 0"):
        MixedPosterItem(id="bad", source_path="/fake.png", width_mm=100, height_mm=100, quantity=0)

    # Dimensiones demasiado grandes
    with pytest.raises(ValueError, match="Dimensiones demasiado grandes"):
        MixedPosterItem(id="bad", source_path="/fake.png", width_mm=1500, height_mm=100)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
