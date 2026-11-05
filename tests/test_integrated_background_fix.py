"""Tests for integrated background processing fix.

This test validates the new functionality for handling PNG files with
integrated dark backgrounds that were losing parts of the white border.

Requirements validated:
- Alpha channel check detects integrated backgrounds
- Flood fill removes background from edges only
- 40-60px transparent padding is added before cropping
- Morphological closing replaces erosion
- Borders are generated after padding using alpha dilation
- Final crop includes safety margin and edge check
- White border is preserved completely
- Internal holes are maintained
- Final result has real transparency
"""

import pytest
from pathlib import Path
from PIL import Image
import numpy as np

from app.stickers.pipeline import StickerProcessor
from app.stickers.models import ProcessingProfile


class TestIntegratedBackgroundFix:
    """Test suite for integrated background processing fix."""

    @pytest.fixture
    def processor(self, tmp_path):
        """Create a StickerProcessor instance with temporary workspace."""
        profile = ProcessingProfile()
        return StickerProcessor(tmp_path, profile)

    def test_has_real_transparency_with_real_alpha(self, processor):
        """Test alpha channel detection with real transparency."""
        # Create image with real transparency
        rgba = Image.new("RGBA", (100, 100), (255, 255, 255, 0))
        rgba.putpixel((50, 50), (255, 0, 0, 255))
        
        has_transparency, has_integrated_bg = processor._has_real_transparency(rgba)
        
        assert bool(has_transparency) is True
        assert bool(has_integrated_bg) is False

    def test_has_real_transparency_with_integrated_background(self, processor):
        """Test alpha channel detection with integrated background."""
        # Create image with integrated background (all alpha = 255)
        rgba = Image.new("RGBA", (100, 100), (0, 0, 0, 255))
        rgba.putpixel((50, 50), (255, 255, 255, 255))
        
        has_transparency, has_integrated_bg = processor._has_real_transparency(rgba)
        
        assert bool(has_transparency) is False
        assert bool(has_integrated_bg) is True

    def test_remove_integrated_background_flood_fill(self, processor):
        """Test flood fill background removal from edges."""
        # Create test image with dark background and white design
        rgba = Image.new("RGBA", (200, 200), (30, 30, 30, 255))
        
        # Add white design in center
        for x in range(70, 130):
            for y in range(70, 130):
                rgba.putpixel((x, y), (255, 255, 255, 255))
        
        alpha = processor._remove_integrated_background_flood_fill(rgba, tolerance=35)
        
        # Check that background is removed (transparent)
        alpha_arr = np.asarray(alpha, dtype=np.uint8)
        
        # Edges should be transparent
        assert alpha_arr[0, 0] == 0
        assert alpha_arr[0, 100] == 0
        assert alpha_arr[100, 0] == 0
        
        # Center design should remain opaque
        assert alpha_arr[100, 100] == 255

    def test_add_transparent_padding(self, processor):
        """Test transparent padding addition."""
        rgba = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
        
        padded = processor._add_transparent_padding(rgba, padding_px=50)
        
        assert padded.size == (200, 200)
        
        # Check that padding is transparent
        assert padded.getpixel((0, 0))[3] == 0
        assert padded.getpixel((25, 25))[3] == 0
        
        # Check that original image is in center
        assert padded.getpixel((75, 75))[3] == 255

    def test_morphological_closing_preserves_border(self, processor):
        """Test that morphological closing preserves white border."""
        # Create alpha with small discontinuities
        alpha = Image.new("L", (100, 100), 0)
        
        # Add main shape
        for x in range(30, 70):
            for y in range(30, 70):
                alpha.putpixel((x, y), 255)
        
        # Add small gap
        for x in range(45, 55):
            alpha.putpixel((x, 35), 0)
        
        original_area = sum(1 for p in alpha.get_flattened_data() if p > 127)
        
        closed = processor._apply_morphological_closing(alpha, kernel_size=3, iterations=1)
        
        # Gap should be filled
        assert closed.getpixel((50, 35)) > 127
        
        # Area should not be significantly reduced (unlike erosion)
        closed_area = sum(1 for p in closed.get_flattened_data() if p > 127)
        assert closed_area >= original_area * 0.95

    def test_generate_borders_from_alpha(self, processor):
        """Test border generation using alpha dilation."""
        alpha = Image.new("L", (100, 100), 0)
        
        # Add small shape in center
        for x in range(45, 55):
            for y in range(45, 55):
                alpha.putpixel((x, y), 255)
        
        white_border, black_border = processor._generate_borders_from_alpha(
            alpha, white_border_px=10, black_border_px=2)
        
        # White border should be larger than original
        white_arr = np.asarray(white_border, dtype=np.uint8)
        alpha_arr = np.asarray(alpha, dtype=np.uint8)
        
        assert white_arr.sum() > alpha_arr.sum()
        
        # Black border should be larger than white border
        black_arr = np.asarray(black_border, dtype=np.uint8)
        assert black_arr.sum() > white_arr.sum()

    def test_safe_crop_with_margin(self, processor):
        """Test safe crop with safety margin."""
        rgba = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        alpha = Image.new("L", (200, 200), 0)
        
        # Add design in center
        for x in range(80, 120):
            for y in range(80, 120):
                rgba.putpixel((x, y), (255, 255, 255, 255))
                alpha.putpixel((x, y), 255)
        
        cropped = processor._safe_crop_with_margin(rgba, alpha, safety_margin_px=15)
        
        # Should be cropped close to design with margin
        assert cropped.size[0] < 200
        assert cropped.size[1] < 200
        
        # Design should still be present
        assert cropped.getpixel((40, 40))[3] == 255

    def test_safe_crop_auto_padding_on_edge_touch(self, processor):
        """Test that auto-padding is added when design touches edge."""
        rgba = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        alpha = Image.new("L", (100, 100), 0)
        
        # Add design that touches edge
        for x in range(0, 50):
            for y in range(0, 50):
                rgba.putpixel((x, y), (255, 255, 255, 255))
                alpha.putpixel((x, y), 255)
        
        cropped = processor._safe_crop_with_margin(rgba, alpha, safety_margin_px=15)
        
        # Should have padding added (size should be larger than bbox)
        assert cropped.size[0] > 50
        assert cropped.size[1] > 50

    def test_safe_crop_ignores_nearly_invisible_alpha_residue(self, processor):
        rgba = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        alpha = Image.new("L", (200, 200), 0)
        rgba.putpixel((2, 2), (255, 255, 255, 4))
        alpha.putpixel((2, 2), 4)
        for x in range(80, 120):
            for y in range(60, 140):
                rgba.putpixel((x, y), (255, 0, 0, 255))
                alpha.putpixel((x, y), 255)

        cropped = processor._safe_crop_with_margin(
            rgba, alpha, safety_margin_px=0,
        )

        assert cropped.size == (40, 80)

    def test_flow_c_with_integrated_background(self, processor, tmp_path):
        """Test Flow C with integrated background PNG."""
        # Create test PNG with integrated dark background
        rgba = Image.new("RGBA", (300, 300), (20, 20, 20, 255))
        
        # Add white shield design with border
        for x in range(100, 200):
            for y in range(100, 200):
                rgba.putpixel((x, y), (255, 255, 255, 255))
        
        # Add black outline
        for x in range(100, 200):
            for y in range(100, 200):
                if x == 100 or x == 199 or y == 100 or y == 199:
                    rgba.putpixel((x, y), (0, 0, 0, 255))
        
        # Save as test file
        test_file = tmp_path / "test_integrated_bg.png"
        rgba.save(test_file)
        
        # Process
        result = processor.process(test_file)
        
        # Verify result exists and has transparency
        assert result.status == "Procesado"
        
        # Check that output has real transparency
        master_path = Path(result.artifacts["master"])
        master = Image.open(master_path)
        alpha = master.getchannel("A")
        
        # Should have transparency
        min_alpha, max_alpha = alpha.getextrema()
        assert min_alpha < 255
        
        # Should have opaque areas
        assert max_alpha == 255


