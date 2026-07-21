import re
from pathlib import Path


def caption_from_filename(path: str | Path) -> str:
    """Descripción local mínima basada en el nombre del archivo."""
    stem = Path(path).stem.replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", stem).strip()
