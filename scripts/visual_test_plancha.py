from PIL import Image, ImageDraw
from app.planchas.model import (
    A4_WIDTH_CM,
    A4_HEIGHT_CM,
    DEFAULT_EXTRA_LAYOUT_CM,
    DEFAULT_MARGIN_CM,
    PlanchaProject,
    PlanchaItem,
    geometric_pack,
    pack_layout,
    Rect,
    intersects,
    printable_area,
    effective_layout_size,
    fits_in_printable_area,
    validate_no_overlaps,
    validate_package_geometry,
)


SCALE = 12  # pixels per cm
MARGIN_PIXELS = 10


def cm_to_px(value_cm: float) -> int:
    return int(round(value_cm * SCALE))


def make_canvas():
    width = cm_to_px(A4_WIDTH_CM) + MARGIN_PIXELS * 2
    height = cm_to_px(A4_HEIGHT_CM) + MARGIN_PIXELS * 2
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    # draw printable area
    left = MARGIN_PIXELS + cm_to_px(DEFAULT_MARGIN_CM)
    top = MARGIN_PIXELS + cm_to_px(DEFAULT_MARGIN_CM)
    right = left + cm_to_px(A4_WIDTH_CM - DEFAULT_MARGIN_CM * 2)
    bottom = top + cm_to_px(A4_HEIGHT_CM - DEFAULT_MARGIN_CM * 2)
    draw.rectangle([left, top, right, bottom], outline="#222222")
    return img, draw, left, top


def draw_classic(placements, filename):
    img, draw, left_offset, top_offset = make_canvas()
    for item in placements:
        x = left_offset + cm_to_px(item.x_cm - DEFAULT_MARGIN_CM)
        y = top_offset + cm_to_px(item.y_cm - DEFAULT_MARGIN_CM)
        w = cm_to_px(item.width_cm)
        h = cm_to_px(item.height_cm)
        draw.rectangle([x, y, x + w, y + h], outline="#0b84ff", width=2)
        # fill a light color
        draw.rectangle([x + 1, y + 1, x + w - 1, y + h - 1], outline=None, fill="#dbeeff")
    img.save(filename)


def draw_geometric(result, filename, free_rects_filename=None):
    img, draw, left_offset, top_offset = make_canvas()
    # draw reserved layout rectangles (layout_width/height)
    for p in result.placed:
        lx = left_offset + cm_to_px(p["x_cm"] - DEFAULT_MARGIN_CM)
        ly = top_offset + cm_to_px(p["y_cm"] - DEFAULT_MARGIN_CM)
        lw = cm_to_px(p["layout_width_cm"])
        lh = cm_to_px(p["layout_height_cm"])
        draw.rectangle([lx, ly, lx + lw, ly + lh], outline="#ff9900", width=2)
        # El editor dibuja el corte desde el origen de la reserva. El extra
        # queda como espacio de seguridad a la derecha y abajo, nunca cambia
        # el tamaño visual/físico del sticker.
        cut_w = cm_to_px(p["cut_width_cm"])
        cut_h = cm_to_px(p["cut_height_cm"])
        inner_x = lx
        inner_y = ly
        draw.rectangle([inner_x, inner_y, inner_x + cut_w, inner_y + cut_h], outline="#2ea44f", width=2, fill="#e6ffee")

    if free_rects_filename:
        # overlay free rects in semi-transparent red
        fr_img = img.copy().convert("RGBA")
        fr_draw = ImageDraw.Draw(fr_img)
        for fr in result.free_rectangles:
            fx = left_offset + cm_to_px(fr.x - DEFAULT_MARGIN_CM)
            fy = top_offset + cm_to_px(fr.y - DEFAULT_MARGIN_CM)
            fw = cm_to_px(fr.width)
            fh = cm_to_px(fr.height)
            fr_draw.rectangle([fx, fy, fx + fw, fy + fh], outline="#ff4444", width=1, fill=(255, 68, 68, 48))
        fr_img.save(free_rects_filename)

    img.save(filename)


