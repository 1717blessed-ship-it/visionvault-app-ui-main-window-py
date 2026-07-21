from pathlib import Path


def rename_image(path: str, new_stem: str) -> Path:
    source = Path(path)
    clean_name = " ".join(new_stem.strip().split())
    if not clean_name or any(char in clean_name for char in '<>:"/\\|?*'):
        raise ValueError("El nombre contiene caracteres no permitidos.")
    destination = source.with_name(clean_name + source.suffix)
    if destination.exists() and destination != source:
        raise FileExistsError("Ya existe un archivo con ese nombre.")
    return source.rename(destination)
