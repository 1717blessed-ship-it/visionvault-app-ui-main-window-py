import unittest

from app.workflow.timeline import (
    GENERAL_WORKFLOW,
    format_timeline,
    get_current_stage,
    get_stage_progress,
    order_statuses,
)


class TimelineWorkflowTests(unittest.TestCase):
    def test_general_workflow_uses_requested_percentages(self):
        self.assertEqual(GENERAL_WORKFLOW[0], ("Recibido", 5))
        self.assertEqual(GENERAL_WORKFLOW[-2:], (("Finalizado", 95), ("Entregado", 100)))
        self.assertEqual(get_stage_progress({"status": "Control de calidad"}), 0.9)

    def test_vinyl_material_selects_sticker_workflow(self):
        order = {"material": "Vinilo Full Color HD", "status": "Corte plotter"}
        self.assertIn("Laminado", order_statuses(order))
        self.assertIn("Empaquetado", order_statuses(order))
        self.assertNotIn("Sublimado / Laminado", order_statuses(order))
        self.assertEqual(get_current_stage(order), "Corte plotter")
        self.assertEqual(get_stage_progress(order), 0.8)
        self.assertEqual(get_current_stage({"material": "Vinilo", "status": "Finalizado"}), "Empaquetado")

    def test_timeline_marks_completed_sticker_stages(self):
        timeline = dict(format_timeline({"material": "Sticker de vinilo", "status": "Impresión"}))
        self.assertEqual(timeline["Recibido"], "●")
        self.assertEqual(timeline["Impresión"], "●")
        self.assertEqual(timeline["Laminado"], "○")
