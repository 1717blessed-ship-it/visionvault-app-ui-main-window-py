"""Exterior-only halo removal, separate from the single printable-border renderer.

Colour is evidence, not permission to erase grey artwork. No global erosion.
"""
from __future__ import annotations

import logging
import numpy as np
from PIL import Image

from .halo_geometry import exterior_regions, decontaminate_exterior, confirmed_white_border

logger = logging.getLogger(__name__)


def detect_grey_halo_thickness(image, alpha):
    """Measure identified exterior pixels, not the cumulative eroded interior."""
    return exterior_regions(image, alpha)[2]


def complete_grey_halo_elimination_with_white_border(
        image, alpha, contraction_px=None, preserve_detail_threshold=.15,
        white_border_mm=1.5, dpi=300, generate_white_border=True,
        *, existing_border=None):
    """Compatibility API; production uses decontaminate_exterior without a border.

    A caller must explicitly declare existing_border=False to render new white.
    Ambiguous white is preserved, never expanded. contraction_px is only a
    maximum allowed depth, not a request for indiscriminate erosion.
    """
    import cv2
    candidate, white, detection = exterior_regions(image, alpha)
    a = np.asarray(alpha.convert('L'), dtype=np.uint8)
    metadata = dict(halo_detected=detection['has_grey_halo'],
                    halo_thickness_estimated_px=detection['estimated_thickness_px'],
                    grey_ratio=detection['grey_ratio'], contraction_applied_px=0,
                    white_border_generated=False, white_border_px=0,
                    area_preserved_ratio=1.0, warnings=[], requires_review=False,
                    border_policy='preserve_existing_or_ambiguous')
    rgba = image.convert('RGBA').copy()
    rgba.putalpha(alpha)
    if detection['ambiguous_pixels']:
        metadata.update(requires_review=True, status='manual_required')
        metadata['warnings'].append('Halo en contacto con posible contenido legítimo.')
        return rgba, alpha.copy(), metadata
    if contraction_px is not None and detection['estimated_thickness_px'] > contraction_px:
        metadata.update(requires_review=True, status='manual_required')
        metadata['warnings'].append('Región contaminada supera el límite indicado.')
        return rgba, alpha.copy(), metadata
    clean = a.copy()
    clean[candidate] = 0
    old_n = cv2.connectedComponents((a > 12).astype(np.uint8), connectivity=8)[0]
    new_n = cv2.connectedComponents((clean > 12).astype(np.uint8), connectivity=8)[0]
    ratio = float((clean > 12).sum()/max(1, (a > 12).sum()))
    # The legacy area threshold cannot authorize destroying small components.
    if new_n != old_n or ratio < max(.5, preserve_detail_threshold):
        metadata.update(requires_review=True, status='manual_required')
        metadata['warnings'].append('La propuesta altera componentes o pierde demasiado contenido.')
        return rgba, alpha.copy(), metadata
    clean_alpha = Image.fromarray(clean)
    rgba.putalpha(clean_alpha)
    metadata.update(contraction_applied_px=detection['estimated_thickness_px'] if candidate.any() else 0,
                    area_preserved_ratio=ratio,
                    status='cleaned' if candidate.any() else 'no_halo_identified')
    if generate_white_border and existing_border is False and not confirmed_white_border(image, alpha):
        if not np.isfinite(dpi) or dpi <= 0 or white_border_mm < 0:
            raise ValueError('Resolución física y borde deben ser válidos.')
        pixels = max(0, round(white_border_mm * dpi / 25.4))
        rgba, clean_alpha = _generate_white_border_only(rgba, clean_alpha, pixels)
        metadata.update(white_border_generated=bool(pixels), white_border_px=pixels,
                        border_policy='generate_once_from_declared_content')
    return rgba, clean_alpha, metadata


def _generate_white_border_only(image, alpha, white_border_px):
    import cv2
    a = np.asarray(alpha.convert('L'), dtype=np.uint8)
    pixels = max(0, int(white_border_px))
    if not pixels:
        result = image.convert('RGBA').copy()
        result.putalpha(alpha)
        return result, alpha.copy()
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (pixels*2+1, pixels*2+1))
    base = cv2.dilate(a, kernel)
    background = Image.new('RGBA', image.size, 'white')
    background.putalpha(Image.fromarray(base))
    design = image.convert('RGBA').copy()
    design.putalpha(alpha)
    background.alpha_composite(design)
    return background, background.getchannel('A')


def eliminate_grey_halo_by_mask_contraction(image, alpha, contraction_px=None,
                                            preserve_detail_threshold=.15):
    result, clean, _ = complete_grey_halo_elimination_with_white_border(
        image, alpha, contraction_px, preserve_detail_threshold,
        generate_white_border=False)
    return result, clean


def decontaminate_grey_halo_precise(image, alpha, outer_band_width=8,
                                  grey_threshold_low=100, grey_threshold_high=210):
    logger.warning('Deprecated compatibility entry point; no global contraction.')
    return eliminate_grey_halo_by_mask_contraction(image, alpha, outer_band_width)[0]
