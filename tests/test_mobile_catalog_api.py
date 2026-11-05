from pathlib import Path

from app.api.mobile_jobs import MobileJobsHandler
from app.database.database import ImageDatabase
from app.events.event_repository import EventRepository


def _handler(database: ImageDatabase) -> MobileJobsHandler:
    """Construye solo la parte sin HTTP del handler para probar el catálogo."""
    handler = object.__new__(MobileJobsHandler)
    handler.event_repo = EventRepository(database.connection)
    return handler


def test_mobile_catalog_exposes_only_explicitly_public_reusable_designs(tmp_path: Path):
    database = ImageDatabase(tmp_path / "catalog.db")
    now = 1.0
    database.connection.execute(
        """INSERT INTO images(path, name, extension, size, modified, category, is_reusable, is_private)
           VALUES (?, ?, '.png', 1, ?, ?, ?, ?)""",
        ("C:/designs/public.png", "Diseño público", now, "Anime", 1, 0),
    )
    database.connection.execute(
        """INSERT INTO images(path, name, extension, size, modified, category, is_reusable, is_private)
           VALUES (?, ?, '.png', 1, ?, ?, ?, ?)""",
        ("C:/designs/private.png", "Diseño privado", now, "Anime", 1, 1),
    )
    database.connection.execute(
        """INSERT INTO images(path, name, extension, size, modified, category, is_reusable, is_private)
           VALUES (?, ?, '.png', 1, ?, ?, ?, ?)""",
        ("C:/designs/not-reusable.png", "No autorizado", now, "Anime", 0, 0),
    )
    database.connection.execute("INSERT INTO tags(name) VALUES ('dragón')")
    database.connection.execute(
        "INSERT INTO image_tags(image_path, tag_id) VALUES (?, 1)",
        ("C:/designs/public.png",),
    )
    database.connection.commit()
    database.save_app_setting("mobile_catalog.access_mode", "selected")

    handler = _handler(database)
    rows = handler._catalog_query()

    assert [row["name"] for row in rows] == ["Diseño público"]
    payload = handler._catalog_payload(rows[0])
    assert "C:/" not in str(payload)
    assert payload["tags"] == ["dragón"]
    assert payload["visible_width"] == 0
    assert payload["visible_height"] == 0
    assert "render=2" in payload["preview_url"]
    assert handler._catalog_design_by_id(payload["id"])["path"] == "C:/designs/public.png"

    database.save_app_setting("mobile_catalog.access_mode", "all")
    assert {row["name"] for row in handler._catalog_query()} == {
        "Diseño público", "Diseño privado", "No autorizado",
    }


def test_mobile_catalog_query_pages_before_building_the_payload(tmp_path: Path):
    database = ImageDatabase(tmp_path / "catalog_paging.db")
    for index in range(6):
        database.connection.execute(
            """INSERT INTO images(path, name, extension, size, modified)
               VALUES (?, ?, '.png', 1, ?)""",
            (f"C:/designs/{index}.png", f"Diseño {index}", float(index)),
        )
    database.connection.commit()

    page = _handler(database)._catalog_query(limit=2, offset=2)

    assert [row["name"] for row in page] == ["Diseño 2", "Diseño 3"]


def test_catalog_payload_primes_constant_time_design_lookup(tmp_path: Path):
    database = ImageDatabase(tmp_path / "catalog_lookup.db")
    database.connection.execute(
        """INSERT INTO images(path, name, extension, size, modified)
           VALUES ('C:/designs/fast.png', 'Rápido', '.png', 1, 1)"""
    )
    database.connection.commit()
    handler = _handler(database)
    payload = handler._catalog_payload(handler._catalog_query()[0])

    handler._catalog_query = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("No debe recorrer el banco para resolver una miniatura")
    )

    assert handler._catalog_design_by_id(payload["id"])["name"] == "Rápido"


