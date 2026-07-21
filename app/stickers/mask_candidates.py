"""Estructuras y utilidades para el sistema de candidatos de máscaras.

Esta fase implementa un sistema inicial de candidatos para seleccionar la
mejor máscara sin reemplazar el flujo heredado actual.

Convención de máscaras binarias:
  - True o 255 = diseño conservado / foreground (primer plano).
  - False o 0 = fondo eliminado.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

# Pesos de scoring deterministas para fase 1.
WEIGHTS = {
    "alpha_match": 0.25,          # coincidencia con alpha original confiable
    "stability": 0.10,            # estabilidad básica del contorno
}

# Umbrales para decisión de confianza.
CONFIDENCE_THRESHOLDS = {
    "auto": 90.0,
    "warn": 70.0,
}

# Requisitos de validación para mascaras.
MIN_SUBJECT_AREA_RATIO = 0.001
MAX_RECTANGULARITY_RATIO = 0.96
MAX_FULL_IMAGE_RATIO = 0.95


@dataclass(slots=True)
class ImageAnalysis:
    width: int
    height: int
    dpi: tuple[int, int] | None
    has_transparency: bool
    transparency_ratio: float
    format: str
    mode: str
    is_png: bool
    case_hypothesis: str
    bg_color: tuple[int, int, int]


@dataclass(slots=True)
class MaskCandidate:
    """Representa una hipótesis de máscara candidata.

    Convención de la máscara binaria (`mask`):
      - 255 (o True) = diseño conservado (foreground).
      - 0 (o False) = fondo eliminado (background).
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

    def pil_mask(self):
        return Image.fromarray(self.mask.astype(np.uint8), mode="L")


@dataclass(slots=True)
class ProcessingDecision:
    selected_method: str
    score: float
    confidence: float
    requires_review: bool
    warnings: list[str]
    candidate_scores: dict[str, float]
    candidates: list[str]


@dataclass(slots=True)
class StickerMasks:
    subject_mask: Any | None = None
    print_mask: Any | None = None
    white_base_mask: Any | None = None
    cut_mask: Any | None = None
    registration_mask: Any | None = None
    protection_mask: Any | None = None


class MaskCandidateError(ValueError):
    pass


def get_best_mask_from_image(image_path: str | Path) -> tuple[np.ndarray, dict]:
    """Función de conveniencia para obtener la mejor máscara de una imagen.
    
    Esta función está diseñada para ser usada por el pipeline principal.
    
    Args:
        image_path: Ruta a la imagen a procesar
        
    Returns:
        Tupla de (máscara binaria numpy, metadatos de decisión)
        La máscara está en formato (height, width) con valores 0/255
        
    Raises:
        MaskCandidateError: Si no se puede generar una máscara válida
    """
    try:
        candidates = generate_and_score_all_candidates(image_path)
        winner, decision = select_candidate(candidates)
        
        if winner.discard_reason is not None:
            raise MaskCandidateError(
                f"No se pudo generar máscara válida: {winner.discard_reason}"
            )
        
        metadata = {
            "method": winner.name,
            "score": winner.score,
            "confidence": winner.confidence,
            "requires_review": decision.requires_review,
            "warnings": decision.warnings,
            "metrics": winner.scores,
        }
        
        return winner.mask, metadata
        
    except Exception as e:
        raise MaskCandidateError(f"Error al generar máscara: {e}") from e


def normalize_mask(mask: Any, size: tuple[int, int]) -> np.ndarray:
    """Normaliza una máscara a ndarray binario uint8 con 0/255.

    Convención:
      - 255 = diseño conservado (foreground).
      - 0 = fondo eliminado (background).
    
    Args:
        mask: Máscara a normalizar (ndarray, PIL Image, o array-like)
        size: Tamaño esperado como (height, width) en formato numpy
    """
    if mask is None:
        raise MaskCandidateError("Mask is None")
    try:
        if isinstance(mask, np.ndarray):
            arr = mask
        else:
            if isinstance(mask, Image.Image):
                arr = np.asarray(mask.convert("L"), dtype=np.uint8)
            else:
                arr = np.asarray(mask, dtype=np.uint8)
    except Exception as exc:
        raise MaskCandidateError(f"Error converting mask: {exc}") from exc

    if arr.ndim != 2:
        raise MaskCandidateError("Mask must be single-channel")
    
    # Verificar dimensiones (arr.shape es (height, width))
    if arr.shape != size:
        raise MaskCandidateError(f"Mask size mismatch: expected {size}, got {arr.shape}")

    arr = arr.astype(np.uint8)
    arr = np.where(arr > 127, 255, 0).astype(np.uint8)
    return arr


def validate_candidate(candidate: MaskCandidate, size: tuple[int, int]) -> MaskCandidate:
    """Valida que el candidato tenga una máscara binaria y dimensiones correctas.
    
    Args:
        candidate: Candidato a validar
        size: Tamaño esperado como (height, width) en formato numpy
    """
    candidate.mask = normalize_mask(candidate.mask, size)
    if candidate.mask.shape != size:
        raise MaskCandidateError(
            f"Candidate '{candidate.name}' has invalid mask shape {candidate.mask.shape}."
        )
    area = candidate.mask.sum() / 255
    total = size[0] * size[1]  # height * width
    if area < max(1, total * MIN_SUBJECT_AREA_RATIO):
        raise MaskCandidateError(f"Candidate '{candidate.name}' contains too little subject area.")
    if area / total >= MAX_FULL_IMAGE_RATIO:
        raise MaskCandidateError(
            f"Candidate '{candidate.name}' covers too much of the image ({area / total:.2f})."
        )
    bbox = _mask_bbox(candidate.mask)
    if bbox is None:
        raise MaskCandidateError(f"Candidate '{candidate.name}' has no subject after mask extraction.")

    return candidate


def _mask_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(mask == 255)
    if len(xs) == 0 or len(ys) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _image_to_lab(rgb: np.ndarray) -> np.ndarray:
    try:
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
        return lab.astype(np.float32)
    except Exception:
        r = rgb[:,:,0].astype(np.float32) / 255.0
        g = rgb[:,:,1].astype(np.float32) / 255.0
        b = rgb[:,:,2].astype(np.float32) / 255.0
        x = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
        y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
        z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b
        xyz = np.stack((x, y, z), axis=-1)
        eps = 216.0 / 24389.0
        kappa = 24389.0 / 27.0
        f = np.where(xyz > eps, np.cbrt(xyz), (kappa * xyz + 16.0) / 116.0)
        L = 116.0 * f[:,:,1] - 16.0
        a = 500.0 * (f[:,:,0] - f[:,:,1])
        b = 200.0 * (f[:,:,1] - f[:,:,2])
        lab = np.stack((L, a, b), axis=-1)
        return lab


