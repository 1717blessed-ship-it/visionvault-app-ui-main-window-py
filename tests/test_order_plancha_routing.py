import sqlite3
import uuid
from pathlib import Path
import json
import subprocess
import sys
import pytest

from app.database.database import ImageDatabase
from app.planchas.model import (
    FIVE_ROW_SIZE_CM,
    SPECIAL_GEOMETRIC,
    STANDARD_FIVE_BANDS,
    PlanchaProject,
    normalize_new_packing_mode,
    packing_mode_for_order_designs,
    order_design_group_id,
)
from app.ui.main_window import (
    VisionVaultApp,
    order_production_route,
    sticker_design_assignment_hint,
    sticker_design_assignment_count,
    sticker_design_assignment_progress,
)


def test_processed_separator_preserves_a_usable_inspector():
    assert VisionVaultApp.processed_separator_position(860, 0.98) == 580
    assert VisionVaultApp.processed_separator_position(1000, 0.10) == 450
    assert VisionVaultApp.processed_separator_position(500, 0.95) == 250


def test_assignment_hint_for_standard_formats_and_per_sticker_modes():
    assert sticker_design_assignment_hint({"material": "Franja"})[2:] == (4, 5)
    assert sticker_design_assignment_hint({"size": "A5"})[2:] == (11, 13)
    assert sticker_design_assignment_hint({"title": "Plancha A4"})[2:] == (20, 25)
    assert sticker_design_assignment_hint({}, [{"title": "Plancha personalizada A4", "quantity": 2}])[2:] == (40, 40)
    assert sticker_design_assignment_hint({}, [
        {"title": "Plancha personalizada A4", "quantity": 1},
        {"title": "Stickers individuales", "size": "29 cm", "quantity": 1},
    ])[2:] == (20, 20)
    assert sticker_design_assignment_hint({"title": "Plancha Doccione"})[2:] == (20, 24)
    assert sticker_design_assignment_hint({"title": "Plancha Diseño Único"})[2:] == (1, 1)
    assert sticker_design_assignment_hint({"title": "Plancha Personalizada Mixta"})[2:] == (None, None)
    assert sticker_design_assignment_hint({}, [{"title": "Póster fotográfico 16 por hoja", "quantity": 2}])[2:] == (32, 32)
    assert sticker_design_assignment_hint({}, [{"title": "Tarjeta personalizada", "quantity": 100}])[2:] == (1, 1)


def test_assignment_progress_uses_the_guided_design_target():
    assert sticker_design_assignment_progress(19, 20) == 95
    assert sticker_design_assignment_progress(21, 20) == 100
    assert sticker_design_assignment_progress(25, 20) == 100
    assert sticker_design_assignment_progress(3, None) is None


def test_assignment_count_includes_each_requested_copy():
    assert sticker_design_assignment_count([{"quantity": 1}, {"quantity": 3}]) == 4
    assert sticker_design_assignment_count([{}, {"quantity": "2"}]) == 3


def test_posters_and_cards_use_continuous_production_not_sticker_planchas():
    assert order_production_route({}, [{"title": "Póster fotográfico 4 por hoja"}]) == "photo_printing"
    assert order_production_route({}, [{"title": "Tarjeta personalizada"}]) == "continuous"
    assert order_production_route({}, [{"title": "Plancha Doccione"}]) == "plancha"
    assert sticker_design_assignment_hint({"material": "Plancha mixta"})[2:] == (None, None)
    assert sticker_design_assignment_hint({"material": "Individuales"})[2:] == (None, None)
from app.planchas.production_geometry import production_max_for_nominal, production_min_for_nominal


def mode(*sizes):
    return packing_mode_for_order_designs([{"size_cm": size} for size in sizes])


def test_all_nominal_five_uses_standard_five_bands():
    assert mode(5, 5, 5) == STANDARD_FIVE_BANDS


def test_mixed_and_special_nominal_sizes_use_geometric_mode():
    assert mode(5, 5, 7) == SPECIAL_GEOMETRIC
    assert mode(3, 7, 10) == SPECIAL_GEOMETRIC
    assert mode(7) == SPECIAL_GEOMETRIC


def test_legacy_geometric_name_normalizes_to_the_single_modern_mixed_engine():
    assert normalize_new_packing_mode(SPECIAL_GEOMETRIC) == "sticker_mixed"
    assert normalize_new_packing_mode(STANDARD_FIVE_BANDS) == STANDARD_FIVE_BANDS


