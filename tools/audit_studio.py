"""Auditoría repetible de planchas, datos y tiempos de Doccione Studio."""

from __future__ import annotations

import json
import sqlite3
import statistics
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont

from app.database.database import ImageDatabase
from app.indexer.thumbnails import prepare_thumbnail
from app.planchas.model import visible_bbox
from app.planchas.template_model import REGULAR_PATTERNS, RegularTemplateProject
from app.printing.windows_print import validate_a4_png


OUTPUT = ROOT / "outputs" / "auditoria"


def elapsed(callable_):
    started = time.perf_counter()
    result = callable_()
    return result, round((time.perf_counter() - started) * 1000, 2)


def existing_images(connection, limit=500):
    rows = connection.execute(
        "SELECT path, visible_ratio FROM images WHERE path <> '' ORDER BY visual_score DESC, modified DESC LIMIT ?",
        (limit,),
    )
    return [(Path(row[0]), float(row[1] or 0)) for row in rows if Path(row[0]).exists()]


def best_sample(images, ratio):
    available = [(path, stored_ratio) for path, stored_ratio in images if stored_ratio > 0]
    if available:
        return min(available, key=lambda item: abs(item[1] - ratio))[0]
    return images[0][0] if images else None


def fitted_image(path, width, height):
    with Image.open(path) as source:
        source = source.convert("RGBA")
    source = source.crop(visible_bbox(source))
    source.thumbnail((max(1, width - 4), max(1, height - 4)), Image.Resampling.LANCZOS)
    return source


