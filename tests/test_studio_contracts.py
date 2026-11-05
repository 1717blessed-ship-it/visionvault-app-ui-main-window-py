import json
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
                self.assertGreaterEqual(horizontal_gap, REGULAR_GAP_CM)
            if rows > 1:
                vertical_gap = (cells[columns].y - (cells[0].y + cells[0].height)) * A4_HEIGHT_CM
                self.assertGreaterEqual(vertical_gap, REGULAR_GAP_CM)
            if definition.get("shape") == "circle":
                self.assertAlmostEqual(first.width * A4_WIDTH_CM, first.height * A4_HEIGHT_CM, places=7)

    def test_redondo_20_has_five_rows_of_four_circular_stickers(self):
        cells = RegularTemplateProject.pattern_cells("circular_4x5")
        self.assertEqual(len(cells), 20)
        self.assertTrue(all(cell.shape == "circle" for cell in cells))
        self.assertEqual(len({round(cell.y, 8) for cell in cells}), 5)
        self.assertEqual(len({round(cell.x, 8) for cell in cells}), 4)

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
    def test_continuous_confirmation_controls_visibility_and_can_be_repeated_after_removal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = ImageDatabase(root / "continuous.db")
            plancha_id = database.save_plancha_project(
                None, "Plancha continua", "Vinilo", "{}", "", workspace_format="a4",
            )
            final_png = root / "plancha.png"
            final_png.write_bytes(b"png")
            database.set_plancha_final_png(plancha_id, str(final_png))

            self.assertNotIn(plancha_id, {row["id"] for row in database.available_planchas_for_continuous()})
            database.confirm_plancha_for_continuous(plancha_id)
            self.assertIn(plancha_id, {row["id"] for row in database.available_planchas_for_continuous()})

            database.save_plancha_status_before_continuous(plancha_id)
            database.update_plancha_production_status(plancha_id, "usada_en_continua")
            database.restore_plancha_status_after_continuous(plancha_id)

            restored = database.plancha_project(plancha_id)
            self.assertEqual(restored["production_status"], "lista")
            self.assertEqual(restored["continuous_confirmed"], 0)
            self.assertNotIn(plancha_id, {row["id"] for row in database.available_planchas_for_continuous()})

            database.confirm_plancha_for_continuous(plancha_id)
            self.assertIn(plancha_id, {row["id"] for row in database.available_planchas_for_continuous()})
            database.close()

    def test_photographic_print_can_be_confirmed_for_continuous_production(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = ImageDatabase(root / "photo-continuous.db")
            plancha_id = database.save_plancha_project(
                None, "Impresión fotográfica A4", "Papel fotográfico A4", "{}", "", workspace_format="a4",
            )
            final_png = root / "foto-a4.png"
            final_png.write_bytes(b"png")
            database.set_plancha_final_png(plancha_id, str(final_png))

            database.confirm_plancha_for_continuous(plancha_id)
            available = {row["id"]: row for row in database.available_planchas_for_continuous()}
            self.assertIn(plancha_id, available)
            self.assertEqual(available[plancha_id]["material"], "Papel fotográfico A4")
            database.close()

    def test_releasing_a_hidden_pending_reservation_allows_reconfirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = ImageDatabase(root / "release.db")
            plancha_id = database.save_plancha_project(None, "Plancha", "", "{}", "")
            final_png = root / "final.png"
            final_png.write_bytes(b"png")
            database.set_plancha_final_png(plancha_id, str(final_png))
            database.confirm_plancha_for_continuous(plancha_id)
            production = {
                "name": "Pendiente", "mode": "Hoja", "width_cm": 21, "length_cm": 29.7,
                "sections": [{"plancha_id": plancha_id}],
            }
            database.save_continuous_production("Pendiente", "Hoja", 21, 29.7, "", json.dumps(production))
            database.save_plancha_status_before_continuous(plancha_id)
            database.update_plancha_production_status(plancha_id, "usada_en_continua")

            self.assertTrue(database.release_plancha_from_continuous(plancha_id))
            self.assertEqual(database.continuous_productions(), [])
            self.assertEqual(database.plancha_project(plancha_id)["production_status"], "lista")
            self.assertEqual(database.plancha_project(plancha_id)["continuous_confirmed"], 0)
            database.confirm_plancha_for_continuous(plancha_id)
            self.assertIn(plancha_id, {row["id"] for row in database.available_planchas_for_continuous()})
            database.close()

    def test_printer_configuration_is_preserved_per_printer(self):
        with tempfile.TemporaryDirectory() as folder:
            database = ImageDatabase(Path(folder) / "printers.db")
            database.save_printing_config(
                "Epson A", {"copies": 2, "devmode_b64": "epson-settings", "devmode_summary": "Papel continuo"},
            )
            database.save_printing_config("Otra impresora", {"copies": 1})
            other = database.printing_config()
            self.assertEqual(other["printer_name"], "Otra impresora")
            self.assertNotIn("devmode_b64", other)

            database.save_printing_config("Epson A", {"copies": 2})
            restored = database.printing_config()
            self.assertEqual(restored["printer_name"], "Epson A")
            self.assertEqual(restored["devmode_b64"], "epson-settings")
            self.assertEqual(restored["devmode_summary"], "Papel continuo")
            self.assertEqual(restored["copies"], 2)
            database.close()

    def test_saved_plancha_can_be_linked_to_an_existing_order(self):
        with tempfile.TemporaryDirectory() as folder:
            database = ImageDatabase(Path(folder) / "plancha.db")
            order_id = database.create_order("Cliente", material="Vinilo")
            plancha_id = database.save_plancha_project(
                None, "Plancha guardada", "", "{}", str(Path(folder) / "plancha.json"),
            )

            self.assertTrue(database.link_plancha_to_order(plancha_id, order_id))
            saved = database.plancha_project(plancha_id)
            self.assertEqual(saved["order_id"], order_id)
            self.assertEqual(saved["material"], "Vinilo")
            database.close()

    def test_regular_template_print_calibration_is_9727_percent(self):
        from app.planchas.template_editor import RegularTemplateEditor
        self.assertEqual(RegularTemplateEditor.PRINT_SCALE, 0.9727)
        self.assertGreater(RegularTemplateEditor.PRINT_OUTLINE_PX, 0)

    def test_completion_options_include_partial_production_scopes(self):
        options = dict(PlanchaEditor.completion_options())
        self.assertEqual(options["1 franja de stickers"], 1 / 5)
        self.assertEqual(options["5 franjas de stickers"], 1.0)
        self.assertEqual(options["Hoja A5 (media A4)"], 1 / 2)
        self.assertEqual(options["1/4 de plancha"], 1 / 4)

    def test_area_selection_selects_each_sticker_that_touches_the_area(self):
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

    def test_hidden_guides_keep_the_sticker_centered_in_its_band(self):
        editor = PlanchaEditor.__new__(PlanchaEditor)
        editor.project = PlanchaProject(workspace_format="a4")
        editor.show_hitboxes = False
        editor.drag_band_index = 0
        item = PlanchaItem("uno.png", "Uno", 4.0, 3.0)

        minimum, maximum = editor.drag_band_bounds(item)

        band_height = editor.project.production_band_heights()[0]
        expected = editor.project.margin_cm + (band_height - item.height_cm) / 2
        self.assertAlmostEqual(minimum, expected)
        self.assertAlmostEqual(maximum, expected)

    def test_copy_paste_selected_stickers_reoptimizes_with_new_ids(self):
        editor = PlanchaEditor.__new__(PlanchaEditor)
        original = PlanchaItem("uno.png", "Uno", 4.0, 3.0)
        editor.project = PlanchaProject([original])
        editor.selected_id = original.item_id
        editor.selected_ids = {original.item_id}
        editor.sticker_clipboard = []
        editor.status_message = lambda _message: None
        editor.snapshot = lambda: None
        optimized = []
        editor.optimize = lambda: optimized.append(True)

        self.assertEqual(editor.copy_selected_items(), "break")
        self.assertEqual(editor.paste_selected_items(), "break")

        self.assertEqual(len(editor.project.items), 2)
        pasted = editor.project.items[-1]
        self.assertNotEqual(pasted.item_id, original.item_id)
        self.assertNotEqual(pasted.group_id, original.group_id)
        self.assertEqual(editor.selected_ids, {pasted.item_id})
        self.assertEqual(optimized, [True])

    def test_copying_a_complete_band_repeats_it_in_the_next_band(self):
        editor = PlanchaEditor.__new__(PlanchaEditor)
        project = PlanchaProject()
        first = PlanchaItem("uno.png", "Uno", 4.0, 3.0, x_cm=0.15, y_cm=0.15)
        second = PlanchaItem("dos.png", "Dos", 4.0, 3.0, x_cm=5.0, y_cm=0.15)
        project.items = [first, second]
        editor.project = project
        editor.selected_id = second.item_id
        editor.selected_ids = {first.item_id, second.item_id}
        editor.sticker_clipboard = []
        editor.clipboard_band_index = None
        editor.status_message = lambda _message: None
        editor.snapshot = lambda: None
        editor.render = lambda: None
        editor.optimize = lambda: self.fail("A complete band must retain its layout")

        editor.copy_selected_items()
        editor.paste_selected_items()

        pasted = project.items[-2:]
        target_top = project.margin_cm + project.production_band_heights()[0]
        self.assertEqual([item.x_cm for item in pasted], [first.x_cm, second.x_cm])
        self.assertEqual([item.y_cm for item in pasted], [target_top, target_top])

    def test_hidden_guides_can_overlap_for_free_visual_adjustment(self):
        editor = PlanchaEditor.__new__(PlanchaEditor)
        first = PlanchaItem("uno.png", "Uno", 4.0, 3.0, x_cm=1.0, y_cm=1.0)
        second = PlanchaItem("dos.png", "Dos", 4.0, 3.0)
        editor.project = PlanchaProject([first, second], gap_cm=0.2)

        self.assertFalse(editor.can_place(second, 4.5, 1.0))

    def test_dragging_to_another_band_updates_the_active_band(self):
        editor = PlanchaEditor.__new__(PlanchaEditor)
        item = PlanchaItem("uno.png", "Uno", 4.0, 3.0, x_cm=0.15, y_cm=0.15)
        editor.project = PlanchaProject([item])
        editor.zoom = 1.0
        editor.show_hitboxes = False
        editor.selected_id = item.item_id
        editor.drag_offset = (0, 0)
        editor.drag_band_index = 0
        editor.area_selection_start = None
        editor.canvas_event_position = lambda event: (event.x, event.y)
        editor.request_render = lambda: None

        band_height = editor.project.production_band_heights()[0]
        target_y_cm = editor.project.margin_cm + band_height + 1.0
        event = type("Event", (), {"x": 25 + editor.cm_to_px(1.0), "y": 25 + editor.cm_to_px(target_y_cm)})()
        editor.drag_item(event)

        self.assertEqual(editor.band_for_item(item), 1)

    def test_distribute_evenly_spreads_designs_across_their_band(self):
        editor = PlanchaEditor.__new__(PlanchaEditor)
        first = PlanchaItem("uno.png", "Uno", 4.0, 3.0, x_cm=1.0, y_cm=0.15)
        second = PlanchaItem("dos.png", "Dos", 4.0, 3.0, x_cm=7.0, y_cm=0.15)
        editor.project = PlanchaProject([first, second])
        editor.snapshot = lambda: None
        editor.render = lambda: None
        editor.status_message = lambda _message: None

        editor.distribute_evenly()

        self.assertEqual(first.x_cm, editor.project.margin_cm)
        self.assertAlmostEqual(second.x_cm + second.width_cm, 21.0 - editor.project.margin_cm)


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

    def test_search_finds_text_recognized_by_ai_without_creating_a_tag(self):
        with tempfile.TemporaryDirectory() as folder:
            database = ImageDatabase(Path(folder) / "audit.db")
            path = str(Path(folder) / "diseno.png")
            database.upsert({"path": path, "name": "diseno.png", "extension": ".png", "size": 1, "modified": 1.0, "caption": ""})
            database.save_ai_result(path, "IA local", "local-v4", 1.0, {"text": "Feliz cumple Martina"})

            found = database.search("martina", limit=10)

            self.assertEqual([item["path"] for item in found], [path])
            self.assertEqual(found[0]["recognized_text"], "Feliz cumple Martina")
            self.assertEqual(found[0]["tags"], None)
            database.close()


if __name__ == "__main__":
    unittest.main()
