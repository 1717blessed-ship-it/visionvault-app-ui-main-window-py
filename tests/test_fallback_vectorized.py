"""Tests del mecanismo de fallback de _uniform_background_alpha.

Verifica cuatro escenarios:
  A. import cv2 falla         → se llama al legacy
  B. cv2.error en vectorizada  → se llama al legacy
  C. MemoryError en vectorizada → se llama al legacy
  D. ValueError en vectorizada  → el error se propaga
"""
import builtins
import unittest
from unittest.mock import patch
from pathlib import Path
from PIL import Image, ImageDraw

from app.stickers.pipeline import StickerProcessor


class TestFallbackVectorized(unittest.TestCase):
    """Prueba que el fallback de _uniform_background_alpha sea seguro."""

    def setUp(self):
        self.img = Image.new("RGB", (100, 100), (200, 200, 200))
        draw = ImageDraw.Draw(self.img)
        draw.ellipse((20, 20, 80, 80), fill=(50, 50, 200))

    # ── A: import cv2 falla ────────────────────────────────────────────

    def test_import_cv2_fails_calls_legacy(self):
        """Si import cv2 falla (ImportError), debe llamar al legacy una vez."""
        original_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "cv2":
                raise ImportError("no module named cv2")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_mock_import):
            with patch.object(
                StickerProcessor, "_uniform_background_alpha_legacy",
                return_value=Image.new("L", (100, 100), 255),
            ) as mock_legacy:
                result = StickerProcessor._uniform_background_alpha(self.img)

                mock_legacy.assert_called_once_with(self.img, 42)
                self.assertIsNotNone(result)

    def test_import_cv2_fails_no_name_error(self):
        """Si import cv2 falla, no debe aparecer NameError por cv2 no definido."""
        original_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "cv2":
                raise ImportError("no module named cv2")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_mock_import):
            try:
                StickerProcessor._uniform_background_alpha(self.img)
            except NameError:
                self.fail("NameError propagado: cv2 no definido al capturar excepcion")

    # ── B: cv2.error en vectorizada ────────────────────────────────────

    @patch.object(StickerProcessor, "_uniform_background_alpha_vectorized")
    def test_vector_raises_cv2_error_calls_legacy(self, mock_vec):
        """Si la vectorizada lanza cv2.error, debe llamar al legacy."""
        import cv2
        mock_vec.side_effect = cv2.error("cv2 error simulado")

        with patch.object(
            StickerProcessor, "_uniform_background_alpha_legacy",
            return_value=Image.new("L", (100, 100), 255),
        ) as mock_legacy:
            result = StickerProcessor._uniform_background_alpha(self.img)

            mock_vec.assert_called_once_with(self.img, 42)
            mock_legacy.assert_called_once_with(self.img, 42)
            self.assertIsNotNone(result)

    # ── C: MemoryError en vectorizada ──────────────────────────────────

    @patch.object(StickerProcessor, "_uniform_background_alpha_vectorized")
    def test_vector_raises_memory_error_calls_legacy(self, mock_vec):
        """Si la vectorizada lanza MemoryError, debe llamar al legacy."""
        mock_vec.side_effect = MemoryError("out of memory")

        with patch.object(
            StickerProcessor, "_uniform_background_alpha_legacy",
            return_value=Image.new("L", (100, 100), 255),
        ) as mock_legacy:
            result = StickerProcessor._uniform_background_alpha(self.img)

            mock_vec.assert_called_once_with(self.img, 42)
            mock_legacy.assert_called_once_with(self.img, 42)
            self.assertIsNotNone(result)

    # ── D: ValueError se propaga ───────────────────────────────────────

    @patch.object(StickerProcessor, "_uniform_background_alpha_vectorized")
    def test_vector_raises_value_error_propagates(self, mock_vec):
        """Si la vectorizada lanza ValueError, el error debe propagarse."""
        mock_vec.side_effect = ValueError("error de programacion")

        with patch.object(
            StickerProcessor, "_uniform_background_alpha_legacy",
        ) as mock_legacy:
            with self.assertRaises(ValueError):
                StickerProcessor._uniform_background_alpha(self.img)

            mock_vec.assert_called_once_with(self.img, 42)
            mock_legacy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
