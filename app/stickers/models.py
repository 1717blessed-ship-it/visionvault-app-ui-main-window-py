"""Estructuras de datos comunes para el creador de stickers.

Este módulo es la única fuente de verdad para las estructuras compartidas
entre pipeline.py, mask_candidates.py, image_analysis.py, exporter.py y
editor.py.  Evita tener diccionarios con nombres distintos que representan
la misma información.

Convención obligatoria para máscaras binarias
----------------------------------------------
    255  o  True  →  conservar diseño (foreground)
     0  o  False  →  eliminar fondo (background)
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

import numpy as np


# ══════════════════════════════════════════════════════════════════════════════
# Enumeraciones
# ══════════════════════════════════════════════════════════════════════════════

class ProcessingMode(enum.Enum):
    """Modo de procesamiento elegido por el usuario o por defecto."""
    AUTO = "Automático"
    PHOTO = "Fotografía"
    ILLUSTRATION = "Ilustración"
    EXISTING = "Sticker existente"
    LOGO = "Logo"


class CreationMode(enum.Enum):
    """Intención del usuario, separada de las rutas técnicas A/B/C/D."""
    SILHOUETTE = "Sticker de silueta"
    FULL_IMAGE = "Sticker de imagen completa"
    MULTI_OBJECT = "Sticker de múltiples objetos"


class BorderMode(enum.Enum):
    """Resultado del análisis de borde blanco sobre la imagen original."""
    PRESERVE_EXISTING_BORDER = "borde_existente"
    GENERATE_WHITE_BORDER = "generar_borde"
    NO_BORDER_REQUIRED = "sin_borde"
    AMBIGUOUS_WHITE_ON_WHITE = "ambiguo_blanco_sobre_blanco"


class BorderTreatment(enum.Enum):
    """Decisión de usuario separada de la clasificación y de las rutas A/B/C/D."""
    PRESERVE_CLEAN = "Conservar y limpiar"
    REPLACE = "Reemplazar"
    ADD = "Agregar nuevo"


class QualityPreset(enum.Enum):
    """Nivel de calidad del procesamiento."""
    FAST = "Rápida"
    BALANCED = "Balanceada"
    COMMERCIAL = "Comercial"
    PREMIUM = "Premium"


class ImageCase(enum.Enum):
    """Caso de imagen detectado por classify()."""
    A = "A - PNG transparente sin borde"
    B = "B - Sticker ya terminado"
    C = "C - Fondo de color uniforme"
    D = "D - Fotografía"




# ══════════════════════════════════════════════════════════════════════════════


class JobStatus(enum.Enum):
    """Estados del historial por imagen."""
    PENDING = "Pendiente"
    PROCESSING = "Procesando"
    NEEDS_REVIEW = "Necesita revision"
    PROCESSED = "Procesado"
    MANUALLY_EDITED = "Editado manualmente"
    APPROVED = "Aprobado"
    EXPORTED = "Exportado"
    ERROR = "Error"
    DISCARDED = "Descartado"



# Dataclasses
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(slots=True)
class ProcessingProfile:
    """Parámetros de procesamiento para un sticker."""
    name: str = "Doccione maestro 5,70"
    # ``master_size_cm`` y ``content_size_cm`` describen el modo legacy.  Un
    # pedido aporta el nominal explícitamente; el raster se prepara entonces
    # para el máximo productivo, no para un maestro comercial fijo.
    nominal_size_cm: float | None = None
    asset_target_size_cm: float | None = None
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
    # Limpieza adaptativa de la base blanca final: 0 conserva cada detalle;
    # 1 elimina microburbujas (valor recomendado); 2 suaviza más para artes
    # simples con halos o ruido visible.
    final_white_polish_strength: int = 1
    final_white_px: int = 30
    inner_white_px: int = 10
    control_black_px: int = 2
    transparent_padding_px: int = 50
    # Modo y calidad
    mode: str = ProcessingMode.AUTO.value
    quality: str = QualityPreset.COMMERCIAL.value
    # ── Pasos del postprocesado (activables individualmente) ──────────────
    remove_particles: bool = True
    remove_particles_min_px: int = 80
    fill_holes: bool = True
    fill_holes_max_px: int = 2000
    close_channels: bool = True
    close_channels_mm: float = 4.0
    merge_regions: bool = True
    merge_regions_mm: float = 2.0
    round_corners: bool = True
    round_corners_mm: float = 0.8
    min_corner_radius_px: int = 8
    remove_spikes: bool = True
    simplify_curves: bool = True
    simplify_curves_mm: float = 0.4
    curve_smooth_iters: int = 2
    # ── Control de fantasmas / semitransparencias internas ────────────────
    ghost_threshold: int = 128
    edge_feather_px: int = 3

    @property
    def master_pixels(self) -> int:
        return round(self.resolved_asset_target_size_cm / 2.54 * self.dpi)

    @property
    def resolved_asset_target_size_cm(self) -> float:
        """Lado mayor rasterizado; excluye el padding transparente.

        Sin nominal se conserva exactamente el maestro histórico de 5,70 cm.
        Con nominal, la única fuente de la compensación es production_geometry.
        """
        if self.asset_target_size_cm is not None:
            return float(self.asset_target_size_cm)
        if self.nominal_size_cm is None:
            return self.master_size_cm
        from app.planchas.production_geometry import production_max_for_nominal
        return production_max_for_nominal(self.nominal_size_cm)

    @property
    def resolved_content_size_cm(self) -> float:
        """Conserva la proporción interna legacy al ampliar el raster."""
        if self.nominal_size_cm is None and self.asset_target_size_cm is None:
            return self.content_size_cm
        return self.resolved_asset_target_size_cm * self.content_size_cm / self.master_size_cm

    @property
    def print_size_cm(self) -> float:
        return self.resolved_asset_target_size_cm * self.print_scale

    @property
    def is_premium(self) -> bool:
        return self.quality == QualityPreset.PREMIUM.value

    @property
    def is_fast(self) -> bool:
        return self.quality == QualityPreset.FAST.value


@dataclass(slots=True)
class ImageAnalysis:
    """Resultado del análisis de una imagen antes de generar máscaras.

    Campos principales:
        background_type        – "white", "dark", "color", "transparent", "mixed"
        existing_white_border  – True si la imagen ya tiene un borde blanco
        confidence             – 0.0–1.0 confianza en la clasificación
        requires_review        – True si la clasificación es ambigua
    """
    width: int = 0
    height: int = 0
    dpi: tuple[int, int] | None = None
    has_transparency: bool = False
    transparency_ratio: float = 0.0
    format: str = ""
    mode: str = ""
    is_png: bool = False
    case_hypothesis: str = ""
    bg_color: tuple[int, int, int] = (0, 0, 0)
    background_type: str = "mixed"
    existing_white_border: bool = False
    existing_white_border_width: int = 0
    confidence: float = 0.0
    requires_review: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MaskCandidate:
    """Representa una hipótesis de máscara candidata.

    Convención de la máscara binaria (``mask``):
        - 255 (o True) = diseño conservado (foreground).
        - 0  (o False) = fondo eliminado (background).
    """
    name: str
    mask: np.ndarray
    status: str = "raw"
    score: float = 0.0
    confidence: float = 0.0
    scores: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    is_raw: bool = True
    needs_postprocessing: bool = True
    is_postprocessed: bool = False
    discard_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def pil_mask(self):
        """Devuelve la máscara como imagen PIL en modo 'L'."""
        from PIL import Image
        return Image.fromarray(self.mask.astype(np.uint8), mode="L")


@dataclass(slots=True)
class ProcessingDecision:
    """Decisión final sobre qué máscara usar y si requiere revisión."""
    selected_method: str
    score: float
    confidence: float
    requires_review: bool
    warnings: list[str]
    candidate_scores: dict[str, float]
    candidates: list[str]
    mask: np.ndarray | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StickerResult:
    """Resultado final del procesamiento de un sticker.

    Reemplaza a ProcessingResult con una estructura más clara.
    Mantiene compatibilidad con el código existente a través de
    ``artifacts``, ``analysis`` y ``profile``.
    """
    job_id: str
    source_path: str
    output_dir: str
    status: str
    quality_status: str
    quality_notes: list[str]
    analysis: dict[str, Any]
    artifacts: dict[str, str]
    profile: dict[str, Any]
    duplicate_path: str = ""
    duplicate_score: float = 0.0
    # Campos nuevos para el historial
    processing_mode: str = ""
    classification: str = ""
    selected_mask_name: str = ""
    confidence: float = 0.0
    parameters: dict[str, Any] = field(default_factory=dict)
    manual_edits: list[dict[str, Any]] = field(default_factory=list)
    exported_path: str = ""
    created_at: str = ""

    @classmethod
    def from_processing_result(cls, pr) -> "StickerResult":
        """Convierte un ProcessingResult heredado en StickerResult."""
        return cls(
            job_id=pr.job_id,
            source_path=pr.source_path,
            output_dir=pr.output_dir,
            status=pr.status,
            quality_status=pr.quality_status,
            quality_notes=pr.quality_notes,
            analysis=pr.analysis,
            artifacts=pr.artifacts,
            profile=pr.profile,
            duplicate_path=getattr(pr, "duplicate_path", ""),
            duplicate_score=getattr(pr, "duplicate_score", 0.0),
        )


@dataclass(slots=True)
class StickerMasks:
    """Contenedor de máscaras derivadas durante el postprocesado."""
    subject_mask: Any | None = None
    print_mask: Any | None = None
    white_base_mask: Any | None = None
    cut_mask: Any | None = None
    registration_mask: Any | None = None
    protection_mask: Any | None = None


@dataclass(slots=True)
class JobHistoryEntry:
    """Entrada del historial por imagen."""
    original_file: str
    processed_at: str
    profile_used: str
    classification: str
    selected_mask: str
    confidence: float
    parameters: dict[str, Any]
    manual_edits: list[dict[str, Any]]
    approved_result: bool
    exported_path: str
    status: str = JobStatus.PENDING.value
    result_path: str = ""