def draw_irregular_shell(filename, source_filename):
    """Referencia visual para la futura fase de packing por máscara alfa.

    El rectángulo naranja es el bounding box reservado; la caracola conserva
    transparencias deliberadas dentro de ese rectángulo.
    """
    shell = Image.new("RGBA", (900, 700), (0, 0, 0, 0))
    draw_shell = ImageDraw.Draw(shell)
    # Una silueta irregular, intencionalmente lejos de un rectángulo lleno.
    draw_shell.polygon(
        [(80, 520), (170, 270), (330, 105), (560, 75), (760, 230),
         (790, 440), (650, 570), (420, 640), (190, 610)],
        fill=(222, 157, 91, 255), outline=(111, 66, 39, 255), width=14,
    )
    draw_shell.ellipse((230, 130, 650, 550), fill=(247, 203, 129, 255), outline=(111, 66, 39, 255), width=14)
    draw_shell.arc((290, 185, 590, 485), start=25, end=385, fill=(135, 76, 51, 255), width=22)
    draw_shell.arc((350, 245, 530, 425), start=25, end=385, fill=(135, 76, 51, 255), width=20)
    draw_shell.ellipse((410, 305, 470, 365), fill=(135, 76, 51, 255))
    shell.save(source_filename)

    img, draw, left_offset, top_offset = make_canvas()
    x_cm, y_cm, width_cm, height_cm = 4.0, 6.0, 12.0, 10.0
    x = left_offset + cm_to_px(x_cm - DEFAULT_MARGIN_CM)
    y = top_offset + cm_to_px(y_cm - DEFAULT_MARGIN_CM)
    w, h = cm_to_px(width_cm), cm_to_px(height_cm)
    draw.rectangle([x, y, x + w, y + h], outline="#ff9900", width=3)
    resized_shell = shell.resize((w, h), Image.Resampling.LANCZOS)
    img.paste(resized_shell, (x, y), resized_shell)
    draw.text((x, y - 15), "bounding box reservado: 12 x 10 cm", fill="#7a3e15")
    img.save(filename)


def item_label(item):
    return f"{item_cut_width(item):g}x{item_cut_height(item):g}"


def item_cut_width(item):
    return float(item["cut_width_cm"] if isinstance(item, dict) else item.width_cm)


def item_cut_height(item):
    return float(item["cut_height_cm"] if isinstance(item, dict) else item.height_cm)


def audit_classic_safety(items):
    """Audita las posiciones clásicas sin alterar su distribución."""
    printable = printable_area(DEFAULT_MARGIN_CM)
    layouts = [
        Rect(item.x_cm, item.y_cm, item.width_cm + DEFAULT_EXTRA_LAYOUT_CM, item.height_cm + DEFAULT_EXTRA_LAYOUT_CM)
        for item in items
    ]
    valid = []
    violations = []
    for index, (item, layout) in enumerate(zip(items, layouts)):
        in_bounds = (
            layout.x >= printable.x and layout.y >= printable.y
            and layout.right <= printable.right and layout.bottom <= printable.bottom
        )
        overlaps = [other for other, candidate in enumerate(layouts) if other != index and intersects(layout, candidate)]
        if in_bounds and not overlaps:
            valid.append(item)
        else:
            violations.append((item, in_bounds, overlaps))
    return valid, violations


def hybrid_order(items):
    """Diagnóstico: grande, pequeño, siguiente grande, siguiente pequeño."""
    ordered = sorted(items, key=lambda item: (item_cut_width(item) * item_cut_height(item), max(item_cut_width(item), item_cut_height(item))), reverse=True)
    mixed = []
    while ordered:
        mixed.append(ordered.pop(0))
        if ordered:
            mixed.append(ordered.pop())
    return mixed


def print_strategy_results(items):
    area = lambda item: item_cut_width(item) * item_cut_height(item)
    strategies = {
        "area_desc": sorted(items, key=area, reverse=True),
        "longest_side_desc": sorted(items, key=lambda item: max(item_cut_width(item), item_cut_height(item)), reverse=True),
        "area_asc": sorted(items, key=area),
        "shortest_side_asc": sorted(items, key=lambda item: min(item_cut_width(item), item_cut_height(item))),
        "hybrid_large_small": hybrid_order(items),
    }
    print("\nMAXRECTS: órdenes diagnósticas (sin cambiar el motor)")
    for name, ordered in strategies.items():
        result = pack_layout(ordered, strategy=name, preserve_order=True, extra_cm=DEFAULT_EXTRA_LAYOUT_CM, allow_rotation=True)
        outside = ", ".join(item_label(item) for item in result.overflow) or "ninguno"
        print(
            f"{name}: placed={len(result.placed)} overflow={len(result.overflow)} "
            f"cut_occ={result.cut_occupancy:.4f} packing_occ={result.packing_occupancy:.4f} outside=[{outside}]"
        )
    return strategies


PAGE_STRATEGIES = ("area_desc", "longest_side_desc", "area_asc", "shortest_side_asc")


def ordered_items(items, strategy):
    area = lambda item: item_cut_width(item) * item_cut_height(item)
    if strategy == "area_desc":
        return sorted(items, key=area, reverse=True)
    if strategy == "longest_side_desc":
        return sorted(items, key=lambda item: max(item_cut_width(item), item_cut_height(item)), reverse=True)
    if strategy == "area_asc":
        return sorted(items, key=area)
    if strategy == "shortest_side_asc":
        return sorted(items, key=lambda item: min(item_cut_width(item), item_cut_height(item)))
    raise ValueError(strategy)


