"""Reglas reales de venta y snapshots comerciales."""
from app.database.database import ImageDatabase


def test_full_color_quantity_tiers_and_program(tmp_path):
    db = ImageDatabase(tmp_path / "commercial.db")
    expected = {1: 400, 5: 400, 7: 400, 10: 350, 20: 300, 100: 280, 200: 260, 500: 240, 1000: 220}
    for quantity, unit in expected.items():
        result = db.resolve_commercial_price(product_code="sticker_troquelado", material="Vinilo Full Color HD", size="5 cm", quantity=quantity)
        assert result["matched"] and result["unit_price"] == unit
        assert result["subtotal"] == unit * quantity
    result = db.resolve_commercial_price(product_code="sticker_troquelado", material="Vinilo Full Color HD", size="5cm", quantity=100, price_list_code="programa_emprendedor_doccione")
    assert result["unit_price"] == 260 and result["subtotal"] == 26000
    assert result["preparation_limit"] == 10
    db.connection.close()


def test_cards_planchas_and_doming_pack_suggestion(tmp_path):
    db = ImageDatabase(tmp_path / "commercial.db")
    for quantity, expected in ((20, 5000), (24, 4800), (80, 12000)):
        r = db.resolve_commercial_price(product_code="tarjeta_personalizada", material="Tarjeta personalizada", quantity=quantity)
        assert r["subtotal"] == expected
    r = db.resolve_commercial_price(product_code="plancha_a4", material="Vinilo especial", size="A4", quantity=3)
    assert r["fixed_total"] == 7000
    r = db.resolve_commercial_price(product_code="sticker_doming", material="Resina 3D Premium", size="5cm", quantity=10)
    assert r["subtotal"] == 15000
    assert r["pack_suggestion"]["total"] == 13000
    assert r["pack_suggestion"]["savings"] == 2000
    db.connection.close()


def test_unique_design_plancha_price_grows_with_quantity(tmp_path):
    db = ImageDatabase(tmp_path / "commercial.db")
    result = db.suggest_price("Vinilo estándar", "A4", 7)
    assert result["suggested_subtotal"] == 35000
    assert result["price_mode"] == "unitario"
    db.connection.close()


def test_plancha_titles_resolve_to_distinct_prices(tmp_path):
    db = ImageDatabase(tmp_path / "plancha_aliases.db")
    assert db.suggest_price("Plancha Diseño Único", "A4", 1)["suggested_subtotal"] == 5000
    assert db.suggest_price("Plancha Personalizada", "A4", 1)["suggested_subtotal"] == 6000
    assert db.suggest_price("Plancha Personalizada 5 cm", "A4", 1)["suggested_subtotal"] == 6000
    assert db.suggest_price("Plancha Personalizada Mixta", "A4", 1)["suggested_subtotal"] == 6000
    assert db.suggest_price("Plancha Doccione", "A4", 1)["suggested_subtotal"] == 5000
    db.connection.close()


def test_unique_design_plancha_multiplies_before_general_discount(tmp_path):
    db = ImageDatabase(tmp_path / "plancha_unit_price.db")
    result = db.suggest_price("Plancha Diseño Único", "A4", 2)

    assert result["price_mode"] == "unitario"
    assert result["suggested_subtotal"] == 10000
    # El formulario aplica luego el descuento general sobre este subtotal.
    assert result["suggested_subtotal"] * 0.8 == 8000
    db.connection.close()


def test_quantity_discount_details_compares_tier_against_list_price(tmp_path):
    db = ImageDatabase(tmp_path / "commercial.db")
    details = db.quantity_discount_details("Póster plastificado", "A4 (21 × 29,7 cm)", 12)

    assert details is not None
    assert details["list_unit_price"] == 2500
    assert details["tier_unit_price"] == 2300
    assert details["discount_percent"] == 8
    assert details["savings"] == 2400
    assert details["tier_total"] == 27600
    db.connection.close()


def test_confirmed_snapshot_is_not_recalculated(tmp_path):
    db = ImageDatabase(tmp_path / "commercial.db")
    order_id = db.create_order("Cliente", jobs=[{"title": "Sticker", "material": "Vinilo Full Color HD", "size": "5cm", "quantity": 1, "subtotal": 400}])
    job = db.order_jobs(order_id)[0]
    r = db.resolve_commercial_price(product_code="sticker_troquelado", material="Vinilo Full Color HD", size="5cm", quantity=1)
    db.save_order_job_price_snapshot(job["id"], r)
    db.connection.execute("UPDATE price_rules SET price = 450 WHERE id = ?", (r["rule_id"],))
    db.connection.commit()
    stored = db.order_jobs(order_id)[0]
    assert stored["unit_price_snapshot"] == 400
    assert db.resolve_commercial_price(product_code="sticker_troquelado", material="Vinilo Full Color HD", size="5cm", quantity=1)["unit_price"] == 450
    db.connection.close()