def test_saved_special_geometric_project_stays_a_legacy_snapshot(tmp_path):
    folder = tmp_path / "legacy_special"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "legacy-special.json"
    path.write_text(json.dumps({
        "project_type": SPECIAL_GEOMETRIC,
        "layout_mode": "special",
        "items": [{"path": "a.png", "name": "A", "width_cm": 8, "height_cm": 4,
                   "x_cm": 2, "y_cm": 3, "rotation": 90, "layout_width_cm": 8.2,
                   "layout_height_cm": 4.2}],
    }), encoding="utf-8")
    project = PlanchaProject.load(path)
    item = project.items[0]
    assert project.project_type == "legacy"
    assert (item.x_cm, item.y_cm, item.width_cm, item.height_cm, item.rotation) == (2, 3, 8, 4, 90)


def test_standard_copies_keep_nominal_five_and_use_internal_five_band_hitbox():
    project = PlanchaProject.from_images([{
        "path": "standard.png", "name": "standard", "order_id": 10,
        "order_quantity": 6, "order_size_cm": 5.0,
        "order_packing_mode": STANDARD_FIVE_BANDS,
        "visible_width": 100, "visible_height": 100,
    }])
    assert len(project.items) == 6
    assert {item.nominal_size_cm for item in project.items} == {5.0}
    assert {item.order_id for item in project.items} == {10}
    assert {item.group_id for item in project.items}
    assert len({item.group_id for item in project.items}) == 1
    assert [item.copy_number for item in project.items] == [1, 2, 3, 4, 5, 6]
    assert all(item.width_cm == pytest.approx(min(production_max_for_nominal(5.0), FIVE_ROW_SIZE_CM - 0.02)) for item in project.items)
    assert all(item.reserved_width_cm == pytest.approx(FIVE_ROW_SIZE_CM) for item in project.items)
    assert all(round(item.width_cm / 2.54 * 300) == round((FIVE_ROW_SIZE_CM - 0.02) / 2.54 * 300) for item in project.items)


def test_special_quantity_expands_without_changing_nominal_cut_size():
    project = PlanchaProject.from_images([{
        "path": "special.png", "name": "special", "order_id": 11,
        "order_quantity": 6, "order_size_cm": 3.0,
        "order_packing_mode": SPECIAL_GEOMETRIC,
        "visible_width": 100, "visible_height": 100,
    }])
    assert len(project.items) == 6
    assert {item.nominal_size_cm for item in project.items} == {3.0}
    assert all(item.width_cm == pytest.approx(production_min_for_nominal(3.0)) for item in project.items)
    assert len({item.group_id for item in project.items}) == 1


def _order_image(path="C:/Banco/A.png", order_id=27, quantity=3):
    return {
        "path": path, "name": Path(path).name, "order_id": order_id,
        "order_quantity": quantity, "order_size_cm": 5.0,
        "order_packing_mode": STANDARD_FIVE_BANDS,
        "visible_width": 100, "visible_height": 100,
    }


def test_order_copy_identities_are_deterministic_across_rebuilds():
    snapshots = []
    for _ in range(3):
        items = PlanchaProject.from_images([_order_image()]).items
        snapshots.append([(item.group_id, item.item_id, item.copy_number) for item in items])
    assert snapshots[0] == snapshots[1] == snapshots[2]


def test_order_identity_distinguishes_copies_designs_and_orders():
    copies = PlanchaProject.from_images([_order_image(quantity=5)]).items
    assert len({item.group_id for item in copies}) == 1
    assert len({item.item_id for item in copies}) == 5
    assert [item.copy_number for item in copies] == [1, 2, 3, 4, 5]
    other_design = PlanchaProject.from_images([_order_image(path="C:/Banco/B.png")]).items[0]
    other_order = PlanchaProject.from_images([_order_image(order_id=28)]).items[0]
    assert copies[0].group_id != other_design.group_id
    assert copies[0].group_id != other_order.group_id


def test_windows_equivalent_paths_share_group_identity():
    assert order_design_group_id(27, r"C:\Banco\A.PNG") == order_design_group_id(27, "c:/banco/a.png")


def test_item_identity_is_independent_of_packing_fields():
    item = PlanchaProject.from_images([_order_image()]).items[0]
    before = item.item_id
    item.x_cm, item.y_cm, item.rotation = 8.0, 12.0, 90
    assert item.item_id == before


def test_order_identity_is_deterministic_across_python_processes():
    code = (
        "import json; from app.planchas.model import PlanchaProject, STANDARD_FIVE_BANDS; "
        "i={'path':'C:/Banco/A.png','order_id':27,'order_quantity':2,'order_size_cm':5.0,"
        "'order_packing_mode':STANDARD_FIVE_BANDS,'visible_width':100,'visible_height':100}; "
        "print(json.dumps([(x.group_id,x.item_id) for x in PlanchaProject.from_images([i]).items]))"
    )
    first = subprocess.check_output([sys.executable, "-c", code], text=True, cwd=Path.cwd()).strip()
    second = subprocess.check_output([sys.executable, "-c", code], text=True, cwd=Path.cwd()).strip()
    assert json.loads(first) == json.loads(second)


