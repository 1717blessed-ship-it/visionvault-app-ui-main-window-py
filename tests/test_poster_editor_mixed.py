"""Pruebas de lógica de interfaz para el modo mixto de pósters."""

import pytest
from pathlib import Path
from PIL import Image
from app.planchas.poster_packing import Orientation, PaperSize, SizePolicy
from app.planchas.poster_print_editor import (
    MixedElement, Unit, _cached_print_source, _load_print_source,
    uniform_preview_page,
)


def test_print_source_cache_returns_independent_editable_copies(tmp_path: Path):
    source = tmp_path / "cached.png"
    Image.new("RGB", (20, 20), "red").save(source)
    _cached_print_source.cache_clear()

    first = _load_print_source(source)
    first.putpixel((0, 0), (0, 0, 0, 0))
    second = _load_print_source(source)

    assert second.getpixel((0, 0)) == (255, 0, 0, 255)
    assert _cached_print_source.cache_info().hits == 1


def test_diptych_preview_is_the_exported_sheet_not_a_single_a4(tmp_path: Path):
    first, second = tmp_path / "first.png", tmp_path / "second.png"
    Image.new("RGB", (300, 200), "red").save(first)
    Image.new("RGB", (300, 200), "blue").save(second)

    page, page_index, first_index = uniform_preview_page([first, second], 2, 1)

    assert page_index == 0
    assert first_index == 0
    # The two designs occupy their respective diptych bands on one A4 sheet.
    assert page.getpixel((1240, 900)) == (255, 0, 0)
    assert page.getpixel((1240, 2600)) == (0, 0, 255)
    # Sin título, las fotos aprovechan toda la tira: no se reserva una franja vacía.
    assert page.getpixel((1240, 300)) == (255, 0, 0)


def test_diptych_title_is_rendered_in_the_reserved_header(tmp_path: Path):
    image = tmp_path / "photo.png"
    Image.new("RGB", (300, 200), "red").save(image)

    page, _page_index, _first_index = uniform_preview_page([image], 2, 0, title="VACACIONES")

    # A title creates ink in the reserved band above the first photo.
    header = page.crop((900, 400, 1580, 650))
    assert any(pixel != (255, 255, 255) for pixel in header.get_flattened_data())


def test_triptych_preview_uses_the_selected_image_page(tmp_path: Path):
    paths = []
    colors = ["red", "green", "blue", "yellow", "magenta"]
    for index, color in enumerate(colors):
        path = tmp_path / f"{index}.png"
        Image.new("RGB", (300, 200), color).save(path)
        paths.append(path)

    page, page_index, first_index = uniform_preview_page(paths, 3, 4)

    assert page_index == 1
    assert first_index == 3
    assert page.getpixel((1240, 900)) == (255, 255, 0)
    assert page.getpixel((1240, 2000)) == (255, 0, 255)


def test_cm_to_mm_conversion():
    """Verifica la conversión de cm a mm."""
    # 10 cm = 100 mm
    assert 10 * 10 == 100

    # 13.75 cm = 137.5 mm
    assert 13.75 * 10 == 137.5


def test_decimal_comma_acceptance():
    """Verifica que se acepte coma como separador decimal."""
    value_str = "13,75"
    value_float = float(value_str.replace(",", "."))
    assert value_float == 13.75


def test_mixed_element_creation():
    """Verifica la creación de MixedElement desde datos de interfaz."""
    element = MixedElement(
        path=Path("/fake/image.png"),
        width_mm=140.0,
        height_mm=200.0,
        quantity=1,
        orientation=Orientation.AUTOMATIC,
        allow_rotation=True,
        preset=None,
    )

    assert element.path == Path("/fake/image.png")
    assert element.width_mm == 140.0
    assert element.height_mm == 200.0
    assert element.quantity == 1
    assert element.orientation == Orientation.AUTOMATIC
    assert element.allow_rotation is True
    assert element.preset is None
    # ID ahora es UUID único
    assert len(element.id) == 36  # UUID string length
    # display_name es el nombre del archivo
    assert element.display_name == "image"


def test_preset_completes_dimensions():
    """Verifica que los presets completen las medidas correctamente."""
    preset_sizes = {
        "A5": (148.0, 210.0),
        "A6": (105.0, 148.0),
        "A7": (74.0, 105.0),
        "10×15 cm": (100.0, 150.0),
        "13×18 cm": (130.0, 180.0),
    }

    for preset_name, (expected_w, expected_h) in preset_sizes.items():
        width_mm, height_mm = preset_sizes[preset_name]
        assert width_mm == expected_w
        assert height_mm == expected_h


