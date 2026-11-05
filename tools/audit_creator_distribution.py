"""Auditoría sin escrituras operativas: sólo modelos en memoria y JSON de métricas."""
from collections import Counter
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
from types import SimpleNamespace
from collections import OrderedDict
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.planchas.model import PlanchaItem, PlanchaProject
from app.planchas.sticker_mixed import StickerMixedPacker
from app.planchas.editor import PlanchaEditor
from app.database.database import ImageDatabase


def scenario(count, mixed=False):
    return [PlanchaItem(path=f'FICTICIO-{i % 3}.png', name=f'Diseño {i % 3}',
                       width_cm=([4.8, 3.2, 2.4][i % 3] if mixed else 4.8),
                       height_cm=([4.8, 3.0, 2.0][i % 3] if mixed else 4.8))
            for i in range(count)]


def inspect(pages, originals):
    errors = []
    placed = [i for p in pages for i in p.items]
    if Counter(i.item_id for i in placed) != Counter(i.item_id for i in originals):
        errors.append('Pérdida/duplicación de unidades')
    for page in pages:
        # Mixta deliberately packs touching hitboxes; each has internal air.
        clearance = 0 if page.project_type == 'sticker_mixed' else page.gap_cm
        for n, item in enumerate(page.items):
            if (item.x_cm < page.margin_cm-.001 or item.y_cm < page.margin_cm-.001
                    or item.x_cm+item.reserved_width_cm > 21-page.margin_cm+.001
                    or item.y_cm+item.reserved_height_cm > page.workspace_bottom_cm+.001):
                errors.append('Fuera de área útil')
            for other in page.items[n+1:]:
                if not (item.x_cm+item.reserved_width_cm+clearance <= other.x_cm+.001
                        or other.x_cm+other.reserved_width_cm+clearance <= item.x_cm+.001
                        or item.y_cm+item.reserved_height_cm+clearance <= other.y_cm+.001
                        or other.y_cm+other.reserved_height_cm+clearance <= item.y_cm+.001):
                    errors.append('Solapamiento/separación insuficiente')
        if PlanchaProject.from_dict(page.to_dict()).to_dict() != page.to_dict():
            errors.append('Persistencia no idéntica')
    return sorted(set(errors))


def main():
    results = []
    for mixed in (False, True):
        for count in (10, 25, 50, 100, 200):
            for gap in (.05, .15):
                timings = []
                for _ in range(5):
                    items = scenario(count, mixed)
                    start = perf_counter()
                    pages = PlanchaProject.calculate_pagination(items, margin_cm=.15, gap_cm=gap)
                    timings.append((perf_counter()-start)*1000)
                errors = inspect(pages, items)
                used = sum(i.width_cm*i.height_cm for p in pages for i in p.items)
                reserved = sum(i.reserved_width_cm*i.reserved_height_cm for p in pages for i in p.items)
                useful = sum(p.usable_width*p.usable_height for p in pages)
                results.append(dict(count=count, mixed=mixed, gap_cm=gap, pages=len(pages),
                                    counts=[len(p.items) for p in pages], median_ms=round(median(timings),3),
                                    max_ms=round(max(timings),3), occupancy_percent=round(used/useful*100,2),
                                    reserved_percent=round(reserved/useful*100,2),
                                    last_page_percent=round(pages[-1].occupancy(),2),
                                    design_counts=dict(Counter(i.name for p in pages for i in p.items)), errors=errors))
    # Reproducer: pagination has no impossible-items result.
    impossible = PlanchaItem(path='imposible.png', name='Imposible', width_cm=30, height_cm=30)
    pages = PlanchaProject.calculate_pagination([impossible])
    probes = {'impossible_input': 1, 'returned_pages': len(pages),
              'returned_items': sum(len(p.items) for p in pages)}
    original = PlanchaProject(scenario(2), margin_cm=.3, gap_cm=.15)
    restored = PlanchaProject.from_dict(original.to_dict())
    probes['recovery'] = {'before': [original.margin_cm, original.gap_cm],
                          'after': [restored.margin_cm, restored.gap_cm]}
    modern = []
    for mode in ('standard', 'mixed'):
        for count in (10, 25, 50, 100, 200):
            timings = []
            for _ in range(3):
                items = scenario(count, mode == 'mixed')
                for index, item in enumerate(items):
                    # Three commercial nominals; unequal design quantities 40/35/25 at n=100.
                    design = 0 if index < round(count*.4) else 1 if index < round(count*.75) else 2
                    item.path = f'FICTICIO-{design}.png'
                    item.name = f'Diseño {design}'
                    item.nominal_size_cm = [5, 8, 10][design] if mode == 'mixed' else 5
                start = perf_counter()
                if mode == 'mixed':
                    packed = StickerMixedPacker().pack(items)
                    pages = packed.projects
                else:
                    pages = PlanchaProject.calculate_pagination(items, project_type='sticker_standard')
                timings.append((perf_counter()-start)*1000)
            modern.append(dict(mode=mode, count=count, median_ms=round(median(timings),3),
                pages=len(pages), counts=[len(p.items) for p in pages],
                occupancy_percent=round(sum(p.occupancy() for p in pages)/len(pages),2),
                last_page_percent=round(pages[-1].occupancy(),2),
                errors=inspect(pages, items),
                scale=packed.scale_factor if mode=='mixed' else None))
    output = ROOT / 'artifacts' / 'creator-audit-20261023'
    output.mkdir(exist_ok=True)
    from PIL import Image
    png = output/'FICTICIO-a4-valid.png'
    Image.new('RGBA', (2480,3508), (255,255,255,255)).save(png, dpi=(300,300))
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE app_settings(setting_key TEXT,setting_value TEXT)')
    config = ImageDatabase.printing_config(SimpleNamespace(connection=conn))
    editor = SimpleNamespace(database=object(), plancha_id=1, project_path=str(png),
        final_png_path=str(png), project=PlanchaProject([]), _linked_order_id=lambda: None,
        _current_print_config=lambda: config)
    probes['printing'] = {'configured_scale': config['scale'],
        'validation_error': PlanchaEditor._print_validation_error(editor)}
    editor = SimpleNamespace(project=PlanchaProject([PlanchaItem(path=str(output/'NO-EXISTE.png'),
        name='Faltante',width_cm=3,height_cm=3,x_cm=1,y_cm=1)]), current_project_index=0,
        _prepare_current_project_for_preview=lambda: None,
        production_sticker_cache=OrderedDict(),production_sticker_cache_pixels=0,
        prepared_production_sticker=lambda *args: None)
    sheet = PlanchaEditor.render_sheet(editor)
    probes['missing_file_render'] = {'raised_error': False,
        'alpha_bbox': sheet.getchannel('A').getbbox(), 'size_px': sheet.size}
    conn.close()
    (output/'distribution.json').write_text(json.dumps({'repeats': 5, 'includes_io': False,
        'scenarios': results, 'modern': modern, 'probes': probes}, ensure_ascii=False, indent=2), encoding='utf-8')
    for r in results:
        print(f"{r['count']:3} {'mixto' if r['mixed'] else 'igual':5} gap={r['gap_cm']} hojas={r['pages']:2} ocup={r['occupancy_percent']:5.2f}% última={r['last_page_percent']:5.2f}% ms={r['median_ms']:7.3f} errores={r['errors']}")
    print('Imposible:', probes)
    print('MODERNOS:', json.dumps(modern, ensure_ascii=False))


if __name__ == '__main__':
    main()
