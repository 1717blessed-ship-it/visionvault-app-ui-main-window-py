from pathlib import Path

from app.database.database import ImageDatabase
from app.fiscal import FiscalRepository


def test_fiscal_draft_snapshots_order_and_authorization(tmp_path: Path):
    database = ImageDatabase(tmp_path / "doccione.db")
    order_id = database.create_order(
        "Ana", "5491100000000", jobs=[{"title": "Stickers", "quantity": 10, "subtotal": 1500}]
    )
    client_id = database.connection.execute("SELECT client_id FROM orders WHERE id = ?", (order_id,)).fetchone()[0]
    fiscal = FiscalRepository(database.connection)
    fiscal.upsert_client_profile(client_id, document_type="CUIT", document_number="20-12345678-9", legal_name="Ana SA")
    profile_id = fiscal.save_profile(
        legal_name="Doccione", cuit="30-12345678-9", iva_condition="Monotributo", point_of_sale=3,
    )

    invoice_id = fiscal.create_invoice_draft(order_id, "C", profile_id=profile_id)
    invoice = fiscal.invoices_for_order(order_id)[0]
    assert invoice["id"] == invoice_id
    assert invoice["status"] == FiscalRepository.DRAFT
    assert "Stickers" in invoice["lines_snapshot_json"]

    fiscal.mark_authorized(invoice_id, voucher_number=1, cae="12345678901234", cae_expires_at="2026-08-10")
    assert fiscal.invoices_for_order(order_id)[0]["status"] == FiscalRepository.AUTHORIZED
