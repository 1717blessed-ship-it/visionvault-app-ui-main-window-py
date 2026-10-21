"""Conservative exterior-halo geometry. No image classification or white rendering."""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


def exterior_regions(image, alpha):
    """White and chromatic pixels are barriers; enclosed greys are not background.

    This produces a *proposal*, not a human reference. A narrow search limit is
    a safety bound, never an erosion radius. Holes are not exterior seeds.
    """
    rgb = np.asarray(image.convert('RGB'), dtype=np.int16)
    a = np.asarray(alpha.convert('L'), dtype=np.uint8)
    visible = a > 12
    neutral = rgb.max(2) - rgb.min(2) <= 20
    white = neutral & (rgb.min(2) >= 235) & visible
    grey = neutral & (rgb.min(2) >= 80) & (rgb.max(2) <= 230)
    passable = (~visible | grey).astype(np.uint8)
    count, labels = cv2.connectedComponents(passable, connectivity=8)
    seeds = np.unique(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])))
    seeds = seeds[seeds != 0]
    exterior = np.isin(labels, seeds) if count > 1 else np.zeros_like(visible)
    # Pad explicitly: objects touching the canvas must not get an implicit rim.
    distance = cv2.distanceTransform(np.pad(visible.astype(np.uint8), 1), cv2.DIST_L2, 5)[1:-1, 1:-1]
    limit = min(12, max(8, round(max(a.shape) * .03)))
    white_distance = cv2.distanceTransform((~white).astype(np.uint8), cv2.DIST_L2, 5)
    candidate = grey & visible & exterior & (distance <= limit) & (white_distance <= limit)
    # Never consume coloured/dark artwork or grey attached directly to it.
    artwork = visible & ~white & ~grey
    protected = cv2.dilate(artwork.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    ambiguous = candidate & protected
    candidate &= ~protected
    edge = visible & (distance <= 1.01)
    white_edge_ratio = float((white & edge).sum() / max(1, edge.sum()))
    thickness = float(distance[candidate].max()) if candidate.any() else 0.0
    return candidate, white, dict(
        candidate_pixels=int(candidate.sum()), ambiguous_pixels=int(ambiguous.sum()),
        grey_ratio=float((grey & edge).sum() / max(1, edge.sum())),
        white_edge_ratio=white_edge_ratio,
        estimated_thickness_px=int(np.ceil(thickness)),
        has_grey_halo=bool(candidate.any()),
        safe_to_contract=bool(candidate.any() and not ambiguous.any()),
    )


def decontaminate_exterior(image, alpha, *, existing_border=False,
                          checkerboard=False, suspected_halo=False, protected_mask=None):
    """Optional common-stage operation, never constructs an additional border.

    Embedded checkerboard plus neutral artwork is intentionally review-only:
    its colour/connectivity is not enough to certify a real outer halo.
    """
    candidate, white, detection = exterior_regions(image, alpha)
    before = np.asarray(alpha.convert('L'), dtype=np.uint8)
    clean = before.copy()
    reason = None
    if checkerboard:
        reason = 'embedded_checkerboard_requires_manual_reference'
    elif detection['ambiguous_pixels']:
        reason = 'halo_touches_possible_artwork'
    elif suspected_halo and not candidate.any():
        reason = 'suspected_halo_not_identified'
    elif candidate.any() and not suspected_halo:
        reason = 'grey_pixels_alone_do_not_authorize_removal'
    elif candidate.any() and not (existing_border or detection['white_edge_ratio'] > .2):
        # A grey drawing itself must not activate cleaning on colour alone.
        reason = 'white_border_not_confirmed'
    else:
        if protected_mask is not None:
            candidate &= np.asarray(protected_mask.convert('L')) == 0
        clean[candidate] = 0
        # A local area loss or a topology change demands a person, not erosion.
        old_n = cv2.connectedComponents((before > 12).astype(np.uint8), connectivity=8)[0]
        new_n = cv2.connectedComponents((clean > 12).astype(np.uint8), connectivity=8)[0]
        ratio = float((clean > 12).sum() / max(1, (before > 12).sum()))
        if (before > 12).any() and (ratio < .85 or new_n != old_n):
            reason = 'local_detail_or_topology_requires_review'
            clean = before.copy()
    if reason:
        clean = before.copy()
    result_alpha = Image.fromarray(clean)
    result = image.convert('RGBA').copy()
    result.putalpha(result_alpha)
    removed = (before > 0) & (clean == 0)
    metadata = dict(
        evaluated=True, status='manual_required' if reason else 'cleaned' if removed.any() else 'no_halo_identified',
        reason=reason, detection=detection,
        applied=bool(removed.any()), removed_pixels=int(removed.sum()),
        contraction_mode='identified_exterior_pixels_only',
        white_border_generated=False, white_border_px=0,
        border_policy='preserve_existing' if existing_border else 'downstream_renderer',
        requires_review=bool(reason),
    )
    return result, result_alpha, metadata, Image.fromarray(candidate.astype(np.uint8)*255), Image.fromarray(white.astype(np.uint8)*255)


def confirmed_white_border(image, alpha):
    """Conservative rendering signal, not another visual/technical class."""
    candidate, _, info = exterior_regions(image, alpha)
    rgb = np.asarray(image.convert('RGB'), dtype=np.int16)
    chromatic = (rgb.max(2)-rgb.min(2) > 40) & (np.asarray(alpha) > 127)
    ratio = info['white_edge_ratio']
    if candidate.any() and not info['ambiguous_pixels']:
        potential = np.asarray(alpha).copy()
        potential[candidate] = 0
        ratio = max(ratio, exterior_regions(image, Image.fromarray(potential))[2]['white_edge_ratio'])
    return bool(ratio >= .85 and chromatic.any())
