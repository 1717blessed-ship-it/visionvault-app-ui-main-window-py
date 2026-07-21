import unittest
from datetime import date, datetime, timedelta

from app.workflow.estimator import format_time_remaining


class EstimatorTests(unittest.TestCase):
    def test_format_time_remaining_accepts_datetime_objects(self):
        delivery = datetime.now() + timedelta(hours=2, minutes=30)
        text = format_time_remaining({"delivery_date": delivery})
        self.assertTrue(text != "Fecha inválida")
        self.assertIn("horas", text)

    def test_format_time_remaining_accepts_date_objects(self):
        delivery = date.today() + timedelta(days=1)
        text = format_time_remaining({"delivery_date": delivery})
        self.assertTrue(text != "Fecha inválida")
        self.assertTrue("horas" in text or "días" in text)
