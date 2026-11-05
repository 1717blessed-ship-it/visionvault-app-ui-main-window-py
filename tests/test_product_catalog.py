from app.database.database import ImageDatabase
from app.ui.product_catalog import parse_price


def test_catalog_product_crud_keeps_information_price_and_image(tmp_path):
    database = ImageDatabase(tmp_path / "catalog.db")
    image = tmp_path / "sample.png"
    image.write_bytes(b"image")

    product_id = database.save_catalog_product(
        name="Kit de stickers",
        price=2500,
        description="Diez stickers personalizados.",
        category="Stickers",
        image_path=str(image),
    )

    product = database.catalog_product(product_id)
    assert product is not None
    assert product["name"] == "Kit de stickers"
    assert product["description"] == "Diez stickers personalizados."
    assert product["category"] == "Stickers"
    assert product["image_path"] == str(image)
    assert product["price"] == 2500
    assert product["price_rule_count"] == 1

    assert database.update_catalog_product(
        product_id,
        name="Kit premium",
        price=3200,
        description="Terminación premium.",
        category="Promociones",
        image_path=str(image),
    )
    updated = database.catalog_product(product_id)
    assert updated is not None
    assert updated["name"] == "Kit premium"
    assert updated["price"] == 3200
    base_rule = database.connection.execute(
        "SELECT material, price FROM price_rules WHERE catalog_key = ?",
        (f"product_card_{product_id}",),
    ).fetchone()
    assert tuple(base_rule) == ("Kit premium", 3200)

    assert database.set_catalog_product_active(product_id, False)
    assert all(item["id"] != product_id for item in database.catalog_products())
    assert any(
        item["id"] == product_id
        for item in database.catalog_products(include_inactive=True)
    )


def test_catalog_search_and_unique_codes(tmp_path):
    database = ImageDatabase(tmp_path / "catalog.db")
    first = database.save_catalog_product(name="Taza mágica", price=8000, category="Regalos")
    second = database.save_catalog_product(name="Taza mágica", price=9000, category="Premium")

    first_row = database.catalog_product(first)
    second_row = database.catalog_product(second)
    assert first_row["code"] == "taza_magica"
    assert second_row["code"] == "taza_magica_2"
    assert [item["id"] for item in database.catalog_products("premium")] == [second]


def test_catalog_product_rename_is_reflected_in_linked_order_jobs(tmp_path):
    database = ImageDatabase(tmp_path / "catalog.db")
    product_id = database.save_catalog_product(name="Taza clásica", price=8000)
    order_id = database.create_order(
        "Cliente",
        jobs=[{"title": "Taza clásica", "product_id": product_id, "quantity": 1, "subtotal": 8000}],
    )

    database.update_catalog_product(product_id, name="Taza premium", price=9200)

    job = database.connection.execute(
        "SELECT title, subtotal FROM order_jobs WHERE order_id = ?", (order_id,)
    ).fetchone()
    assert tuple(job) == ("Taza premium", 8000)


def test_parse_price_accepts_common_local_formats():
    assert parse_price("$ 1.250,50") == 1250.50
    assert parse_price("1,250.50") == 1250.50
    assert parse_price("2500") == 2500
