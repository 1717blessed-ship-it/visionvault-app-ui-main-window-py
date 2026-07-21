"""Referencias culturales detectadas de manera conservadora a partir de IA y OCR."""

import re
import unicodedata


REFERENCES = (
    ("Selección Argentina", "Fútbol", "Argentina", "Escudo de la Selección Argentina", ("selección", "fútbol", "argentina"), 2),
    ("Argentina", "País", "Argentina", "Mapa y bandera argentina", ("argentina", "bandera", "celeste", "mapa"), 2),
    ("Alexis Mac Allister", "Futbolista", "Fútbol argentino", "Casaca de Mac Allister 20", ("mac allister",), 1),
    ("Zootopia", "Película", "Películas y series", "Nick Wilde y Judy Hopps", ("zorro", "conejo", "liebre", "judy", "nick"), 2),
    ("Los Simpson", "Serie", "Películas y series", "Personajes de Springfield", ("simpson", "homero", "bart", "marge", "lisa"), 1),
    ("Shrek", "Película", "Películas y series", "Personajes de Shrek", ("shrek", "burro", "fiona", "ogro"), 1),
    ("Dragon Ball", "Anime", "Anime y manga", "Personaje de Dragon Ball", ("dragon ball", "goku", "vegeta", "saiyan"), 1),
    ("Naruto", "Anime", "Anime y manga", "Personaje de Naruto", ("naruto", "sasuke", "kakashi", "hokage"), 1),
    ("One Piece", "Anime", "Anime y manga", "Personaje de One Piece", ("one piece", "luffy", "zoro", "chopper"), 1),
    ("Spider-Man", "Película", "Cómics y superhéroes", "Personaje de Spider-Man", ("spider", "spiderman", "hombre araña", "peter parker"), 1),
    ("Star Wars", "Película", "Películas y series", "Personaje de Star Wars", ("star wars", "darth", "yoda", "jedi", "stormtrooper"), 1),
    ("Harry Potter", "Película", "Películas y series", "Personaje de Harry Potter", ("harry potter", "hogwarts", "gryffindor", "hermione"), 1),
    ("Vans", "Marca", "Logotipos y marcas", "Logo de Vans", ("vans",), 1),
    ("Hello Kitty", "Personaje", "Personajes", "Personaje de Hello Kitty", ("hello kitty", "kitty"), 1),
)

SEARCH_TERMS = {
    "Selección Argentina": "Selección Argentina · fútbol argentino · celeste y blanca · hecho en Argentina",
    "Argentina": "Argentina · bandera argentina · celeste y blanca · mapa de Argentina",
    "Alexis Mac Allister": "Alexis Mac Allister · Selección Argentina · fútbol argentino · campeones del mundo",
    "Zootopia": "Zootopia · Nick Wilde · Judy Hopps · película animada",
}


def _plain(text: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFD", text.casefold()) if not unicodedata.combining(char))


def cultural_references(description: str, text: str) -> list[dict]:
    source = _plain(f"{description} {text}")
    found = []
    for name, kind, category, detail, keywords, required in REFERENCES:
        hits = sum(bool(re.search(rf"(?<!\w){re.escape(_plain(word))}(?!\w)", source)) for word in keywords)
        if hits >= required:
            found.append({"name": name, "kind": kind, "category": category, "detail": detail, "search_terms": SEARCH_TERMS.get(name, f"{name} · {category} · {detail}")})
    return found
