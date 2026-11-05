from functools import lru_cache
import hashlib
from io import BytesIO
from pathlib import Path


THUMBNAIL_CACHE = Path(__file__).resolve().parents[2] / ".cache" / "thumbnails"
THUMBNAIL_ALGORITHM_VERSION = "visible-alpha-v2"


def prepare_thumbnail(
    path: str,
    width: int,
    height: int,
    modified: float,
    *,
    border: int = 0,
    upscale: bool = False,
    trim_transparency: bool = False,
):
    """Devuelve una miniatura PIL persistente e invalidada por modificación.

    La primera lectura prepara el PNG pequeño; las aperturas siguientes no
    vuelven a decodificar los archivos originales de la biblioteca.
    """
    from PIL import Image, ImageOps

    identity = (
        f"{THUMBNAIL_ALGORITHM_VERSION}|{Path(path).resolve()}|"
        f"{modified:.6f}|{width}x{height}"
    )
    if border or upscale or trim_transparency:
        identity += (
            f"|border={border}|upscale={int(upscale)}"
            f"|trim={int(trim_transparency)}"
        )
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
        if trim_transparency:
            # Compartir exactamente la misma definición de contenido visible
            # que usa Producción: los residuos alfa 1..8 no deben achicar la
            # miniatura ni hacerla diferir de la plancha.
            alpha = image.getchannel("A")
            visible_bounds = alpha.point(
                lambda value: 255 if value > 8 else 0
            ).getbbox()
            # JPG y PNG opaco: delegar la detección del fondo uniforme al
            # mismo detector productivo. En transparencia real se usa la caja
            # exacta para aprovechar toda la tarjeta de Biblioteca.
            if alpha.getextrema() == (255, 255):
                from app.planchas.model import visible_bbox
                visible_bounds = visible_bbox(image)
            if visible_bounds:
                image = image.crop(visible_bounds)
        border = max(0, int(border))
        target_width = max(1, int(width) - border * 2)
        target_height = max(1, int(height) - border * 2)
        if upscale:
            scale = min(target_width / image.width, target_height / image.height)
            resized = (
                max(1, round(image.width * scale)),
                max(1, round(image.height * scale)),
            )
            if resized != image.size:
                image = image.resize(resized, Image.Resampling.LANCZOS)
        else:
            image.thumbnail((target_width, target_height), Image.Resampling.LANCZOS)
        if border:
            image = ImageOps.expand(image, border=border, fill=(0, 0, 0, 255))
    try:
        THUMBNAIL_CACHE.mkdir(parents=True, exist_ok=True)
        temporary = cached_path.with_suffix(".tmp.png")
        image.save(temporary, "PNG", compress_level=1)
        temporary.replace(cached_path)
    except OSError:
        pass
    return image


@lru_cache(maxsize=512)
def thumbnail_png_bytes(
    path: str,
    width: int,
    height: int,
    modified: float,
    border: int = 0,
    upscale: bool = False,
    trim_transparency: bool = False,
) -> bytes:
    """PNG listo para HTTP, cacheado en memoria para evitar recodificaciones."""
    image = prepare_thumbnail(
        path,
        width,
        height,
        modified,
        border=border,
        upscale=upscale,
        trim_transparency=trim_transparency,
    )
    output = BytesIO()
    image.save(output, format="PNG", compress_level=1)
    return output.getvalue()


@lru_cache(maxsize=600)
def _cached_thumbnail(
    path: str, width: int, height: int, modified: float,
    upscale: bool = False, trim_transparency: bool = False,
):
    from PIL import ImageTk

    return ImageTk.PhotoImage(prepare_thumbnail(
        path, width, height, modified,
        upscale=upscale, trim_transparency=trim_transparency,
    ))


def load_thumbnail(
    path: str, size: tuple[int, int], *,
    upscale: bool = False, trim_transparency: bool = False,
):
    """Miniatura cacheada; se regenera automáticamente si cambia el archivo."""
    try:
        source = Path(path)
        return _cached_thumbnail(
            str(source), size[0], size[1], source.stat().st_mtime,
            upscale, trim_transparency,
        )
    except Exception:
        return None
