"""Offline visual evidence bank. Never publishes or approves production assets.

Run: python -m scripts.validate_sticker_visuals --output artifacts/sticker-visual-v1
Each invocation requires a NEW output folder; previous evidence is immutable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from app.stickers.models import CreationMode
from app.stickers.pipeline import StickerProcessor, VISUAL_STICKER_TYPES


def checker(size, cell=12):
    y, x = np.indices((size[1], size[0]))
    grey = np.where((x // cell + y // cell) % 2, 205, 245).astype('uint8')
    return Image.fromarray(np.dstack([grey, grey, grey, np.full_like(grey, 255)]))


def synthetic(kind, complex_case):
    """Deterministic technical probes, not photographic production references."""
    size = (480, 360)
    alpha = Image.new('L', size)
    draw = ImageDraw.Draw(alpha)
    draw.ellipse((100, 55, 360, 305), fill=255)
    if complex_case:
        draw.ellipse((180, 125, 265, 210), fill=0)
        draw.rectangle((350, 160, 430, 168), fill=255)
    if kind == 'multiples_objetos':
        alpha = Image.new('L', size)
        draw = ImageDraw.Draw(alpha)
        for box in ((35, 40, 135, 140), (195, 65, 290, 170), (325, 205, 435, 320)):
            draw.ellipse(box, fill=255)
        if complex_case:
            draw.line((130, 110, 200, 110), fill=255, width=2)
    elif kind in ('lineas_finas', 'logo_tipografia', 'dibujo_escaneado'):
        alpha = Image.new('L', size)
        draw = ImageDraw.Draw(alpha)
        if kind == 'logo_tipografia':
            draw.text((70, 100), 'DOC CIONE 18', fill=255, font_size=45 if not complex_case else 24)
        else:
            draw.line([(50, 280), (130, 80), (240, 280), (350, 80), (420, 280)], fill=255,
                      width=2 if complex_case else 6)
    elif kind == 'sujeto_cortado_encuadre':
        draw.ellipse((-80, 45, 290, 330), fill=255)
    elif kind == 'semitransparencias':
        alpha = alpha.filter(ImageFilter.GaussianBlur(12 if complex_case else 4))
        alpha = alpha.point(lambda p: round(p * .65))

    art = Image.new('RGBA', size, (195, 45, 100, 255))
    if kind in ('logo_tipografia', 'lineas_finas', 'dibujo_escaneado'):
        art = Image.new('RGBA', size, (35, 35, 35, 255))
    ImageDraw.Draw(art).line((130, 100, 310, 270), fill=(255, 200, 20, 255), width=9)
    art.putalpha(alpha)
    truth = alpha.copy()
    if kind in ('sticker_terminado', 'sticker_con_halo', 'borde_color'):
        base = alpha.filter(ImageFilter.MaxFilter(25))
        under = Image.new('RGBA', size, (255, 255, 255, 255) if kind != 'borde_color' else (40, 150, 240, 255))
        under.putalpha(base)
        under.alpha_composite(art)
        art = under
        truth = base
        if kind == 'sticker_con_halo':
            halo = Image.new('RGBA', size, (145, 145, 145, 255))
            halo.putalpha(base.filter(ImageFilter.GaussianBlur(4)))
            halo.alpha_composite(art)
            art = halo
    if kind in ('arte_transparente', 'sticker_terminado', 'borde_color', 'semitransparencias', 'multiples_objetos'):
        return art, truth
    if kind == 'damero_incrustado':
        background = checker(size, 8 if complex_case else 16)
    elif kind in ('fondo_degradado_texturizado', 'ilustracion_compleja', 'fotografia', 'imagen_completa'):
        y, x = np.indices((size[1], size[0]))
        channel = ((x * .2 + y * .15 + (np.sin(y / 8) * 25 if complex_case else 0)) % 100 + 130).astype('uint8')
        background = Image.fromarray(np.dstack([channel, channel // 2, 255-channel, np.full_like(channel, 255)]))
    else:
        color = {'fondo_neutro': (215, 215, 215), 'fondo_color': (30, 190, 80)}.get(kind, (255, 255, 255))
        background = Image.new('RGBA', size, color + (255,))
    background.alpha_composite(art)
    return background.convert('RGB'), truth


def prepare_bank(root):
    inputs = root / 'inputs'
    inputs.mkdir()
    fixture_root = Path(__file__).resolve().parents[1] / 'tests/fixtures/sticker_regression'
    real = {('fondo_blanco', 'B'): 'lips_white.png',
            ('damero_incrustado', 'A'): 'heart_checker.png',
            ('damero_incrustado', 'B'): 'disco_checker.png'}
    cases = []
    for index, (kind, label) in enumerate(VISUAL_STICKER_TYPES, 1):
        for variant in ('A', 'B'):
            case_id = f'{index:02d}-{variant}'
            path = inputs / f'{case_id}-{kind}.png'
            fixture = real.get((kind, variant))
            truth_path = None
            if fixture:
                import shutil
                shutil.copyfile(fixture_root / fixture, path)
            else:
                image, truth = synthetic(kind, variant == 'B')
                image.save(path)
                truth_path = inputs / f'{case_id}-reference-mask.png'
                truth.save(truth_path)
            mode = (CreationMode.FULL_IMAGE if kind == 'imagen_completa' else
                    CreationMode.MULTI_OBJECT if kind == 'multiples_objetos' else CreationMode.SILHOUETTE)
            cases.append(dict(id=case_id, category=kind, category_label=label, variant=variant,
                              source=str(path.resolve()), reference_mask=str(truth_path.resolve()) if truth_path else None,
                              provenance='real_user_reference' if fixture else 'synthetic_technical_probe',
                              real_reference_required=not bool(fixture), creation_mode=mode.value))
    return cases


def composite(image, color):
    image = image.convert('RGBA')
    background = checker(image.size) if color == 'checker' else Image.new('RGBA', image.size, color)
    background.alpha_composite(image)
    return background.convert('RGB')


def tile(image, label, size=(260, 290)):
    panel = Image.new('RGB', size, '#dddddd')
    image = ImageOps.contain(image.convert('RGB'), (size[0]-12, size[1]-40))
    panel.paste(image, ((size[0]-image.width)//2, 32+(size[1]-40-image.height)//2))
    ImageDraw.Draw(panel).text((6, 7), label, fill='black')
    return panel


def diagnostics(record, result, folder):
    folder.mkdir()
    images = {}
    with Image.open(record['source']) as original:
        images['original'] = composite(original, 'checker')
    for key in ('thumbnail', 'native_master', 'mask_editable', 'native_printable_base', 'native_cut'):
        with Image.open(result.artifacts[key]) as image:
            images[key] = composite(image, 'checker') if image.mode == 'RGBA' else image.convert('RGB')
    with Image.open(result.artifacts['native_master']) as image:
        for color in ('white', 'black', 'checker'):
            images[color] = composite(image, color)
        # True pixel crop with nearest-neighbour 200% zoom, no smoothed enlargement.
        bbox = image.getchannel('A').getbbox()
        x = bbox[2]-20 if bbox else image.width//2
        y = image.height//2
        crop = composite(image, 'black').crop((max(0,x-55), max(0,y-55), min(image.width,x+55), min(image.height,y+55)))
        crop.save(folder/'edge_100pct.png')
        images['edge_200pct'] = crop.resize((crop.width*2, crop.height*2), Image.Resampling.NEAREST)
        import cv2
        with Image.open(result.artifacts['native_cut']) as cut:
            contours, _ = cv2.findContours(np.asarray(cut).copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        overlay = np.asarray(composite(image, 'checker')).copy()
        cv2.drawContours(overlay, contours, -1, (0, 210, 50), 1)
        Image.fromarray(overlay).save(folder/'cut_overlay.png')
    paths = {}
    for name, image in images.items():
        target = folder / f'{name}.png'
        image.save(target)
        paths[name] = str(target.resolve())
    grid = Image.new('RGB', (260*5, 290*2), 'white')
    for index, (name, image) in enumerate(images.items()):
        grid.paste(tile(image, name), ((index%5)*260, (index//5)*290))
    target = folder / 'comparison.png'
    grid.save(target)
    paths['comparison'] = str(target.resolve())
    paths['edge_100pct'] = str((folder/'edge_100pct.png').resolve())
    paths['cut_overlay'] = str((folder/'cut_overlay.png').resolve())
    return paths


def execute(record, root, options=None):
    start = time.perf_counter()
    record = dict(record, automatic_result='ERROR', visual_validation='PENDING', visual_observations=[], defects=[])
    source = Path(record['source'])
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    try:
        processor = StickerProcessor(root / 'pipeline')
        result = processor.process(source, creation_mode=record['creation_mode'], **(options or {}))
        a = result.analysis
        q = a['quality_report']
        record.update(automatic_result='COMPLETED', job_id=result.job_id, detected_type=a['sticker_type'],
                      additional_features=a['classification_features'], detected_types=a['detected_types'],
                      technical_route=a['case'], source_resolution=a['source_pixels'],
                      result_resolution=a['native_resolution']['pixels'], physical_size_cm=a['native_resolution']['physical_size_cm'],
                      quality_status=q['status'], warnings=q['warnings'], errors=q['errors'],
                      alternatives=a.get('automatic_recovery'), artifacts=result.artifacts,
                      object_components=a.get('object_components', []),
                      reprocess_parameters=a.get('reprocess_parameters', {}),
                      diagnostic_options={key: str(value) if isinstance(value, Path) else value for key,value in (options or {}).items()},
                      diagnostic_artifacts=diagnostics(record, result, root / 'views' / record['id']))
        if (record.get('reference_mask') and record['creation_mode'] != CreationMode.FULL_IMAGE.value
                and not (options or {}).get('selected_component_ids')):
            with Image.open(record['reference_mask']) as reference, Image.open(result.artifacts['mask_editable']) as actual:
                ref, got = np.asarray(reference)>12, np.asarray(actual)>12
                record['synthetic_reference_iou'] = float((ref & got).sum()/max(1,(ref | got).sum()))
                record['synthetic_alpha_mae'] = float(np.abs(np.asarray(reference,dtype=float)-np.asarray(actual,dtype=float)).mean())
    except Exception as exc:
        logging.exception('Case %s failed', record['id'])
        record['exception'] = f'{type(exc).__name__}: {exc}'
    record.update(elapsed_seconds=round(time.perf_counter()-start, 3), source_sha256=before,
                  source_unchanged=before == hashlib.sha256(source.read_bytes()).hexdigest())
    print(record['id'], record['automatic_result'], flush=True)
    return record


def run(root):
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root/'views').mkdir()
    logging.basicConfig(filename=root/'execution.log', level=logging.INFO)
    cases = prepare_bank(root)
    records = []
    for case in cases:
        records.append(execute(case, root))
        (root/'manifest.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    # Explicit compatible combinations only, without forced visual classification.
    base = next(c for c in cases if c['category']=='imagen_completa' and c['variant']=='A')
    for shape in ('Circular', 'Ovalada', 'Personalizada'):
        case = dict(base, id='mode-'+shape, full_image_shape=shape)
        options = dict(full_image_shape=shape)
        if shape == 'Personalizada':
            options['mask_override'] = base['reference_mask']
        records.append(execute(case, root, options))
    multiple = next(r for r in records if r['id']=='12-A')
    ids = [c['id'] for c in multiple.get('object_components', [])]
    if ids:
        case = dict(next(c for c in cases if c['id']=='12-A'), id='mode-objects-selected')
        records.append(execute(case, root, dict(selected_component_ids=ids[:1], previous_object_components=multiple['object_components'])))
        case = dict(case, id='mode-objects-reprocess')
        records.append(execute(case, root, dict(previous_object_components=multiple['object_components'])))
    # Preserve a user-authored mask with a hole across two real process calls.
    manual = next(c for c in cases if c['id']=='01-B')
    for suffix in ('first', 'reprocess'):
        records.append(execute(dict(manual, id='mode-manual-'+suffix), root,
                               dict(mask_override=manual['reference_mask'])))
    # Independent cut correction: source/design are not edited.
    full = next(r for r in records if r['id']=='17-A')
    with Image.open(full['artifacts']['cut']) as automatic_cut:
        corrected_cut = Image.new('L', automatic_cut.size)
        ImageDraw.Draw(corrected_cut).ellipse((60, 60, automatic_cut.width-61, automatic_cut.height-61), fill=255)
    corrected_cut_path = root/'inputs'/'manual-cut.png'
    corrected_cut.save(corrected_cut_path)
    records.append(execute(dict(base, id='mode-independent-cut'), root,
                           dict(cut_mask_override=corrected_cut_path)))
    (root/'sheets').mkdir()
    for index in range(1,19):
        sheet = Image.new('RGB', (1300, 1200), 'white')
        draw = ImageDraw.Draw(sheet)
        for row, variant in enumerate(('A','B')):
            record = next(r for r in records if r['id']==f'{index:02d}-{variant}')
            draw.text((8,row*600+5), f"{record['id']} {record['category']} | {record['provenance']} | VISUAL PENDING", fill='black')
            path = record.get('diagnostic_artifacts',{}).get('comparison')
            if path:
                with Image.open(path) as image:
                    sheet.paste(image,(0,row*600+20))
        sheet.save(root/'sheets'/f'{index:02d}.png')
    (root/'manifest.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    return records


def compare_runs(baseline, current):
    """Add separate before/after evidence without rewriting either run."""
    baseline, current = Path(baseline).resolve(), Path(current).resolve()
    before = {r['id']: r for r in json.loads((baseline/'manifest.json').read_text(encoding='utf-8'))}
    after = json.loads((current/'manifest.json').read_text(encoding='utf-8'))
    destination = current/'before_after'
    destination.mkdir(exist_ok=False)
    comparisons = []
    for new in after:
        old = before[new['id']]
        sheet = Image.new('RGB', (260*6, 290), 'white')
        for index, (label, record, artifact) in enumerate([
            ('before alpha', old, 'mask_editable'), ('after alpha', new, 'mask_editable'),
            ('before native', old, 'native_master'), ('after native', new, 'native_master'),
            ('before cut', old, 'native_cut'), ('after cut', new, 'native_cut')]):
            with Image.open(record['artifacts'][artifact]) as image:
                panel = composite(image, 'black') if image.mode == 'RGBA' else image.convert('RGB')
                sheet.paste(tile(panel, label), (index*260, 0))
        path = destination/f"{new['id']}.png"
        sheet.save(path)
        comparisons.append(dict(id=new['id'], evidence=str(path), provenance=new['provenance'],
                                same_source=old['source_sha256']==new['source_sha256'],
                                same_detected_type=old['detected_type']==new['detected_type'],
                                same_route=old['technical_route']==new['technical_route'],
                                before_iou=old.get('synthetic_reference_iou'), after_iou=new.get('synthetic_reference_iou'),
                                before_quality=old['quality_status'], after_quality=new['quality_status']))
    (destination/'comparison.json').write_text(json.dumps(comparisons, ensure_ascii=False, indent=2), encoding='utf-8')
    return comparisons


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.output)
