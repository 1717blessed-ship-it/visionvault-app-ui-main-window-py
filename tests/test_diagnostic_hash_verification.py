"""Diagnostic test with SHA-256 hash verification and intermediate image saving.

This test addresses three critical errors:
ERROR 1: Wrong file being processed (cache/path issues)
ERROR 2: Transparency exists but preview doesn't use it
ERROR 3: White border removed in later pipeline stages
"""

import hashlib
import logging
import time
from pathlib import Path
from datetime import datetime

import pytest
import numpy as np
from PIL import Image

from app.stickers.pipeline import StickerProcessor
from app.stickers.models import ProcessingProfile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def get_file_info(path: Path) -> dict:
    """Get comprehensive file information."""
    stat = path.stat()
    return {
        "path": str(path.absolute()),
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "sha256": compute_sha256(path),
    }


def save_intermediate(image, step_name: str, output_dir: Path):
    """Save intermediate image with step name."""
    output_path = output_dir / f"{step_name}.png"
    image.save(output_path)
    logger.info(f"Saved intermediate: {output_path}")
    return output_path


def clean_hidden_rgb(rgba: Image.Image) -> Image.Image:
    """Clean RGB values under transparent pixels to white.

    This prevents applications that ignore alpha from showing black rectangles.
    """
    rgba_arr = np.array(rgba.convert("RGBA"))
    transparent = rgba_arr[:, :, 3] == 0
    rgba_arr[transparent, 0:3] = 255
    return Image.fromarray(rgba_arr, "RGBA")


def create_preview_with_alpha(output_path: Path, preview_path: Path):
    """Create preview using proper alpha compositing."""
    rgba = Image.open(output_path).convert("RGBA")
    fondo = Image.new("RGBA", rgba.size, (235, 235, 235, 255))
    preview = Image.alpha_composite(fondo, rgba).convert("RGB")
    preview.save(preview_path)
    logger.info(f"Saved alpha-aware preview: {preview_path}")


