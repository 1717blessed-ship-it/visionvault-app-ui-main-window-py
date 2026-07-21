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

logger = logging.getLogger(__name__)
from dataclasses import asdict, dataclass, field
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
# Enumeraciones
# ══════════════════════════════════════════════════════════════════════════════

class ImageCase(enum.Enum):
    """Caso de imagen detectado por classify()."""
    A = "A - PNG transparente sin borde"
    B = "B - Sticker ya terminado"
    C = "C - Fondo de color uniforme"
    D = "D - Fotografía"


class ProcessingMode(enum.Enum):
    """Modo de procesamiento elegido por el usuario o por defecto."""
    AUTO          = "Automático"
    PHOTO         = "Fotografía"
    ILLUSTRATION  = "Ilustración"
    EXISTING      = "Sticker existente"
    LOGO          = "Logo"


class BorderMode(enum.Enum):
    """Resultado del análisis de borde blanco sobre la imagen original."""
    PRESERVE_EXISTING_BORDER = "borde_existente"
    GENERATE_WHITE_BORDER    = "generar_borde"
    NO_BORDER_REQUIRED       = "sin_borde"
    AMBIGUOUS_WHITE_ON_WHITE = "ambiguo_blanco_sobre_blanco"


class QualityPreset(enum.Enum):
    """Nivel de calidad del procesamiento."""
    FAST       = "Rápida"
    BALANCED   = "Balanceada"
    COMMERCIAL = "Comercial"
    PREMIUM    = "Premium"


# ══════════════════════════════════════════════════════════════════════════════
# Dataclasses
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(slots=True)
class ProcessingProfile:
    name: str = "Doccione maestro 5,70"
    master_size_cm: float = 5.70
    content_size_cm: float = 5.30
    dpi: int = 300
    print_scale: float = 0.9727
    cut_inset_mm: float = 1.0
    # Conservados para compatibilidad con jobs históricos.
    initial_white_px: int = 0
    consolidate_inset_px: int = 0
    # Borde blanco exterior
    smooth_px: int = 8
    final_white_px: int = 30
    inner_white_px: int = 10
    control_black_px: int = 2
    # Modo y calidad
    mode: str = ProcessingMode.AUTO.value
    quality: str = QualityPreset.COMMERCIAL.value
    # ── Pasos del postprocesado (activables individualmente) ──────────────
    remove_particles: bool = True
    remove_particles_min_px: int = 80        # área mínima en px² a 300 dpi
    fill_holes: bool = True
    fill_holes_max_px: int = 2000            # área máxima del hueco a rellenar
    close_channels: bool = True
    close_channels_mm: float = 4.0           # ancho máximo del canal a cerrar
    merge_regions: bool = True
    merge_regions_mm: float = 2.0            # distancia máxima entre regiones
    round_corners: bool = True
    round_corners_mm: float = 0.8            # radio mínimo de esquinas en mm
    min_corner_radius_px: int = 8            # radio mínimo de esquina en px
    remove_spikes: bool = True               # eliminar picos por análisis de hull
    simplify_curves: bool = True
    simplify_curves_mm: float = 0.4          # tolerancia Douglas-Peucker
    curve_smooth_iters: int = 2              # nivel de suavizado de curvas
    # ── Control de fantasmas / semitransparencias internas ────────────────
    ghost_threshold: int = 128               # alpha por debajo del cual se descarta si es interior
    edge_feather_px: int = 3                 # corona perimetral donde SÍ se permite suavidad

    @property
    def master_pixels(self) -> int:
        return round(self.master_size_cm / 2.54 * self.dpi)

    @property
    def print_size_cm(self) -> float:
        return self.master_size_cm * self.print_scale

    @property
    def is_premium(self) -> bool:
        return self.quality == QualityPreset.PREMIUM.value

    @property
    def is_fast(self) -> bool:
        return self.quality == QualityPreset.FAST.value


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


# ══════════════════════════════════════════════════════════════════════════════
# StickerProcessor
# ══════════════════════════════════════════════════════════════════════════════

