"""Properties for reported visual defects, not golden-image approvals."""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.stickers.pipeline import StickerProcessor
from app.stickers.models import CreationMode
from scripts.validate_sticker_visuals import synthetic


@pytest.mark.parametrize('kind', ['fondo_neutro', 'fondo_color'])
@pytest.mark.parametrize('complex_case', [False, True])
def test_vv01_saturated_regions_survive_background_removal(tmp_path, kind, complex_case):
    image, truth = synthetic(kind, complex_case)
    source = tmp_path/'source.png'
    image.save(source)
    before = source.read_bytes()
    result = StickerProcessor(tmp_path/'work').process(source, automatic_recovery=False)
    with Image.open(result.artifacts['mask_editable']) as mask:
        arr = np.asarray(mask)
        assert arr[160,140] == 255  # Pink pigment, not just yellow stripe.
        assert arr[10,10] == 0     # No recovery of exterior background.
        expected = np.asarray(truth)>12
        actual = arr>12
        assert (expected & actual).sum()/max(1,expected.sum()) > .99
    assert source.read_bytes() == before


@pytest.mark.parametrize('kind', ['arte_transparente', 'sticker_terminado', 'semitransparencias', 'borde_color'])
def test_vv02_visual_alpha_holes_and_partial_alpha_survive_reprocess(tmp_path, kind):
    image, truth = synthetic(kind, True)
    source = tmp_path/'source.png'
    image.save(source)
    processor = StickerProcessor(tmp_path/'work')
    for _ in range(2):
        result = processor.process(source)
        with Image.open(result.artifacts['mask_editable']) as actual:
            assert np.array_equal(np.asarray(actual), np.asarray(truth))
        with Image.open(result.artifacts['native_printable_base']) as base:
            assert base.getpixel((base.width//2,base.height//2)) == 255
        assert not result.analysis['png_holes_filled_white']
        if kind == 'sticker_terminado':
            assert result.analysis['native_resolution']['border_px'] == 0


def test_vv04_selected_small_object_does_not_flatten_at_canvas_boundary(tmp_path):
    image, _ = synthetic('multiples_objetos', False)
    source = tmp_path/'objects.png'
    image.save(source)
    processor = StickerProcessor(tmp_path/'work')
    first = processor.process(source, creation_mode=CreationMode.MULTI_OBJECT.value)
    selected = processor.process(source, creation_mode=CreationMode.MULTI_OBJECT.value,
                                 selected_component_ids=[1],
                                 previous_object_components=first.analysis['object_components'])
    for key in ('native_printable_base', 'native_cut'):
        with Image.open(selected.artifacts[key]) as mask:
            box = mask.getbbox()
            assert box[1] > 0 and box[3] < mask.height
            # A rounded cap is narrower than the middle section.
            arr = np.asarray(mask)>127
            assert arr[box[1]].sum() < arr[mask.height//2].sum()*.5
    assert [c['id'] for c in selected.analysis['object_components']] == [1,2,3]


def test_vv08_invalid_manual_cut_is_reported_without_changing_design_or_mask(tmp_path):
    image, _ = synthetic('imagen_completa', False)
    source = tmp_path/'source.png'
    image.save(source)
    processor = StickerProcessor(tmp_path/'work')
    first = processor.process(source, creation_mode=CreationMode.FULL_IMAGE.value)
    with Image.open(first.artifacts['cut']) as original:
        cut = Image.new('L', original.size)
        ImageDraw.Draw(cut).ellipse((60,60,cut.width-61,cut.height-61), fill=255)
    path = tmp_path/'manual.png'
    cut.save(path)
    before = path.read_bytes()
    second = processor.process(source, creation_mode=CreationMode.FULL_IMAGE.value, cut_mask_override=path)
    assert 'cut_outside_base' in {x['code'] for x in second.analysis['quality_report']['errors']}
    assert second.quality_status == 'Error'
    with Image.open(first.artifacts['native_master']) as a, Image.open(second.artifacts['native_master']) as b:
        assert a.tobytes() == b.tobytes()
    assert path.read_bytes() == before


def test_valid_manual_cut_inside_base_is_not_rejected(tmp_path):
    image, _ = synthetic('arte_transparente', False)
    source = tmp_path/'source.png'
    image.save(source)
    processor = StickerProcessor(tmp_path/'work')
    first = processor.process(source)
    second = processor.process(source, cut_mask_override=first.artifacts['cut'])
    assert not second.analysis['quality_report']['errors']


def test_vv03_complex_background_remains_explicitly_unresolved(tmp_path):
    image, _ = synthetic('fondo_degradado_texturizado', True)
    source = tmp_path/'gradient.png'
    image.save(source)
    result = StickerProcessor(tmp_path/'work').process(source)
    assert any('Fondo variable' in x['message'] for x in result.analysis['quality_report']['warnings'])
    assert result.analysis['complex_background_unresolved']
    assert 'automatic_recovery' not in result.analysis


def test_vv05_checker_cleanup_cannot_erase_silver_or_star_cores(tmp_path):
    source = Path(__file__).parent/'fixtures/sticker_regression/disco_checker.png'
    with Image.open(source) as image:
        raw = StickerProcessor._checkerboard_exterior_alpha(image)
    result = StickerProcessor(tmp_path/'work').process(source, automatic_recovery=False)
    import cv2
    arr = np.asarray(raw)
    core = cv2.distanceTransform((arr>12).astype(np.uint8), cv2.DIST_L2, 5)>3
    with Image.open(result.artifacts['mask_editable']) as mask:
        actual = np.asarray(mask)
        # Existing isolated-speck cleanup may affect small detached debris, not
        # the interiors of the sphere and its intentional decorative stars.
        assert (actual[core]>12).mean() > .999
        assert actual[0,0] == 0
