"""Exportación de stickers procesados.

Controla:
- Tamaño final de 5,75 cm
- Resolución de 300 DPI
- PNG transparente
- Nombre del archivo
- Evitar sobrescritura accidental
- Carpeta de salida
- Metadatos del resultado
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from app.stickers.models import ProcessingProfile, StickerResult


# ══════════════════════════════════════════════════════════════════════════════
# Cálculo de tamaños
# ══════════════════════════════════════════════════════════════════════════════

def calculate_export_size(profile: ProcessingProfile) -> tuple[int, int]:
    """Calcula el tamaño en píxeles para el export final.

    Returns:
        (width_px, height_px) al DPI configurado.
    """
    pixels = profile.master_pixels
    return pixels, pixels


def calculate_print_size(profile: ProcessingProfile) -> tuple[int, int]:
    """Calcula el tamaño de impresión (con print_scale aplicado)."""
    print_cm = profile.print_size_cm
    pixels = round(print_cm / 2.54 * profile.dpi)
    return pixels, pixels


# ══════════════════════════════════════════════════════════════════════════════
# Generación de nombres de archivo
# ══════════════════════════════════════════════════════════════════════════════

def generate_filename(source_path: str | Path, profile: ProcessingProfile,
                      suffix: str = "", use_hash: bool = True) -> str:
    """Genera un nombre de archivo único basado en el origen y perfil.
    
    Args:
        source_path: Path to source file
        profile: Processing profile
        suffix: Optional suffix
        use_hash: If True, use SHA-256 hash for uniqueness (prevents cache collisions)
    
    Returns:
        Unique filename
    """
    source = Path(source_path)
    
    if use_hash:
        # Use SHA-256 hash to prevent cache collisions between files with same name
        file_hash = hashlib.sha256()
        with source.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                file_hash.update(block)
        hash_short = file_hash.hexdigest()[:12]
        base_name = hash_short
    else:
        # Fallback to original stem-based naming (not recommended for production)
        base_name = source.stem
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in base_name)
        base_name = safe_name
    
    profile_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in profile.name)
    parts = [base_name, profile_name]
    if suffix:
        parts.append(suffix)
    return "_".join(parts) + ".png"


def avoid_overwrite(directory: Path, filename: str) -> Path:
    """Evita sobrescribir un archivo existente añadiendo un sufijo numérico."""
    target = directory / filename
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    counter = 1
    while True:
        candidate = directory / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def generate_job_id(source_path: str | Path) -> str:
    """Genera un ID único para un trabajo basado en el archivo y timestamp."""
    source = Path(source_path)
    name_hash = hashlib.md5(str(source).encode()).hexdigest()[:8]
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{name_hash}"


# ══════════════════════════════════════════════════════════════════════════════
# Metadatos
# ══════════════════════════════════════════════════════════════════════════════

def build_metadata(result: StickerResult, profile: ProcessingProfile) -> dict[str, Any]:
    """Construye el diccionario de metadatos para guardar con el sticker."""
    return {
        "job_id": result.job_id,
        "source_path": result.source_path,
        "created_at": result.created_at or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "profile": {**profile.__dict__} if hasattr(profile, "__dict__") else {},
        "analysis": result.analysis,
        "artifacts": result.artifacts,
        "quality_status": result.quality_status,
        "quality_notes": result.quality_notes,
        "processing_mode": result.processing_mode,
        "classification": result.classification,
        "selected_mask": result.selected_mask_name,
        "confidence": result.confidence,
    }


def save_metadata(metadata: dict[str, Any], output_dir: Path) -> Path:
    """Guarda los metadatos como metadata.json en el directorio de salida."""
    meta_path = output_dir / "metadata.json"
    meta_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return meta_path


# ══════════════════════════════════════════════════════════════════════════════
# Exportación principal
# ══════════════════════════════════════════════════════════════════════════════

def export_sticker(rgba_image: Any, profile: ProcessingProfile,
                   output_dir: str | Path, source_path: str | Path,
                   result: StickerResult | None = None,
                   suffix: str = "") -> tuple[Path, StickerResult]:
    """Exporta un sticker como PNG transparente a 300 DPI.

    Returns:
        (ruta_del_archivo, StickerResult_actualizado)
    """
    from PIL import Image

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    filename = generate_filename(source_path, profile, suffix)
    export_path = avoid_overwrite(output, filename)

    if not isinstance(rgba_image, Image.Image):
        rgba_image = Image.fromarray(rgba_image)
    rgba_image.save(export_path, format="PNG", dpi=(profile.dpi, profile.dpi),
                    optimize=False)

    if result is None:
        job_id = generate_job_id(source_path)
        result = StickerResult(
            job_id=job_id,
            source_path=str(source_path),
            output_dir=str(output),
            status="Exportado",
            quality_status="Listo",
            quality_notes=[],
            analysis={},
            artifacts={},
            profile={},
            exported_path=str(export_path),
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
    else:
        result.exported_path = str(export_path)
        result.status = "Exportado"

    metadata = build_metadata(result, profile)
    meta_path = save_metadata(metadata, output)
    result.artifacts["metadata"] = str(meta_path)

    return export_path, result
