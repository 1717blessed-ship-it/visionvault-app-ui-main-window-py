import unittest

from app.ui.theme import PRIORITY_STYLES, format_currency, normalize_order_style_key
from app.workflow.priority import get_priority_color


class OrderCardStylesTests(unittest.TestCase):
    def test_normalize_order_style_key_handles_case_and_accents(self):
        self.assertEqual(normalize_order_style_key(" Impresión "), "impresion")
        self.assertEqual(normalize_order_style_key("SUBLIMADO"), "sublimado")
        self.assertEqual(normalize_order_style_key("En Diseño"), "diseño")
        self.assertEqual(normalize_order_style_key("Urgente"), "urgente")

    def test_normalize_order_style_key_falls_back_to_default(self):
        self.assertEqual(normalize_order_style_key("estado desconocido"), "default")

    def test_format_currency_uses_consistent_format(self):
        self.assertEqual(format_currency(1234.5), "$1,234.50")
        self.assertEqual(format_currency(0), "$0.00")

    def test_priority_styles_and_colors_are_consistent(self):
        self.assertEqual(normalize_order_style_key("Sin prisa"), "sin prisa")
        self.assertIn("sin prisa", PRIORITY_STYLES)
        self.assertEqual(get_priority_color("Baja"), PRIORITY_STYLES["baja"]["accent"])
        self.assertEqual(get_priority_color("Urgente"), PRIORITY_STYLES["urgente"]["accent"])


if __name__ == "__main__":
    unittest.main()