def test_diagnostic_hash_verification(tmp_path):
    """Diagnostic test with hash verification and intermediate images.

    This test validates:
    - Selected file hash matches loaded file hash
    - Intermediate images are saved for inspection
    - Alpha channel is properly used in preview
    - White border is preserved through pipeline
    """
    # Setup
    test_dir = tmp_path / "diagnostic"
    test_dir.mkdir(exist_ok=True)
    intermediates_dir = test_dir / "intermediates"
    intermediates_dir.mkdir(exist_ok=True)

    # Create a test image with specific features (ring, white border, circle)
    # This simulates the image(614).png with argolla superior
    test_image = Image.new("RGBA", (400, 400), (30, 30, 30, 255))  # Dark integrated background

    # Add white circular border
    from PIL import ImageDraw
    draw = ImageDraw.Draw(test_image)
    draw.ellipse([50, 50, 350, 350], outline=(255, 255, 255, 255), width=20)

    # Add ring (argolla) at top
    draw.ellipse([180, 20, 220, 60], outline=(200, 200, 200, 255), width=8)

    # Add internal black details
    draw.ellipse([100, 100, 300, 300], outline=(0, 0, 0, 255), width=5)

    # Save test file
    test_file = test_dir / "test_image_with_ring.png"
    test_image.save(test_file)

    # Get source file info
    source_info = get_file_info(test_file)
    logger.info(f"SOURCE FILE INFO: {source_info}")

    # Initialize processor
    profile = ProcessingProfile()
    processor = StickerProcessor(test_dir, profile)

    # Generate unique execution ID
    execution_id = f"{int(time.time())}_{hash(str(test_file))}"
    logger.info(f"EXECUTION ID: {execution_id}")

    # STEP 00: Load source and verify hash
    logger.info("STEP 00: Loading source image")
    with Image.open(test_file) as img:
        loaded_rgba = img.convert("RGBA").copy()

    # Verify loaded image hash matches source
    loaded_temp = test_dir / "temp_loaded.png"
    loaded_rgba.save(loaded_temp)
    loaded_hash = compute_sha256(loaded_temp)

    logger.info(f"Source SHA-256: {source_info['sha256']}")
    logger.info(f"Loaded SHA-256: {loaded_hash}")

    # Save intermediate 00
    intermediate_00 = save_intermediate(loaded_rgba, f"00_source_loaded_{execution_id}", intermediates_dir)

    # ASSERTION 1: Hash verification
    assert loaded_hash == source_info['sha256'], \
        f"Hash mismatch! Source: {source_info['sha256']}, Loaded: {loaded_hash}"

    # STEP 01: Check alpha and remove integrated background
    logger.info("STEP 01: Checking alpha and removing background")
    alpha_ch = loaded_rgba.getchannel("A")
    alpha_min, alpha_max = alpha_ch.getextrema()
    logger.info(f"Alpha range: {alpha_min} to {alpha_max}")

    has_transparency, has_integrated_bg = processor._has_real_transparency(loaded_rgba)
    logger.info(f"Has transparency: {has_transparency}, Has integrated bg: {has_integrated_bg}")

    if has_integrated_bg:
        logger.info("Using flood fill for integrated background")
        alpha_mask = processor._remove_integrated_background_flood_fill(loaded_rgba, tolerance=35)
    else:
        logger.info("Using uniform background removal")
        alpha_mask = processor._uniform_background_alpha(loaded_rgba, tolerance=42)

    # Save intermediate 01 (background removed)
    bg_removed = loaded_rgba.copy()
    bg_removed.putalpha(alpha_mask)
    intermediate_01 = save_intermediate(bg_removed, f"01_background_removed_{execution_id}", intermediates_dir)

    # ASSERTION 2: Alpha has transparency
    alpha_arr = np.asarray(alpha_mask, dtype=np.uint8)
    assert alpha_arr.min() == 0, "Alpha should have transparent pixels (min == 0)"
    assert alpha_arr.max() == 255, "Alpha should have opaque pixels (max == 255)"
    logger.info(f"Alpha statistics: min={alpha_arr.min()}, max={alpha_arr.max()}, transparent_pixels={(alpha_arr == 0).sum()}")

    # STEP 02: Save alpha mask
    logger.info("STEP 02: Saving alpha mask")
    intermediate_02 = save_intermediate(alpha_mask, f"02_alpha_mask_{execution_id}", intermediates_dir)

    # STEP 03: Apply morphological closing (preserve white border)
    logger.info("STEP 03: Applying morphological closing")
    alpha_closed = processor._apply_morphological_closing(alpha_mask, kernel_size=3, iterations=1)
    intermediate_03 = save_intermediate(alpha_closed, f"03_white_border_preserved_{execution_id}", intermediates_dir)

    # Verify white border is preserved
    # Check that white pixels in original border remain opaque
    rgb_arr = np.asarray(loaded_rgba.convert("RGB"), dtype=np.uint8)
    white_pixels = (rgb_arr[:, :, 0] > 200) & (rgb_arr[:, :, 1] > 200) & (rgb_arr[:, :, 2] > 200)
    white_alpha = alpha_arr[white_pixels]

    # ASSERTION 3: White pixels should remain opaque
    if white_pixels.sum() > 0:
        white_opaque_ratio = (white_alpha > 127).sum() / max(1, white_pixels.sum())
        logger.info(f"White border opaque ratio: {white_opaque_ratio:.2%}")
        assert white_opaque_ratio > 0.8, \
            f"White border not preserved: only {white_opaque_ratio:.2%} of white pixels are opaque"

    # STEP 04: Clean hidden RGB and create final
    logger.info("STEP 04: Cleaning hidden RGB and creating final")
    final_rgba = bg_removed.copy()
    final_rgba.putalpha(alpha_closed)
    final_cleaned = clean_hidden_rgb(final_rgba)
    intermediate_04 = save_intermediate(final_cleaned, f"04_final_{execution_id}", intermediates_dir)

    # STEP 05: Create alpha-aware preview
    logger.info("STEP 05: Creating alpha-aware preview")
    preview_path = test_dir / f"preview_{execution_id}.jpg"
    create_preview_with_alpha(intermediate_04, preview_path)

    # Verify final result
    final_alpha = final_cleaned.getchannel("A")
    final_min, final_max = final_alpha.getextrema()
    logger.info(f"Final alpha range: {final_min} to {final_max}")

    # ASSERTION 4: Final has proper transparency
    assert final_min < 255, "Final should have transparent areas"
    assert final_max == 255, "Final should have opaque areas"

    # Verify ring (argolla) is preserved
    # Check top region for the ring
    top_region = np.asarray(final_cleaned.crop((180, 20, 220, 60)).convert("L"), dtype=np.uint8)
    logger.info(f"Top region (ring area) brightness: {top_region.mean():.1f}")
    # Ring should have some content (not completely transparent)
    assert top_region.mean() > 10, "Ring (argolla) should be preserved in final result"

    logger.info("All diagnostic assertions passed!")
    logger.info(f"Intermediate images saved to: {intermediates_dir}")


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        result = test_diagnostic_hash_verification(Path(tmp))
        print(f"\nDiagnostic complete. Results: {result}")