def physically_impossible(items):
    possible, impossible = [], []
    for item in items:
        layout = effective_layout_size(item_cut_width(item), item_cut_height(item), DEFAULT_EXTRA_LAYOUT_CM)
        (possible if fits_in_printable_area(layout, margin_cm=DEFAULT_MARGIN_CM, allow_rotation=True) else impossible).append(item)
    return possible, impossible


def pack_all_pages(items, strategy):
    """Ejecuta una estrategia con páginas nuevas hasta agotar el lote."""
    remaining, impossible = physically_impossible(list(items))
    pages = []
    while remaining:
        if strategy == "best_of_strategies_per_page":
            candidates = [
                pack_layout(ordered_items(remaining, candidate), strategy=candidate, preserve_order=True,
                            extra_cm=DEFAULT_EXTRA_LAYOUT_CM, allow_rotation=True)
                for candidate in PAGE_STRATEGIES
            ]
            result = max(candidates, key=lambda candidate: (
                len(candidate.placed), candidate.cut_occupancy, candidate.packing_occupancy,
            ))
        else:
            result = pack_layout(ordered_items(remaining, strategy), strategy=strategy, preserve_order=True,
                                 extra_cm=DEFAULT_EXTRA_LAYOUT_CM, allow_rotation=True)
        if not result.placed:
            # Protección ante una regresión: nunca iterar sobre el mismo overflow.
            impossible.extend(result.overflow)
            break
        pages.append(result)
        remaining = result.overflow
    return pages, impossible


def count_rotations(result):
    return sum(1 for item in result.placed if item.get("rotated"))


def sizes_in(items):
    counts = {}
    for item in items:
        label = item_label(item)
        counts[label] = counts.get(label, 0) + 1
    return ", ".join(f"{label}×{count}" for label, count in counts.items()) or "—"


def multipage_report(lots):
    lines = ["MULTIPAGE PACKING DIAGNOSTIC", f"margin={DEFAULT_MARGIN_CM:g} extra={DEFAULT_EXTRA_LAYOUT_CM:g}"]
    for lot_name, items in lots.items():
        lines.extend(("", f"LOT {lot_name}: requested={len(items)} [{sizes_in(items)}]"))
        for strategy in (*PAGE_STRATEGIES, "best_of_strategies_per_page"):
            pages, impossible = pack_all_pages(items, strategy)
            placed = sum(len(page.placed) for page in pages)
            cut_values = [page.cut_occupancy for page in pages]
            pack_values = [page.packing_occupancy for page in pages]
            rotations = sum(count_rotations(page) for page in pages)
            lines.append(
                f"  {strategy}: sheets={len(pages)} placed={placed}/{len(items)} impossible={len(impossible)} "
                f"avg_cut={sum(cut_values) / len(cut_values):.4f} worst_cut={min(cut_values):.4f} "
                f"avg_pack={sum(pack_values) / len(pack_values):.4f} worst_pack={min(pack_values):.4f} rotations={rotations}"
            )
            for number, page in enumerate(pages, start=1):
                lines.append(
                    f"    page {number}: placed={len(page.placed)} [{sizes_in(page.placed)}] "
                    f"overflow=[{sizes_in(page.overflow)}] cut={page.cut_occupancy:.4f} pack={page.packing_occupancy:.4f}"
                )
    return "\n".join(lines)