def _color_distance_lab(c0: np.ndarray, c1: np.ndarray) -> np.ndarray:
    return np.linalg.norm(c0 - c1, axis=-1)


def _perimeter_seed_points(width: int, height: int, steps: int = 7) -> list[tuple[int, int]]:
    coords = []
    xs = [round(i * (width - 1) / steps) for i in range(steps + 1)]
    ys = [round(i * (height - 1) / steps) for i in range(steps + 1)]
    for x in xs:
        coords.append((x, 0))
        coords.append((x, height - 1))
    for y in ys[1:-1]:
        coords.append((0, y))
        coords.append((width - 1, y))
    return coords


def _sample_background_colors(rgb: np.ndarray, points: list[tuple[int, int]]) -> np.ndarray:
    samples = [rgb[y, x] for x, y in points]
    return np.asarray(samples, dtype=np.float32)


def _adaptive_tolerance(lab_samples: np.ndarray) -> float:
    if len(lab_samples) == 0:
        return 24.0
    diffs = np.linalg.norm(lab_samples - np.median(lab_samples, axis=0), axis=1)
    base = float(np.percentile(diffs, 85))
    return max(12.0, min(60.0, base * 1.4 + 4.0))


def _compute_edge_map(rgb: np.ndarray) -> np.ndarray:
    gray = (0.299 * rgb[:,:,0] + 0.587 * rgb[:,:,1] + 0.114 * rgb[:,:,2]).astype(np.float32)
    gx = np.abs(gray[:, 1:] - gray[:, :-1])
    gy = np.abs(gray[1:, :] - gray[:-1, :])
    edge = np.zeros_like(gray)
    edge[:, :-1] = np.maximum(edge[:, :-1], gx)
    edge[:-1, :] = np.maximum(edge[:-1, :], gy)
    return edge


