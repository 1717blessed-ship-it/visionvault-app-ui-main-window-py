"""Convierte descripciones de IA en etiquetas de búsqueda independientes."""

from __future__ import annotations

import re


_STOP_WORDS = frozenset({
    "a", "al", "con", "de", "del", "el", "ella", "en", "es", "la", "las",
    "los", "o", "por", "un", "una", "uno", "y", "the", "with", "of", "on",
    "sticker", "pegatina", "diseño", "imagen", "pintura", "palabra",
})
_RELATED_TAGS = {
    "joker": ("Batman", "Risa"),
    "batman": ("Joker", "DC Comics"),
}


def individual_tags(*values: str) -> list[str]:
    """Devuelve palabras/ideas buscables, no una oración completa."""
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        for word in re.findall(r"[A-Za-zÀ-ÿ0-9]+", str(value or "")):
            key = word.casefold()
            if len(word) < 3 or key in _STOP_WORDS or key in seen:
                continue
            seen.add(key)
            tags.append(word[:1].upper() + word[1:])
    for tag in list(tags):
        for related in _RELATED_TAGS.get(tag.casefold(), ()):
            if related.casefold() not in seen:
                seen.add(related.casefold())
                tags.append(related)
    return tags
