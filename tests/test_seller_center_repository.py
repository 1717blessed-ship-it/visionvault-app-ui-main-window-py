from pathlib import Path

import pytest

from app.database.database import ImageDatabase
from app.sales.repository import SellerRepository


@pytest.fixture()
def sales(tmp_path):
    database = ImageDatabase(tmp_path / "sales.db")
    return database, SellerRepository(database.connection)


def test_lead_creates_and_replaces_followup_task(sales):
    _database, repository = sales
    lead_id = repository.create_lead(
        client_name="Ana", whatsapp="112233", source="Instagram",
        next_action="Enviar opciones", next_action_at="2026-08-15 10:00",
    )

    lead = repository.lead(lead_id)
    tasks = repository.tasks()
    assert lead["stage"] == "Nueva"
    assert tasks[0]["lead_id"] == lead_id
    assert tasks[0]["title"] == "Enviar opciones"

    repository.update_lead(
        lead_id, stage="Calificada", probability=75,
        next_action="Llamar", next_action_at="2026-08-16 12:00",
    )
    active = [task for task in repository.tasks() if task["lead_id"] == lead_id]
    assert len(active) == 1
    assert active[0]["title"] == "Llamar"
    assert repository.lead(lead_id)["probability"] == 75


def test_quote_requires_discount_approval_and_converts_to_order(sales):
    database, repository = sales
    product_id = database.save_catalog_product(name="Kit de stickers", price=1000)
    lead_id = repository.create_lead(client_name="Carla", whatsapp="114455")
    quote_id = repository.create_quote(
        client_name="Carla", whatsapp="114455", lead_id=lead_id,
        discount_percent=15, discount_reason="Cliente mayorista",
        items=[{
            "product_id": product_id, "product_name": "Kit de stickers",
            "quantity": 2, "unit_price": 1000,
        }],
    )

    quote = repository.quote(quote_id)
    assert quote["total"] == 1700
    assert quote["approval_status"] == "Pendiente"
    assert repository.lead(lead_id)["stage"] == "Presupuestada"
    with pytest.raises(ValueError, match="aprobación"):
        repository.convert_quote_to_order(quote_id, database.create_order)

    repository.approve_quote(quote_id, "Responsable comercial")
    order_id = repository.convert_quote_to_order(quote_id, database.create_order)
    order = database.order(order_id)
    assert order["budget_total"] == 1700
    assert repository.quote(quote_id)["converted_order_id"] == order_id
    assert repository.lead(lead_id)["stage"] == "Ganada"
    assert repository.convert_quote_to_order(quote_id, database.create_order) == order_id


def test_receivables_deliveries_metrics_and_customer_segments(sales):
    database, repository = sales
    first = database.create_order("Cliente frecuente", "119999", jobs=[{"title": "Producto", "quantity": 1, "subtotal": 5000}])
    second = database.create_order("Cliente frecuente", "119999", jobs=[{"title": "Producto", "quantity": 2, "subtotal": 8000}])
    database.register_order_payment(first, 2000, "Transferencia")

    rows = repository.receivables()
    first_row = next(item for item in rows if item["order_id"] == first)
    assert first_row["pending"] == 3000
    assert "pedido #" in first_row["message"]

    repository.upsert_delivery(
        first, method="Mensajería", address="Calle 123", city="Buenos Aires",
        shipping_cost=1500, scheduled_at="2026-08-20 15:00", status="Coordinada",
    )
    delivery = repository.delivery(first)
    assert delivery["address"] == "Calle 123"
    assert delivery["shipping_cost"] == 1500

    metrics = repository.dashboard_metrics()
    assert metrics["orders"] == 2
    assert metrics["sales"] == 13000
    assert metrics["collected"] == 2000
    assert metrics["outstanding"] == 11000
    assert metrics["repeat_customers"] == 1
    customer = repository.customer_segments()[0]
    assert customer["order_count"] == 2
    assert customer["segment"] in {"Recurrente", "Inactivo", "VIP"}


def test_policies_promotions_and_standalone_catalog_export(sales, tmp_path):
    database, repository = sales
    image = tmp_path / "product.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    database.save_catalog_product(
        name="Plancha personalizada", price=6000,
        description="Diseños elegidos por el cliente", category="Stickers", image_path=str(image),
    )
    repository.save_settings({
        "max_discount_without_approval": "12", "quote_valid_days": "10",
        "business_whatsapp": "+54 9 11 2345-6789",
    })
    repository.save_promotion(code="VUELVE10", name="Reactivación", discount_percent=10, audience="Inactivo")

    assert repository.setting("max_discount_without_approval") == "12"
    assert repository.promotions()[0]["code"] == "VUELVE10"

    quote_id = repository.create_quote(
        client_name="Cliente promo", promotion_code="VUELVE10",
        items=[{"product_name": "Plancha personalizada", "quantity": 1, "unit_price": 6000}],
    )
    assert repository.quote(quote_id)["total"] == 5400
    repository.revise_quote(
        quote_id, client_name="Cliente promo", promotion_code="VUELVE10",
        valid_until="2026-09-30", discount_percent=0,
        items=[{"product_name": "Plancha personalizada", "quantity": 2, "unit_price": 6000}],
    )
    revised = repository.quote(quote_id)
    assert revised["version"] == 2
    assert revised["total"] == 10800
    assert database.connection.execute(
        "SELECT COUNT(*) FROM sales_quote_versions WHERE quote_id=?", (quote_id,)
    ).fetchone()[0] == 2

    output = repository.export_catalog_html(tmp_path / "catalogo.html")
    content = output.read_text(encoding="utf-8")
    assert "Plancha personalizada" in content
    assert "Diseños elegidos por el cliente" in content
    assert "data:image/png;base64" in content
    assert "https://wa.me/5491123456789" in content
    assert output == Path(tmp_path / "catalogo.html")
