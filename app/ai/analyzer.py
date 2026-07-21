"""Análisis local de stickers: OCR y descripción visual mediante modelos de IA."""

from functools import lru_cache
import re


@lru_cache(maxsize=1)
def _ocr_reader():
    import easyocr

    return easyocr.Reader(["es", "en"], gpu=False, verbose=False)


@lru_cache(maxsize=1)
def _captioner():
    from transformers import BlipForConditionalGeneration, BlipProcessor

    processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
    model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base")
    return processor, model


@lru_cache(maxsize=1)
def _translator():
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained("Helsinki-NLP/opus-mt-en-es")
    model = AutoModelForSeq2SeqLM.from_pretrained("Helsinki-NLP/opus-mt-en-es")
    return tokenizer, model


def _spanish_sentence(text: str) -> str:
    """Traduce la descripción BLIP y le da formato de oración en español."""
    tokenizer, model = _translator()
    encoded = tokenizer(text, return_tensors="pt", truncation=True)
    translated = model.generate(**encoded, max_new_tokens=64)
    sentence = tokenizer.decode(translated[0], skip_special_tokens=True).strip()
    tokens = sentence.split()
    # Evita salidas degeneradas como "Alemania Alemania Alemania...".
    if tokens and len({token.casefold().strip(".,;:!") for token in tokens}) == 1:
        sentence = tokens[0]
    # Vocabulario natural para Argentina en descripciones de stickers.
    sentence = re.sub(r"\bjersey\b", "casaca", sentence, flags=re.I)
    sentence = re.sub(r"\bUn casaca\b", "Una casaca", sentence, flags=re.I)
    sentence = re.sub(r"\bEl casaca\b", "La casaca", sentence, flags=re.I)
    return sentence[:1].upper() + sentence[1:] if sentence else ""


def analyze_image(path: str, progress=None) -> dict:
    """Devuelve texto detectado, descripción y propuestas para etiquetar."""
    progress = progress or (lambda _message: None)
    missing = []
    errors = []
    text = ""
    words: list[str] = []
    caption = ""
    try:
        progress("Leyendo texto horizontal y vertical con OCR…")
        from PIL import Image
        import numpy as np

        # Primero se prueba la orientación normal. Solo se gira la imagen si
        # no hay texto confiable: acelera mucho los stickers habituales.
        with Image.open(path) as source:
            source = source.convert("RGB")
            def scan(angle):
                rotated = source.rotate(angle, expand=True)
                return _ocr_reader().readtext(np.array(rotated), detail=1, paragraph=False, mag_ratio=1.5)

            readings = scan(0)
            has_clear_text = lambda items: any(
                item[2] >= 0.65 and sum(letter.isalpha() for letter in item[1]) >= 3 for item in items
            )
            if not has_clear_text(readings):
                for angle in (90, 270, 180):
                    rotated_readings = scan(angle)
                    readings.extend(rotated_readings)
                    if has_clear_text(rotated_readings):
                        break
        # EasyOCR con es+en reconoce palabras, acentos y números. Se exige una
        # confianza mayor para evitar que iconos (por ejemplo, $) se conviertan
        # en números falsos. Los números solos se aceptan solo junto a texto.
        words = [item[1].strip() for item in readings if item[1].strip() and item[2] >= 0.55]
        if not any(any(letter.isalpha() for letter in word) for word in words):
            words = []
        # Conserva texto útil una sola vez y descarta símbolos/ruido del OCR.
        seen = set()
        words = [
            word for word in words
            if re.fullmatch(r"[\wÀ-ÿ][\wÀ-ÿ' -]*", word)
            and (any(letter.isalpha() for letter in word) or len(word) >= 2)
            and not (word.casefold() in seen or seen.add(word.casefold()))
        ]
        # Una lectura de una o dos letras suele ser ruido de un icono o de un
        # borde circular; se excluye de las etiquetas automáticas.
        words = [word for word in words if len(word) >= 3 or word.isdigit()]
        text = " · ".join(words)
    except ImportError:
        missing.append("OCR")
    except Exception as error:
        errors.append(f"OCR: {type(error).__name__}: {str(error)[:140]}")
    try:
        progress("Analizando el contenido visual…")
        from PIL import Image

        processor, model = _captioner()
        with Image.open(path) as photo:
            inputs = processor(images=photo.convert("RGB"), return_tensors="pt")
        generated = model.generate(**inputs, max_new_tokens=16, num_beams=3, no_repeat_ngram_size=2, repetition_penalty=1.3)
        caption = processor.decode(generated[0], skip_special_tokens=True).strip()
        if caption:
            progress("Traduciendo la descripción al español…")
            caption = _spanish_sentence(caption)
    except ImportError:
        missing.append("descripción visual")
    except Exception as error:
        errors.append(f"Descripción visual: {type(error).__name__}: {str(error)[:140]}")
    suggestions = []
    if caption:
        suggestions.append(caption)
    suggestions.extend(words)
    progress("Análisis completado.")
    from app.ai.cultural import cultural_references

    references = cultural_references(caption, text)
    suggestions.extend(reference["search_terms"] for reference in references)
    return {"text": text, "caption": caption, "suggestions": list(dict.fromkeys(suggestions)), "missing": missing, "errors": errors, "references": references}