def render_patterns(images):
    page_w, page_h = 420, 594
    card_w, card_h = page_w + 20, page_h + 46
    contact = Image.new("RGB", (card_w * 3, card_h * 3), "#17191b")
    draw_contact = ImageDraw.Draw(contact)
    for index, (pattern_id, pattern) in enumerate(REGULAR_PATTERNS.items()):
        page = Image.new("RGBA", (page_w, page_h), "white")
        draw = ImageDraw.Draw(page)
        sample = best_sample(images, RegularTemplateProject.cell_ratio(pattern_id))
        cells = RegularTemplateProject.pattern_cells(pattern_id)
        for cell in cells:
            x = round(cell.x * page_w)
            y = round(cell.y * page_h)
            width = round(cell.width * page_w)
            height = round(cell.height * page_h)
            draw.rectangle((x, y, x + width, y + height), outline="#777777", width=1)
            if sample:
                sticker = fitted_image(sample, width, height)
                page.alpha_composite(sticker, (x + (width - sticker.width) // 2, y + (height - sticker.height) // 2))
        column, row = index % 3, index // 3
        left, top = column * card_w + 10, row * card_h + 34
        contact.paste(page.convert("RGB"), (left, top))
        draw_contact.text((left, top - 24), f"{pattern['title']} · {pattern['detail']}", fill="#f2e5da")
    path = OUTPUT / "patrones_reales.png"
    contact.save(path, optimize=True)
    return path


def create_print_calibration():
    """Crea una hoja diagnóstica; no forma parte de una plancha de producción."""
    dpi = 300
    width, height = round(21 / 2.54 * dpi), round(29.7 / 2.54 * dpi)
    page = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(page)
    try:
        title_font = ImageFont.truetype("arialbd.ttf", 46)
        text_font = ImageFont.truetype("arial.ttf", 30)
    except OSError:
        title_font = text_font = ImageFont.load_default()
    cm = dpi / 2.54
    margin = round(0.15 * cm)
    gap = max(1, round(0.05 * cm))
    draw.rectangle((0, 0, width - 1, height - 1), outline="black", width=2)
    draw.rectangle((margin, margin, width - margin - 1, height - margin - 1), outline="#d60916", width=3)
    draw.text((90, 90), "CALIBRACIÓN DOCCIONE · A4 · 300 DPI · ESCALA 100 %", fill="black", font=title_font)
    draw.text((90, 160), "Medir físicamente: margen rojo 1,5 mm · separación 0,5 mm · regla 100 mm.", fill="black", font=text_font)
    x, y, length = 260, 350, round(10 * cm)
    draw.line((x, y, x + length, y), fill="black", width=4)
    draw.line((x, y - 25, x, y + 25), fill="black", width=4)
    draw.line((x + length, y - 25, x + length, y + 25), fill="black", width=4)
    draw.text((x, y + 40), "100 mm exactos", fill="black", font=text_font)
    box_w, box_h = round(5.7 * cm), round(5.7 * cm)
    top = 650
    left = (width - (box_w * 2 + gap)) // 2
    draw.rounded_rectangle((left, top, left + box_w, top + box_h), radius=80, fill="#f2f2f2", outline="black", width=2)
    draw.rounded_rectangle((left + box_w + gap, top, left + box_w * 2 + gap, top + box_h), radius=80, fill="#f2f2f2", outline="black", width=2)
    draw.text((left + 80, top + box_h // 2), "5,70 cm", fill="black", font=title_font)
    draw.text((left + box_w + gap + 80, top + box_h // 2), "5,70 cm", fill="black", font=title_font)
    draw.text((left, top + box_h + 45), "La luz entre cajas debe medir 0,5 mm.", fill="black", font=text_font)
    vertical_x, vertical_y = 320, 1750
    draw.line((vertical_x, vertical_y, vertical_x, vertical_y + length), fill="black", width=4)
    draw.line((vertical_x - 25, vertical_y, vertical_x + 25, vertical_y), fill="black", width=4)
    draw.line((vertical_x - 25, vertical_y + length, vertical_x + 25, vertical_y + length), fill="black", width=4)
    draw.text((vertical_x + 45, vertical_y + length // 2), "100 mm", fill="black", font=text_font)
    draw.text((700, 1950), "Resultado físico", fill="black", font=title_font)
    for index, label in enumerate(("Ancho medido:", "Alto medido:", "Margen real:", "Separación real:")):
        yy = 2050 + index * 120
        draw.text((700, yy), label, fill="black", font=text_font)
        draw.line((1050, yy + 35, 1750, yy + 35), fill="#777777", width=2)
    draw.text((90, height - 180), "Si 100 mm no miden 100 mm, revisar el driver: no ajustar, no expandir, no reducir.", fill="black", font=text_font)
    path = OUTPUT / "calibracion_impresion_A4_300dpi.png"
    page.save(path, "PNG", dpi=(300, 300), compress_level=3)
    return path


def normalized_duplicates(connection, table, column):
    values = [str(row[0] or "") for row in connection.execute(f"SELECT {column} FROM {table} WHERE TRIM(COALESCE({column}, '')) <> ''")]
    groups = {}
    for value in values:
        groups.setdefault(" ".join(value.split()).casefold(), set()).add(value)
    return [sorted(group) for group in groups.values() if len(group) > 1]


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    database, startup_ms = elapsed(lambda: ImageDatabase(ROOT / "visionvault.db"))
    connection = database.connection
    images = existing_images(connection)
    _, search_50_ms = elapsed(lambda: database.search(limit=50))
    _, search_500_ms = elapsed(lambda: database.search(limit=500))

    def make_thumbnails():
        for path, _ratio in images[:100]:
            prepare_thumbnail(str(path), 120, 120, path.stat().st_mtime)

    _, thumbnails_ms = elapsed(make_thumbnails)
    _, cached_thumbnails_ms = elapsed(make_thumbnails)
    patterns_path, patterns_ms = elapsed(lambda: render_patterns(images))
    calibration_path, calibration_ms = elapsed(create_print_calibration)

    export_candidates = [
        path for path in (ROOT / "outputs").rglob("*.png")
        if OUTPUT not in path.parents
    ]
    print_validation = []
    export_copy_ms = None
    if export_candidates:
        candidate = max(export_candidates, key=lambda path: path.stat().st_mtime)
        valid, message = validate_a4_png(candidate)
        print_validation.append({"file": str(candidate), "valid": valid, "message": message})

        def export_copy():
            with Image.open(candidate) as source:
                source.load()
                source.save(OUTPUT / "prueba_exportacion_sin_perdida.png", "PNG", dpi=(300, 300), compress_level=3)

        _, export_copy_ms = elapsed(export_copy)

    state_rows = connection.execute(
        "SELECT is_private, is_reusable, is_favorite, COUNT(*) FROM images GROUP BY is_private, is_reusable, is_favorite"
    ).fetchall()
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "contracts": {
            "a4_pixels_300_dpi": [2480, 3508], "scale_percent": 100,
            "regular_margin_cm": 0.15, "regular_gap_cm": 0.05,
            "automatic_policy": "Se propone el patrón con confianza; el usuario confirma antes de aplicarlo.",
            "commercial_definition": "Reutilizable + favorito; privado nunca aparece como comercial.",
        },
        "performance_ms": {
            "database_startup": startup_ms, "search_50": search_50_ms,
            "search_500": search_500_ms, "prepare_100_thumbnails": thumbnails_ms,
            "reload_100_cached_thumbnails": cached_thumbnails_ms,
            "render_all_regular_patterns": patterns_ms, "create_calibration_sheet": calibration_ms,
            "lossless_png_copy": export_copy_ms,
        },
        "data": {
            "images_total": connection.execute("SELECT COUNT(*) FROM images").fetchone()[0],
            "existing_sample_files": len(images),
            "duplicate_tags": normalized_duplicates(connection, "tags", "name"),
            "duplicate_categories": normalized_duplicates(connection, "images", "category"),
            "duplicate_collections": normalized_duplicates(connection, "collections", "name"),
            "favorites": connection.execute("SELECT COUNT(*) FROM images WHERE is_favorite = 1").fetchone()[0],
            "reusable": connection.execute("SELECT COUNT(*) FROM images WHERE is_reusable = 1").fetchone()[0],
            "private": connection.execute("SELECT COUNT(*) FROM images WHERE is_private = 1").fetchone()[0],
            "invalid_private_reusable": connection.execute("SELECT COUNT(*) FROM images WHERE is_private = 1 AND is_reusable = 1").fetchone()[0],
            "states": [list(row) for row in state_rows],
        },
        "printing": print_validation,
        "visual_patterns": str(patterns_path),
        "print_calibration_sheet": str(calibration_path),
        "physical_calibration_pending": [
            "Medir el margen real del plotter con regla.",
            "Comparar 100 mm del PNG con 100 mm impresos a escala 100 %.",
            "Confirmar separación de 0,05 cm y contornos blanco/negro sobre el material real.",
        ],
    }
    report_path = OUTPUT / "informe_auditoria.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    database.close()


if __name__ == "__main__":
    main()