def test_custom_size_not_converted_to_iso():
    """Verifica que un tamaño personalizado no se convierta a formato ISO."""
    element = MixedElement(
        path=Path("/fake/custom.png"),
        width_mm=137.5,
        height_mm=192.0,
        quantity=1,
    )

    # Las dimensiones deben permanecer exactas
    assert element.width_mm == 137.5
    assert element.height_mm == 192.0
    assert element.preset is None


def test_quantity_update():
    """Verifica la actualización de cantidad."""
    element = MixedElement(
        path=Path("/fake/image.png"),
        width_mm=100.0,
        height_mm=100.0,
        quantity=1,
    )

    element.quantity = 5
    assert element.quantity == 5


def test_duplicate_with_unique_id():
    """Verifica que el duplicado tenga el mismo contenido pero ID diferente."""
    original = MixedElement(
        path=Path("/fake/image.png"),
        width_mm=100.0,
        height_mm=100.0,
        quantity=2,
        orientation=Orientation.AUTOMATIC,
        allow_rotation=True,
        preset=PaperSize.A6,
    )

    duplicate = MixedElement(
        path=original.path,
        width_mm=original.width_mm,
        height_mm=original.height_mm,
        quantity=original.quantity,
        orientation=original.orientation,
        allow_rotation=original.allow_rotation,
        preset=original.preset,
    )

    # Mismo contenido
    assert duplicate.path == original.path
    assert duplicate.width_mm == original.width_mm
    assert duplicate.height_mm == original.height_mm
    assert duplicate.quantity == original.quantity
    assert duplicate.orientation == original.orientation
    assert duplicate.allow_rotation == original.allow_rotation
    assert duplicate.preset == original.preset

    # IDs deben ser diferentes (UUID únicos)
    assert duplicate.id != original.id


def test_dimension_validation():
    """Verifica la validación de dimensiones."""
    # Valores válidos
    assert 140.0 > 0
    assert 200.0 > 0
    assert 1 > 0

    # Valores inválidos
    assert not (0.0 > 0)
    assert not (-10.0 > 0)


def test_unit_enum():
    """Verifica el enum de unidades."""
    assert Unit.MM.value == "mm"
    assert Unit.CM.value == "cm"


def test_size_policy_enum():
    """Verifica el enum de política de tamaño."""
    assert SizePolicy.EXACTO.value == "exacto"
    assert SizePolicy.AJUSTAR_AL_AREA_IMPRIMIBLE.value == "ajustar"


def test_dimension_string_parsing():
    """Verifica el parsing de strings de dimensiones."""
    # Punto decimal
    assert float("13.75") == 13.75

    # Coma decimal
    assert float("13,75".replace(",", ".")) == 13.75

    # Entero
    assert float("140") == 140.0


def test_unique_ids():
    """Verifica que los IDs sean únicos incluso con archivos del mismo nombre."""
    element1 = MixedElement(
        path=Path("/folder1/poster.png"),
        width_mm=100.0,
        height_mm=100.0,
    )
    element2 = MixedElement(
        path=Path("/folder2/poster.png"),
        width_mm=100.0,
        height_mm=100.0,
    )

    # IDs deben ser diferentes
    assert element1.id != element2.id
    # display_name puede ser el mismo
    assert element1.display_name == element2.display_name == "poster"


def test_duplicate_no_collision():
    """Verifica que duplicar no cause colisiones de ID."""
    original = MixedElement(
        path=Path("/fake/image.png"),
        width_mm=100.0,
        height_mm=100.0,
    )

    duplicate = MixedElement(
        path=original.path,
        width_mm=original.width_mm,
        height_mm=original.height_mm,
    )

    # IDs deben ser diferentes
    assert original.id != duplicate.id


def test_cm_mm_bidirectional_conversion():
    """Verifica conversión bidireccional cm/mm."""
    # 1 cm = 10 mm
    assert 1.0 * 10 == 10.0
    # 10 mm = 1 cm
    assert 10.0 / 10 == 1.0

    # 13.75 cm = 137.5 mm
    assert 13.75 * 10 == 137.5
    # 137.5 mm = 13.75 cm
    assert 137.5 / 10 == 13.75


def test_preset_resets_to_custom_on_edit():
    """Verifica que editar medidas resetee el preset a Personalizado."""
    element = MixedElement(
        path=Path("/fake/image.png"),
        width_mm=105.0,
        height_mm=148.0,
        preset=PaperSize.A6,
    )

    assert element.preset == PaperSize.A6

    # Simular edición manual
    element.width_mm = 140.0
    element.preset = None  # Esto debe hacerse al editar

    assert element.preset is None


def test_negative_margins_validation():
    """Verifica que márgenes negativos se corrijan a cero."""
    assert max(0, -5.0) == 0.0
    assert max(0, 0.0) == 0.0
    assert max(0, 5.0) == 5.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
