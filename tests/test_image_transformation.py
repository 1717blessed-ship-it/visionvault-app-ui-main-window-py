"""Pruebas del sistema de transformación de imagen en modo mixto."""

import pytest
from pathlib import Path
from app.planchas.poster_print_editor import (
    FitMode,
    ImageTransform,
    MixedElement,
    _calculate_contain_scale,
    _calculate_cover_scale,
)
from app.planchas.poster_packing import Orientation, PaperSize


def test_fit_mode_enum():
    """Verifica el enum de modos de ajuste."""
    assert FitMode.CONTAIN.value == "contain"
    assert FitMode.COVER.value == "cover"
    assert FitMode.MANUAL.value == "manual"


def test_image_transform_defaults():
    """Verifica los valores por defecto de ImageTransform."""
    transform = ImageTransform()

    assert transform.fit_mode == FitMode.COVER
    assert transform.image_offset_x == 0.0
    assert transform.image_offset_y == 0.0
    assert transform.image_scale == 1.0
    assert transform.image_rotation_deg == 0.0
    assert transform.anchor_x == 0.5
    assert transform.anchor_y == 0.5
    assert transform.auto_fitted is True


def test_image_transform_custom():
    """Verifica la creación de ImageTransform con valores personalizados."""
    transform = ImageTransform(
        fit_mode=FitMode.CONTAIN,
        image_offset_x=10.0,
        image_offset_y=-5.0,
        image_scale=1.5,
        image_rotation_deg=45.0,
        anchor_x=0.3,
        anchor_y=0.7,
        auto_fitted=False,
    )

    assert transform.fit_mode == FitMode.CONTAIN
    assert transform.image_offset_x == 10.0
    assert transform.image_offset_y == -5.0
    assert transform.image_scale == 1.5
    assert transform.image_rotation_deg == 45.0
    assert transform.anchor_x == 0.3
    assert transform.anchor_y == 0.7
    assert transform.auto_fitted is False


def test_mixed_element_with_transform():
    """Verifica que MixedElement tenga transformación por defecto."""
    element = MixedElement(
        path=Path("/fake/image.png"),
        width_mm=100.0,
        height_mm=100.0,
    )

    assert element.transform is not None
    assert element.transform.fit_mode == FitMode.COVER
    assert isinstance(element.transform, ImageTransform)


def test_mixed_element_custom_transform():
    """Verifica que MixedElement acepte transformación personalizada."""
    custom_transform = ImageTransform(
        fit_mode=FitMode.CONTAIN,
        image_scale=2.0,
    )

    element = MixedElement(
        path=Path("/fake/image.png"),
        width_mm=100.0,
        height_mm=100.0,
        transform=custom_transform,
    )

    assert element.transform.fit_mode == FitMode.CONTAIN
    assert element.transform.image_scale == 2.0


def test_calculate_contain_scale():
    """Verifica el cálculo de escala para modo contain."""
    # Imagen más pequeña que marco - escala hacia arriba
    scale = _calculate_contain_scale(100, 100, 200, 200)
    assert scale == 2.0

    # Imagen más grande que marco - escala hacia abajo
    scale = _calculate_contain_scale(400, 400, 200, 200)
    assert scale == 0.5

    # Imagen del mismo tamaño
    scale = _calculate_contain_scale(200, 200, 200, 200)
    assert scale == 1.0

    # Imagen panorámara en marco vertical
    scale = _calculate_contain_scale(400, 100, 200, 200)
    assert scale == 0.5  # Limitado por ancho

    # Imagen vertical en marco panorámico
    scale = _calculate_contain_scale(100, 400, 200, 200)
    assert scale == 0.5  # Limitado por alto


def test_calculate_cover_scale():
    """Verifica el cálculo de escala para modo cover."""
    # Imagen más pequeña que marco - escala hacia arriba
    scale = _calculate_cover_scale(100, 100, 200, 200)
    assert scale == 2.0

    # Imagen más grande que marco - escala hacia abajo
    scale = _calculate_cover_scale(400, 400, 200, 200)
    assert scale == 0.5

    # Imagen del mismo tamaño
    scale = _calculate_cover_scale(200, 200, 200, 200)
    assert scale == 1.0

    # Imagen panorámica en marco vertical - escala para cubrir alto
    scale = _calculate_cover_scale(400, 100, 200, 200)
    assert scale == 2.0  # Escala para cubrir alto

    # Imagen vertical en marco panorámico - escala para cubrir ancho
    scale = _calculate_cover_scale(100, 400, 200, 200)
    assert scale == 2.0  # Escala para cubrir ancho


