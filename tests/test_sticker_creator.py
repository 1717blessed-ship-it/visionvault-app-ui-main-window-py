import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from app.stickers.editor import MaskEditor
from app.stickers.pipeline import ProcessingProfile, StickerProcessor


class _Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class StickerCreatorContracts(unittest.TestCase):
    def test_mask_editor_restore_opened_mask_discards_only_mask_changes(self):
        editor = MaskEditor.__new__(MaskEditor)
        editor.mask = Image.new("L", (20, 20), 255)
        editor._opened_mask = editor.mask.copy()
        ImageDraw.Draw(editor.mask).ellipse((4, 4, 15, 15), fill=0)
        editor._undo_stack = [{"patches": []}]
        editor._active_stroke = None
        editor._lasso_points = [(1, 1), (4, 4)]
        editor._render_after = None
        editor.end_stroke = lambda: None
        editor.render = lambda: None

        self.assertEqual(editor.restore_opened_mask(confirm=False), "break")
        self.assertEqual(editor.mask.getextrema(), (255, 255))
        self.assertEqual(editor._undo_stack, [])
        self.assertEqual(editor._lasso_points, [])

    def test_mask_editor_ctrl_z_restores_the_whole_last_stroke(self):
        editor = MaskEditor.__new__(MaskEditor)
        editor.original = Image.new("RGBA", (80, 80), (220, 40, 60, 255))
        editor.mask = Image.new("L", (80, 80), 255)
        editor.brush = _Value(24)
        editor.mode = _Value("erase")
        editor.display_scale = 1.0
        editor.image_modified = False
        editor._undo_stack = []
        editor._active_stroke = {"patches": [], "image_modified_before": False}
        editor._render_after = None
        editor.after = lambda *_args: "render-pending"
        editor.after_cancel = lambda *_args: None
        editor.render = lambda: None

        editor.paint_at(30, 30)
        editor.paint_at(42, 30)
        editor.end_stroke()
        self.assertEqual(editor.mask.getpixel((30, 30)), 0)
        self.assertEqual(editor.mask.getpixel((42, 30)), 0)

        editor.undo()
        self.assertEqual(editor.mask.getpixel((30, 30)), 255)
        self.assertEqual(editor.mask.getpixel((42, 30)), 255)
        self.assertEqual(editor._undo_stack, [])

    def test_transparent_png_holes_survive_separately_from_white_substrate(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "anillo.png"
            image = Image.new("RGBA", (420, 420), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.ellipse((35, 35, 385, 385), fill=(20, 95, 210, 255))
            draw.ellipse((135, 135, 285, 285), fill=(0, 0, 0, 0))
            image.save(source)

            result = StickerProcessor(Path(folder) / "work").process(source)
            # New explicit requirement: negative space belongs to visual alpha;
            # the physical white substrate may remain solid independently.
            self.assertFalse(result.analysis["png_holes_filled_white"])
            with Image.open(result.artifacts["mask"]) as mask:
                alpha = mask.convert("L")
                self.assertEqual(alpha.getpixel((210, 210)), 0)
                self.assertEqual(alpha.getpixel((5, 5)), 0)
            with Image.open(result.artifacts["clean"]) as clean:
                center = clean.convert("RGBA").getpixel((clean.width // 2, clean.height // 2))
                self.assertEqual(center[3], 0)
            with Image.open(result.artifacts["native_printable_base"]) as base:
                self.assertEqual(base.getpixel((base.width // 2, base.height // 2)), 255)

    def test_transparent_holes_are_not_filled_for_non_png_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "anillo.webp"
            image = Image.new("RGBA", (420, 420), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.ellipse((35, 35, 385, 385), fill=(20, 95, 210, 255))
            draw.ellipse((135, 135, 285, 285), fill=(0, 0, 0, 0))
            image.save(source)

            result = StickerProcessor(Path(folder) / "work").process(source)
            self.assertFalse(result.analysis["png_holes_filled_white"])
            with Image.open(result.artifacts["mask"]) as mask:
                self.assertEqual(mask.convert("L").getpixel((210, 210)), 0)

    def test_photo_selection_can_be_kept_complete_without_background_removal(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "foto.png"
            image = Image.new("RGB", (520, 360), (15, 40, 80))
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 180, 520, 360), fill=(35, 135, 55))
            draw.ellipse((180, 55, 340, 300), fill=(225, 170, 105))
            image.save(source)

            result = StickerProcessor(Path(folder) / "work").process(source, preserve_full_image=True)
            with Image.open(result.artifacts["mask"]) as mask:
                self.assertEqual(mask.convert("L").getextrema(), (255, 255))
            self.assertEqual(result.analysis["selection_processing_mode"], "Selección completa")
            self.assertEqual(result.analysis["shape_type"], "Rectangular")

    def test_closed_contour_protects_everything_inside_but_not_open_regions(self):
        closed = Image.new("L", (120, 120), 0)
        ImageDraw.Draw(closed).rectangle((18, 18, 102, 102), outline=255, width=5)
        protected = StickerProcessor._preserve_closed_interiors(closed)
        self.assertEqual(protected.getpixel((60, 60)), 255)
        self.assertEqual(protected.getpixel((4, 4)), 0)

        opened = Image.new("L", (120, 120), 0)
        draw = ImageDraw.Draw(opened)
        draw.line((18, 18, 48, 18), fill=255, width=5)
        draw.line((72, 18, 102, 18), fill=255, width=5)
        draw.line((18, 18, 18, 102), fill=255, width=5)
        draw.line((102, 18, 102, 102), fill=255, width=5)
        draw.line((18, 102, 102, 102), fill=255, width=5)
        not_protected = StickerProcessor._preserve_closed_interiors(opened)
        self.assertEqual(not_protected.getpixel((60, 60)), 0)

    def test_automatic_background_removal_keeps_original_white_inside_closed_border(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "cerrado.png"
            image = Image.new("RGB", (420, 420), "white")
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((55, 55, 365, 365), radius=55, outline="black", width=14)
            draw.ellipse((180, 180, 240, 240), fill=(220, 20, 45))
            image.save(source)

            result = StickerProcessor(Path(folder) / "work").process(source)
            with Image.open(result.artifacts["mask"]) as mask:
                alpha = mask.convert("L")
                self.assertEqual(alpha.getpixel((210, 105)), 255)
                self.assertEqual(alpha.getpixel((5, 5)), 0)
            with Image.open(result.artifacts["clean"]) as clean:
                rgba = clean.convert("RGBA")
                sample = rgba.getpixel((rgba.width // 2, rgba.height // 5))
                self.assertGreater(sample[3], 240)
                self.assertGreater(min(sample[:3]), 240)
            self.assertEqual(result.analysis["background_removal_scope"], "Solo exterior conectado")

    def test_light_gray_background_removal_crosses_shadow_but_stops_at_white_sticker(self):
        # Secuencia requerida: fondo 239 -> sombras 233/217 -> borde blanco 255.
        # El gris que queda tras el blanco es parte del diseño y no debe tocarse.
        image = Image.new("RGB", (9, 5), (239, 239, 239))
        draw = ImageDraw.Draw(image)
        for x, value in ((2, 233), (3, 217), (4, 255), (5, 145), (6, 145)):
            draw.line((x, 0, x, 4), fill=(value, value, value))

        alpha = StickerProcessor._light_neutral_exterior_alpha(image)
        self.assertEqual(alpha.getpixel((0, 2)), 0)
        self.assertEqual(alpha.getpixel((2, 2)), 0)
        self.assertEqual(alpha.getpixel((3, 2)), 0)
        self.assertEqual(alpha.getpixel((4, 2)), 255)
        self.assertEqual(alpha.getpixel((5, 2)), 255)

    def test_inner_white_stroke_covers_only_the_inside_edge(self):
        base = Image.new("L", (20, 20), 0)
        ImageDraw.Draw(base).rectangle((3, 3, 16, 16), fill=255)
        alpha = StickerProcessor._build_inner_white_stroke(base, 2).getchannel("A")
        self.assertEqual(alpha.getpixel((2, 10)), 0)
        self.assertEqual(alpha.getpixel((3, 10)), 255)
        self.assertEqual(alpha.getpixel((5, 10)), 0)

    def test_neutral_halo_is_whitened_only_in_the_outer_margin(self):
        image = Image.new("RGBA", (80, 80), (255, 255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.line((10, 5, 10, 74), fill=(190, 190, 190, 255), width=2)
        draw.line((40, 20, 40, 60), fill=(190, 190, 190, 255), width=2)
        alpha = Image.new("L", (80, 80), 0)
        ImageDraw.Draw(alpha).rectangle((5, 5, 74, 74), fill=255)
        clean = StickerProcessor._whiten_neutral_outer_halo(image, alpha, width=14)
        self.assertEqual(clean.getpixel((10, 40))[:3], (255, 255, 255))
        self.assertEqual(clean.getpixel((40, 40))[:3], (190, 190, 190))

    def test_dark_background_flood_fill_preserves_existing_white_border(self):
        image = Image.new("RGB", (100, 100), (18, 20, 22))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((18, 18, 81, 81), radius=14, fill="white")
        draw.ellipse((30, 30, 70, 70), fill=(180, 30, 45))
        alpha = StickerProcessor._uniform_background_alpha(image, tolerance=42)
        self.assertEqual(alpha.getpixel((2, 2)), 0)
        self.assertEqual(alpha.getpixel((50, 20)), 255)
        self.assertEqual(alpha.getpixel((50, 50)), 255)
        self.assertTrue(StickerProcessor._has_white_outer_border(image, alpha))

    def test_isolated_small_component_is_removed_but_nearby_detail_is_preserved(self):
        alpha = Image.new("L", (300, 300), 0)
        draw = ImageDraw.Draw(alpha)
        draw.rectangle((45, 45, 220, 230), fill=255)
        draw.ellipse((228, 120, 238, 130), fill=255)  # detalle cercano
        draw.ellipse((268, 250, 286, 268), fill=255)  # fragmento aislado

        cleaned, removed = StickerProcessor._remove_isolated_components(alpha)

        self.assertEqual(cleaned.getpixel((277, 259)), 0)
        self.assertEqual(cleaned.getpixel((233, 125)), 255)
        self.assertEqual(len(removed), 1)

    def test_detached_caption_above_the_design_is_preserved(self):
        alpha = Image.new("L", (300, 300), 0)
        draw = ImageDraw.Draw(alpha)
        draw.rectangle((45, 105, 220, 260), fill=255)  # main design
        draw.rectangle((110, 42, 145, 78), fill=255)   # caption character

        cleaned, removed = StickerProcessor._remove_isolated_components(alpha)

        self.assertEqual(cleaned.getpixel((128, 60)), 255)
        self.assertEqual(removed, [])

    def test_tiny_background_speck_is_removed_even_near_the_design(self):
        alpha = Image.new("L", (300, 300), 0)
        draw = ImageDraw.Draw(alpha)
        draw.rectangle((45, 45, 220, 230), fill=255)
        draw.rectangle((225, 125, 227, 127), fill=255)  # 9 px of residue

        cleaned, removed = StickerProcessor._remove_isolated_components(alpha)

        self.assertEqual(cleaned.getpixel((226, 126)), 0)
        self.assertEqual(len(removed), 1)

    def test_final_sticker_is_exact_570_cm_and_covers_gray_halo(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "halo.png"
            image = Image.new("RGBA", (720, 520), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((98, 58, 622, 462), radius=105, fill=(145, 145, 145, 255))
            draw.rounded_rectangle((104, 64, 616, 456), radius=99, fill=(220, 25, 45, 255))
            image.save(source)

            profile = ProcessingProfile()
            result = StickerProcessor(Path(folder) / "work", profile).process(source)
            final_path = Path(result.artifacts["master"])
            with Image.open(final_path) as final:
                rgba = final.convert("RGBA")
                self.assertEqual(rgba.size, (profile.master_pixels, profile.master_pixels))
                dpi = final.info.get("dpi", (0, 0))
                self.assertAlmostEqual(dpi[0], 300, delta=.1)
                visible = rgba.getchannel("A").getbbox()
                self.assertIsNotNone(visible)
                # El halo gris del original queda cubierto por la banda blanca interna.
                gray_pixels = sum(
                    1 for red, green, blue, alpha in rgba.get_flattened_data()
                    if alpha > 240 and 90 <= red <= 190 and abs(red - green) < 3 and abs(green - blue) < 3
                )
                self.assertEqual(gray_pixels, 0)

    def test_thumbnail_and_approved_master_are_the_same_visual_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "forma.png"
            image = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
            ImageDraw.Draw(image).ellipse((40, 40, 360, 360), fill=(20, 90, 210, 255))
            image.save(source)
            result = StickerProcessor(Path(folder) / "work").process(source)
            with Image.open(result.artifacts["master"]) as master, Image.open(result.artifacts["thumbnail"]) as thumbnail:
                master_copy = master.convert("RGBA")
                master_copy.thumbnail(thumbnail.size, Image.Resampling.LANCZOS)
                self.assertEqual(master_copy.tobytes(), thumbnail.convert("RGBA").tobytes())

    def test_rectangular_design_keeps_its_original_edge_without_inner_white_band(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "placa.png"
            image = Image.new("RGBA", (640, 460), (0, 0, 0, 0))
            ImageDraw.Draw(image).rectangle((20, 20, 620, 440), fill=(210, 20, 35, 255))
            image.save(source)
            result = StickerProcessor(Path(folder) / "work").process(source)
            self.assertEqual(result.analysis["shape_type"], "Rectangular")
            with Image.open(result.artifacts["master"]) as master:
                rgba = master.convert("RGBA")
                visible_box = rgba.getchannel("A").getbbox()
                red_box = rgba.getchannel("R").point(
                    lambda value: 255 if 180 <= value < 245 else 0
                ).getbbox()
                self.assertIsNotNone(visible_box)
                self.assertIsNotNone(red_box)
                self.assertAlmostEqual(
                    red_box[0] - visible_box[0],
                    ProcessingProfile().final_white_px,
                    delta=1,
                )

    def test_longest_side_is_always_oriented_vertically_without_deformation(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "horizontal.png"
            image = Image.new("RGBA", (820, 360), (0, 0, 0, 0))
            ImageDraw.Draw(image).rounded_rectangle(
                (10, 10, 810, 350), radius=70, fill=(30, 120, 220, 255)
            )
            image.save(source)
            result = StickerProcessor(Path(folder) / "work").process(source)
            self.assertTrue(result.analysis["rotated_to_vertical"])
            self.assertEqual(result.analysis["orientation"], "Vertical")
            with Image.open(result.artifacts["silhouette"]) as silhouette:
                self.assertGreater(silhouette.height, silhouette.width)
                self.assertAlmostEqual(
                    silhouette.height / silhouette.width,
                    800 / 340,
                    delta=.02,
                )

    def test_rectangular_selection_keeps_its_horizontal_orientation(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "banner.png"
            image = Image.new("RGBA", (820, 360), (30, 120, 220, 255))
            image.save(source)

            result = StickerProcessor(Path(folder) / "work").process(
                source, preserve_full_image=True, preserve_orientation=True)

            self.assertFalse(result.analysis["rotated_to_vertical"])
            self.assertEqual(result.analysis["orientation"], "Horizontal")
            with Image.open(result.artifacts["silhouette"]) as silhouette:
                self.assertGreater(silhouette.width, silhouette.height)

    def test_visual_classification_keeps_principal_type_and_observable_traits(self):
        processor = StickerProcessor.__new__(StickerProcessor)
        image = Image.new("RGBA", (240, 240), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((45, 55, 195, 185), fill=(40, 120, 220, 255))
        # Transición alfa real: debe describirse como rasgo y no como una
        # supuesta probabilidad de clasificación.
        draw.rectangle((100, 55, 140, 185), fill=(255, 80, 160, 120))

        result = processor.classify(image)

        self.assertEqual(result.detected_types[0], result.sticker_type)
        self.assertTrue(result.classification_features["real_transparency"])
        self.assertTrue(result.classification_features["semi_transparency"])
        self.assertIn("semitransparencias", result.detected_types)
        self.assertNotIn("confidence", result.classification_features)

    def test_full_image_creation_mode_applies_a_circular_alpha_without_cropping_content(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "postal.png"
            image = Image.new("RGB", (520, 340), (35, 100, 190))
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 180, 520, 340), fill=(30, 155, 75))
            draw.ellipse((205, 60, 315, 170), fill=(255, 205, 60))
            image.save(source)

            result = StickerProcessor(Path(folder) / "work").process(
                source,
                creation_mode="Sticker de imagen completa",
                full_image_shape="Circular",
            )

            self.assertEqual(result.analysis["creation_mode"], "Sticker de imagen completa")
            self.assertEqual(result.analysis["full_image_shape"], "Circular")
            self.assertEqual(result.analysis["sticker_type"], "imagen_completa")
            with Image.open(result.artifacts["mask"]) as mask:
                alpha = mask.convert("L")
                self.assertEqual(alpha.getpixel((0, 0)), 0)
                self.assertGreater(alpha.getpixel((alpha.width // 2, alpha.height // 2)), 240)

    def test_multi_object_mode_exports_masks_and_can_keep_selected_objects(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "dos_objetos.png"
            image = Image.new("RGBA", (420, 300), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((35, 80, 175, 230), radius=24, fill=(30, 115, 220, 255))
            draw.ellipse((265, 90, 385, 210), fill=(230, 55, 90, 255))
            image.save(source)

            result = StickerProcessor(Path(folder) / "work").process(
                source,
                creation_mode="Sticker de múltiples objetos",
                selected_component_ids=[2],
            )

            components = result.analysis["object_components"]
            self.assertEqual(len(components), 2)
            self.assertEqual([item["id"] for item in components if item["selected"]], [2])
            for item in components:
                self.assertTrue(Path(item["artifact"]).exists())
            self.assertIn("object_mask_1", result.artifacts)
            self.assertIn("object_mask_2", result.artifacts)


if __name__ == "__main__":
    unittest.main()
