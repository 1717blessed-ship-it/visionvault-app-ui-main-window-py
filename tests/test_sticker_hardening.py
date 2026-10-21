import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from app.stickers.objects import match_object_ids
from app.stickers.pipeline import StickerProcessor, ProcessingCancelled
from app.stickers.quality import validate_sticker


class StickerHardeningTests(unittest.TestCase):
    def test_known_inputs_keep_classification_and_valid_artifacts(self):
        fixtures = Path(__file__).parent / "fixtures" / "sticker_regression"
        for filename, category in [("lips_white.png", "fondo_blanco"),
                                   ("disco_checker.png", "damero_incrustado"),
                                   ("heart_checker.png", "damero_incrustado")]:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as folder:
                result = StickerProcessor(Path(folder)).process(fixtures / filename)
                self.assertEqual(result.analysis["sticker_type"], category)
                self.assertFalse(result.analysis["quality_report"]["errors"])
                with Image.open(result.artifacts["master"]) as master:
                    self.assertEqual(master.getchannel("A").getextrema(), (0, 255))

    def report(self, **overrides):
        mask = Image.new("L", (100, 100), 0)
        ImageDraw.Draw(mask).rectangle((15, 15, 84, 84), fill=255)
        master = Image.new("RGBA", mask.size, "red")
        master.putalpha(mask)
        params = dict(design_alpha=mask, master=master, cut_mask=mask,
                      expected_pixels=100, dpi=100, target_cm=2.54,
                      source_size=(1000, 1000))
        params.update(overrides)
        return validate_sticker(**params)

    def test_empty_masks_and_degenerate_cut_are_errors(self):
        empty = Image.new("L", (100, 100), 0)
        report = self.report(design_alpha=empty, cut_mask=empty)
        self.assertEqual(report.status, "ERROR")
        self.assertEqual({item["code"] for item in report.errors}, {"empty_design", "degenerate_cut"})

    def test_partial_alpha_and_intentional_holes_are_valid(self):
        mask = Image.new("L", (100, 100), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((10, 10, 90, 90), fill=120)
        draw.ellipse((35, 35, 65, 65), fill=0)
        report = self.report(design_alpha=mask)
        self.assertEqual(report.status, "APROBADO")
        self.assertGreater(report.metrics["partial_alpha_px"], 0)

    def test_resolution_warning_is_not_an_error(self):
        report = self.report(source_size=(30, 30))
        self.assertEqual(report.status, "REVISAR")
        self.assertFalse(report.errors)

    def test_wrong_physical_dimensions_are_errors(self):
        self.assertEqual(self.report(target_cm=5).status, "ERROR")

    def test_redo_restores_an_overlapping_stroke_as_one_action(self):
        from app.stickers.editor import MaskEditor
        from tests.test_sticker_creator import _Value
        editor = MaskEditor.__new__(MaskEditor)
        editor.original = Image.new("RGBA", (80, 80), "red")
        editor.mask = Image.new("L", (80, 80), 255)
        editor.brush, editor.mode = _Value(24), _Value("erase")
        editor.display_scale = 1.
        editor.image_modified = False
        editor._undo_stack, editor._redo_stack = [], []
        editor._active_stroke = {"patches": [], "image_modified_before": False}
        editor._render_after = None
        editor.after = lambda *_: "pending"
        editor.after_cancel = lambda *_: None
        editor.render = lambda: None
        editor.paint_at(30, 30)
        editor.paint_at(42, 30)
        editor.end_stroke()
        expected = editor.mask.tobytes()
        editor.undo()
        editor.redo()
        self.assertEqual(editor.mask.tobytes(), expected)

    def test_ids_survive_reordering_and_ambiguous_objects_get_new_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            masks = []
            previous = []
            for identifier, box in [(4, (5, 5, 35, 35)), (9, (60, 60, 90, 90))]:
                mask = Image.new("L", (100, 100), 0)
                ImageDraw.Draw(mask).rectangle(box, fill=255)
                path = Path(folder) / f"{identifier}.png"
                mask.save(path)
                previous.append({"id": identifier, "artifact": str(path)})
                masks.append(mask)
            ids, ambiguous = match_object_ids(list(reversed(masks)), previous)
            self.assertEqual(ids, [9, 4])
            self.assertFalse(ambiguous)
            ids, ambiguous = match_object_ids([Image.new("L", (100, 100), 255)], previous)
            self.assertTrue(ambiguous)
            self.assertGreater(ids[0], 9)

    def test_cancellation_removes_only_current_run(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "original.png"
            image = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
            ImageDraw.Draw(image).ellipse((20, 20, 180, 180), fill="red")
            image.save(source)
            workspace = Path(folder) / "work"
            processor = StickerProcessor(workspace)
            def progress(percent, _message):
                if percent >= 48:
                    raise ProcessingCancelled()
            with self.assertRaises(ProcessingCancelled):
                processor.process(source, progress=progress)
            self.assertTrue(source.exists())
            self.assertEqual(list(workspace.iterdir()), [])

    def test_manual_holes_and_independent_cut_survive_reprocessing(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.png"
            Image.new("RGB", (200, 200), "red").save(source)
            mask = Image.new("L", (200, 200), 0)
            draw = ImageDraw.Draw(mask)
            draw.ellipse((20, 20, 180, 180), fill=255)
            draw.ellipse((75, 75, 125, 125), fill=0)
            mask_path = Path(folder) / "manual.png"
            mask.save(mask_path)
            processor = StickerProcessor(Path(folder) / "work")
            first = processor.process(source, mask_override=mask_path)
            cut = Image.new("L", (processor.profile.master_pixels,) * 2, 0)
            ImageDraw.Draw(cut).ellipse((100, 100, 500, 500), fill=255)
            cut_path = Path(folder) / "cut.png"
            cut.save(cut_path)
            second = processor.process(source, mask_override=mask_path, cut_mask_override=cut_path)
            with Image.open(second.artifacts["mask_editable"]) as saved:
                self.assertEqual(saved.tobytes(), mask.tobytes())
            with Image.open(first.artifacts["mask_editable"]) as one, Image.open(second.artifacts["mask_editable"]) as two:
                self.assertEqual(one.tobytes(), two.tobytes())
            with Image.open(second.artifacts["cut"]) as saved:
                self.assertEqual(saved.tobytes(), cut.tobytes())

    def test_plancha_keeps_order_dimensions_and_existing_outline(self):
        from app.planchas.model import PlanchaProject
        from app.planchas.production_geometry import production_min_for_nominal
        from app.planchas.editor import prepare_sticker_for_target
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "asset.png"
            Image.new("RGBA", (1200, 600), "red").save(source)
            project = PlanchaProject.from_images([{
                "path": str(source), "quantity": 1, "size_cm": 8.,
                "order_size_cm": 8., "order_id": 77,
            }])
            item = project.items[0]
            self.assertAlmostEqual(max(item.production_width_cm, item.production_height_cm), production_min_for_nominal(8.))
            self.assertAlmostEqual(item.production_width_cm / item.production_height_cm, 2.)
            image = Image.new("RGBA", (100, 100))
            draw = ImageDraw.Draw(image)
            draw.ellipse((8, 8, 91, 91), fill="white")
            draw.ellipse((17, 17, 82, 82), fill=(220, 30, 30, 255))
            prepared = prepare_sticker_for_target(image, (300, 300), outlined=True)
            self.assertEqual(prepared.getpixel((150, 150))[:3], (220, 30, 30))

    def test_editable_coordinates_and_reproduction_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.png"
            image = Image.new("RGB", (300, 200), "white")
            ImageDraw.Draw(image).ellipse((70, 20, 230, 180), fill="red")
            image.save(source)
            result = StickerProcessor(Path(folder) / "work").process(source)
            with Image.open(result.artifacts["mask_editable"]) as mask, Image.open(result.artifacts["source_editable"]) as aligned:
                self.assertEqual(mask.size, aligned.size)
                self.assertEqual(mask.size, image.size)
            metadata = json.loads(Path(result.artifacts["metadata"]).read_text(encoding="utf-8"))
            self.assertIn("reprocess_parameters", metadata)
            self.assertIn("quality_report", metadata["analysis"])


if __name__ == "__main__":
    unittest.main()
