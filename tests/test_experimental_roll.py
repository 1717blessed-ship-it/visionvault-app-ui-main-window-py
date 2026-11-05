import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.planchas.experimental_roll import (
    DEFAULT_BLOCK_LENGTH_MM,
    ExperimentalRollBlock,
    make_roll_blocks,
    mm_to_pixels,
    render_roll_block,
    validate_roll_block_png,
)
from app.printing.experimental_epson_continuity import (
    EpsonContinuityRun,
    generate_continuity_patterns,
    latest_measurements,
    save_continuity_measurement,
)


class ExperimentalRollTests(unittest.TestCase):
    def test_default_block_is_210_by_1188_mm_at_300_dpi(self):
        block = ExperimentalRollBlock(("one.png",))
        self.assertEqual(block.pixel_size, (mm_to_pixels(210), mm_to_pixels(DEFAULT_BLOCK_LENGTH_MM)))

    def test_sections_share_boundaries_without_separator_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = []
            for index, color in enumerate(((255, 0, 0, 255), (0, 255, 0, 255))):
                path = root / f"{index}.png"
                Image.new("RGBA", (10, 10), color).save(path)
                paths.append(path)
            output = render_roll_block(ExperimentalRollBlock(tuple(map(str, paths))), root / "block.png")
            with Image.open(output) as image:
                first_end = round(mm_to_pixels(2 * 297) / 2)
                self.assertEqual(image.getpixel((0, first_end - 1))[:3], (255, 0, 0))
                self.assertEqual(image.getpixel((0, first_end))[:3], (0, 255, 0))
            self.assertTrue(validate_roll_block_png(output)[0])

    def test_sequence_is_partitioned_in_order_into_four_a4_blocks(self):
        blocks = make_roll_blocks([f"{number}.png" for number in range(9)])
        self.assertEqual([len(block.paths) for block in blocks], [4, 4, 1])
        self.assertEqual(blocks[1].paths[0], "4.png")

    def test_continuity_patterns_and_measurements_are_kept_outside_production_history(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.printing.experimental_epson_continuity.experimental_output_folder", return_value=Path(temp_dir)
        ):
            first, second = generate_continuity_patterns()
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())
            run = EpsonContinuityRun("A", True, "ok", (10, 11))
            location = save_continuity_measurement(run, "Epson L3210", True, {"separation_mm": "2.5"})
            self.assertTrue(location.exists())
            self.assertEqual(latest_measurements()["A"]["job_ids"], [10, 11])
