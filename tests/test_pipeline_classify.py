"""Tests del árbol de clasificación y de los flujos A / B / C / D.

Cada test construye una imagen sintética que representa fielmente
el caso que necesita ejercitar y verifica:
  · Que classify() asigne el ImageCase correcto.
  · Que process() complete sin errores.
  · Que los artefactos clave existan y tengan las propiedades esperadas.
"""

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


# ---------------------------------------------------------------------------
# Fábrica de imágenes sintéticas
# ---------------------------------------------------------------------------

def _png_transparent(size=(400, 500), color=(30, 120, 220, 255)):
    """Caso A: PNG con canal alpha, sin borde blanco, sin outline negro."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((40, 40, size[0]-40, size[1]-40), fill=color)
    return img


def _sticker_finished(size=(400, 500)):
    """Caso B: diseño recortado con borde blanco exterior visible."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Borde blanco exterior
    draw.ellipse((10, 10, size[0]-10, size[1]-10), fill=(255, 255, 255, 255))
    # Outline negro del personaje
    draw.ellipse((38, 38, size[0]-38, size[1]-38), fill=(0, 0, 0, 255))
    # Contenido de color
    draw.ellipse((46, 46, size[0]-46, size[1]-46), fill=(200, 50, 50, 255))
    return img


def _uniform_white_bg(size=(400, 500)):
    """Caso C-blanco: ilustración sobre fondo blanco sólido."""
    img = Image.new("RGB", size, (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.ellipse((60, 60, size[0]-60, size[1]-60), fill=(30, 120, 220))
    return img


def _uniform_color_bg(size=(400, 500), bg=(0, 180, 0)):
    """Caso C-color: ilustración sobre fondo de color uniforme."""
    img = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(img)
    draw.ellipse((60, 60, size[0]-60, size[1]-60), fill=(220, 80, 20))
    return img


def _photo_like(size=(400, 500)):
    """Caso D: imagen con degradados y muchos colores (simula fotografía)."""
    import random
    random.seed(42)
    img = Image.new("RGB", size, (200, 180, 160))
    draw = ImageDraw.Draw(img)
    # Muchas formas de colores distintos generan una paleta amplia
    for _ in range(120):
        x = random.randint(0, size[0]-1)
        y = random.randint(0, size[1]-1)
        r = random.randint(1, 30)
        c = (random.randint(0,255), random.randint(0,255), random.randint(0,255))
        draw.ellipse((x-r, y-r, x+r, y+r), fill=c)
    # Aplicar blur para crear degradados suaves (característica de foto)
    return img.filter(ImageFilter.GaussianBlur(2))


def _png_with_black_outline(size=(400, 500)):
    """Caso A con contorno interno negro: diseño recortado con outline."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Outline negro (contorno interno)
    draw.ellipse((40, 40, size[0]-40, size[1]-40), fill=(0, 0, 0, 255))
    # Contenido de color
    draw.ellipse((56, 56, size[0]-56, size[1]-56), fill=(80, 160, 240, 255))
    return img


# ---------------------------------------------------------------------------
# Tests de classify()
# ---------------------------------------------------------------------------

class TestClassify(unittest.TestCase):

    def _proc(self):
        from app.stickers.pipeline import StickerProcessor
        return StickerProcessor.__new__(StickerProcessor)

    def test_caso_a_png_transparente_sin_borde(self):
        from app.stickers.pipeline import ImageCase
        proc = self._proc()
        rgba = _png_transparent()
        result = proc.classify(rgba)
        self.assertEqual(result.case, ImageCase.A)
        self.assertTrue(result.has_transparency)
        self.assertFalse(result.has_white_border)

    def test_caso_b_sticker_terminado_con_borde_blanco(self):
        from app.stickers.pipeline import ImageCase
        proc = self._proc()
        rgba = _sticker_finished()
        result = proc.classify(rgba)
        self.assertEqual(result.case, ImageCase.B)
        self.assertTrue(result.has_white_border)

    def test_caso_c_fondo_blanco_uniforme(self):
        from app.stickers.pipeline import ImageCase
        proc = self._proc()
        rgba = _uniform_white_bg().convert("RGBA")
        result = proc.classify(rgba)
        self.assertEqual(result.case, ImageCase.C)
        self.assertTrue(result.uniform_background)

    def test_caso_c_fondo_color_uniforme(self):
        from app.stickers.pipeline import ImageCase
        proc = self._proc()
        rgba = _uniform_color_bg().convert("RGBA")
        result = proc.classify(rgba)
        self.assertEqual(result.case, ImageCase.C)

    def test_caso_d_fotografia(self):
        from app.stickers.pipeline import ImageCase
        proc = self._proc()
        rgba = _photo_like().convert("RGBA")
        result = proc.classify(rgba)
        # Fotografía: muchos colores, bordes suaves
        self.assertIn(result.case, (ImageCase.C, ImageCase.D))
        # Al menos debe ser tratada como no-A y no-B
        self.assertNotEqual(result.case, ImageCase.A)
        self.assertNotEqual(result.case, ImageCase.B)

    def test_contorno_negro_detectado(self):
        proc = self._proc()
        rgba = _png_with_black_outline()
        result = proc.classify(rgba)
        self.assertEqual(result.design_mode, "Contorno interno")

    def test_sin_contorno_negro_es_color_uniforme(self):
        proc = self._proc()
        rgba = _png_transparent(color=(200, 80, 40, 255))
        result = proc.classify(rgba)
        self.assertEqual(result.design_mode, "Color uniforme")

    def test_mode_override_fuerza_caso_b(self):
        from app.stickers.pipeline import ImageCase, ProcessingMode
        proc = self._proc()
        rgba = _uniform_white_bg().convert("RGBA")
        result = proc.classify(rgba,
                               mode_override=ProcessingMode.EXISTING.value)
        self.assertEqual(result.case, ImageCase.B)

    def test_mode_override_fuerza_caso_d(self):
        from app.stickers.pipeline import ImageCase, ProcessingMode
        proc = self._proc()
        rgba = _png_transparent()
        result = proc.classify(rgba,
                               mode_override=ProcessingMode.PHOTO.value)
        self.assertEqual(result.case, ImageCase.D)

    def test_classify_devuelve_razones_no_vacias(self):
        proc = self._proc()
        rgba = _png_transparent()
        result = proc.classify(rgba)
        self.assertGreater(len(result.reasons), 0)


# ---------------------------------------------------------------------------
# Tests de process() — un caso por flujo
# ---------------------------------------------------------------------------

class TestProcessFlows(unittest.TestCase):

    def setUp(self):
        self._temp_dirs = []

    def tearDown(self):
        import shutil
        for d in self._temp_dirs:
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass

    def _run(self, img, suffix=".png", **kwargs):
        """Guarda img en un tempdir y corre process(), devuelve result."""
        from app.stickers.pipeline import StickerProcessor
        folder = tempfile.mkdtemp()
        self._temp_dirs.append(folder)
        src = Path(folder) / f"fuente{suffix}"
        img.save(src)
        result = StickerProcessor(
            Path(folder) / "work"
        ).process(src, **kwargs)
        # Verificaciones básicas comunes a todos los flujos
        self.assertEqual(result.status, "Procesado")
        self.assertIn("master", result.artifacts)
        self.assertIn("cut",    result.artifacts)
        self.assertIn("thumbnail", result.artifacts)
        master_path = Path(result.artifacts["master"])
        self.assertTrue(master_path.exists())
        with Image.open(master_path) as m:
            self.assertGreater(m.getchannel("A").getbbox()[2], 0)
        return result

    def test_flujo_a_png_transparente(self):
        result = self._run(_png_transparent())
        self.assertIn(result.analysis["case"],
                      ["A - PNG transparente sin borde",
                       "B - Sticker ya terminado"])  # ambos válidos

    def test_flujo_b_sticker_terminado(self):
        result = self._run(_sticker_finished())
        self.assertEqual(result.analysis["case"],
                         "B - Sticker ya terminado")

    def test_flujo_c_fondo_blanco(self):
        result = self._run(_uniform_white_bg(), suffix=".jpg")
        self.assertIn("case", result.analysis)
        self.assertEqual(result.analysis["case"],
                         "C - Fondo de color uniforme")

    def test_flujo_c_fondo_verde(self):
        result = self._run(_uniform_color_bg(bg=(0, 200, 0)), suffix=".jpg")
        self.assertEqual(result.analysis["case"],
                         "C - Fondo de color uniforme")

    def test_flujo_preserve_full_image(self):
        img = _photo_like()
        result = self._run(img, suffix=".jpg", preserve_full_image=True)
        self.assertEqual(result.analysis["selection_processing_mode"],
                         "Selección completa")

    def test_contorno_negro_activa_trazo_interno(self):
        result = self._run(_png_with_black_outline())
        self.assertEqual(result.analysis["design_mode"], "Contorno interno")

    def test_artefactos_requeridos_siempre_presentes(self):
        for img, suf in [
            (_png_transparent(),      ".png"),
            (_sticker_finished(),     ".png"),
            (_uniform_white_bg(),     ".jpg"),
        ]:
            with tempfile.TemporaryDirectory() as folder:
                from app.stickers.pipeline import StickerProcessor
                src = Path(folder) / f"img{suf}"
                img.save(src)
                result = StickerProcessor(
                    Path(folder) / "work").process(src)
                for key in ("original","clean","mask","master",
                            "print","control","cut","thumbnail","metadata"):
                    self.assertIn(key, result.artifacts, msg=f"{key} falta")
                    self.assertTrue(Path(result.artifacts[key]).exists(),
                                    msg=f"{key} no existe en disco")

    def test_master_tiene_dpi_300_y_tamano_correcto(self):
        from app.stickers.pipeline import ProcessingProfile
        result = self._run(_png_transparent())
        expected_px = ProcessingProfile().master_pixels
        master_path = Path(result.artifacts["master"])
        with Image.open(master_path) as m:
            self.assertEqual(m.size, (expected_px, expected_px))
            dpi = m.info.get("dpi", (0, 0))
            self.assertAlmostEqual(dpi[0], 300, delta=0.5)

    def test_orientacion_vertical_forzada(self):
        """Un diseño horizontal debe rotarse para que el lado mayor quede vertical."""
        img = Image.new("RGBA", (700, 300), (0, 0, 0, 0))
        ImageDraw.Draw(img).rounded_rectangle(
            (10, 10, 690, 290), radius=60, fill=(50, 100, 200, 255))
        result = self._run(img)
        self.assertTrue(result.analysis["rotated_to_vertical"])


if __name__ == "__main__":
    unittest.main()