def test_contain_vs_cover_difference():
    """Verifica la diferencia entre contain y cover."""
    # Imagen panorámica (400x100) en marco cuadrado (200x200)
    contain_scale = _calculate_contain_scale(400, 100, 200, 200)
    cover_scale = _calculate_cover_scale(400, 100, 200, 200)

    # Contain: escala para que quepa completo (limitado por ancho)
    assert contain_scale == 0.5
    # Cover: escala para cubrir todo (limitado por alto)
    assert cover_scale == 2.0

    # Contain debe ser menor o igual que cover
    assert contain_scale <= cover_scale


def test_scale_edge_cases():
    """Verifica casos borde de cálculo de escala."""
    # Dimensiones cero
    scale = _calculate_contain_scale(0, 100, 200, 200)
    assert scale == 1.0  # Fallback a 1.0

    scale = _calculate_cover_scale(0, 100, 200, 200)
    assert scale == 1.0  # Fallback a 1.0

    # Marco muy pequeño
    scale = _calculate_contain_scale(1000, 1000, 1, 1)
    assert scale == 0.001


def test_transform_independence_from_packing():
    """Verifica que la transformación no afecte el packing físico."""
    element1 = MixedElement(
        path=Path("/fake/image.png"),
        width_mm=100.0,
        height_mm=100.0,
        transform=ImageTransform(fit_mode=FitMode.CONTAIN),
    )

    element2 = MixedElement(
        path=Path("/fake/image.png"),
        width_mm=100.0,
        height_mm=100.0,
        transform=ImageTransform(fit_mode=FitMode.COVER, image_scale=2.0),
    )

    # Las dimensiones físicas deben ser iguales
    assert element1.width_mm == element2.width_mm
    assert element1.height_mm == element2.height_mm

    # Las transformaciones deben ser diferentes
    assert element1.transform.fit_mode != element2.transform.fit_mode
    assert element1.transform.image_scale != element2.transform.image_scale


def test_transform_modes():
    """Verifica los diferentes modos de transformación."""
    # Contain
    contain = ImageTransform(fit_mode=FitMode.CONTAIN)
    assert contain.fit_mode == FitMode.CONTAIN

    # Cover
    cover = ImageTransform(fit_mode=FitMode.COVER)
    assert cover.fit_mode == FitMode.COVER

    # Manual
    manual = ImageTransform(fit_mode=FitMode.MANUAL)
    assert manual.fit_mode == FitMode.MANUAL


def test_offset_and_rotation():
    """Verifica offset y rotación de imagen."""
    transform = ImageTransform(
        image_offset_x=50.0,
        image_offset_y=-30.0,
        image_rotation_deg=90.0,
    )

    assert transform.image_offset_x == 50.0
    assert transform.image_offset_y == -30.0
    assert transform.image_rotation_deg == 90.0


def test_anchor_points():
    """Verifica puntos de anclaje."""
    # Centro (default)
    center = ImageTransform()
    assert center.anchor_x == 0.5
    assert center.anchor_y == 0.5

    # Esquina superior izquierda
    top_left = ImageTransform(anchor_x=0.0, anchor_y=0.0)
    assert top_left.anchor_x == 0.0
    assert top_left.anchor_y == 0.0

    # Esquina inferior derecha
    bottom_right = ImageTransform(anchor_x=1.0, anchor_y=1.0)
    assert bottom_right.anchor_x == 1.0
    assert bottom_right.anchor_y == 1.0


def test_auto_fitted_flag():
    """Verifica el flag auto_fitted."""
    # Por defecto es True
    default = ImageTransform()
    assert default.auto_fitted is True

    # Puede ser False
    manual = ImageTransform(auto_fitted=False)
    assert manual.auto_fitted is False


def test_scale_percentage_conversion():
    """Verifica conversión de escala a porcentaje."""
    transform = ImageTransform(image_scale=1.0)
    percentage = transform.image_scale * 100
    assert percentage == 100.0

    transform = ImageTransform(image_scale=1.5)
    percentage = transform.image_scale * 100
    assert percentage == 150.0

    transform = ImageTransform(image_scale=0.5)
    percentage = transform.image_scale * 100
    assert percentage == 50.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
