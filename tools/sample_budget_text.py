import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from app.database.database import ImageDatabase

DB = root / "visionvault.db"

def fmt(v: float) -> str:
    return f"$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def build_text(material: str, size: str, quantity: int, discount: float, extra: float, title: str = "Producto") -> str:
    db = ImageDatabase(DB)
    rule = db.suggest_price(material, size, quantity)
    subtotal_base = float(rule["suggested_subtotal"]) if rule and rule.get("suggested_subtotal") else 0.0
    unit_price = subtotal_base / quantity if quantity and subtotal_base else 0.0
    precio_unitario = fmt(unit_price) if unit_price else "-"
    base_text = fmt(subtotal_base)
    extra_text = fmt(extra) if extra else "$ 0,00"
    discount_text = f"{discount:g}%" if discount else "0%"
    final_total = max(0.0, subtotal_base - subtotal_base * discount / 100 + extra)
    final_total_text = fmt(final_total)
    detail = rule.get("calculation_detail") if rule else ""

    lines = [
        "📋 Presupuesto Doccione",
        "",
        "• Producto:",
        f"  - {title}",
        f"    • Material: {material or '-'}",
        f"    • Tamaño: {size or '-'}",
        f"    • Cantidad: {quantity}",
        f"    • Precio unitario: {precio_unitario}",
        f"    • Subtotal base: {base_text}",
        f"    • Descuento aplicado: {discount_text}",
        f"    • Servicios extra: {extra_text}",
        "",
        f"Total final: {final_total_text}",
        "",
        f"Precio sugerido: {detail}" if detail else "Precio sugerido: sin detalle disponible",
        "",
        "⏳ Tiempo de entrega: 3-5 días hábiles (estimado)",
        "💳 Seña: 0",
        "📦 Entrega: Retiro",
        "",
        "¡Gracias por elegir Doccione! Cualquier modificación en medidas, cantidad o material actualiza el presupuesto.",
    ]
    return "\n".join(lines)

if __name__ == "__main__":
    examples = [
        ("Resina 3D Premium", "29cm", 1, 0, 0, "Test Resina 29cm"),
        ("Vinilo Full Color HD", "25cm", 2, 10, 500, "Vinilo 25cm x2"),
    ]
    for material, size, quantity, discount, extra, title in examples:
        print(build_text(material, size, quantity, discount, extra, title))
        print("\n---\n")
