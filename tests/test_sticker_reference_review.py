"""Synthetic test approvals below are not approvals of the real disco fixture."""
import json

import pytest
from PIL import Image, ImageDraw

from scripts.sticker_reference_review import prepare, compare, digest, validate_reference


def packet_inputs(tmp_path):
    source=tmp_path/'source.png'
    Image.new('RGB',(100,100),'pink').save(source)
    mask=tmp_path/'automatic.png'
    image=Image.new('L',(100,100))
    ImageDraw.Draw(image).rectangle((10,10,90,90),fill=255)
    image.save(mask)
    metadata=tmp_path/'metadata.json'
    metadata.write_text(json.dumps(dict(artifacts=dict(mask_editable=str(mask),source_hash=digest(source)))),encoding='utf-8')
    return source,mask,metadata


def synthetic_approval(tmp_path,source,mask):
    # Only a synthetic unit-test declaration, never a real reference approval.
    data=dict(approved=True,reviewer='SYNTHETIC TEST ONLY',reviewed_at='2026-10-17T00:00:00+00:00',
              coordinate_space='source',source_sha256=digest(source),mask_path=str(mask),
              mask_sha256=digest(mask),original_dimensions=[100,100])
    path=tmp_path/'approval-test-only.json'
    path.write_text(json.dumps(data),encoding='utf-8')
    return path


def test_prepare_never_creates_reference_or_approval(tmp_path):
    source,mask,metadata=packet_inputs(tmp_path)
    output=tmp_path/'review'
    result=prepare(source,metadata,output)
    assert result['reference_created'] is False and result['reference_approved'] is False
    assert not (output/'mask_reviewed.png').exists()
    assert json.loads((output/'approval_PENDING.json').read_text(encoding='utf-8'))['approved'] is False
    assert (output/'automatic_proposal_NOT_REFERENCE.png').is_file()
    assert (output/'original.png').read_bytes()==source.read_bytes()


def test_pending_reference_cannot_produce_comparison_metrics(tmp_path):
    source,mask,metadata=packet_inputs(tmp_path)
    prepare(source,metadata,tmp_path/'review')
    with pytest.raises(ValueError,match='aprobación humana'):
        compare(source,mask,tmp_path/'review/approval_PENDING.json',tmp_path/'differences')
    assert not (tmp_path/'differences').exists()


def test_comparison_exposes_tiny_local_errors_despite_high_global_overlap(tmp_path):
    source,mask,_=packet_inputs(tmp_path)
    reference=tmp_path/'reference-test-only.png'
    with Image.open(mask) as image:
        image.save(reference)
        image.putpixel((50,50),0)
        image.putpixel((20,20),180)
        image.save(mask)
    approval=synthetic_approval(tmp_path,source,reference)
    result=compare(source,mask,approval,tmp_path/'differences')
    assert result['foreground_iou']>.999
    assert result['missing_pixels']==1
    assert result['partial_alpha_difference_pixels']==1
    assert len(result['difference_regions'])==2
    assert result['boundary_distance_p95_px'] is not None
    assert len(list((tmp_path/'differences').glob('region_*_200pct.png')))==2
    assert result['production_approval'] is False


def test_modified_reference_requires_new_human_approval(tmp_path):
    source,mask,_=packet_inputs(tmp_path)
    approval=synthetic_approval(tmp_path,source,mask)
    with Image.open(mask) as image:
        image.putpixel((50,50),0)
        image.save(mask)
    with pytest.raises(ValueError,match='hash aprobado'):
        validate_reference(source,approval)


def test_wrong_sized_reference_is_rejected_not_resized(tmp_path):
    source,mask,_=packet_inputs(tmp_path)
    Image.new('L',(99,100),128).save(mask)
    approval=synthetic_approval(tmp_path,source,mask)
    with pytest.raises(ValueError,match='Dimensiones distintas'):
        validate_reference(source,approval)


def test_unrelated_same_size_source_cannot_be_attached_to_metadata(tmp_path):
    source,mask,metadata=packet_inputs(tmp_path)
    Image.new('RGB',(100,100),'blue').save(source)
    with pytest.raises(ValueError,match='metadata'):
        prepare(source,metadata,tmp_path/'review')
    assert not (tmp_path/'review').exists()