class StickerProcessor:

    def __init__(self, workspace: str | Path,
                 profile: ProcessingProfile | None = None):
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.profile = profile or ProcessingProfile()

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
    def _expand(mask, pixels: int):
        try:
            import cv2
            import numpy as np
            from PIL import Image
            diameter = max(1, int(pixels) * 2 + 1)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                               (diameter, diameter))
            return Image.fromarray(
                cv2.dilate(np.asarray(mask.convert("L")), kernel, iterations=1),
                mode="L")
        except (ImportError, ModuleNotFoundError):
            pass

        from PIL import ImageFilter
        result, remaining = mask, max(0, pixels)
        while remaining:
            r = min(remaining, 20)
            result = result.filter(ImageFilter.MaxFilter(r * 2 + 1))
            remaining -= r
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
        data = list(small.getdata())
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
        has_transparency = alpha_ch.getextrema()[0] < 250

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
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
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
            if has_transparency and has_white_border:
                case = ImageCase.B
                reasons.append("Auto → Caso B (sticker ya terminado)")
            elif has_transparency and has_grey_border:
                # Sticker con borde gris/sombra exterior → mismo flujo B
                case = ImageCase.B
                reasons.append("Auto → Caso B (borde gris exterior detectado)")
            elif has_transparency:
                case = ImageCase.A
                reasons.append("Auto → Caso A (PNG transparente)")
            elif uniform_bg:
                case = ImageCase.C
                reasons.append(
                    f"Auto → Caso C (fondo uniforme RGB{bg_color})")
            elif is_photo:
                case = ImageCase.D
                reasons.append("Auto → Caso D (fotografía)")
            else:
                case = ImageCase.C
                reasons.append("Auto → Caso C (ilustración sin fondo claro)")

        design_mode = ("Contorno interno"
                       if has_black_outline else "Color uniforme")

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
        )

    def analyze(self, path: str | Path) -> Analysis:
        """Análisis rápido para metadatos y control de calidad."""
        from PIL import Image, ImageFilter, ImageStat
        with Image.open(path) as src:
            rgba = src.convert("RGBA")
        alpha = rgba.getchannel("A")
        has_transparency = alpha.getextrema()[0] < 250
        w, h = rgba.size
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
        vis = sum(v > 12 for v in alpha.resize((64,64)).getdata()) / (64*64)
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

    # ──────────────────────────────────────────────────────────────────────────
    # FLUJO A — PNG transparente sin borde
    # ──────────────────────────────────────────────────────────────────────────

    def _flow_a(self, rgba, classify_result: ClassifyResult,
                progress: Callable, fill_closed_holes: bool = True) -> "Image":
        """PNG con transparencia pero sin borde blanco.

        1. Tomar el canal alpha existente como máscara base.
        2. Reparar pequeños huecos internos cerrados.
        3. Refinar contorno si el diseño tiene outline negro propio.
        4. Suavizar y limpiar la máscara.
        5. Devolver la imagen RGBA recortada con máscara corregida.
        """
        from PIL import Image, ImageChops, ImageFilter

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

        progress(20, "Flujo B: eliminando borde exterior")
        alpha = self._strip_existing_border(rgba, classify_result)
        alpha = self._clean_alpha(alpha)

        progress(32, "Flujo B: reconstruyendo máscara")
        alpha = self._preserve_closed_interiors(alpha)

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

            if classify_result.has_grey_border:
                # Gris: los tres canales muy similares entre sí y en rango medio
                neutral = (np.abs(r.astype(int) - g.astype(int)) < 35) & \
                          (np.abs(g.astype(int) - b.astype(int)) < 35) & \
                          (np.abs(r.astype(int) - b.astype(int)) < 35)
                # Incluir también el blanco para un solo flood fill combinado
                border_px = neutral & (r > 90) | \
                            ((r >= 210) & (g >= 210) & (b >= 210))
            else:
                # Solo blanco/casi blanco (tolerancia 30)
                lo = 255 - 30
                border_px = (r >= lo) & (g >= lo) & (b >= lo)

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
        """
        from PIL import Image, ImageFilter

        progress(20, "Flujo C: separando fondo uniforme")
        # Primero usar siempre un flood fill conectado al lienzo. Esto separa
        # también stickers con fondo oscuro sin cruzar su borde blanco.
        alpha = self._uniform_background_alpha(rgba, tolerance=42)
        if alpha.getbbox() is None or alpha.getextrema() == (255, 255):
            # En gris claro la sombra puede estar más alejada del color de
            # fondo; aplicar la tolerancia asimétrica antes de segmentar.
            alpha = self._light_neutral_exterior_alpha(rgba)
            if alpha.getbbox() is None or alpha.getextrema() == (255, 255):
                progress(24, "Flujo C: segmentando con fondo uniforme")
                alpha = self._segment_ia(rgba, progress)

        progress(34, "Flujo C: preservando interiores cerrados")
        alpha = self._clean_alpha(alpha)
        alpha = self._preserve_closed_interiors(alpha)

        progress(40, "Flujo C: suavizando máscara")
        alpha = self._clean_alpha(alpha)

        result = rgba.copy()
        result.putalpha(alpha)
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
    def _uniform_background_alpha(image, tolerance: int):
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
            value = rgb.max(axis=2).astype(np.int16)
            minimum = rgb.min(axis=2).astype(np.int16)
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
    def _build_inner_white_stroke(base_mask, inner_stroke_px: int):
        """Anillo blanco exterior al diseño (Diseño 2 / Contorno interno)."""
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

        rgb = np.asarray(rgba.convert("RGB"), dtype=np.uint8)
        h, w = rgb.shape[:2]

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
        sat = np.where(cmax == 0, 0.0, delta / cmax)
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

            has_design = float(design.sum()) > (h * w * 0.005)
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
    def _whiten_neutral_outer_halo(image, alpha, width: int = 24):
        """Blanquea solo grises suaves dentro del margen blanco exterior."""
        try:
            import numpy as np
            from PIL import Image, ImageChops

            solid = alpha.convert("L").point(lambda value: 255 if value > 127 else 0)
            inner = StickerProcessor._contract(solid, width)
            outer_band = np.asarray(ImageChops.subtract(solid, inner), dtype=np.uint8) > 0
            rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
            rgb = rgba[:, :, :3].astype(np.int16)
            neutral = ((np.abs(rgb[:, :, 0] - rgb[:, :, 1]) <= 18)
                       & (np.abs(rgb[:, :, 1] - rgb[:, :, 2]) <= 18)
                       & (rgb[:, :, 0] >= 145) & (rgb[:, :, 0] <= 250))
            cover = outer_band & neutral
            rgba[cover, :3] = 255
            return Image.fromarray(rgba, mode="RGBA")
        except (ImportError, ModuleNotFoundError):
            return image.convert("RGBA")

    @staticmethod
    def _shape_type(mask) -> str:
        binary = mask.convert("L").point(lambda v: 255 if v >= 24 else 0)
        bbox = binary.getbbox()
        if not bbox:
            return "Silueta"
        cropped = binary.crop(bbox).resize((64, 64))
        pixels = list(cropped.getdata())
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

    # ──────────────────────────────────────────────────────────────────────────
    # TAREA 7 — Postprocesado unificado
    # ──────────────────────────────────────────────────────────────────────────

    def _postprocess(self, mask, dpi: int, fill_holes: bool | None = None) -> tuple["Image", dict]:
        """Postprocesado unificado aplicado a todos los casos.

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
        }
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
            if p.remove_particles:
                min_area = max(1, p.remove_particles_min_px)
                n_c, lmap_c, stats_c, _ = cv2.connectedComponentsWithStats(
                    arr, connectivity=8)
                clean = np.zeros_like(arr)
                for lb in range(1, n_c):
                    area = int(stats_c[lb, cv2.CC_STAT_AREA])
                    left = int(stats_c[lb, cv2.CC_STAT_LEFT])
                    top = int(stats_c[lb, cv2.CC_STAT_TOP])
                    width = int(stats_c[lb, cv2.CC_STAT_WIDTH])
                    height = int(stats_c[lb, cv2.CC_STAT_HEIGHT])
                    if area >= min_area:
                        clean[lmap_c == lb] = 255
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
            if p.round_corners:
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
        from scipy import ndimage

        alpha_np = np.array(alpha_img, dtype=np.uint8)
        binary = alpha_np > 127

        labeled, n_labels = ndimage.label(binary.astype(np.uint8))
        if n_labels <= 1:
            return alpha_img, []

        comp_sizes = []
        for i in range(1, n_labels + 1):
            comp_sizes.append((i, int((labeled == i).sum())))
        comp_sizes.sort(key=lambda x: x[1], reverse=True)
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

    def process(
        self,
        source_path: str | Path,
        progress: Callable[[int, str], None] | None = None,
        cut_inset_mm: float | None = None,
        mask_override: str | Path | None = None,
        preserve_full_image: bool = False,
        mode_override: str | None = None,
        protection_zones: list | None = None,
    ) -> ProcessingResult:
        """Orquesta el árbol de decisiones completo.

        Orden:
          1. Copiar original y analizar metadatos básicos.
          2. classify() → determina ImageCase.
          3. Aplicar mask_override / preserve_full_image si fue solicitado.
          4. Despachar al flujo adecuado (A / B / C / D).
          5. _postprocess() sobre la máscara resultante.
          6. Normalizar al tamaño maestro.
          7. Construir capas: borde blanco, trazo interno (si aplica), diseño.
          8. Generar artefactos: maestro, impresión, control, troquel.
          9. Control de calidad y metadata.
        """
        from PIL import Image, ImageChops, ImageFilter

        progress = progress or (lambda _p, _m: None)
        source_path = self.validate_source(source_path)
        job_id = uuid.uuid4().hex
        output = self.workspace / job_id
        output.mkdir(parents=True, exist_ok=True)
        artifacts: dict[str, str] = {}

        # ── 1. Copiar original ────────────────────────────────────────────────
        progress(5, "Copiando original")
        original_copy = output / f"original{source_path.suffix.lower() or '.png'}"
        shutil.copy2(source_path, original_copy)
        artifacts["original"] = str(original_copy)

        analysis = self.analyze(source_path)
        progress(10, f"Análisis: {analysis.engine}")

        # Respeta la orientación EXIF de fotos de teléfono y crea una copia
        # independiente antes de cerrar el archivo de origen.
        from PIL import ImageOps
        with Image.open(source_path) as src:
            rgba = ImageOps.exif_transpose(src).convert("RGBA").copy()
        png_closed_holes = (
            source_path.suffix.lower() == ".png"
            and self._closed_interior_mask(rgba.getchannel("A")).getbbox() is not None
        )

        # ── 2. Clasificar ─────────────────────────────────────────────────────
        progress(13, "Clasificando imagen")
        if preserve_full_image:
            # Caso especial: usar la imagen completa sin recorte
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
            rgba.putalpha(Image.new("L", rgba.size, 255))
        elif mask_override and Path(mask_override).exists():
            with Image.open(mask_override) as m:
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
        else:
            classify_result = self.classify(rgba, mode_override=mode_override)

        progress(16, f"Caso {classify_result.case.value}")

        # ── 3. Despachar al flujo correspondiente ─────────────────────────────
        case = classify_result.case

        border_analysis = self.analyze_original_border_structure(rgba)
        border_mode = border_analysis["mode"]

        # Construir máscara de protección en coordenadas de la imagen fuente
        prot_mask = None
        if protection_zones:
            prot_mask = self._build_protection_mask(rgba.size, protection_zones)

        if case == ImageCase.B:
            prepared_rgba = self._flow_b(rgba, classify_result, progress)
        elif case == ImageCase.D:
            prepared_rgba = self._flow_d(rgba, classify_result, progress)
        elif case == ImageCase.C:
            prepared_rgba = self._flow_c(rgba, classify_result, progress)
        else:
            prepared_rgba = self._flow_a(
                rgba, classify_result, progress,
                fill_closed_holes=source_path.suffix.lower() == ".png",
            )

        # Restaurar zonas protegidas que el flujo pudo haber eliminado
        if prot_mask is not None:
            raw_alpha_pre = self._apply_protection(
                prepared_rgba.getchannel("A"), prot_mask)
            prepared_rgba.putalpha(raw_alpha_pre)

        progress(46, "Postprocesando máscara")

        # ── 4. Postprocesado unificado ────────────────────────────────────────
        raw_alpha = prepared_rgba.getchannel("A")
        bbox_check = raw_alpha.point(lambda v: 255 if v > 12 else 0).getbbox()
        if not bbox_check:
            raise ValueError("No se pudo separar el diseño del fondo.")

        debug_raw_mask = raw_alpha.convert("L").point(lambda v: 255 if v > 12 else 0)
        debug_raw_mask_path = output / "mask_segmentation_raw.png"
        debug_raw_mask.save(debug_raw_mask_path, dpi=(self.profile.dpi,)*2,
                            optimize=False)
        artifacts["mask_segmentation_raw"] = str(debug_raw_mask_path)

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
            refined_alpha, postprocess_meta = self._postprocess(
                raw_alpha, self.profile.dpi,
                fill_holes=source_path.suffix.lower() == ".png",
            )

        # ── Etapa 2B: eliminar ruido gris aislado ────────────────────────
        grey_noise_log = []
        if border_mode == BorderMode.AMBIGUOUS_WHITE_ON_WHITE:
            _rgb2 = np.array(rgba.convert("RGB"), dtype=np.uint8)
            refined_alpha, grey_noise_log = self._remove_grey_noise(
                refined_alpha, _rgb2)

        # Una selección completa representa deliberadamente el rectángulo
        # elegido: no se le aplican márgenes transparentes ni limpieza de borde.
        if preserve_full_image:
            refined_alpha = Image.new("L", rgba.size, 255)

        # Restaurar zonas protegidas que el postprocesado pudo haber tocado
        if prot_mask is not None:
            refined_alpha = self._apply_protection(refined_alpha, prot_mask)

        white_border_after = self._white_outer_border_pixels(rgba, refined_alpha)
        white_border_loss = 1 - (white_border_after / max(white_border_before, 1))

        prepared_rgba.putalpha(refined_alpha)
        # En JPG con fondo gris claro puede sobrevivir una línea gris dentro
        # del margen blanco. No pertenece al dibujo: se limpia únicamente en
        # la corona exterior, antes de crear el trazo final.
        if (case == ImageCase.C and classify_result.uniform_background) or (
                case == ImageCase.B and classify_result.has_grey_border):
            prepared_rgba = self._whiten_neutral_outer_halo(
                prepared_rgba, refined_alpha)
            prepared_rgba.putalpha(refined_alpha)

        # Guardar la máscara binaria básica justo después de la extracción y
        # antes de construir la base blanca.
        intermediate_mask = refined_alpha.convert("L").point(
            lambda v: 255 if v > 12 else 0)
        intermediate_mask_path = output / "mask_binary_intermediate.png"
        intermediate_mask.save(intermediate_mask_path,
                               dpi=(self.profile.dpi,)*2,
                               optimize=False)
        artifacts["mask_intermediate"] = str(intermediate_mask_path)

        # ── 5. Recortar, rotar a vertical y guardar intermedios ───────────────
        progress(50, "Recortando y orientando")
        bbox = refined_alpha.point(lambda v: 255 if v > 12 else 0).getbbox()
        clean = prepared_rgba.crop(bbox)
        clean_alpha = refined_alpha.crop(bbox)
        shape_type = self._shape_type(clean_alpha)

        rotated_to_vertical = clean.width > clean.height
        if rotated_to_vertical:
            clean = clean.transpose(Image.Transpose.ROTATE_270)
            clean_alpha = clean_alpha.transpose(Image.Transpose.ROTATE_270)

        clean_path = output / "diseno_limpio.png"
        clean.save(clean_path, dpi=(self.profile.dpi,)*2, optimize=False)
        artifacts["clean"] = str(clean_path)

        mask_path = output / "mascara.png"
        refined_alpha.save(mask_path, dpi=(self.profile.dpi,)*2, optimize=False)
        artifacts["mask"] = str(mask_path)

        cropped_mask_path = output / "mascara_recortada.png"
        clean_alpha.save(cropped_mask_path, dpi=(self.profile.dpi,)*2,
                         optimize=False)
        artifacts["mask_cropped"] = str(cropped_mask_path)

        silhouette_path = output / "silueta_consolidada.png"
        clean.save(silhouette_path, dpi=(self.profile.dpi,)*2, optimize=False)
        artifacts["silhouette"] = str(silhouette_path)

        # ── 6. Normalizar al tamaño maestro ──────────────────────────────────
        progress(54, "Normalizando al maestro")
        master_px = self.profile.master_pixels
        reserved = self.profile.final_white_px + self.profile.control_black_px + 4
        exact_content_px = master_px - reserved * 2
        requested_px = round(self.profile.content_size_cm / 2.54 * self.profile.dpi)
        content_px = min(requested_px, exact_content_px)
        scale = min(content_px / clean.width, content_px / clean.height)
        csz = (max(1, round(clean.width * scale)),
               max(1, round(clean.height * scale)))
        scaled = clean.resize(csz, Image.Resampling.LANCZOS)
        c_alpha = scaled.getchannel("A")

        canvas = Image.new("RGBA", (master_px, master_px), (0, 0, 0, 0))
        offset = ((master_px - scaled.width) // 2,
                  (master_px - scaled.height) // 2)
        canvas.alpha_composite(scaled, offset)

        # Construir la base blanca únicamente a partir del contorno exterior.
        binary_mask = Image.new("L", canvas.size, 0)
        binary_mask.paste(scaled.getchannel("A"), offset)
        binary_mask = binary_mask.point(lambda v: 255 if v > 12 else 0)

        base_mask = binary_mask
        try:
            import numpy as np
            import cv2

            arr = np.asarray(binary_mask, dtype=np.uint8)
            if arr.max() > 0:
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
                arr = cv2.morphologyEx(arr, cv2.MORPH_CLOSE, kernel)

                contours, _ = cv2.findContours(arr, cv2.RETR_EXTERNAL,
                                               cv2.CHAIN_APPROX_SIMPLE)
                base_arr = np.zeros_like(arr)
                if contours:
                    cv2.fillPoly(base_arr, contours, 255)
                base_mask = Image.fromarray(base_arr, mode="L")

                # Cerrar canales muy estrechos para mejorar el trazo final.
                if base_arr.max() > 0:
                    kernel2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
                    base_arr = cv2.morphologyEx(base_arr, cv2.MORPH_CLOSE, kernel2)
                    base_mask = Image.fromarray(base_arr, mode="L")
        except (ImportError, ModuleNotFoundError):
            pass

        # ── 7. Construir capas de borde ───────────────────────────────────────
        progress(62, "Construyendo bordes")
        # Los espesores pertenecen al perfil de producción y deben ser
        # consistentes, independientemente de la proporción del diseño.
        preserve_existing_white = preserve_existing_white_source
        control_black_px = self.profile.control_black_px
        inner_white_px = self.profile.inner_white_px

        pre_smooth = base_mask.filter(ImageFilter.GaussianBlur(1))
        pre_smooth = pre_smooth.point(lambda v: 255 if v >= 128 else 0)
        
        # Si hay borde blanco preexistente, usar la máscara tal cual (ya incluye el borde)
        # Si no, agregar el borde blanco de producción
        if preserve_existing_white:
            # El borde blanco ya está en la máscara: usar tal cual sin expansión
            white_mask = pre_smooth
            # Solo aplicar un suavizado muy leve para eliminar escalones del flood fill
            if self.profile.smooth_px:
                white_mask = white_mask.filter(ImageFilter.GaussianBlur(2))
                white_mask = white_mask.point(lambda v: 255 if v >= 128 else 0)
        else:
            # Agregar borde blanco de producción
            final_white_px = self.profile.final_white_px
            white_mask = self._expand(pre_smooth, final_white_px)
            if self.profile.smooth_px:
                white_mask = white_mask.filter(
                    ImageFilter.GaussianBlur(self.profile.smooth_px / 2))
                white_mask = white_mask.point(lambda v: 255 if v >= 128 else 0)
        
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
                base_mask, min(2, self.profile.inner_white_px))

        # Diseño recortado real encima de la base blanca sólida.
        subject_layer = canvas.copy()
        print_image.alpha_composite(subject_layer)
        if apply_inner_white:
            # El halo es parte de la capa del diseÃ±o, por eso el trazo debe
            # componerse despuÃ©s de ella para realmente ocultarlo.
            print_image.alpha_composite(inner_layer)

        # ── 8. Generar artefactos ─────────────────────────────────────────────
        progress(68, "Guardando maestro")
        master_path = output / "maestro_5_70cm.png"
        print_image.save(master_path, dpi=(self.profile.dpi,)*2, optimize=False)
        artifacts["master"] = str(master_path)

        # Impresión escalada al 97.27 %
        prod_px = max(1, round(master_px * self.profile.print_scale))
        prod_layer = print_image.resize((prod_px, prod_px),
                                        Image.Resampling.LANCZOS)
        production = Image.new("RGBA", print_image.size, (0, 0, 0, 0))
        prod_off = ((master_px - prod_px) // 2,) * 2
        production.alpha_composite(prod_layer, prod_off)
        print_path = output / "impresion_97_27.png"
        production.save(print_path, dpi=(self.profile.dpi,)*2, optimize=False)
        artifacts["print"] = str(print_path)

        # Vista de control con anillo negro de registro
        black_ring = ImageChops.subtract(black_mask, white_mask)
        control = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        bl = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        bl.putalpha(black_ring)
        control.alpha_composite(bl)
        control.alpha_composite(print_image)
        control_path = output / "control.png"
        control.save(control_path, dpi=(self.profile.dpi,)*2, optimize=False)
        artifacts["control"] = str(control_path)

        # Troquel de corte
        progress(74, "Generando troquel")
        inset_mm = self.profile.cut_inset_mm if cut_inset_mm is None \
                   else float(cut_inset_mm)
        inset_px = round(inset_mm / 25.4 * self.profile.dpi)
        cut_mask = self._contract(white_mask, inset_px).point(
            lambda v: 255 if v > 127 else 0)
        cut_path = output / "contorno_corte.png"
        cut_mask.save(cut_path, dpi=(self.profile.dpi,)*2, optimize=False)
        artifacts["cut"] = str(cut_path)

        # Miniatura de revisión
        thumb = print_image.copy()
        thumb.thumbnail((256, 256), Image.Resampling.LANCZOS)
        thumb_path = output / "miniatura.png"
        thumb.save(thumb_path, optimize=True)
        artifacts["thumbnail"] = str(thumb_path)

        # Perfil de producción JSON
        prod_profile_path = output / "perfil_produccion.json"
        prod_profile_path.write_text(json.dumps({
            "master_cm": self.profile.master_size_cm,
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
        notes: list[str] = []
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
        
        quality = "Listo" if not notes else "Revisar"

        analysis_data = {
            **asdict(analysis),
            "case": classify_result.case.value,
            "case_reasons": classify_result.reasons,
            "design_mode": classify_result.design_mode,
            "shape_type": shape_type,
            "orientation": "Vertical",
            "rotated_to_vertical": rotated_to_vertical,
            "has_white_border_detected": classify_result.has_white_border,
            "has_black_outline_detected": classify_result.has_black_outline,
            "mode": self.profile.mode,
            "quality": self.profile.quality,
            # Campos de compatibilidad con tests y metadata histórica
            "selection_processing_mode": (
                "Selección completa" if preserve_full_image else "Extraer silueta"
            ),
            "background_removal_scope": "Solo exterior conectado",
            "png_holes_filled_white": bool(
                png_closed_holes
            ),
            "png_internal_hole_fill": source_path.suffix.lower() == ".png",
            "closed_interior_preserved": False,
            "holes_detected": postprocess_meta.get("holes_detected", 0),
            "holes_filled": postprocess_meta.get("holes_filled", 0),
            "hole_analysis": postprocess_meta.get("hole_analysis", []),
            "removed_particles_count": postprocess_meta.get("removed_particles_count", 0),
            "removed_particles": postprocess_meta.get("removed_particles", []),
            "protection_zones": [list(z) for z in (protection_zones or [])],
        }

        metadata = {
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

        progress(100, quality)
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