def test_mobile_catalog_quote_ignores_phone_discount_and_uses_studio_rules(tmp_path: Path):
    database = ImageDatabase(tmp_path / "catalog_quote.db")
    database.connection.execute(
        """INSERT INTO images(path, name, extension, size, modified, category, is_reusable, is_private)
           VALUES (?, ?, '.png', 1, 1, 'Anime', 1, 0)""",
        ("C:/designs/sale.png", "Diseño de venta"),
    )
    database.connection.execute(
        """INSERT INTO price_rules(material, size, min_quantity, price, active, price_mode, pack_quantity)
           VALUES ('Vinilo', '5cm', 1, 250, 1, 'unitario', 1)"""
    )
    database.connection.commit()
    handler = _handler(database)
    design_id = handler._catalog_payload(handler._catalog_query()[0])["id"]

    quote, error = handler._catalog_quote(
        [{"design_id": design_id, "quantity": 3, "material": "Vinilo", "size": ""}], 10,
    )

    assert error is None
    assert quote is not None
    assert quote["subtotal"] == 750
    assert quote["discount_amount"] == 0
    assert quote["total"] == 750
    assert quote["warnings"] == []
    assert quote["items"][0]["size"] == "5cm"


def test_mobile_catalog_applies_studio_discount_only_at_rule_quantity(tmp_path: Path):
    database = ImageDatabase(tmp_path / "catalog_quantity_discount.db")
    database.connection.execute(
        """INSERT INTO images(path, name, extension, size, modified, category, is_reusable, is_private)
           VALUES (?, ?, '.png', 1, 1, 'Anime', 1, 0)""",
        ("C:/designs/quantity-sale.png", "Diseño con descuento"),
    )
    database.connection.execute(
        """INSERT INTO price_rules(
               material, size, min_quantity, price, discount_percent, active,
               price_mode, pack_quantity
           ) VALUES ('Vinilo', '5cm', 1, 250, 0, 1, 'unitario', 1)"""
    )
    database.connection.execute(
        """INSERT INTO price_rules(
               material, size, min_quantity, price, discount_percent, active,
               price_mode, pack_quantity
           ) VALUES ('Vinilo', '5cm', 10, 250, 10, 1, 'unitario', 1)"""
    )
    database.connection.commit()
    handler = _handler(database)
    design_id = handler._catalog_payload(handler._catalog_query()[0])["id"]

    below_threshold, error = handler._catalog_quote([
        {"design_id": design_id, "quantity": 9, "material": "Vinilo", "size": "5cm"}
    ])
    assert error is None
    assert below_threshold is not None
    assert below_threshold["discount_amount"] == 0
    assert below_threshold["total"] == 2250

    qualifying, error = handler._catalog_quote([
        {"design_id": design_id, "quantity": 10, "material": "Vinilo", "size": "5cm"}
    ])
    assert error is None
    assert qualifying is not None
    assert qualifying["discount_percent"] == 10
    assert qualifying["discount_amount"] == 250
    assert qualifying["total"] == 2250
    assert qualifying["items"][0]["discount_percent"] == 10


def test_mobile_sticker_quote_uses_the_standard_a4_price_rule(tmp_path: Path):
    database = ImageDatabase(tmp_path / "sticker_quote.db")

    quote, error = _handler(database)._sticker_quote("Plancha A4", 4)

    assert error is None
    assert quote is not None
    assert quote["matched"] is True
    assert quote["total"] == 5000


def test_mobile_product_catalog_uses_active_studio_products(tmp_path: Path):
    database = ImageDatabase(tmp_path / "products.db")
    now = "2026-01-01T00:00:00"
    database.connection.execute("INSERT INTO products(code, name, active, created_at, updated_at) VALUES ('copia', 'Fotocopia', 1, ?, ?)", (now, now))
    database.connection.execute("INSERT INTO products(code, name, active, created_at, updated_at) VALUES ('oculto', 'Oculto', 0, ?, ?)", (now, now))
    database.connection.commit()
    handler = _handler(database)
    rows = handler.event_repo.conn.execute("SELECT code, name FROM products WHERE active = 1 ORDER BY name").fetchall()

    assert {row["code"] for row in rows} >= {"copia"}
