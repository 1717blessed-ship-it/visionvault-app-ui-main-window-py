import unittest
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw

from app.stickers.mask_candidates import (
    generate_and_score_all_candidates,
    select_candidate,
    MaskCandidate
)


class TestCandidateGenerationAndScoring(unittest.TestCase):

    def _compute_iou(self, mask1: np.ndarray, mask2: np.ndarray) -> float:
        """Calcula Intersection over Union (IoU) entre dos máscaras binarias (0/255)."""
        m1 = mask1 == 255
        m2 = mask2 == 255
        intersection = np.count_nonzero(m1 & m2)
        union = np.count_nonzero(m1 | m2)
        if union == 0:
            return 0.0
        return intersection / union

    def test_uniform_background(self):
        """Test 1: Fondo uniforme con un objeto en el centro.
        Comprueba que el fondo sea eliminado y el objeto conservado con un IoU alto.
        """
        # Imagen de 200x200 con fondo blanco y círculo azul en el centro
        img = Image.new("RGBA", (200, 200), (255, 255, 255, 255))
        draw = ImageDraw.Draw(img)
        # Círculo en el centro (x1, y1, x2, y2)
        draw.ellipse((50, 50, 150, 150), fill=(30, 120, 220, 255))

        # Máscara esperada: 255 dentro del círculo, 0 fuera
        expected_draw_img = Image.new("L", (200, 200), 0)
        ImageDraw.Draw(expected_draw_img).ellipse((50, 50, 150, 150), fill=255)
        expected_mask = np.array(expected_draw_img)

        candidates = generate_and_score_all_candidates(img)
        self.assertGreater(len(candidates), 1)

        # Buscamos el mejor candidato puntuado
        winner, decision = select_candidate(candidates)
        self.assertEqual(winner.discard_reason, None)

        iou = self._compute_iou(winner.mask, expected_mask)
        self.assertGreaterEqual(iou, 0.95)

        # Verificar porcentaje de fondo eliminado
        bg_pixels_expected = np.count_nonzero(expected_mask == 0)
        bg_pixels_removed = np.count_nonzero((winner.mask == 0) & (expected_mask == 0))
        pct_bg_removed = bg_pixels_removed / bg_pixels_expected
        self.assertGreaterEqual(pct_bg_removed, 0.95)

        # Verificar desglose de métricas
        self.assertIn("area_ratio", winner.scores)
        self.assertIn("final_score", winner.scores)

    def test_grey_border(self):
        """Test 2: Diseño con un borde gris propio.
        Comprueba que el borde gris sea conservado como parte del diseño.
        """
        # Fondo blanco con círculo rojo y borde gris grueso alrededor
        img = Image.new("RGBA", (200, 200), (255, 255, 255, 255))
        draw = ImageDraw.Draw(img)
        # Borde gris (150, 150, 150)
        draw.ellipse((40, 40, 160, 160), fill=(150, 150, 150, 255))
        # Círculo rojo central
        draw.ellipse((50, 50, 150, 150), fill=(220, 30, 30, 255))

        # Máscara de los píxeles grises originales del diseño
        grey_pixels_mask = np.zeros((200, 200), dtype=bool)
        img_np = np.array(img)
        for y in range(200):
            for x in range(200):
                r, g, b, a = img_np[y, x]
                if abs(r - 150) < 5 and abs(g - 150) < 5 and abs(b - 150) < 5:
                    grey_pixels_mask[y, x] = True

        candidates = generate_and_score_all_candidates(img)
        winner, decision = select_candidate(candidates)

        # Comprobar que una proporción alta del borde gris original permanece en foreground (255)
        grey_pixels_in_foreground = np.count_nonzero((winner.mask == 255) & grey_pixels_mask)
        total_grey_pixels = np.count_nonzero(grey_pixels_mask)
        ratio_grey_preserved = grey_pixels_in_foreground / total_grey_pixels

        self.assertGreaterEqual(ratio_grey_preserved, 0.90)

    def test_png_transparency(self):
        """Test 3: PNG con transparencia en el canal alpha.
        Comprueba que el candidato basado en la transparencia original coincida exactamente.
        """
        img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((50, 50, 150, 150), fill=(30, 120, 220, 255))

        # Máscara esperada basada en canal alpha
        expected_mask = np.zeros((200, 200), dtype=np.uint8)
        alpha = np.asarray(img.getchannel("A"))
        expected_mask[alpha > 12] = 255

        candidates = generate_and_score_all_candidates(img)
        
        # Encontrar candidato alpha_original
        alpha_cand = None
        for c in candidates:
            if c.name == "alpha_original":
                alpha_cand = c
                break

        self.assertIsNotNone(alpha_cand)
        self.assertIsNone(alpha_cand.discard_reason)
        
        # Verificar IoU exacto (1.0)
        iou = self._compute_iou(alpha_cand.mask, expected_mask)
        self.assertEqual(iou, 1.0)

    def test_internal_holes(self):
        """Test 4: Diseño tipo donut con un hueco interno.
        El hueco central debe conservarse (como fondo/0 en la máscara)
        y no recibir una penalización de hueco interno irregular.
        """
        img = Image.new("RGBA", (200, 200), (255, 255, 255, 255))
        draw = ImageDraw.Draw(img)
        # Círculo exterior (diseño verde)
        draw.ellipse((30, 30, 170, 170), fill=(30, 180, 50, 255))
        # Círculo interior (hueco blanco)
        draw.ellipse((80, 80, 120, 120), fill=(255, 255, 255, 255))

        candidates = generate_and_score_all_candidates(img)
        winner, decision = select_candidate(candidates)

        # El hueco central debe conservarse como background (0) en la máscara ganadora
        center_pixel_val = winner.mask[100, 100]
        self.assertEqual(center_pixel_val, 0)

        # Y no debe ser penalizado como hueco irregular (internal_holes_penalty debe ser bajo/nulo)
        self.assertLessEqual(winner.scores.get("irregular_hole_ratio", 0.0), 0.05)
        self.assertLessEqual(winner.scores.get("internal_holes_penalty", 0.0), 0.05)

    def test_color_gradient_background(self):
        """Test 5: Fondo degradado con cambios suaves de color.
        Comprueba que las tres tolerancias produzcan resultados distintos
        y que la tolerancia media/alta sea mejor que la baja.
        """
        img = Image.new("RGBA", (200, 200))
        # Generar un degradado de fondo oscuro a claro en R/G/B
        pixels = np.zeros((200, 200, 4), dtype=np.uint8)
        for y in range(200):
            val = int(100 + 155 * (y / 200.0))
            pixels[y, :, 0] = val
            pixels[y, :, 1] = val
            pixels[y, :, 2] = val
            pixels[y, :, 3] = 255

        # Dibujar círculo verde central directamente en los píxeles
        mask_circle = np.zeros((200, 200), dtype=bool)
        for y in range(200):
            for x in range(200):
                if (x - 100)**2 + (y - 100)**2 <= 50**2:
                    pixels[y, x] = [30, 180, 50, 255]
                    mask_circle[y, x] = True

        img = Image.fromarray(pixels, mode="RGBA")

        candidates = generate_and_score_all_candidates(img)

        # Extraer los scores/máscaras de las tres tolerancias
        c_low = next(c for c in candidates if c.name == "border_connected_low")
        c_mid = next(c for c in candidates if c.name == "border_connected_mid")
        c_high = next(c for c in candidates if c.name == "border_connected_high")

        # Comprobar que las tolerancias produzcan resultados distintos
        self.assertNotEqual(np.count_nonzero(c_low.mask == 255), np.count_nonzero(c_mid.mask == 255))
        self.assertNotEqual(np.count_nonzero(c_mid.mask == 255), np.count_nonzero(c_high.mask == 255))

        # La tolerancia media o alta debe eliminar más fondo (tener menor área de foreground) que la tolerancia baja
        self.assertLess(np.count_nonzero(c_mid.mask == 255), np.count_nonzero(c_low.mask == 255))

        # El ganador no debe ser penalizado si es el óptimo
        winner, decision = select_candidate(candidates)
        self.assertNotEqual(winner.score, 0.0)

    def test_object_touching_border(self):
        """Test 6: El objeto toca un borde de la imagen.
        Comprueba que no se produzca flood fill dentro del objeto.
        """
        img = Image.new("RGBA", (200, 200), (255, 255, 255, 255))
        draw = ImageDraw.Draw(img)
        # Círculo que corta/toca el borde inferior
        draw.ellipse((50, 120, 150, 220), fill=(220, 30, 30, 255))

        expected_draw_img = Image.new("L", (200, 200), 0)
        ImageDraw.Draw(expected_draw_img).ellipse((50, 120, 150, 220), fill=255)
        expected_mask = np.array(expected_draw_img)

        candidates = generate_and_score_all_candidates(img)
        winner, decision = select_candidate(candidates)

        # No debe ocurrir inundación/floodfill dentro del objeto.
        # Es decir, el objeto debe estar mayormente conservado (IoU alto contra la parte visible esperada)
        iou = self._compute_iou(winner.mask, expected_mask)
        self.assertGreaterEqual(iou, 0.90)

    def test_opaque_image_no_background(self):
        """Test 7: Imagen completamente opaca sin fondo distinguible.
        Comprueba que no se elija un ganador falso.
        """
        # Imagen con ruido aleatorio
        np.random.seed(42)
        noise = np.random.randint(0, 256, (200, 200, 4), dtype=np.uint8)
        noise[:, :, 3] = 255 # Completamente opaca
        img = Image.fromarray(noise, mode="RGBA")

        candidates = generate_and_score_all_candidates(img)
        winner, decision = select_candidate(candidates)

        # Ningún candidato debe ser considerado altamente confiable para selección automática
        # Es decir, su score o confianza debe ser bajo, o bien estar descartado.
        self.assertTrue(decision.requires_review)
        self.assertLess(decision.confidence, 70.0)

    def test_detached_component_suspicious(self):
        """Test 8: Componente secundario pequeño separado a gran distancia.
        Verifica que se detecten componentes separados, se penalicen, el estado
        quede en 'Revisar' y que no se borren de forma automática durante la Fase 1.
        """
        img = Image.new("RGBA", (200, 200), (255, 255, 255, 255))
        draw = ImageDraw.Draw(img)
        # Objeto principal grande
        draw.ellipse((40, 40, 120, 120), fill=(30, 180, 50, 255))
        # Componente secundario pequeño separado
        draw.ellipse((165, 165, 185, 185), fill=(30, 180, 50, 255))

        candidates = generate_and_score_all_candidates(img)
        winner, decision = select_candidate(candidates)

        # 1. Se deben detectar al menos 2 componentes de foreground
        self.assertGreaterEqual(winner.scores["component_count"], 2)

        # 2. El componente secundario se marca como sospechoso
        self.assertGreaterEqual(winner.scores["suspicious_component_count"], 1)

        # 3. Recibe penalización
        self.assertGreater(winner.scores["detached_component_penalty"], 0.0)

        # 4. Requiere revisión
        self.assertTrue(decision.requires_review)

        # 5. El componente NO se elimina automáticamente de la máscara ganadora (ambos están presentes)
        self.assertEqual(winner.mask[80, 80], 255)
        self.assertEqual(winner.mask[175, 175], 255)

    def test_detached_component_legitimate(self):
        """Test 9: Componente secundario legítimo cercano (ej. punto de letra o estrella).
        No debe recibir una penalización fuerte.
        """
        img = Image.new("RGBA", (200, 200), (255, 255, 255, 255))
        draw = ImageDraw.Draw(img)
        # Objeto principal
        draw.ellipse((40, 40, 120, 120), fill=(30, 180, 50, 255))
        # Componente legítimo muy cercano
        draw.ellipse((125, 125, 140, 140), fill=(30, 180, 50, 255))

        candidates = generate_and_score_all_candidates(img)
        winner, decision = select_candidate(candidates)

        # No se marca como sospechoso de penalización fuerte debido a la cercanía
        self.assertLessEqual(winner.scores["suspicious_component_count"], 0)
        self.assertEqual(winner.scores["detached_component_penalty"], 0.0)


if __name__ == "__main__":
    unittest.main()
