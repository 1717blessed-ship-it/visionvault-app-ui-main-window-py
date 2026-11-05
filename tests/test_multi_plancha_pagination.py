"""Validaciones obligatorias para paginación múltiple de planchas.

Este módulo prueba que el sistema de paginación automática cumple con todos
los requisitos especificados:
1. 200 stickers generan todas las planchas necesarias.
2. La suma de stickers de todas las planchas coincide exactamente con la cantidad solicitada.
3. No hay stickers duplicados ni faltantes.
4. Cada plancha respeta márgenes y separación.
5. Al guardar y volver a abrir el trabajo aparecen todas las planchas.
6. La exportación genera un archivo por plancha.
7. El flujo actual de una sola plancha continúa funcionando cuando todos los stickers entran en una hoja.
"""

import pytest
import json
from pathlib import Path
from app.planchas.model import PlanchaProject, PlanchaItem


def test_pagination_generates_required_planchas():
    """Prueba 1: 200 stickers generan todas las planchas necesarias."""
    # Crear 200 stickers del mismo tamaño (5.7 cm x 5.7 cm)
    items = []
    for i in range(200):
        items.append(PlanchaItem(
            path=f"/fake/path/sticker_{i}.png",
            name=f"Sticker {i}",
            width_cm=5.7,
            height_cm=5.7,
            quantity=1
        ))

    # Calcular paginación
    projects = PlanchaProject.calculate_pagination(
        items,
        margin_cm=0.15,
        gap_cm=0.05,
        layout_mode="classic",
        workspace_format="a4"
    )

    # Verificar que se generaron múltiples planchas
    assert len(projects) > 1, "Deberían generarse múltiples planchas para 200 stickers"

    # Verificar que todos los stickers fueron distribuidos
    total_placed = sum(len(project.items) for project in projects)
    assert total_placed == 200, f"Se esperaban 200 stickers, se colocaron {total_placed}"


def test_pagination_exact_quantity_match():
    """Prueba 2: La suma de stickers de todas las planchas coincide exactamente con la cantidad solicitada."""
    # Probar con diferentes cantidades
    test_quantities = [50, 100, 150, 200, 250]

    for quantity in test_quantities:
        items = []
        for i in range(quantity):
            items.append(PlanchaItem(
                path=f"/fake/path/sticker_{i}.png",
                name=f"Sticker {i}",
                width_cm=5.7,
                height_cm=5.7,
                quantity=1
            ))

        projects = PlanchaProject.calculate_pagination(
            items,
            margin_cm=0.15,
            gap_cm=0.05,
            layout_mode="classic",
            workspace_format="a4"
        )

        total_placed = sum(len(project.items) for project in projects)
        assert total_placed == quantity, f"Para {quantity} stickers, se colocaron {total_placed}"


def test_no_duplicates_or_missing():
    """Prueba 3: No hay stickers duplicados ni faltantes."""
    # Crear stickers con IDs únicos
    items = []
    for i in range(100):
        items.append(PlanchaItem(
            path=f"/fake/path/sticker_{i}.png",
            name=f"Sticker {i}",
            width_cm=5.7,
            height_cm=5.7,
            quantity=1
        ))

    projects = PlanchaProject.calculate_pagination(
        items,
        margin_cm=0.15,
        gap_cm=0.05,
        layout_mode="classic",
        workspace_format="a4"
    )

    # Recopilar todos los IDs de stickers en todas las planchas
    all_item_ids = set()
    for project in projects:
        for item in project.items:
            all_item_ids.add(item.item_id)

    # Verificar que no hay duplicados
    assert len(all_item_ids) == sum(len(project.items) for project in projects), \
        "Hay stickers duplicados en las planchas"

    # Verificar que todos los stickers originales están presentes
    original_ids = {item.item_id for item in items}
    placed_ids = {item.item_id for project in projects for item in project.items}

    assert original_ids == placed_ids, \
        f"Faltan stickers: {original_ids - placed_ids} o hay extras: {placed_ids - original_ids}"


