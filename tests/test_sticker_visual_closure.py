"""Properties of bounded local proposals; not semantic/physical approvals."""
import json
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.stickers.pipeline import StickerProcessor, ProcessingResult, ProcessingCancelled
from app.stickers.models import CreationMode
from app.stickers.background_refinement import variable_background_proposal
from scripts.validate_sticker_visuals import synthetic


@pytest.mark.parametrize('category', ['fotografia','ilustracion_compleja','fondo_degradado_texturizado'])
@pytest.mark.parametrize('complex_case', [False,True])
def test_variable_background_proposal_removes_background_without_losing_holes_or_tail(tmp_path, category, complex_case):
    image, truth = synthetic(category, complex_case)
    source = tmp_path/'source.png'
    image.save(source)
    before = source.read_bytes()
    result = StickerProcessor(tmp_path/'work').process(source)
    assert result.analysis['case'].startswith('C - ')
    assert result.analysis['background_refinement']['status']=='proposal_requires_review'
    assert result.analysis['background_refinement']['seed_agreement_iou'] >= .995
    with Image.open(result.artifacts['mask_editable']) as mask:
        actual = np.asarray(mask)>12
        expected = np.asarray(truth)>12
        assert (actual&expected).sum()/(actual|expected).sum() > .995
        assert not actual[10,10]
        if complex_case:
            assert not actual[160,220]  # Negative space remains a hole.
            assert actual[164,410]     # Thin legitimate tail survives.
    for key in ('background_initial_alpha','background_candidate_1','background_candidate_2'):
        with Image.open(result.artifacts[key]) as mask:
            assert mask.size == image.size
    assert source.read_bytes()==before
    restored = ProcessingResult.from_metadata(result.artifacts['metadata'])
    assert restored.analysis['background_refinement']==result.analysis['background_refinement']
    assert restored.artifacts['background_initial_alpha']==result.artifacts['background_initial_alpha']
    assert result.quality_status == 'Revisar'


def test_disagreeing_proposals_require_manual_review_and_retain_both_masks(tmp_path):
    processor = StickerProcessor(tmp_path/'work')
    first = Image.new('L',(100,100))
    second = Image.new('L',(100,100))
    ImageDraw.Draw(first).ellipse((10,10,60,60),fill=255)
    ImageDraw.Draw(second).ellipse((40,40,90,90),fill=255)
    with patch.object(processor,'_refine_checkerboard_alpha',side_effect=[first,second]):
        proposal, diagnostic, candidates = variable_background_proposal(processor,Image.new('RGB',(100,100),'white'))
    assert proposal is None
    assert diagnostic['status']=='manual_required'
    assert len(candidates)==2
    assert candidates[0].tobytes()!=candidates[1].tobytes()


def test_failed_grabcut_rectangular_seed_is_not_accepted_as_foreground(tmp_path):
    processor = StickerProcessor(tmp_path/'work')
    with patch.object(processor,'_refine_checkerboard_alpha',side_effect=lambda _image, seed: seed):
        proposal, diagnostic, candidates = variable_background_proposal(processor,Image.new('RGB',(200,180),'white'))
    assert proposal is None
    assert diagnostic['status']=='manual_required'
    assert len(candidates)==2


@pytest.mark.parametrize('full_image', [False,True])
def test_manual_alpha_and_full_image_never_use_automatic_background_proposals(tmp_path, full_image):
    image, _ = synthetic('fondo_degradado_texturizado',True)
    source = tmp_path/'source.png'
    image.save(source)
    mask = Image.new('L',image.size,120)
    ImageDraw.Draw(mask).ellipse((180,120,270,220),fill=0)
    manual = tmp_path/'manual.png'
    mask.save(manual)
    before = manual.read_bytes()
    options = ({'creation_mode':CreationMode.FULL_IMAGE.value} if full_image else {'mask_override':manual})
    with patch('app.stickers.background_refinement.variable_background_proposal',side_effect=AssertionError('must not run')):
        result = StickerProcessor(tmp_path/'work').process(source,**options)
    assert not result.analysis['background_refinement']
    if not full_image:
        with Image.open(result.artifacts['mask_editable']) as output:
            assert output.tobytes()==mask.tobytes()
    assert manual.read_bytes()==before


def test_cancellation_between_local_proposals_preserves_previous_run(tmp_path):
    image, _ = synthetic('fondo_degradado_texturizado',False)
    source = tmp_path/'source.png'
    image.save(source)
    processor = StickerProcessor(tmp_path/'work')
    prior = processor.process(source,creation_mode=CreationMode.FULL_IMAGE.value)
    previous = set(processor.workspace.iterdir())
    cancel = [False]
    def progress(_percent, message):
        if 'propuesta local' in message:
            cancel[0]=True
    with pytest.raises(ProcessingCancelled):
        processor.process(source,progress=progress,cancelled=lambda:cancel[0])
    assert set(processor.workspace.iterdir())==previous
    assert ProcessingResult.from_metadata(prior.artifacts['metadata']).job_id==prior.job_id


def test_proposal_reprocessing_keeps_geometry_and_original_files(tmp_path):
    image, _ = synthetic('fondo_degradado_texturizado',True)
    source=tmp_path/'source.png'
    image.save(source)
    processor=StickerProcessor(tmp_path/'work')
    first=processor.process(source)
    old_metadata=open(first.artifacts['metadata'],encoding='utf-8').read()
    second=processor.process(source)
    with Image.open(first.artifacts['mask_editable']) as a, Image.open(second.artifacts['mask_editable']) as b:
        assert np.array_equal(np.asarray(a)>12,np.asarray(b)>12)
    assert first.job_id!=second.job_id
    assert json.loads(open(first.artifacts['metadata'],encoding='utf-8').read())==json.loads(old_metadata)


def test_disco_wider_candidate_is_saved_for_review_never_applied(tmp_path):
    from pathlib import Path
    source=Path(__file__).parent/'fixtures/sticker_regression/disco_checker.png'
    processor=StickerProcessor(tmp_path/'work')
    result=processor.process(source,automatic_recovery=False)
    assert result.analysis['checkerboard_review']['wider_candidate_selected'] is False
    assert result.analysis['checkerboard_review']['status']=='manual_required'
    with Image.open(result.artifacts['checkerboard_initial_alpha']) as original, Image.open(result.artifacts['mask_editable']) as mask:
        import cv2
        reference=np.asarray(original)
        core=cv2.distanceTransform((reference>12).astype('uint8'),cv2.DIST_L2,5)>3
        assert (np.asarray(mask)[core]>12).mean()>.999
    with Image.open(result.artifacts['checkerboard_segmentation_candidate']) as candidate:
        assert candidate.size==(421,421)
    reopened=ProcessingResult.from_metadata(result.artifacts['metadata'])
    assert reopened.analysis['checkerboard_review']==result.analysis['checkerboard_review']
