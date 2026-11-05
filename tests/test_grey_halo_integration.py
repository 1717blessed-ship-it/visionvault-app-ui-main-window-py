"""Full-flow regression, real fixtures are never treated as approved truth."""
from pathlib import Path
import hashlib

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from app.stickers.pipeline import StickerProcessor, ProcessingResult
from app.stickers.grey_halo_decontamination import (
    complete_grey_halo_elimination_with_white_border, decontaminate_exterior)


FIXTURES = Path(__file__).parent/'fixtures'/'sticker_regression'


@pytest.mark.parametrize('filename', ['disco_checker.png', 'heart_checker.png', 'lips_white.png'])
def test_real_pipeline_evaluates_halo_without_changing_route_or_stacking_white(tmp_path, filename, monkeypatch):
    import app.stickers.grey_halo_decontamination as module
    source = FIXTURES/filename
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    observed = []
    real = module.decontaminate_exterior

    def observe(image, alpha, **kwargs):
        result = real(image, alpha, **kwargs)
        observed.append((alpha.copy(), result[1].copy(), result[2]))
        return result

    monkeypatch.setattr(module, 'decontaminate_exterior', observe)
    result = StickerProcessor(tmp_path/'pipeline').process(source)
    assert result.analysis['case'].startswith('C -')
    assert len(observed) == 1  # Includes recovery: must not replay ambiguous halo.
    before, after, meta = observed[0]
    assert not meta['white_border_generated']
    assert np.all(np.asarray(after) <= np.asarray(before))
    assert not result.analysis['processing_downscaled']
    assert result.analysis['native_resolution']['source_to_native_scale'] == 1
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    restored = ProcessingResult.from_metadata(result.artifacts['metadata'])
    assert restored.analysis['grey_halo_review'] == result.analysis['grey_halo_review']
    for key in ('halo_mask_initial', 'halo_region', 'halo_mask_clean',
                'halo_original_white_border', 'halo_before_printable_border'):
        assert Path(restored.artifacts[key]).is_file()
        with Image.open(restored.artifacts[key]) as artifact, Image.open(source) as original:
            assert artifact.size == original.size
    if filename == 'disco_checker.png':
        assert meta['status'] == 'manual_required'
        assert np.array_equal(np.asarray(before), np.asarray(after))
        assert any(w['code'] == 'halo_manual_review' for w in result.analysis['quality_report']['warnings'])
        assert not result.analysis.get('automatic_recovery')


def drawing(halo=False, stars=False):
    shape = Image.new('L', (240, 240))
    d = ImageDraw.Draw(shape)
    d.ellipse((55, 55, 185, 185), fill=255)
    if stars:
        d.polygon([(185, 20), (190, 45), (215, 50), (190, 55), (185, 80), (180, 55), (155, 50), (180, 45)], fill=255)
        d.line((175, 65, 170, 85), fill=255, width=2)
    base = shape.filter(ImageFilter.MaxFilter(9))
    image = Image.new('RGBA', shape.size)
    if halo:
        image = Image.new('RGBA', shape.size, (150, 150, 150, 255))
        image.putalpha(base.filter(ImageFilter.MaxFilter(7)))
    white = Image.new('RGBA', shape.size, 'white')
    white.putalpha(base)
    image.alpha_composite(white)
    art = Image.new('RGBA', shape.size, '#ec1680')
    art.putalpha(shape)
    image.alpha_composite(art)
    ImageDraw.Draw(image).ellipse((95, 95, 145, 145), fill=(145, 145, 145, 255))
    return image, base


@pytest.mark.parametrize('halo,stars', [(False, False), (True, False), (True, True), (False, True)])
def test_generated_full_flow_preserves_reflections_connections_and_source_alpha(tmp_path, halo, stars):
    image, base = drawing(halo, stars)
    source = tmp_path/'source.png'
    image.save(source)
    result = StickerProcessor(tmp_path/'pipeline').process(source)
    with Image.open(result.artifacts['mask_editable']) as mask:
        # Known valid white, coloured and silver content; never truth from auto.
        known = np.asarray(base) > 0
        assert np.all(np.asarray(mask)[known] > 0)
    assert result.analysis['case'][0] in 'ABC'
    assert result.analysis['native_resolution']['source_to_native_scale'] == 1
    meta = result.analysis['grey_halo_review']
    assert not meta.get('white_border_generated', False)
    assert result.analysis['native_resolution']['border_px'] == 0
    with Image.open(result.artifacts['source_editable']) as saved:
        assert saved.getpixel((120, 120))[:3] == (145, 145, 145)


@pytest.mark.parametrize('existing', [True, False, None])
def test_existing_white_border_cannot_gain_another_thirty_pixels(existing):
    image, _ = drawing(False, True)
    alpha = image.getchannel('A')
    out, mask, meta = complete_grey_halo_elimination_with_white_border(
        image, alpha, white_border_mm=2.54, dpi=300, existing_border=existing)
    assert not meta['white_border_generated']
    assert np.array_equal(np.asarray(mask), np.asarray(alpha))
    assert np.array_equal(np.asarray(out), np.asarray(image))


def test_identified_halo_only_removed_not_global_erosion():
    image, base = drawing(True, True)
    out, mask, meta, candidate, _ = decontaminate_exterior(
        image, image.getchannel('A'), existing_border=True, suspected_halo=True)
    before = np.asarray(image.getchannel('A'))
    after = np.asarray(mask)
    changed = before != after
    assert meta['applied']
    assert changed.any()
    assert np.all(np.asarray(candidate)[changed] > 0)
    assert np.array_equal(after[np.asarray(base)>0], before[np.asarray(base)>0])
    assert not meta['white_border_generated']
    assert np.array_equal(np.asarray(out.getchannel('A')), after)


def test_manual_mask_cannot_be_recleaned(tmp_path):
    image, base = drawing(True, True)
    source, manual = tmp_path/'source.png', tmp_path/'manual.png'
    image.save(source)
    base.save(manual)
    processor = StickerProcessor(tmp_path/'pipeline')
    for _ in range(2):
        result = processor.process(source, mask_override=manual)
        assert not result.analysis['grey_halo_review']['evaluated']
        with Image.open(result.artifacts['mask_editable']) as mask:
            assert np.array_equal(np.asarray(mask), np.asarray(base))


def test_new_border_uses_explicit_effective_dpi_and_has_matching_alpha():
    image = Image.new('RGBA', (100, 100))
    ImageDraw.Draw(image).ellipse((40, 40, 60, 60), fill='red')
    out, alpha, meta = complete_grey_halo_elimination_with_white_border(
        image, image.getchannel('A'), white_border_mm=2.54, dpi=194.2877,
        existing_border=False)
    assert meta['white_border_px'] == 19
    assert np.array_equal(np.asarray(out.getchannel('A')), np.asarray(alpha))
