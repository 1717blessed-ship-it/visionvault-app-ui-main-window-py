import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.database.database import ImageDatabase
from app.planchas.editor import PlanchaEditor
from app.planchas.model import PlanchaItem, PlanchaProject
from app.planchas.template_model import (
    A4_HEIGHT_CM,
    A4_WIDTH_CM,
    REGULAR_GAP_CM,
    REGULAR_MARGIN_CM,
    REGULAR_PATTERNS,
    RegularTemplateProject,
    TemplateResource,
)
from app.printing.windows_print import validate_a4_png


class RegularAndFreeContracts(unittest.TestCase):
    def test_regular_patterns_reserve_plotter_safety_margin(self):
        for pattern_id, definition in REGULAR_PATTERNS.items():
            cells = RegularTemplateProject.pattern_cells(pattern_id)
            columns = int(definition["columns"])
            rows = int(definition["rows"])

            first = cells[0]
            last = cells[-1]
            self.assertAlmostEqual(first.x * A4_WIDTH_CM, REGULAR_MARGIN_CM, places=7)
            self.assertAlmostEqual(first.y * A4_HEIGHT_CM, REGULAR_MARGIN_CM, places=7)
            self.assertAlmostEqual(
                (last.x + last.width) * A4_WIDTH_CM,
                A4_WIDTH_CM - REGULAR_MARGIN_CM,
                places=7,
            )
            self.assertAlmostEqual(
                (last.y + last.height) * A4_HEIGHT_CM,
                A4_HEIGHT_CM - REGULAR_MARGIN_CM,
                places=7,
            )
            if columns > 1:
                horizontal_gap = (cells[1].x - (cells[0].x + cells[0].width)) * A4_WIDTH_CM
                self.assertAlmostEqual(horizontal_gap, REGULAR_GAP_CM, places=7)
            if rows > 1:
                vertical_gap = (cells[columns].y - (cells[0].y + cells[0].height)) * A4_HEIGHT_CM
                self.assertAlmostEqual(vertical_gap, REGULAR_GAP_CM, places=7)

    def test_every_regular_pattern_stays_inside_a4_without_overlaps(self):
        for pattern_id, definition in REGULAR_PATTERNS.items():
            cells = RegularTemplateProject.pattern_cells(pattern_id)
            self.assertEqual(len(cells), definition["rows"] * definition["columns"])
            for cell in cells:
                self.assertGreaterEqual(cell.x, 0)
                self.assertGreaterEqual(cell.y, 0)
                self.assertLessEqual(cell.x + cell.width, 1.0)
                self.assertLessEqual(cell.y + cell.height, 1.0)
            for index, left in enumerate(cells):
                for right in cells[index + 1:]:
                    overlaps = not (
                        left.x + left.width <= right.x or right.x + right.width <= left.x
                        or left.y + left.height <= right.y or right.y + right.height <= left.y
                    )
                    self.assertFalse(overlaps, pattern_id)

    def test_conversion_to_free_preserves_physical_geometry_exactly(self):
        for pattern_id in REGULAR_PATTERNS:
            project = RegularTemplateProject(pattern_id=pattern_id)
            resource = TemplateResource("C:/muestra.png", "Muestra", 1000, 1000)
            project.resources = [resource]
            for cell in project.cells:
                cell.resource_id = resource.resource_id
            free = project.to_free_project()
            self.assertEqual(len(free.items), len(project.cells))
            for cell, item in zip(project.cells, free.items):
                self.assertEqual(item.x_cm, cell.x * A4_WIDTH_CM)
                self.assertEqual(item.y_cm, cell.y * A4_HEIGHT_CM)
                self.assertEqual(item.width_cm, cell.width * A4_WIDTH_CM)
                self.assertEqual(item.height_cm, cell.height * A4_HEIGHT_CM)

    def test_pattern_recommendation_is_a_proposal_with_confidence(self):
        resources = [TemplateResource("a.png", "A", 1000, 1800), TemplateResource("b.png", "B", 1000, 1750)]
        report = RegularTemplateProject.recommended_pattern_report(resources)
        self.assertIn(report["pattern_id"], REGULAR_PATTERNS)
        self.assertGreaterEqual(report["confidence"], 0)
        self.assertLessEqual(report["confidence"], 1)
        self.assertIn("auto_suitable", report)