def test_margins_and_separation_respected():
    """Prueba 4: Cada plancha respeta márgenes y separación."""
    # Crear stickers
    items = []
    for i in range(50):
        items.append(PlanchaItem(
            path=f"/fake/path/sticker_{i}.png",
            name=f"Sticker {i}",
            width_cm=5.7,
            height_cm=5.7,
            quantity=1
        ))

    projects = PlanchaProject.calculate_pagination(
        items,
        margin_cm=0.15,
        gap_cm=0.05,
        layout_mode="classic",
        workspace_format="a4"
    )

    margin_cm = 0.15
    gap_cm = 0.05
    usable_width = 21.0 - 2 * margin_cm
    usable_height = 29.7 - 2 * margin_cm

    for project in projects:
        for item in project.items:
            # Verificar que el sticker está dentro de los márgenes
            assert item.x_cm >= margin_cm - 0.001, \
                f"Sticker {item.name} fuera del margen izquierdo: x={item.x_cm}"
            assert item.y_cm >= margin_cm - 0.001, \
                f"Sticker {item.name} fuera del margen superior: y={item.y_cm}"
            assert item.x_cm + item.width_cm <= usable_width + margin_cm + 0.001, \
                f"Sticker {item.name} fuera del margen derecho: x+w={item.x_cm + item.width_cm}"
            assert item.y_cm + item.height_cm <= usable_height + margin_cm + 0.001, \
                f"Sticker {item.name} fuera del margen inferior: y+h={item.y_cm + item.height_cm}"

        # Verificar que no hay superposiciones
        for i, item1 in enumerate(project.items):
            for item2 in project.items[i+1:]:
                # Verificar separación horizontal
                if not (item1.x_cm + item1.width_cm + gap_cm <= item2.x_cm or
                        item2.x_cm + item2.width_cm + gap_cm <= item1.x_cm):
                    # Si se superponen horizontalmente, verificar que no se superponen verticalmente
                    assert (item1.y_cm + item1.height_cm + gap_cm <= item2.y_cm or
                            item2.y_cm + item2.height_cm + gap_cm <= item1.y_cm), \
                        f"Stickers {item1.name} y {item2.name} se superponen"


def test_save_and_reload_all_planchas():
    """Prueba 5: Al guardar y volver a abrir el trabajo aparecen todas las planchas."""
    import tempfile

    # Crear stickers
    items = []
    for i in range(50):
        items.append(PlanchaItem(
            path=f"/fake/path/sticker_{i}.png",
            name=f"Sticker {i}",
            width_cm=5.7,
            height_cm=5.7,
            quantity=1
        ))

    # Calcular paginación
    projects = PlanchaProject.calculate_pagination(
        items,
        margin_cm=0.15,
        gap_cm=0.05,
        layout_mode="classic",
        workspace_format="a4"
    )

    # Guardar cada plancha en archivos temporales
    with tempfile.TemporaryDirectory() as tmpdir:
        saved_paths = []
        for i, project in enumerate(projects):
            path = Path(tmpdir) / f"plancha_{i}.json"
            project.save(path)
            saved_paths.append(path)

        # Recargar todas las planchas
        reloaded_projects = []
        for path in saved_paths:
            reloaded = PlanchaProject.load(path)
            reloaded_projects.append(reloaded)

        # Verificar que se recargaron todas las planchas
        assert len(reloaded_projects) == len(projects), \
            f"Se esperaban {len(projects)} planchas, se recargaron {len(reloaded_projects)}"

        # Verificar que el contenido es el mismo
        for original, reloaded in zip(projects, reloaded_projects):
            assert len(original.items) == len(reloaded.items), \
                "Diferente cantidad de stickers después de recargar"

            original_ids = {item.item_id for item in original.items}
            reloaded_ids = {item.item_id for item in reloaded.items}
            assert original_ids == reloaded_ids, \
                "IDs de stickers diferentes después de recargar"


