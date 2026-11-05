"""Script de diagnostico para mostrar distribuciones especificas."""

from app.planchas.poster_packing import (
    PaperSize,
    SizePolicy,
    Orientation,
    MarginConfig,
    MixedPosterItem,
    pack_mixed_posters,
)


def print_distribution(title: str, result):
    print(f"\n{'='*60}")
    print(f"{title}")
    print(f"{'='*60}")
    print(f"Hojas: {result.total_pages}")
    print(f"Elementos colocados: {result.total_placements}")
    print(f"Ocupacion total: {result.total_utilization_percent:.1f}%")
    print(f"Factor de escala: {result.scale_factor:.3f}")

    if result.warnings:
        print(f"Advertencias: {result.warnings}")

    for i, page in enumerate(result.pages):
        print(f"\n--- Hoja {i+1} ---")
        print(f"Ocupacion: {page.utilization_percent:.1f}%")
        print(f"Elementos: {len(page.placements)}")
        for j, placement in enumerate(page.placements):
            print(f"  {j+1}. {placement.item_id}: ({placement.x_mm:.1f}, {placement.y_mm:.1f}) "
                  f"{placement.width_mm:.1f}x{placement.height_mm:.1f}mm "
                  f"[rotado={placement.rotation}]")


# 1 A5 + 2 A6 sin margenes
print("TEST 1: 1 A5 + 2 A6 sin margenes")
items_1 = [
    MixedPosterItem.from_preset(PaperSize.A5, id="a5_1", source_path="/fake/a5.png", quantity=1),
    MixedPosterItem.from_preset(PaperSize.A6, id="a6_1", source_path="/fake/a6.png", quantity=1),
    MixedPosterItem.from_preset(PaperSize.A6, id="a6_2", source_path="/fake/a6_2.png", quantity=1),
]
no_margins = MarginConfig(top=0, bottom=0, left=0, right=0, horizontal_gap=0, vertical_gap=0)
result_1 = pack_mixed_posters(items_1, margins=no_margins, size_policy=SizePolicy.EXACTO)
print_distribution("1 A5 + 2 A6 (sin margenes)", result_1)

# 3 A6 + 2 A7 sin margenes
print("\n\nTEST 2: 3 A6 + 2 A7 sin margenes")
items_2 = [
    MixedPosterItem.from_preset(PaperSize.A6, id=f"a6_{i}", source_path=f"/fake/a6_{i}.png", quantity=1)
    for i in range(3)
] + [
    MixedPosterItem.from_preset(PaperSize.A7, id=f"a7_{i}", source_path=f"/fake/a7_{i}.png", quantity=1)
    for i in range(2)
]
result_2 = pack_mixed_posters(items_2, margins=no_margins, size_policy=SizePolicy.EXACTO)
print_distribution("3 A6 + 2 A7 (sin margenes)", result_2)

# Con margenes estandar
print("\n\nTEST 3: 1 A5 + 2 A6 con margenes estandar")
standard_margins = MarginConfig(top=5, bottom=5, left=5, right=5, horizontal_gap=2, vertical_gap=2)
result_3 = pack_mixed_posters(items_1, margins=standard_margins, size_policy=SizePolicy.EXACTO)
print_distribution("1 A5 + 2 A6 (con margenes)", result_3)

print("\n\nTEST 4: 3 A6 + 2 A7 con margenes estandar")
result_4 = pack_mixed_posters(items_2, margins=standard_margins, size_policy=SizePolicy.EXACTO)
print_distribution("3 A6 + 2 A7 (con margenes)", result_4)

# Politica AJUSTAR
print("\n\nTEST 5: Politica AJUSTAR_AL_AREA_IMPRIMIBLE")
result_5 = pack_mixed_posters(items_1, margins=standard_margins, size_policy=SizePolicy.AJUSTAR_AL_AREA_IMPRIMIBLE)
print_distribution("1 A5 + 2 A6 (AJUSTAR)", result_5)
