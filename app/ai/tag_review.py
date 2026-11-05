"""Helpers for reviewing AI-generated library tags before saving them."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


_STYLE_WORDS = frozenset({
    "kawaii", "retro", "vintage", "minimalista", "minimal", "cartoon",
    "anime", "realista", "acuarela", "neon", "neón", "glitter",
})
_COLOR_WORDS = frozenset({
    "rojo", "azul", "verde", "amarillo", "negro", "blanco", "rosa",
    "violeta", "naranja", "dorado", "plateado", "multicolor",
})
_FORM_WORDS = frozenset({
    "circular", "redondo", "cuadrado", "rectangular", "troquelado",
    "contorno", "corazon", "corazón", "estrella",
})


def normalize_tag(value: str) -> str:
    """Returns a comparison key while preserving the user-facing spelling elsewhere."""
    folded = unicodedata.normalize("NFKD", value.strip().casefold())
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", folded)


def tag_group(tag: str) -> str:
    """Places a suggestion in a compact, user-facing review group."""
    words = set(normalize_tag(tag).split())
    if words & _COLOR_WORDS:
        return "Color"
    if words & _FORM_WORDS:
        return "Forma"
    if words & _STYLE_WORDS:
        return "Estilo"
    return "Tema y busqueda"


def review_suggestions(suggestions: Iterable[str], existing_tags: Iterable[str], dismissed: Iterable[str] = ()) -> list[dict[str, str | bool]]:
    """Deduplicates AI proposals and identifies an existing equivalent tag.

    The caller keeps control of acceptance; this function never persists data.
    """
    existing_by_key = {normalize_tag(tag): tag for tag in existing_tags if tag.strip()}
    dismissed_keys = {normalize_tag(tag) for tag in dismissed}
    seen: set[str] = set()
    result: list[dict[str, str | bool]] = []
    for raw_tag in suggestions:
        tag = str(raw_tag).strip()
        key = normalize_tag(tag)
        if not key or key in seen or key in dismissed_keys:
            continue
        seen.add(key)
        equivalent = existing_by_key.get(key, "")
        result.append({
            "tag": equivalent or tag,
            "source_tag": tag,
            "existing": bool(equivalent),
            "group": tag_group(equivalent or tag),
        })
    return result
