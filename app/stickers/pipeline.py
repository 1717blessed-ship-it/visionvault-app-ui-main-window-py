"""Pipeline no destructivo para convertir imágenes en stickers listos para producir.

Arquitectura: árbol de decisiones
──────────────────────────────────
  classify()  →  determina ImageCase (A / B / C / D)
  _flow_a()   →  PNG transparente sin borde
  _flow_b()   →  Sticker ya terminado
  _flow_c()   →  Fondo de color uniforme
  _flow_d()   →  Fotografía (segmentación IA)
  _postprocess() → postprocesado unificado para todos los casos
  process()   →  orquesta el árbol completo
"""

from __future__ import annotations

import enum
import hashlib
import json
import logging
import math
import shutil
import time
import uuid
import os

logger = logging.getLogger(__name__)


class ProcessingCancelled(Exception):
    """Cancelación cooperativa; nunca representa un artefacto aprobable."""

from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Callable


def _json_default(value):
    """Convierte escalares de librerías de imagen a valores JSON nativos."""
    if isinstance(value, Path):
        return str(value)
    item = getattr(value, "item", None)
    if callable(item):
        native_value = item()
        if native_value is not value:
            return native_value
    raise TypeError(f"{type(value).__name__} no es serializable como JSON")


# ══════════════════════════════════════════════════════════════════════════════

from .models import (
    BorderMode,
    CreationMode,
    ImageCase,
    ProcessingMode,
    ProcessingProfile,
    QualityPreset,
)

# Catálogo visual: no interviene en la selección de los flujos A/B/C/D.
# Las claves se guardan en metadata y las etiquetas se muestran en revisión,
# de manera que una corrección manual sea estable entre ejecuciones.
VISUAL_STICKER_TYPES: tuple[tuple[str, str], ...] = (
    ("arte_transparente", "Arte transparente sin borde"),
    ("sticker_terminado", "Sticker terminado con borde blanco"),
    ("sticker_con_halo", "Sticker terminado con halo gris"),
    ("damero_incrustado", "Sticker sobre damero incrustado"),
    ("fondo_blanco", "Diseño sobre fondo blanco"),
    ("fondo_neutro", "Sticker sobre fondo gris o neutro"),
    ("fondo_color", "Diseño sobre fondo de color uniforme"),
    ("fotografia", "Fotografía para recorte inteligente"),
    ("ilustracion_compleja", "Ilustración con fondo complejo"),
    ("logo_tipografia", "Logo o tipografía"),
    ("lineas_finas", "Dibujo de líneas finas"),
    ("multiples_objetos", "Composición con múltiples objetos"),
    ("semitransparencias", "Imagen con semitransparencias"),
    ("borde_color", "Sticker terminado con borde de color"),
    ("fondo_degradado_texturizado", "Diseño sobre fondo degradado o texturizado"),
    ("sujeto_cortado_encuadre", "Imagen con sujeto cortado por el encuadre"),
    ("imagen_completa", "Diseño completo para sticker"),
    ("dibujo_escaneado", "Dibujo escaneado o fotografiado"),
)
VISUAL_STICKER_TYPE_LABELS = dict(VISUAL_STICKER_TYPES)
VISUAL_STICKER_TYPE_IDS_BY_LABEL = {
    label: identifier for identifier, label in VISUAL_STICKER_TYPES
}



@dataclass(slots=True)
class ClassifyResult:
    """Resultado del árbol de clasificación."""
    case: ImageCase
    design_mode: str          # "Contorno interno" | "Color uniforme"
    reasons: list[str]
    has_transparency: bool
    has_white_border: bool
    has_grey_border: bool     # borde gris/sombra exterior (no blanco puro)
    has_black_outline: bool
    uniform_background: bool
    is_photo: bool
    bg_color: tuple           # color dominante del fondo (R, G, B)
    is_sticker_on_neutral_bg: bool = False  # sticker terminado sobre fondo neutro
    # Etiqueta comercial independiente del flujo técnico A/B/C/D. Permite
    # mostrar al usuario qué clase de entrada se detectó y por qué ruta pasa.
    sticker_type: str = ""
    sticker_type_label: str = ""
    detected_types: list[str] = field(default_factory=list)
    classification_features: dict = field(default_factory=dict)


@dataclass(slots=True)
class Analysis:
    engine: str
    has_transparency: bool
    uniform_background: bool
    looks_prepared: bool
    kind: str
    main_elements: int
    has_text_hint: bool
    resolution_ok: bool
    width: int
    height: int


@dataclass(slots=True)
class ProcessingResult:
    job_id: str
    source_path: str
    output_dir: str
    status: str
    quality_status: str
    quality_notes: list[str]
    analysis: dict
    artifacts: dict[str, str]
    profile: dict
    duplicate_path: str = ""
    duplicate_score: float = 0.0

    @classmethod
    def from_metadata(cls, path):
        """Abre resultados actuales o legacy sin reprocesar sus imágenes."""
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        artifacts = dict(data.get("artifacts", {}))
        artifacts["metadata"] = str(path)
        return cls(
            job_id=data["job_id"], source_path=data["source_path"],
            output_dir=str(path.parent), status=data.get("status", "Procesado"),
            quality_status=data.get("quality_status", "Revisar"),
            quality_notes=data.get("quality_notes", []),
            analysis=data.get("analysis", {}), artifacts=artifacts,
            profile=data.get("profile", {}),
        )


# ══════════════════════════════════════════════════════════════════════════════
# StickerProcessor
# ══════════════════════════════════════════════════════════════════════════════