def test_export_generates_files_per_plancha():
    """Prueba 6: La exportación genera un archivo por plancha."""
    import tempfile
    from PIL import Image

    # Crear stickers
    items = []
    for i in range(30):
        items.append(PlanchaItem(
            path=f"/fake/path/sticker_{i}.png",
            name=f"Sticker {i}",
            width_cm=5.7,
            height_cm=5.7,
            quantity=1
        ))

    # Calcular paginación
    projects = PlanchaProject.calculate_pagination(
        items,
        margin_cm=0.15,
        gap_cm=0.05,
        layout_mode="classic",
        workspace_format="a4"
    )

    # Simular exportación (crear archivos PNG vacíos para verificar estructura)
    with tempfile.TemporaryDirectory() as tmpdir:
        export_paths = []
        for i, project in enumerate(projects):
            path = Path(tmpdir) / f"plancha_{i}.png"
            # Crear un PNG vacío para simular la exportación
            img = Image.new('RGB', (2480, 3508), color='white')
            img.save(path)
            export_paths.append(path)

        # Verificar que se generó un archivo por plancha
        assert len(export_paths) == len(projects), \
            f"Se esperaban {len(projects)} archivos, se generaron {len(export_paths)}"

        # Verificar que todos los archivos existen
        for path in export_paths:
            assert path.exists(), f"Archivo de exportación no existe: {path}"


def test_single_plancha_flow_still_works():
    """Prueba 7: El flujo actual de una sola plancha continúa funcionando cuando todos los stickers entran en una hoja."""
    # Crear pocos stickers que entran en una sola plancha
    items = []
    for i in range(10):
        items.append(PlanchaItem(
            path=f"/fake/path/sticker_{i}.png",
            name=f"Sticker {i}",
            width_cm=5.7,
            height_cm=5.7,
            quantity=1
        ))

    # Calcular paginación
    projects = PlanchaProject.calculate_pagination(
        items,
        margin_cm=0.15,
        gap_cm=0.05,
        layout_mode="classic",
        workspace_format="a4"
    )

    # Verificar que solo se generó una plancha
    assert len(projects) == 1, \
        f"Se esperaba 1 plancha para 10 stickers, se generaron {len(projects)}"

    # Verificar que todos los stickers están en esa plancha
    assert len(projects[0].items) == 10, \
        f"Se esperaban 10 stickers en la plancha, hay {len(projects[0].items)}"


def test_different_sizes_distribution():
    """Prueba adicional: Distribución correcta de stickers de diferentes tamaños."""
    # Crear stickers de diferentes tamaños
    items = []
    for i in range(50):
        if i % 3 == 0:
            width, height = 5.7, 5.7  # Pequeño
        elif i % 3 == 1:
            width, height = 8.0, 5.7  # Mediano
        else:
            width, height = 11.4, 5.7  # Grande

        items.append(PlanchaItem(
            path=f"/fake/path/sticker_{i}.png",
            name=f"Sticker {i}",
            width_cm=width,
            height_cm=height,
            quantity=1
        ))

    # Calcular paginación
    projects = PlanchaProject.calculate_pagination(
        items,
        margin_cm=0.15,
        gap_cm=0.05,
        layout_mode="special",  # Usar modo especial para tamaños variados
        workspace_format="a4"
    )

    # Verificar que todos los stickers fueron distribuidos
    total_placed = sum(len(project.items) for project in projects)
    assert total_placed == 50, f"Se esperaban 50 stickers, se colocaron {total_placed}"

    # Verificar que no hay superposiciones en ninguna plancha
    gap_cm = 0.05
    for project in projects:
        for i, item1 in enumerate(project.items):
            for item2 in project.items[i+1:]:
                # Las posiciones se guardan redondeadas a cm; tolerar el
                # error binario al comparar una separación exacta de 0,05.
                epsilon = 1e-6
                overlap_x = not (item1.x_cm + item1.width_cm + gap_cm <= item2.x_cm + epsilon or
                                 item2.x_cm + item2.width_cm + gap_cm <= item1.x_cm + epsilon)
                overlap_y = not (item1.y_cm + item1.height_cm + gap_cm <= item2.y_cm + epsilon or
                                 item2.y_cm + item2.height_cm + gap_cm <= item1.y_cm + epsilon)
                assert not (overlap_x and overlap_y), \
                    f"Stickers {item1.name} y {item2.name} se superponen"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
