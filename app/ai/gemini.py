"""Análisis de stickers mediante la API de Gemini."""

import json
import re
import base64
from io import BytesIO
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def analyze_image(path: str, api_key: str, model: str, progress=None) -> dict:
    progress = progress or (lambda _message: None)
    # Mantener el mismo contrato para éxitos, claves ausentes y errores de
    # red. Así la interfaz puede siempre mostrar un resultado informativo.
    base = {
        "text": "", "caption": "", "suggestions": [], "category": "",
        "names": [], "references": [], "confidence": "",
    }
    if not api_key:
        return base | {"missing": ["Clave de Gemini"], "errors": []}
    try:
        progress("Enviando la imagen a Gemini para analizarla…")
        from PIL import Image, ImageOps

        prompt = """Clasificá este sticker para una biblioteca argentina. Devolvé un objeto JSON válido con TODAS estas claves: text, caption, category, names, tags y confidence.
text: texto legible horizontal o vertical en español, inglés y números; no inventes texto.
caption: descripción visual breve, concreta y con mayúscula inicial en español argentino.
category: una categoría simple y global; por ejemplo Argentina, Fútbol, Música, Logos, Personajes o Frases.
names: arreglo de hasta tres nombres claros para argentinos; si no reconocés una referencia, describí sin inventar.
tags: arreglo de hasta seis etiquetas individuales útiles para buscar; no uses una oración completa. Separá personaje, objeto, color y franquicia cuando corresponda.
confidence: Alta, Media o Baja según qué tan segura sea la identificación.
No uses el nombre del archivo como evidencia."""
        with Image.open(path) as image:
            image = ImageOps.contain(image.convert("RGB"), (768, 768), method=Image.Resampling.LANCZOS)
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=88, optimize=True)
        body = json.dumps({
            "contents": [{"parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(buffer.getvalue()).decode("ascii")}},
            ]}],
            "generationConfig": {
                "temperature": 0.15,
                "maxOutputTokens": 360,
                "responseMimeType": "application/json",
            },
        }).encode("utf-8")
        request = Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            method="POST",
        )
        with urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
        parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        raw = "".join(part.get("text", "") for part in parts).strip()

        # La respuesta JSON es el camino normal. El formato por líneas queda
        # como respaldo si una versión del modelo no admite JSON estructurado.
        try:
            structured = json.loads(raw.removeprefix("```json").removesuffix("```").strip())
        except (ValueError, TypeError):
            structured = {}

        def string_list(value) -> list[str]:
            if isinstance(value, list):
                return [str(item).strip() for item in value if str(item).strip()]
            if isinstance(value, str):
                return [item.strip() for item in re.split(r"\s*\|\s*", value) if item.strip()]
            return []

        # Gemini puede agregar acentos, viñetas o nombres alternativos a las
        # cabeceras. Aceptamos esas variantes sin modificar el contenido que
        # devuelve (así se conservan los acentos de las etiquetas y nombres).
        headers = {
            "text": r"TEXTO",
            "caption": r"DESCRIPCI(?:O|Ó)N(?:\s+VISUAL)?",
            "category": r"CATEGOR[IÍ]A",
            "names": r"NOMBRES(?:\s+SUGERIDOS)?",
            "tags": r"ETIQUETAS",
            "confidence": r"CONFIANZA",
        }
        all_headers = "|".join(headers.values())

        def field(header: str) -> str:
            match = re.search(
                rf"(?ims)^\s*(?:[-*#]+\s*)?(?:{header})\s*:\s*(.*?)(?=^\s*(?:[-*#]+\s*)?(?:{all_headers})\s*:|\Z)",
                raw,
            )
            return " ".join(match.group(1).split()) if match else ""

        text = str(structured.get("text") or field(headers["text"])).strip()
        caption = str(structured.get("caption") or field(headers["caption"])).strip()
        category = str(structured.get("category") or field(headers["category"])).strip()
        from app.ai.tagging import individual_tags
        raw_tags = string_list(structured.get("tags")) or [tag.strip() for tag in re.split(r"\s*\|\s*", field(headers["tags"])) if tag.strip()]
        tags = individual_tags(*raw_tags)
        names = string_list(structured.get("names")) or [name.strip() for name in re.split(r"\s*\|\s*", field(headers["names"])) if name.strip()]
        return base | {
            "text": text,
            "caption": caption[:1].upper() + caption[1:] if caption else "",
            "suggestions": list(dict.fromkeys(tags + ([text] if text else []))),
            "category": category.title(),
            "names": names,
            "confidence": str(structured.get("confidence") or field(headers["confidence"])).strip().title(),
            "missing": [],
            "errors": [],
        }
    except HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            detail = ""
        message = f"Gemini rechazó la solicitud ({error.code})"
        if detail:
            message += f": {detail}"
        return base | {"missing": [], "errors": [message]}
    except URLError as error:
        reason = getattr(error, "reason", error)
        if getattr(reason, "winerror", None) == 10013:
            message = (
                "Windows bloqueó la conexión con Gemini (error 10013). "
                "Permití Doccione o Python en el Firewall de Windows y verificá "
                "que tu red no bloquee generativelanguage.googleapis.com."
            )
        else:
            message = f"No se pudo conectar con Gemini: {reason}"
        return base | {"missing": [], "errors": [message]}
    except Exception as error:
        return base | {"missing": [], "errors": [str(error)]}