class StickerProcessor:

    def __init__(self, workspace: str | Path,
                 profile: ProcessingProfile | None = None):
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.profile = profile or ProcessingProfile()
        # Diagnostics flag (environment-controlled)
        diag_env = os.environ.get("STICKER_PIPELINE_DIAGNOSTICS", "0")
        self._diag_enabled = str(diag_env).lower() in ("1", "true", "yes")
        # Save intermediate masks when loss pct >= this threshold (percent)
        try:
            self._diag_save_threshold_pct = float(os.environ.get("STICKER_PIPELINE_DIAGNOSTICS_SAVE_THRESHOLD_PCT", "0.5"))
        except Exception:
            self._diag_save_threshold_pct = 0.5
        # Internal per-run diagnostics output path (set in process())
        self._diag_output_dir: Path | None = None

    # -------------------- Diagnostic helpers --------------------
    def _compute_alpha_metrics(self, alpha_image):
        """Return a dict with alpha statistics for a PIL L-mode image."""
        from PIL import Image
        try:
            import numpy as np
            arr = np.asarray(alpha_image.convert("L"), dtype=np.uint8)
            h, w = arr.shape
            total = int(arr.size)
            cnt_eq_0 = int((arr == 0).sum())
            cnt_eq_255 = int((arr == 255).sum())
            cnt_semi = int(((arr > 0) & (arr < 255)).sum())
            pct_transparent = 100.0 * cnt_eq_0 / max(1, total)
            pct_semi = 100.0 * cnt_semi / max(1, total)
            pct_opaque = 100.0 * cnt_eq_255 / max(1, total)
            alpha_min = int(arr.min())
            alpha_max = int(arr.max())
            # bounding box of alpha>0
            mask = (arr > 0).astype(np.uint8) * 255
            from PIL import Image
            mask_img = Image.fromarray(mask, mode="L")
            bbox = mask_img.getbbox()
            bbox_w = bbox[2] - bbox[0] if bbox else 0
            bbox_h = bbox[3] - bbox[1] if bbox else 0
            bbox_area = bbox_w * bbox_h
            bbox_pct = 100.0 * bbox_area / max(1, total)
            # perimeter: top/bottom/left/right
            top = arr[0, :]
            bottom = arr[-1, :]
            left = arr[:, 0]
            right = arr[:, -1]
            def edge_pct(line):
                return 100.0 * int((line == 0).sum()) / max(1, line.size)
            top_pct = edge_pct(top)
            bottom_pct = edge_pct(bottom)
            left_pct = edge_pct(left)
            right_pct = edge_pct(right)
            perimeter_pct = 100.0 * int(((arr[0, :] == 0).sum() + (arr[-1, :] == 0).sum() + (arr[:, 0] == 0).sum() + (arr[:, -1] == 0).sum())) / (4 * max(1, w))
            return {
                "alpha_min": int(alpha_min),
                "alpha_max": int(alpha_max),
                "width": int(w),
                "height": int(h),
                "total_pixels": int(total),
                "cnt_eq_0": int(cnt_eq_0),
                "cnt_semi": int(cnt_semi),
                "cnt_eq_255": int(cnt_eq_255),
                "pct_transparent": float(pct_transparent),
                "pct_semi": float(pct_semi),
                "pct_opaque": float(pct_opaque),
                "bbox": bbox,
                "bbox_w": int(bbox_w),
                "bbox_h": int(bbox_h),
                "bbox_pct": float(bbox_pct),
                "top_pct": float(top_pct),
                "bottom_pct": float(bottom_pct),
                "left_pct": float(left_pct),
                "right_pct": float(right_pct),
                "perimeter_pct": float(perimeter_pct),
            }
        except Exception:
            # Fallback slower PIL-only implementation
            alpha = alpha_image.convert("L")
            w, h = alpha.size
            data = list(alpha.get_flattened_data())
            total = w * h
            cnt_eq_0 = sum(1 for v in data if v == 0)
            cnt_eq_255 = sum(1 for v in data if v == 255)
            cnt_semi = total - cnt_eq_0 - cnt_eq_255
            pct_transparent = 100.0 * cnt_eq_0 / max(1, total)
            pct_semi = 100.0 * cnt_semi / max(1, total)
            pct_opaque = 100.0 * cnt_eq_255 / max(1, total)
            alpha_min = min(data)
            alpha_max = max(data)
            mask = alpha.point(lambda v: 255 if v > 0 else 0)
            bbox = mask.getbbox()
            bbox_w = bbox[2] - bbox[0] if bbox else 0
            bbox_h = bbox[3] - bbox[1] if bbox else 0
            bbox_area = bbox_w * bbox_h
            bbox_pct = 100.0 * bbox_area / max(1, total)
            top_pct = 100.0 * sum(1 for x in range(w) if alpha.getpixel((x, 0)) == 0) / max(1, w)
            bottom_pct = 100.0 * sum(1 for x in range(w) if alpha.getpixel((x, h-1)) == 0) / max(1, w)
            left_pct = 100.0 * sum(1 for y in range(h) if alpha.getpixel((0, y)) == 0) / max(1, h)
            right_pct = 100.0 * sum(1 for y in range(h) if alpha.getpixel((w-1, y)) == 0) / max(1, h)
            perimeter_pct = 100.0 * (sum(1 for x in range(w) if alpha.getpixel((x, 0)) == 0) + sum(1 for x in range(w) if alpha.getpixel((x, h-1)) == 0) + sum(1 for y in range(h) if alpha.getpixel((0, y)) == 0) + sum(1 for y in range(h) if alpha.getpixel((w-1, y)) == 0)) / (4 * max(1, w))
            return {
                "alpha_min": int(alpha_min),
                "alpha_max": int(alpha_max),
                "width": int(w),
                "height": int(h),
                "total_pixels": int(total),
                "cnt_eq_0": int(cnt_eq_0),
                "cnt_semi": int(cnt_semi),
                "cnt_eq_255": int(cnt_eq_255),
                "pct_transparent": float(pct_transparent),
                "pct_semi": float(pct_semi),
                "pct_opaque": float(pct_opaque),
                "bbox": bbox,
                "bbox_w": int(bbox_w),
                "bbox_h": int(bbox_h),
                "bbox_pct": float(bbox_pct),
                "top_pct": float(top_pct),
                "bottom_pct": float(bottom_pct),
                "left_pct": float(left_pct),
                "right_pct": float(right_pct),
                "perimeter_pct": float(perimeter_pct),
            }

    def _mask_diff_metrics(self, orig_alpha, new_alpha, threshold: int = 127):
        """Compute lost/gained pixels between two L-mode alpha images.

        Returns dict with counts and percentages relative to original visible pixels.
        """
        try:
            import numpy as np
            oa = np.asarray(orig_alpha.convert("L"), dtype=np.uint8)
            na = np.asarray(new_alpha.convert("L"), dtype=np.uint8)
            vis_orig = oa > threshold
            vis_new = na > threshold
            lost = int(((vis_orig) & (~vis_new)).sum())
            gained = int(((~vis_orig) & (vis_new)).sum())
            orig_visible = int(vis_orig.sum())
            lost_pct = 100.0 * lost / max(1, orig_visible)
            gained_pct = 100.0 * gained / max(1, orig_visible)
            return {
                "lost": lost,
                "gained": gained,
                "orig_visible": orig_visible,
                "lost_pct": float(lost_pct),
                "gained_pct": float(gained_pct),
            }
        except Exception:
            oa = list(orig_alpha.convert("L").get_flattened_data())
            na = list(new_alpha.convert("L").get_flattened_data())
            total = len(oa)
            vis_orig = [v > threshold for v in oa]
            vis_new = [v > threshold for v in na]
            lost = sum(1 for o, n in zip(vis_orig, vis_new) if o and not n)
            gained = sum(1 for o, n in zip(vis_orig, vis_new) if (not o) and n)
            orig_visible = sum(1 for v in vis_orig if v)
            lost_pct = 100.0 * lost / max(1, orig_visible)
            gained_pct = 100.0 * gained / max(1, orig_visible)
            return {
                "lost": int(lost),
                "gained": int(gained),
                "orig_visible": int(orig_visible),
                "lost_pct": float(lost_pct),
                "gained_pct": float(gained_pct),
            }

    def _append_diag_record(self, record: dict):
        """Append a JSON line to diagnostics summary in workspace."""
        try:
            # Ensure source is present for easier aggregation
            if "source" not in record:
                record["source"] = getattr(self, "_current_source_name", None)
            import json
            diag_file = self.workspace / "diagnostics.jsonl"
            with open(diag_file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=_json_default) + "\n")
        except Exception:
            logger.exception("Failed to append diagnostics record")

    @staticmethod
    def validate_source(source_path: str | Path) -> Path:
        """Valida un archivo antes de iniciar el pipeline.

        El resto del proceso trabaja siempre con una imagen raster legible por
        Pillow.  Fallar aquí evita errores crípticos de OpenCV o de las etapas
        de máscara y permite que la interfaz explique qué debe corregirse.
        """
        from PIL import Image, UnidentifiedImageError

        path = Path(source_path)
        if not path.exists():
            raise ValueError("El archivo ya no existe o fue movido.")
        if not path.is_file():
            raise ValueError("La ruta elegida no corresponde a un archivo de imagen.")
        try:
            if path.stat().st_size <= 0:
                raise ValueError("El archivo está vacío.")
        except OSError as error:
            raise ValueError("No se pudo acceder al archivo.") from error

        try:
            # verify detecta imágenes truncadas/corruptas sin cargar todo el
            # contenido. Se abre otra vez después porque verify invalida el
            # objeto de imagen.
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                width, height = image.size
                if width < 2 or height < 2:
                    raise ValueError("La imagen es demasiado pequeña para crear un sticker.")
                if width * height > 120_000_000:
                    raise ValueError(
                        "La imagen es demasiado grande para procesarla de forma segura "
                        "(máximo: 120 megapíxeles)."
                    )
        except (UnidentifiedImageError, OSError, SyntaxError) as error:
            raise ValueError(
                "El archivo no es una imagen compatible o está dañado. "
                "Usá PNG, JPG, JPEG, WEBP, BMP, GIF o TIFF válidos."
            ) from error
        return path

    # ──────────────────────────────────────────────────────────────────────────
    # Utilidades generales
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def file_hash(path: str | Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def log_alpha(name, image) -> None:
        """Log alpha channel statistics for debugging transparency issues.

        Distinguishes between L/1 masks and RGBA images to avoid false diagnostics.
        """
        import numpy as np

        if image.mode in ("1", "L"):
            mask = image.convert("L")
            arr = np.asarray(mask, dtype=np.uint8)
            logger.info(
                "%s MASK mode=%s size=%s extrema=%s bbox=%s "
                "pixels_0=%d pixels_255=%d pixels_partial=%d",
                name,
                image.mode,
                image.size,
                mask.getextrema(),
                mask.getbbox(),
                int(np.count_nonzero(arr == 0)),
                int(np.count_nonzero(arr == 255)),
                int(np.count_nonzero((arr > 0) & (arr < 255))),
            )
            return

        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        arr = np.asarray(alpha, dtype=np.uint8)
        logger.info(
            "%s RGBA mode=%s size=%s alpha_extrema=%s alpha_bbox=%s "
            "transparent=%d opaque=%d partial=%d",
            name,
            rgba.mode,
            rgba.size,
            alpha.getextrema(),
            alpha.getbbox(),
            int(np.count_nonzero(arr == 0)),
            int(np.count_nonzero(arr == 255)),
            int(np.count_nonzero((arr > 0) & (arr < 255))),
        )

    @staticmethod
    def clean_hidden_rgb(rgba: "Image") -> "Image":
        """Clean RGB values under transparent pixels to white.

        ERROR 2 FIX: This prevents applications that ignore alpha from showing
        black rectangles. Sets RGB to (255, 255, 255) for pixels with alpha == 0.

        Args:
            rgba: PIL Image in RGBA mode

        Returns:
            PIL Image in RGBA mode with cleaned RGB under transparent pixels
        """
        logger.info("clean_hidden_rgb: Starting, image mode=%s, size=%s", rgba.mode, rgba.size)

        # Optimized PIL-only version for maximum compatibility
        try:
            from PIL import Image
            # Ensure RGBA mode
            if rgba.mode != "RGBA":
                rgba = rgba.convert("RGBA")

            # Split into channels for faster processing
            r, g, b, a = rgba.split()
            # Create a mask where alpha == 0
            alpha_mask = a.point(lambda v: 255 if v == 0 else 0)
            # Apply white only where alpha is 0
            r.paste(255, mask=alpha_mask)
            g.paste(255, mask=alpha_mask)
            b.paste(255, mask=alpha_mask)
            # Recombine
            result = Image.merge("RGBA", (r, g, b, a))
            logger.info("clean_hidden_rgb: Completed successfully")
            return result
        except Exception as e:
            logger.exception("clean_hidden_rgb: Error, returning original: %s", e)
            # Return original if anything fails
            return rgba

    @staticmethod
    def _expand(mask, pixels: int):
        logger.info("_expand: Starting, pixels=%d, mask size=%s", pixels, mask.size)
        try:
            import cv2
            import numpy as np
            from PIL import Image
            diameter = max(1, int(pixels) * 2 + 1)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                               (diameter, diameter))
            logger.info("_expand: Using OpenCV, kernel size=%s", kernel.shape)
            result = Image.fromarray(
                cv2.dilate(np.asarray(mask.convert("L")), kernel, iterations=1),
                mode="L")
            logger.info("_expand: OpenCV dilation completed")
            return result
        except (ImportError, ModuleNotFoundError) as e:
            logger.warning("_expand: OpenCV not available, using PIL fallback: %s", e)

        from PIL import Image, ImageFilter
        result, remaining = mask, max(0, pixels)
        iterations = 0
        while remaining:
            r = min(remaining, 20)
            result = result.filter(ImageFilter.MaxFilter(r * 2 + 1))
            remaining -= r
            iterations += 1
        logger.info("_expand: PIL fallback completed, iterations=%d", iterations)
        return result

    @staticmethod
    def _contract(mask, pixels: int):
        try:
            import cv2
            import numpy as np
            from PIL import Image
            diameter = max(1, int(pixels) * 2 + 1)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                               (diameter, diameter))
            return Image.fromarray(
                cv2.erode(np.asarray(mask.convert("L")), kernel, iterations=1),
                mode="L")
        except (ImportError, ModuleNotFoundError):
            pass
        from PIL import ImageFilter
        result, remaining = mask, max(0, pixels)
        while remaining:
            r = min(remaining, 20)
            result = result.filter(ImageFilter.MinFilter(r * 2 + 1))
            remaining -= r
        return result

    @staticmethod
    def _clean_alpha_hard(alpha):
        """Limpieza binaria sin ningún blur final.

        Usado en los pasos intermedios del pipeline para evitar introducir
        semitransparencias que luego se convierten en fantasmas/borrones.
        """
        from PIL import ImageFilter
        mask = alpha.convert("L").point(lambda v: 255 if v > 18 else 0)
        mask = mask.filter(ImageFilter.MedianFilter(3))
        return mask.filter(ImageFilter.MaxFilter(3)).filter(
            ImageFilter.MinFilter(3))

    @staticmethod
    def _clean_alpha_soft(alpha, feather_px: int = 3):
        """Limpieza con suavidad solo en la franja perimetral exterior.

        1. Binariza duro el interior.
        2. Dilata la máscara binaria feather_px píxeles.
        3. En la corona entre la máscara original y la dilatada aplica
           un GaussianBlur suave → transición real en el borde exterior.
        4. El interior permanece 100 % opaco.

        Esto preserva la suavidad del cabello en el contorno sin dejar
        ningún píxel semitransparente en el centro de la silueta.
        """
        from PIL import ImageFilter
        try:
            import cv2
            import numpy as np
            from PIL import Image

            # Máscara binaria base
            base = alpha.convert("L").point(lambda v: 255 if v > 18 else 0)
            base = base.filter(ImageFilter.MedianFilter(3))
            base = base.filter(ImageFilter.MaxFilter(3)).filter(
                ImageFilter.MinFilter(3))

            arr = np.asarray(base, dtype=np.uint8)

            if feather_px <= 0:
                return base

            # Corona exterior: diferencia entre dilatada y la binaria
            fp = max(1, int(feather_px))
            k  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                           (fp * 2 + 1, fp * 2 + 1))
            dilated = cv2.dilate(arr, k)
            corona  = (dilated > 127) & (arr <= 127)   # zona de transición

            # Blur moderado solo en la corona
            blurred = cv2.GaussianBlur(arr.astype(np.float32),
                                       (fp * 4 + 1, fp * 4 + 1), fp * 0.8)
            result  = arr.copy()
            result[corona] = np.clip(blurred[corona], 0, 255).astype(np.uint8)
            return Image.fromarray(result, mode="L")

        except (ImportError, ModuleNotFoundError):
            from PIL import ImageFilter
            mask = alpha.convert("L").point(lambda v: 255 if v > 18 else 0)
            mask = mask.filter(ImageFilter.MedianFilter(3))
            mask = mask.filter(ImageFilter.MaxFilter(3)).filter(
                ImageFilter.MinFilter(3))
            return mask.filter(ImageFilter.GaussianBlur(min(feather_px, 1)))

    # Alias de compatibilidad: los flujos A/B/C siguen usando _clean_alpha
    # con la versión hard (binarizada), que es el comportamiento correcto
    # para ilustraciones y logos que no tienen bordes difusos de cabello.
    @staticmethod
    def _clean_alpha(alpha):
        """Limpieza binaria — alias de _clean_alpha_hard para compatibilidad."""
        from PIL import ImageFilter
        mask = alpha.convert("L").point(lambda v: 255 if v > 18 else 0)
        mask = mask.filter(ImageFilter.MedianFilter(3))
        return mask.filter(ImageFilter.MaxFilter(3)).filter(
            ImageFilter.MinFilter(3))

    @staticmethod
    def _closed_interior_mask(alpha):
        """Huecos transparentes encerrados por la silueta."""
        import numpy as np
        from PIL import Image
        opaque = alpha.convert("L").point(lambda v: 255 if v > 18 else 0)
        arr = np.asarray(opaque, dtype=np.uint8)
        try:
            from scipy.ndimage import binary_fill_holes
            filled = binary_fill_holes(arr > 127)
            holes = (filled & ~(arr > 127)).astype(np.uint8) * 255
            return Image.fromarray(holes, mode="L")
        except (ImportError, ModuleNotFoundError):
            pass
        try:
            import cv2
            transparent = (arr == 0).astype(np.uint8) * 255
            h, w = transparent.shape
            exterior = transparent.copy()
            fm = np.zeros((h + 2, w + 2), np.uint8)
            for x in range(w):
                if exterior[0, x]:     cv2.floodFill(exterior, fm, (x, 0),     128)
                if exterior[h-1, x]:   cv2.floodFill(exterior, fm, (x, h-1),   128)
            for y in range(h):
                if exterior[y, 0]:     cv2.floodFill(exterior, fm, (0, y),     128)
                if exterior[y, w-1]:   cv2.floodFill(exterior, fm, (w-1, y),   128)
            holes = np.where(exterior == 255, np.uint8(255), np.uint8(0))
            return Image.fromarray(holes, mode="L")
        except (ImportError, ModuleNotFoundError):
            pass
        from PIL import ImageChops, ImageDraw
        inv = ImageChops.invert(opaque)
        w, h = inv.size
        outside = inv.copy()
        for x in range(w):
            if outside.getpixel((x, 0)) == 255:
                ImageDraw.floodfill(outside, (x, 0), 128, thresh=0)
            if outside.getpixel((x, h-1)) == 255:
                ImageDraw.floodfill(outside, (x, h-1), 128, thresh=0)
        for y in range(h):
            if outside.getpixel((0, y)) == 255:
                ImageDraw.floodfill(outside, (0, y), 128, thresh=0)
            if outside.getpixel((w-1, y)) == 255:
                ImageDraw.floodfill(outside, (w-1, y), 128, thresh=0)
        return outside.point(lambda v: 255 if v == 255 else 0)

    @classmethod
    def _preserve_closed_interiors(cls, alpha):
        from PIL import ImageChops
        return ImageChops.lighter(alpha.convert("L"),
                                  cls._closed_interior_mask(alpha))

    @classmethod
    def _analyze_closed_holes(cls, alpha):
        """Retorna estadísticas de cada hueco interior cerrado en la máscara."""
        try:
            import cv2
            import numpy as np
            from PIL import Image

            holes   = np.asarray(cls._closed_interior_mask(alpha), dtype=np.uint8)
            if holes.max() == 0:
                return []

            stats = cv2.connectedComponentsWithStats(holes, connectivity=8)
            n_h, lmap, stats_h, _ = stats
            subject = np.asarray(alpha.convert("L").point(lambda v: 255 if v > 18 else 0), dtype=np.uint8)
            inv_subject = np.where(subject > 0, 0, 255).astype(np.uint8)
            distance = cv2.distanceTransform(inv_subject, cv2.DIST_L2, 5)

            details: list[dict] = []
            for lb in range(1, n_h):
                area = int(stats_h[lb, cv2.CC_STAT_AREA])
                x = int(stats_h[lb, cv2.CC_STAT_LEFT])
                y = int(stats_h[lb, cv2.CC_STAT_TOP])
                w = int(stats_h[lb, cv2.CC_STAT_WIDTH])
                h = int(stats_h[lb, cv2.CC_STAT_HEIGHT])
                component = lmap == lb
                if not component.any():
                    continue
                mean_distance = float(distance[component].mean()) if component.any() else 0.0
                details.append({
                    "area_px": area,
                    "bbox": [x, y, w, h],
                    "min_dimension_px": min(w, h),
                    "distance_to_subject_px": round(mean_distance, 2),
                })
            return details
        except (ImportError, ModuleNotFoundError, Exception):
            # Fallback mínimo con PIL: devuelve solo área y bounding box.
            holes = cls._closed_interior_mask(alpha)
            if holes.getbbox() is None:
                return []
            try:
                from PIL import Image
                import numpy as np
            except (ImportError, ModuleNotFoundError):
                return []
            arr = np.asarray(holes.convert("L"), dtype=np.uint8)
            unique, counts = np.unique(arr, return_counts=True)
            details = []
            # No hay etiquetas con PIL puro, solo un conteo global.
            details.append({
                "area_px": int((arr == 255).sum()),
                "bbox": list(holes.getbbox()),
                "min_dimension_px": int(min(holes.size)),
                "distance_to_subject_px": 0.0,
            })
            return details

    @staticmethod
    def _component_count(mask, threshold: int = 20) -> int:
        small = mask.convert("L").resize((48, 48)).point(
            lambda v: 255 if v > threshold else 0)
        data = list(small.get_flattened_data())
        seen: set[int] = set()
        count = 0
        for start, value in enumerate(data):
            if not value or start in seen:
                continue
            stack = [start]
            seen.add(start)
            area = 0
            while stack:
                idx = stack.pop()
                area += 1
                x, y = idx % 48, idx // 48
                for nx, ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                    nb = ny * 48 + nx
                    if 0 <= nx < 48 and 0 <= ny < 48 and nb not in seen \
                            and data[nb]:
                        seen.add(nb); stack.append(nb)
            if area >= 5:
                count += 1
        return count

    @staticmethod
    def _describe_sticker_type(rgba, case, *, useful_alpha: bool,
                               has_white_border: bool,
                               has_grey_border: bool,
                               is_photo: bool,
                               uniform_background: bool,
                               bg_color: tuple) -> tuple[str, str]:
        """Devuelve una clasificación legible, separada del flujo A/B/C/D.

        Los casos técnicos controlan el procesamiento; estos tipos permiten
        distinguir entradas que visualmente se parecen pero deben explicarse
        de otro modo al usuario (por ejemplo, un sticker real frente a una
        captura de ese sticker sobre un damero).
        """
        if not useful_alpha:
            try:
                if StickerProcessor._checkerboard_exterior_alpha(rgba) is not None:
                    return ("damero_incrustado", "Sticker sobre damero incrustado")
            except Exception:
                pass

        if useful_alpha:
            if has_white_border:
                return ("sticker_terminado", "Sticker terminado con borde blanco")
            if has_grey_border:
                return ("sticker_con_halo", "Sticker terminado con halo gris")
            return ("arte_transparente", "Arte transparente sin borde")

        if case == ImageCase.D:
            return ("fotografia", "Fotografía para recorte inteligente")

        if uniform_background:
            luminance = (0.299 * bg_color[0] + 0.587 * bg_color[1]
                         + 0.114 * bg_color[2])
            if luminance >= 235:
                return ("fondo_blanco", "Diseño sobre fondo blanco")
            if max(bg_color) - min(bg_color) <= 22:
                return ("fondo_neutro", "Sticker sobre fondo gris o neutro")
            return ("fondo_color", "Diseño sobre fondo de color uniforme")

        if is_photo:
            return ("fotografia", "Fotografía para recorte inteligente")

        return ("ilustracion_compleja", "Ilustración con fondo complejo")

    @staticmethod
    def _classification_features(rgba, *, useful_alpha: bool,
                                 has_white_border: bool,
                                 has_grey_border: bool,
                                 uniform_background: bool,
                                 bg_color: tuple,
                                 is_photo: bool) -> tuple[dict, list[str]]:
        """Extrae rasgos observables sin convertirlos en probabilidades.

        El resultado es deliberadamente descriptivo: los rasgos pueden
        coexistir y explican qué ajustes usará el flujo técnico. Ninguna
        puntuación heurística se presenta como una confianza estadística.
        """
        from PIL import Image, ImageFilter
        import numpy as np

        rgb = rgba.convert("RGB")
        alpha = rgba.getchannel("A")
        alpha_arr = np.asarray(alpha, dtype=np.uint8)
        opaque = alpha_arr > 127
        partial = (alpha_arr > 0) & (alpha_arr < 255)
        h, w = alpha_arr.shape

        # Para entradas opacas, el damero se detecta sin asumir que sea parte
        # del diseño. El detector exige sus dos bandas neutras en el perímetro.
        checkerboard = False
        checker_alpha = None
        if not useful_alpha:
            try:
                checker_alpha = StickerProcessor._checkerboard_exterior_alpha(rgba)
                checkerboard = checker_alpha is not None
            except Exception:
                pass

        foreground = opaque
        foreground_isolated = bool(useful_alpha)
        if not useful_alpha and checkerboard:
            try:
                foreground = np.asarray(checker_alpha, dtype=np.uint8) > 127
                foreground_isolated = True
            except Exception:
                pass
        elif not useful_alpha and uniform_background:
            # Para un fondo uniforme opaco el alfa entero no representa al
            # sujeto. Usamos una extracción liviana solo para describir los
            # rasgos; el flujo técnico mantiene su propia máscara.
            try:
                estimated_alpha = StickerProcessor._uniform_background_alpha(
                    rgb, tolerance=42)
                estimated = np.asarray(estimated_alpha, dtype=np.uint8) > 127
                if 0 < float(estimated.mean()) < 0.96:
                    foreground = estimated
                    foreground_isolated = True
            except Exception:
                pass

        component_count = 0
        if checkerboard:
            # El damero capturado deja pequeños residuos aislados en el borde.
            # No se deben presentar como "múltiples objetos" del usuario.
            component_count = int(foreground.any())
        else:
            try:
                import cv2
                labels_count, _, stats, _ = cv2.connectedComponentsWithStats(
                    foreground.astype(np.uint8), connectivity=8)
                min_component_area = max(16, round(h * w * 0.0005))
                component_count = sum(
                    int(stats[label, cv2.CC_STAT_AREA]) >= min_component_area
                    for label in range(1, labels_count))
            except Exception:
                component_count = StickerProcessor._component_count(
                    Image.fromarray(foreground.astype(np.uint8) * 255), threshold=20)

        frame_contact_ratio = max(
            float(foreground[0, :].mean()), float(foreground[-1, :].mean()),
            float(foreground[:, 0].mean()), float(foreground[:, -1].mean()),
        )
        # Una mota aislada sobre el borde no significa que el sujeto esté
        # cortado. Exigimos una fracción visible de un lado del encuadre.
        touches_edges = bool(foreground_isolated and frame_contact_ratio >= 0.03)
        holes = StickerProcessor._closed_interior_mask(
            Image.fromarray(foreground.astype(np.uint8) * 255))
        has_internal_holes = holes.getbbox() is not None

        small = rgb.copy()
        small.thumbnail((192, 192))
        rgb_arr = np.asarray(small, dtype=np.uint8)
        gray_image = small.convert("L")
        edge = np.asarray(gray_image.filter(ImageFilter.FIND_EDGES), dtype=np.uint8)
        edge_density = float((edge > 38).mean())
        palette = small.convert("P", palette=1, colors=64).getcolors(192 * 192) or []
        palette_count = len(palette)
        high_edge_graphic = edge_density >= 0.17
        logo_or_typography = bool(
            not is_photo and palette_count <= 24 and high_edge_graphic)
        fine_lines = bool(
            not is_photo and edge_density >= 0.23 and palette_count <= 48)

        # Borde existente de color: se mide sobre la corona exterior del alfa,
        # nunca sobre el interior del diseño.
        colored_border = False
        border_color = None
        if useful_alpha and opaque.any():
            try:
                import cv2
                binary = opaque.astype(np.uint8) * 255
                outer = cv2.dilate(binary, np.ones((3, 3), np.uint8)) > 0
                inner = cv2.erode(binary, np.ones((3, 3), np.uint8)) > 0
                band = outer & ~inner & opaque
                values = np.asarray(rgb, dtype=np.uint8)[band]
                if values.size:
                    mean = values.mean(axis=0)
                    spread = float(mean.max() - mean.min())
                    brightness = float(mean.mean())
                    colored_border = spread >= 32 and brightness < 245
                    if colored_border:
                        border_color = [int(round(v)) for v in mean]
            except Exception:
                pass

        bg_luminance = float(0.299 * bg_color[0] + 0.587 * bg_color[1]
                             + 0.114 * bg_color[2])
        bg_neutral = max(bg_color) - min(bg_color) <= 22
        background_kind = (
            "damero_incrustado" if checkerboard else
            "transparente" if useful_alpha else
            "blanco" if uniform_background and bg_luminance >= 235 else
            "neutro" if uniform_background and bg_neutral else
            "color_uniforme" if uniform_background else
            "complejo"
        )
        textured_or_gradient = not uniform_background and not is_photo
        # Papel suele ser claro, ligeramente no uniforme y acompañado de
        # trazos contrastados; se expone como rasgo para revisión, no certeza.
        paper_like = bool(
            not useful_alpha and not checkerboard and bg_luminance >= 205
            and not uniform_background and edge_density >= 0.10)
        compression_artifacts = bool(
            min(w, h) < 160 or (edge_density > 0.32 and palette_count > 48))

        features = {
            "real_transparency": bool(alpha_arr.min() < 255),
            "semi_transparency": bool(partial.any()),
            "semi_transparent_ratio": round(float(partial.mean()), 4),
            "existing_border": bool(has_white_border or has_grey_border or colored_border),
            "border_kind": ("blanco" if has_white_border else
                            "gris" if has_grey_border else
                            "color" if colored_border else "ninguno"),
            "border_color_rgb": border_color,
            "object_count": int(component_count),
            "multiple_objects": bool(component_count > 1),
            "text_or_logo_hint": logo_or_typography,
            "fine_line_hint": fine_lines,
            "internal_holes": has_internal_holes,
            "background_kind": background_kind,
            "gradient_or_textured_background": textured_or_gradient,
            "subject_touches_frame": touches_edges,
            "frame_contact_ratio": round(frame_contact_ratio, 4),
            "paper_or_scan_hint": paper_like,
            "compression_artifacts_hint": compression_artifacts,
            "resolution": [int(w), int(h)],
            "edge_density": round(edge_density, 4),
            "palette_count": int(palette_count),
        }

        types: list[str] = []
        if logo_or_typography:
            types.append("logo_tipografia")
        if fine_lines:
            types.append("lineas_finas")
        if component_count > 1:
            types.append("multiples_objetos")
        if partial.any():
            types.append("semitransparencias")
        if colored_border:
            types.append("borde_color")
        if textured_or_gradient:
            types.append("fondo_degradado_texturizado")
        if touches_edges:
            types.append("sujeto_cortado_encuadre")
        if paper_like:
            types.append("dibujo_escaneado")
        return features, types

    # ──────────────────────────────────────────────────────────────────────────
    # PASO 1 + 2 — Análisis y clasificación
    # ──────────────────────────────────────────────────────────────────────────

    def classify(self, rgba, mode_override: str | None = None) -> ClassifyResult:
        """Analiza el contenido visual y devuelve el ImageCase adecuado.

        Árbol de decisiones (en orden de prioridad):
          1. ¿Tiene borde blanco continuo + figura recortada?  → Caso B
          2. ¿Tiene transparencia sin borde blanco?            → Caso A
          3. ¿Fondo de color uniforme?                         → Caso C
          4. Fotografía (muchos colores, degradados)           → Caso D
             (ilustración sin fondo uniforme también → Caso D con IA ligera)

        Si mode_override no es None se fuerza el caso correspondiente.
        """
        from PIL import ImageFilter, ImageStat

        reasons: list[str] = []

        # ── Señales básicas ───────────────────────────────────────────────────
        alpha_ch = rgba.getchannel("A")
        alpha_min, alpha_max = alpha_ch.getextrema()

        # Detectar si el alfa es realmente útil
        # Si min(alpha) == 255, no hay transparencia útil, aunque tenga canal alfa
        has_transparency = alpha_min < 250
        useful_alpha = alpha_min < 255  # True si hay algún píxel transparente

        # Diagnóstico
        logger.info(
            "Clasificación - modo=%s, alpha_min=%d, alpha_max=%d, useful_alpha=%s",
            rgba.mode, alpha_min, alpha_max, useful_alpha
        )

        rgb_small = rgba.convert("RGB").resize((128, 128))
        gray_small = rgb_small.convert("L")

        # Bordes de la imagen (muestra perimetral 128 px)
        pix = rgb_small.load()
        edge_px = []
        for x in range(128):
            edge_px.extend([pix[x, 0], pix[x, 127]])
        for y in range(1, 127):
            edge_px.extend([pix[0, y], pix[127, y]])

        means = tuple(sum(p[c] for p in edge_px) / len(edge_px) for c in range(3))
        spread = sum(abs(p[c] - means[c])
                     for p in edge_px for c in range(3)) / (len(edge_px) * 3)
        uniform_bg = spread < 22
        bg_color = tuple(int(m) for m in means)

        # Cantidad de colores únicos (reducido a paleta de 64)
        colors = rgb_small.convert("P", palette=1, colors=64).getcolors(8192) or []
        n_colors = len(colors)

        # Fuerza de bordes internos (Canny proxy)
        edge_strength = ImageStat.Stat(
            gray_small.filter(ImageFilter.FIND_EDGES)).mean[0]

        is_photo = (n_colors >= 48 and edge_strength < 22)
        if is_photo:
            reasons.append(f"Fotografía detectada ({n_colors} colores, "
                           f"bordes={edge_strength:.1f})")

        # ── ¿Tiene borde blanco continuo? (Caso B) ────────────────────────────
        has_white_border = False
        has_grey_border  = False
        has_black_outline = False
        if has_transparency:
            import numpy as np
            a_arr = np.asarray(alpha_ch.resize((128, 128)), dtype=np.uint8)
            rgb_arr = np.asarray(rgb_small, dtype=np.uint8)
            opaque = (a_arr > 127)
            # Píxeles blancos/casi blancos dentro de la zona opaca
            white_px = opaque & (rgb_arr[:,:,0]>210) & \
                       (rgb_arr[:,:,1]>210) & (rgb_arr[:,:,2]>210)
            white_ratio = white_px.sum() / max(1, opaque.sum())
            # El borde blanco existe si hay una banda perimetral blanca opaca
            has_white_border = bool(white_ratio > 0.12)
            if has_white_border:
                reasons.append(f"Borde blanco detectado ({white_ratio:.0%})")

            # ── Borde gris exterior ───────────────────────────────────────
            # Píxeles grises (R≈G≈B, todos entre 100 y 210) en la periferia
            # de la zona opaca → sombra o borde exterior de sticker previo.
            if not has_white_border:
                r, g, b = rgb_arr[:,:,0], rgb_arr[:,:,1], rgb_arr[:,:,2]
                # Neutro: los tres canales muy cercanos entre sí
                neutral = (np.abs(r.astype(int) - g.astype(int)) < 30) & \
                          (np.abs(g.astype(int) - b.astype(int)) < 30) & \
                          (np.abs(r.astype(int) - b.astype(int)) < 30)
                grey_px  = opaque & neutral & (r > 100) & (r < 215)
                grey_ratio = grey_px.sum() / max(1, opaque.sum())
                # Verificar además que ese gris está conectado al perímetro
                # usando solo los píxeles del borde de la máscara opaca
                try:
                    import cv2
                    op_u8  = opaque.astype(np.uint8) * 255
                    k_peri = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
                    # Banda *interior* pegada a la transparencia exterior:
                    # ahí aparece una sombra gris; no debe confundirse con
                    # gris dentro de una ilustración.
                    outside = (~opaque).astype(np.uint8) * 255
                    inner_edge = opaque & (cv2.dilate(outside, k_peri) > 127)
                    edge_grey_ratio = float((grey_px & inner_edge).sum()) / max(
                        1, int(inner_edge.sum()))
                    has_grey_border = bool(edge_grey_ratio >= 0.20)
                except (ImportError, ModuleNotFoundError):
                    has_grey_border = bool(grey_ratio > 0.05)
                if has_grey_border:
                    reasons.append(f"Borde gris detectado ({grey_ratio:.0%})")

            # Contorno negro: píxeles oscuros en la banda interior del alpha
            try:
                import cv2
                # La banda debe cubrir contornos internos de distinto grosor
                # después de reducir la imagen a 128 px; 9 px podía quedarse
                # solo en el borde de transparencia y perder outlines reales.
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
                op_u8 = opaque.astype(np.uint8) * 255
                band = cv2.dilate(cv2.bitwise_not(op_u8), kernel) & op_u8
                dark = (rgb_arr[:,:,0]<45) & (rgb_arr[:,:,1]<45) & \
                       (rgb_arr[:,:,2]<45)
                band_pixels = band > 0
                dark_ratio = float((dark & band_pixels).sum()) / max(
                    1, int(band_pixels.sum()))
                has_black_outline = dark_ratio >= 0.15
                if has_black_outline:
                    reasons.append(
                        f"Contorno negro detectado ({dark_ratio:.0%})")
            except (ImportError, ModuleNotFoundError):
                pass

        # ── Árbol de decisiones ───────────────────────────────────────────────
        # El modo manual sobreescribe la detección automática.
        # classify() también se usa de forma aislada por herramientas y tests.
        # En ese caso no necesita una instancia inicializada con perfil.
        forced = mode_override or getattr(self, "profile", ProcessingProfile()).mode
        is_sticker_on_neutral_bg = False

        if forced == ProcessingMode.EXISTING.value:
            case = ImageCase.B
            reasons.insert(0, "Modo forzado: Sticker existente")
        elif forced == ProcessingMode.PHOTO.value:
            case = ImageCase.D
            reasons.insert(0, "Modo forzado: Fotografía")
        elif forced in (ProcessingMode.ILLUSTRATION.value,
                        ProcessingMode.LOGO.value):
            case = ImageCase.A if has_transparency else ImageCase.C
            reasons.insert(0, f"Modo forzado: {forced}")
        else:
            # Automático
            # Usar useful_alpha en lugar de has_transparency para decidir
            # Si el alfa no es útil (todo opaco), tratar como fondo integrado
            if useful_alpha and has_white_border:
                case = ImageCase.B
                reasons.append("Auto → Caso B (sticker ya terminado)")
            elif useful_alpha and has_grey_border:
                # Sticker con borde gris/sombra exterior → mismo flujo B
                case = ImageCase.B
                reasons.append("Auto → Caso B (borde gris exterior detectado)")
            elif useful_alpha:
                case = ImageCase.A
                reasons.append("Auto → Caso A (PNG transparente)")
            elif uniform_bg:
                # ── ¿Sticker terminado sobre fondo neutro? ──────────────
                is_sticker_on_neutral_bg = False
                if not useful_alpha:
                    try:
                        border_info = self.analyze_original_border_structure(
                            rgba)
                        if (border_info["has_design"]
                                and border_info["white_in_ring_ratio"] >= 0.45
                                and not border_info["background_is_white"]):
                            is_sticker_on_neutral_bg = True
                    except Exception:
                        pass
                if is_sticker_on_neutral_bg:
                    case = ImageCase.B
                    has_white_border = True
                    reasons.append(
                        f"Auto → Caso B (sticker sobre fondo neutro, "
                        f"anillo blanco="
                        f"{border_info['white_in_ring_ratio']:.0%})")
                else:
                    case = ImageCase.C
                    reasons.append(
                        f"Auto → Caso C (fondo uniforme RGB{bg_color}, alfa no útil)")
            elif is_photo:
                case = ImageCase.D
                reasons.append("Auto → Caso D (fotografía)")
            else:
                case = ImageCase.C
                reasons.append("Auto → Caso C (ilustración sin fondo claro)")

        design_mode = ("Contorno interno"
                       if has_black_outline else "Color uniforme")
        sticker_type, sticker_type_label = self._describe_sticker_type(
            rgba, case,
            useful_alpha=useful_alpha,
            has_white_border=has_white_border,
            has_grey_border=has_grey_border,
            is_photo=is_photo,
            uniform_background=uniform_bg,
            bg_color=bg_color,
        )
        reasons.insert(0, f"Tipo: {sticker_type_label}")

        classification_features, secondary_types = self._classification_features(
            rgba,
            useful_alpha=useful_alpha,
            has_white_border=has_white_border,
            has_grey_border=has_grey_border,
            uniform_background=uniform_bg,
            bg_color=bg_color,
            is_photo=is_photo,
        )
        detected_types = [sticker_type, *(
            item for item in secondary_types if item != sticker_type)]
        if secondary_types:
            reasons.append(
                "Características: " + ", ".join(
                    item.replace("_", " ") for item in secondary_types))

        # Diagnóstico completo
        logger.info(
            "DIAGNÓSTICO CLASIFICACIÓN: "
            "modo=%s, alpha_min=%d, alpha_max=%d, useful_alpha=%s, "
            "case=%s, design_mode=%s, bg_color=%s, uniform_bg=%s, is_photo=%s, "
            "has_white_border=%s, has_grey_border=%s, has_black_outline=%s, "
            "reasons=%s",
            rgba.mode, alpha_min, alpha_max, useful_alpha,
            case.value if hasattr(case, 'value') else str(case),
            design_mode, bg_color, uniform_bg, is_photo,
            has_white_border, has_grey_border, has_black_outline,
            reasons
        )

        return ClassifyResult(
            case=case,
            design_mode=design_mode,
            reasons=reasons,
            has_transparency=has_transparency,
            has_white_border=has_white_border,
            has_grey_border=has_grey_border,
            has_black_outline=has_black_outline,
            uniform_background=uniform_bg,
            is_photo=is_photo,
            bg_color=bg_color,
            is_sticker_on_neutral_bg=is_sticker_on_neutral_bg,
            sticker_type=sticker_type,
            sticker_type_label=sticker_type_label,
            detected_types=detected_types,
            classification_features=classification_features,
        )

    @staticmethod
    def _has_real_transparency(rgba) -> tuple[bool, bool]:
        """Check if image has real transparency or integrated background.

        Returns:
            (has_transparency, has_integrated_background)
            - has_transparency: True if any pixel has alpha < 255
            - has_integrated_background: True if all pixels have alpha = 255
        """
        try:
            import numpy as np
            alpha_ch = rgba.getchannel("A")
            alpha_arr = np.asarray(alpha_ch, dtype=np.uint8)
            has_transparency = alpha_arr.min() < 255
            has_integrated_background = alpha_arr.min() == 255 and alpha_arr.max() == 255
            return has_transparency, has_integrated_background
        except (ImportError, ModuleNotFoundError):
            alpha_ch = rgba.getchannel("A")
            min_alpha, max_alpha = alpha_ch.getextrema()
            has_transparency = min_alpha < 255
            has_integrated_background = min_alpha == 255 and max_alpha == 255
            return has_transparency, has_integrated_background

    @staticmethod
    def _remove_integrated_background_flood_fill(rgba, tolerance: int = 25) -> "Image":
        """Remove integrated background using edge-connected flood fill.

        Only removes background pixels connected to the image edges, preserving
        isolated light grey/white areas in the design.

        Args:
            rgba: PIL Image in RGBA mode
            tolerance: Color tolerance for background matching

        Returns:
            PIL Image in L mode (alpha channel)
        """
        try:
            import numpy as np
            from PIL import Image

            rgb = rgba.convert("RGB")
            w, h = rgb.size
            rgb_arr = np.asarray(rgb, dtype=np.uint8)

            # Sample background color from corners
            corners = [
                rgb.getpixel((0, 0)),
                rgb.getpixel((w-1, 0)),
                rgb.getpixel((0, h-1)),
                rgb.getpixel((w-1, h-1))
            ]

            # Use median of corners as background color
            bg_color = tuple(
                int(sorted([c[i] for c in corners])[len(corners)//2])
                for i in range(3)
            )

            logger.info(f"EDGE_FLOOD_FILL: bg_color={bg_color}, tolerance={tolerance}")

            # Create mask of pixels similar to background color
            # Fixed: Use AND logic (all channels must match) instead of OR
            bg_arr = np.asarray(bg_color, dtype=np.int16).reshape(1, 1, 3)
            delta = np.abs(rgb_arr.astype(np.int16) - bg_arr)
            bg_mask = np.all(delta <= tolerance, axis=2)
            bg_mask = StickerProcessor._restrict_to_edge_ring(bg_mask.astype(np.uint8), margin_px=12).astype(bool)

            # Flood fill from edges: only mark pixels connected to edges as background
            from collections import deque
            queue = deque()
            visited = np.zeros((h, w), dtype=bool)

            # Start from all edge pixels that match background color
            for x in range(w):
                if bg_mask[0, x]:
                    queue.append((x, 0))
                    visited[0, x] = True
                if bg_mask[h-1, x]:
                    queue.append((x, h-1))
                    visited[h-1, x] = True
            for y in range(h):
                if bg_mask[y, 0]:
                    queue.append((0, y))
                    visited[y, 0] = True
                if bg_mask[y, w-1]:
                    queue.append((w-1, y))
                    visited[y, w-1] = True

            # BFS flood fill - only mark connected pixels
            while queue:
                x, y = queue.popleft()
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h:
                        if bg_mask[ny, nx] and not visited[ny, nx]:
                            visited[ny, nx] = True
                            queue.append((nx, ny))

            # Create alpha: transparent only for visited (edge-connected) background pixels
            alpha_arr = np.where(visited, np.uint8(0), np.uint8(255))
            alpha = Image.fromarray(alpha_arr, mode="L")

            logger.info(f"EDGE_FLOOD_FILL_COMPLETE: extrema={alpha.getextrema()}, bbox={alpha.getbbox()}, bg_removed={visited.sum()}")
            return alpha

        except Exception as e:
            logger.error(f"EDGE_FLOOD_FILL_ERROR: {e} - using threshold fallback")
            # Fallback: simple threshold
            from PIL import Image
            rgb = rgba.convert("RGB")
            w, h = rgb.size
            corners = [
                rgb.getpixel((0, 0)),
                rgb.getpixel((w-1, 0)),
                rgb.getpixel((0, h-1)),
                rgb.getpixel((w-1, h-1))
            ]
            bg_color = tuple(
                int(sorted([c[i] for c in corners])[len(corners)//2])
                for i in range(3)
            )

            alpha = Image.new("L", rgb.size, 255)
            pixels = alpha.load()
            rgb_pixels = rgb.load()

            for y in range(h):
                for x in range(w):
                    pixel = rgb_pixels[x, y]
                    if max(abs(pixel[i] - bg_color[i]) for i in range(3)) <= tolerance:
                        pixels[x, y] = 0

            return alpha

    @staticmethod
    @staticmethod
    def _is_png_border_only(source_path: str | Path) -> bool:
        """True for PNG inputs that must be treated as border-only.

        The rule is intentionally strict: all PNG inputs go through a
        non-destructive border generation path and never through background
        subtraction/removal logic that would alter the artwork.
        """
        path = Path(source_path)
        return path.suffix.lower() == ".png"

    @staticmethod
    def _add_transparent_padding(rgba, padding_px: int = 50) -> "Image":
        """Add transparent padding around the image.

        This function adds transparent padding to ensure that borders
        can be generated without cutting off the original white border.

        Args:
            rgba: PIL Image in RGBA mode
            padding_px: Padding amount in pixels (default 50, range 40-60)

        Returns:
            PIL Image in RGBA mode with padding
        """
        from PIL import Image

        w, h = rgba.size
        padding = max(40, min(60, padding_px))

        # Create new canvas with padding
        new_w = w + 2 * padding
        new_h = h + 2 * padding
        padded = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))

        # Paste original image in center
        padded.paste(rgba, (padding, padding))

        return padded

    @staticmethod
    def _apply_morphological_closing(alpha, kernel_size: int = 3, iterations: int = 1) -> "Image":
        """Apply morphological closing to fix small discontinuities.

        This function uses morphological closing (dilation followed by erosion)
        to fix small discontinuities in the mask without destroying the original
        white border as erosion would do.

        Args:
            alpha: PIL Image in L mode (alpha channel)
            kernel_size: Size of the morphological kernel (default 3x3)
            iterations: Number of iterations (default 1)

        Returns:
            PIL Image in L mode
        """
        try:
            import cv2
            import numpy as np
            from PIL import Image

            arr = np.asarray(alpha.convert("L"), dtype=np.uint8)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                             (kernel_size, kernel_size))
            closed = cv2.morphologyEx(arr, cv2.MORPH_CLOSE, kernel, iterations=iterations)
            return Image.fromarray(closed, mode="L")

        except (ImportError, ModuleNotFoundError):
            from PIL import ImageFilter
            # Fallback: use MaxFilter (dilation) followed by MinFilter (erosion)
            result = alpha.filter(ImageFilter.MaxFilter(kernel_size))
            result = result.filter(ImageFilter.MinFilter(kernel_size))
            return result

    @staticmethod
    def _generate_borders_from_alpha(alpha, white_border_px: int = 30, black_border_px: int = 2) -> tuple["Image", "Image"]:
        """Generate white and black borders using alpha mask dilation.

        This function generates borders by dilating the alpha mask, which ensures
        that the borders are generated from the actual design shape rather than
        from cropped contours against the canvas.

        Args:
            alpha: PIL Image in L mode (alpha channel)
            white_border_px: Width of white border in pixels (default 30)
            black_border_px: Width of black border in pixels (default 2)

        Returns:
            Tuple of (white_border_mask, black_border_mask) as PIL Images in L mode
        """
        try:
            import cv2
            import numpy as np
            from PIL import Image

            arr = np.asarray(alpha.convert("L"), dtype=np.uint8)

            # Generate white border by dilation
            white_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                                     (white_border_px * 2 + 1, white_border_px * 2 + 1))
            white_border = cv2.dilate(arr, white_kernel, iterations=1)
            white_mask = Image.fromarray(white_border, mode="L")

            # Generate black border by further dilation of white border
            black_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                                     (black_border_px * 2 + 1, black_border_px * 2 + 1))
            black_border = cv2.dilate(white_border, black_kernel, iterations=1)
            black_mask = Image.fromarray(black_border, mode="L")

            return white_mask, black_mask

        except (ImportError, ModuleNotFoundError):
            from PIL import ImageFilter
            # Fallback using PIL filters
            white_border = alpha.filter(ImageFilter.MaxFilter(white_border_px * 2 + 1))
            black_border = white_border.filter(ImageFilter.MaxFilter(black_border_px * 2 + 1))
            return white_border, black_border

    @staticmethod
    def _generate_non_destructive_border(content_rgba, border_px: int = 30) -> "Image":
        """CORRECCIÓN 5: Generar borde blanco sin deformar el contenido.

        Mantiene dos máscaras diferentes:
        - content_alpha: contenido original, no se modifica
        - border_alpha: dilatación exterior

        Genera el borde únicamente hacia afuera:
        1. Extraer content_alpha del RGBA original
        2. Dilatar solo hacia afuera para crear border_alpha
        3. Componer: lienzo transparente → borde blanco exterior → imagen original RGBA sin alterar

        Nunca dilatar, cerrar o suavizar el alfa del contenido original.

        Args:
            content_rgba: PIL Image in RGBA mode (original content)
            border_px: Width of white border in pixels (default 30)

        Returns:
            PIL Image in RGBA mode with white border added without deforming content
        """
        logger.info("_generate_non_destructive_border: Starting, border_px=%d, size=%s", border_px, content_rgba.size)

        try:
            import cv2
            import numpy as np
            from PIL import Image

            logger.info("_generate_non_destructive_border: Using OpenCV path")
            # Extraer alfa original del contenido
            content_alpha = content_rgba.getchannel("A").copy()

            # Convertir a array numpy
            binary = (np.asarray(content_alpha, dtype=np.uint8) > 0).astype(np.uint8)
            h, w = binary.shape
            logger.info("_generate_non_destructive_border: Binary mask shape=%s", binary.shape)

            # Crear kernel elíptico para dilatación exterior
            kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (border_px * 2 + 1, border_px * 2 + 1),
            )
            logger.info("_generate_non_destructive_border: Kernel created, size=%s", kernel.shape)

            # Dilatar solo hacia afuera
            expanded = cv2.dilate(binary, kernel, iterations=1)
            logger.info("_generate_non_destructive_border: Dilation completed")

            # Crear máscara de borde solo (expandido - original)
            border_only = (expanded > 0) & (binary == 0)
            border_mask = border_only.astype(np.uint8) * 255
            logger.info("_generate_non_destructive_border: Border mask created, pixels=%d", int(border_mask.sum()))

            # Crear lienzo transparente
            canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))

            # 1. Agregar borde blanco exterior
            border_layer = Image.new("RGBA", (w, h), (255, 255, 255, 255))
            border_layer.putalpha(Image.fromarray(border_mask, mode="L"))
            canvas.alpha_composite(border_layer)
            logger.info("_generate_non_destructive_border: Border layer composited")

            # 2. Componer imagen original RGBA sin alterar
            canvas.alpha_composite(content_rgba)
            logger.info("_generate_non_destructive_border: Content composited, completed")

            return canvas

        except (ImportError, ModuleNotFoundError) as e:
            logger.warning("_generate_non_destructive_border: OpenCV not available, using PIL fallback: %s", e)
            # Fallback PIL puro
            from PIL import Image, ImageFilter, ImageChops

            content_alpha = content_rgba.getchannel("A").copy()
            binary = content_alpha.point(lambda v: 255 if v > 127 else 0)

            # Dilatar usando MaxFilter
            expanded = binary.filter(ImageFilter.MaxFilter(border_px * 2 + 1))
            border_only = ImageChops.subtract(expanded, binary)

            # Crear lienzo y componer
            w, h = content_rgba.size
            canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))

            # Borde blanco
            border_layer = Image.new("RGBA", (w, h), (255, 255, 255, 255))
            border_layer.putalpha(border_only)
            canvas.alpha_composite(border_layer)

            # Contenido original
            canvas.alpha_composite(content_rgba)

            logger.info("_generate_non_destructive_border: PIL fallback completed")
            return canvas
        except Exception as e:
            logger.exception("_generate_non_destructive_border: Unexpected error, returning original")
            # Return original if anything fails
            return content_rgba

    @staticmethod
    def _safe_crop_with_margin(rgba, alpha, safety_margin_px: int = 15) -> "Image":
        """Crop image with safety margin and edge check.

        This function crops the image to the bounding box of the alpha mask
        while ensuring a safety margin. If any opaque pixel touches the edge
        after cropping, it automatically adds more padding.

        Args:
            rgba: PIL Image in RGBA mode
            alpha: PIL Image in L mode (alpha channel)
            safety_margin_px: Safety margin in pixels (default 15)

        Returns:
            Cropped PIL Image in RGBA mode
        """
        from PIL import Image
        import numpy as np

        # Get bounding box of the alpha mask
        bbox = alpha.getbbox()
        if bbox is None:
            return rgba

        x1, y1, x2, y2 = bbox

        # Add safety margin
        w, h = rgba.size
        x1 = max(0, x1 - safety_margin_px)
        y1 = max(0, y1 - safety_margin_px)
        x2 = min(w, x2 + safety_margin_px)
        y2 = min(h, y2 + safety_margin_px)

        # Crop the image
        cropped = rgba.crop((x1, y1, x2, y2))

        # Check if any opaque pixel touches the edge
        try:
            cropped_alpha = cropped.getchannel("A")
            cropped_arr = np.asarray(cropped_alpha, dtype=np.uint8)
            h_c, w_c = cropped_arr.shape

            # Check edges
            top_edge = (cropped_arr[0, :] > 127).any()
            bottom_edge = (cropped_arr[-1, :] > 127).any()
            left_edge = (cropped_arr[:, 0] > 127).any()
            right_edge = (cropped_arr[:, -1] > 127).any()

            # If any edge has opaque pixels, add padding and retry
            if top_edge or bottom_edge or left_edge or right_edge:
                # Add padding
                padding = safety_margin_px
                new_w = w_c + 2 * padding
                new_h = h_c + 2 * padding
                padded = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))
                padded.paste(cropped, (padding, padding))
                return padded
            else:
                return cropped

        except (ImportError, ModuleNotFoundError):
            # Fallback without edge check
            return cropped

    @staticmethod
    def _full_image_shape_alpha(size: tuple[int, int], shape: str):
        """Devuelve una máscara para los cortes de imagen completa.

        ``Personalizado`` se resuelve con la máscara no destructiva del
        editor, por eso esta función no inventa una forma para ese caso.
        """
        from PIL import Image, ImageDraw

        normalized = (shape or "Rectangular").strip().casefold()
        if normalized.startswith("rect") or normalized.startswith("personal"):
            return None

        width, height = size
        mask = Image.new("L", size, 0)
        draw = ImageDraw.Draw(mask)
        if normalized.startswith("circ"):
            side = min(width, height)
            left = (width - side) // 2
            top = (height - side) // 2
            draw.ellipse((left, top, left + side - 1, top + side - 1), fill=255)
        elif normalized.startswith("oval"):
            draw.ellipse((0, 0, width - 1, height - 1), fill=255)
        else:
            return None
        return mask

    @staticmethod
    def _split_foreground_components(alpha):
        """Obtiene máscaras independientes sin alterar la máscara original."""
        try:
            from PIL import Image
            import cv2
            import numpy as np

            arr = np.asarray(alpha.convert("L"), dtype=np.uint8)
            binary = (arr > 12).astype(np.uint8)
            labels_count, labels, stats, _ = cv2.connectedComponentsWithStats(
                binary, connectivity=8)
            minimum_area = max(12, round(arr.size * 0.0001))
            found = []
            for label in range(1, labels_count):
                x, y, width, height, area = stats[label]
                if int(area) < minimum_area:
                    continue
                component = np.where(labels == label, arr, 0).astype(np.uint8)
                found.append((
                    int(area), (int(x), int(y), int(width), int(height)),
                    Image.fromarray(component, mode="L"),
                ))
            found.sort(key=lambda entry: entry[0], reverse=True)
            return found
        except (ImportError, ModuleNotFoundError):
            bbox = alpha.getbbox()
            return [] if bbox is None else [(int((alpha.point(lambda value: value > 12).getbbox() is not None)), bbox, alpha.convert("L"))]

    def classify(self, rgba, mode_override: str | None = None) -> ClassifyResult:
        """Analiza el contenido visual y devuelve el ImageCase adecuado.

        Árbol de decisiones (en orden de prioridad):
          1. ¿Tiene borde blanco continuo + figura recortada?  → Caso B
          2. ¿Tiene transparencia sin borde blanco?            → Caso A
          3. ¿Fondo de color uniforme?                         → Caso C
          4. Fotografía (muchos colores, degradados)           → Caso D
             (ilustración sin fondo uniforme también → Caso D con IA ligera)

        Si mode_override no es None se fuerza el caso correspondiente.
        """
        from PIL import ImageFilter, ImageStat

        reasons: list[str] = []

        # ── Señales básicas ───────────────────────────────────────────────────
        alpha_ch = rgba.getchannel("A")
        alpha_min, alpha_max = alpha_ch.getextrema()

        # Detectar si el alfa es realmente útil
        # Si min(alpha) == 255, no hay transparencia útil, aunque tenga canal alfa
        has_transparency = alpha_min < 250
        useful_alpha = alpha_min < 255  # True si hay algún píxel transparente

        # Diagnóstico
        logger.info(
            "Clasificación - modo=%s, alpha_min=%d, alpha_max=%d, useful_alpha=%s",
            rgba.mode, alpha_min, alpha_max, useful_alpha
        )

        rgb_small = rgba.convert("RGB").resize((128, 128))
        gray_small = rgb_small.convert("L")

        # Bordes de la imagen (muestra perimetral 128 px)
        pix = rgb_small.load()
        edge_px = []
        for x in range(128):
            edge_px.extend([pix[x, 0], pix[x, 127]])
        for y in range(1, 127):
            edge_px.extend([pix[0, y], pix[127, y]])

        means = tuple(sum(p[c] for p in edge_px) / len(edge_px) for c in range(3))
        spread = sum(abs(p[c] - means[c])
                     for p in edge_px for c in range(3)) / (len(edge_px) * 3)
        uniform_bg = spread < 22
        bg_color = tuple(int(m) for m in means)

        # Cantidad de colores únicos (reducido a paleta de 64)
        colors = rgb_small.convert("P", palette=1, colors=64).getcolors(8192) or []
        n_colors = len(colors)

        # Fuerza de bordes internos (Canny proxy)
        edge_strength = ImageStat.Stat(
            gray_small.filter(ImageFilter.FIND_EDGES)).mean[0]

        is_photo = (n_colors >= 48 and edge_strength < 22)
        if is_photo:
            reasons.append(f"Fotografía detectada ({n_colors} colores, "
                           f"bordes={edge_strength:.1f})")

        # ── ¿Tiene borde blanco continuo? (Caso B) ────────────────────────────
        has_white_border = False
        has_grey_border  = False
        has_black_outline = False
        if has_transparency:
            import numpy as np
            a_arr = np.asarray(alpha_ch.resize((128, 128)), dtype=np.uint8)
            rgb_arr = np.asarray(rgb_small, dtype=np.uint8)
            opaque = (a_arr > 127)
            # Píxeles blancos/casi blancos dentro de la zona opaca
            white_px = opaque & (rgb_arr[:,:,0]>210) & \
                       (rgb_arr[:,:,1]>210) & (rgb_arr[:,:,2]>210)
            white_ratio = white_px.sum() / max(1, opaque.sum())
            # El borde blanco existe si hay una banda perimetral blanca opaca
            has_white_border = bool(white_ratio > 0.12)
            if has_white_border:
                reasons.append(f"Borde blanco detectado ({white_ratio:.0%})")

            # ── Borde gris exterior ───────────────────────────────────────
            # Píxeles grises (R≈G≈B, todos entre 100 y 210) en la periferia
            # de la zona opaca → sombra o borde exterior de sticker previo.
            if not has_white_border:
                r, g, b = rgb_arr[:,:,0], rgb_arr[:,:,1], rgb_arr[:,:,2]
                # Neutro: los tres canales muy cercanos entre sí
                neutral = (np.abs(r.astype(int) - g.astype(int)) < 30) & \
                          (np.abs(g.astype(int) - b.astype(int)) < 30) & \
                          (np.abs(r.astype(int) - b.astype(int)) < 30)
                grey_px  = opaque & neutral & (r > 100) & (r < 215)
                grey_ratio = grey_px.sum() / max(1, opaque.sum())
                # Verificar además que ese gris está conectado al perímetro
                # usando solo los píxeles del borde de la máscara opaca
                try:
                    import cv2
                    op_u8  = opaque.astype(np.uint8) * 255
                    k_peri = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
                    # Banda *interior* pegada a la transparencia exterior:
                    # ahí aparece una sombra gris; no debe confundirse con
                    # gris dentro de una ilustración.
                    outside = (~opaque).astype(np.uint8) * 255
                    inner_edge = opaque & (cv2.dilate(outside, k_peri) > 127)
                    edge_grey_ratio = float((grey_px & inner_edge).sum()) / max(
                        1, int(inner_edge.sum()))
                    has_grey_border = bool(edge_grey_ratio >= 0.20)
                except (ImportError, ModuleNotFoundError):
                    has_grey_border = bool(grey_ratio > 0.05)
                if has_grey_border:
                    reasons.append(f"Borde gris detectado ({grey_ratio:.0%})")

            # Contorno negro: píxeles oscuros en la banda interior del alpha
            try:
                import cv2
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
                op_u8 = opaque.astype(np.uint8) * 255
                band = cv2.dilate(cv2.bitwise_not(op_u8), kernel) & op_u8
                dark = (rgb_arr[:,:,0]<45) & (rgb_arr[:,:,1]<45) & \
                       (rgb_arr[:,:,2]<45)
                band_pixels = band > 0
                dark_ratio = float((dark & band_pixels).sum()) / max(
                    1, int(band_pixels.sum()))
                has_black_outline = dark_ratio >= 0.15
                if has_black_outline:
                    reasons.append(
                        f"Contorno negro detectado ({dark_ratio:.0%})")
            except (ImportError, ModuleNotFoundError):
                pass

        # ── Árbol de decisiones ───────────────────────────────────────────────
        # El modo manual sobreescribe la detección automática.
        # classify() también se usa de forma aislada por herramientas y tests.
        # En ese caso no necesita una instancia inicializada con perfil.
        forced = mode_override or getattr(self, "profile", ProcessingProfile()).mode
        is_sticker_on_neutral_bg = False

        if forced == ProcessingMode.EXISTING.value:
            case = ImageCase.B
            reasons.insert(0, "Modo forzado: Sticker existente")
        elif forced == ProcessingMode.PHOTO.value:
            case = ImageCase.D
            reasons.insert(0, "Modo forzado: Fotografía")
        elif forced in (ProcessingMode.ILLUSTRATION.value,
                        ProcessingMode.LOGO.value):
            case = ImageCase.A if has_transparency else ImageCase.C
            reasons.insert(0, f"Modo forzado: {forced}")
        else:
            # Automático
            # Usar useful_alpha en lugar de has_transparency para decidir
            # Si el alfa no es útil (todo opaco), tratar como fondo integrado
            if useful_alpha and has_white_border:
                case = ImageCase.B
                reasons.append("Auto → Caso B (sticker ya terminado)")
            elif useful_alpha and has_grey_border:
                # Sticker con borde gris/sombra exterior → mismo flujo B
                case = ImageCase.B
                reasons.append("Auto → Caso B (borde gris exterior detectado)")
            elif useful_alpha:
                case = ImageCase.A
                reasons.append("Auto → Caso A (PNG transparente)")
            elif uniform_bg:
                # ── ¿Sticker terminado sobre fondo neutro? ──────────────
                is_sticker_on_neutral_bg = False
                if not useful_alpha:
                    try:
                        border_info = self.analyze_original_border_structure(
                            rgba)
                        if (border_info["has_design"]
                                and border_info["white_in_ring_ratio"] >= 0.45
                                and not border_info["background_is_white"]):
                            is_sticker_on_neutral_bg = True
                    except Exception:
                        pass
                if is_sticker_on_neutral_bg:
                    case = ImageCase.B
                    has_white_border = True
                    reasons.append(
                        f"Auto → Caso B (sticker sobre fondo neutro, "
                        f"anillo blanco="
                        f"{border_info['white_in_ring_ratio']:.0%})")
                else:
                    case = ImageCase.C
                    reasons.append(
                        f"Auto → Caso C (fondo uniforme RGB{bg_color}, alfa no útil)")
            elif is_photo:
                case = ImageCase.D
                reasons.append("Auto → Caso D (fotografía)")
            else:
                case = ImageCase.C
                reasons.append("Auto → Caso C (ilustración sin fondo claro)")

        design_mode = ("Contorno interno"
                       if has_black_outline else "Color uniforme")

        sticker_type, sticker_type_label = self._describe_sticker_type(
            rgba, case,
            useful_alpha=useful_alpha,
            has_white_border=has_white_border,
            has_grey_border=has_grey_border,
            is_photo=is_photo,
            uniform_background=uniform_bg,
            bg_color=bg_color,
        )
        reasons.insert(0, f"Tipo: {sticker_type_label}")

        # El tipo principal y los rasgos adicionales se guardan por separado.
        # Un logo con transparencia y líneas finas, por ejemplo, no se fuerza
        # a una sola casilla ni se confunde con el caso A/B/C/D que lo procesa.
        classification_features, secondary_types = self._classification_features(
            rgba,
            useful_alpha=useful_alpha,
            has_white_border=has_white_border,
            has_grey_border=has_grey_border,
            uniform_background=uniform_bg,
            bg_color=bg_color,
            is_photo=is_photo,
        )
        detected_types = [sticker_type, *(
            item for item in secondary_types if item != sticker_type)]
        if secondary_types:
            labels = [VISUAL_STICKER_TYPE_LABELS.get(item, item.replace("_", " "))
                      for item in secondary_types]
            reasons.append("Rasgos visuales: " + ", ".join(labels))

        # Diagnóstico completo
        logger.info(
            "DIAGNÓSTICO CLASIFICACIÓN: "
            "modo=%s, alpha_min=%d, alpha_max=%d, useful_alpha=%s, "
            "case=%s, design_mode=%s, bg_color=%s, uniform_bg=%s, is_photo=%s, "
            "has_white_border=%s, has_grey_border=%s, has_black_outline=%s, "
            "reasons=%s",
            rgba.mode, alpha_min, alpha_max, useful_alpha,
            case.value if hasattr(case, 'value') else str(case),
            design_mode, bg_color, uniform_bg, is_photo,
            has_white_border, has_grey_border, has_black_outline,
            reasons
        )

        return ClassifyResult(
            case=case,
            design_mode=design_mode,
            reasons=reasons,
            has_transparency=has_transparency,
            has_white_border=has_white_border,
            has_grey_border=has_grey_border,
            has_black_outline=has_black_outline,
            uniform_background=uniform_bg,
            is_photo=is_photo,
            bg_color=bg_color,
            is_sticker_on_neutral_bg=is_sticker_on_neutral_bg,
            sticker_type=sticker_type,
            sticker_type_label=sticker_type_label,
            detected_types=detected_types,
            classification_features=classification_features,
        )

    def _analyze_rgba(self, rgba, source_size: tuple[int, int] | None = None) -> Analysis:
        """Analiza una imagen ya cargada, sin volver a decodificar el archivo."""
        from PIL import ImageFilter, ImageStat
        alpha = rgba.getchannel("A")
        has_transparency = alpha.getextrema()[0] < 250
        w, h = source_size or rgba.size
        sample = rgba.convert("RGB").resize((64, 64))
        pix = sample.load()
        edge = []
        for x in range(64):
            edge.extend([pix[x, 0], pix[x, 63]])
        for y in range(1, 63):
            edge.extend([pix[0, y], pix[63, y]])
        means = tuple(sum(p[c] for p in edge) / len(edge) for c in range(3))
        spread = sum(abs(p[c] - means[c])
                     for p in edge for c in range(3)) / (len(edge) * 3)
        uniform = spread < 19
        vis = sum(v > 12 for v in alpha.resize((64, 64)).get_flattened_data()) / (64 * 64)
        looks_prepared = has_transparency and vis < 0.96
        colors = sample.convert("P", palette=1, colors=64).getcolors(4096) or []
        edges = sample.convert("L").filter(ImageFilter.FIND_EDGES)
        es = ImageStat.Stat(edges).mean[0]
        kind = "Logo o ilustración" if len(colors) < 48 or es > 22 \
               else "Fotografía"
        if looks_prepared: engine = "Transparente"
        elif uniform:      engine = "Rápido"
        elif kind != "Fotografía": engine = "Híbrido"
        else:              engine = "IA"
        return Analysis(
            engine=engine, has_transparency=has_transparency,
            uniform_background=uniform, looks_prepared=looks_prepared,
            kind=kind,
            main_elements=max(1, self._component_count(
                alpha if has_transparency else edges, threshold=24)),
            has_text_hint=False,
            resolution_ok=max(w, h) >= self.profile.master_pixels,
            width=w, height=h,
        )

    def analyze(self, path: str | Path) -> Analysis:
        """Análisis rápido para metadatos y control de calidad."""
        from PIL import Image
        with Image.open(path) as src:
            rgba = src.convert("RGBA")
        return self._analyze_rgba(rgba)

    # ──────────────────────────────────────────────────────────────────────────
    # FLUJO A — PNG transparente sin borde
    # ──────────────────────────────────────────────────────────────────────────

    def _flow_a(self, rgba, classify_result: ClassifyResult,
                progress: Callable, fill_closed_holes: bool = True) -> "Image":
        """PNG con transparencia pero sin borde blanco.

        CORRECCIÓN 1-5: Para PNG con transparencia real, preservar contenido original.

        1. Verificar si tiene transparencia real (alpha_min < 255)
        2. Si tiene transparencia real:
           - Limpiar RGB oculto antes de cualquier operación (set to white where alpha == 0)
           - Usar alfa original sin modificaciones
           - NO aplicar _clean_alpha()
           - NO aplicar _preserve_closed_interiors()
           - NO aplicar _extract_to_inner_contour()
           - NO aplicar operaciones morfológicas
        3. Si no tiene transparencia real: procesar normalmente
        4. Devolver la imagen RGBA recortada con máscara corregida.
        """
        from PIL import Image, ImageChops, ImageFilter

        progress(20, "Flujo A: verificando transparencia real")
        alpha_original = rgba.getchannel("A")
        alpha_min, alpha_max = alpha_original.getextrema()

        # CORRECCIÓN 1-3: Detectar transparencia real
        has_real_transparency = alpha_min < 255

        logger.info(
            "FLOW_A: has_real_transparency=%s, alpha_min=%d, alpha_max=%d",
            has_real_transparency, alpha_min, alpha_max
        )

        if has_real_transparency:
            # CORRECCIÓN 1: Limpiar RGB oculto antes de operaciones
            progress(22, "Flujo A: limpiando RGB oculto bajo transparencia")
            try:
                rgba = self.clean_hidden_rgb(rgba)
                logger.info("FLOW_A: clean_hidden_rgb completed successfully")
            except Exception as e:
                logger.exception("FLOW_A: Error in clean_hidden_rgb, using original rgba")
                # Continuar con el original si falla la limpieza

            # CORRECCIÓN 1-3: Usar alfa original sin modificaciones
            progress(25, "Flujo A: usando alfa original sin modificaciones")
            alpha = alpha_original.copy()
            # Los PNG son arte final, pero un hueco transparente totalmente
            # encerrado (por ejemplo el centro de una letra o un anillo) se
            # imprime como parte de la base blanca del sticker. Solo se
            # completa cuando el formato lo solicita; el exterior conectado
            # permanece idéntico al alfa original.
            holes = self._closed_interior_mask(alpha) if fill_closed_holes else None
            if holes and holes.getbbox():
                alpha = self._preserve_closed_interiors(alpha)

            # NO aplicar _clean_alpha, _preserve_closed_interiors, etc.
            # El alfa original no debe reconstruirse ni simplificarse
        else:
            # Procesamiento normal para PNG sin transparencia real
            progress(20, "Flujo A: extrayendo canal alpha")
            alpha = rgba.getchannel("A")
            alpha = self._clean_alpha(alpha)

            # Los PNG se usan como arte final y sus huecos interiores se imprimen
            # blancos; otros formatos conservan su transparencia original.
            if fill_closed_holes:
                progress(28, "Flujo A: reparando huecos internos")
                holes = self._closed_interior_mask(alpha)
                alpha = self._preserve_closed_interiors(alpha)
            else:
                holes = None

            # Refinar hacia el contorno negro si aplica
            if classify_result.has_black_outline:
                progress(34, "Flujo A: refinando a contorno negro")
                alpha = self._extract_to_inner_contour(rgba, alpha)

            # Suavizar borde de la máscara
            progress(40, "Flujo A: suavizando máscara")
            alpha = self._clean_alpha(alpha)

        result = rgba.copy()
        if holes and holes.getbbox():
            result.paste((255, 255, 255, 255), mask=holes)
        result.putalpha(alpha)
        return result

    # ──────────────────────────────────────────────────────────────────────────
    # FLUJO B — Sticker ya terminado
    # ──────────────────────────────────────────────────────────────────────────

    def _flow_b(self, rgba, classify_result: ClassifyResult,
                progress: Callable) -> "Image":
        """Sticker existente con borde blanco o gris exterior.

        1. Eliminar borde exterior (blanco o gris) por flood fill selectivo.
        2. Limpiar residuos y reconstruir máscara binaria.
        3. Rellenar huecos cerrados internos.
        4. Si había borde gris: aplicar trazo blanco interno para cubrir
           cualquier tono gris residual pegado al diseño.
        5. Si hay contorno negro propio: refinar hacia ese contorno.
        6. Suavizar contorno final.
        """
        from PIL import Image, ImageFilter

        has_grey = classify_result.has_grey_border

        # Record B0: original alpha
        if getattr(self, "_diag_enabled", False):
            try:
                orig_alpha = rgba.getchannel("A").copy()
                b0_metrics = self._compute_alpha_metrics(orig_alpha)
                self._append_diag_record({
                    "source": None, "stage": "B0_orig_alpha", "metrics": b0_metrics
                })
            except Exception:
                logger.exception("Diagnostics: failed B0 metrics")

        progress(20, "Flujo B: eliminando borde exterior")
        alpha = self._strip_existing_border(rgba, classify_result)

        # Record B1: after strip_existing_border
        if getattr(self, "_diag_enabled", False):
            try:
                b1_metrics = self._compute_alpha_metrics(alpha)
                diff_b1 = self._mask_diff_metrics(orig_alpha, alpha)
                self._append_diag_record({
                    "source": None, "stage": "B1_strip", "metrics": b1_metrics, "diff_vs_B0": diff_b1
                })
            except Exception:
                logger.exception("Diagnostics: failed B1 metrics")

        alpha = self._clean_alpha(alpha)

        # Record B2: after clean_alpha
        if getattr(self, "_diag_enabled", False):
            try:
                b2_metrics = self._compute_alpha_metrics(alpha)
                diff_b2 = self._mask_diff_metrics(orig_alpha, alpha)
                self._append_diag_record({
                    "source": None, "stage": "B2_clean", "metrics": b2_metrics, "diff_vs_B0": diff_b2
                })
            except Exception:
                logger.exception("Diagnostics: failed B2 metrics")

        progress(32, "Flujo B: reconstruyendo máscara")
        alpha = self._preserve_closed_interiors(alpha)

        # Record B3: after preserve_closed_interiors
        if getattr(self, "_diag_enabled", False):
            try:
                b3_metrics = self._compute_alpha_metrics(alpha)
                diff_b3 = self._mask_diff_metrics(orig_alpha, alpha)
                self._append_diag_record({
                    "source": None, "stage": "B3_preserve_closed", "metrics": b3_metrics, "diff_vs_B0": diff_b3
                })
            except Exception:
                logger.exception("Diagnostics: failed B3 metrics")

        # Trazo blanco interno para cubrir el gris residual —
        # se aplica ANTES de refinar el contorno negro para que quede
        # completamente tapado por el borde blanco de producción.
        if has_grey:
            progress(36, "Flujo B: aplicando trazo blanco sobre borde gris")
            alpha = self._apply_grey_border_cover(rgba, alpha)

        if classify_result.has_black_outline:
            progress(40, "Flujo B: refinando a contorno negro interno")
            alpha = self._extract_to_inner_contour(rgba, alpha)

        progress(44, "Flujo B: suavizando")
        alpha = self._clean_alpha(alpha)

        # Record B4: final alpha before putalpha
        if getattr(self, "_diag_enabled", False):
            try:
                b4_metrics = self._compute_alpha_metrics(alpha)
                diff_b4 = self._mask_diff_metrics(orig_alpha, alpha)
                self._append_diag_record({
                    "source": None, "stage": "B4_final", "metrics": b4_metrics, "diff_vs_B0": diff_b4
                })
                # Optionally save masks for high-loss cases
                try:
                    lost_pct = diff_b4.get("lost_pct", 0.0)
                    if self._diag_output_dir and lost_pct >= self._diag_save_threshold_pct:
                        # save images: original alpha, strip result (b1), final alpha
                        if hasattr(orig_alpha, "save"):
                            orig_path = self._diag_output_dir / f"{uuid.uuid4().hex}_B0_orig_alpha.png"
                            orig_alpha.save(orig_path)
                        if hasattr(alpha, "save"):
                            final_path = self._diag_output_dir / f"{uuid.uuid4().hex}_B4_final_alpha.png"
                            alpha.save(final_path)
                except Exception:
                    logger.exception("Diagnostics: failed saving high-loss masks")
            except Exception:
                logger.exception("Diagnostics: failed B4 metrics")

        result = rgba.copy()
        if has_grey:
            # El gris identificado como borde/sombra no forma parte del arte:
            # se vuelve blanco para que nunca reaparezca como halo en el PNG
            # final, aun si queda un píxel dentro de la máscara.
            try:
                import numpy as np
                from PIL import Image

                rgb = np.asarray(result.convert("RGB"), dtype=np.uint8)
                red, green, blue = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
                neutral = (
                    (np.abs(red.astype(int) - green.astype(int)) < 35)
                    & (np.abs(green.astype(int) - blue.astype(int)) < 35)
                    & (red > 90)
                    & (red < 215)
                )
                alpha_arr = np.asarray(alpha, dtype=np.uint8) > 127
                cover = Image.fromarray(
                    ((neutral & alpha_arr).astype(np.uint8) * 255), mode="L"
                )
                result.paste((255, 255, 255, 255), mask=cover)
            except (ImportError, ModuleNotFoundError):
                pass
        result.putalpha(alpha)
        return result

    def _apply_grey_border_cover(self, rgba, alpha):
        """Expande la máscara para asegurarse de que el borde gris residual
        quede cubierto por el trazo blanco que se construirá en process().

        Estrategia: dilatar la máscara un radio equivalente al grosor del
        borde gris detectado (aprox. inner_white_px / 2) para que cuando
        se aplique el borde blanco interior en process() tape cualquier
        resto gris que haya quedado adherido al diseño.
        """
        try:
            import cv2
            import numpy as np
            from PIL import Image

            arr = np.asarray(alpha.convert("L"), dtype=np.uint8)
            # Radio de expansión = la mitad del trazo interno configurado,
            # mínimo 4 px para que tape bordes grises típicos de ~2–3 px.
            r  = max(4, self.profile.inner_white_px // 2)
            k  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r*2+1, r*2+1))
            expanded = cv2.dilate(arr, k)
            # Solo expandir donde los píxeles son grises/neutros en la imagen
            rgb = np.asarray(rgba.convert("RGB"), dtype=np.uint8)
            rc, gc, bc = rgb[:,:,0], rgb[:,:,1], rgb[:,:,2]
            neutral = (np.abs(rc.astype(int) - gc.astype(int)) < 40) & \
                      (np.abs(gc.astype(int) - bc.astype(int)) < 40) & \
                      (rc > 80)
            # Zona nueva = expandida pero solo sobre píxeles neutros/grises
            zone_new  = (expanded > 127) & (arr <= 127)
            final     = arr.copy()
            # Donde la expansión cae sobre gris → incluir en máscara
            final[zone_new & neutral] = 255
            # Donde cae sobre blanco puro → también incluir (borde blanco)
            white_px = (rc >= 210) & (gc >= 210) & (bc >= 210)
            final[zone_new & white_px] = 255
            return Image.fromarray(final, mode="L")
        except (ImportError, ModuleNotFoundError):
            return alpha

    @staticmethod
    def _strip_existing_border(rgba, classify_result: "ClassifyResult"):
        """Elimina el borde exterior de un sticker ya terminado.

        Soporta dos variantes:
          - Borde blanco/casi blanco  (has_white_border)
          - Borde gris/sombra exterior (has_grey_border)

        Estrategia común: flood fill desde los bordes del canvas avanzando
        SOLO por píxeles que pertenecen al borde (blanco o gris según el
        caso) y por píxeles ya transparentes.  Los colores del diseño
        propiamente dicho nunca se tocan.
        """
        try:
            import cv2
            import numpy as np
            from PIL import Image

            rgb = np.asarray(rgba.convert("RGB"), dtype=np.uint8)
            a   = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
            h, w = rgb.shape[:2]
            r, g, b = rgb[:,:,0], rgb[:,:,1], rgb[:,:,2]
            transp = a < 128

            # Un sticker terminado puede venir montado sobre un fondo negro
            # (muy habitual en imágenes descargadas de catálogo). El antiguo
            # flujo solo recorría píxeles blancos/grises, por lo que nunca
            # llegaba a borrar ese exterior. Tomamos el color robusto del
            # perímetro y lo eliminamos únicamente si es oscuro; el borde
            # blanco continuo del sticker corta la conectividad hacia dentro.
            perimeter = np.concatenate((
                rgb[0, :], rgb[-1, :], rgb[1:-1, 0], rgb[1:-1, -1],
            )).astype(np.int16)
            perimeter_color = np.median(perimeter, axis=0)
            perimeter_luminance = (
                0.299 * perimeter_color[0]
                + 0.587 * perimeter_color[1]
                + 0.114 * perimeter_color[2]
            )
            if perimeter_luminance < 70:
                distance = np.sqrt(np.sum(
                    (rgb.astype(np.int16) - perimeter_color) ** 2, axis=2))
                rgb_max = rgb.max(axis=2).astype(np.int16)
                rgb_min = rgb.min(axis=2).astype(np.int16)
                # ``np.divide`` produce valores fraccionarios. El buffer de
                # salida anterior heredaba int16 de ``rgb_max`` y NumPy no
                # permite volcar float64 allí con casting ``same_kind``.
                # Convertir antes de multiplicar también evita overflow int16
                # (255 * 255) y conserva la precisión de la fórmula original.
                numerator = (rgb_max - rgb_min).astype(np.float64) * 255.0
                saturation = np.zeros_like(rgb_max, dtype=np.float64)
                np.divide(
                    numerator, rgb_max,
                    out=saturation, where=rgb_max != 0,
                )
                # Además del negro, eliminamos grises neutros conectados al
                # exterior: suelen ser el contorno residual o la compresión
                # de un JPEG. El blanco queda fuera del candidato para que el
                # borde blanco del sticker sea una barrera inequívoca.
                neutral_exterior = (saturation <= 45) & (rgb_max < 245)
                # JPEG deja píxeles grisáceos alrededor de un negro pleno.
                # La tolerancia cubre esa compresión sin atravesar el borde
                # blanco que encierra el sticker.
                candidate = ((distance <= 90) | neutral_exterior | transp).astype(np.uint8) * 255
            elif (perimeter_luminance < 245
                    and int(perimeter_color.max()) - int(perimeter_color.min()) <= 24):
                # Fondo gris o blanco roto con un borde blanco real. En vez
                # de intentar adivinar cada tono de la sombra, usamos el borde
                # blanco como una barrera: todo lo que esté conectado al
                # perímetro sin cruzarlo es exterior y puede transparentarse.
                white_barrier = (r >= 245) & (g >= 245) & (b >= 245)
                white_barrier = cv2.dilate(
                    white_barrier.astype(np.uint8),
                    cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
                    iterations=1,
                ).astype(bool)
                candidate = ((~white_barrier) | transp).astype(np.uint8) * 255
            else:
                candidate = None

            use_neutral_exterior_path = (
                classify_result.has_grey_border
                or classify_result.is_sticker_on_neutral_bg
            )
            if use_neutral_exterior_path:
                # Gris: los tres canales muy similares entre sí y en rango medio
                # More conservative: only mid-range grays (100-180), not light grays
                neutral = (np.abs(r.astype(int) - g.astype(int)) < 35) & \
                          (np.abs(g.astype(int) - b.astype(int)) < 35) & \
                          (np.abs(r.astype(int) - b.astype(int)) < 35)
                # Incluir también el blanco para un solo flood fill combinado
                border_px = neutral & (r > 100) & (r < 180) | \
                            ((r >= 210) & (g >= 210) & (b >= 210))
            else:
                # Solo blanco/casi blanco (tolerancia 30)
                lo = 255 - 30
                border_px = (r >= lo) & (g >= lo) & (b >= lo)

            if candidate is None:
                candidate = (border_px | transp).astype(np.uint8) * 255

            exterior = candidate.copy()
            fm = np.zeros((h + 2, w + 2), np.uint8)
            for x in range(w):
                if exterior[0, x]:     cv2.floodFill(exterior, fm, (x, 0),     128)
                if exterior[h-1, x]:   cv2.floodFill(exterior, fm, (x, h-1),   128)
            for y in range(1, h-1):
                if exterior[y, 0]:     cv2.floodFill(exterior, fm, (0, y),     128)
                if exterior[y, w-1]:   cv2.floodFill(exterior, fm, (w-1, y),   128)

            new_alpha = np.where(exterior == 128, np.uint8(0), np.uint8(255))
            new_alpha  = cv2.medianBlur(new_alpha, 3)
            return Image.fromarray(new_alpha, mode="L")

        except (ImportError, ModuleNotFoundError):
            # Fallback PIL: flood fill solo por blancos
            from PIL import Image, ImageDraw
            rgb_img = rgba.convert("RGB")
            w, h = rgb_img.size
            lo = 255 - 30
            mask = rgb_img.point(lambda v: 255 if v >= lo else 0).convert("L")
            for x in range(w):
                if mask.getpixel((x, 0)) == 255:
                    ImageDraw.floodfill(mask, (x, 0), 128, thresh=0)
                if mask.getpixel((x, h-1)) == 255:
                    ImageDraw.floodfill(mask, (x, h-1), 128, thresh=0)
            for y in range(h):
                if mask.getpixel((0, y)) == 255:
                    ImageDraw.floodfill(mask, (0, y), 128, thresh=0)
                if mask.getpixel((w-1, y)) == 255:
                    ImageDraw.floodfill(mask, (w-1, y), 128, thresh=0)
            return mask.point(lambda v: 0 if v == 128 else 255)

    @staticmethod
    def _strip_existing_white_border(rgba, tolerance: int = 30):
        """Alias de compatibilidad — delega a _strip_existing_border sin classify."""
        try:
            import cv2
            import numpy as np
            from PIL import Image

            rgb = np.asarray(rgba.convert("RGB"), dtype=np.uint8)
            a   = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
            h, w = rgb.shape[:2]
            lo = 255 - tolerance
            white  = (rgb[:,:,0]>=lo)&(rgb[:,:,1]>=lo)&(rgb[:,:,2]>=lo)
            transp = a < 128
            candidate = (white | transp).astype(np.uint8) * 255
            exterior = candidate.copy()
            fm = np.zeros((h+2, w+2), np.uint8)
            for x in range(w):
                if exterior[0,x]:   cv2.floodFill(exterior, fm, (x,0),   128)
                if exterior[h-1,x]: cv2.floodFill(exterior, fm, (x,h-1), 128)
            for y in range(1, h-1):
                if exterior[y,0]:   cv2.floodFill(exterior, fm, (0,y),   128)
                if exterior[y,w-1]: cv2.floodFill(exterior, fm, (w-1,y), 128)
            new_alpha = np.where(exterior==128, np.uint8(0), np.uint8(255))
            new_alpha = cv2.medianBlur(new_alpha, 3)
            return Image.fromarray(new_alpha, mode="L")
        except (ImportError, ModuleNotFoundError):
            from PIL import Image, ImageDraw
            rgb = rgba.convert("RGB")
            w, h = rgb.size
            lo = 255 - tolerance
            mask = rgb.point(lambda v: 255 if v >= lo else 0).convert("L")
            for x in range(w):
                if mask.getpixel((x,0)) == 255:
                    ImageDraw.floodfill(mask,(x,0),128,thresh=0)
                if mask.getpixel((x,h-1)) == 255:
                    ImageDraw.floodfill(mask,(x,h-1),128,thresh=0)
            for y in range(h):
                if mask.getpixel((0,y)) == 255:
                    ImageDraw.floodfill(mask,(0,y),128,thresh=0)
                if mask.getpixel((w-1,y)) == 255:
                    ImageDraw.floodfill(mask,(w-1,y),128,thresh=0)
            return mask.point(lambda v: 0 if v==128 else 255)

    def generate_diagnostics_summary(self, out_path: Path | None = None) -> dict:
        """Aggregate diagnostics.jsonl into a summary report.

        Returns a dictionary with aggregated counts and top-loss images.
        """
        import json
        from collections import defaultdict, Counter
        diag_file = self.workspace / "diagnostics.jsonl"
        summary = {
            "total_records": 0,
            "cases": Counter(),
            "opaque_gate_true": 0,
            "opaque_gate_false": 0,
            "transparency_bins": defaultdict(int),
            "case_b_losses": [],
            "db_locked_occurrences": 0,
            "db_locked_images": set(),
        }
        if not diag_file.exists():
            return summary
        records = []
        with open(diag_file, "r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                    records.append(rec)
                except Exception:
                    continue
        summary["total_records"] = len(records)

        # Parse classify records and mask diffs
        per_image = defaultdict(list)
        for r in records:
            src = r.get("source")
            per_image[src].append(r)
            if r.get("stage") == "classify":
                case = r.get("case")
                summary["cases"][case] += 1
                # look for alpha extrema
                am = r.get("alpha_extrema")
                if am:
                    if am == (255, 255):
                        summary["opaque_gate_true"] += 1
                    else:
                        summary["opaque_gate_false"] += 1
        # For each image, compute transparency distribution and losses for case B
        losses = []
        for src, recs in per_image.items():
            # find loaded alpha metrics
            loaded = next((x for x in recs if x.get("stage") == "loaded"), None)
            if loaded and loaded.get("alpha_metrics"):
                pct = loaded["alpha_metrics"].get("pct_transparent", 0.0)
                if pct < 0.1:
                    summary["transparency_bins"]["<0.1"] += 1
                elif pct < 1.0:
                    summary["transparency_bins"]["<1"] += 1
                elif pct <= 10.0:
                    summary["transparency_bins"]["1-10"] += 1
                else:
                    summary["transparency_bins"][">10"] += 1
            # case B losses
            # find final B4 diff
            b4 = next((x for x in recs if x.get("stage") == "B4_final"), None)
            if b4:
                diff = b4.get("diff_vs_B0") or {}
                lost_pct = diff.get("lost_pct", 0.0)
                if lost_pct > 0:
                    summary["case_b_losses"].append((src, lost_pct))
                    losses.append((src, lost_pct))
        # compute thresholds
        summary["case_b_loss_counts"] = {
            ">0.5": sum(1 for s, p in losses if p > 0.5),
            ">1": sum(1 for s, p in losses if p > 1.0),
            ">3": sum(1 for s, p in losses if p > 3.0),
            ">5": sum(1 for s, p in losses if p > 5.0),
        }
        # top 20
        top20 = sorted(losses, key=lambda x: x[1], reverse=True)[:20]
        summary["top20"] = top20

        # Scan workspace logs for 'database is locked'
        import glob
        db_locked = 0
        db_images = set()
        for path in glob.glob(str(self.workspace / "**"), recursive=True):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        if "database is locked" in line.lower():
                            db_locked += 1
                            # try to extract filename from same line
                            import re
                            m = re.search(r"(\w+\.(?:png|jpg|jpeg|webp))", line, re.IGNORECASE)
                            if m:
                                db_images.add(m.group(1))
            except Exception:
                continue
        summary["db_locked_occurrences"] = db_locked
        summary["db_locked_images"] = list(db_images)

        # Optionally write summary
        if out_path:
            try:
                with open(out_path, "w", encoding="utf-8") as fh:
                    json.dump(summary, fh, default=_json_default, indent=2)
            except Exception:
                logger.exception("Failed to write diagnostics summary")
        return summary

    # ──────────────────────────────────────────────────────────────────────────
    # FLUJO C — Fondo de color uniforme
    # ──────────────────────────────────────────────────────────────────────────

    def _flow_c(self, rgba, classify_result: ClassifyResult,
                progress: Callable) -> "Image":
        """Fondo de color uniforme.

        No segmentamos el sujeto a partir de umbrales de intensidad ni de la
        imagen RGB/gris. La máscara se obtiene desde el algoritmo de eliminación
        de fondo (SAM/GrabCut/RMBG/u otro modelo). Solo después de obtener esa
        máscara se aplican operaciones de limpieza binaria.

        Updated to handle PNG files with integrated backgrounds using:
        - Alpha channel check to detect integrated backgrounds
        - Flood fill from edges for background removal
        - Morphological closing instead of erosion
        """
        from PIL import Image, ImageFilter
        import threading
        import time

        logger.info("FLOW_C_START")
        start_time = time.time()

        progress(20, "Flujo C: verificando canal alfa")
        logger.info("FLOW_C_STEP_1_verifying_alpha")
        # Check if image has integrated background (all pixels alpha = 255)
        has_transparency, has_integrated_bg = self._has_real_transparency(rgba)
        logger.info(f"FLOW_C_STEP_1_complete has_transparency={has_transparency} has_integrated_bg={has_integrated_bg}")

        # Diagnostic logging
        alpha_ch = rgba.getchannel("A")
        alpha_min, alpha_max = alpha_ch.getextrema()
        logger.info(
            "FLOW_C_DECISION has_transparency=%s has_integrated_bg=%s alpha_extrema=%s",
            has_transparency,
            has_integrated_bg,
            (alpha_min, alpha_max),
        )

        alpha = None
        if has_integrated_bg:
            progress(22, "Flujo C: detectado fondo integrado, usando flood fill")
            logger.info("FLOW_C_STEP_2_flood_fill_start")
            # Use flood fill from edges for integrated backgrounds with timeout
            try:
                def run_flood_fill():
                    # JPG: se conserva la extracción conectada al fondo. La
                    # compresión puede volver neutras zonas claras del diseño;
                    # tratarlas como sombra partiría el sticker en dos.
                    corners = [
                        rgba.convert("RGB").getpixel((0, 0)),
                        rgba.convert("RGB").getpixel((rgba.width - 1, 0)),
                        rgba.convert("RGB").getpixel((0, rgba.height - 1)),
                        rgba.convert("RGB").getpixel((rgba.width - 1, rgba.height - 1)),
                    ]
                    bg_luminance = sum(
                        0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
                        for color in corners
                    ) / len(corners)
                    if bg_luminance >= 235:
                        # En producto sobre blanco, primero retiramos solo el
                        # blanco neutro que sigue conectado al exterior. Es
                        # más preciso que GrabCut para no incorporar lienzo
                        # blanco como parte del sticker; rosas y reflejos con
                        # color o textura quedan fuera del candidato.
                        alpha = self._uniform_background_alpha(rgba, tolerance=35)
                        if alpha.getbbox() is not None and alpha.getextrema() != (255, 255):
                            return alpha
                        # Si el fondo no ofrece una separación suficiente,
                        # conservar GrabCut como segunda propuesta local.
                        return self._segment_ia(rgba, progress)
                    return self._remove_integrated_background_flood_fill(
                        rgba, tolerance=35)

                flood_thread = threading.Thread(target=lambda: None, daemon=True)
                flood_result = [None]
                flood_error = [None]

                def flood_worker():
                    try:
                        logger.info("FLOW_C_FLOOD_WORKER_START")
                        flood_result[0] = run_flood_fill()
                        logger.info("FLOW_C_FLOOD_WORKER_COMPLETE")
                    except Exception as e:
                        logger.error(f"FLOW_C_FLOOD_WORKER_ERROR: {e}")
                        flood_error[0] = e

                flood_thread = threading.Thread(target=flood_worker, daemon=True)
                flood_thread.start()
                logger.info("FLOW_C_FLOOD_THREAD_STARTED")
                flood_thread.join(timeout=60)  # 60 second timeout
                logger.info("FLOW_C_FLOOD_THREAD_JOINED")

                if flood_thread.is_alive():
                    logger.error("FLOOD_FILL_TIMEOUT - usando fallback")
                    # Fallback: simple threshold
                    alpha = rgba.convert("L").point(lambda v: 255 if v > 200 else 0)
                elif flood_error[0]:
                    raise flood_error[0]
                else:
                    alpha = flood_result[0]

                # Log flood fill result immediately
                logger.info(
                    "FLOOD_FILL_RESULT mode=%s size=%s extrema=%s bbox=%s",
                    alpha.mode,
                    alpha.size,
                    alpha.getextrema(),
                    alpha.getbbox(),
                )

                # Validate that flood fill actually removed background pixels
                if alpha.getextrema() == (255, 255):
                    logger.warning("Flood fill no eliminó píxeles - usando fallback")
                    alpha = rgba.convert("L").point(lambda v: 255 if v > 200 else 0)
            except Exception as e:
                logger.error(f"FLOOD_FILL_ERROR: {e} - usando fallback")
                alpha = rgba.convert("L").point(lambda v: 255 if v > 200 else 0)
            logger.info("FLOW_C_STEP_2_flood_fill_complete")
        else:
            progress(20, "Flujo C: separando fondo uniforme")
            logger.info("FLOW_C_STEP_2_uniform_background_start")
            # Primero usar siempre un flood fill conectado al lienzo. Esto separa
            # también stickers con fondo oscuro sin cruzar su borde blanco.
            try:
                alpha = self._uniform_background_alpha(rgba, tolerance=42)
                logger.info("FLOW_C_UNIFORM_BACKGROUND_COMPLETE")
            except Exception as e:
                logger.error(f"UNIFORM_BACKGROUND_ERROR: {e} - usando fallback")
                alpha = rgba.convert("L").point(lambda v: 255 if v > 200 else 0)

            if alpha.getbbox() is None or alpha.getextrema() == (255, 255):
                logger.info("FLOW_C_UNIFORM_BACKGROUND_FAILED - trying light_neutral")
                # En gris claro la sombra puede estar más alejada del color de
                # fondo; aplicar la tolerancia asimétrica antes de segmentar.
                try:
                    alpha = self._light_neutral_exterior_alpha(rgba)
                    logger.info("FLOW_C_LIGHT_NEUTRAL_COMPLETE")
                except Exception as e:
                    logger.error(f"LIGHT_NEUTRAL_ERROR: {e} - usando fallback")
                    alpha = rgba.convert("L").point(lambda v: 255 if v > 200 else 0)

                if alpha.getbbox() is None or alpha.getextrema() == (255, 255):
                    progress(24, "Flujo C: segmentando con fondo uniforme")
                    logger.info("FLOW_C_LIGHT_NEUTRAL_FAILED - trying segment_ia")
                    try:
                        alpha = self._segment_ia(rgba, progress)
                        logger.info("FLOW_C_SEGMENT_IA_COMPLETE")
                    except Exception as e:
                        logger.error(f"SEGMENT_IA_ERROR: {e} - usando fallback")
                        alpha = rgba.convert("L").point(lambda v: 255 if v > 200 else 0)
            logger.info("FLOW_C_STEP_2_uniform_background_complete")

        progress(34, "Flujo C: limpiando máscara")
        logger.info("FLOW_C_STEP_3_clean_alpha_start")
        try:
            alpha = self._clean_alpha(alpha)
            logger.info("FLOW_C_STEP_3_clean_alpha_complete")
        except Exception as e:
            logger.error(f"CLEAN_ALPHA_ERROR: {e} - usando máscara sin limpiar")

        # Un hueco cerrado ya no comunica con el fondo exterior. En fondos
        # blancos, las zonas de acuarela, brillos metálicos y rosa muy pálido
        # pueden ser casi indistinguibles del lienzo y quedar transparentes
        # durante el flood-fill. Conservarlas evita que la base blanca final
        # borre su pigmento. Esto no crea burbujas: el fondo que llega al
        # troquel siempre está conectado al exterior.
        try:
            alpha = self._preserve_closed_interiors(alpha)
            logger.info("FLOW_C_CLOSED_INTERIORS_PRESERVED")
        except Exception as e:
            logger.debug("FLOW_C_CLOSED_INTERIORS_SKIPPED: %s", e)

        # CORRECCIÓN 4: NO aplicar cierre morfológico (redondea puntas y cierra concavidades)
        # progress(40, "Flujo C: aplicando cierre morfológico (sin erosión)")
        # alpha = self._apply_morphological_closing(alpha, kernel_size=3, iterations=1)

        progress(48, "Flujo C: suavizando máscara final")
        logger.info("FLOW_C_STEP_4_final_clean_start")
        try:
            alpha = self._clean_alpha(alpha)
            logger.info("FLOW_C_STEP_4_final_clean_complete")
        except Exception as e:
            logger.error(f"FINAL_CLEAN_ERROR: {e} - usando máscara anterior")

        logger.info("FLOW_C_STEP_5_creating_result")
        result = rgba.copy()
        result.putalpha(alpha)

        elapsed = time.time() - start_time
        logger.info(f"FLOW_C_COMPLETE elapsed={elapsed:.2f}s")
        return result

    @staticmethod
    def _sample_perimeter_background_colors(rgb_pixels, w, h, tolerance):
        corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
        samples = [rgb_pixels[x, y] for x, y in corners]

        step_x = max(1, w // 8)
        step_y = max(1, h // 8)

        def similar_to_base(color, base_color):
            return max(abs(color[i] - base_color[i]) for i in range(3)) <= tolerance * 2

        base_color = tuple(
            int(sorted([c[i] for c in samples])[len(samples) // 2])
            for i in range(3)
        )

        for x in range(0, w, step_x):
            for y in (0, h - 1):
                color = rgb_pixels[x, y]
                if similar_to_base(color, base_color):
                    samples.append(color)
        for y in range(step_y, h - step_y, step_y):
            for x in (0, w - 1):
                color = rgb_pixels[x, y]
                if similar_to_base(color, base_color):
                    samples.append(color)

        return [tuple(int(c) for c in color) for color in samples]

    @staticmethod
    def _restrict_to_edge_ring(mask, margin_px: int = 8):
        """Limita una máscara al conjunto de regiones conectadas al borde.

        La estrategia concreta aquí es conservar solo los componentes conectados
        al perímetro del canvas y descartar grandes regiones interiores que
        representen blanco real del diseño.  Esto evita el caso de fondo blanco
        con un personaje de colores claros, donde la máscara se expande por todo
        el centro del arte y termina borrando el dibujo.
        """
        import numpy as np

        arr = np.asarray(mask, dtype=np.uint8)
        if arr.ndim == 0:
            return arr.copy()
        h, w = arr.shape[:2]
        if h == 0 or w == 0:
            return arr.copy()

        mask_bool = arr > 0
        if not np.any(mask_bool):
            return np.zeros_like(arr, dtype=np.uint8)

        ring_px = max(1, int(margin_px))
        border = np.zeros_like(mask_bool, dtype=bool)
        border[:ring_px, :] = True
        border[-ring_px:, :] = True
        border[:, :ring_px] = True
        border[:, -ring_px:] = True

        # Un bloque blanco grande y central normalmente es parte del diseño, no
        # del fondo.  Si es pequeño, casi siempre es ruido o un artefacto
        # desconectado del borde y debe descartarse.
        if h > ring_px * 2 and w > ring_px * 2:
            central = mask_bool[ring_px:h - ring_px, ring_px:w - ring_px]
            central_ratio = (
                np.count_nonzero(central) / central.size
                if central.size
                else 0.0
            )
            if central_ratio >= 0.20:
                return arr.copy()

        # Fallback conservador: devolver solo el anillo de borde del candidato.
        edge_ring = np.zeros_like(arr, dtype=np.uint8)
        edge_ring[border & mask_bool] = 255
        return edge_ring

    @staticmethod
    def _grow_perimeter_background_alpha(image, tolerance: int):
        from PIL import Image
        from collections import deque

        rgb_img = image.convert("RGB")
        w, h = rgb_img.size
        pixels = rgb_img.load()
        background_colors = StickerProcessor._sample_perimeter_background_colors(
            pixels, w, h, tolerance)
        if not background_colors:
            background_colors = [pixels[x, y] for x, y in (
                (0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)
            )]

        def is_background(color):
            return any(
                max(abs(color[i] - bc[i]) for i in range(3)) <= tolerance
                for bc in background_colors
            )

        visited = [[False] * w for _ in range(h)]
        queue = deque()

        for x in range(w):
            for y in (0, h - 1):
                if is_background(pixels[x, y]):
                    visited[y][x] = True
                    queue.append((x, y))
        for y in range(1, h - 1):
            for x in (0, w - 1):
                if is_background(pixels[x, y]):
                    visited[y][x] = True
                    queue.append((x, y))

        neighbors = ((1, 0), (-1, 0), (0, 1), (0, -1),
                     (1, 1), (1, -1), (-1, 1), (-1, -1))
        while queue:
            x, y = queue.popleft()
            for dx, dy in neighbors:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and not visited[ny][nx]:
                    if is_background(pixels[nx, ny]):
                        visited[ny][nx] = True
                        queue.append((nx, ny))

        alpha = Image.new("L", (w, h), 255)
        alpha_pixels = alpha.load()
        for y in range(h):
            for x in range(w):
                if visited[y][x]:
                    alpha_pixels[x, y] = 0
        return alpha

    @staticmethod
    def _exterior_background_mask(image, tolerance: int):
        """Devuelve la máscara de fondo exterior conectada al borde del canvas."""
        from PIL import Image
        from collections import deque

        rgb_img = image.convert("RGB")
        w, h = rgb_img.size
        pixels = rgb_img.load()
        background_colors = StickerProcessor._sample_perimeter_background_colors(
            pixels, w, h, tolerance)

        def is_background(color, alpha=255):
            if alpha == 0:
                return True
            return any(
                max(abs(color[i] - bc[i]) for i in range(3)) <= tolerance
                for bc in background_colors
            )

        visited = [[False] * w for _ in range(h)]
        queue = deque()

        for x in range(w):
            for y in (0, h - 1):
                alpha = image.getchannel("A").getpixel((x, y))
                if is_background(pixels[x, y], alpha):
                    visited[y][x] = True
                    queue.append((x, y))
        for y in range(1, h - 1):
            for x in (0, w - 1):
                alpha = image.getchannel("A").getpixel((x, y))
                if is_background(pixels[x, y], alpha):
                    visited[y][x] = True
                    queue.append((x, y))

        neighbors = ((1, 0), (-1, 0), (0, 1), (0, -1),
                     (1, 1), (1, -1), (-1, 1), (-1, -1))
        while queue:
            x, y = queue.popleft()
            for dx, dy in neighbors:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and not visited[ny][nx]:
                    alpha = image.getchannel("A").getpixel((nx, ny))
                    if is_background(pixels[nx, ny], alpha):
                        visited[ny][nx] = True
                        queue.append((nx, ny))

        alpha = Image.new("L", (w, h), 0)
        alpha_pixels = alpha.load()
        for y in range(h):
            for x in range(w):
                if visited[y][x]:
                    alpha_pixels[x, y] = 255
        return alpha

    @staticmethod
    def _white_background_alpha(image, white_tolerance: int = 30):
        """Elimina el fondo a partir del borde exterior, con tolerancia a blancos."""
        try:
            import numpy as np
            from PIL import Image

            rgb_img = image.convert("RGB")
            rgb = np.asarray(rgb_img, dtype=np.uint8)
            h, w = rgb.shape[:2]
            pixels = rgb_img.load()
            background_colors = StickerProcessor._sample_perimeter_background_colors(
                pixels, w, h, white_tolerance)
            if not background_colors:
                background_colors = [pixels[x, y] for x, y in (
                    (0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)
                )]

            bg_arr = np.array(background_colors, dtype=np.int16)

            def is_bg(pixel):
                pixel = np.asarray(pixel, dtype=np.int16)
                diffs = np.abs(bg_arr - pixel)
                return int(diffs.max(axis=1).min()) <= white_tolerance

            visited = np.zeros((h, w), dtype=bool)
            from collections import deque
            queue = deque()

            for x in range(w):
                if is_bg(tuple(rgb[0, x])):
                    visited[0, x] = True
                    queue.append((x, 0))
                if is_bg(tuple(rgb[h - 1, x])):
                    visited[h - 1, x] = True
                    queue.append((x, h - 1))
            for y in range(1, h - 1):
                if is_bg(tuple(rgb[y, 0])):
                    visited[y, 0] = True
                    queue.append((0, y))
                if is_bg(tuple(rgb[y, w - 1])):
                    visited[y, w - 1] = True
                    queue.append((w - 1, y))

            neighbors = ((1, 0), (-1, 0), (0, 1), (0, -1),
                         (1, 1), (1, -1), (-1, 1), (-1, -1))
            while queue:
                x, y = queue.popleft()
                for dx, dy in neighbors:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx]:
                        if is_bg(tuple(rgb[ny, nx])):
                            visited[ny, nx] = True
                            queue.append((nx, ny))

            alpha = np.where(visited, np.uint8(0), np.uint8(255))
            return Image.fromarray(alpha, mode="L")
        except (ImportError, ModuleNotFoundError):
            return StickerProcessor._grow_perimeter_background_alpha(
                image, white_tolerance)

    @staticmethod
    def _uniform_background_alpha(image, tolerance=42):
        """Ruta principal: delega en la version vectorizada con fallback a legacy.

        La version vectorizada reemplaza el BFS Python por operaciones
        vectorizadas NumPy + connectedComponents.  Si falla por errores
        esperados (ImportError, ModuleNotFoundError, cv2.error, MemoryError)
        se registra el evento y se ejecuta el algoritmo legacy BFS.
        """
        try:
            import cv2
        except (ImportError, ModuleNotFoundError):
            logger.exception(
                "OpenCV no disponible, fallback a legacy BFS para %s",
                getattr(image, 'filename', '?'))
            return StickerProcessor._uniform_background_alpha_legacy(
                image, tolerance)

        try:
            return StickerProcessor._uniform_background_alpha_vectorized(
                image, tolerance)
        except (cv2.error, MemoryError):
            logger.exception(
                "Error en ruta vectorizada, fallback a legacy BFS para %s",
                getattr(image, 'filename', '?'))
            return StickerProcessor._uniform_background_alpha_legacy(
                image, tolerance)

    @staticmethod
    def _uniform_background_alpha_legacy(image, tolerance: int):
        """Elimina el fondo conectado a los bordes del canvas, incluyendo bordes blancos externos.

        Estrategia mejorada para evitar borde doble:
        1. Estimación del color de fondo desde las esquinas y perímetro.
        2. Flood fill que elimina TODO el fondo conectado a los bordes del canvas,
           incluyendo bordes blancos que forman parte del fondo exterior.
        3. Conserva el borde blanco original que es parte del diseño interior.
        4. Usa detección de gradientes/bordes para distinguir entre:
           - Fondo blanco uniforme (eliminar)
           - Borde blanco del diseño (conservar)
        """
        try:
            import numpy as np
            from PIL import Image

            rgb_img = image.convert("RGB")
            rgb = np.asarray(rgb_img, dtype=np.uint8)
            h, w = rgb.shape[:2]
            pixels = rgb_img.load()
            background_colors = StickerProcessor._sample_perimeter_background_colors(
                pixels, w, h, tolerance)
            if not background_colors:
                background_colors = [pixels[x, y] for x, y in (
                    (0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)
                )]

            # Estimamos el fondo predominante del marco exterior
            bg_arr = np.array(background_colors, dtype=np.int16)
            bg_mean = tuple(int(bg_arr.mean(axis=0)[i]) for i in range(3))

            # Detectar si el fondo es blanco o claro (luminosidad promedio >= 200)
            bg_luminosity = 0.299 * bg_mean[0] + 0.587 * bg_mean[1] + 0.114 * bg_mean[2]
            bg_is_white_or_light = bg_luminosity >= 200

            # Calcular luminosidad y saturación para cada píxel
            r, g, b = rgb[:,:,0], rgb[:,:,1], rgb[:,:,2]
            luminosity = (0.299 * r + 0.587 * g + 0.114 * b).astype(np.float32)

            # Saturación HSV simplificada
            rgb_max = rgb.max(axis=2).astype(np.float32)
            rgb_min = rgb.min(axis=2).astype(np.float32)
            saturation = np.zeros_like(luminosity)
            nonzero = rgb_max > 0
            saturation[nonzero] = ((rgb_max[nonzero] - rgb_min[nonzero]) / rgb_max[nonzero]) * 255.0

            # Calcular mapa de gradientes (detección de bordes visuales)
            # Esto nos permite detectar la transición fondo → diseño
            gray = luminosity
            h_img, w_img = gray.shape
            gx = np.zeros_like(gray)
            gy = np.zeros_like(gray)

            # Gradiente horizontal
            if w_img > 1:
                gx[:, 1:] = np.abs(gray[:, 1:] - gray[:, :-1])

            # Gradiente vertical
            if h_img > 1:
                gy[1:, :] = np.abs(gray[1:, :] - gray[:-1, :])

            edge_map = np.maximum(gx, gy)
            max_edge = edge_map.max() if edge_map.size > 0 else 1.0
            edge_threshold = max(12.0, max_edge * 0.40)

            visited = np.zeros((h, w), dtype=bool)
            from collections import deque
            queue = deque()

            def color_distance(pixel, bg):
                """Distancia euclidiana en RGB (Delta E simplificado)."""
                return float(np.sqrt(np.sum((np.asarray(pixel, dtype=np.float32) -
                                             np.asarray(bg, dtype=np.float32))**2)))

            def is_bg_similar(pixel, lum, sat, nx, ny):
                """Determina si un píxel pertenece al fondo exterior.

                ESTRATEGIA CON DETECCIÓN DE BORDES:
                - Para fondos blancos: usa gradientes para detectar transición al diseño
                - Para fondos oscuros: detiene al encontrar píxeles blancos
                """
                # Similitud de color con el fondo
                dist = color_distance(pixel, bg_mean)

                # Si el fondo es blanco o claro
                if bg_is_white_or_light:
                    # Para fondos blancos: verificar gradientes
                    if lum >= 200 and sat <= 50:
                        # Es blanco o casi blanco
                        # Verificar si estamos en un borde visual (transición)
                        gradient = edge_map[ny, nx]

                        # Alto gradiente = borde visual = transición fondo → diseño
                        if gradient > edge_threshold:
                            return False  # Detener: estamos en el borde del diseño

                        # Bajo gradiente + similar al fondo = parte del fondo uniforme
                        return dist <= tolerance * 2.0
                    else:
                        # No es blanco, verificar similitud directa
                        return dist <= tolerance * 1.5
                else:
                    # Para fondos oscuros: detenerse al encontrar blancos
                    # porque el blanco NO es parte del fondo oscuro
                    if lum >= 225 and sat <= 45:
                        return False  # Detener: blanco del diseño sobre fondo oscuro

                    # Similitud de color con el fondo oscuro
                    return dist <= tolerance * 1.5

            # Sembrar desde los bordes del canvas
            for x in range(w):
                pix = tuple(rgb[0, x])
                lum, sat = luminosity[0, x], saturation[0, x]
                if is_bg_similar(pix, lum, sat, x, 0):
                    visited[0, x] = True
                    queue.append((x, 0))

                pix = tuple(rgb[h - 1, x])
                lum, sat = luminosity[h-1, x], saturation[h-1, x]
                if is_bg_similar(pix, lum, sat, x, h - 1):
                    visited[h - 1, x] = True
                    queue.append((x, h - 1))

            for y in range(1, h - 1):
                pix = tuple(rgb[y, 0])
                lum, sat = luminosity[y, 0], saturation[y, 0]
                if is_bg_similar(pix, lum, sat, 0, y):
                    visited[y, 0] = True
                    queue.append((0, y))

                pix = tuple(rgb[y, w - 1])
                lum, sat = luminosity[y, w-1], saturation[y, w-1]
                if is_bg_similar(pix, lum, sat, w - 1, y):
                    visited[y, w - 1] = True
                    queue.append((w - 1, y))

            # Flood fill con detección de bordes
            neighbors = ((1, 0), (-1, 0), (0, 1), (0, -1),
                         (1, 1), (1, -1), (-1, 1), (-1, -1))
            while queue:
                x, y = queue.popleft()
                for dx, dy in neighbors:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx]:
                        pixel = tuple(rgb[ny, nx])
                        lum = luminosity[ny, nx]
                        sat = saturation[ny, nx]

                        if is_bg_similar(pixel, lum, sat, nx, ny):
                            visited[ny, nx] = True
                            queue.append((nx, ny))

            # La máscara es la inversa: lo no visitado es el sticker
            alpha = np.where(visited, np.uint8(0), np.uint8(255))
            return Image.fromarray(alpha, mode="L")
        except (ImportError, ModuleNotFoundError):
            return StickerProcessor._grow_perimeter_background_alpha(image, tolerance)

    @staticmethod
    def _uniform_background_alpha_vectorized(image, tolerance=42):
        """Version vectorizada de _uniform_background_alpha.

        Reemplaza el BFS Python (>800k iteraciones) por:
          1. Calculos vectorizados de distancia, luminosidad, saturacion, gradiente.
          2. connectedComponents() sobre la mascara candidata.
          3. Seleccion de labels conectados a los bordes del canvas.

        Retorna Image "L" (alpha), mismo contrato que la version original.
        """
        import numpy as np

        rgb_img = image.convert("RGB")
        rgb = np.asarray(rgb_img, dtype=np.uint8)
        h, w = rgb.shape[:2]
        pixels = rgb_img.load()

        background_colors = StickerProcessor._sample_perimeter_background_colors(
            pixels, w, h, tolerance)
        if not background_colors:
            background_colors = [pixels[x, y] for x, y in (
                (0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]

        bg_arr = np.array(background_colors, dtype=np.int16)
        bg_mean_f32 = bg_arr.mean(axis=0).astype(np.float32)

        bg_luminosity = float(
            0.299 * bg_mean_f32[0]
            + 0.587 * bg_mean_f32[1]
            + 0.114 * bg_mean_f32[2])
        bg_is_white_or_light = bg_luminosity >= 200.0

        r = rgb[:, :, 0].astype(np.float32)
        g = rgb[:, :, 1].astype(np.float32)
        b = rgb[:, :, 2].astype(np.float32)
        luminosity = 0.299 * r + 0.587 * g + 0.114 * b

        rgb_max = np.maximum(np.maximum(r, g), b)
        rgb_min = np.minimum(np.minimum(r, g), b)
        saturation = np.zeros_like(luminosity)
        nonzero = rgb_max > 0.0
        saturation[nonzero] = (
            (rgb_max[nonzero] - rgb_min[nonzero])
            / rgb_max[nonzero]
            * 255.0
        )

        gray = luminosity
        gx = np.zeros_like(gray)
        gy = np.zeros_like(gray)
        if w > 1:
            gx[:, 1:] = np.abs(gray[:, 1:] - gray[:, :-1])
        if h > 1:
            gy[1:, :] = np.abs(gray[1:, :] - gray[:-1, :])
        edge_map = np.maximum(gx, gy)
        max_edge = float(edge_map.max()) if edge_map.size > 0 else 1.0
        edge_threshold = max(12.0, max_edge * 0.40)

        rgb_f32 = np.stack([r, g, b], axis=2)
        bg_3d = bg_mean_f32[np.newaxis, np.newaxis, :]
        dist = np.sqrt(np.sum((rgb_f32 - bg_3d) ** 2, axis=2))

        if bg_is_white_or_light:
            # Sobre blanco, el criterio de distancia RGB por sí solo borra
            # acuarelas, reflejos plateados y rosas muy claros. El fondo debe
            # ser casi neutro, casi blanco y de bajo contraste local. Así los
            # detalles claros que tienen color o textura siguen siendo arte.
            white_like = (luminosity >= 238.0) & (saturation <= 14.0)
            low_contrast = edge_map <= max(10.0, edge_threshold * 0.45)
            candidate = white_like & low_contrast & (dist <= tolerance * 1.5)
        else:
            bright = (luminosity >= 225.0) & (saturation <= 45.0)
            candidate = (~bright) & (dist <= tolerance * 1.5)

        import cv2
        candidate_u8 = candidate.astype(np.uint8) * 255
        n_labels, labels = cv2.connectedComponents(candidate_u8, connectivity=8)

        border_px = np.concatenate([
            labels[0, :], labels[-1, :],
            labels[:, 0], labels[:, -1],
        ])
        border_labels = np.unique(border_px)
        border_labels = border_labels[border_labels != 0]

        exterior = np.isin(labels, border_labels)
        alpha = np.where(exterior, np.uint8(0), np.uint8(255)).astype(np.uint8)
        from PIL import Image
        return Image.fromarray(alpha, mode="L")

    @staticmethod
    def _checkerboard_exterior_alpha(image):
        """Recorta un damero incrustado a partir de sus dos tonos del borde.

        Las capturas de pantalla a veces contienen el tablero de transparencia
        como RGB opaco. No debe confundirse con una ilustración plateada: solo
        se consideran fondo los dos grises neutros repetidos en el perímetro.
        Devuelve ``None`` cuando el marco no presenta ese patrón.
        """
        try:
            import cv2
            import numpy as np
            from PIL import Image

            rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
            h, w = rgb.shape[:2]
            if min(w, h) < 24:
                return None
            perimeter = np.concatenate((
                rgb[0, :], rgb[-1, :], rgb[1:-1, 0], rgb[1:-1, -1],
            ))
            neutral = (np.ptp(perimeter, axis=1) <= 8)
            values = perimeter[neutral, 0]
            if values.size < max(20, (w + h) // 3):
                return None

            # Cuantizar neutraliza el antialiasing/JPEG de las celdas.
            # El antialiasing crea una franja intermedia entre ambas celdas,
            # por eso se detectan dos bandas y no solo dos valores exactos.
            low_band = (values >= 190) & (values <= 215)
            high_band = (values >= 225) & (values <= 250)
            if (int(low_band.sum()) < values.size * 0.12
                    or int(high_band.sum()) < values.size * 0.12):
                return None

            channel = rgb[:, :, 0].astype(np.int16)
            pixels_neutral = np.ptp(rgb.astype(np.int16), axis=2) <= 10
            # Incluye la franja de transición (~220) para que las celdas sean
            # una única región conectada, pero deja el borde blanco puro (255)
            # como barrera frente a la ilustración.
            candidate = pixels_neutral & (channel >= 190) & (channel <= 250)
            n_labels, labels = cv2.connectedComponents(
                candidate.astype(np.uint8), connectivity=8)
            if n_labels <= 1:
                return None
            border_labels = np.unique(np.concatenate((
                labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1],
            )))
            border_labels = border_labels[border_labels != 0]
            if border_labels.size == 0:
                return None
            exterior = np.isin(labels, border_labels)
            return Image.fromarray(
                np.where(exterior, 0, 255).astype(np.uint8), mode="L")
        except (ImportError, ModuleNotFoundError):
            return None

    @staticmethod
    def _refine_checkerboard_alpha(image, exterior_alpha):
        """Refina una máscara de damero con GrabCut inicializado por fondo.

        ``exterior_alpha`` aporta píxeles seguros de fondo. El resto empieza
        como primer plano probable, permitiendo a GrabCut quitar el borde
        antialiasado del tablero sin borrar metal, acuarela o blanco del arte.
        """
        try:
            import cv2
            import numpy as np
            from PIL import Image

            rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
            seed = np.asarray(exterior_alpha.convert("L"), dtype=np.uint8)
            mask = np.full(seed.shape, cv2.GC_PR_FGD, dtype=np.uint8)
            mask[seed == 0] = cv2.GC_BGD
            bg_model = np.zeros((1, 65), dtype=np.float64)
            fg_model = np.zeros((1, 65), dtype=np.float64)
            cv2.setRNGSeed(0)
            cv2.grabCut(
                cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), mask, None,
                bg_model, fg_model, 4, cv2.GC_INIT_WITH_MASK,
            )
            foreground = (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)
            return Image.fromarray(foreground.astype(np.uint8) * 255, mode="L")
        except Exception:
            return exterior_alpha

    @staticmethod
    def _colorful_foreground_alpha(image):
        """Máscara de un objeto cromático sobre un fondo neutro incrustado."""
        try:
            import cv2
            import numpy as np
            from PIL import Image

            rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
            hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
            colored = ((hsv[:, :, 1] > 38) & (hsv[:, :, 2] > 45)).astype(np.uint8)
            count, labels, stats, _ = cv2.connectedComponentsWithStats(colored, 8)
            if count <= 1:
                return None
            label = int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) + 1
            area = int(stats[label, cv2.CC_STAT_AREA])
            if area < rgb.shape[0] * rgb.shape[1] * 0.08:
                return None
            mask = (labels == label).astype(np.uint8) * 255
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                           cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                return None
            solid = np.zeros_like(mask)
            cv2.drawContours(solid, contours, -1, 255, thickness=cv2.FILLED)
            return Image.fromarray(solid, mode="L")
        except Exception:
            return None

    @staticmethod
    def _compare_background_alpha_methods(image, tolerance=42):
        """Compara _uniform_background_alpha_legacy (BFS) vs version vectorizada.

        Retorna un dict con metricas de tiempo, diferencias de alpha y
        alteracion de transparencia original.
        """
        import time
        import numpy as np

        t0 = time.perf_counter()
        old = StickerProcessor._uniform_background_alpha_legacy(image, tolerance)
        t_old = time.perf_counter() - t0

        t0 = time.perf_counter()
        new = StickerProcessor._uniform_background_alpha_vectorized(
            image, tolerance)
        t_new = time.perf_counter() - t0

        oa = np.asarray(old, dtype=np.uint8)
        na = np.asarray(new, dtype=np.uint8)
        diff = oa != na

        rgba = image.convert("RGBA")
        orig_a = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
        orig_transparent = orig_a < 128
        altered = orig_transparent & (na > 0)
        revealed = orig_transparent & (oa == 0) & (na > 0)
        destroyed = (~orig_transparent) & (oa > 0) & (na == 0)

        removed_new = (diff & (oa > 0) & (na == 0))
        preserved_new = (diff & (oa == 0) & (na > 0))

        return {
            "time_old": t_old,
            "time_new": t_new,
            "speedup": t_old / max(t_new, 1e-9),
            "diff_pixels": int(diff.sum()),
            "diff_pct": float(diff.mean() * 100),
            "removed_by_new_only": int(removed_new.sum()),
            "conserved_by_new_only": int(preserved_new.sum()),
            "orig_transparency_altered": int(altered.sum()),
            "orig_transparency_revealed": int(revealed.sum()),
            "orig_transparency_destroyed": int(destroyed.sum()),
            "shape": list(image.size),
        }

    @staticmethod
    def _diagnose_components(result: "ProcessingResult") -> dict:
        """Cuenta componentes en cada etapa del pipeline a partir de artefactos.

        No modifica el algoritmo: solo lee los PNG intermedios que ya
        genera process().

        Retorna:
          componentes_art_original:        componentes en mask_segmentation_raw
          componentes_mascara_limpia:      componentes en mask_binary_intermediate
          componentes_base_final:          componentes en la base blanca (master)
        """
        import cv2
        import numpy as np
        from PIL import Image
        from pathlib import Path

        def _count(path_str):
            if not path_str or not Path(path_str).exists():
                return -1
            arr = np.asarray(
                Image.open(path_str).convert("L"), dtype=np.uint8)
            _, labels = cv2.connectedComponents(
                (arr > 12).astype(np.uint8), connectivity=8)
            return int(labels.max())

        return {
            "componentes_art_original": _count(
                result.artifacts.get("mask_segmentation_raw", "")),
            "componentes_mascara_limpia": _count(
                result.artifacts.get("mask_intermediate", "")),
            "componentes_base_final": _count(
                result.artifacts.get("master", "")),
        }

    @staticmethod
    def _light_neutral_exterior_alpha(image, saturation_limit: int = 35,
                                      shadow_depth: int = 30,
                                      bright_stop: int = 6):
        """Quita fondo/sombra neutros conectados al borde de una imagen.

        El intervalo de luminosidad es deliberadamente asimétrico: atraviesa
        una sombra hasta ``shadow_depth`` más oscura que el fondo, pero no
        cruza una región claramente más blanca, que suele ser el borde real
        del sticker. Los grises interiores nunca se visitan si el borde blanco
        u otro color del diseño los separa del canvas.
        """
        from PIL import Image
        try:
            from collections import deque
            import numpy as np

            rgba = image.convert("RGBA")
            rgb = np.asarray(rgba.convert("RGB"), dtype=np.uint8)
            original_alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
            h, w = rgb.shape[:2]
            if not h or not w:
                return Image.new("L", (w, h), 0)

            # Valor y saturación HSV calculados en 8 bits; evitamos depender
            # de OpenCV para que esta limpieza esté disponible en todos los
            # entornos de ejecución. Para los neutros, V coincide con su L
            # perceptual a la precisión necesaria para este umbral.
            # Saturation numerator can reach 65025; int16 erases saturated art.
            value = rgb.max(axis=2).astype(np.int32)
            minimum = rgb.min(axis=2).astype(np.int32)
            saturation = np.zeros((h, w), dtype=np.uint8)
            nonblack = value > 0
            saturation[nonblack] = np.clip(
                ((value[nonblack] - minimum[nonblack]) * 255)
                // value[nonblack], 0, 255
            ).astype(np.uint8)
            frame = np.concatenate((value[0, :], value[-1, :],
                                    value[1:-1, 0], value[1:-1, -1]))
            background_l = int(np.median(frame))
            removable = (
                (original_alpha < 128)
                | ((saturation <= saturation_limit)
                   & (value >= background_l - shadow_depth)
                   & (value <= background_l + bright_stop))
            )

            visited = np.zeros((h, w), dtype=bool)
            queue = deque()

            def seed(x, y):
                if removable[y, x] and not visited[y, x]:
                    visited[y, x] = True
                    queue.append((x, y))

            for x in range(w):
                seed(x, 0)
                seed(x, h - 1)
            for y in range(1, h - 1):
                seed(0, y)
                seed(w - 1, y)

            while queue:
                x, y = queue.popleft()
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                               (1, 1), (1, -1), (-1, 1), (-1, -1)):
                    nx, ny = x + dx, y + dy
                    if (0 <= nx < w and 0 <= ny < h and not visited[ny, nx]
                            and removable[ny, nx]):
                        visited[ny, nx] = True
                        queue.append((nx, ny))

            return Image.fromarray(np.where(visited, 0, 255).astype(np.uint8),
                                   mode="L")
        except (ImportError, ModuleNotFoundError):
            return Image.new("L", image.size, 255)

    # ──────────────────────────────────────────────────────────────────────────
    # FLUJO D — Fotografía (segmentación IA)
    # ──────────────────────────────────────────────────────────────────────────

    def _flow_d(self, rgba, classify_result: ClassifyResult,
                progress: Callable) -> "Image":
        """Fotografía: segmentación por IA con eliminación de fantasmas y
        suavidad real solo en el borde exterior del sujeto.

        Cadena
        ──────
          segment_ia  →  _binarize_interior_ghosts  →  _clean_alpha_hard
          →  _preserve_closed_interiors  →  _clean_alpha_soft (borde)
        """
        from PIL import Image

        progress(18, "Flujo D: segmentando con IA")
        alpha = self._segment_ia(rgba, progress)

        # Eliminar fantasmas/semitransparencias internas;
        # solo el borde perimetral conserva transición suave.
        progress(50, "Flujo D: eliminando fantasmas internos")
        alpha = self._binarize_interior_ghosts(rgba, alpha)

        # Limpieza binaria dura: sin blur, sin residuos
        progress(56, "Flujo D: limpiando máscara")
        alpha = self._clean_alpha_hard(alpha)
        alpha = self._preserve_closed_interiors(alpha)

        # Solo al final, aplicar feather suave en la corona perimetral
        progress(64, "Flujo D: suavizando borde exterior")
        alpha = self._clean_alpha_soft(alpha,
                                       feather_px=self.profile.edge_feather_px)

        result = rgba.copy()
        result.putalpha(alpha)
        return result

    def _segment_ia(self, rgba, progress: Callable):
        """Segmentación IA con cascada de motores.

        El pipeline utiliza IA para obtener la máscara inicial del sujeto,
        y luego deja a OpenCV el trabajo geométrico posterior:
          - limpieza de la máscara
          - construcción de la base blanca
          - generación de bordes
          - preparación de impresión

        Se intenta primero un motor de eliminación de fondo como RMBG, y
        luego un fallback de GrabCut si no hay un motor IA disponible.
        """
        from PIL import Image

        # Priorizar el motor local: rembg puede descargar/inicializar modelos
        # grandes en una instalación nueva y dejar la cola parada varios
        # minutos. GrabCut no requiere red y es suficiente para generar una
        # propuesta que el usuario puede revisar o corregir.
        try:
            import cv2
            import numpy as np

            progress(20, "Segmentando con GrabCut local")
            image = cv2.cvtColor(np.asarray(rgba.convert("RGB")), cv2.COLOR_RGB2BGR)
            height, width = image.shape[:2]
            margin = max(2, min(10, width // 12, height // 12))
            mask = np.zeros((height, width), np.uint8)
            background_model = np.zeros((1, 65), np.float64)
            foreground_model = np.zeros((1, 65), np.float64)
            cv2.setRNGSeed(0)
            cv2.grabCut(
                image, mask, (margin, margin, width - margin * 2, height - margin * 2),
                background_model, foreground_model, 3, cv2.GC_INIT_WITH_RECT,
            )
            alpha = np.where((mask == 2) | (mask == 0), np.uint8(0), np.uint8(255))
            return Image.fromarray(alpha, mode="L")
        except Exception:
            # Se conserva la cascada histórica debajo para instalaciones sin
            # OpenCV o imágenes que GrabCut no pueda resolver.
            pass

        # ── Motor 1: rembg (Bria RMBG / rembg) ───────────────────────────
        try:
            from rembg import remove as rembg_remove
            import io
            progress(20, "Segmentando con RMBG")
            buf = io.BytesIO()
            rgba.save(buf, format="PNG")
            buf.seek(0)
            out = rembg_remove(buf.read())
            result = Image.open(io.BytesIO(out)).convert("RGBA")
            return result.getchannel("A").resize(rgba.size,
                                                  Image.Resampling.LANCZOS)
        except (ImportError, ModuleNotFoundError, Exception):
            pass

        # ── Motor 2: GrabCut OpenCV como fallback robusto ────────────────
        try:
            import cv2
            import numpy as np
            from PIL import Image

            progress(20, "Segmentando con GrabCut")
            img = cv2.cvtColor(np.asarray(rgba.convert("RGB")),
                               cv2.COLOR_RGB2BGR)
            h, w = img.shape[:2]
            mask = np.zeros((h, w), np.uint8)
            m = 10
            rect = (m, m, w - m * 2, h - m * 2)
            bgm = np.zeros((1, 65), np.float64)
            fgm = np.zeros((1, 65), np.float64)
            cv2.setRNGSeed(0)
            cv2.grabCut(img, mask, rect, bgm, fgm, 5,
                        cv2.GC_INIT_WITH_RECT)
            result = np.where((mask == 2) | (mask == 0),
                              np.uint8(0), np.uint8(255))
            return Image.fromarray(result, mode="L")
        except (ImportError, ModuleNotFoundError, Exception):
            pass

        # ── Fallback final: tratar como fondo uniforme solo si no hay otra opción
        progress(20, "Fallback de segmentación: fondo uniforme")
        return self._uniform_background_alpha(rgba, tolerance=46)

    def _binarize_interior_ghosts(self, rgba, alpha):
        """Elimina semitransparencias internas (fantasmas) sin tocar el borde real.

        Estrategia
        ──────────
        1. Construir la máscara binaria del sujeto (threshold = ghost_threshold).
        2. Erosionar esa máscara edge_feather_px píxeles → zona "interior puro".
        3. En el interior puro: cualquier píxel con alpha > 0 queda en 255
           (opaco completo); no puede haber semitransparencias allí.
        4. En la corona perimetral (entre la binaria y la erosionada):
           conservar el alpha original de la segmentación IA → transición suave.
        5. Fuera de la máscara binaria: alpha = 0 (transparente).

        El resultado es: interior sólido + borde exterior con feather natural.
        """
        try:
            import cv2
            import numpy as np
            from PIL import Image

            p   = self.profile
            thr = max(1, min(254, int(p.ghost_threshold)))
            fp  = max(0, int(p.edge_feather_px))

            a_orig = np.asarray(alpha.convert("L"), dtype=np.uint8)

            # ── 1. Máscara binaria del sujeto ─────────────────────────────
            _, binary = cv2.threshold(a_orig, thr, 255, cv2.THRESH_BINARY)

            # Limpiar partículas aisladas de la binaria
            binary = cv2.medianBlur(binary, 3)

            # ── 2. Interior puro (erosionado) ─────────────────────────────
            if fp > 0:
                k_fp   = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                                   (fp * 2 + 1, fp * 2 + 1))
                interior = cv2.erode(binary, k_fp)
            else:
                interior = binary.copy()

            # ── 3. Interior → opaco completo ──────────────────────────────
            result = a_orig.copy()
            result[interior > 127] = 255

            # ── 4. Corona perimetral → alpha original suavizado ───────────
            #   (no hacemos nada: result ya tiene a_orig en esa zona)

            # ── 5. Fuera de la binaria → transparente ─────────────────────
            result[binary == 0] = 0

            # Aplicar un suavizado muy leve solo en la corona para
            # quitar escalones duros sin introducir halos internos
            if fp > 0:
                corona = (binary > 127) & (interior == 0)
                blur   = cv2.GaussianBlur(result,
                                          (fp * 4 + 1, fp * 4 + 1),
                                          fp * 0.6)
                result[corona] = blur[corona]

            return Image.fromarray(result, mode="L")

        except (ImportError, ModuleNotFoundError):
            # Fallback PIL puro: binarización simple
            from PIL import ImageFilter
            thr = getattr(self.profile, "ghost_threshold", 128)
            return alpha.convert("L").point(lambda v: 255 if v > thr else 0)

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers de contorno (usados en flujos y postprocesado)
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_to_inner_contour(rgba, alpha):
        """Ajusta el alpha para que el corte quede en el borde negro."""
        try:
            import cv2
            import numpy as np
            from PIL import Image
            a = np.asarray(alpha.convert("L"), dtype=np.uint8)
            r = 4
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(r*2+1,r*2+1))
            transp = (a < 128).astype(np.uint8) * 255
            restored = cv2.erode(cv2.dilate(transp, k), k)
            new_a = np.where(restored>127, np.uint8(0), np.uint8(255))
            final = np.where((a>127)&(new_a>127), np.uint8(255), new_a)
            return Image.fromarray(final, mode="L")
        except (ImportError, ModuleNotFoundError):
            return alpha

    @staticmethod
    def _build_inner_white_stroke(base_mask, inner_stroke_px: int,
                                  content_rgba=None):
        """Construye el trazo blanco sin invadir la ilustración.

        Si se proporciona la capa del contenido, solo cubre los píxeles
        neutros del contorno gris. Los detalles coloreados quedan intactos.
        """
        from PIL import Image, ImageChops
        try:
            import cv2
            import numpy as np
            arr = np.asarray(base_mask.convert("L"), dtype=np.uint8)
            d = inner_stroke_px * 2 + 1
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d))
            contracted = Image.fromarray(cv2.erode(arr, k), mode="L")
        except (ImportError, ModuleNotFoundError):
            from PIL import ImageFilter
            contracted = base_mask.filter(
                ImageFilter.MinFilter(inner_stroke_px * 2 + 1))
        band = ImageChops.subtract(
            base_mask.point(lambda v: 255 if v > 127 else 0),
            contracted.point(lambda v: 255 if v > 127 else 0),
        )
        if content_rgba is not None:
            try:
                import numpy as np

                rgba = np.asarray(content_rgba.convert("RGBA"), dtype=np.uint8)
                rgb = rgba[:, :, :3].astype(np.int16)
                neutral = (
                    (np.max(rgb, axis=2) - np.min(rgb, axis=2) <= 18)
                    & (np.mean(rgb, axis=2) >= 145)
                    & (rgba[:, :, 3] > 12)
                )
                band_arr = np.asarray(band, dtype=np.uint8)
                band = Image.fromarray(
                    np.where(neutral, band_arr, 0).astype(np.uint8), mode="L")
            except (ImportError, ModuleNotFoundError):
                pass
        layer = Image.new("RGBA", base_mask.size, (255, 255, 255, 0))
        layer.putalpha(band)
        return layer

    @staticmethod
    def _analyze_white_border_structural(rgba, subject_mask):
        """Analiza un borde blanco externo usando tres condiciones combinadas.

        Combina:
        1. porcentaje_blanco_suficiente en el anillo del contorno externo
        2. grosor_estimado >= grosor_minimo
        3. continuidad_alrededor_del_objeto >= continuidad_minima

        Esta aproximación usa el contorno externo real del objeto para evitar
        confundir zonas blancas internas con un borde blanco externo.
        """
        try:
            import numpy as np

            rgb = np.asarray(rgba.convert("RGB"), dtype=np.uint8)
            mask_arr = np.asarray(subject_mask.convert("L"), dtype=np.uint8)
            subject = mask_arr > 127

            if not subject.any():
                return {
                    "has_border": False,
                    "white_percentage": 0.0,
                    "estimated_border_thickness_px": 0.0,
                    "continuity": 0.0,
                }

            is_white = (rgb[:, :, 0] >= 240) & (rgb[:, :, 1] >= 240) & (rgb[:, :, 2] >= 240)

            # Comprobación estructural del borde blanco externo. Se analiza una
            # banda delgada justo dentro del perímetro del objeto para detectar
            # que ese borde sea blanco y continuo, sin confundirlo con zonas
            # blancas internas.
            try:
                import cv2

                subject_bool = subject.astype(bool)
                subject_u8 = (subject_bool.astype(np.uint8) * 255)
                contours, _ = cv2.findContours(subject_u8, cv2.RETR_EXTERNAL,
                                              cv2.CHAIN_APPROX_SIMPLE)
                if not contours:
                    return {
                        "has_border": False,
                        "white_percentage": 0.0,
                        "estimated_border_thickness_px": 0.0,
                        "continuity": 0.0,
                    }

                contour_mask = np.zeros_like(subject_u8, dtype=np.uint8)
                cv2.drawContours(contour_mask, contours, -1, 255, thickness=1)

                best_result = None
                for width in (3, 5, 7, 9):
                    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                                      (width * 2 + 1, width * 2 + 1))
                    dilated_contour = cv2.dilate(contour_mask, kernel, iterations=1)
                    eroded_subject = cv2.erode(subject_u8, kernel, iterations=1)
                    band_mask = ((dilated_contour > 0) & subject_bool)
                    band_mask &= ~(eroded_subject > 0)
                    band_mask = band_mask.astype(bool)

                    if not band_mask.any():
                        continue

                    white_band = is_white & band_mask
                    white_percentage = float(white_band.sum() / max(1, band_mask.sum()))

                    contour_coords = np.argwhere(contour_mask > 0)
                    continuity = 0.0
                    if contour_coords.size:
                        supported = 0
                        for y, x in contour_coords:
                            local_patch = white_band[
                                max(0, y - 1):min(subject.shape[0], y + 2),
                                max(0, x - 1):min(subject.shape[1], x + 2),
                            ]
                            if local_patch.any():
                                supported += 1
                        continuity = float(supported / contour_coords.shape[0])

                    if white_percentage >= 0.55 and continuity >= 0.25:
                        candidate = {
                            "white_percentage": white_percentage,
                            "continuity": continuity,
                            "estimated_border_thickness_px": float(width),
                        }
                        if best_result is None or (
                            candidate["white_percentage"] > best_result["white_percentage"]
                            or (
                                abs(candidate["white_percentage"] - best_result["white_percentage"]) < 1e-9
                                and candidate["estimated_border_thickness_px"] > best_result["estimated_border_thickness_px"]
                            )
                        ):
                            best_result = candidate

                if best_result is None:
                    return {
                        "has_border": False,
                        "white_percentage": 0.0,
                        "estimated_border_thickness_px": 0.0,
                        "continuity": 0.0,
                    }

                return {
                    "has_border": True,
                    "white_percentage": best_result["white_percentage"],
                    "estimated_border_thickness_px": best_result["estimated_border_thickness_px"],
                    "continuity": best_result["continuity"],
                }
            except Exception:
                logger.exception("Error en análisis CV de borde blanco estructural")
                return {
                    "has_border": False,
                    "white_percentage": 0.0,
                    "estimated_border_thickness_px": 0.0,
                    "continuity": 0.0,
                }
        except Exception:
            logger.exception("Error analizando el borde blanco estructural")
            return {
                "has_border": False,
                "white_percentage": 0.0,
                "estimated_border_thickness_px": 0.0,
                "continuity": 0.0,
            }

    @staticmethod
    def analyze_original_border_structure(rgba):
        """Analiza la imagen RGBA original antes de cualquier flood fill.

        Determina si la imagen tiene un borde blanco exterior distinguible
        del fondo, o si fondo y borde son indistinguibles (ambiguo).

        Retorna un dict con:
          mode: BorderMode
          background_is_white: bool
          border_distinguishable: bool
          white_band_ratio: float
          bg_color: tuple(R, G, B)
        """
        import numpy as np

        alpha_ch = rgba.getchannel("A")
        has_transparency = alpha_ch.getextrema()[0] < 250
        if has_transparency:
            return {
                "mode": BorderMode.NO_BORDER_REQUIRED,
                "background_is_white": False,
                "border_distinguishable": False,
                "white_band_ratio": 0.0,
                "white_in_ring_ratio": 0.0,
                "bg_color": (0, 0, 0),
                "perimeter_median_rgb": (0, 0, 0),
                "perimeter_luminance": 0.0,
                "perimeter_saturation": 0.0,
                "background_distance_threshold": 35.0,
                "has_design": False,
                "selected_mode": BorderMode.NO_BORDER_REQUIRED,
                "mode_reason": "image has transparency",
            }

        # Este análisis decide el tratamiento del borde; no genera el PNG
        # final. Limitarlo evita recorrer millones de píxeles de fotos 4K sin
        # perder detalle útil para distinguir un anillo blanco.
        if max(rgba.size) > 1024:
            from PIL import Image
            rgba = rgba.copy()
            rgba.thumbnail((1024, 1024), Image.Resampling.LANCZOS)

        rgb = np.asarray(rgba.convert("RGB"), dtype=np.uint8)
        h, w = rgb.shape[:2]

        perimeter = np.concatenate([
            rgb[0, :], rgb[h - 1, :],
            rgb[1:h - 1, 0], rgb[1:h - 1, w - 1]
        ])
        bg_color = tuple(int(v) for v in np.median(perimeter, axis=0))

        bg_lum = (0.299 * bg_color[0]
                  + 0.587 * bg_color[1]
                  + 0.114 * bg_color[2])
        background_is_white = bg_lum >= 248

        pf = perimeter.astype(np.float32) / 255.0
        cmax = np.maximum(np.maximum(pf[:, 0], pf[:, 1]), pf[:, 2])
        cmin = np.minimum(np.minimum(pf[:, 0], pf[:, 1]), pf[:, 2])
        delta = cmax - cmin
        sat = np.divide(delta, cmax, out=np.zeros_like(delta), where=cmax != 0)
        perimeter_saturation = float(np.mean(sat))

        bg_dist_threshold = 35.0

        try:
            import cv2

            bg_arr = np.array(bg_color, dtype=np.int16)
            diffs = np.abs(rgb.astype(np.int16) - bg_arr)
            max_diff = diffs.max(axis=2)
            is_bg = max_diff < 35

            is_white = (
                (rgb[:, :, 0] >= 245)
                & (rgb[:, :, 1] >= 245)
                & (rgb[:, :, 2] >= 245)
            )

            design = (~is_bg) & (~is_white)
            has_design = float(design.sum()) > (h * w * 0.005)

            if not design.any():
                mode = (BorderMode.AMBIGUOUS_WHITE_ON_WHITE
                        if background_is_white
                        else BorderMode.GENERATE_WHITE_BORDER)
                return {
                    "mode": mode,
                    "background_is_white": background_is_white,
                    "border_distinguishable": False,
                    "white_band_ratio": 0.0,
                    "white_in_ring_ratio": 0.0,
                    "bg_color": bg_color,
                    "perimeter_median_rgb": bg_color,
                    "perimeter_luminance": bg_lum,
                    "perimeter_saturation": perimeter_saturation,
                    "background_distance_threshold": bg_dist_threshold,
                    "has_design": False,
                    "selected_mode": mode,
                    "mode_reason": "no design detected",
                }

            dilate_r = 15
            k = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (dilate_r * 2 + 1, dilate_r * 2 + 1))
            dilated = cv2.dilate(
                design.astype(np.uint8) * 255, k, iterations=1)
            ring = (dilated > 127) & (~design)

            if not ring.any():
                return {
                    "mode": BorderMode.GENERATE_WHITE_BORDER,
                    "background_is_white": background_is_white,
                    "border_distinguishable": False,
                    "white_band_ratio": 0.0,
                    "white_in_ring_ratio": 0.0,
                    "bg_color": bg_color,
                    "perimeter_median_rgb": bg_color,
                    "perimeter_luminance": bg_lum,
                    "perimeter_saturation": perimeter_saturation,
                    "background_distance_threshold": bg_dist_threshold,
                    "has_design": has_design,
                    "selected_mode": BorderMode.GENERATE_WHITE_BORDER,
                    "mode_reason": "no ring around design",
                }

            white_in_ring = float((is_white & ring).sum()
                                  / max(1, ring.sum()))

            border_distinguishable = (
                has_design
                and white_in_ring > 0.55
                and not background_is_white
            )

            if background_is_white and white_in_ring >= 0.55:
                mode = BorderMode.AMBIGUOUS_WHITE_ON_WHITE
                mode_reason = (
                    f"background is white and white ring is prominent"
                    f" (ratio={white_in_ring:.2f})")
            elif not background_is_white and white_in_ring >= 0.55:
                mode = BorderMode.PRESERVE_EXISTING_BORDER
                mode_reason = (
                    f"background is not white and white ring is prominent"
                    f" (ratio={white_in_ring:.2f})")
            else:
                mode = BorderMode.GENERATE_WHITE_BORDER
                if not has_design:
                    mode_reason = "no design detected"
                elif white_in_ring < 0.55:
                    mode_reason = (
                        f"white ring not prominent enough"
                        f" (ratio={white_in_ring:.2f})")
                else:
                    mode_reason = "no distinguishable white border"

            return {
                "mode": mode,
                "background_is_white": background_is_white,
                "border_distinguishable": border_distinguishable,
                "white_band_ratio": white_in_ring,
                "white_in_ring_ratio": white_in_ring,
                "bg_color": bg_color,
                "perimeter_median_rgb": bg_color,
                "perimeter_luminance": bg_lum,
                "perimeter_saturation": perimeter_saturation,
                "background_distance_threshold": bg_dist_threshold,
                "has_design": has_design,
                "selected_mode": mode,
                "mode_reason": mode_reason,
            }

        except Exception:
            logger.exception("Error en analyze_original_border_structure")
            mode = (BorderMode.AMBIGUOUS_WHITE_ON_WHITE
                    if background_is_white
                    else BorderMode.GENERATE_WHITE_BORDER)
            return {
                "mode": mode,
                "background_is_white": background_is_white,
                "border_distinguishable": False,
                "white_band_ratio": 0.0,
                "white_in_ring_ratio": 0.0,
                "bg_color": bg_color,
                "perimeter_median_rgb": bg_color,
                "perimeter_luminance": bg_lum if 'bg_lum' in dir() else 0.0,
                "perimeter_saturation": perimeter_saturation if 'perimeter_saturation' in dir() else 0.0,
                "background_distance_threshold": 35.0,
                "has_design": False,
                "selected_mode": mode,
                "mode_reason": "error in analysis",
            }

    @staticmethod
    def _detect_white_border_structural(rgba, subject_mask):
        """Detecta borde blanco por análisis estructural con tres condiciones."""
        return StickerProcessor._analyze_white_border_structural(rgba, subject_mask)["has_border"]

    @staticmethod
    def _has_white_outer_border(image, alpha, threshold: float = .55) -> bool:
        """Indica si la silueta expuesta ya trae un borde blanco continuo.

        Mejorado para detectar bordes blancos más sutiles:
        - Threshold más bajo (default 0.55, pero se usa 0.20 en llamada)
        - Analiza múltiples anchos de borde (3px, 5px, 8px)
        - Considera el mejor resultado entre los anchos probados
        """
        try:
            import numpy as np
            from PIL import ImageChops

            solid = alpha.convert("L").point(lambda value: 255 if value > 127 else 0)

            # Probar con diferentes anchos de borde para ser más robusto
            border_widths = [3, 5, 8]
            best_ratio = 0.0

            for width in border_widths:
                edge = np.asarray(
                    ImageChops.subtract(solid, StickerProcessor._contract(solid, width)),
                    dtype=np.uint8,
                ) > 0

                if not edge.any():
                    continue

                rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)

                # Píxeles blancos (R, G, B >= 225)
                white = (rgb[:, :, 0] >= 225) & (rgb[:, :, 1] >= 225) & (rgb[:, :, 2] >= 225)

                # Ratio de píxeles blancos en el borde
                white_in_edge = (white & edge).sum()
                total_edge = edge.sum()

                if total_edge > 0:
                    ratio = float(white_in_edge) / int(total_edge)
                    best_ratio = max(best_ratio, ratio)

            # Usar el mejor ratio encontrado
            has_border = best_ratio >= threshold

            return has_border

        except (ImportError, ModuleNotFoundError):
            return False

    @staticmethod
    def _white_outer_border_pixels(image, alpha) -> int:
        """Cuenta píxeles blancos presentes en la corona exterior."""
        try:
            import numpy as np
            from PIL import ImageChops
            solid = alpha.convert("L").point(lambda value: 255 if value > 127 else 0)
            edge = np.asarray(ImageChops.subtract(
                solid, StickerProcessor._contract(solid, 3)), dtype=np.uint8) > 0
            rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
            white = (rgb[:, :, 0] >= 225) & (rgb[:, :, 1] >= 225) & (rgb[:, :, 2] >= 225)
            return int((white & edge).sum())
        except (ImportError, ModuleNotFoundError):
            return 0

    @staticmethod
    def _whiten_neutral_outer_halo(image, alpha, width: int = 12):
        """Blanquea solo grises suaves dentro del margen blanco exterior.

        More conservative version to avoid removing white design elements.
        """
        try:
            import numpy as np
            from PIL import Image, ImageChops

            solid = alpha.convert("L").point(lambda value: 255 if value > 127 else 0)
            inner = StickerProcessor._contract(solid, width)
            outer_band = np.asarray(ImageChops.subtract(solid, inner), dtype=np.uint8) > 0
            rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
            rgb = rgba[:, :, :3].astype(np.int16)
            # El halo de recorte suele ser gris medio, no solo gris muy claro.
            # La intervención sigue siendo segura porque se limita a la corona
            # exterior de la máscara; los grises del interior del diseño no se
            # tocan.
            neutral = ((np.abs(rgb[:, :, 0] - rgb[:, :, 1]) <= 12)
                       & (np.abs(rgb[:, :, 1] - rgb[:, :, 2]) <= 12)
                       & (rgb[:, :, 0] >= 90) & (rgb[:, :, 0] <= 240))
            cover = outer_band & neutral
            rgba[cover, :3] = 255
            return Image.fromarray(rgba, mode="RGBA")
        except (ImportError, ModuleNotFoundError):
            return image.convert("RGBA")

    @staticmethod
    def _decontaminate_halo_dispatcher(image, alpha, case, classify_result, profile=None):
        """Compatibility shim: no route-specific rendering or second border."""
        from .grey_halo_decontamination import decontaminate_exterior
        result, clean, metadata, _, _ = decontaminate_exterior(
            image, alpha, existing_border=classify_result.has_white_border,
            suspected_halo=classify_result.has_grey_border)
        return result, clean, metadata

    @staticmethod
    def _remove_existing_white_border_for_replacement(image, alpha, max_depth_px=48):
        """Retira sólo blanco exterior conectado para construir un borde nuevo.

        Es una operación explícita del usuario, nunca una heurística automática.
        La búsqueda queda limitada por profundidad desde el contorno alfa. Si
        el resultado pierde demasiado contenido o queda vacío, no se aplica y
        se solicita corrección manual.
        """
        import cv2
        import numpy as np
        from PIL import Image
        from .halo_geometry import confirmed_white_border

        a = np.asarray(alpha.convert("L"), dtype=np.uint8)
        visible = a > 12
        if not visible.any():
            return alpha.copy(), {"applied": False, "requires_review": True,
                                  "reason": "empty_alpha", "removed_pixels": 0}
        rgb = np.asarray(image.convert("RGB"), dtype=np.int16)
        neutral = rgb.max(2) - rgb.min(2) <= 18
        white = neutral & (rgb.min(2) >= 232) & visible
        # Distancia hacia el interior de la silueta. Limitarla impide que una
        # zona blanca interna grande se convierta en transparencia.
        distance = cv2.distanceTransform(visible.astype(np.uint8), cv2.DIST_L2, 5)
        candidate = white & (distance <= max(2, int(max_depth_px)))
        count, labels = cv2.connectedComponents(candidate.astype(np.uint8), connectivity=8)
        edge = visible & (distance <= 1.01)
        seeds = np.unique(labels[edge])
        seeds = seeds[seeds != 0]
        removable = np.isin(labels, seeds) if count > 1 and seeds.size else np.zeros_like(visible)
        clean = a.copy()
        clean[removable] = 0
        retained = clean > 12
        ratio = float(retained.sum() / max(1, visible.sum()))
        reason = None
        if not removable.any():
            reason = "existing_white_border_not_isolated"
        elif not retained.any() or ratio < .55:
            reason = "replacement_would_remove_legitimate_content"
        elif confirmed_white_border(image, Image.fromarray(clean)):
            # Si la corona sigue siendo blanca, generar otra sólo produciría
            # un contorno acumulado. La sustitución queda para máscara manual.
            reason = "existing_white_border_remains_after_replacement"
        if reason:
            clean = a.copy()
        return Image.fromarray(clean), {
            "applied": bool(removable.any() and reason is None),
            "requires_review": bool(reason),
            "reason": reason,
            "removed_pixels": int(removable.sum()) if reason is None else 0,
            "retained_area_ratio": ratio,
            "method": "exterior_connected_white_with_depth_limit",
        }

    @staticmethod
    def _polish_final_white_base(mask, strength: int = 1):
        """Suaviza la base blanca final sin modificar el dibujo original.

        La expansión del borde puede amplificar microhuecos, puntos aislados o
        restos de la segmentación y convertirlos en burbujas visibles. Este
        paso opera únicamente sobre la capa blanca. La intensidad permite
        priorizar detalle (0), equilibrio (1) o una limpieza más fuerte (2).
        """
        try:
            import cv2
            import numpy as np
            from PIL import Image

            strength = max(0, min(2, int(strength)))
            binary = (np.asarray(mask.convert("L"), dtype=np.uint8) > 127).astype(np.uint8)
            if not binary.any():
                return mask.convert("L")

            if strength == 0:
                return Image.fromarray(binary * 255, mode="L")

            kernel_size = 5 if strength == 1 else 7
            kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

            count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
            if count > 1:
                areas = stats[1:, cv2.CC_STAT_AREA]
                main_area = int(areas.max())
                minimum_area = max(
                    36 if strength == 1 else 64,
                    round(main_area * (0.0008 if strength == 1 else 0.0015)),
                )
                keep = np.zeros_like(binary)
                for label in range(1, count):
                    if stats[label, cv2.CC_STAT_AREA] >= minimum_area:
                        keep[labels == label] = 1
                binary = keep

            # La base blanca es deliberadamente sólida: los huecos internos
            # pequeños no deben llegar a la capa final como burbujas. Usar
            # RETR_EXTERNAL conserva los detalles grandes como componentes
            # propios en vez de fusionarlos artificialmente.
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            polished = np.zeros_like(binary)
            cv2.drawContours(polished, contours, -1, 1, thickness=cv2.FILLED)
            return Image.fromarray(polished * 255, mode="L")
        except (ImportError, ModuleNotFoundError):
            return mask.convert("L")

    @staticmethod
    def _shape_type(mask) -> str:
        binary = mask.convert("L").point(lambda v: 255 if v >= 24 else 0)
        bbox = binary.getbbox()
        if not bbox:
            return "Silueta"
        cropped = binary.crop(bbox).resize((64, 64))
        pixels = list(cropped.get_flattened_data())
        occ = sum(v > 0 for v in pixels) / len(pixels)
        corner = 8
        cv = []
        for sx, sy in ((0,0),(64-corner,0),(0,64-corner),(64-corner,64-corner)):
            cv.extend(cropped.getpixel((x,y))
                      for y in range(sy,sy+corner)
                      for x in range(sx,sx+corner))
        cf = sum(v > 0 for v in cv) / len(cv)
        return "Rectangular" if occ >= 0.94 and cf >= 0.88 else "Silueta"

    @staticmethod
    def _build_protection_mask(size: tuple[int, int],
                               zones: list[tuple[int, int, int, int]]):
        """Crea una máscara L (mismo tamaño que la imagen fuente) donde las
        zonas de protección valen 255 y el resto 0.

        size  : (width, height) de la imagen original en la que se definieron
                las zonas.
        zones : lista de (x1, y1, x2, y2) en coordenadas de esa imagen.
        """
        from PIL import Image, ImageDraw
        mask = Image.new("L", size, 0)
        draw = ImageDraw.Draw(mask)
        for x1, y1, x2, y2 in zones:
            draw.rectangle([x1, y1, x2, y2], fill=255)
        return mask

    @staticmethod
    def _apply_protection(alpha, protection_mask):
        """Fuerza opacidad completa en las zonas protegidas.

        Se llama después de cada paso que modifica la máscara para garantizar
        que ningún flood fill, segmentación IA ni postprocesado elimine los
        píxeles que el usuario marcó como "no tocar".

        protection_mask debe estar en el mismo espacio de coordenadas que
        alpha (mismo tamaño).  Si los tamaños difieren se reescala al vuelo.
        """
        from PIL import Image, ImageChops
        if protection_mask is None:
            return alpha
        pm = protection_mask
        if pm.size != alpha.size:
            pm = pm.resize(alpha.size, Image.Resampling.NEAREST)
        return ImageChops.lighter(alpha.convert("L"),
                                  pm.point(lambda v: 255 if v > 127 else 0))

    @staticmethod
    def _remove_isolated_components(alpha, protection_mask=None):
        """Descarta fragmentos pequeños y alejados del diseño principal.

        El detector ya informa estas piezas como "componentes separados", pero
        antes quedaban en la máscara final. Solo se eliminan si son pequeñas y
        están claramente aisladas; letras, puntos y adornos cercanos se
        conservan. Las zonas que el usuario protegió nunca se modifican.
        """
        try:
            import cv2
            import numpy as np
            from PIL import Image

            arr = np.asarray(alpha.convert("L"), dtype=np.uint8).copy()
            binary = (arr > 12).astype(np.uint8)
            count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
            if count <= 2:
                return alpha, []

            areas = stats[1:, cv2.CC_STAT_AREA]
            main = int(np.argmax(areas)) + 1
            main_area = float(stats[main, cv2.CC_STAT_AREA])
            mx, my, mw, mh = stats[main, :4]
            diagonal = math.hypot(arr.shape[1], arr.shape[0])
            min_gap = max(12.0, diagonal * 0.045)
            protected = (np.asarray(protection_mask.convert("L")) > 127
                         if protection_mask is not None else None)
            removed = []

            for label in range(1, count):
                if label == main:
                    continue
                x, y, width, height, area = stats[label]
                gap_x = max(mx - (x + width), x - (mx + mw), 0)
                gap_y = max(my - (y + height), y - (my + mh), 0)
                gap = math.hypot(gap_x, gap_y)
                component = labels == label
                is_protected = protected is not None and bool(protected[component].any())
                # A caption above the main illustration is valid artwork even
                # when every letter is a disconnected component.  It will be
                # joined to the unified white base in the later render stage.
                is_top_caption = y < my and area > max(24, main_area * 0.001)
                # Pixel-sized blobs are background/compression residue, not
                # artwork.  Remove them even when they are near the silhouette;
                # otherwise the proximity rule would preserve visible bubbles.
                is_tiny_speck = area <= 24
                if ((is_tiny_speck or (area <= main_area * 0.08
                                       and gap >= min_gap))
                        and not is_protected and not is_top_caption):
                    arr[component] = 0
                    removed.append({
                        "area_px": int(area),
                        "bbox": [int(x), int(y), int(width), int(height)],
                        "gap_px": round(gap, 1),
                    })
            return Image.fromarray(arr, mode="L"), removed
        except (ImportError, ModuleNotFoundError):
            return alpha, []

    # ──────────────────────────────────────────────────────────────────────────
    # TAREA 6B — Base blanca unificada
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_unified_white_base(
        binary_arr,
        final_white_px,
        merge_regions_mm,
        dpi,
    ):
        """Construye una base blanca sólida a partir de la silueta del diseño.

        La máscara de entrada ya fue limpiada por el pipeline; esta función
        no elimina componentes por tamaño.

        Paso 1: Rellena la silueta vía contornos externos (RETR_EXTERNAL + fillPoly).
        Paso 2: Dilatación elíptica por final_white_px → borde blanco.
        Paso 3: Une todas las componentes con puentes (progresivo, mayor→menor).
        Paso 4: MORPH_CLOSE + rellenar contornos + suavizar + binarizar.
        Paso 5: Validación — si quedan >1 componente, reintenta unión.

        Retorna (base_arr, far_components):
          - base_arr: np.ndarray uint8 (H, W), base blanca sólida, 1 componente.
          - far_components: lista de dicts con info de componentes lejanas.
        """
        import cv2
        import numpy as np
        import time

        t0 = time.perf_counter()
        h, w = binary_arr.shape

        # ── 1. Rellenar silueta vía contornos externos ──────────────────
        contours, _ = cv2.findContours(
            binary_arr, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        solid = np.zeros_like(binary_arr)
        if contours:
            cv2.fillPoly(solid, contours, 255)

        if solid.max() == 0:
            return solid, []

        # ── 2. Dilatación elíptica → borde blanco ───────────────────────
        d = max(1, final_white_px * 2 + 1)
        kernel_dilate = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d))
        expanded = cv2.dilate(solid, kernel_dilate, iterations=1)

        # ── 3. Unir todas las componentes con puentes ────────────────────
        n_exp, exp_labels, exp_stats, _ = cv2.connectedComponentsWithStats(
            expanded, connectivity=8)
        far_components = []
        bridge_width = max(
            final_white_px,
            round(merge_regions_mm * dpi / 25.4))
        max_gap = max(
            final_white_px * 2,
            round(merge_regions_mm * dpi / 25.4))
        radius = max(1, bridge_width // 2)

        if n_exp > 2:
            order = sorted(range(1, n_exp),
                           key=lambda i: exp_stats[i, cv2.CC_STAT_AREA],
                           reverse=True)
            main_label = order[0]
            group_mask = (exp_labels == main_label).astype(np.uint8) * 255

            for label in order[1:]:
                comp_mask = (exp_labels == label).astype(np.uint8) * 255

                inv_group = cv2.bitwise_not(group_mask)
                dist_map = cv2.distanceTransform(inv_group, cv2.DIST_L2, 5)

                cnt, _ = cv2.findContours(
                    comp_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
                if not cnt:
                    continue
                pts = cnt[0].reshape(-1, 2)

                max_sample = 2000
                if len(pts) > max_sample:
                    idx = np.linspace(0, len(pts) - 1,
                                      max_sample, dtype=int)
                    pts = pts[idx]

                dists = dist_map[pts[:, 1], pts[:, 0]]
                min_i = int(np.argmin(dists))
                p_comp = (int(pts[min_i, 0]), int(pts[min_i, 1]))
                dist = float(dists[min_i])

                if dist > max_gap:
                    far_components.append({
                        "label": int(label),
                        "area_px": int(
                            exp_stats[label, cv2.CC_STAT_AREA]),
                        "distance_px": round(dist, 1),
                    })
                    # No dibujar puentes hasta residuos lejanos: inflan la
                    # base blanca y convierten motas de fondo en bultos.
                    continue

                dd = int(np.ceil(dist))
                cy0 = max(0, p_comp[1] - dd - 1)
                cy1 = min(h, p_comp[1] + dd + 2)
                cx0 = max(0, p_comp[0] - dd - 1)
                cx1 = min(w, p_comp[0] + dd + 2)
                crop = group_mask[cy0:cy1, cx0:cx1]
                g_ys, g_xs = np.where(crop > 0)
                if len(g_ys) == 0:
                    continue
                g_d = ((g_ys - (p_comp[1] - cy0)) ** 2
                       + (g_xs - (p_comp[0] - cx0)) ** 2)
                bi = int(np.argmin(g_d))
                p_group = (int(g_xs[bi]) + cx0,
                           int(g_ys[bi]) + cy0)

                cv2.line(expanded, p_comp, p_group, 255,
                         thickness=bridge_width,
                         lineType=cv2.LINE_8)
                cv2.circle(expanded, p_comp, radius, 255, -1)
                cv2.circle(expanded, p_group, radius, 255, -1)

                comp_u8 = (exp_labels == label).astype(np.uint8) * 255
                bridge_u8 = np.zeros_like(expanded)
                cv2.line(bridge_u8, p_comp, p_group, 255,
                         thickness=bridge_width, lineType=cv2.LINE_8)
                cv2.circle(bridge_u8, p_comp, radius, 255, -1)
                cv2.circle(bridge_u8, p_group, radius, 255, -1)
                group_mask = cv2.bitwise_or(
                    group_mask, cv2.bitwise_or(comp_u8, bridge_u8))

        # ── 4. Cerrar canales + rellenar + suavizar + binarizar ──────────
        k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        expanded = cv2.morphologyEx(expanded, cv2.MORPH_CLOSE, k5)

        contours, _ = cv2.findContours(
            expanded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            cv2.fillPoly(expanded, contours, 255)

        expanded = cv2.GaussianBlur(expanded, (3, 3), 0.8)
        _, expanded = cv2.threshold(
            expanded, 127, 255, cv2.THRESH_BINARY)

        # ── 5. Validación final: debe quedar 1 componente ────────────────
        final_count, _, _, _ = cv2.connectedComponentsWithStats(
            expanded, connectivity=8)
        if final_count - 1 > 1:
            # Reintento: unir las que queden por borde más cercano
            n_retry, retry_labels, retry_stats, _ = (
                cv2.connectedComponentsWithStats(expanded, connectivity=8))
            if n_retry > 2:
                retry_order = sorted(
                    range(1, n_retry),
                    key=lambda i: retry_stats[i, cv2.CC_STAT_AREA],
                    reverse=True)
                retry_group = (
                    retry_labels == retry_order[0]
                ).astype(np.uint8) * 255

                for rl in retry_order[1:]:
                    rcomp = (
                        retry_labels == rl
                    ).astype(np.uint8) * 255
                    inv_rg = cv2.bitwise_not(retry_group)
                    dm = cv2.distanceTransform(
                        inv_rg, cv2.DIST_L2, 5)
                    rc, _ = cv2.findContours(
                        rcomp, cv2.RETR_EXTERNAL,
                        cv2.CHAIN_APPROX_NONE)
                    if not rc:
                        continue
                    rpts = rc[0].reshape(-1, 2)
                    if len(rpts) > 2000:
                        idx = np.linspace(
                            0, len(rpts) - 1, 2000, dtype=int)
                        rpts = rpts[idx]
                    rd = dm[rpts[:, 1], rpts[:, 0]]
                    mi = int(np.argmin(rd))
                    pa = (int(rpts[mi, 0]), int(rpts[mi, 1]))
                    dd2 = int(np.ceil(float(rd[mi])))
                    ry0 = max(0, pa[1] - dd2 - 1)
                    ry1 = min(h, pa[1] + dd2 + 2)
                    rx0 = max(0, pa[0] - dd2 - 1)
                    rx1 = min(w, pa[0] + dd2 + 2)
                    rcrop = retry_group[ry0:ry1, rx0:rx1]
                    gy, gx = np.where(rcrop > 0)
                    if len(gy) == 0:
                        continue
                    gd = ((gy - (pa[1] - ry0)) ** 2
                          + (gx - (pa[0] - rx0)) ** 2)
                    bi2 = int(np.argmin(gd))
                    pb = (int(gx[bi2]) + rx0,
                          int(gy[bi2]) + ry0)
                    cv2.line(expanded, pa, pb, 255,
                             thickness=bridge_width,
                             lineType=cv2.LINE_8)
                    cv2.circle(expanded, pa, radius, 255, -1)
                    cv2.circle(expanded, pb, radius, 255, -1)
                    ru = rcomp
                    bu = np.zeros_like(expanded)
                    cv2.line(bu, pa, pb, 255,
                             thickness=bridge_width,
                             lineType=cv2.LINE_8)
                    cv2.circle(bu, pa, radius, 255, -1)
                    cv2.circle(bu, pb, radius, 255, -1)
                    retry_group = cv2.bitwise_or(
                        retry_group,
                        cv2.bitwise_or(ru, bu))

            # Re-postprocesar tras reintento
            expanded = cv2.morphologyEx(
                expanded, cv2.MORPH_CLOSE, k5)
            contours, _ = cv2.findContours(
                expanded, cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                cv2.fillPoly(expanded, contours, 255)
            expanded = cv2.GaussianBlur(expanded, (3, 3), 0.8)
            _, expanded = cv2.threshold(
                expanded, 127, 255, cv2.THRESH_BINARY)

            final_count2, _, _, _ = cv2.connectedComponentsWithStats(
                expanded, connectivity=8)
            if final_count2 - 1 > 1 and not far_components:
                far_components.append({
                    "label": -1,
                    "area_px": 0,
                    "distance_px": 0,
                    "warning": (
                        "No se pudo unir en una sola componente"),
                })

        ms = int((time.perf_counter() - t0) * 1000)
        final_n, _, _, _ = cv2.connectedComponentsWithStats(
            expanded, connectivity=8)
        logger.info(
            "_build_unified_white_base: %d ms, "
            "%d→%d componentes, %d lejanas",
            ms, max(0, n_exp - 1), max(0, final_n - 1),
            len(far_components))

        return expanded, far_components

    # ──────────────────────────────────────────────────────────────────────────
    # TAREA 7 — Postprocesado unificado
    # ──────────────────────────────────────────────────────────────────────────

    def _postprocess(self, mask, dpi: int, fill_holes: bool | None = None,
                    skip_corner_rounding: bool = False,
                    skip_all_morphology: bool = False) -> tuple["Image", dict]:
        """Postprocesado unificado aplicado a todos los casos.

        CORRECCIÓN 3: Para PNG con transparencia real, skip_all_morphology=True
        para preservar el alfa original sin modificaciones.

        Cada paso se controla con los campos booleanos + numéricos de
        self.profile, de modo que el usuario puede activarlos y ajustar
        sus parámetros desde ProcessingProfileEditor sin tocar código.

        Orden canónico
        ──────────────
        1.  Rellenar huecos internos          (fill_holes)
        2.  Eliminar partículas               (remove_particles)
        3.  Cerrar canales estrechos          (close_channels)
        4.  Unir regiones cercanas            (merge_regions)
        5.  Redondear esquinas                (round_corners)
        6.  Eliminar picos (hull adaptativo)  (remove_spikes)
        7.  Simplificar + suavizar curvas     (simplify_curves)
        8.  Unificar grosor ±0.05 mm
        9.  Verificar troquel continuo
        """
        metadata = {
            "holes_detected": 0,
            "holes_filled": 0,
            "hole_analysis": [],
            "removed_particles_count": 0,
            "removed_particles": [],
            "preserved_nearby_components": [],
        }

        # CORRECCIÓN 3: Skip all morphology for transparent PNGs to preserve original alpha
        if skip_all_morphology:
            logger.info("CORRECCION_3: Skipping all morphology operations to preserve original alpha")
            return mask, metadata

        try:
            import cv2
            import numpy as np
            from PIL import Image

            p   = self.profile          # alias corto
            px  = dpi / 25.4            # px por mm

            arr = np.asarray(mask.convert("L"), dtype=np.uint8)
            _, arr = cv2.threshold(arr, 127, 255, cv2.THRESH_BINARY)

            def ek(mm: float):
                """Kernel elíptico para un radio expresado en mm."""
                r = max(1, int(round(mm * px)))
                return cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                                 (r * 2 + 1, r * 2 + 1))

            # ── 1. Rellenar huecos internos ───────────────────────────────
            hole_details = self._analyze_closed_holes(mask)
            holes_filled = 0
            if p.fill_holes and fill_holes is not False:
                closed = cv2.morphologyEx(arr, cv2.MORPH_CLOSE, ek(2.0))
                diff   = cv2.subtract(closed, arr)
                # Solo rellenar si el hueco es más pequeño que fill_holes_max_px
                if p.fill_holes_max_px > 0:
                    n_h, lmap_h, stats_h, _ = cv2.connectedComponentsWithStats(
                        diff, connectivity=8)
                    patch = np.zeros_like(diff)
                    for lb in range(1, n_h):
                        if stats_h[lb, cv2.CC_STAT_AREA] <= p.fill_holes_max_px:
                            patch[lmap_h == lb] = 255
                            holes_filled += 1
                    arr = cv2.bitwise_or(arr, patch)
                else:
                    arr = cv2.bitwise_or(arr, diff)
                    holes_filled = len(hole_details)
            else:
                holes_filled = 0

            # ── 2. Eliminar partículas ────────────────────────────────────
            removed_particles: list[dict] = []
            preserved_nearby_components: list[dict] = []
            if p.remove_particles:
                min_area = max(1, p.remove_particles_min_px)
                n_c, lmap_c, stats_c, _ = cv2.connectedComponentsWithStats(
                    arr, connectivity=8)
                clean = np.zeros_like(arr)

                # A small feature beside the main design (such as a letter
                # dot) is part of the same sticker, not disposable noise.
                merge_gap_px = (
                    p.merge_regions_mm * px
                    if p.merge_regions and p.merge_regions_mm > 0 else 0.0
                )

                def bbox_gap(first, second) -> float:
                    fx, fy, fw, fh = (int(first[cv2.CC_STAT_LEFT]),
                                      int(first[cv2.CC_STAT_TOP]),
                                      int(first[cv2.CC_STAT_WIDTH]),
                                      int(first[cv2.CC_STAT_HEIGHT]))
                    sx, sy, sw, sh = (int(second[cv2.CC_STAT_LEFT]),
                                      int(second[cv2.CC_STAT_TOP]),
                                      int(second[cv2.CC_STAT_WIDTH]),
                                      int(second[cv2.CC_STAT_HEIGHT]))
                    dx = max(fx - (sx + sw), sx - (fx + fw), 0)
                    dy = max(fy - (sy + sh), sy - (fy + fh), 0)
                    return float((dx * dx + dy * dy) ** 0.5)
                for lb in range(1, n_c):
                    area = int(stats_c[lb, cv2.CC_STAT_AREA])
                    left = int(stats_c[lb, cv2.CC_STAT_LEFT])
                    top = int(stats_c[lb, cv2.CC_STAT_TOP])
                    width = int(stats_c[lb, cv2.CC_STAT_WIDTH])
                    height = int(stats_c[lb, cv2.CC_STAT_HEIGHT])
                    close_to_design = (
                        area < min_area and merge_gap_px > 0 and any(
                            other != lb
                            and int(stats_c[other, cv2.CC_STAT_AREA]) >= min_area
                            and bbox_gap(stats_c[lb], stats_c[other]) <= merge_gap_px
                            for other in range(1, n_c)
                        )
                    )
                    if area >= min_area or close_to_design:
                        clean[lmap_c == lb] = 255
                        if close_to_design:
                            preserved_nearby_components.append({
                                "area_px": area,
                                "bbox": [left, top, width, height],
                                "merge_gap_px": round(merge_gap_px, 2),
                            })
                    else:
                        removed_particles.append({
                            "area_px": area,
                            "bbox": [left, top, width, height],
                            "min_dimension_px": min(width, height),
                            "centroid": [
                                left + width // 2,
                                top + height // 2,
                            ],
                        })
                arr = clean
            else:
                removed_particles = []
                preserved_nearby_components = []

            # ── 3. Eliminar picos ───────────────────────────────────────
            MAX_MOUTH_MM = 4.0
            MAX_RATIO    = 0.25
            dp_tol       = (p.simplify_curves_mm if p.simplify_curves else 0) * px

            if p.remove_spikes:
                contours, hier = cv2.findContours(
                    arr, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_TC89_L1)
                if contours:
                    refined = np.zeros_like(arr)
                    for ci, cnt in enumerate(contours):
                        is_hole = hier is not None and hier[0][ci][3] != -1
                        if is_hole or len(cnt) < 8:
                            if len(cnt) >= 3:
                                cv2.fillPoly(refined,
                                             [cnt.reshape(-1, 1, 2)],
                                             0 if is_hole else 255)
                            continue
                        pts  = cnt.reshape(-1, 2).astype(np.float64)
                        hidx = cv2.convexHull(cnt, returnPoints=False)
                        if hidx is None or len(hidx) < 3:
                            cv2.fillPoly(refined, [cnt], 255)
                            continue
                        hf       = sorted(hidx.flatten().tolist())
                        new_pts: list = []
                        for si in range(len(hf)):
                            ia, ib = hf[si], hf[(si + 1) % len(hf)]
                            pa, pb = pts[ia], pts[ib]
                            new_pts.append((float(pa[0]), float(pa[1])))
                            seg = (pts[ia + 1:ib] if ib > ia
                                   else np.vstack([pts[ia + 1:], pts[:ib]]))
                            if not len(seg):
                                continue
                            ch = pb - pa
                            cl = float(np.linalg.norm(ch))
                            if cl < 1e-6:
                                new_pts.extend(
                                    (float(q[0]), float(q[1])) for q in seg)
                                continue
                            cu   = ch / cl
                            perp = np.abs((seg - pa)[:, 0] * (-cu[1]) +
                                          (seg - pa)[:, 1] * cu[0])
                            if not (perp.max() / px / cl * px < MAX_RATIO
                                    and cl / px < MAX_MOUTH_MM):
                                new_pts.extend(
                                    (float(q[0]), float(q[1])) for q in seg)
                        if len(new_pts) < 3:
                            cv2.fillPoly(refined, [cnt], 255)
                            continue
                        poly = np.array(
                            [[int(round(x)), int(round(y))]
                             for x, y in new_pts], dtype=np.int32)
                        cv2.fillPoly(refined, [poly], 255)
                    arr = refined

            # ── 4. Cerrar canales estrechos ───────────────────────────────
            if p.close_channels and p.close_channels_mm > 0:
                r_mm = p.close_channels_mm / 2.0
                arr  = cv2.morphologyEx(arr, cv2.MORPH_CLOSE, ek(r_mm))

            # ── 5. Unir regiones cercanas ─────────────────────────────────
            if p.merge_regions and p.merge_regions_mm > 0:
                r_mm  = p.merge_regions_mm / 2.0
                k     = ek(r_mm)
                arr   = cv2.erode(cv2.dilate(arr, k), k)

            # ── 6. Redondear esquinas ─────────────────────────────────────
            # Skip corner rounding for PNG files to preserve original shape
            if p.round_corners and not skip_corner_rounding:
                corner_mm = p.round_corners_mm
                if p.min_corner_radius_px > 0:
                    corner_mm = max(corner_mm, p.min_corner_radius_px / px)
                if corner_mm > 0:
                    arr = cv2.morphologyEx(arr, cv2.MORPH_OPEN,
                                           ek(corner_mm))

            # ── 7. Suavizar curvas ─────────────────────────────────────────

            def chaikin(pts, iters: int = 2):
                for _ in range(iters):
                    out, m = [], len(pts)
                    for k in range(m):
                        p0, p1 = pts[k], pts[(k + 1) % m]
                        out.append((.75 * p0[0] + .25 * p1[0],
                                    .75 * p0[1] + .25 * p1[1]))
                        out.append((.25 * p0[0] + .75 * p1[0],
                                    .25 * p0[1] + .75 * p1[1]))
                    pts = out
                return pts

            if p.simplify_curves and dp_tol > 0:
                c2, h2 = cv2.findContours(
                    arr, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
                if c2:
                    final = np.zeros_like(arr)
                    for ci, cnt in enumerate(c2):
                        ap = cv2.approxPolyDP(cnt, dp_tol, closed=True)
                        if len(ap) < 3:
                            continue
                        raw  = [(float(q[0][0]), float(q[0][1])) for q in ap]
                        smth = chaikin(raw, iters=p.curve_smooth_iters)
                        poly = np.array(
                            [[int(round(x)), int(round(y))]
                             for x, y in smth], dtype=np.int32)
                        ih = h2 is not None and h2[0][ci][3] != -1
                        cv2.fillPoly(final, [poly], 0 if ih else 255)
                    arr = final

            # ── 8. Unificar grosor ±0.05 mm ───────────────────────────────
            tk = ek(0.05)
            arr = cv2.erode(cv2.dilate(arr, tk), tk)

            # ── 9. Verificar troquel continuo ─────────────────────────────
            result = Image.fromarray(arr, mode="L")
            metadata = {
                "holes_detected": len(hole_details),
                "holes_filled": holes_filled,
                "hole_analysis": hole_details,
                "removed_particles_count": len(removed_particles),
                "removed_particles": removed_particles,
                "preserved_nearby_components": preserved_nearby_components,
            }
            if not result.getbbox():
                return mask, metadata  # fallback: devolver la máscara sin tocar
            return result, metadata

        except (ImportError, ModuleNotFoundError):
            return mask, metadata

    # ──────────────────────────────────────────────────────────────────────────
    # Etapa 2B — Eliminación de ruido gris aislado
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_geometry_preservation(original_rgba, final_rgba, source_path: str) -> dict:
        """CORRECCIÓN 8: Validar que la geometría del diseño se preserve correctamente.

        Pruebas obligatorias:
        - Verificar que no se pierdan píxeles opacos del contenido original
        - Comparar visualmente alfa original versus alfa final
        - La prueba debe fallar si se pierde cualquier píxel opaco del contenido original

        Args:
            original_rgba: PIL Image in RGBA mode (original content)
            final_rgba: PIL Image in RGBA mode (final processed content)
            source_path: Path to source file for logging

        Returns:
            dict with validation results and any errors found
        """
        try:
            import numpy as np
            from PIL import Image

            logger.info("GEOMETRY_VALIDATION: starting for %s", source_path)

            # Extraer canales alfa
            original_alpha = np.asarray(original_rgba.getchannel("A"), dtype=np.uint8)
            final_alpha = np.asarray(final_rgba.getchannel("A"), dtype=np.uint8)

            # Verificar que no se pierdan píxeles opacos del contenido original
            original_content_alpha = (original_alpha > 127)
            final_content_alpha = (final_alpha > 127)

            # Píxeles perdidos: opacos en original pero transparentes en final
            lost_pixels = (original_content_alpha & ~final_content_alpha)
            lost_count = int(lost_pixels.sum())

            # Píxeles ganados: transparentes en original pero opacos en final
            gained_pixels = (~original_content_alpha & final_content_alpha)
            gained_count = int(gained_pixels.sum())

            # Calcular porcentajes
            total_original_opaque = int(original_content_alpha.sum())
            lost_ratio = lost_count / max(1, total_original_opaque)

            validation_result = {
                "source_path": str(source_path),
                "original_opaque_pixels": total_original_opaque,
                "final_opaque_pixels": int(final_content_alpha.sum()),
                "lost_pixels": lost_count,
                "lost_ratio": round(lost_ratio, 6),
                "gained_pixels": gained_count,
                "validation_passed": True,
                "errors": []
            }

            # ERROR CRÍTICO: Si se pierden píxeles opacos del contenido original
            if lost_count > 0:
                error_msg = (
                    f"El postprocesado eliminó {lost_count} píxeles originales "
                    f"({lost_ratio:.2%} del contenido original)"
                )
                validation_result["validation_passed"] = False
                validation_result["errors"].append(error_msg)
                logger.error("GEOMETRY_VALIDATION: %s", error_msg)
            else:
                logger.info("GEOMETRY_VALIDATION: No se perdieron píxeles del contenido original")

            # ADVERTENCIA: Si se ganaron muchos píxeles (posible sobre-expansión)
            if gained_count > total_original_opaque * 0.1:
                warning_msg = (
                    f"El postprocesado agregó {gained_count} píxeles "
                    f"({gained_count / max(1, total_original_opaque):.2%} del contenido original)"
                )
                validation_result["errors"].append(warning_msg)
                logger.warning("GEOMETRY_VALIDATION: %s", warning_msg)

            # Verificar preservación de forma para estrellas (detección de puntas afiladas)
            # Comparar la relación perímetro/área para detectar redondeo
            try:
                import cv2

                # Encontrar contornos del alfa original
                original_binary = original_content_alpha.astype(np.uint8) * 255
                contours, _ = cv2.findContours(original_binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                if contours:
                    # Calcular perímetro y área del contorno más grande
                    main_contour = max(contours, key=cv2.contourArea)
                    original_perimeter = cv2.arcLength(main_contour, True)
                    original_area = cv2.contourArea(main_contour)

                    # Hacer lo mismo para el final
                    final_binary = final_content_alpha.astype(np.uint8) * 255
                    final_contours, _ = cv2.findContours(final_binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                    if final_contours:
                        main_final = max(final_contours, key=cv2.contourArea)
                        final_perimeter = cv2.arcLength(main_final, True)
                        final_area = cv2.contourArea(main_final)

                        # Calcular compactación (perímetro² / área)
                        # Valores más altos indican formas más irregulares (puntas afiladas)
                        original_compactness = (original_perimeter ** 2) / max(1, original_area)
                        final_compactness = (final_perimeter ** 2) / max(1, final_area)

                        compactness_loss = (original_compactness - final_compactness) / max(1, original_compactness)

                        validation_result["original_compactness"] = round(original_compactness, 2)
                        validation_result["final_compactness"] = round(final_compactness, 2)
                        validation_result["compactness_loss"] = round(compactness_loss, 6)

                        # Si la compactación disminuye significativamente, las puntas se redondearon
                        if compactness_loss > 0.05:  # 5% de pérdida de compactación
                            warning_msg = (
                                f"Posible redondeo de puntas: "
                                f"compactación cambió de {original_compactness:.2f} a {final_compactness:.2f} "
                                f"({compactness_loss:.1%})"
                            )
                            validation_result["errors"].append(warning_msg)
                            logger.warning("GEOMETRY_VALIDATION: %s", warning_msg)

            except (ImportError, ModuleNotFoundError):
                logger.info("GEOMETRY_VALIDATION: OpenCV no disponible, omitiendo análisis de puntas")

            logger.info(
                "GEOMETRY_VALIDATION: passed=%s, lost=%d, gained=%d, errors=%d",
                validation_result["validation_passed"],
                lost_count,
                gained_count,
                len(validation_result["errors"])
            )

            return validation_result

        except Exception as e:
            logger.exception("GEOMETRY_VALIDATION: error durante validación")
            return {
                "source_path": str(source_path),
                "validation_passed": False,
                "errors": [f"Error durante validación: {str(e)}"]
            }

    @staticmethod
    def _remove_grey_noise(alpha_img, rgb_np):
        """Elimina componentes grises aislados de baja textura.

        Extremadamente conservador: solo elimina componentes que cumplen
        TODAS las condiciones de ruido gris. Preserva componentes con
        saturación, textura o líneas oscuras.

        Returns: (alpha_img, removal_log)
        """
        import numpy as np
        import cv2
        from PIL import Image as _PilImage
        alpha_np = np.array(alpha_img, dtype=np.uint8)
        binary = alpha_np > 127

        # OpenCV ya se usa en esta etapa. Sus estadísticas evitan el barrido
        # completo por cada componente que hacía scipy.ndimage, especialmente
        # costoso en imágenes grandes con muchos fragmentos.
        n_labels, labeled, stats, _ = cv2.connectedComponentsWithStats(
            binary.astype(np.uint8), connectivity=8)
        if n_labels <= 2:
            return alpha_img, []

        comp_sizes = sorted(
            ((label, int(stats[label, cv2.CC_STAT_AREA]))
             for label in range(1, n_labels)),
            key=lambda item: item[1], reverse=True)
        main_label = comp_sizes[0][0]
        main_area = comp_sizes[0][1]

        grey = np.mean(rgb_np.astype(np.float32), axis=2)
        r_ch = rgb_np[:, :, 0].astype(np.float32)
        g_ch = rgb_np[:, :, 1].astype(np.float32)
        b_ch = rgb_np[:, :, 2].astype(np.float32)
        cmax = np.maximum(np.maximum(r_ch, g_ch), b_ch) / 255.0
        cmin = np.minimum(np.minimum(r_ch, g_ch), b_ch) / 255.0
        with np.errstate(divide="ignore", invalid="ignore"):
            saturation = np.where(cmax == 0, 0.0, (cmax - cmin) / cmax)

        grey_u8 = np.clip(grey, 0, 255).astype(np.uint8)
        blurred = cv2.blur(grey_u8.astype(np.float32), (7, 7))
        local_var = cv2.blur(
            (grey_u8.astype(np.float32) - blurred) ** 2, (7, 7))
        local_std = np.sqrt(np.maximum(local_var, 0))

        sobelx = cv2.Sobel(grey_u8, cv2.CV_32F, 1, 0, ksize=3)
        sobely = cv2.Sobel(grey_u8, cv2.CV_32F, 0, 1, ksize=3)
        grad = np.sqrt(sobelx ** 2 + sobely ** 2)

        removal_log = []
        result = alpha_np.copy()

        for comp_label, comp_area in comp_sizes:
            if comp_label == main_label:
                continue

            area_ratio = comp_area / max(main_area, 1)
            if area_ratio >= 0.01:
                continue

            mask = labeled == comp_label
            comp_grey = grey[mask]
            comp_sat = saturation[mask]
            n_pix = max(comp_area, 1)
            comp_texture = float((local_std[mask] > 15).sum()) / n_pix
            comp_dark = float(
                ((grey[mask] < 80) & (grad[mask] > 20)).sum()) / n_pix
            mean_lum = float(comp_grey.mean())
            mean_sat = float(comp_sat.mean())

            should_remove = (
                area_ratio < 0.01
                and mean_sat < 0.10
                and 170 <= mean_lum <= 220
                and comp_texture < 0.20
                and comp_dark < 0.05
            )

            entry = {
                "area": comp_area,
                "area_ratio": round(area_ratio, 6),
                "mean_luminance": round(mean_lum, 1),
                "mean_saturation": round(mean_sat, 4),
                "texture_ratio": round(comp_texture, 4),
                "dark_line_ratio": round(comp_dark, 4),
                "removed": should_remove,
            }

            if should_remove:
                result[mask] = 0
                entry["reason"] = (
                    "grey noise: area_ratio=%.4f, "
                    "sat=%.3f, lum=%.0f, tex=%.3f, dark=%.3f"
                    % (area_ratio, mean_sat, mean_lum,
                       comp_texture, comp_dark))
            else:
                reasons = []
                if mean_sat >= 0.10:
                    reasons.append("sat=%.3f>=0.10" % mean_sat)
                if comp_texture >= 0.20:
                    reasons.append("tex=%.3f>=0.20" % comp_texture)
                if comp_dark >= 0.05:
                    reasons.append("dark=%.3f>=0.05" % comp_dark)
                if mean_lum < 170 or mean_lum > 220:
                    reasons.append("lum=%.0f outside [170,220]" % mean_lum)
                entry["reason"] = "kept: %s" % ", ".join(reasons)

            removal_log.append(entry)

        result_img = _PilImage.fromarray(result, "L")
        removed_count = sum(1 for e in removal_log if e["removed"])
        logger.info(
            "Etapa 2B: %d/%d components removed as grey noise",
            removed_count, len(removal_log))
        return result_img, removal_log

    # ──────────────────────────────────────────────────────────────────────────
    # Etapa 2A — Reconstrucción de base blanca desplazada
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _measure_white_base(rgb_np, alpha_np):
        """Mide cobertura, exceso y faltante de la base blanca.

        Returns dict con coverage_ratio, excess_ratio, missing_ratio.
        """
        import cv2

        subject_mask = alpha_np > 127
        white_mask = (
            (rgb_np[:, :, 0] > 235)
            & (rgb_np[:, :, 1] > 235)
            & (rgb_np[:, :, 2] > 235)
        )
        expected = white_mask & subject_mask
        actual_white = white_mask & (alpha_np > 127)

        expected_area = int(expected.sum())
        intersection = int((expected & actual_white).sum())
        excess = int((actual_white & ~expected).sum())
        missing = int((expected & ~actual_white).sum())

        return {
            "coverage_ratio": round(intersection / max(expected_area, 1), 4),
            "excess_ratio": round(excess / max(expected_area, 1), 4),
            "missing_ratio": round(missing / max(expected_area, 1), 4),
            "expected_base_area": expected_area,
            "excess_white_area": excess,
            "missing_white_area": missing,
        }

    @staticmethod
    def _rebuild_displaced_white_base(rgb_np, raw_alpha, target_radius,
                                       tolerance=10):
        """Reconstruye la base blanca cuando está desplazada.

        Crea una máscara de diseño real desde el RGB original, genera una
        base blanca nueva mediante distancia al diseño, y combina con el
        blanco existente que esté próximo.

        No usa convexHull ni cierre morfológico grande.

        Returns: Image.alpha (L mode) con la máscara reconstruida.
        """
        import cv2
        from PIL import Image

        h, w = rgb_np.shape[:2]

        r_ch = rgb_np[:, :, 0].astype(np.float32)
        g_ch = rgb_np[:, :, 1].astype(np.float32)
        b_ch = rgb_np[:, :, 2].astype(np.float32)
        cmax = np.maximum(np.maximum(r_ch, g_ch), b_ch) / 255.0
        cmin = np.minimum(np.minimum(r_ch, g_ch), b_ch) / 255.0
        saturation = np.where(cmax == 0, 0.0, (cmax - cmin) / cmax)
        luminance = 0.299 * r_ch + 0.587 * g_ch + 0.114 * b_ch

        sat_thresh = 0.12
        dark_thresh = 180
        design_seed = (saturation > sat_thresh) | (luminance < dark_thresh)

        existing_white = raw_alpha.point(lambda v: 255 if v > 127 else 0)
        existing_white_np = np.array(existing_white) > 0
        white_mask = (
            (rgb_np[:, :, 0] > 235)
            & (rgb_np[:, :, 1] > 235)
            & (rgb_np[:, :, 2] > 235)
        )
        existing_white_area = existing_white_np & white_mask

        inv_design = (~design_seed).astype(np.uint8)
        dist_to_design = cv2.distanceTransform(inv_design, cv2.DIST_L2, 5)

        generated_base = dist_to_design <= target_radius

        valid_existing = existing_white_area & (
            dist_to_design <= target_radius + tolerance
        )

        final_subject = design_seed | generated_base | valid_existing

        labeled, n_labels = cv2.connectedComponents(
            final_subject.astype(np.uint8))
        if n_labels > 1:
            sizes = [(labeled == i).sum() for i in range(1, n_labels)]
            main_label = np.argmax(sizes) + 1
            final_subject = labeled == main_label

        result_alpha = np.where(final_subject, 255, 0).astype(np.uint8)
        return Image.fromarray(result_alpha, "L")

    # ──────────────────────────────────────────────────────────────────────────
    # TAREA 8 — process(): orquestador principal
    # ──────────────────────────────────────────────────────────────────────────

    def process(self, source_path, progress=None, cut_inset_mm=None,
                mask_override=None, preserve_full_image=False,
                preserve_orientation=False, mode_override=None,
                protection_zones=None, creation_mode=None,
                full_image_shape="Rectangular", selected_component_ids=None,
                visual_type_override=None, border_treatment=None,
                selection_contraction_mm=0.0, selection_smoothing_mm=0.08,
                selection_expansion_mm=0.0,
                selection_protection_mask=None,
                *, cancelled=None, **options):
        """Ejecuta una corrida aislada y elimina solo su salida si se cancela."""
        automatic_recovery = options.pop("automatic_recovery", True)
        approved_result = options.pop("approved_result", False)
        options.update(
            cut_inset_mm=cut_inset_mm, mask_override=mask_override,
            preserve_full_image=preserve_full_image,
            preserve_orientation=preserve_orientation, mode_override=mode_override,
            protection_zones=protection_zones, creation_mode=creation_mode,
            full_image_shape=full_image_shape,
            selected_component_ids=selected_component_ids,
            visual_type_override=visual_type_override,
            border_treatment=border_treatment,
            selection_contraction_mm=selection_contraction_mm,
            selection_smoothing_mm=selection_smoothing_mm,
            selection_expansion_mm=selection_expansion_mm,
            selection_protection_mask=selection_protection_mask,
        )
        run_id = uuid.uuid4().hex
        run_directory = self.workspace / run_id
        def checked_progress(percent, message):
            if cancelled is not None and cancelled():
                raise ProcessingCancelled("Procesamiento cancelado; no se aprobó ningún resultado.")
            if progress is not None:
                progress(percent, message)
        run_directories = [run_directory]
        try:
            checked_progress(0, "Preparando procesamiento")
            result = self._process_impl(source_path, progress=checked_progress,
                                        _run_id=run_id, **options)
            from .recovery import recovery_allowed, compare_recovery
            if automatic_recovery and recovery_allowed(result, {**options, "approved_result": approved_result}):
                raw_mask = (result.artifacts.get("mask_recovery_raw")
                            or result.artifacts.get("mask_segmentation_raw"))
                if raw_mask and Path(raw_mask).exists():
                    # Una sola alternativa: la misma extracción antes de las
                    # correcciones automáticas; ninguna otra ruta de IA.
                    checked_progress(90, "Evaluando recuperación compatible")
                    alternative_id = uuid.uuid4().hex
                    run_directories.append(self.workspace / alternative_id)
                    alternative_options = {**options, "mask_override": raw_mask,
                                           "visual_type_override": result.analysis.get("sticker_type")}
                    try:
                        alternative = self._process_impl(
                            source_path, progress=checked_progress,
                            _run_id=alternative_id, **alternative_options)
                    except ProcessingCancelled:
                        raise
                    except Exception as error:
                        failed_directory = self.workspace / alternative_id
                        if failed_directory.exists():
                            shutil.rmtree(failed_directory)
                        result.analysis["automatic_recovery"] = {
                            "attempts": 1, "status": "alternative_failed",
                            "error": str(error), "primary_job_id": result.job_id,
                        }
                        self._persist_result_analysis(result)
                        return result
                    for key in ("sticker_type", "sticker_type_label", "detected_types", "classification_features"):
                        if key in result.analysis:
                            alternative.analysis[key] = result.analysis[key]
                    comparison = compare_recovery(result, alternative)
                    selected = alternative if comparison["select_alternative"] else result
                    history = {"attempts": 1, "primary_job_id": result.job_id,
                               "alternative_job_id": alternative.job_id,
                               "primary_metadata": result.artifacts["metadata"],
                               "alternative_metadata": alternative.artifacts["metadata"],
                               "selected_job_id": selected.job_id,
                               "comparison": comparison}
                    result.analysis["automatic_recovery"] = history
                    alternative.analysis["automatic_recovery"] = history
                    self._persist_result_analysis(result)
                    self._persist_result_analysis(alternative)
                    return selected
            return result
        except ProcessingCancelled:
            # El destino deriva de un UUID creado aquí, dentro del workspace;
            # jamás se elimina una entrada del usuario ni una corrida previa.
            for directory in run_directories:
                if directory.parent.resolve() == self.workspace.resolve() and directory.exists():
                    shutil.rmtree(directory)
            raise

    @staticmethod
    def _persist_result_analysis(result):
        path = Path(result.artifacts["metadata"])
        metadata = json.loads(path.read_text(encoding="utf-8"))
        metadata["analysis"] = result.analysis
        path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2,
                                   default=_json_default), encoding="utf-8")

    def _process_impl(
        self,
        source_path: str | Path,
        progress: Callable[[int, str], None] | None = None,
        cut_inset_mm: float | None = None,
        mask_override: str | Path | None = None,
        preserve_full_image: bool = False,
        preserve_orientation: bool = False,
        mode_override: str | None = None,
        protection_zones: list | None = None,
        creation_mode: str | None = None,
        full_image_shape: str = "Rectangular",
        selected_component_ids: list[int] | None = None,
        visual_type_override: str | None = None,
        border_treatment: str | None = None,
        selection_contraction_mm: float = 0.0,
        selection_smoothing_mm: float = 0.08,
        selection_expansion_mm: float = 0.0,
        selection_protection_mask: str | Path | None = None,
        previous_object_components: list[dict] | None = None,
        cut_mask_override: str | Path | None = None,
        _run_id: str | None = None,
    ) -> ProcessingResult:
        """Orquesta el árbol de decisiones completo.

        Orden:
          1. Copiar original y analizar metadatos básicos.
          2. classify() → determina ImageCase.
          3. Aplicar máscara, intención de creación y preservación de imagen.
          4. Despachar al flujo adecuado (A / B / C / D).
          5. _postprocess() sobre la máscara resultante.
          6. Normalizar al tamaño maestro.
          7. Construir capas: borde blanco, trazo interno (si aplica), diseño.
          8. Generar artefactos: maestro, impresión, control, troquel.
          9. Control de calidad y metadata.
        """
        from pathlib import Path
        import os

        logger.debug("PIPELINE_RUNTIME_MARKER=OPAQUE_PNG_TEST_V4")
        logger.debug("PIPELINE_RUNTIME_FILE=%s", Path(__file__).resolve())
        logger.debug("PIPELINE_RUNTIME_PID=%s", os.getpid())
        logger.debug("PIPELINE_SOURCE=%s", Path(source_path).resolve())

        from PIL import Image, ImageChops, ImageFilter
        import numpy as np

        progress = progress or (lambda _p, _m: None)
        from .models import BorderTreatment
        valid_border_treatments = {item.value for item in BorderTreatment}
        if border_treatment is not None and border_treatment not in valid_border_treatments:
            raise ValueError(f"Tratamiento de borde desconocido: {border_treatment}")
        selection_contraction_mm = float(selection_contraction_mm or 0.0)
        selection_expansion_mm = float(selection_expansion_mm or 0.0)
        selection_smoothing_mm = float(selection_smoothing_mm or 0.0)
        if not 0 <= selection_contraction_mm <= 2:
            raise ValueError("La contracción debe estar entre 0 y 2 mm.")
        if not 0 <= selection_expansion_mm <= 2:
            raise ValueError("La expansión debe estar entre 0 y 2 mm.")
        if not 0 <= selection_smoothing_mm <= 1:
            raise ValueError("El suavizado debe estar entre 0 y 1 mm.")
        source_path = self.validate_source(source_path)
        valid_creation_modes = {item.value for item in CreationMode}
        resolved_creation_mode = creation_mode or CreationMode.SILHOUETTE.value
        if resolved_creation_mode not in valid_creation_modes:
            resolved_creation_mode = CreationMode.SILHOUETTE.value
        # El modo de imagen completa es una intención explícita del usuario;
        # no sustituye el clasificador ni las rutas técnicas del fondo.
        if resolved_creation_mode == CreationMode.FULL_IMAGE.value:
            preserve_full_image = True
        has_manual_mask_override = bool(mask_override and Path(mask_override).exists())
        # Current source name for diagnostics
        if getattr(self, "_diag_enabled", False):
            try:
                self._current_source_name = source_path.name
            except Exception:
                self._current_source_name = None
        job_id = _run_id or uuid.uuid4().hex
        output = self.workspace / job_id
        output.mkdir(parents=True, exist_ok=True)
        artifacts: dict[str, str] = {}
        # Prepare per-run diagnostics output dir
        if getattr(self, "_diag_enabled", False):
            try:
                self._diag_output_dir = output / "diagnostics"
                self._diag_output_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                logger.exception("Failed to create diagnostics output dir")

        # ── 1. Copiar original ────────────────────────────────────────────────
        progress(5, "Copiando original")
        original_copy = output / f"original{source_path.suffix.lower() or '.png'}"
        shutil.copy2(source_path, original_copy)
        artifacts["original"] = str(original_copy)

        # Respeta la orientación EXIF de fotos de teléfono y crea una copia
        # independiente antes de cerrar el archivo de origen.
        from PIL import ImageOps

        # ERROR 1 FIX: Verify hash to ensure correct file is loaded
        source_hash = self.file_hash(source_path)
        source_size = source_path.stat().st_size
        logger.info(f"RUN_ID={job_id}")
        logger.info(f"SOURCE={source_path.resolve()}")
        logger.info(f"SOURCE_SIZE={source_size} bytes")
        logger.info(f"SOURCE_FILE_HASH={source_hash}")

        with Image.open(source_path) as src:
            rgba = ImageOps.exif_transpose(src).convert("RGBA").copy()

        # Diagnostics: compute alpha metrics immediately after load
        if getattr(self, "_diag_enabled", False):
            try:
                alpha_loaded = rgba.getchannel("A")
                alpha_metrics = self._compute_alpha_metrics(alpha_loaded)
                diag_record = {
                    "source": str(source_path.name),
                    "stage": "loaded",
                    "alpha_metrics": alpha_metrics,
                }
                self._append_diag_record(diag_record)
            except Exception:
                logger.exception("Diagnostic: failed computing alpha metrics on load")

        # ── PNG border-only gate ───────────────────────────────────────────────
        alpha_original = rgba.getchannel("A")
        alpha_extrema = alpha_original.getextrema()

        png_border_only = self._is_png_border_only(source_path) and not preserve_full_image
        opaque_png = (
            png_border_only
            and alpha_extrema == (255, 255)
            and not has_manual_mask_override
        )

        logger.debug(
            "OPAQUE_PNG_DIRECT_GATE source=%s size=%s "
            "alpha=%s enabled=%s",
            source_path.resolve(),
            rgba.size,
            alpha_extrema,
            opaque_png,
        )

        # Verify loaded image matches source hash using pixel hash
        try:
            import numpy as np
            pixel_hash = hashlib.sha256(np.asarray(rgba).tobytes()).hexdigest()
        except (ImportError, ModuleNotFoundError):
            # Fallback without numpy
            from io import BytesIO
            buf = BytesIO()
            rgba.save(buf, format='PNG')
            pixel_hash = hashlib.sha256(buf.getvalue()).hexdigest()

        logger.info(f"PIXEL_HASH={pixel_hash}")
        logger.info(f"IMAGE_SIZE={rgba.size[0]}x{rgba.size[1]}")

        # Verify loaded image matches source hash
        loaded_temp = output / "00_source_loaded.png"
        rgba.save(loaded_temp)
        loaded_hash = self.file_hash(loaded_temp)
        logger.info(f"LOADED_FILE_HASH={loaded_hash}")

        # Log alpha for 00_source_loaded.png
        self.log_alpha("00_source_loaded.png", rgba)

        # Note: Hashes may differ slightly due to EXIF transpose, but should be consistent
        # for the actual image data. This is a sanity check for cache/path issues.
        artifacts["source_hash"] = source_hash
        artifacts["loaded_hash"] = loaded_hash
        artifacts["pixel_hash"] = pixel_hash

        # La fuente definitiva y las máscaras mantienen coordenadas originales
        # (tras EXIF). Solo los analizadores y la miniatura pueden reducirse.
        # El maestro se rasteriza después según tamaño físico/DPI del perfil.
        original_working_size = rgba.size
        processing_size = rgba.size
        # Los radios expresados en mm se convierten en píxeles de la fuente,
        # no en píxeles del maestro reducido. Las rutas A/B/C/D no cambian.
        source_effective_dpi = max(rgba.size) * 2.54 / self.profile.resolved_content_size_cm
        # Reutiliza la imagen que ya está en memoria. Antes se abría y
        # decodificaba el archivo una segunda vez sólo para el análisis.
        analysis = self._analyze_rgba(rgba, original_working_size)
        progress(10, f"Análisis: {analysis.engine}")
        png_closed_holes = (
            source_path.suffix.lower() == ".png"
            and self._closed_interior_mask(rgba.getchannel("A")).getbbox() is not None
        )

        # ── 2. Clasificar ─────────────────────────────────────────────────────
        progress(13, "Clasificando imagen")
        if has_manual_mask_override:
            # Una forma personalizada tiene prioridad incluso dentro del modo
            # de imagen completa: la máscara editada es la decisión explícita.
            with Image.open(mask_override) as m:
                manual_mask_original_size = m.size
                ov_alpha = m.convert("L").resize(rgba.size,
                                                  Image.Resampling.LANCZOS)
            rgba.putalpha(ov_alpha)
            classify_result = ClassifyResult(
                case=ImageCase.A,
                design_mode="Color uniforme",
                reasons=["mask_override proporcionado"],
                has_transparency=True,
                has_white_border=False,
                has_grey_border=False,
                has_black_outline=False,
                uniform_background=False,
                is_photo=False,
                bg_color=(0, 0, 0),
            )
        elif preserve_full_image:
            # Caso especial: conservar el recorte elegido por el usuario. Si
            # fue rotado, sus esquinas ya son transparentes; no se las debe
            # rellenar porque el borde debe seguir el rectángulo inclinado.
            classify_result = ClassifyResult(
                case=ImageCase.A,
                design_mode="Color uniforme",
                reasons=["preserve_full_image=True"],
                has_transparency=True,
                has_white_border=False,
                has_grey_border=False,
                has_black_outline=False,
                uniform_background=False,
                is_photo=False,
                bg_color=(0, 0, 0),
            )
        else:
            classify_result = self.classify(rgba, mode_override=mode_override)

        # Las vías explícitas (máscara o imagen completa) omiten classify(),
        # pero siguen conservando su diagnóstico visual para la revisión.
        if not classify_result.classification_features:
            alpha_for_features = rgba.getchannel("A")
            alpha_min_for_features = alpha_for_features.getextrema()[0]
            feature_bg = (0, 0, 0)
            classification_features, secondary_types = self._classification_features(
                rgba,
                useful_alpha=alpha_min_for_features < 255,
                has_white_border=False,
                has_grey_border=False,
                uniform_background=False,
                bg_color=feature_bg,
                is_photo=False,
            )
            classify_result.classification_features = classification_features
            classify_result.detected_types = secondary_types

        if resolved_creation_mode == CreationMode.FULL_IMAGE.value:
            classify_result.sticker_type = "imagen_completa"
            classify_result.sticker_type_label = VISUAL_STICKER_TYPE_LABELS["imagen_completa"]
            classify_result.detected_types = [
                "imagen_completa", *(
                    item for item in classify_result.detected_types
                    if item != "imagen_completa")]
            classify_result.reasons.insert(0, "Tipo: Diseño completo para sticker")
        elif visual_type_override and visual_type_override in VISUAL_STICKER_TYPE_LABELS:
            classify_result.sticker_type = visual_type_override
            classify_result.sticker_type_label = VISUAL_STICKER_TYPE_LABELS[visual_type_override]
            classify_result.detected_types = [
                visual_type_override, *(
                    item for item in classify_result.detected_types
                    if item != visual_type_override)]
            classify_result.reasons.insert(
                0, f"Tipo corregido manualmente: {classify_result.sticker_type_label}")

        progress(16, f"Caso {classify_result.case.value}")

        # Diagnostic logging after classification
        alpha_ch = rgba.getchannel("A")
        alpha_min, alpha_max = alpha_ch.getextrema()
        useful_alpha = alpha_min < 255
        has_real_transparency = alpha_min < 255

        logger.info(
            "PROCESS POST-CLASSIFICATION: modo=%s, alpha_min=%d, alpha_max=%d, useful_alpha=%s, has_real_transparency=%s, "
            "case=%s, reasons=%s",
            rgba.mode, alpha_min, alpha_max, useful_alpha, has_real_transparency,
            classify_result.case.value, classify_result.reasons
        )

        # Diagnostics: write a single parseable classification line
        if getattr(self, "_diag_enabled", False):
            try:
                white_ratio = None
                grey_ratio = None
                try:
                    import numpy as np
                    a_arr = np.asarray(alpha_ch.resize((128, 128)), dtype=np.uint8)
                    rgb_small = rgba.convert("RGB").resize((128, 128))
                    rgb_arr = np.asarray(rgb_small, dtype=np.uint8)
                    opaque = (a_arr > 127)
                    white_px = opaque & (rgb_arr[:, :, 0] > 210) & (rgb_arr[:, :, 1] > 210) & (rgb_arr[:, :, 2] > 210)
                    white_ratio = float(white_px.sum()) / max(1, int(opaque.sum()))
                    r, g, b = rgb_arr[:, :, 0], rgb_arr[:, :, 1], rgb_arr[:, :, 2]
                    neutral = (np.abs(r.astype(int) - g.astype(int)) < 30) & (np.abs(g.astype(int) - b.astype(int)) < 30)
                    grey_px = opaque & neutral & (r > 100) & (r < 215)
                    grey_ratio = float(grey_px.sum()) / max(1, int(opaque.sum()))
                except Exception:
                    pass
                classify_line = {
                    "source": str(source_path.name),
                    "stage": "classify",
                    "case": classify_result.case.value,
                    "reasons": classify_result.reasons,
                    "useful_alpha": bool(useful_alpha),
                    "alpha_extrema": (int(alpha_min), int(alpha_max)),
                    "white_ratio": float(white_ratio) if white_ratio is not None else None,
                    "grey_ratio": float(grey_ratio) if grey_ratio is not None else None,
                }
                self._append_diag_record(classify_line)
            except Exception:
                logger.exception("Diagnostics: failed writing classify line")

        # ── 3. Despachar al flujo correspondiente ─────────────────────────────
        # Regla global: todo PNG debe tratarse como border-only y nunca como
        # extracción destructiva del fondo.  El arte original queda intacto y se
        # añade el borde alrededor del contenido.
        if png_border_only:
            # La ruta PNG solo cambia el tratamiento del borde; no debe
            # borrar señales válidas de clasificación como un contorno negro.
            classify_result = replace(
                classify_result,
                reasons=[*classify_result.reasons, "PNG: borde sin tocar artwork"],
            )

        case = classify_result.case

        border_analysis = self.analyze_original_border_structure(rgba)
        logger.info(
            "BORDER ANALYSIS: mode=%s, border_distinguishable=%s, bg_color=%s",
            border_analysis.get("mode"), border_analysis.get("border_distinguishable"),
            border_analysis.get("bg_color")
        )
        border_mode = border_analysis["mode"]

        # Construir máscara de protección en coordenadas de la imagen fuente
        prot_mask = None
        if protection_zones:
            prot_mask = self._build_protection_mask(rgba.size, protection_zones)

        # ── OPAQUE PNG DIRECT ROUTE ─────────────────────────────────────────────
        source_has_existing_white_border = False
        checkerboard_sticker = False
        complex_background_unresolved = False
        background_refinement = {}
        checkerboard_review = {}
        if opaque_png:
            progress(20, "PNG opaco: eliminando fondo integrado")

            # Los stickers de catálogo suelen venir sobre un fondo gris claro
            # con sombra suave. El flood fill por distancia de color deja esa
            # sombra como parte de la silueta y genera bultos en el borde.
            # Primero atravesamos únicamente los neutros exteriores; el
            # flood fill clásico queda como respaldo para fondos no neutros.
            # Un PNG de catálogo puede ser opaco tanto sobre gris como sobre
            # blanco puro. El algoritmo de neutros grises conservaría parte
            # del blanco exterior como si fuera arte y ensancharía la base.
            corners = [
                rgba.convert("RGB").getpixel((0, 0)),
                rgba.convert("RGB").getpixel((rgba.width - 1, 0)),
                rgba.convert("RGB").getpixel((0, rgba.height - 1)),
                rgba.convert("RGB").getpixel((rgba.width - 1, rgba.height - 1)),
            ]
            corner_luminance = sum(
                0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
                for color in corners
            ) / len(corners)
            raw_alpha = self._checkerboard_exterior_alpha(rgba)
            if raw_alpha is not None:
                colorful_alpha = self._colorful_foreground_alpha(rgba)
                if colorful_alpha is not None:
                    # Un objeto cromático (por ejemplo un corazón) se separa
                    # mejor por pigmento que por el blanco de una captura.
                    # Recuperamos solo la corona necesaria para su borde
                    # original y marcamos el asset como ya terminado: no se
                    # agrega una segunda corona de producción más gruesa.
                    raw_alpha = self._expand(colorful_alpha, 5)
                    checkerboard_sticker = True
                else:
                    # Keep the stable two-pixel refinement. Wider neutral-rim
                    # removal failed conservation regression; do not erase art
                    # to make the contact sheet look smoother.
                    candidate = self._refine_checkerboard_alpha(rgba, raw_alpha)
                    # Retain the rejected wider proposal for manual comparison;
                    # it is never substituted for the stable silhouette.
                    for key, mask in (("checkerboard_initial_alpha", raw_alpha),
                                      ("checkerboard_segmentation_candidate", candidate)):
                        candidate_path = output / f"{key}.png"
                        mask.save(candidate_path)
                        artifacts[key] = str(candidate_path)
                    checkerboard_review = {"status": "manual_required",
                                           "applied": "stable_two_pixel_refinement",
                                           "wider_candidate_selected": False}
                    raw_array = np.asarray(raw_alpha, dtype=np.uint8)
                    import cv2
                    distance = cv2.distanceTransform((raw_array > 12).astype(np.uint8), cv2.DIST_L2, 5)
                    refined_array = np.asarray(candidate, dtype=np.uint8)
                    raw_alpha = Image.fromarray(np.where(
                        (distance > 0) & (distance <= 2),
                        np.minimum(raw_array, refined_array), raw_array).astype(np.uint8))
                    # Es un sticker neutro ya preparado visto sobre el damero
                    # de una interfaz: conservar su borde evita duplicarlo.
                    checkerboard_sticker = True
                logger.info("OPAQUE_PNG_DIRECT_MASK: checkerboard background removed")
            elif corner_luminance >= 235.0:
                raw_alpha = self._uniform_background_alpha(rgba, tolerance=35)
            else:
                raw_alpha = self._light_neutral_exterior_alpha(
                    rgba, shadow_depth=60, bright_stop=6)
            if not checkerboard_sticker:
                rgb_frame = np.asarray(rgba.convert("RGB"), dtype=np.int16)
                frame = np.concatenate((rgb_frame[0], rgb_frame[-1], rgb_frame[:,0], rgb_frame[:,-1]))
                # Do not silently call a multicolored perimeter uniform. Keep
                # the extraction for review rather than inventing a subject.
                spread = np.percentile(frame, 90, axis=0) - np.percentile(frame, 10, axis=0)
                complex_background_unresolved = bool(spread.max() > 45)
                if complex_background_unresolved:
                    from .background_refinement import variable_background_proposal
                    initial_mask_path = output / "background_initial_alpha.png"
                    raw_alpha.save(initial_mask_path)
                    artifacts["background_initial_alpha"] = str(initial_mask_path)
                    proposal, background_refinement, candidates = variable_background_proposal(self, rgba, progress)
                    for index, candidate in enumerate(candidates):
                        candidate_path = output / f"background_candidate_{index+1}.png"
                        candidate.save(candidate_path)
                        artifacts[f"background_candidate_{index+1}"] = str(candidate_path)
                    if proposal is not None:
                        raw_alpha = proposal
            if raw_alpha.getextrema() == (255, 255):
                raw_alpha = self._remove_integrated_background_flood_fill(
                    rgba,
                    tolerance=25,
                )

            logger.debug(
                "OPAQUE_PNG_DIRECT_MASK extrema=%s bbox=%s",
                raw_alpha.getextrema(),
                raw_alpha.getbbox(),
            )

            if raw_alpha.getextrema() == (255, 255):
                raise RuntimeError(
                    "La ruta directa de PNG opaco no eliminó el fondo"
                )

            source_has_existing_white_border = (
                checkerboard_sticker
                or self._has_white_outer_border(rgba, raw_alpha, threshold=.55))

            prepared_rgba = rgba.copy()
            prepared_rgba.putalpha(raw_alpha)

            debug_path = output / "OPAQUE_PNG_DIRECT_RESULT.png"
            prepared_rgba.save(debug_path, "PNG")

            with Image.open(debug_path) as check:
                check_alpha = check.convert("RGBA").getchannel("A").getextrema()

            logger.debug(
                "OPAQUE_PNG_DIRECT_RESULT path=%s alpha=%s",
                debug_path.resolve(),
                check_alpha,
            )

            if check_alpha == (255, 255):
                raise RuntimeError(
                    "La máscara se perdió al crear el resultado directo"
                )

            # Forzar classify_result para continuar con el resto del pipeline
            classify_result = replace(classify_result,
                case=ImageCase.C,
                design_mode="Color uniforme",
                reasons=["PNG opaco con fondo integrado detectado"],
                has_transparency=False,
                has_white_border=False,
                has_grey_border=False,
                has_black_outline=False,
                uniform_background=True,
                is_photo=False,
                bg_color=(0, 0, 0),
            )
        else:
            # ── Normal flow dispatch ─────────────────────────────────────────────
            if png_border_only and not has_real_transparency:
                prepared_rgba = self._generate_non_destructive_border(rgba, border_px=max(4, self.profile.final_white_px))
            elif case == ImageCase.B:
                prepared_rgba = self._flow_b(rgba, classify_result, progress)
            elif case == ImageCase.D:
                prepared_rgba = self._flow_d(rgba, classify_result, progress)
            elif case == ImageCase.C:
                prepared_rgba = self._flow_c(rgba, classify_result, progress)
            else:
                prepared_rgba = self._flow_a(
                    rgba, classify_result, progress,
                    fill_closed_holes=False,
                )

        if has_real_transparency and not has_manual_mask_override and not preserve_full_image:
            # Visual alpha (including holes) is not the solid white substrate.
            prepared_rgba = self.clean_hidden_rgb(rgba.copy())
            source_has_existing_white_border = classify_result.has_white_border

        # Restaurar zonas protegidas que el flujo pudo haber eliminado
        if prot_mask is not None:
            raw_alpha_pre = self._apply_protection(
                prepared_rgba.getchannel("A"), prot_mask)
            prepared_rgba.putalpha(raw_alpha_pre)

        progress(46, "Postprocesando máscara")
        extraction_reference = prepared_rgba.getchannel("A").copy()
        if not has_real_transparency and not has_manual_mask_override and not preserve_full_image:
            recovery_mask_path = output / "mask_recovery_raw.png"
            extraction_reference.save(recovery_mask_path, optimize=False)
            artifacts["mask_recovery_raw"] = str(recovery_mask_path)

        # ── 4. Postprocesado unificado ────────────────────────────────────────
        # Validación antes del postprocesado para PNG opaco
        logger.debug(
            "BEFORE_POSTPROCESS opaque_png=%s raw_alpha=%s",
            opaque_png,
            prepared_rgba.getchannel("A").getextrema(),
        )

        if opaque_png and prepared_rgba.getchannel("A").getextrema() == (255, 255):
            raise RuntimeError(
                "El alfa del PNG opaco fue sobrescrito antes del postprocesado"
            )

        # Initialize variables to avoid UnboundLocalError
        white_border_before = 0
        preserve_existing_white_source = False

        # Para PNG opaco, saltar postprocesado normal
        if opaque_png:
            raw_alpha = prepared_rgba.getchannel("A")
            refined_alpha = raw_alpha
            postprocess_meta = {
                "holes_detected": 0,
                "holes_filled": 0,
                "hole_analysis": [],
                "removed_particles_count": 0,
                "removed_particles": [],
            }
        else:
            raw_alpha = prepared_rgba.getchannel("A")
            bbox_check = raw_alpha.point(lambda v: 255 if v > 12 else 0).getbbox()
            if not bbox_check:
                raise ValueError("No se pudo separar el diseño del fondo.")

            # ERROR 3 FIX: Validation assertions for white border preservation
            # Ensure alpha has proper transparency range
            alpha_arr = np.asarray(raw_alpha, dtype=np.uint8)
            alpha_min, alpha_max = alpha_arr.min(), alpha_arr.max()

            logger.info(
                "VALIDATION: alpha_min=%d, alpha_max=%d, transparent_pixels=%d",
                alpha_min, alpha_max, (alpha_arr == 0).sum()
            )

            # Una selección rectangular es deliberadamente opaca: su borde se
            # agrega después, al construir la base blanca. Las demás entradas
            # todavía deben tener transparencia tras la extracción.
            if not preserve_full_image:
                assert alpha_min < 255, (
                    f"Alpha should have transparent pixels (min={alpha_min})")

            # ASSERTION: Alpha should have opaque areas (max == 255)
            assert alpha_max > 0, f"Alpha should have visible pixels (max={alpha_max})"

            # VALIDATION: Verify white pixels on the outer alpha edge remain opaque.
            # This avoids false warnings from white artwork inside the sticker.
            rgb_arr = np.asarray(rgba.convert("RGB"), dtype=np.uint8)
            white_pixels = (rgb_arr[:, :, 0] > 200) & (rgb_arr[:, :, 1] > 200) & (rgb_arr[:, :, 2] > 200)
            if white_pixels.sum() > 0:
                from PIL import ImageChops
                raw_solid = raw_alpha.convert("L").point(lambda v: 255 if v > 127 else 0)
                raw_edge = np.asarray(
                    ImageChops.subtract(raw_solid, self._contract(raw_solid, 3)),
                    dtype=np.uint8,
                ) > 0
                edge_white_pixels = white_pixels & raw_edge
                if edge_white_pixels.sum() > 0:
                    white_alpha = alpha_arr[edge_white_pixels]
                    white_opaque_ratio = (white_alpha > 127).sum() / edge_white_pixels.sum()
                    logger.info(f"White border preservation ratio: {white_opaque_ratio:.2%}")
                    # Log warning only when the outer border edge is actually present.
                    if white_opaque_ratio < 0.7:
                        logger.warning(
                            f"White border may not be fully preserved: {white_opaque_ratio:.2%} opaque"
                        )

            debug_raw_mask = raw_alpha.convert("L").point(lambda v: 255 if v > 12 else 0)
            debug_raw_mask_path = output / "01_alpha_raw.png"
            debug_raw_mask.save(debug_raw_mask_path, dpi=(self.profile.dpi,)*2,
                                optimize=False)
            artifacts["mask_segmentation_raw"] = str(debug_raw_mask_path)

            # Log alpha for 01_alpha_raw.png
            self.log_alpha("01_alpha_raw.png", debug_raw_mask)

            preserve_existing_white_source = (
                border_mode == BorderMode.PRESERVE_EXISTING_BORDER
            )
            white_border_before = self._white_outer_border_pixels(rgba, raw_alpha)

            skip_postprocessing = (
                (case == ImageCase.A and not preserve_full_image)
                or preserve_existing_white_source
                or border_mode == BorderMode.AMBIGUOUS_WHITE_ON_WHITE
            )

            # ── Etapa 2A: reconstruir base blanca desplazada ──────────────────
            rebuild_white_base = False
            if border_mode == BorderMode.AMBIGUOUS_WHITE_ON_WHITE:
                import numpy as np
                _rgb = np.array(rgba.convert("RGB"), dtype=np.uint8)
                _alpha = np.array(raw_alpha, dtype=np.uint8)
                _wb = self._measure_white_base(_rgb, _alpha)
                if (_wb["coverage_ratio"] < 0.95
                        and (_wb["missing_ratio"] > 0.05
                             or _wb["excess_ratio"] > 0.10)):
                    rebuild_white_base = True
                    target_r = self.profile.final_white_px
                    raw_alpha = self._rebuild_displaced_white_base(
                        _rgb, _alpha, target_r)
                    prepared_rgba.putalpha(raw_alpha)
                    logger.info(
                        "Etapa 2A: base blanca reconstruida para %s "
                        "(coverage=%.2f, missing=%.2f, excess=%.2f)",
                        source_path.name,
                        _wb["coverage_ratio"],
                        _wb["missing_ratio"],
                        _wb["excess_ratio"],
                    )

            if skip_postprocessing:
                refined_alpha = raw_alpha
                postprocess_meta = {
                    "holes_detected": 0,
                    "holes_filled": 0,
                    "hole_analysis": [],
                    "removed_particles_count": 0,
                    "removed_particles": [],
                }
            else:
                # CORRECCIÓN 3-4: Para PNG con transparencia real, skip_all_morphology
                # para preservar el alfa original sin modificaciones
                refined_alpha, postprocess_meta = self._postprocess(
                raw_alpha, source_effective_dpi,
                fill_holes=False,  # CORRECCIÓN 4: desactivado para evitar redondeo
                skip_corner_rounding=source_path.suffix.lower() == ".png",
                skip_all_morphology=has_real_transparency and not opaque_png,  # CORRECCIÓN 3
            )

        # ── Etapa 2B: eliminar ruido gris aislado ────────────────────────
        # TEMPORARILY DISABLED: Removing grey noise was deleting light grey design elements
        grey_noise_log = []
        if False and border_mode == BorderMode.AMBIGUOUS_WHITE_ON_WHITE:
            _rgb2 = np.array(rgba.convert("RGB"), dtype=np.uint8)
            refined_alpha, grey_noise_log = self._remove_grey_noise(
                refined_alpha, _rgb2)

        # Una selección completa conserva su alfa original. Normalmente será
        # un rectángulo opaco; una selección rotada incluye esquinas
        # transparentes que son necesarias para que el borde no vuelva a una
        # caja rectangular.

        # También se aplica a casos que omiten el postprocesado (por ejemplo,
        # PNG ya preparados): de otro modo un fragmento aislado llega intacto
        # al PNG final aunque la interfaz lo haya detectado como sospechoso.
        if has_manual_mask_override:
            # Las decisiones manuales prevalecen sobre limpieza, relleno de
            # huecos y eliminación de componentes de los modos automáticos.
            refined_alpha = ov_alpha.copy()
        object_components: list[dict] = []
        object_selection_warning = ""
        if (not preserve_full_image and not has_manual_mask_override
                and background_refinement.get("status") != "proposal_requires_review"
                and resolved_creation_mode != CreationMode.MULTI_OBJECT.value):
            refined_alpha, removed_detached = self._remove_isolated_components(
                refined_alpha, prot_mask)
        else:
            removed_detached = []
        postprocess_meta["removed_detached_components"] = removed_detached

        # Restaurar zonas protegidas que el postprocesado pudo haber tocado
        if prot_mask is not None:
            refined_alpha = self._apply_protection(refined_alpha, prot_mask)

        # Una selección completa y opaca es una decisión explícita del
        # usuario: no debe adquirir transparencia por la ruta de análisis o
        # por el tratamiento del borde. Las selecciones rotadas conservan sus
        # esquinas transparentes originales.
        if (preserve_full_image and not has_manual_mask_override
                and rgba.getchannel("A").getextrema()[0] == 255):
            refined_alpha = Image.new("L", rgba.size, 255)

        # Los cortes circular y ovalado se aplican tras conservar la imagen
        # completa. No hay deformación: únicamente se ajusta el alfa.
        if (resolved_creation_mode == CreationMode.FULL_IMAGE.value
                and not has_manual_mask_override):
            shape_alpha = self._full_image_shape_alpha(
                rgba.size, full_image_shape)
            if shape_alpha is not None:
                refined_alpha = ImageChops.multiply(refined_alpha, shape_alpha)

        # El modo de múltiples objetos no borra piezas alejadas. Conserva una
        # máscara independiente por componente para que el usuario pueda usar
        # todos juntos o elegir sus identificadores al reprocesar.
        if resolved_creation_mode == CreationMode.MULTI_OBJECT.value:
            progress(46, "Separando objetos detectados")
            component_masks = self._split_foreground_components(refined_alpha)
            from .objects import match_object_ids
            component_ids, ambiguous_ids = match_object_ids(
                [item[2] for item in component_masks], previous_object_components)
            if ambiguous_ids:
                object_selection_warning = "Cambió la correspondencia de objetos; revisá los IDs antes de confirmar."
            wanted_components = {
                int(identifier) for identifier in (selected_component_ids or [])
                if isinstance(identifier, int) or str(identifier).isdigit()
            }
            valid_wanted_components = {
                identifier for identifier in wanted_components
                if identifier in component_ids
            }
            if wanted_components and not valid_wanted_components:
                object_selection_warning = (
                    "Los IDs de objetos indicados no existen; se conservaron todos.")
            keep_all_components = not wanted_components or not valid_wanted_components
            selected_alpha = Image.new("L", refined_alpha.size, 0)
            for index, (area, bbox, component_mask) in zip(component_ids, component_masks):
                mask_path = output / f"object_mask_{index:02d}.png"
                component_mask.save(mask_path, dpi=(self.profile.dpi,) * 2,
                                    optimize=False)
                artifacts[f"object_mask_{index}"] = str(mask_path)
                object_components.append({
                    "id": index,
                    "area_px": area,
                    "bbox": list(bbox),
                    "artifact": str(mask_path),
                    "selected": (keep_all_components
                                 or index in valid_wanted_components),
                })
                if keep_all_components or index in valid_wanted_components:
                    selected_alpha = ImageChops.lighter(selected_alpha, component_mask)
            if component_masks and valid_wanted_components:
                refined_alpha = selected_alpha

        reference_binary = np.asarray(extraction_reference) > 12
        refined_binary = np.asarray(refined_alpha) > 12
        extracted_area_loss = float((reference_binary & ~refined_binary).sum() / max(int(reference_binary.sum()), 1))
        del reference_binary, refined_binary, extraction_reference
        white_border_after = self._white_outer_border_pixels(rgba, refined_alpha)
        white_border_loss = 1 - (white_border_after / max(white_border_before, 1))

        prepared_rgba.putalpha(refined_alpha)
        # A narrow existing white rim can be missed by the coarse visual
        # classifier. Trust real alpha plus a white exterior around coloured
        # content; this only controls rendering, never changes A/B/C/D.
        if has_real_transparency and not has_manual_mask_override and not preserve_full_image:
            from .halo_geometry import confirmed_white_border
            if confirmed_white_border(prepared_rgba, refined_alpha):
                source_has_existing_white_border = True
                preserve_existing_white_source = True
        # Complementary operation, independent of A/B/C/D. It never renders
        # white: the existing downstream renderer remains the single owner.
        from .grey_halo_decontamination import decontaminate_exterior
        halo_metadata = {"evaluated": False, "status": "not_applicable"}
        halo_eligible = (not has_manual_mask_override and not preserve_full_image
                         and not selected_component_ids
                         and not (has_real_transparency and not classify_result.has_grey_border
                                  and not preserve_existing_white_source))
        if halo_eligible:
            halo_initial = refined_alpha.copy()
            prepared_rgba, refined_alpha, halo_metadata, halo_region, original_white = decontaminate_exterior(
                prepared_rgba, refined_alpha,
                existing_border=bool(preserve_existing_white_source or source_has_existing_white_border),
                checkerboard=bool(checkerboard_review or checkerboard_sticker),
                suspected_halo=bool(classify_result.has_grey_border),
                protected_mask=prot_mask)
            for key, layer in (("halo_mask_initial", halo_initial),
                               ("halo_region", halo_region),
                               ("halo_mask_clean", refined_alpha),
                               ("halo_original_white_border", original_white),
                               ("halo_before_printable_border", prepared_rgba)):
                path = output / f"{key}.png"
                layer.save(path, optimize=False)
                artifacts[key] = str(path)

        # Política explícita de borde, común a A/B/C/D. El modo automático
        # conserva el comportamiento histórico; las tres decisiones manuales
        # sólo controlan el borde y nunca reclasifican la imagen.
        border_treatment_metadata = {
            "requested": border_treatment,
            "effective": "Automático",
            "requires_review": False,
            "reason": None,
            "existing_border_detected": bool(
                preserve_existing_white_source or source_has_existing_white_border),
        }
        if border_treatment == BorderTreatment.PRESERVE_CLEAN.value:
            source_has_existing_white_border = True
            preserve_existing_white_source = True
            border_treatment_metadata["effective"] = BorderTreatment.PRESERVE_CLEAN.value
        elif border_treatment == BorderTreatment.REPLACE.value:
            if halo_metadata.get("requires_review"):
                replacement_alpha = refined_alpha.copy()
                replacement_meta = {
                    "applied": False, "requires_review": True,
                    "reason": "ambiguous_halo_blocks_automatic_replacement",
                    "removed_pixels": 0,
                }
            else:
                replacement_alpha, replacement_meta = self._remove_existing_white_border_for_replacement(
                    prepared_rgba, refined_alpha,
                    max_depth_px=max(12, round(self.profile.final_white_px * 1.6)))
            border_treatment_metadata.update(replacement_meta)
            border_treatment_metadata["effective"] = BorderTreatment.REPLACE.value
            if replacement_meta["applied"]:
                refined_alpha = replacement_alpha
                prepared_rgba.putalpha(refined_alpha)
                source_has_existing_white_border = False
                preserve_existing_white_source = False
            else:
                # Fallo seguro: conservar el borde, no apilar otro encima.
                border_treatment_metadata["effective"] = BorderTreatment.PRESERVE_CLEAN.value
                source_has_existing_white_border = True
                preserve_existing_white_source = True
        elif border_treatment == BorderTreatment.ADD.value:
            from .halo_geometry import confirmed_white_border
            if (source_has_existing_white_border or preserve_existing_white_source
                    or confirmed_white_border(prepared_rgba, refined_alpha)):
                border_treatment_metadata.update(
                    effective=BorderTreatment.PRESERVE_CLEAN.value,
                    requires_review=True,
                    reason="existing_or_ambiguous_border_blocks_addition")
                source_has_existing_white_border = True
                preserve_existing_white_source = True
            else:
                border_treatment_metadata["effective"] = BorderTreatment.ADD.value
                source_has_existing_white_border = False
                preserve_existing_white_source = False

        border_treatment_mask_path = output / "border_treatment_alpha.png"
        refined_alpha.save(border_treatment_mask_path, optimize=False)
        artifacts["border_treatment_alpha"] = str(border_treatment_mask_path)

        # Etapa compartida A/B/C/D: siempre parte de la máscara base de esta
        # corrida. No reutiliza una máscara ya contraída ni toca los colores.
        selection_base_alpha = refined_alpha.copy()
        selection_base_path = output / "selection_alpha_original.png"
        shutil.copy2(border_treatment_mask_path, selection_base_path)
        artifacts["selection_alpha_original"] = str(selection_base_path)
        from .mask_contraction import offset_alpha_signed_distance
        selection_offset_mm = selection_contraction_mm - selection_expansion_mm
        contracted_alpha, contraction_report = offset_alpha_signed_distance(
            selection_base_alpha, selection_offset_mm,
            source_effective_dpi, selection_smoothing_mm)
        if selection_protection_mask and Path(selection_protection_mask).is_file():
            with Image.open(selection_protection_mask) as protected_source:
                protected_alpha = protected_source.convert("L")
            if protected_alpha.size != selection_base_alpha.size:
                protected_alpha = protected_alpha.resize(
                    selection_base_alpha.size, Image.Resampling.LANCZOS)
            protection = np.asarray(protected_alpha, dtype=np.float32) / 255.0
            adjusted = np.asarray(contracted_alpha, dtype=np.float32)
            baseline = np.asarray(selection_base_alpha, dtype=np.float32)
            contracted_alpha = Image.fromarray(np.rint(
                adjusted * (1-protection) + baseline * protection
            ).astype(np.uint8), "L")
            protection_path = output / "selection_protection.png"
            protected_alpha.save(protection_path, optimize=False)
            artifacts["selection_protection"] = str(protection_path)
        refined_alpha = contracted_alpha
        prepared_rgba.putalpha(refined_alpha)
        contracted_path = output / "selection_alpha_contracted.png"
        refined_alpha.save(contracted_path, optimize=False)
        artifacts["selection_alpha_contracted"] = str(contracted_path)
        # En JPG con fondo gris claro puede sobrevivir una línea gris dentro
        # del margen blanco. No pertenece al dibujo: se limpia únicamente en
        # la corona exterior, antes de crear el trazo final.
        # El blanqueo del halo solo corresponde a fondos neutros oscuros o
        # grises. Sobre fondo blanco convertiría en blanco los reflejos
        # plateados, trazos grisáceos y acuarelas muy claras del propio arte.
        source_perimeter_luminance = float(
            border_analysis.get("perimeter_luminance", 0.0))
        if ((case == ImageCase.C and classify_result.uniform_background
             and source_perimeter_luminance < 235.0)
                or (has_real_transparency
                    and source_path.suffix.lower() == ".png")):
            prepared_rgba = self._whiten_neutral_outer_halo(prepared_rgba, refined_alpha)
            prepared_rgba.putalpha(refined_alpha)

        # Guardar la máscara binaria básica justo después de la extracción y
        # antes de construir la base blanca.
        intermediate_mask = refined_alpha.convert("L").point(
            lambda v: 255 if v > 12 else 0)
        intermediate_mask_path = output / "02_after_flow_c.png"
        intermediate_mask.save(intermediate_mask_path,
                               dpi=(self.profile.dpi,)*2,
                               optimize=False)
        artifacts["mask_intermediate"] = str(intermediate_mask_path)

        # Log alpha for 02_after_flow_c.png
        self.log_alpha("02_after_flow_c.png", intermediate_mask)

        # ── 5. Add padding for integrated backgrounds before cropping ──────────
        # Edición en coordenadas de trabajo, antes del padding de producción.
        # Se expone siempre la base previa a la contracción para que editar y
        # reprocesar no vuelva a contraer un resultado ya desplazado.
        editable_mask_path = output / "mask_editable.png"
        shutil.copy2(selection_base_path, editable_mask_path)
        artifacts["mask_editable"] = str(editable_mask_path)
        editable_source_path = output / "source_editable.png"
        shutil.copy2(loaded_temp, editable_source_path)
        artifacts["source_editable"] = str(editable_source_path)
        progress(48, "Verificando necesidad de padding transparente")
        # Check if we need to add padding for integrated backgrounds
        has_transparency, has_integrated_bg = self._has_real_transparency(rgba)
        if (not preserve_full_image and
                (has_integrated_bg or (case == ImageCase.C and classify_result.uniform_background))):
            progress(49, "Agregando padding transparente para preservar borde blanco")
            prepared_rgba = self._add_transparent_padding(
                prepared_rgba, padding_px=self.profile.transparent_padding_px)
            refined_alpha = prepared_rgba.getchannel("A")
            from PIL import ImageOps
            padding = max(40, min(60, self.profile.transparent_padding_px))
            selection_base_alpha = ImageOps.expand(
                selection_base_alpha, border=padding, fill=0)

        # ── 6. Recortar, rotar a vertical y guardar intermedios ───────────────
        progress(50, "Recortando y orientando con margen de seguridad")
        # Use safe crop with margin to preserve white border
        # El PNG transparente ya trae una silueta fiable: recortarlo al
        # contenido evita convertir su padding accidental en parte del asset.
        # Las selecciones completas conservan el margen de seguridad porque
        # pueden incluir un encuadre o esquinas transparentes deliberadas.
        safety_margin = 0 if has_real_transparency and not preserve_full_image else 15
        clean = self._safe_crop_with_margin(
            prepared_rgba, selection_base_alpha, safety_margin_px=safety_margin)
        clean_alpha = clean.getchannel("A")
        shape_type = self._shape_type(clean_alpha)

        # La orientación vertical es la norma de producción. Solo se conserva
        # explícitamente cuando el usuario trabajó una selección deliberada.
        # Rotar únicamente los formatos claramente apaisados. Una diferencia
        # mínima aparece a menudo por el recorte de un borde irregular y no
        # debe girar un sticker prácticamente cuadrado.
        should_rotate = (
            clean.width / max(clean.height, 1) >= 1.20
            and not preserve_orientation
        )
        rotated_to_vertical = should_rotate

        if rotated_to_vertical:
            clean = clean.transpose(Image.Transpose.ROTATE_270)
            clean_alpha = clean_alpha.transpose(Image.Transpose.ROTATE_270)

        clean_path = output / "03_postprocessed_alpha.png"
        clean.save(clean_path, dpi=(self.profile.dpi,)*2, optimize=False)
        artifacts["clean"] = str(clean_path)

        # Log alpha for 03_postprocessed_alpha.png
        self.log_alpha("03_postprocessed_alpha.png", clean)

        mask_path = output / "04_mask.png"
        refined_alpha.save(mask_path, dpi=(self.profile.dpi,)*2, optimize=False)
        artifacts["mask"] = str(mask_path)

        # Log alpha for 04_mask.png
        self.log_alpha("04_mask.png", refined_alpha)

        cropped_mask_path = output / "05_mask_cropped.png"
        clean_alpha.save(cropped_mask_path, dpi=(self.profile.dpi,)*2,
                         optimize=False)
        artifacts["mask_cropped"] = str(cropped_mask_path)

        silhouette_path = output / "06_silhouette.png"
        clean.save(silhouette_path, dpi=(self.profile.dpi,)*2, optimize=False)
        artifacts["silhouette"] = str(silhouette_path)

        # Log alpha for 06_silhouette.png
        self.log_alpha("06_silhouette.png", clean)

        # ── 6. Normalizar al tamaño maestro ──────────────────────────────────
        progress(54, "Normalizando al maestro")
        master_px = self.profile.master_pixels
        reserved = self.profile.final_white_px + self.profile.control_black_px + 4
        exact_content_px = master_px - reserved * 2
        requested_px = round(
            self.profile.resolved_content_size_cm / 2.54 * self.profile.dpi)
        content_px = min(requested_px, exact_content_px)
        scale = min(content_px / clean.width, content_px / clean.height)
        csz = (max(1, round(clean.width * scale)),
               max(1, round(clean.height * scale)))

        # RGBa informa a Pillow que el color ya está premultiplicado.
        # Sustituye el resultado legacy que premultiplicaba dos veces en RGBA.
        scaled = clean.convert("RGBa").resize(
            csz, Image.Resampling.LANCZOS).convert("RGBA")
        c_alpha = scaled.getchannel("A")

        canvas = Image.new("RGBA", (master_px, master_px), (0, 0, 0, 0))
        offset = ((master_px - scaled.width) // 2,
                  (master_px - scaled.height) // 2)
        canvas.alpha_composite(scaled, offset)

        # Construir la base blanca sólida con puentes entre componentes.
        binary_mask = Image.new("L", canvas.size, 0)
        binary_mask.paste(scaled.getchannel("A"), offset)
        binary_mask = binary_mask.point(lambda v: 255 if v > 12 else 0)

        base_arr, far_components = self._build_unified_white_base(
            np.asarray(binary_mask, dtype=np.uint8),
            final_white_px=(0 if source_has_existing_white_border
                            else self.profile.final_white_px),
            merge_regions_mm=self.profile.merge_regions_mm,
            dpi=self.profile.dpi,
        )
        base_mask = Image.fromarray(base_arr, mode="L")

        # Quality notes are finalized below, but disconnected components are
        # detected before the rendering layers are built.
        preflight_notes: list[str] = []
        if complex_background_unresolved:
            preflight_notes.append(
                "Fondo variable: propuesta local conservada junto a máscaras alternativas; revisá detalles y huecos antes de confirmar."
                if background_refinement.get("status") == "proposal_requires_review" else
                "Fondo variable: segmentación ambigua. Se conservaron alternativas; corregí la máscara antes de confirmar.")
        if extracted_area_loss > .25 and not has_manual_mask_override and not selected_component_ids:
            preflight_notes.append("La limpieza perdió más del 25 % de la superficie extraída; revisá la silueta.")
        if far_components:
            preflight_notes.append(
                f"{len(far_components)} componente(s) separada(s) "
                f"que requiere revisión manual.")

        # ── 7. Construir capas de borde ───────────────────────────────────────
        progress(62, "Construyendo bordes")
        # Los espesores pertenecen al perfil de producción y deben ser
        # consistentes, independientemente de la proporción del diseño.
        preserve_existing_white = preserve_existing_white_source
        control_black_px = self.profile.control_black_px
        inner_white_px = self.profile.inner_white_px

        # CORRECCIÓN 2: Para PNG con transparencia real, usar el flujo normal
        # pero asegurar que el RGB oculto esté limpio antes de crear el borde
        if has_real_transparency and not opaque_png:
            logger.info("CORRECCION_2: Using normal border flow for transparent PNG (RGB already cleaned)")
            # Usar el flujo normal ya que el RGB oculto ya fue limpiado en _flow_a
            pre_smooth = base_mask
        else:
            # Flujo normal para imágenes opacas
            pre_smooth = base_mask

        # La base blanca unificada ya incluye el borde blanco (dilatación
        # por final_white_px dentro de _build_unified_white_base).
        # No se aplica _expand adicional para evitar doble borde.
        white_mask = pre_smooth
        smooth_r = (2 if preserve_existing_white
                    else self.profile.smooth_px / 2)
        if self.profile.smooth_px:
            white_mask = white_mask.filter(
                ImageFilter.GaussianBlur(smooth_r))
            white_mask = white_mask.point(lambda v: 255 if v >= 128 else 0)

        white_mask = self._polish_final_white_base(
            white_mask, self.profile.final_white_polish_strength)

        # Capas independientes y alineadas al maestro, consumibles también
        # por revisión/diagnóstico sin reconstruir el resultado compuesto.
        design_layer_path = output / "design_layer.png"
        canvas.save(design_layer_path, dpi=(self.profile.dpi,) * 2, optimize=False)
        artifacts["design_layer"] = str(design_layer_path)
        printable_base_path = output / "printable_base_mask.png"
        white_mask.save(printable_base_path, dpi=(self.profile.dpi,) * 2, optimize=False)
        artifacts["printable_base_mask"] = str(printable_base_path)

        black_mask = self._expand(white_mask, control_black_px)

        # Imagen de impresión: base blanca sólida sin agujeros internos.
        print_image = Image.new("RGBA", canvas.size, (255, 255, 255, 0))
        print_image.putalpha(white_mask)

        # Trazo blanco interno —
        # se activa para: Diseño con contorno negro propio, O Caso B con borde gris
        apply_inner_white = (
            classify_result.design_mode == "Contorno interno"
            or (classify_result.case == ImageCase.B
                and classify_result.has_grey_border)
        )
        if apply_inner_white:
            progress(65, "Aplicando trazo interno blanco")
            inner_layer = self._build_inner_white_stroke(
                base_mask, min(2, self.profile.inner_white_px), canvas)

        # Diseño recortado real encima de la base blanca sólida.
        subject_layer = canvas.copy()
        print_image.alpha_composite(subject_layer)
        if apply_inner_white:
            # El halo es parte de la capa del diseño, por eso el trazo debe
            # componerse después de ella para realmente ocultarlo.
            print_image.alpha_composite(inner_layer)

        # ── 8. Generar artefactos ─────────────────────────────────────────────
        progress(68, "Guardando maestro")

        # Validation before saving final master
        final = print_image.convert("RGBA")
        alpha_min, alpha_max = final.getchannel("A").getextrema()

        logger.info(
            "FINAL_BEFORE_SAVE alpha_min=%d alpha_max=%d",
            alpha_min,
            alpha_max,
        )

        if alpha_min == 255:
            raise RuntimeError(
                "El maestro final perdió la transparencia antes de guardarse"
            )

        # Validación final para PNG opaco
        final_master = print_image.convert("RGBA")
        final_extrema = final_master.getchannel("A").getextrema()

        logger.debug(
            "OPAQUE_PNG_FINAL alpha=%s path=%s",
            final_extrema,
            Path(output / "07_final_master.png").resolve(),
        )

        if opaque_png and final_extrema == (255, 255):
            raise RuntimeError(
                "El PNG opaco perdió la transparencia antes de exportarse"
            )

        master_path = output / "07_final_master.png"
        print_image.save(master_path, dpi=(self.profile.dpi,)*2, optimize=False)
        artifacts["master"] = str(master_path)

        logger.debug(
            "UI_ACTUAL_PREVIEW_PATH=%s",
            Path(master_path).resolve(),
        )

        # Validation after saving final master
        with Image.open(master_path) as check:
            check = check.convert("RGBA")
            after_extrema = check.getchannel("A").getextrema()
            logger.info(
                "FINAL_AFTER_SAVE alpha_extrema=%s",
                after_extrema,
            )
            if after_extrema[0] == 255:
                raise RuntimeError(
                    "El maestro final perdió la transparencia después de guardarse"
                )

        # Log alpha for 07_final_master.png
        self.log_alpha("07_final_master.png", print_image)

        # Impresión escalada al 97.27 %
        prod_px = max(1, round(master_px * self.profile.print_scale))
        prod_layer = print_image.resize((prod_px, prod_px),
                                        Image.Resampling.LANCZOS)
        production = Image.new("RGBA", print_image.size, (0, 0, 0, 0))
        prod_off = ((master_px - prod_px) // 2,) * 2
        production.alpha_composite(prod_layer, prod_off)
        print_path = output / "08_print.png"
        production.save(print_path, dpi=(self.profile.dpi,)*2, optimize=False)
        artifacts["print"] = str(print_path)

        # Vista de control con anillo negro de registro
        black_ring = ImageChops.subtract(black_mask, white_mask)
        control = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        bl = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        bl.putalpha(black_ring)
        control.alpha_composite(bl)
        control.alpha_composite(print_image)
        control_path = output / "09_control.png"
        control.save(control_path, dpi=(self.profile.dpi,)*2, optimize=False)
        artifacts["control"] = str(control_path)

        # Troquel de corte
        progress(74, "Generando troquel")
        inset_mm = self.profile.cut_inset_mm if cut_inset_mm is None \
                   else float(cut_inset_mm)
        inset_px = round(inset_mm / 25.4 * self.profile.dpi)
        cut_mask = self._contract(white_mask, inset_px).point(
            lambda v: 255 if v > 127 else 0)
        if cut_mask_override:
            with Image.open(cut_mask_override) as saved_cut:
                if saved_cut.size != white_mask.size:
                    raise ValueError("La corrección de corte debe coincidir con el tamaño maestro.")
                cut_mask = saved_cut.convert("L").point(lambda value: 255 if value > 127 else 0)
        cut_path = output / "10_cut.png"
        cut_mask.save(cut_path, dpi=(self.profile.dpi,)*2, optimize=False)
        artifacts["cut"] = str(cut_path)

        from .resolution import render_native
        native_artifacts, native_resolution = render_native(
            self, clean, output, content_scale=scale,
            existing_border=source_has_existing_white_border,
            cut_inset_mm=inset_mm, inner_white=apply_inner_white,
            cut_override=cut_mask if cut_mask_override else None,
            progress=progress,
        )
        artifacts.update(native_artifacts)
        halo_metadata["physical_border"] = {
            "requested_mm": self.profile.final_white_px * 25.4 / self.profile.dpi,
            "effective_dpi": native_resolution["dpi"],
            "generated_native_px": native_resolution["border_px"],
            "existing_border_preserved": bool(source_has_existing_white_border),
        }

        # Miniatura de revisión
        thumb = print_image.copy()
        thumb.thumbnail((256, 256), Image.Resampling.LANCZOS)
        thumb_path = output / "11_thumbnail.png"
        thumb.save(thumb_path, optimize=True)
        artifacts["thumbnail"] = str(thumb_path)

        # Log alpha for 11_thumbnail.png
        self.log_alpha("11_thumbnail.png", thumb)

        # Perfil de producción JSON
        prod_profile_path = output / "perfil_produccion.json"
        prod_profile_path.write_text(json.dumps({
            "master_cm": self.profile.resolved_asset_target_size_cm,
            "nominal_cm": self.profile.nominal_size_cm,
            "master_pixels": master_px,
            "dpi": self.profile.dpi,
            "print_scale_percent": round(self.profile.print_scale * 100, 2),
            "printed_long_side_cm": round(self.profile.print_size_cm, 3),
            "cut_inset_mm": inset_mm,
            "original_unchanged": True,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        artifacts["production_profile"] = str(prod_profile_path)

        # ── 9. Control de calidad y metadata ─────────────────────────────────
        progress(86, "Controlando calidad")
        notes: list[str] = preflight_notes
        if not analysis.resolution_ok:
            notes.append("Resolución original inferior al tamaño maestro.")
        if analysis.main_elements > 8:
            notes.append("Se detectaron posibles partículas o elementos separados.")
        if not cut_mask.getbbox():
            notes.append("El contorno de corte quedó vacío.")
        if min(offset) < self.profile.final_white_px:
            notes.append("El contenido está muy próximo al límite maestro.")

        # Control de calidad: verificar pérdida de borde blanco
        if white_border_loss > 0.25:
            notes.append(f"Posible eliminación del borde blanco original ({white_border_loss:.0%} perdido)")

        from .quality import validate_sticker
        quality_report = validate_sticker(
            design_alpha=clean_alpha, master=print_image, cut_mask=cut_mask,
            expected_pixels=master_px, dpi=self.profile.dpi,
            target_cm=self.profile.resolved_asset_target_size_cm,
            source_size=original_working_size,
            source_content_size=clean.size, target_content_size=csz,
            printable_base=base_mask if cut_mask_override is not None else None,
            intentional_components=resolved_creation_mode == CreationMode.MULTI_OBJECT.value,
            manual_mask=has_manual_mask_override,
        )
        quality_report.metrics["extracted_area_loss"] = extracted_area_loss
        if halo_metadata.get("requires_review"):
            quality_report.warnings.append({"code": "halo_manual_review", "message":
                "Halo exterior ambiguo: conservá la propuesta y revisá la máscara manualmente."})
        if border_treatment_metadata.get("requires_review"):
            quality_report.warnings.append({"code": "border_treatment_manual_review", "message":
                "El tratamiento solicitado podría duplicar o destruir el borde; se conservó el existente para revisión manual."})
        if contraction_report.requires_review:
            for warning in contraction_report.warnings:
                quality_report.warnings.append({
                    "code": "selection_contraction_detail_loss",
                    "message": warning})
        if extracted_area_loss > .25 and not has_manual_mask_override and not selected_component_ids:
            quality_report.warnings.append({"code": "surface_loss", "message": "Pérdida de superficie durante la limpieza automática."})
        for note in notes:
            quality_report.warnings.append({"code": "pipeline_review", "message": note})
        notes.extend(item["message"] for item in quality_report.errors + quality_report.warnings)
        notes = list(dict.fromkeys(notes))
        quality = "Error" if quality_report.errors else "Listo" if not notes else "Revisar"

        analysis_data = {
            **asdict(analysis),
            "quality_report": quality_report.to_dict(),
            "complex_background_unresolved": complex_background_unresolved,
            "background_refinement": background_refinement,
            "checkerboard_review": checkerboard_review,
            "grey_halo_review": halo_metadata,
            "border_treatment": border_treatment_metadata,
            "selection_contraction": contraction_report.to_dict(),
            "case": classify_result.case.value,
            "case_reasons": classify_result.reasons,
            "sticker_type": classify_result.sticker_type,
            "sticker_type_label": classify_result.sticker_type_label,
            "detected_types": classify_result.detected_types,
            "classification_features": classify_result.classification_features,
            "design_mode": classify_result.design_mode,
            "creation_mode": resolved_creation_mode,
            "layer_coordinates": {"design_layer": "master", "printable_base_mask": "master", "cut": "master", "mask_editable": "source_editable"},
            "printable_border_mm": round(self.profile.final_white_px * 25.4 / self.profile.dpi, 4),
            "full_image_shape": full_image_shape,
            "selected_component_ids": selected_component_ids or [],
            "object_components": object_components,
            "object_selection_warning": object_selection_warning,
            "shape_type": shape_type,
            "orientation": "Vertical" if rotated_to_vertical or clean.height >= clean.width else "Horizontal",
            "rotated_to_vertical": rotated_to_vertical,
            "has_white_border_detected": classify_result.has_white_border,
            "has_black_outline_detected": classify_result.has_black_outline,
            "mode": self.profile.mode,
            "quality": self.profile.quality,
            "source_pixels": list(original_working_size),
            "processing_pixels": list(processing_size),
            "processing_downscaled": processing_size != original_working_size,
            "native_resolution": native_resolution,
            "source_content_pixels": list(clean.size),
            "master_content_pixels": list(csz),
            "source_to_master_scale": scale,
            "source_processing_dpi": source_effective_dpi,
            "manual_mask_transform": ({
                "input_pixels": list(manual_mask_original_size),
                "output_pixels": list(rgba.size),
                "scale_x": rgba.width / manual_mask_original_size[0],
                "scale_y": rgba.height / manual_mask_original_size[1],
            } if has_manual_mask_override else None),
            "effective_content_dpi": self.profile.dpi / scale,
            # Campos de compatibilidad con tests y metadata histórica
            "selection_processing_mode": (
                "Selección completa" if preserve_full_image else "Extraer silueta"
            ),
            "background_removal_scope": "Solo exterior conectado",
            "png_holes_filled_white": False,
            "png_internal_hole_fill": False,
            "closed_interior_preserved": False,
            "holes_detected": postprocess_meta.get("holes_detected", 0),
            "holes_filled": postprocess_meta.get("holes_filled", 0),
            "hole_analysis": postprocess_meta.get("hole_analysis", []),
            "removed_particles_count": postprocess_meta.get("removed_particles_count", 0),
            "removed_particles": postprocess_meta.get("removed_particles", []),
            "removed_detached_components": postprocess_meta.get("removed_detached_components", []),
            "protection_zones": [list(z) for z in (protection_zones or [])],
        }

        metadata = {
            "schema_version": 2,
            "reprocess_parameters": {
                "creation_mode": resolved_creation_mode,
                "full_image_shape": full_image_shape,
                "selected_component_ids": selected_component_ids or [],
                "visual_type_override": visual_type_override,
                "mode_override": mode_override,
                "mask_override": str(mask_override) if mask_override else None,
                "cut_mask_override": str(cut_mask_override) if cut_mask_override else None,
                "border_treatment": border_treatment,
                "selection_contraction_mm": selection_contraction_mm,
                "selection_expansion_mm": selection_expansion_mm,
                "selection_protection_mask": str(selection_protection_mask) if selection_protection_mask else None,
                "selection_smoothing_mm": selection_smoothing_mm,
                "preserve_full_image": preserve_full_image,
                "preserve_orientation": preserve_orientation,
                "protection_zones": protection_zones or [],
                "cut_inset_mm": inset_mm,
                "previous_object_components": previous_object_components or [],
            },
            "job_id": job_id,
            "source_path": str(source_path),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "analysis": analysis_data,
            "profile": {**asdict(self.profile), "cut_inset_mm": inset_mm},
            "artifacts": artifacts,
            "quality_status": quality,
            "quality_notes": notes,
        }
        meta_path = output / "metadata.json"
        meta_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8")
        artifacts["metadata"] = str(meta_path)

        # Manifest for UI - explicit paths for current execution
        manifest = {
            "run_id": job_id,
            "source_path": str(source_path.resolve()),
            "source_pixel_hash": pixel_hash,
            "final_path": str(master_path.resolve()),
            "thumbnail_path": str(thumb_path.resolve()),
        }
        manifest_path = output / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8")
        artifacts["manifest"] = str(manifest_path)
        logger.info(f"MANIFEST_PATH={manifest_path.resolve()}")

        progress(100, quality)

        # Final tracing logs
        logger.info(f"OUTPUT_FINAL={master_path.resolve()}")
        logger.info(f"OUTPUT_CONTROL={control_path.resolve()}")
        logger.info(f"OUTPUT_PRINT={print_path.resolve()}")
        logger.info(f"OUTPUT_DIR={output.resolve()}")

        return ProcessingResult(
            job_id=job_id,
            source_path=str(source_path),
            output_dir=str(output),
            status="Procesado",
            quality_status=quality,
            quality_notes=notes,
            analysis=analysis_data,
            artifacts=artifacts,
            profile={**asdict(self.profile), "cut_inset_mm": inset_mm},
        )
