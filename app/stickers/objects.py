"""Correspondencia conservadora de objetos entre corridas alineadas."""
from pathlib import Path

import numpy as np
from PIL import Image


def match_object_ids(masks, previous):
    """Reutiliza IDs solo con solapamiento concluyente y correspondencia única.

    Un cambio de encuadre requiere revisión; no se fuerza una coincidencia
    por orden, color o tamaño. Los identificadores retirados no se reciclan.
    """
    previous = previous or []
    next_id = max((int(item["id"]) for item in previous), default=0) + 1
    references = []
    for item in previous:
        path = item.get("artifact", "")
        if path and Path(path).exists():
            with Image.open(path) as image:
                references.append((int(item["id"]), np.asarray(image.convert("L")) > 12))
    used = set()
    result = []
    ambiguous = False
    for mask in masks:
        current = np.asarray(mask.convert("L")) > 12
        ranked = []
        for identifier, reference in references:
            if reference.shape != current.shape:
                continue
            union = int((current | reference).sum())
            score = float((current & reference).sum() / max(union, 1))
            ranked.append((score, identifier))
        ranked.sort(reverse=True)
        reliable = (ranked and ranked[0][0] >= .65
                    and (len(ranked) < 2 or ranked[0][0] - ranked[1][0] >= .2)
                    and ranked[0][1] not in used)
        if reliable:
            identifier = ranked[0][1]
        else:
            identifier = next_id
            next_id += 1
            ambiguous = ambiguous or bool(previous)
        used.add(identifier)
        result.append(identifier)
    return result, ambiguous