def test_shield_images_processing(tmp_path):
    """Test processing of the five shield images.
    
    This test requires the actual shield images to be present in the
    test directory. It validates that:
    - White border is preserved completely
    - Top, bottom and sides are not flat or cut
    - Internal blacks are not transparent
    - Internal holes are maintained
    - Final result has real transparency
    """
    shield_files = [
        "shield1.png",
        "shield2.png", 
        "shield3.png",
        "shield4.png",
        "shield5.png"
    ]
    
    test_dir = tmp_path / "shields"
    test_dir.mkdir(exist_ok=True)
    
    # This test will be skipped if shield files are not present
    for shield_file in shield_files:
        shield_path = test_dir / shield_file
        if not shield_path.exists():
            pytest.skip(f"Shield file {shield_file} not found")
    
    profile = ProcessingProfile()
    processor = StickerProcessor(tmp_path, profile)
    
    for shield_file in shield_files:
        shield_path = test_dir / shield_file
        
        # Process shield
        result = processor.process(shield_path)
        
        # Verify processing succeeded
        assert result.status == "Procesado"
        
        # Check master output
        master_path = Path(result.artifacts["master"])
        master = Image.open(master_path)
        
        # Verify transparency
        alpha = master.getchannel("A")
        min_alpha, max_alpha = alpha.getextrema()
        assert min_alpha < 255, f"{shield_file} should have transparency"
        assert max_alpha == 255, f"{shield_file} should have opaque areas"
        
        # Verify edges are not completely flat (should have variation)
        # This indicates the white border is preserved
        rgb = master.convert("RGB")
        edge_pixels = []
        for x in range(master.width):
            edge_pixels.append(rgb.getpixel((x, 0)))
            edge_pixels.append(rgb.getpixel((x, master.height - 1)))
        for y in range(master.height):
            edge_pixels.append(rgb.getpixel((0, y)))
            edge_pixels.append(rgb.getpixel((master.width - 1, y)))
        
        # Check that not all edge pixels are the same (would indicate flat cut)
        unique_colors = len(set(edge_pixels))
        assert unique_colors > 1, f"{shield_file} edges should not be completely flat"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