def test_standard_rectangles_keep_aspect_and_orient_longest_side_vertically():
    horizontal = PlanchaProject.from_images([{
        "path": "wide.png", "order_size_cm": 5.0, "order_packing_mode": STANDARD_FIVE_BANDS,
        "visible_width": 200, "visible_height": 100,
    }]).items[0]
    vertical = PlanchaProject.from_images([{
        "path": "tall.png", "order_size_cm": 5.0, "order_packing_mode": STANDARD_FIVE_BANDS,
        "visible_width": 100, "visible_height": 200,
    }]).items[0]
    production = min(production_max_for_nominal(5.0), FIVE_ROW_SIZE_CM - 0.02)
    assert (horizontal.width_cm, horizontal.height_cm) == pytest.approx((production / 2, production))
    assert (vertical.width_cm, vertical.height_cm) == pytest.approx((production / 2, production))
    assert horizontal.rotation == 90
    assert vertical.rotation == 0
    assert horizontal.reserved_width_cm == pytest.approx(production / 2 + 0.02)
    assert horizontal.reserved_height_cm == pytest.approx(5.7)
    assert vertical.reserved_width_cm == pytest.approx(production / 2 + 0.02)
    assert vertical.reserved_height_cm == pytest.approx(5.7)


def test_existing_quarter_turn_is_not_applied_twice_when_orienting_vertical():
    item = PlanchaProject.from_images([{
        "path": "already-rotated-wide.png",
        "order_size_cm": 5.0,
        "order_packing_mode": STANDARD_FIVE_BANDS,
        "visible_width": 200,
        "visible_height": 100,
        "rotation": 90,
    }]).items[0]

    assert item.height_cm > item.width_cm
    assert item.rotation == 90


def test_standard_project_equalizes_same_nominal_from_different_entry_paths():
    order_item = PlanchaProject.from_images([{
        "path": "order.png",
        "order_size_cm": 5.0,
        "order_packing_mode": STANDARD_FIVE_BANDS,
        "visible_width": 100,
        "visible_height": 200,
    }]).items[0]
    library_item = PlanchaProject.from_images([{
        "path": "library.png",
        "order_size_cm": 5.0,
        "visible_width": 100,
        "visible_height": 200,
    }]).items[0]
    assert max(library_item.width_cm, library_item.height_cm) < max(
        order_item.width_cm, order_item.height_cm)

    project = PlanchaProject(
        [order_item, library_item], project_type="sticker_standard",
    )
    project.optimize()

    expected = min(production_max_for_nominal(5.0), FIVE_ROW_SIZE_CM - 0.02)
    assert max(order_item.width_cm, order_item.height_cm) == pytest.approx(expected)
    assert max(library_item.width_cm, library_item.height_cm) == pytest.approx(expected)
    assert order_item.height_cm / order_item.width_cm == pytest.approx(2.0)
    assert library_item.height_cm / library_item.width_cm == pytest.approx(2.0)


def test_selected_standard_items_are_equalized_before_pagination():
    large = PlanchaProject.from_images([{
        "path": "selected-order.png", "order_size_cm": 5.0,
        "order_packing_mode": STANDARD_FIVE_BANDS,
        "visible_width": 100, "visible_height": 200,
    }]).items[0]
    small = PlanchaProject.from_images([{
        "path": "selected-library.png", "order_size_cm": 5.0,
        "visible_width": 100, "visible_height": 200,
    }]).items[0]

    pages = PlanchaProject.calculate_pagination(
        [large, small], project_type="sticker_standard",
    )
    placed = [item for page in pages for item in page.items]
    majors = [max(item.width_cm, item.height_cm) for item in placed]

    assert len(placed) == 2
    assert majors[0] == pytest.approx(majors[1])
    assert all(page.project_type == "sticker_standard" for page in pages)


def test_legacy_59_migrates_to_nominal_5_idempotently():
    path = Path("artifacts") / f"test_nominal_size_{uuid.uuid4().hex}.db"
    path.parent.mkdir(exist_ok=True)
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE order_designs (order_id INTEGER NOT NULL, image_path TEXT NOT NULL, quantity INTEGER DEFAULT 1, size_cm REAL DEFAULT 5.9, rotation INTEGER DEFAULT 0, PRIMARY KEY(order_id, image_path))")
    raw.execute("INSERT INTO order_designs(order_id, image_path, quantity, size_cm) VALUES(1, 'legacy.png', 1, 5.9)")
    raw.commit()
    raw.close()

    database = ImageDatabase(path)
    assert database.connection.execute("SELECT size_cm FROM order_designs").fetchone()[0] == 5.0
    assert str(database.connection.execute("PRAGMA table_info(order_designs)").fetchall()[3][4]) == "5.0"
    database._migrate_order_designs_nominal_size()
    assert database.connection.execute("SELECT size_cm FROM order_designs").fetchone()[0] == 5.0
    database.connection.close()
    path.unlink()
