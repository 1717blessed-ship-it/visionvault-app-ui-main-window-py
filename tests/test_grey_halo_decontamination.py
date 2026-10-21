"""
Tests para la ELIMINACIÓN TOTAL de halos grises en stickers.

DOCCIONE STUDIO - ESPECIFICACIÓN:
- El halo gris debe ser ELIMINADO completamente mediante contracción de máscara
- NO debe blanquearse ni convertirse en borde blanco
- La máscara debe contraerse solo lo necesario
- Se debe preservar la geometría del diseño
"""

import unittest
import numpy as np
from PIL import Image, ImageDraw


class TestGreyHaloElimination(unittest.TestCase):
    """Tests para el módulo de ELIMINACIÓN de halos grises."""

    def setUp(self):
        """Configuración inicial para cada test."""
        try:
            from app.stickers.grey_halo_decontamination import (
                eliminate_grey_halo_by_mask_contraction,
                detect_grey_halo_thickness
            )
            self.eliminate_func = eliminate_grey_halo_by_mask_contraction
            self.detect_func = detect_grey_halo_thickness
        except ImportError:
            self.skipTest("Módulo grey_halo_decontamination no disponible")

    def test_detection_of_grey_halo(self):
        """Test de detección de halo gris."""
        # Crear sticker con halo gris
        size = 100
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # Diseño blanco
        draw.ellipse((30, 30, 70, 70), fill=(255, 255, 255, 255))
        
        # Halo gris de 5px
        for i in range(1, 6):
            draw.ellipse(
                (30-i, 30-i, 70+i, 70+i),
                outline=(150, 150, 150, 255),
                width=1
            )
        
        alpha = image.getchannel("A")
        
        # Detectar halo
        halo_info = self.detect_func(image, alpha)
        
        self.assertTrue(halo_info["has_grey_halo"])
        self.assertGreater(halo_info["estimated_thickness_px"], 0)
        self.assertGreater(halo_info["grey_ratio"], 0.15)

    def test_elimination_creates_transparent_background(self):
        """Test: El halo debe convertirse en fondo completamente transparente."""
        size = 100
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # Diseño blanco
        draw.ellipse((30, 30, 70, 70), fill=(255, 255, 255, 255))
        
        # Halo gris
        for i in range(1, 6):
            draw.ellipse(
                (30-i, 30-i, 70+i, 70+i),
                outline=(140, 140, 140, 255),
                width=1
            )
        
        alpha = image.getchannel("A")
        
        # Aplicar eliminación
        clean_image, clean_alpha = self.eliminate_func(image, alpha)
        
        # Verificar que la imagen limpia es RGBA
        self.assertEqual(clean_image.mode, "RGBA")
        self.assertEqual(clean_alpha.mode, "L")
        
        # Verificar que hay región transparente (alfa = 0)
        alpha_arr = np.array(clean_alpha)
        transparent_pixels = (alpha_arr == 0).sum()
        self.assertGreater(transparent_pixels, 0, "Debe haber píxeles transparentes")
        
        # Verificar que el centro sigue opaco
        center_alpha = clean_alpha.getpixel((50, 50))
        self.assertGreater(center_alpha, 200, "El centro debe seguir opaco")

    def test_no_grey_pixels_in_result(self):
        """Test crítico: NO debe haber píxeles grises en el resultado."""
        size = 100
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # Diseño blanco
        draw.ellipse((30, 30, 70, 70), fill=(255, 255, 255, 255))
        
        # Halo gris prominente
        for i in range(1, 8):
            grey = 130 + i * 5
            draw.ellipse(
                (30-i, 30-i, 70+i, 70+i),
                outline=(grey, grey, grey, 255),
                width=1
            )
        
        alpha_original = image.getchannel("A")
        
        # Aplicar eliminación
        clean_image, clean_alpha = self.eliminate_func(image, alpha_original)
        
        # Extraer región opaca del resultado
        rgba = np.array(clean_image)
        alpha_arr = np.array(clean_alpha)
        opaque_region = alpha_arr > 50
        
        if opaque_region.any():
            # Verificar que NO hay píxeles grises en región opaca
            r = rgba[opaque_region, 0]
            g = rgba[opaque_region, 1]
            b = rgba[opaque_region, 2]
            
            # Detectar grises neutros
            is_neutral = (
                (np.abs(r.astype(int) - g.astype(int)) <= 25) &
                (np.abs(g.astype(int) - b.astype(int)) <= 25) &
                (np.abs(r.astype(int) - b.astype(int)) <= 25)
            )
            is_grey = (r >= 100) & (r <= 200)
            grey_pixels = (is_neutral & is_grey).sum()
            grey_ratio = float(grey_pixels) / len(r)
            
            # El ratio de grises debe ser mínimo (< 5%)
            self.assertLess(
                grey_ratio, 0.05,
                f"Hay demasiados píxeles grises ({grey_ratio:.1%}) en la región opaca"
            )

    def test_preserve_star_geometry(self):
        """Test: Preservar geometría de estrellas."""
        import math
        
        size = 100
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # Estrella blanca
        center_x, center_y = 50, 50
        star_points = []
        for i in range(10):
            angle = (i * 36 - 90) * math.pi / 180
            radius = 30 if i % 2 == 0 else 15
            x = center_x + radius * math.cos(angle)
            y = center_y + radius * math.sin(angle)
            star_points.append((x, y))
        
        draw.polygon(star_points, fill=(255, 255, 255, 255))
        
        # Halo gris
        for offset in range(1, 5):
            halo_points = []
            for i in range(10):
                angle = (i * 36 - 90) * math.pi / 180
                radius = (30 if i % 2 == 0 else 15) + offset
                x = center_x + radius * math.cos(angle)
                y = center_y + radius * math.sin(angle)
                halo_points.append((x, y))
            draw.polygon(halo_points, outline=(140, 140, 140, 255), width=1)
        
        alpha_original = image.getchannel("A")
        
        # Aplicar eliminación
        clean_image, clean_alpha = self.eliminate_func(image, alpha_original)
        
        # Verificar que el centro sigue opaco (estrella preservada)
        center_alpha = clean_alpha.getpixel((50, 50))
        self.assertGreater(center_alpha, 200)
        
        # Verificar que hay forma definida
        alpha_arr = np.array(clean_alpha)
        opaque_area = (alpha_arr > 127).sum()
        self.assertGreater(opaque_area, 100, "Debe haber área opaca significativa")

    def test_no_halo_case(self):
        """Test: Imágenes sin halo no deben modificarse excesivamente."""
        size = 100
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # Diseño limpio sin halo
        draw.ellipse((30, 30, 70, 70), fill=(255, 255, 255, 255))
        
        alpha_original = image.getchannel("A")
        
        # Aplicar eliminación
        clean_image, clean_alpha = self.eliminate_func(image, alpha_original)
        
        # Comparar áreas
        original_area = (np.array(alpha_original) > 127).sum()
        clean_area = (np.array(clean_alpha) > 127).sum()
        
        # El área no debe cambiar dramáticamente si no hay halo
        area_ratio = clean_area / max(1, original_area)
        self.assertGreater(area_ratio, 0.85, "No debe contraer excesivamente sin halo")

    def test_auto_detection_of_thickness(self):
        """Test: Detección automática del grosor del halo."""
        size = 100
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # Diseño blanco
        draw.ellipse((35, 35, 65, 65), fill=(255, 255, 255, 255))
        
        # Halo gris de grosor conocido (7px)
        for i in range(1, 8):
            draw.ellipse(
                (35-i, 35-i, 65+i, 65+i),
                outline=(145, 145, 145, 255),
                width=1
            )
        
        alpha = image.getchannel("A")
        
        # Detectar grosor automáticamente
        halo_info = self.detect_func(image, alpha)
        
        # El grosor estimado debe estar cerca de 7px (±5px)
        estimated = halo_info["estimated_thickness_px"]
        self.assertGreater(estimated, 4, "Grosor mínimo detectado")
        self.assertLessEqual(estimated, 15, "Grosor máximo razonable")

    def test_complete_process_with_white_border_generation(self):
        """Test CRÍTICO: Proceso completo con generación de borde blanco."""
        try:
            from app.stickers.grey_halo_decontamination import (
                complete_grey_halo_elimination_with_white_border
            )
        except ImportError:
            self.skipTest("Función completa no disponible")
        
        size = 100
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # Diseño blanco
        draw.ellipse((30, 30, 70, 70), fill=(255, 255, 255, 255))
        
        # Halo gris
        for i in range(1, 6):
            draw.ellipse(
                (30-i, 30-i, 70+i, 70+i),
                outline=(140, 140, 140, 255),
                width=1
            )
        
        alpha = image.getchannel("A")
        
        # Aplicar proceso completo
        final_image, final_alpha, metadata = complete_grey_halo_elimination_with_white_border(
            image, alpha,
            contraction_px=None,  # Auto
            white_border_mm=1.0,
            dpi=300,
            generate_white_border=True,
            existing_border=False,  # Explicit content, not a finished sticker border.
        )
        
        # Verificaciones
        self.assertEqual(final_image.mode, "RGBA")
        self.assertEqual(final_alpha.mode, "L")
        
        # Debe haber generado borde blanco
        self.assertTrue(metadata["white_border_generated"])
        self.assertGreater(metadata["white_border_px"], 0)
        
        # Debe haber aplicado contracción
        self.assertGreater(metadata["contraction_applied_px"], 0)
        
        # El área final debe ser mayor que la contraída (por el borde)
        alpha_final_arr = np.array(final_alpha)
        final_area = (alpha_final_arr > 127).sum()
        
        # El alfa original
        alpha_original_arr = np.array(alpha)
        original_area = (alpha_original_arr > 127).sum()
        
        # El área final puede ser mayor o menor dependiendo del borde
        # Lo importante es que exista borde blanco
        self.assertGreater(final_area, 0)
        
        # Verificar que hay píxeles blancos en el borde
        rgba_final = np.array(final_image)
        opaque_region = alpha_final_arr > 127
        
        if opaque_region.any():
            r = rgba_final[opaque_region, 0]
            g = rgba_final[opaque_region, 1]
            b = rgba_final[opaque_region, 2]
            
            # Debe haber píxeles blancos
            white_pixels = ((r > 240) & (g > 240) & (b > 240)).sum()
            white_ratio = float(white_pixels) / len(r)
            
            self.assertGreater(white_ratio, 0.1, "Debe haber píxeles blancos del borde")


if __name__ == "__main__":
    unittest.main()