def run_and_save():
    # build items
    items = []
    items.append({"cut_width_cm": 15.0, "cut_height_cm": 8.0})
    items.extend([{"cut_width_cm": 10.0, "cut_height_cm": 6.0}] * 2)
    items.extend([{"cut_width_cm": 7.0, "cut_height_cm": 7.0}] * 3)
    items.extend([{"cut_width_cm": 5.0, "cut_height_cm": 5.0}] * 6)
    items.extend([{"cut_width_cm": 3.0, "cut_height_cm": 3.0}] * 8)

    def new_project():
        return PlanchaProject([
            PlanchaItem(path=str(i) + ".png", name=str(i), width_cm=float(item["cut_width_cm"]), height_cm=float(item["cut_height_cm"]))
            for i, item in enumerate(items)
        ], margin_cm=DEFAULT_MARGIN_CM)

    # Ambas ejecuciones parten de instancias nuevas con el mismo input.
    classic_proj = new_project()
    classic_overflow = classic_proj.optimize()
    classic_overflow_ids = {it.item_id for it in classic_overflow}
    classic_placed = [it for it in classic_proj.items if it.item_id not in classic_overflow_ids]
    classic_valid, classic_violations = audit_classic_safety(classic_placed)

    geometric_proj = new_project()
    geo_result = geometric_pack(
        [
            {
                **item.to_dict(),
                "cut_width_cm": item.width_cm,
                "cut_height_cm": item.height_cm,
            }
            for item in geometric_proj.items
        ],
        extra_cm=DEFAULT_EXTRA_LAYOUT_CM,
        allow_rotation=True,
    )

    # Ensure artifacts dir
    import os
    artifacts = os.path.join(os.getcwd(), "artifacts")
    os.makedirs(artifacts, exist_ok=True)

    classic_path = os.path.join(artifacts, "packing_classic.png")
    geometric_path = os.path.join(artifacts, "packing_geometric.png")
    free_rects_path = os.path.join(artifacts, "packing_geometric_free_rects.png")
    shell_path = os.path.join(artifacts, "packing_irregular_shell.png")
    shell_source_path = os.path.join(artifacts, "irregular_shell_source.png")

    draw_classic(classic_placed, classic_path)
    draw_geometric(geo_result, geometric_path, free_rects_path)
    draw_irregular_shell(shell_path, shell_source_path)

    # print summary numbers
    printable_area_cm2 = (A4_WIDTH_CM - DEFAULT_MARGIN_CM * 2) * (A4_HEIGHT_CM - DEFAULT_MARGIN_CM * 2)
    classic_cut_area = sum(it.width_cm * it.height_cm for it in classic_placed)
    classic_cut_occ = classic_cut_area / printable_area_cm2

    geo_cut_occ = geo_result.cut_occupancy

    print("CLASSIC: placed=", len(classic_placed), "overflow=", len(classic_overflow), "cut_occ=", f"{classic_cut_occ:.4f}", "packing_occ=N/A", "rotated=0")
    print(f"CLASSIC under +{DEFAULT_EXTRA_LAYOUT_CM:g} safety rule: valid={len(classic_valid)}/{len(classic_placed)} violations={len(classic_violations)}")
    for item, in_bounds, overlaps in classic_violations:
        print(f"  classic violation {item.width_cm:g}x{item.height_cm:g}: in_bounds={in_bounds} overlaps={len(overlaps)}")
    print("GEOMETRIC: placed=", len(geo_result.placed), "overflow=", len(geo_result.overflow), "cut_occ=", f"{geo_cut_occ:.4f}", "packing_occ=", f"{geo_result.packing_occupancy:.4f}", "rotated=", sum(1 for p in geo_result.placed if p.get("rotated")))
    print("\nPor tamaño: solicitado / clásico / geométrico")
    for width, height in ((15, 8), (10, 6), (7, 7), (5, 5), (3, 3)):
        requested = sum(1 for item in items if (item["cut_width_cm"], item["cut_height_cm"]) == (width, height))
        classic_count = sum(1 for item in classic_placed if (item.width_cm, item.height_cm) == (width, height))
        geometric_count = sum(1 for item in geo_result.placed if (item["cut_width_cm"], item["cut_height_cm"]) == (width, height))
        print(f"{width}x{height}: requested={requested} classic={classic_count} geometric={geometric_count}")
    geometric_items = [
        {**item.to_dict(), "cut_width_cm": item.width_cm, "cut_height_cm": item.height_cm}
        for item in geometric_proj.items
    ]
    print_strategy_results(geometric_items)

    def lot(*groups):
        expanded = []
        for count, width, height in groups:
            expanded.extend({"cut_width_cm": width, "cut_height_cm": height} for _ in range(count))
        return expanded

    lots = {
        "visual_current": geometric_items,
        "large_heavy": lot((4, 15, 8), (5, 10, 6), (6, 7, 7), (4, 3, 3)),
        "small_heavy": lot((1, 15, 8), (2, 10, 6), (4, 7, 7), (14, 5, 5), (24, 3, 3)),
        "balanced_rectangles": lot((3, 14, 5), (5, 9, 6), (8, 6, 4), (12, 3, 3)),
        "tall_wide_mix": lot((3, 18, 3), (3, 5, 12), (5, 8, 5), (10, 4, 4), (14, 2, 3)),
        "medium_dense": lot((8, 8, 7), (10, 6, 5), (16, 4, 4), (12, 3, 2)),
    }
    report = multipage_report(lots)
    report_path = os.path.join(artifacts, "multipage_packing_report.txt")
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(report + "\n")
    print("\n" + report)
    print("Multipage report:", report_path)
    print("Artifacts:", classic_path, geometric_path, free_rects_path, shell_path)


if __name__ == "__main__":
    run_and_save()
