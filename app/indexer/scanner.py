from pathlib import Path

from app.ai.caption import caption_from_filename

# Debe coincidir con los formatos ofrecidos por el Creador de Stickers.
# Pillow abre TIFF tanto con .tif como con .tiff.
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}


def scan_folder(folder: str | Path):
    root = Path(folder)
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            stat = path.stat()
            yield {
                "path": str(path.resolve()),
                "name": path.name,
                "extension": path.suffix.lower(),
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "caption": caption_from_filename(path),
            }
