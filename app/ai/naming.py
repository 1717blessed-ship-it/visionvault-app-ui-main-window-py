"""Nombres y categorías claras en español para la biblioteca de stickers."""

import re


CATEGORIES = {
    "Deportes": ("fútbol", "futbol", "pelota", "deporte", "club", "basket", "tenis"),
    "Música": ("música", "musica", "guitarra", "banda", "micrófono", "vinilo"),
    "Comida y bebida": ("comida", "pizza", "café", "cafe", "cerveza", "hamburguesa"),
    "Animales": ("perro", "gato", "animal", "pájaro", "pajaro", "pez", "conejo"),
    "Amor y amistad": ("amor", "corazón", "corazon", "beso", "pareja", "románt"),
    "Humor y memes": ("meme", "gracioso", "humor", "caricatura"),
    "Tecnología": ("computadora", "celular", "tecnología", "tecnologia", "robot", "internet"),
    "Viajes y países": ("argentina", "italia", "alemania", "bandera", "país", "pais", "viaje"),
    "Logotipos y marcas": ("logo", "logotipo", "marca", "símbolo", "simbolo"),
}


def sticker_names(description: str, ocr_text: str, reference: dict | None = None) -> tuple[str, list[str]]:
    """Propone nombres comprensibles en Argentina y una categoría general."""
    raw = description.strip()
    raw = re.sub(r"^(una?|el|la)\s+(pegatina|sticker)\s+(de|con)\s+", "", raw, flags=re.I)
    raw = re.sub(r"^(el|la)\s+logotipo\s+de\s+", "Logo ", raw, flags=re.I)
    raw = re.sub(r"^logotipo\s+de\s+", "Logo ", raw, flags=re.I)
    raw = re.sub(r"\s+", " ", raw).strip(" .")
    if not raw:
        raw = "Diseño sin descripción"
    base = raw[:1].upper() + raw[1:]
    context = f"{base} {ocr_text}".lower()
    category = next((name for name, keywords in CATEGORIES.items() if any(word in context for word in keywords)), "Diseños e ilustraciones")
    if reference:
        category = reference["category"]
        base = f"{reference['name']} - {reference['detail']}"
        if reference["name"] == "Alexis Mac Allister":
            names = [
                "Casaca de Mac Allister 20",
                "Selección Argentina - Mac Allister 20",
                "Campeones del Mundo - Mac Allister 20",
                "Alexis Mac Allister - Selección Argentina",
            ]
            return category, names
        if reference["name"] == "Argentina":
            names = [
                "Mapa de Argentina con bandera",
                "Argentina - Celeste y blanca",
                "Orgullo argentino",
                "Bandera de Argentina",
            ]
            return category, names
        if reference["name"] == "Selección Argentina":
            return category, [
                "Selección Argentina",
                "Escudo de la Selección Argentina",
                "Hecho en Argentina",
            ]
    names = [base]
    clean_ocr = [word.strip() for word in ocr_text.split("·") if len(word.strip()) >= 3]
    if clean_ocr:
        words = " ".join(clean_ocr[:3])
        names.extend((words, f"{base} - {words}"))
    return category, list(dict.fromkeys(names))
