"""Lectura de etiquetas XMP/IPTC exportadas por gestores de imágenes."""
import html
import re
from pathlib import Path


def _subject_values(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        values = []
        for item in value:
            values.extend(_subject_values(item))
        return values
    if isinstance(value, dict):
        values = []
        for item in value.values():
            values.extend(_subject_values(item))
        return values
    return []


def read_file_tags(path: str | Path) -> set[str]:
    """Extrae palabras clave XMP (incluye las exportadas por Allusion)."""
    try:
        from PIL import Image

        with Image.open(path) as image:
            xmp = image.getxmp() if hasattr(image, "getxmp") else {}
            raw = image.info.get("xmp", image.info.get("XML:com.adobe.xmp", b""))
    except Exception:
        return set()

    tags = []
    if isinstance(xmp, dict):
        for key, value in xmp.items():
            if any(word in key.lower() for word in ("subject", "keyword", "tag")):
                tags.extend(_subject_values(value))

    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="ignore")
    if isinstance(raw, str):
        for section in re.findall(r"<(?:\w+:)?(?:subject|Keywords)[^>]*>(.*?)</(?:\w+:)?(?:subject|Keywords)>", raw, flags=re.DOTALL | re.IGNORECASE):
            tags.extend(re.findall(r"<(?:\w+:)?li[^>]*>(.*?)</(?:\w+:)?li>", section, flags=re.DOTALL | re.IGNORECASE))

    return {html.unescape(re.sub(r"<[^>]+>", "", tag)).strip() for tag in tags if tag and tag.strip()}