def _flood_fill_background(rgb: np.ndarray, threshold: float, use_lab: bool = True) -> np.ndarray:
    """Flood fill desde los bordes para identificar el fondo.
    
    Returns:
        Máscara uint8 donde 255 = fondo, 0 = diseño
    
    Raises:
        ValueError si la imagen es inválida
    """
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(f"RGB array must have shape (H, W, 3), got {rgb.shape}")
    
    h, w, _ = rgb.shape
    if h < 1 or w < 1:
        raise ValueError(f"Invalid image dimensions: {h}x{w}")
    
    try:
        lab = _image_to_lab(rgb) if use_lab else rgb.astype(np.float32)
        seeds = _perimeter_seed_points(w, h)
        sample_lab = _sample_background_colors(lab, seeds)
        median_bg = np.median(sample_lab, axis=0)
        edge_map = _compute_edge_map(rgb)
        max_edge = edge_map.max() if edge_map.size else 1.0
        edge_threshold = max(15.0, max_edge * 0.45)

        visited = np.zeros((h, w), dtype=bool)
        queue = deque()
        for x, y in seeds:
            if 0 <= x < w and 0 <= y < h and not visited[y, x]:
                dist = float(np.linalg.norm(lab[y, x] - median_bg))
                if dist <= threshold:
                    visited[y, x] = True
                    queue.append((x, y))

        while queue:
            x, y = queue.popleft()
            for dx, dy in ((1,0),(-1,0),(0,1),(0,-1), (1,1), (1,-1), (-1,1), (-1,-1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx]:
                    dist = float(np.linalg.norm(lab[ny, nx] - median_bg))
                    if dist <= threshold and edge_map[ny, nx] <= edge_threshold:
                        visited[ny, nx] = True
                        queue.append((nx, ny))
        return np.where(visited, 255, 0).astype(np.uint8)
    except Exception as e:
        raise ValueError(f"Flood fill failed: {e}") from e


def _color_similarity_background(rgb: np.ndarray, threshold: float, use_lab: bool = True) -> np.ndarray:
    """Identifica el fondo por similitud de color con los bordes (sin conectividad).
    
    Returns:
        Máscara uint8 donde 255 = fondo, 0 = diseño
    
    Raises:
        ValueError si la imagen es inválida
    """
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(f"RGB array must have shape (H, W, 3), got {rgb.shape}")
    
    h, w, _ = rgb.shape
    if h < 1 or w < 1:
        raise ValueError(f"Invalid image dimensions: {h}x{w}")
    
    try:
        lab = _image_to_lab(rgb) if use_lab else rgb.astype(np.float32)
        seeds = _perimeter_seed_points(w, h)
        sample_lab = _sample_background_colors(lab, seeds)
        median_bg = np.median(sample_lab, axis=0)
        dists = np.linalg.norm(lab - median_bg, axis=-1)
        visited = dists <= threshold
        return np.where(visited, 255, 0).astype(np.uint8)
    except Exception as e:
        raise ValueError(f"Color similarity calculation failed: {e}") from e


def _get_intelligent_components(mask: np.ndarray) -> np.ndarray:
    """Conserva el componente principal, más secundarios significativos o cercanos.
    
    Returns:
        Máscara con componentes inteligentemente seleccionados
        
    Raises:
        ValueError si la máscara es inválida
    """
    if mask.ndim != 2:
        raise ValueError(f"Mask must be 2D, got shape {mask.shape}")
    
    try:
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if num_labels <= 1:
            return np.zeros_like(mask)

        # El label 0 es fondo. Buscamos el componente más grande entre 1..num_labels-1.
        areas = stats[1:, cv2.CC_STAT_AREA]
        largest_idx = int(np.argmax(areas)) + 1
        largest_area = stats[largest_idx, cv2.CC_STAT_AREA]

        keep_labels = {largest_idx}

        cx_M = centroids[largest_idx, 0]
        cy_M = centroids[largest_idx, 1]

        h, w = mask.shape
        max_dim = max(w, h)

        # Caja delimitadora del componente principal
        x1_M = stats[largest_idx, cv2.CC_STAT_LEFT]
        y1_M = stats[largest_idx, cv2.CC_STAT_TOP]
        w_M = stats[largest_idx, cv2.CC_STAT_WIDTH]
        h_M = stats[largest_idx, cv2.CC_STAT_HEIGHT]

        for i in range(1, num_labels):
            if i == largest_idx:
                continue

            area_i = stats[i, cv2.CC_STAT_AREA]
            cx_i = centroids[i, 0]
            cy_i = centroids[i, 1]

            # Condición 1: Componente secundario significativo (área relativa >= 5% de la principal)
            is_significant = (area_i >= 0.05 * largest_area)

            # Condición 2: Componentes cercanos al componente principal (distancia de bbox < 15% de la dimensión máxima)
            x1_i = stats[i, cv2.CC_STAT_LEFT]
            y1_i = stats[i, cv2.CC_STAT_TOP]
            w_i = stats[i, cv2.CC_STAT_WIDTH]
            h_i = stats[i, cv2.CC_STAT_HEIGHT]

            dx = max(0, x1_M - (x1_i + w_i), x1_i - (x1_M + w_M))
            dy = max(0, y1_M - (y1_i + h_i), y1_i - (y1_M + h_M))
            dist_bbox = math.sqrt(dx**2 + dy**2)

            is_close = (dist_bbox < 0.15 * max_dim)

            if is_significant or is_close:
                keep_labels.add(i)

        result = np.zeros_like(mask)
        for lbl in keep_labels:
            result[labels == lbl] = 255
        return result
    except Exception as e:
        raise ValueError(f"Component analysis failed: {e}") from e


def _mask_metrics(mask: np.ndarray) -> dict[str, float]:
    total = mask.size
    area = mask.sum() / 255
    bbox = _mask_bbox(mask)
    if bbox is None:
        return {
            "area_ratio": 0.0,
            "rectangularity": 0.0,
            "component_count": 0.0,
            "small_particles": 0.0,
        }
    x1, y1, x2, y2 = bbox
    bbox_area = (x2 - x1 + 1) * (y2 - y1 + 1)
    rectangularity = (area / bbox_area) if bbox_area > 0 else 1.0
    components = 0
    small_particles = 0
    visited = np.zeros_like(mask, dtype=bool)
    for y in range(mask.shape[0]):
        for x in range(mask.shape[1]):
            if mask[y,x] == 255 and not visited[y,x]:
                components += 1
                size = 0
                queue = deque([(x,y)])
                visited[y,x] = True
                while queue:
                    cx, cy = queue.popleft()
                    size += 1
                    for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
                        nx, ny = cx+dx, cy+dy
                        if 0 <= nx < mask.shape[1] and 0 <= ny < mask.shape[0] and not visited[ny,nx] and mask[ny,nx] == 255:
                            visited[ny,nx] = True
                            queue.append((nx, ny))
                if size <= max(1, total * 0.002):
                    small_particles += 1
    return {
        "area_ratio": area / total,
        "rectangularity": min(1.0, rectangularity),
        "component_count": float(components),
        "small_particles": float(small_particles),
    }


def _mask_edge_residual(mask: np.ndarray, width: int = 12) -> float:
    if width < 1:
        return 0.0
    h, w = mask.shape
    top = mask[:width, :]
    bottom = mask[-width:, :]
    left = mask[:, :width]
    right = mask[:, -width:]
    edge = np.concatenate([top.ravel(), bottom.ravel(), left.ravel(), right.ravel()])
    return 1.0 - (np.count_nonzero(edge == 0) / max(1, edge.size))


def _alpha_match(mask: np.ndarray, alpha_mask: np.ndarray) -> float:
    if alpha_mask is None or alpha_mask.shape != mask.shape:
        return 0.0
    intersection = np.count_nonzero((mask == 255) & (alpha_mask == 255))
    union = np.count_nonzero((mask == 255) | (alpha_mask == 255))
    if union == 0:
        return 0.0
    return intersection / union


def _mask_stability(mask: np.ndarray) -> float:
    """Calcula estabilidad de la máscara con fallback si scipy no está disponible."""
    try:
        from scipy.ndimage import binary_erosion, binary_dilation

        binary = mask == 255
        eroded = binary_erosion(binary, structure=np.ones((3,3)), iterations=1)
        dilated = binary_dilation(binary, structure=np.ones((3,3)), iterations=1)
        stable = np.count_nonzero((binary == eroded) | (binary == dilated))
        return stable / max(1, mask.size)
    except (ImportError, ModuleNotFoundError):
        # Fallback usando cv2 cuando scipy no está disponible
        binary = (mask == 255).astype(np.uint8)
        kernel = np.ones((3, 3), dtype=np.uint8)
        eroded = cv2.erode(binary, kernel, iterations=1)
        dilated = cv2.dilate(binary, kernel, iterations=1)
        stable = np.count_nonzero((binary == eroded) | (binary == dilated))
        return float(stable / max(1, mask.size))


def _score_mask(
    mask: np.ndarray,
    alpha_mask: np.ndarray | None,
    rgba: Image.Image
) -> tuple[float, dict[str, float]]:
    """Calcula el score normalizado de 0.0 a 1.0 y el desglose completo de métricas."""
    h, w = mask.shape
    total_pixels = mask.size
    area_ratio = float(np.count_nonzero(mask == 255) / total_pixels)

    # 1. Components
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    component_count = float(max(0, num_labels - 1))
    significant_component_count = 0.0
    for i in range(1, num_labels):
        if stats[i, cv2.CC_STAT_AREA] >= 0.015 * total_pixels:
            significant_component_count += 1.0

    # 2. Edge Occupancy and background remnants
    perimeter_mask = np.zeros((h, w), dtype=bool)
    perimeter_mask[0, :] = True
    perimeter_mask[-1, :] = True
    perimeter_mask[:, 0] = True
    perimeter_mask[:, -1] = True
    total_perimeter_pixels = np.count_nonzero(perimeter_mask)
    perimeter_fg_pixels = np.count_nonzero(mask[perimeter_mask] == 255)
    edge_occupancy_ratio = float(perimeter_fg_pixels / total_perimeter_pixels)

    # Color similarity of perimeter pixels to estimated background color
    rgb = np.asarray(rgba.convert("RGB"), dtype=np.uint8)
    lab = _image_to_lab(rgb)
    seeds = _perimeter_seed_points(w, h)
    sample_lab = _sample_background_colors(lab, seeds)
    median_bg = np.median(sample_lab, axis=0)

    border_fg_indices = np.where((mask == 255) & perimeter_mask)
    similar_border_fg_count = 0
    for cy, cx in zip(*border_fg_indices):
        dist = np.linalg.norm(lab[cy, cx] - median_bg)
        if dist < 25.0:
            similar_border_fg_count += 1
    perimeter_bg_similarity = float(similar_border_fg_count / total_perimeter_pixels)

    # Longest continuous run of foreground along perimeter
    perimeter_pixels = []
    for x in range(w):
        perimeter_pixels.append(mask[0, x])
    for y in range(1, h):
        perimeter_pixels.append(mask[y, w-1])
    for x in range(w-2, -1, -1):
        perimeter_pixels.append(mask[h-1, x])
    for y in range(h-2, 0, -1):
        perimeter_pixels.append(mask[y, 0])

    max_run = 0
    current_run = 0
    for val in perimeter_pixels:
        if val == 255:
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 0
    if len(perimeter_pixels) > 0 and perimeter_pixels[0] == 255 and perimeter_pixels[-1] == 255:
        start_run = 0
        for val in perimeter_pixels:
            if val == 255:
                start_run += 1
            else:
                break
        end_run = 0
        for val in reversed(perimeter_pixels):
            if val == 255:
                end_run += 1
            else:
                break
        max_run = max(max_run, start_run + end_run)
    continuous_run_ratio = float(max_run / max(1, len(perimeter_pixels)))

    # 3. Holes analysis (separating structured vs irregular)
    inverted_mask = (255 - mask).astype(np.uint8)
    num_labels_i, labels_i, stats_i, centroids_i = cv2.connectedComponentsWithStats(inverted_mask, connectivity=8)
    hole_count = 0.0
    irregular_holes_count = 0.0
    irregular_holes_area = 0.0
    for i in range(1, num_labels_i):
        left = stats_i[i, cv2.CC_STAT_LEFT]
        top = stats_i[i, cv2.CC_STAT_TOP]
        width = stats_i[i, cv2.CC_STAT_WIDTH]
        height = stats_i[i, cv2.CC_STAT_HEIGHT]
        area = stats_i[i, cv2.CC_STAT_AREA]

        touches_border = (left == 0) or (top == 0) or (left + width >= w) or (top + height >= h)
        if not touches_border:
            hole_count += 1.0
            # Compute compactness of this hole
            crop = (labels_i[top:top+height, left:left+width] == i).astype(np.uint8) * 255
            contours_h, _ = cv2.findContours(crop, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours_h:
                perimeter = cv2.arcLength(contours_h[0], True)
            else:
                perimeter = 2 * (width + height)

            compactness = (perimeter ** 2) / (4 * math.pi * area) if area > 0 else 0.0
            # Irregular if tiny area (< 0.05% image) or high compactness (> 6.0)
            is_irregular = (area < max(15, 0.0005 * total_pixels)) or (compactness > 6.0)
            if is_irregular:
                irregular_holes_count += 1.0
                irregular_holes_area += area

    irregular_hole_ratio = float(irregular_holes_count / max(1.0, hole_count)) if hole_count > 0 else 0.0

    # 4. Contour complexity
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        largest_contour = max(contours, key=cv2.contourArea)
        c_area = cv2.contourArea(largest_contour)
        c_perimeter = cv2.arcLength(largest_contour, True)
        contour_complexity = float((c_perimeter ** 2) / (4 * math.pi * c_area)) if c_area > 0 else 0.0
    else:
        contour_complexity = 0.0

    # 5. Fragmentation & background removed ratio
    fragmentation = float((component_count - significant_component_count) / max(1.0, component_count))
    background_removed_ratio = 1.0 - area_ratio

    # 6. Stability
    try:
        stability = _mask_stability(mask)
    except Exception:
        stability = 0.5

    # 7. Alpha score comparison
    alpha_score = 0.0
    if alpha_mask is not None:
        alpha_score = _alpha_match(mask, alpha_mask)

    # 7.5. Color similarity of all foreground pixels to background color (foreground bg similarity)
    # This helps penalize candidates that fill legitimate background holes.
    similar_fg_count = 0
    foreground_pixels = np.where(mask == 255)
    total_fg_pixels = len(foreground_pixels[0])
    if total_fg_pixels > 0:
        fg_labs = lab[foreground_pixels[0], foreground_pixels[1]]
        dists_fg = np.linalg.norm(fg_labs - median_bg, axis=-1)
        similar_fg_count = np.count_nonzero(dists_fg < 20.0)
        fg_bg_similarity_ratio = float(similar_fg_count / total_fg_pixels)
    else:
        fg_bg_similarity_ratio = 0.0

    fg_bg_similarity_penalty = 0.35 * fg_bg_similarity_ratio

    # ── BASE SCORE BEFORE PENALTIES ──────────────────────────────────────────
    if alpha_mask is not None:
        score_before_penalties = float(alpha_score)
    else:
        score_before_penalties = float(0.85 + 0.15 * stability)

    # ── PENALTIES calculation ────────────────────────────────────────────────
    # Excessive design removal penalty
    excessive_removal_penalty = 0.0
    if area_ratio < 0.05:
        excessive_removal_penalty = 0.8 + 0.2 * (1.0 - area_ratio / 0.05)
    elif area_ratio < 0.10:
        excessive_removal_penalty = 0.3 * (0.10 - area_ratio) / 0.05

    # Large background remnants penalty
    bg_remnants_penalty = 0.0
    if edge_occupancy_ratio > 0.05 and perimeter_bg_similarity > 0.02:
        bg_remnants_penalty += 0.4 * edge_occupancy_ratio + 0.3 * perimeter_bg_similarity
    if continuous_run_ratio > 0.25:
        bg_remnants_penalty += 0.3 * continuous_run_ratio
    bg_remnants_penalty = min(1.0, bg_remnants_penalty)

    # Irregular holes penalty (structured holes are NOT penalized)
    internal_holes_penalty = 0.0
    if hole_count > 0:
        internal_holes_penalty += 0.4 * irregular_hole_ratio
        internal_holes_penalty += 0.1 * min(irregular_holes_count, 3.0) / 3.0

    # Fragmented borders penalty
    fragmentation_penalty = 0.0
    if fragmentation > 0.2 or component_count > 3:
        fragmentation_penalty += 0.2 * fragmentation + 0.1 * min(component_count - 1.0, 5.0) / 5.0
    if contour_complexity > 8.0:
        fragmentation_penalty += 0.2 * min((contour_complexity - 8.0) / 20.0, 1.0)
    fragmentation_penalty = min(1.0, fragmentation_penalty)

    # Almost empty or almost full penalty
    almost_empty_or_full_penalty = 0.0
    if area_ratio < 0.02 or area_ratio > 0.95:
        almost_empty_or_full_penalty = 0.9

    total_penalty = float(
        excessive_removal_penalty +
        bg_remnants_penalty +
        internal_holes_penalty +
        fragmentation_penalty +
        almost_empty_or_full_penalty +
        fg_bg_similarity_penalty
    )
    total_penalty = min(1.0, total_penalty)

    final_score = max(0.0, score_before_penalties - total_penalty)

    metrics = {
        "area_ratio": area_ratio,
        "component_count": component_count,
        "significant_component_count": significant_component_count,
        "edge_occupancy_ratio": edge_occupancy_ratio,
        "hole_count": hole_count,
        "irregular_hole_ratio": irregular_hole_ratio,
        "contour_complexity": contour_complexity,
        "fragmentation": fragmentation,
        "background_removed_ratio": background_removed_ratio,
        "score_before_penalties": score_before_penalties,
        "total_penalty": total_penalty,
        "final_score": final_score,
    }

    return final_score, metrics


def select_candidate(candidates: list[MaskCandidate]) -> tuple[MaskCandidate, ProcessingDecision]:
    """Selecciona el mejor candidato basado en el score."""
    sorted_candidates = sorted(
        candidates,
        key=lambda c: (c.discard_reason is not None, -c.score, c.name),
    )
    if not sorted_candidates:
        raise MaskCandidateError("No valid candidates available")

    winner = sorted_candidates[0]

    # Si el ganador está descartado, no hay candidatos válidos utilizables
    if winner.discard_reason is not None or winner.score == 0.0:
        decision = ProcessingDecision(
            selected_method=winner.name,
            score=0.0,
            confidence=0.0,
            requires_review=True,
            warnings=["No valid candidate found"] + winner.warnings,
            candidate_scores={c.name: 0.0 for c in sorted_candidates},
            candidates=[c.name for c in sorted_candidates],
        )
        winner.confidence = 0.0
        return winner, decision

    second_score = sorted_candidates[1].score if (len(sorted_candidates) > 1 and sorted_candidates[1].discard_reason is None) else 0.0
    gap = winner.score - second_score

    # Convertimos score final (0.0-1.0) a confianza (0-100)
    base_confidence = winner.score * 100.0
    gap_bonus = min(10.0, gap * 100.0)
    confidence = base_confidence + gap_bonus

    confidence -= 10.0 * min(len(winner.warnings), 2)

    # Si el score final es débil, limitamos la confianza para forzar revisión manual
    if winner.score < 0.60:
        confidence = min(confidence, 50.0)

    confidence = max(0.0, min(100.0, confidence))
    requires_review = confidence < CONFIDENCE_THRESHOLDS["warn"]

    decision = ProcessingDecision(
        selected_method=winner.name,
        score=round(winner.score, 4),
        confidence=round(confidence, 2),
        requires_review=requires_review,
        warnings=winner.warnings.copy(),
        candidate_scores={c.name: round(c.score, 4) for c in sorted_candidates},
        candidates=[c.name for c in sorted_candidates],
    )
    winner.confidence = confidence
    return winner, decision


def build_alpha_candidate(rgba: Image.Image, analysis: ImageAnalysis) -> MaskCandidate:
    """Extrae el candidato basado en el canal alpha original de la imagen.

    Binarización:
      - alpha > 12 = 255 (diseño conservado).
      - alpha <= 12 = 0 (fondo eliminado).
      Este umbral bajo de 12 se utiliza para omitir ruido de compresión semi-transparente
      y preservar exactamente el diseño útil original.
    """
    alpha = np.asarray(rgba.getchannel("A").convert("L"), dtype=np.uint8)
    if not analysis.has_transparency:
        raise MaskCandidateError("Alpha is fully opaque or absent")
    if alpha.max() == 0:
        raise MaskCandidateError("Alpha is fully transparent")

    mask = np.where(alpha > 12, 255, 0).astype(np.uint8)
    candidate = MaskCandidate(
        name="alpha_original",
        mask=mask,
        status="raw",
        diagnostics={
            "transparency_ratio": analysis.transparency_ratio,
            "alpha_extrema": [int(alpha.min()), int(alpha.max())],
        },
        is_raw=True,
        needs_postprocessing=True,
        is_postprocessed=False,
    )
    return candidate


def build_border_connected_background_candidate(rgba: Image.Image, analysis: ImageAnalysis) -> MaskCandidate:
    """Genera candidato por conectividad desde los bordes con tolerancia adaptativa."""
    rgb = np.asarray(rgba.convert("RGB"), dtype=np.uint8)
    lab = _image_to_lab(rgb)
    seeds = _perimeter_seed_points(analysis.width, analysis.height)
    sample = _sample_background_colors(lab, seeds)
    tolerance = _adaptive_tolerance(sample)
    bg_mask = _flood_fill_background(rgb, tolerance, use_lab=True)
    subject_mask = np.where(bg_mask == 255, 0, 255).astype(np.uint8)
    candidate = MaskCandidate(
        name="border_connected_adaptive",
        mask=subject_mask,
        status="raw",
        diagnostics={
            "background_tolerance": tolerance,
            "perimeter_seeds": len(seeds),
            "use_lab": True,
            "bg_color": analysis.bg_color,
        },
        is_raw=True,
        needs_postprocessing=True,
        is_postprocessed=False,
    )
    return candidate


def build_border_connected_candidate(rgba: Image.Image, analysis: ImageAnalysis, tolerance: float) -> MaskCandidate:
    """Genera candidato por conectividad desde los bordes con una tolerancia LAB explícita."""
    rgb = np.asarray(rgba.convert("RGB"), dtype=np.uint8)
    bg_mask = _flood_fill_background(rgb, tolerance, use_lab=True)
    subject_mask = np.where(bg_mask == 255, 0, 255).astype(np.uint8)
    candidate = MaskCandidate(
        name=f"border_connected_{tolerance}",
        mask=subject_mask,
        status="raw",
        diagnostics={
            "background_tolerance": tolerance,
            "use_lab": True,
            "bg_color": analysis.bg_color,
        },
        is_raw=True,
        needs_postprocessing=True,
        is_postprocessed=False,
    )
    return candidate


def build_color_similarity_candidate(rgba: Image.Image, analysis: ImageAnalysis, tolerance: float) -> MaskCandidate:
    """Genera candidato por similitud de color con los bordes (ignora conectividad)."""
    rgb = np.asarray(rgba.convert("RGB"), dtype=np.uint8)
    bg_mask = _color_similarity_background(rgb, tolerance, use_lab=True)
    subject_mask = np.where(bg_mask == 255, 0, 255).astype(np.uint8)
    candidate = MaskCandidate(
        name=f"color_similarity_{tolerance}",
        mask=subject_mask,
        status="raw",
        diagnostics={
            "background_tolerance": tolerance,
            "use_lab": True,
            "bg_color": analysis.bg_color,
        },
        is_raw=True,
        needs_postprocessing=True,
        is_postprocessed=False,
    )
    return candidate


def build_legacy_candidate(mask: np.ndarray, analysis: ImageAnalysis) -> MaskCandidate:
    candidate = MaskCandidate(
        name="legacy_pipeline",
        mask=mask,
        status="legacy",
        diagnostics={
            "note": "Mask extracted from current pipeline logic",
        },
        is_raw=False,
        needs_postprocessing=False,
        is_postprocessed=True,
    )
    return candidate


def analyze_image_for_candidates(rgba: Image.Image) -> ImageAnalysis:
    """Analiza propiedades de la imagen para determinar canales, transparencia y color de fondo."""
    w, h = rgba.size
    alpha = rgba.getchannel("A")
    extrema = alpha.getextrema()
    has_transparency = extrema[0] < 254
    transparency_ratio = np.count_nonzero(np.asarray(alpha) < 254) / alpha.size

    # Color de fondo de muestra estimativo (mediana de los bordes)
    pix = rgba.convert("RGB").resize((64, 64))
    edge_pixels = []
    for x in range(64):
        edge_pixels.append(pix.getpixel((x, 0)))
        edge_pixels.append(pix.getpixel((x, 63)))
    for y in range(1, 63):
        edge_pixels.append(pix.getpixel((0, y)))
        edge_pixels.append(pix.getpixel((63, y)))

    r_vals = [p[0] for p in edge_pixels]
    g_vals = [p[1] for p in edge_pixels]
    b_vals = [p[2] for p in edge_pixels]
    bg_color = (int(np.median(r_vals)), int(np.median(g_vals)), int(np.median(b_vals)))

    return ImageAnalysis(
        width=w,
        height=h,
        dpi=rgba.info.get("dpi"),
        has_transparency=has_transparency,
        transparency_ratio=transparency_ratio,
        format=getattr(rgba, "format", "PNG") or "PNG",
        mode=rgba.mode,
        is_png=(getattr(rgba, "format", "") or "").upper() == "PNG",
        case_hypothesis="A" if has_transparency else "C",
        bg_color=bg_color
    )


def generate_and_score_all_candidates(image_path_or_ndarray: str | Path | np.ndarray | Image.Image) -> list[MaskCandidate]:
    """Genera todos los candidatos de máscara y los devuelve ordenados de mayor a menor score.

    Parámetros:
      - image_path_or_ndarray: Ruta a un archivo de imagen (str o Path), imagen RGBA (numpy.ndarray de np.uint8) o PIL.Image.Image.

    Convención de máscaras binarias devueltas en MaskCandidate.mask:
      - 255 = diseño conservado (foreground).
      - 0 = fondo eliminado (background).

    Los candidatos descartados permanecen en la lista con score=0.0, discard_reason especificado,
    y se ordenan de manera determinista al final de la lista.
    """
    # 1. Validaciones explícitas de entrada
    if isinstance(image_path_or_ndarray, (str, Path)):
        path = Path(image_path_or_ndarray)
        if not path.exists():
            raise FileNotFoundError(f"La ruta del archivo no existe: {path}")
        try:
            rgba_img = Image.open(path).convert("RGBA")
        except Exception as exc:
            raise ValueError(f"Error al abrir la imagen en {path}: {exc}") from exc
    elif isinstance(image_path_or_ndarray, np.ndarray):
        arr = image_path_or_ndarray
        if arr.ndim != 3:
            raise ValueError(f"La imagen array debe tener 3 dimensiones (H, W, C), se recibió ndim={arr.ndim}")
        if arr.shape[2] != 4:
            raise ValueError(f"La imagen array debe tener 4 canales (RGBA), se recibió shape={arr.shape}")
        if arr.dtype != np.uint8:
            raise ValueError(f"El tipo de datos del array debe ser np.uint8, se recibió dtype={arr.dtype}")
        try:
            rgba_img = Image.fromarray(arr, mode="RGBA")
        except Exception as exc:
            raise ValueError(f"Error al convertir array de entrada a imagen PIL: {exc}") from exc
    elif isinstance(image_path_or_ndarray, Image.Image):
        rgba_img = image_path_or_ndarray.convert("RGBA")
    else:
        raise TypeError("El argumento de entrada debe ser de tipo str, Path, numpy.ndarray o PIL.Image.Image")

    # 2. Análisis preliminar de la imagen
    analysis = analyze_image_for_candidates(rgba_img)
    w, h = rgba_img.size  # PIL usa (width, height)
    size_hw = (h, w)  # Numpy usa (height, width)

    candidates: list[MaskCandidate] = []

    # A. Candidato de transparencia original
    alpha_cand = None
    try:
        alpha_cand = build_alpha_candidate(rgba_img, analysis)
    except Exception as e:
        dummy_mask = np.zeros(size_hw, dtype=np.uint8)  # Usar size_hw para numpy
        alpha_cand = MaskCandidate(
            name="alpha_original",
            mask=dummy_mask,
            discard_reason=f"No transparency detected or fully opaque: {e}",
            status="discarded",
            is_raw=True,
            needs_postprocessing=False,
        )
    candidates.append(alpha_cand)

    # B. Candidatos de conectividad desde los bordes (baja, media, alta tolerancia)
    tolerances = {"low": 15.0, "mid": 30.0, "high": 50.0}
    for tol_name, tol_val in tolerances.items():
        try:
            cand = build_border_connected_candidate(rgba_img, analysis, tol_val)
            cand.name = f"border_connected_{tol_name}"
            candidates.append(cand)
        except Exception as e:
            dummy_mask = np.zeros(size_hw, dtype=np.uint8)
            candidates.append(MaskCandidate(
                name=f"border_connected_{tol_name}",
                mask=dummy_mask,
                discard_reason=f"Generation failed: {e}",
                status="discarded"
            ))

    # C. Candidatos de similitud de color con los bordes (baja, media, alta tolerancia)
    for tol_name, tol_val in tolerances.items():
        try:
            cand = build_color_similarity_candidate(rgba_img, analysis, tol_val)
            cand.name = f"color_similarity_{tol_name}"
            candidates.append(cand)
        except Exception as e:
            dummy_mask = np.zeros(size_hw, dtype=np.uint8)
            candidates.append(MaskCandidate(
                name=f"color_similarity_{tol_name}",
                mask=dummy_mask,
                discard_reason=f"Generation failed: {e}",
                status="discarded"
            ))

    # D. Conservación del componente principal del diseño (inteligente)
    try:
        # Usamos border_connected_mid como base
        base_mask = None
        for c in candidates:
            if c.name == "border_connected_mid" and c.discard_reason is None:
                base_mask = c.mask
                break
        if base_mask is None:
            # Fallback a cualquier candidato válido de bordes
            for c in candidates:
                if "border_connected" in c.name and c.discard_reason is None:
                    base_mask = c.mask
                    break
        if base_mask is not None:
            main_mask = _get_intelligent_components(base_mask)
            main_cand = MaskCandidate(
                name="main_component_preservation",
                mask=main_mask,
                status="raw",
                diagnostics={"source": "intelligent components extraction"},
                is_raw=True,
                needs_postprocessing=True,
            )
            candidates.append(main_cand)
        else:
            raise MaskCandidateError("No base mask available for component preservation extraction")
    except Exception as e:
        dummy_mask = np.zeros(size_hw, dtype=np.uint8)
        candidates.append(MaskCandidate(
            name="main_component_preservation",
            mask=dummy_mask,
            discard_reason=f"Generation failed: {e}",
            status="discarded"
        ))

    # 3. Validación individual y scoring de cada hipótesis
    alpha_mask = None
    if analysis.has_transparency:
        try:
            alpha_mask = np.where(np.asarray(rgba_img.getchannel("A")) > 12, 255, 0).astype(np.uint8)
        except Exception:
            pass

    for cand in candidates:
        if cand.discard_reason is not None:
            cand.score = 0.0
            cand.scores = {
                "area_ratio": 0.0,
                "component_count": 0.0,
                "significant_component_count": 0.0,
                "edge_occupancy_ratio": 0.0,
                "hole_count": 0.0,
                "irregular_hole_ratio": 0.0,
                "contour_complexity": 0.0,
                "fragmentation": 0.0,
                "background_removed_ratio": 0.0,
                "score_before_penalties": 0.0,
                "total_penalty": 0.0,
                "final_score": 0.0,
            }
            continue

        # Validaciones de área de máscara
        area = cand.mask.sum() / 255
        total_pixels = w * h

        if area == 0:
            cand.discard_reason = "Mask is completely empty"
            cand.status = "discarded"
            cand.score = 0.0
            cand.scores = {
                "area_ratio": 0.0,
                "component_count": 0.0,
                "significant_component_count": 0.0,
                "edge_occupancy_ratio": 0.0,
                "hole_count": 0.0,
                "irregular_hole_ratio": 0.0,
                "contour_complexity": 0.0,
                "fragmentation": 0.0,
                "background_removed_ratio": 1.0 - (area / total_pixels),
                "score_before_penalties": 0.0,
                "total_penalty": 1.0,
                "final_score": 0.0,
            }
            continue

        if area / total_pixels >= MAX_FULL_IMAGE_RATIO:
            cand.discard_reason = f"Subject area too large ({area / total_pixels:.4f} >= {MAX_FULL_IMAGE_RATIO})"
            cand.status = "discarded"
            cand.score = 0.0
            cand.scores = {
                "area_ratio": area / total_pixels,
                "component_count": 0.0,
                "significant_component_count": 0.0,
                "edge_occupancy_ratio": 0.0,
                "hole_count": 0.0,
                "irregular_hole_ratio": 0.0,
                "contour_complexity": 0.0,
                "fragmentation": 0.0,
                "background_removed_ratio": 1.0 - (area / total_pixels),
                "score_before_penalties": 0.0,
                "total_penalty": 1.0,
                "final_score": 0.0,
            }
            continue

        if area < total_pixels * MIN_SUBJECT_AREA_RATIO:
            cand.discard_reason = f"Subject area too small ({area / total_pixels:.4f} < {MIN_SUBJECT_AREA_RATIO})"
            cand.status = "discarded"
            cand.score = 0.0
            cand.scores = {
                "area_ratio": area / total_pixels,
                "component_count": 0.0,
                "significant_component_count": 0.0,
                "edge_occupancy_ratio": 0.0,
                "hole_count": 0.0,
                "irregular_hole_ratio": 0.0,
                "contour_complexity": 0.0,
                "fragmentation": 0.0,
                "background_removed_ratio": 1.0 - (area / total_pixels),
                "score_before_penalties": 0.0,
                "total_penalty": 1.0,
                "final_score": 0.0,
            }
            continue

        # Scoring
        try:
            final_score, breakdown = _score_mask(cand.mask, alpha_mask, rgba_img)
            cand.score = final_score
            cand.scores = breakdown
            cand.status = "scored"
        except Exception as e:
            cand.discard_reason = f"Scoring evaluation failed: {e}"
            cand.status = "discarded"
            cand.score = 0.0
            cand.scores = {
                "area_ratio": area / total_pixels,
                "component_count": 0.0,
                "significant_component_count": 0.0,
                "edge_occupancy_ratio": 0.0,
                "hole_count": 0.0,
                "irregular_hole_ratio": 0.0,
                "contour_complexity": 0.0,
                "fragmentation": 0.0,
                "background_removed_ratio": 1.0 - (area / total_pixels),
                "score_before_penalties": 0.0,
                "total_penalty": 1.0,
                "final_score": 0.0,
            }

    # 3.5. Secondary component metrics and detached component penalty calculation
    rgb = np.asarray(rgba_img.convert("RGB"), dtype=np.uint8)
    for cand in candidates:
        if cand.discard_reason is not None or cand.status != "scored":
            continue

        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(cand.mask, connectivity=8)
        
        secondary_component_count = 0.0
        suspicious_component_count = 0.0
        largest_secondary_ratio = 0.0
        secondary_distance_ratio = 0.0
        component_consensus_ratio = 1.0
        detached_component_penalty = 0.0
        secondary_details = []

        if num_labels > 2:
            areas = stats[1:, cv2.CC_STAT_AREA]
            largest_idx = int(np.argmax(areas)) + 1
            main_area = stats[largest_idx, cv2.CC_STAT_AREA]
            cx_M, cy_M = centroids[largest_idx]
            diagonal = math.sqrt(w**2 + h**2)
            
            secondary_indices = [i for i in range(1, num_labels) if i != largest_idx]
            secondary_component_count = float(len(secondary_indices))
            
            consensus_sums = []
            for i in secondary_indices:
                area_i = stats[i, cv2.CC_STAT_AREA]
                cx_i, cy_i = centroids[i]
                
                # Area ratios
                ratio_to_main = float(area_i / main_area)
                largest_secondary_ratio = max(largest_secondary_ratio, ratio_to_main)
                
                # Distance calculation
                x1_M = stats[largest_idx, cv2.CC_STAT_LEFT]
                y1_M = stats[largest_idx, cv2.CC_STAT_TOP]
                w_M = stats[largest_idx, cv2.CC_STAT_WIDTH]
                h_M = stats[largest_idx, cv2.CC_STAT_HEIGHT]
                x1_i = stats[i, cv2.CC_STAT_LEFT]
                y1_i = stats[i, cv2.CC_STAT_TOP]
                w_i = stats[i, cv2.CC_STAT_WIDTH]
                h_i = stats[i, cv2.CC_STAT_HEIGHT]
                
                dx = max(0, x1_M - (x1_i + w_i), x1_i - (x1_M + w_M))
                dy = max(0, y1_M - (y1_i + h_i), y1_i - (y1_M + h_M))
                dist_bbox = math.sqrt(dx**2 + dy**2)
                
                norm_dist = float(dist_bbox / diagonal)
                secondary_distance_ratio = max(secondary_distance_ratio, norm_dist)
                
                # Consensus among other candidates
                cx_int, cy_int = int(cx_i), int(cy_i)
                other_votes = 0
                for other_cand in candidates:
                    if other_cand.mask is not None and other_cand.mask.shape == cand.mask.shape:
                        if 0 <= cx_int < w and 0 <= cy_int < h:
                            if other_cand.mask[cy_int, cx_int] == 255:
                                other_votes += 1
                consensus = float(other_votes / len(candidates))
                consensus_sums.append(consensus)
                
                # Color similarity to main component
                mask_main = (labels == largest_idx).astype(np.uint8)
                mask_i = (labels == i).astype(np.uint8)
                mean_main_rgb = cv2.mean(rgb, mask=mask_main)[:3]
                mean_i_rgb = cv2.mean(rgb, mask=mask_i)[:3]
                color_dist = np.linalg.norm(np.array(mean_main_rgb) - np.array(mean_i_rgb))
                
                # Check isolated outline (final_white_px default is 12)
                final_white_px = 12.0
                has_isolated_outline = dist_bbox > (2.0 * final_white_px)
                
                secondary_details.append({
                    "area_pct": float(area_i / (w * h)) * 100.0,
                    "distance_pct": float(dist_bbox / diagonal) * 100.0
                })
                
                # Determine if suspicious:
                # - Very small relative to main (ratio < 0.05) OR far away (norm_dist > 0.12)
                # - OR low consensus (present in <= 3 candidates) or has isolated outline or dissimilar color
                is_suspicious = False
                if ratio_to_main < 0.05:
                    is_suspicious = True
                if norm_dist > 0.12:
                    is_suspicious = True
                if consensus <= 0.4:
                    is_suspicious = True
                if color_dist > 60.0:
                    is_suspicious = True
                
                # Exemption for close components that are not far, have good consensus, and color match
                if norm_dist <= 0.08 and consensus > 0.4 and color_dist <= 60.0:
                    is_suspicious = False
                
                # If suspicious: calculate penalty
                if is_suspicious:
                    suspicious_component_count += 1.0
                    p_i = 0.15
                    if has_isolated_outline:
                        p_i += 0.20
                    if ratio_to_main < 0.03:
                        p_i += 0.10
                    if consensus <= 0.4:
                        p_i += 0.10
                    detached_component_penalty += p_i

            if consensus_sums:
                component_consensus_ratio = float(np.mean(consensus_sums))
                
            cand.diagnostics["secondary_components"] = secondary_details
            
        # Apply penalty to final score
        detached_component_penalty = min(0.70, detached_component_penalty)
        cand.score = max(0.0, cand.score - detached_component_penalty)
        
        # Store in cand.scores
        cand.scores["secondary_component_count"] = secondary_component_count
        cand.scores["suspicious_component_count"] = suspicious_component_count
        cand.scores["largest_secondary_ratio"] = largest_secondary_ratio
        cand.scores["secondary_distance_ratio"] = secondary_distance_ratio
        cand.scores["component_consensus_ratio"] = component_consensus_ratio
        cand.scores["detached_component_penalty"] = detached_component_penalty
        
        # Update total penalty and final score in metrics
        cand.scores["total_penalty"] = min(1.0, cand.scores.get("total_penalty", 0.0) + detached_component_penalty)
        cand.scores["final_score"] = cand.score

    # 4. Ordenación final determinista
    # - Primero los candidatos válidos (con score descendente)
    # - Luego los candidatos descartados (ordenados alfabéticamente por nombre)
    sorted_candidates = sorted(
        candidates,
        key=lambda c: (c.discard_reason is not None, -c.score, c.name)
    )

    return sorted_candidates
