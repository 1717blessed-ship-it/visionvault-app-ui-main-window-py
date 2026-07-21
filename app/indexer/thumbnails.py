from functools import lru_cache
import hashlib
from pathlib import Path


THUMBNAIL_CACHE = Path(__file__).resolve().parents[2] / ".cache" / "thumbnails"


def prepare_thumbnail(path: str, width: int, height: int, modified: float):
    """Devuelve una miniatura PIL persistente e invalidada por modificación.

    La primera lectura prepara el PNG pequeño; las aperturas siguientes no
    vuelven a decodificar los archivos originales de la biblioteca.
    """
    from PIL import Image

    identity = f"{Path(path).resolve()}|{modified:.6f}|{width}x{height}"
    digest = hashlib.sha1(identity.encode("utf-8", errors="surrogatepass")).hexdigest()
    cached_path = THUMBNAIL_CACHE / f"{digest}.png"
    try:
        with Image.open(cached_path) as cached:
            cached.load()
            return cached.convert("RGBA")
    except (OSError, ValueError):
        pass
    with Image.open(path) as source:
        image = source.convert("RGBA")
        image.thumbnail((width, height), Image.Resampling.LANCZOS)
    try:
        THUMBNAIL_CACHE.mkdir(parents=True, exist_ok=True)
        temporary = cached_path.with_suffix(".tmp.png")
        image.save(temporary, "PNG", compress_level=1)
        temporary.replace(cached_path)
    except OSError:
        pass
    return image


@lru_cache(maxsize=600)
def _cached_thumbnail(path: str, width: int, height: int, modified: float):
    from PIL import ImageTk

    return ImageTk.PhotoImage(prepare_thumbnail(path, width, height, modified))


def load_thumbnail(path: str, size: tuple[int, int]):
    """Miniatura cacheada; se regenera automáticamente si cambia el archivo."""
    try:
        source = Path(path)
        return _cached_thumbnail(str(source), size[0], size[1], source.stat().st_mtime)
    except Exception:
        return None
