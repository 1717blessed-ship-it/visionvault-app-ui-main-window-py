from pathlib import Path

from app.database.database import ImageDatabase


def test_visual_products_groups_sizes_and_uses_any_available_image(tmp_path: Path):
    db = ImageDatabase(tmp_path / "visual-products.db")
    db.save_price_rule("Stickers - Vinilo", "5cm", 1, 100)
    db.save_price_rule("Stickers - Vinilo", "10cm", 1, 200, image_path="C:/images/stickers.png")
    products = db.visual_products()
    sticker = next(item for item in products if item["material"] == "Stickers - Vinilo")
    assert sticker["image_path"] == "C:/images/stickers.png"
    assert sticker["sizes"] == ["5cm", "10cm"]