class PlanchaInteractionContracts(unittest.TestCase):
    def test_area_selection_uses_the_center_of_each_real_hitbox(self):
        editor = PlanchaEditor.__new__(PlanchaEditor)
        editor.zoom = 1.0
        first = PlanchaItem("uno.png", "Uno", 5.0, 5.0, x_cm=0.2, y_cm=0.2)
        second = PlanchaItem("dos.png", "Dos", 5.0, 5.0, x_cm=6.0, y_cm=0.2)
        editor.project = PlanchaProject([first, second])
        left = 25 + editor.cm_to_px(0.1)
        top = 25 + editor.cm_to_px(0.1)
        right = 25 + editor.cm_to_px(5.4)
        bottom = 25 + editor.cm_to_px(5.4)
        self.assertEqual(editor.item_ids_in_area(left, top, right, bottom), {first.item_id})


class PrintingContracts(unittest.TestCase):
    def test_only_a4_300_dpi_is_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            valid = Path(folder) / "a4.png"
            invalid = Path(folder) / "otra.png"
            Image.new("RGBA", (2480, 3508), (0, 0, 0, 0)).save(valid, dpi=(300, 300))
            Image.new("RGBA", (1000, 1000), (0, 0, 0, 0)).save(invalid, dpi=(72, 72))
            self.assertTrue(validate_a4_png(valid)[0])
            self.assertFalse(validate_a4_png(invalid)[0])

    def test_order_is_printed_only_when_every_sheet_is_printed(self):
        with tempfile.TemporaryDirectory() as folder:
            database = ImageDatabase(Path(folder) / "audit.db")
            order_id = database.create_order("Cliente de prueba", jobs=[
                {"title": "Trabajo A", "quantity": 10},
                {"title": "Trabajo B", "quantity": 20},
            ])
            first = database.save_plancha_project(order_id, "Plancha 1", "Vinilo", "{}", "uno.json")
            second = database.save_plancha_project(order_id, "Plancha 2", "Vinilo", "{}", "dos.json")
            database.set_plancha_print_status(first, "Impresa")
            order = database.order(order_id)
            self.assertEqual(order["printed_planchas"], 1)
            self.assertNotEqual(order["print_status"], "Impresa")
            database.set_plancha_print_status(second, "Error de impresión", "Falla simulada")
            self.assertNotEqual(database.order(order_id)["print_status"], "Impresa")
            database.set_plancha_print_status(second, "Impresa")
            order = database.order(order_id)
            self.assertEqual(order["print_status"], "Impresa")
            self.assertEqual(order["printed_planchas"], 2)
            self.assertEqual(len(database.order_jobs(order_id)), 2)
            database.close()


class LibraryContracts(unittest.TestCase):
    def test_search_ignores_technical_filename_and_uses_tags(self):
        with tempfile.TemporaryDirectory() as folder:
            database = ImageDatabase(Path(folder) / "audit.db")
            path = str(Path(folder) / "IMG_918273_tecnico.png")
            database.upsert({"path": path, "name": "IMG_918273_tecnico.png", "extension": ".png", "size": 1, "modified": 1.0, "caption": ""})
            self.assertEqual(database.search("918273", limit=10), [])
            database.add_tag(path, "Selección Argentina")
            self.assertEqual(len(database.search("selección", limit=10)), 1)
            database.set_design_library_state(path, reusable=True)
            image = database.search("selección", limit=1)[0]
            self.assertEqual(image["is_reusable"], 1)
            self.assertEqual(image["is_private"], 0)
            database.close()


if __name__ == "__main__":
    unittest.main()
