import os
from pathlib import Path

from app.ai.caption import caption_from_filename

# Debe coincidir con los formatos ofrecidos por el Creador de Stickers.
# Pillow abre TIFF tanto con .tif como con .tiff.
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}


def scan_folder(folder: str | Path, follow_symlinks: bool = False):
    """Escanea una carpeta en busca de imágenes.

    Args:
        folder: Ruta de la carpeta a escanear
        follow_symlinks: Si es False, no sigue enlaces simbólicos que salgan de la carpeta
    """
    root = Path(folder).resolve()
    # Path.rglob() consulta el estado del archivo varias veces (is_file,
    # is_symlink y stat). scandir ya trae esos datos desde el directorio y
    # evita ese coste al recorrer bibliotecas grandes.
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    try:
                        is_link = entry.is_symlink()
                        if is_link:
                            if not follow_symlinks:
                                continue
                            resolved = path.resolve()
                            if not resolved.is_relative_to(root):
                                continue
                        if entry.is_dir(follow_symlinks=follow_symlinks):
                            # La papelera de stickers y otras carpetas ocultas
                            # no son parte de la biblioteca indexable. Sin este
                            # filtro, un diseño eliminado vuelve a aparecer al
                            # reindexar porque el escaneo es recursivo.
                            if path.name.startswith("."):
                                continue
                            pending.append(path)
                            continue
                        if not entry.is_file(follow_symlinks=follow_symlinks):
                            continue
                        if path.suffix.lower() not in IMAGE_EXTENSIONS:
                            continue
                        stat = entry.stat(follow_symlinks=follow_symlinks)
                    except OSError:
                        # Archivos inaccesibles o que cambian durante el
                        # recorrido no deben interrumpir toda la indexación.
                        continue
                    yield {
                        "path": str(path.resolve()),
                        "name": path.name,
                        "extension": path.suffix.lower(),
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                        "caption": caption_from_filename(path),
                    }
        except OSError:
            # Una subcarpeta protegida no debe impedir indexar el resto.
            continue
