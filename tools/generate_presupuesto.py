import csv
import sys
from decimal import Decimal, ROUND_HALF_UP

def read_prices(path):
    prices = {}
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            key = (r['producto'].strip().lower(), r.get('tamaño','').strip().lower(), r.get('material','').strip().lower())
            prices[key] = Decimal(r['precio']).quantize(Decimal('0.01'))
    return prices

def read_order(path):
    items = []
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            items.append({
                'producto': r['producto'].strip(),
                'cantidad': int(r.get('cantidad',1)),
                'tamaño': r.get('tamaño','').strip(),
                'material': r.get('material','').strip(),
                'nota': r.get('nota','').strip()
            })
    return items


def format_money(d):
    return f"${d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"


def generate_quote(prices_path, order_path, seña='0', entrega='Retiro'):
    prices = read_prices(prices_path)
    order = read_order(order_path)
    lines = []
    total = Decimal('0')
    for it in order:
        key = (it['producto'].lower(), it['tamaño'].lower(), it['material'].lower())
        price = prices.get(key)
        if price is None:
            # try matching by product only
            key2 = (it['producto'].lower(), '', '')
            price = prices.get(key2)
        if price is None:
            price = Decimal('0')
        subtotal = price * it['cantidad']
        total += subtotal
        lines.append((it['producto'], it['cantidad'], it['tamaño'], it['material'], format_money(price), format_money(subtotal)))

    # print message
    print('📋 Presupuesto Doccione')
    print()
    print('• Productos:')
    for p,c,t,m,pr,sub in lines:
        print(f"  - {p} — Cantidad: {c}, Tamaño: {t or '-'}, Material: {m or '-'}, Precio unitario: {pr}, Subtotal: {sub}")
    print()
    print(f'• Precios totales: {format_money(total)}')
    print()
    print(f'⏳ Tiempo de entrega: 3-5 días hábiles (estimado)')
    print(f'💳 Seña: {seña}')
    print(f'📦 Entrega: {entrega}')
    print()
    print('¡Gracias por elegir Doccione! Cualquier modificación en medidas, cantidad o material actualiza el presupuesto.')


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print('Uso: python generate_presupuesto.py precios.csv pedido.csv [seña] [Retiro|Envío]')
        sys.exit(1)
    precios_csv = sys.argv[1]
    pedido_csv = sys.argv[2]
    seña = sys.argv[3] if len(sys.argv) > 3 else '0'
    entrega = sys.argv[4] if len(sys.argv) > 4 else 'Retiro'
    generate_quote(precios_csv, pedido_csv, seña, entrega)
