"""Read-only production-code audit on the real disc; outputs are NOT approved."""
from pathlib import Path
import hashlib
import json
import logging
import shutil
import sys

import numpy as np
from PIL import Image, ImageDraw

from app.stickers.pipeline import StickerProcessor
from app.stickers import grey_halo_decontamination as halo


def run(root):
    source = Path('artifacts/sticker-disc-human-review/original.png').resolve()
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    logging.basicConfig(filename=root/'execution.log', level=logging.INFO)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert digest == '0d84cf0c255870106b608ad18d3819c6aae187d3bec5caca45ce31e50c968221'
    original = Image.open(source).convert('RGBA')
    assert original.size == (421, 421)
    shutil.copy2(source, root/'original.png')
    captured = {}
    calls = []
    real = halo.complete_grey_halo_elimination_with_white_border
    common = halo.decontaminate_exterior

    def observe(image, alpha, **kwargs):
        captured['image'] = image.copy()
        captured['alpha'] = alpha.copy()
        result = common(image, alpha, **kwargs)
        calls.append(result[2])
        return result

    halo.decontaminate_exterior = observe
    try:
        result = StickerProcessor(root/'pipeline').process(source)
    finally:
        halo.decontaminate_exterior = common

    before = captured['alpha']
    image = captured['image']
    image.putalpha(before)
    before.save(root/'mask_before_contraction.png')
    image.save(root/'pipeline_before_halo.png')
    mask = Image.open(result.artifacts['mask_editable']).convert('L')
    mask.save(root/'pipeline_mask_clean.png')
    source_rgba = original.copy()
    source_rgba.putalpha(mask)
    source_rgba.save(root/'pipeline_source_resolution_421.png')
    shutil.copy2(result.artifacts['native_master'], root/'pipeline_final_transparent.png')
    for key in ('halo_region', 'halo_original_white_border', 'halo_mask_initial',
                'halo_mask_clean', 'halo_before_printable_border', 'native_printable_base'):
        if key in result.artifacts:
            shutil.copy2(result.artifacts[key], root/f'{key}.png')
    native_info = result.analysis['native_resolution']
    with Image.open(result.artifacts['native_printable_base']) as base, Image.open(result.artifacts['clean']) as design:
        native_design_alpha = Image.new('L', base.size)
        native_design_alpha.paste(design.getchannel('A'), tuple(native_info['design_offset']))
        added = (np.asarray(base) > 0) & (np.asarray(native_design_alpha) == 0)
        Image.fromarray(added.astype(np.uint8)*255).save(root/'printable_base_added_pixels.png')
    # This file refers only to configured extra border, not smoothing/substrate.
    if native_info['border_px'] == 0:
        Image.new('L', tuple(native_info['pixels'])).save(root/'new_printable_border_ZERO_preserved_original.png')

    # An isolated real-image diagnostic is explicitly NOT an end-to-end success.
    diagnostic = root/'isolated_module_NOT_PIPELINE'
    diagnostic.mkdir()
    mm = 30 * 25.4 / 300
    clean, clean_alpha, clean_meta = real(image, before, white_border_mm=mm,
                                         dpi=300, generate_white_border=False)
    final, final_alpha, final_meta = real(image, before, white_border_mm=mm,
                                         dpi=300, generate_white_border=True)
    clean_alpha.save(diagnostic/'mask_clean.png')
    clean.save(diagnostic/'before_new_white_border.png')
    final.save(diagnostic/'final_transparent_421.png', dpi=(300, 300))
    final_alpha.save(diagnostic/'returned_final_alpha.png')

    def backgrounds(img, folder):
        for name, color in [('black', 'black'), ('magenta', '#ff00ff'), ('white', 'white')]:
            base = Image.new('RGBA', img.size, color)
            base.alpha_composite(img)
            base.convert('RGB').save(folder/f'on_{name}.png')

    backgrounds(final, diagnostic)
    pipeline_final = Image.open(root/'pipeline_final_transparent.png').convert('RGBA')
    backgrounds(pipeline_final, root)
    panels = [('Original REAL', original), ('Pipeline nativo', pipeline_final),
              ('Modulo AISLADO - no aprobado', final), ('Antes de borde (aislado)', clean)]
    comparison = Image.new('RGB', (421*4, 451), '#ff00ff')
    draw = ImageDraw.Draw(comparison)
    for i, (title, img) in enumerate(panels):
        view = img.copy()
        view.thumbnail((421, 421))
        bg = Image.new('RGBA', (421, 421), '#ff00ff')
        bg.alpha_composite(view, ((421-view.width)//2, (421-view.height)//2))
        comparison.paste(bg.convert('RGB'), (421*i, 30))
        draw.text((421*i+5, 8), title, fill='black')
    comparison.save(root/'before_after.png')
    old_file = Path('artifacts/sticker-halo-real-20261019-v2/isolated_module_NOT_PIPELINE/final_transparent_421.png')
    if old_file.exists():
        old = Image.open(old_file).convert('RGBA')
        strip = Image.new('RGB', (421*3, 451), '#ff00ff')
        draw = ImageDraw.Draw(strip)
        for index, (label, view) in enumerate([
                ('Original', original), ('ANTES: modulo aislado fallido', old),
                ('AHORA: pipeline, revision manual', source_rgba)]):
            bg = Image.new('RGBA', view.size, '#ff00ff')
            bg.alpha_composite(view)
            strip.paste(bg.convert('RGB'), (index*421, 30))
            draw.text((index*421+5, 8), label, fill='black')
        strip.save(root/'integration_before_after.png')
    for name, img in [('pipeline', pipeline_final), ('module', final)]:
        bg = Image.new('RGBA', img.size, '#ff00ff')
        bg.alpha_composite(img)
        bg.resize((img.width*3, img.height*3), Image.Resampling.NEAREST).save(root/f'{name}_300pct.png')
    regions = {'upper_star': (295, 15, 400, 150), 'left_star': (20, 175, 100, 270),
               'lower_star_connection': (250, 290, 330, 365),
               'small_star_connection': (295, 335, 365, 405)}
    for name, box in regions.items():
        views = [original.crop(box), source_rgba.crop(box), final.crop(box)]
        w, h = views[0].size
        zoom = Image.new('RGBA', (w*3, h), '#ff00ff')
        for index, view in enumerate(views):
            zoom.alpha_composite(view, (index*w, 0))
        zoom.resize((w*12, h*4), Image.Resampling.NEAREST).save(root/f'{name}_400pct.png')
    auto = np.asarray(before) > 12
    contracted = np.asarray(clean_alpha) > 12
    rgb = np.asarray(original)[:, :, :3]
    # Loss map is diagnostic; original pixels are NOT a human-approved mask.
    removed = auto & ~contracted
    nonwhite_removed = removed & (rgb.min(axis=2) < 235)
    loss = np.zeros((421, 421, 4), dtype=np.uint8)
    loss[removed] = [255, 0, 0, 255]
    Image.fromarray(loss).save(diagnostic/'removed_pixels_NOT_GROUND_TRUTH.png')
    summary = dict(source=str(source), sha256=digest, dimensions=list(original.size),
                   original_alpha_extrema=original.getchannel('A').getextrema(),
                   pipeline_module_calls=calls, route=result.analysis.get('case'),
                   grey_halo_review=result.analysis.get('grey_halo_review'),
                   quality=result.analysis.get('quality_report'),
                   native_resolution=result.analysis.get('native_resolution'),
                   module_clean=clean_meta, module_final=final_meta,
                   caveat='Isolated output is NOT the pipeline output and is NOT approved; clean mask may be unchanged.',
                   border_mm=mm, nominal_dpi=300,
                   returned_alpha_matches_rgba=bool(np.array_equal(np.asarray(final_alpha), np.asarray(final.getchannel('A')))),
                   removed_pixels=int(removed.sum()), removed_nonwhite_pixels=int(nonwhite_removed.sum()),
                   manual_reference_approved=False, p1_status='PENDING_HUMAN_REVIEW',
                   production_approved=False, artifacts=result.artifacts,
                   source_unchanged=hashlib.sha256(source.read_bytes()).hexdigest() == digest)
    (root/'audit.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k != 'artifacts'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    run(sys.argv[1])
