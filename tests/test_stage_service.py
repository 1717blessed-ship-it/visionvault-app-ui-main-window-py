"""Pruebas del servicio que alimenta el tablero de producciÃ³n."""

import sqlite3

from app.services.stage_service import StageService


def test_delivered_order_overrides_outdated_pending_jobs():
    """Un pedido entregado no debe volver a Pendiente por jobs histÃ³ricos."""
    service = StageService(sqlite3.connect(":memory:"))

    stage = service._get_order_current_stage(
        {
            "status": "Entregado",
            "jobs": [{"status": "Recibido"}, {"status": "Pendiente"}],
        }
    )

    assert stage == "Entregado"


def test_terminal_order_status_is_normalized_for_board():
    """El valor almacenado con mayÃºsculas o espacios sigue siendo terminal."""
    service = StageService(sqlite3.connect(":memory:"))

    stage = service._get_order_current_stage(
        {"status": "  entregado  ", "jobs": [{"status": "Recibido"}]}
    )

    assert stage == "Entregado"
