"""Bounded proposals using the existing local GrabCut implementation.

These are review proposals, not semantic certainty or production approvals.
No model downloads, global morphology, or source image writes.
"""
import cv2
import numpy as np
from PIL import Image


def variable_background_proposal(processor, image, progress=lambda *_: None):
    """Require agreement between two independent rectangular background seeds."""
    width, height = image.size
    masks = []
    if min(width, height) < 48:
        return None, {"status": "manual_required", "reason": "small_source"}, masks
    for margin in (max(2, min(width, height)//72), max(4, min(width, height)//36)):
        progress(24, 'Evaluando propuesta local de fondo variable')
        seed = Image.new('L', image.size)
        seed.paste(255, (margin, margin, width-margin, height-margin))
        masks.append(processor._refine_checkerboard_alpha(image, seed))
    a, b = (np.asarray(mask)>12 for mask in masks)
    union = int((a|b).sum())
    overlap = float((a&b).sum()/max(1,union))
    fraction = float(a.mean())
    frame_contact = bool(a[0].any() or a[-1].any() or a[:,0].any() or a[:,-1].any())
    # A failed GrabCut returns its rectangular seed. Do not call agreement or
    # a large rectangle a trustworthy foreground, even when both runs agree.
    count, _, stats, _ = cv2.connectedComponentsWithStats(a.astype('uint8'), 8)
    rectangular = count == 2 and int(stats[1,4]) == int(stats[1,2])*int(stats[1,3])
    accepted = overlap >= .995 and .01 < fraction < .85 and not frame_contact and not rectangular
    info = dict(status='proposal_requires_review' if accepted else 'manual_required',
                method='existing_local_grabcut', seed_agreement_iou=overlap,
                foreground_fraction=fraction, frame_contact=frame_contact,
                reason='stable_local_proposal' if accepted else 'ambiguous_or_failed_segmentation')
    return masks[0] if accepted else None, info, masks


