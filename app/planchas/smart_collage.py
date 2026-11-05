"""Sistema de collage inteligente con detección de elementos importantes.

Crea diseños de collage automáticos que:
- Ocupan el 100% de la hoja
- Detectan caras y elementos importantes
- Evitan cortar contenido relevante
- Optimizan el uso del espacio
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Tuple, List, Optional
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


# ============================================================================
# DETECCIÓN DE ELEMENTOS IMPORTANTES
# ============================================================================

class ImportanceType(Enum):
    """Tipos de elementos importantes en una imagen."""
    FACE = "face"
    PERSON = "person"
    OBJECT = "object"
    EDGE_DENSITY = "edge_density"


@dataclass
class ImportantRegion:
    """Región importante en una imagen."""
    x: int
    y: int
    width: int
    height: int
    confidence: float
    type: ImportanceType
    
    @property
    def center(self) -> Tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)
    
    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass
class ImageAnalysis:
    """Análisis completo de una imagen."""
    width: int
    height: int
    important_regions: List[ImportantRegion] = field(default_factory=list)
    safe_crop_bounds: Optional[Tuple[int, int, int, int]] = None
    dominant_colors: List[Tuple[int, int, int]] = field(default_factory=list)
    has_transparency: bool = False
    
    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height if self.height > 0 else 1.0
    
    @property
    def is_landscape(self) -> bool:
        return self.aspect_ratio > 1.0
    
    @property
    def is_portrait(self) -> bool:
        return self.aspect_ratio < 1.0


class SmartImageAnalyzer:
    """Analiza imágenes para detectar elementos importantes."""
    
    def __init__(self):
        self._face_cascade = None
        self._person_detector = None
        
    def _get_face_cascade(self):
        """Carga el clasificador de caras de OpenCV."""
        if self._face_cascade is None:
            try:
                import cv2
                # Verificar que cv2 tiene CascadeClassifier
                if not hasattr(cv2, 'CascadeClassifier'):
                    logger.info("OpenCV no tiene CascadeClassifier, detección de caras deshabilitada")
                    return None
                
                # Usar el clasificador Haar Cascade para caras
                cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
                self._face_cascade = cv2.CascadeClassifier(cascade_path)
                
                # Verificar que se cargó correctamente
                if self._face_cascade.empty():
                    logger.warning("No se pudo cargar el clasificador de caras")
                    self._face_cascade = None
            except Exception as e:
                logger.info(f"Detección de caras no disponible: {e}")
                self._face_cascade = None
        return self._face_cascade
    
    def analyze_image(self, image_path: Path) -> ImageAnalysis:
        """Analiza una imagen completa."""
        try:
            import cv2
            from PIL import ImageStat
            
            # Corregir siempre la orientación indicada por la cámara antes de
            # analizar caras, contexto o relación de aspecto.
            from PIL import ImageOps
            pil_image = ImageOps.exif_transpose(Image.open(image_path))
            width, height = pil_image.size
            
            # Detectar transparencia
            has_transparency = pil_image.mode in ('RGBA', 'LA') or \
                             (pil_image.mode == 'P' and 'transparency' in pil_image.info)
            
            # Convertir a formato OpenCV
            if pil_image.mode == 'RGBA':
                cv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGBA2BGR)
            elif pil_image.mode == 'RGB':
                cv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
            else:
                cv_image = cv2.cvtColor(np.array(pil_image.convert('RGB')), cv2.COLOR_RGB2BGR)
            
            gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
            
            # Crear análisis
            analysis = ImageAnalysis(
                width=width,
                height=height,
                has_transparency=has_transparency
            )
            
            # Detectar caras
            face_regions = self._detect_faces(gray)
            analysis.important_regions.extend(face_regions)
            
            # Detectar regiones con alta densidad de bordes (contenido importante)
            edge_regions = self._detect_edge_density(gray)
            analysis.important_regions.extend(edge_regions)
            
            # Calcular límites seguros de recorte
            analysis.safe_crop_bounds = self._calculate_safe_crop(
                width, height, analysis.important_regions
            )
            
            # Extraer colores dominantes
            analysis.dominant_colors = self._extract_dominant_colors(pil_image)
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error al analizar imagen {image_path}: {e}")
            # Retornar análisis básico en caso de error
            try:
                from PIL import ImageOps
                pil_image = ImageOps.exif_transpose(Image.open(image_path))
                width, height = pil_image.size
                context_w, context_h = int(width * 0.72), int(height * 0.72)
                return ImageAnalysis(
                    width=width, height=height,
                    important_regions=[ImportantRegion(
                        (width - context_w) // 2, (height - context_h) // 2,
                        context_w, context_h, 0.35, ImportanceType.OBJECT,
                    )],
                )
            except Exception:
                return ImageAnalysis(width=800, height=600)
    
    def _detect_faces(self, gray_image) -> List[ImportantRegion]:
        """Detecta caras en la imagen."""
        regions = []
        
        face_cascade = self._get_face_cascade()
        if face_cascade is None:
            return regions
        
        try:
            # Detectar caras con diferentes escalas
            faces = face_cascade.detectMultiScale(
                gray_image,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(30, 30)
            )
            
            for (x, y, w, h) in faces:
                regions.append(ImportantRegion(
                    x=int(x),
                    y=int(y),
                    width=int(w),
                    height=int(h),
                    confidence=0.9,
                    type=ImportanceType.FACE
                ))
                
        except Exception as e:
            logger.warning(f"Error en detección de caras: {e}")
        
        return regions
    
    def _detect_edge_density(self, gray_image) -> List[ImportantRegion]:
        """Detecta regiones con alta densidad de bordes (contenido importante)."""
        import cv2
        regions = []
        
        try:
            # Detectar bordes con Canny
            edges = cv2.Canny(gray_image, 50, 150)
            
            # Dividir imagen en grid 3x3
            h, w = gray_image.shape
            grid_h = h // 3
            grid_w = w // 3
            
            threshold = 0.05  # 5% de píxeles deben ser bordes
            
            for row in range(3):
                for col in range(3):
                    y1 = row * grid_h
                    y2 = (row + 1) * grid_h if row < 2 else h
                    x1 = col * grid_w
                    x2 = (col + 1) * grid_w if col < 2 else w
                    
                    region_edges = edges[y1:y2, x1:x2]
                    edge_density = np.sum(region_edges > 0) / region_edges.size
                    
                    if edge_density > threshold:
                        confidence = min(1.0, edge_density / 0.2)
                        regions.append(ImportantRegion(
                            x=x1,
                            y=y1,
                            width=x2 - x1,
                            height=y2 - y1,
                            confidence=confidence,
                            type=ImportanceType.EDGE_DENSITY
                        ))
            
        except Exception as e:
            logger.warning(f"Error en detección de densidad de bordes: {e}")
        
        return regions
    
    def _calculate_safe_crop(
        self,
        width: int,
        height: int,
        regions: List[ImportantRegion]
    ) -> Tuple[int, int, int, int]:
        """Calcula los límites seguros para recortar sin perder contenido importante."""
        if not regions:
            # Sin regiones importantes, usar toda la imagen
            return (0, 0, width, height)
        
        # Encontrar el bounding box que contiene todas las regiones importantes
        # Priorizar caras sobre otros elementos
        face_regions = [r for r in regions if r.type == ImportanceType.FACE]
        priority_regions = face_regions if face_regions else regions
        
        min_x = min(r.x for r in priority_regions)
        min_y = min(r.y for r in priority_regions)
        max_x = max(r.x + r.width for r in priority_regions)
        max_y = max(r.y + r.height for r in priority_regions)
        
        # Agregar margen de seguridad (10% del tamaño de la región)
        region_width = max_x - min_x
        region_height = max_y - min_y
        margin_x = int(region_width * 0.1)
        margin_y = int(region_height * 0.1)
        
        safe_x1 = max(0, min_x - margin_x)
        safe_y1 = max(0, min_y - margin_y)
        safe_x2 = min(width, max_x + margin_x)
        safe_y2 = min(height, max_y + margin_y)
        
        return (safe_x1, safe_y1, safe_x2, safe_y2)
    
    def _extract_dominant_colors(self, pil_image: Image.Image, num_colors: int = 3) -> List[Tuple[int, int, int]]:
        """Extrae los colores dominantes de la imagen."""
        try:
            from PIL import ImageStat
            
            # Redimensionar para acelerar el análisis
            thumb = pil_image.copy()
            thumb.thumbnail((150, 150))
            
            if thumb.mode != 'RGB':
                thumb = thumb.convert('RGB')
            
            # Método simple: usar estadísticas de canales
            stat = ImageStat.Stat(thumb)
            dominant = tuple(int(v) for v in stat.mean[:3])
            
            return [dominant]
            
        except Exception as e:
            logger.warning(f"Error al extraer colores dominantes: {e}")
            return [(128, 128, 128)]


# ============================================================================
# TEMPLATES DE COLLAGE
# ============================================================================

@dataclass
class CollageCell:
    """Una celda en un layout de collage."""
    x: float  # Posición X normalizada (0.0 - 1.0)
    y: float  # Posición Y normalizada (0.0 - 1.0)
    width: float  # Ancho normalizado (0.0 - 1.0)
    height: float  # Alto normalizado (0.0 - 1.0)
    priority: int = 1  # Prioridad para asignar imágenes (1 = más importante)
    
    def to_pixels(self, canvas_width: int, canvas_height: int) -> Tuple[int, int, int, int]:
        """Convierte coordenadas normalizadas a píxeles."""
        px = int(self.x * canvas_width)
        py = int(self.y * canvas_height)
        pw = int(self.width * canvas_width)
        ph = int(self.height * canvas_height)
        return (px, py, pw, ph)


@dataclass
class CollageTemplate:
    """Template de collage con celdas predefinidas."""
    name: str
    cells: List[CollageCell]
    min_images: int
    max_images: int
    description: str = ""
    
    @property
    def num_cells(self) -> int:
        return len(self.cells)


class CollageTemplateLibrary:
    """Biblioteca de templates de collage prediseñados."""
    
    @staticmethod
    def get_all_templates() -> List[CollageTemplate]:
        """Retorna todos los templates disponibles."""
        return [
            CollageTemplateLibrary.single_large(),
            CollageTemplateLibrary.two_vertical(),
            CollageTemplateLibrary.two_horizontal(),
            CollageTemplateLibrary.three_mixed(),
            CollageTemplateLibrary.four_grid(),
            CollageTemplateLibrary.five_focus(),
            CollageTemplateLibrary.six_grid(),
            CollageTemplateLibrary.magazine_style(),
            CollageTemplateLibrary.hero_strip(),
        ]
    
    @staticmethod
    def single_large() -> CollageTemplate:
        """Una imagen grande que ocupa toda la hoja."""
        return CollageTemplate(
            name="single_large",
            cells=[CollageCell(0, 0, 1.0, 1.0, priority=1)],
            min_images=1,
            max_images=1,
            description="Una imagen grande"
        )
    
    @staticmethod
    def two_vertical() -> CollageTemplate:
        """Dos imágenes verticales lado a lado."""
        return CollageTemplate(
            name="two_vertical",
            cells=[
                CollageCell(0, 0, 0.5, 1.0, priority=1),
                CollageCell(0.5, 0, 0.5, 1.0, priority=1),
            ],
            min_images=2,
            max_images=2,
            description="Dos imágenes verticales"
        )
    
    @staticmethod
    def two_horizontal() -> CollageTemplate:
        """Dos imágenes horizontales una sobre otra."""
        return CollageTemplate(
            name="two_horizontal",
            cells=[
                CollageCell(0, 0, 1.0, 0.5, priority=1),
                CollageCell(0, 0.5, 1.0, 0.5, priority=1),
            ],
            min_images=2,
            max_images=2,
            description="Dos imágenes horizontales"
        )
    
    @staticmethod
    def three_mixed() -> CollageTemplate:
        """Una grande arriba, dos pequeñas abajo."""
        return CollageTemplate(
            name="three_mixed",
            cells=[
                CollageCell(0, 0, 1.0, 0.6, priority=1),
                CollageCell(0, 0.6, 0.5, 0.4, priority=2),
                CollageCell(0.5, 0.6, 0.5, 0.4, priority=2),
            ],
            min_images=3,
            max_images=3,
            description="Una grande + dos pequeñas"
        )
    
    @staticmethod
    def four_grid() -> CollageTemplate:
        """Grid 2x2 uniforme."""
        return CollageTemplate(
            name="four_grid",
            cells=[
                CollageCell(0, 0, 0.5, 0.5, priority=1),
                CollageCell(0.5, 0, 0.5, 0.5, priority=1),
                CollageCell(0, 0.5, 0.5, 0.5, priority=1),
                CollageCell(0.5, 0.5, 0.5, 0.5, priority=1),
            ],
            min_images=4,
            max_images=4,
            description="Grid 2x2"
        )
    
    @staticmethod
    def five_focus() -> CollageTemplate:
        """Una central grande, cuatro pequeñas en las esquinas."""
        return CollageTemplate(
            name="five_focus",
            cells=[
                CollageCell(0, 0, 1.0, 0.58, priority=1),
                CollageCell(0, 0.58, 0.25, 0.42, priority=2),
                CollageCell(0.25, 0.58, 0.25, 0.42, priority=2),
                CollageCell(0.5, 0.58, 0.25, 0.42, priority=2),
                CollageCell(0.75, 0.58, 0.25, 0.42, priority=2),
            ],
            min_images=5,
            max_images=5,
            description="Una central + cuatro esquinas"
        )
    
    @staticmethod
    def six_grid() -> CollageTemplate:
        """Grid 3x2."""
        return CollageTemplate(
            name="six_grid",
            cells=[
                CollageCell(0, 0, 0.333, 0.5, priority=1),
                CollageCell(0.333, 0, 0.334, 0.5, priority=1),
                CollageCell(0.667, 0, 0.333, 0.5, priority=1),
                CollageCell(0, 0.5, 0.333, 0.5, priority=1),
                CollageCell(0.333, 0.5, 0.334, 0.5, priority=1),
                CollageCell(0.667, 0.5, 0.333, 0.5, priority=1),
            ],
            min_images=6,
            max_images=6,
            description="Grid 3x2"
        )
    
    @staticmethod
    def magazine_style() -> CollageTemplate:
        """Estilo revista: una grande a la izquierda, tres apiladas a la derecha."""
        return CollageTemplate(
            name="magazine_style",
            cells=[
                CollageCell(0, 0, 0.6, 1.0, priority=1),
                CollageCell(0.6, 0, 0.4, 0.333, priority=2),
                CollageCell(0.6, 0.333, 0.4, 0.334, priority=2),
                CollageCell(0.6, 0.667, 0.4, 0.333, priority=2),
            ],
            min_images=4,
            max_images=4,
            description="Estilo revista"
        )
    
    @staticmethod
    def hero_strip() -> CollageTemplate:
        """Imagen hero arriba, tres pequeñas abajo."""
        return CollageTemplate(
            name="hero_strip",
            cells=[
                CollageCell(0, 0, 1.0, 0.65, priority=1),
                CollageCell(0, 0.65, 0.333, 0.35, priority=2),
                CollageCell(0.333, 0.65, 0.334, 0.35, priority=2),
                CollageCell(0.667, 0.65, 0.333, 0.35, priority=2),
            ],
            min_images=4,
            max_images=4,
            description="Hero + strip"
        )
    
    @staticmethod
    def get_template_for_count(count: int) -> Optional[CollageTemplate]:
        """Retorna el mejor template para una cantidad específica de imágenes."""
        templates = CollageTemplateLibrary.get_all_templates()
        
        # Buscar template exacto
        exact_matches = [t for t in templates if t.min_images <= count <= t.max_images]
        if exact_matches:
            return exact_matches[0]
        
        # Si no hay match exacto, retornar None
        return None


# ============================================================================
# GENERADOR DE COLLAGE
# ============================================================================

class SmartCollageGenerator:
    """Genera collages inteligentes que respetan elementos importantes."""
    
    def __init__(self):
        self.analyzer = SmartImageAnalyzer()
        self._analysis_cache: dict[str, ImageAnalysis] = {}
    
    def create_collage(
        self,
        image_paths: List[Path],
        canvas_width: int = 2480,
        canvas_height: int = 3508,
        template: Optional[CollageTemplate] = None,
        gap: int = 0,
        image_offsets: Optional[dict[str, tuple[float, float]]] = None,
        image_scales: Optional[dict[str, float]] = None,
        image_rotations: Optional[dict[str, int]] = None,
        manual_image_keys: Optional[set[str]] = None,
    ) -> Image.Image:
        """Crea un collage inteligente.
        
        Args:
            image_paths: Lista de paths a las imágenes
            canvas_width: Ancho del canvas en píxeles (default: A4 a 300dpi)
            canvas_height: Alto del canvas en píxeles (default: A4 a 300dpi)
            template: Template específico (None = auto-select)
            gap: Separación entre imágenes en píxeles
        
        Returns:
            Imagen PIL del collage
        """
        if not image_paths:
            raise ValueError("No se proporcionaron imágenes")
        
        # Auto-seleccionar template si no se especificó
        # A template with a different number of cells would leave blank areas.
        # Rebuild the last partial batch so every pixel is occupied.
        if template is None or template.num_cells != len(image_paths):
            template = CollageTemplateLibrary.get_template_for_count(len(image_paths))
            if template is None:
                # Si hay más imágenes que templates, usar grid
                template = self._create_dynamic_grid_template(len(image_paths))
        
        # Analizar todas las imágenes
        analyses = []
        for path in image_paths[:template.num_cells]:
            key = str(path)
            analysis = self._analysis_cache.get(key)
            if analysis is None:
                analysis = self.analyzer.analyze_image(path)
                self._analysis_cache[key] = analysis
            analyses.append((path, analysis))
        
        # Crear canvas
        canvas = Image.new('RGB', (canvas_width, canvas_height), (255, 255, 255))
        
        # Colocar imágenes en las celdas
        for (image_path, analysis), cell in zip(analyses, template.cells):
            cell_x, cell_y, cell_w, cell_h = cell.to_pixels(canvas_width, canvas_height)
            
            # Aplicar gap
            if gap > 0:
                cell_x += gap // 2
                cell_y += gap // 2
                cell_w -= gap
                cell_h -= gap
            
            # Renderizar imagen en la celda
            cell_image = self._render_image_in_cell(
                image_path,
                analysis,
                cell_w,
                cell_h,
                (image_offsets or {}).get(str(image_path), (0.0, 0.0)),
                (image_scales or {}).get(str(image_path), 1.0),
                (image_rotations or {}).get(str(image_path), 0),
                str(image_path) in (manual_image_keys or set()),
            )
            
            # Pegar en el canvas
            canvas.paste(cell_image, (cell_x, cell_y))
        
        return canvas
    
    def _render_image_in_cell(
        self,
        image_path: Path,
        analysis: ImageAnalysis,
        cell_width: int,
        cell_height: int,
        offset: tuple[float, float] = (0.0, 0.0),
        zoom: float = 1.0,
        rotation: int = 0,
        manual: bool = False,
    ) -> Image.Image:
        """Renderiza una imagen dentro de una celda respetando regiones importantes."""
        from PIL import ImageOps
        
        # Cargar imagen
        image = Image.open(image_path)
        image = ImageOps.exif_transpose(image)

        rotation %= 360
        if rotation:
            image = image.rotate(-rotation, expand=True)

        # Además del EXIF, rotar 90° cuando la orientación contraria llena
        # mejor la celda. Se evita un recorte innecesario de personas/fondos.
        source_ratio = image.width / image.height
        cell_ratio = cell_width / cell_height
        normal_error = abs(math.log(source_ratio / cell_ratio))
        rotated_error = abs(math.log((1 / source_ratio) / cell_ratio))
        if not rotation and rotated_error + 0.15 < normal_error:
            image = image.rotate(90, expand=True)
        
        if image.mode != 'RGB':
            # Convertir preservando transparencia si existe
            if image.mode in ('RGBA', 'LA'):
                background = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'RGBA':
                    background.paste(image, mask=image.split()[3])
                else:
                    background.paste(image, mask=image.split()[1])
                image = background
            else:
                image = image.convert('RGB')
        
        img_width, img_height = image.size
        
        # Si hay regiones importantes, intentar recorte inteligente
        if False and analysis.safe_crop_bounds and analysis.important_regions:
            # Recortar a la región segura
            x1, y1, x2, y2 = analysis.safe_crop_bounds
            safe_width = x2 - x1
            safe_height = y2 - y1
            
            # Calcular aspect ratio de la región segura vs la celda
            safe_aspect = safe_width / safe_height if safe_height > 0 else 1.0
            cell_aspect = cell_width / cell_height if cell_height > 0 else 1.0
            
            # Si los aspect ratios son similares, usar recorte inteligente
            aspect_diff = abs(safe_aspect - cell_aspect) / cell_aspect
            if aspect_diff < 0.3:  # 30% de diferencia máxima
                cropped = image.crop((x1, y1, x2, y2))
                return ImageOps.fit(cropped, (cell_width, cell_height), Image.Resampling.LANCZOS)
        
        # Usar estrategia de cover (llenar la celda, recortar excedente)
        regions = [] if manual else analysis.important_regions
        crop_box = self._content_aware_crop_box(image.size, (cell_width, cell_height), regions)
        # El zoom reduce la ventana de recorte sin dejar espacios vacíos.
        zoom = max(1.0, min(3.0, zoom))
        if zoom > 1.0:
            left, top, right, bottom = crop_box
            crop_w, crop_h = (right - left) / zoom, (bottom - top) / zoom
            center_x, center_y = (left + right) / 2, (top + bottom) / 2
            crop_box = (int(center_x - crop_w / 2), int(center_y - crop_h / 2),
                        int(center_x + crop_w / 2), int(center_y + crop_h / 2))
        center_x = (crop_box[0] + crop_box[2]) / (2 * img_width)
        center_y = (crop_box[1] + crop_box[3]) / (2 * img_height)
        crop_w, crop_h = crop_box[2] - crop_box[0], crop_box[3] - crop_box[1]
        offset_x = offset[0] / img_width
        offset_y = offset[1] / img_height
        allow_empty_edge = zoom == 1.0 and (offset_x or offset_y)
        if allow_empty_edge:
            # El usuario pidió mover sin ampliar ni reencuadrar. Por eso no se
            # limita la posición al borde de la foto: si se la desplaza más
            # allá, se conserva su tamaño y aparece fondo blanco en ese borde.
            center_x += offset_x
            center_y += offset_y
        else:
            center_x = max(crop_w / (2 * img_width), min(1 - crop_w / (2 * img_width), center_x + offset_x))
            center_y = max(crop_h / (2 * img_height), min(1 - crop_h / (2 * img_height), center_y + offset_y))
        left = int(round(center_x * img_width - crop_w / 2))
        top = int(round(center_y * img_height - crop_h / 2))
        if allow_empty_edge:
            cropped = Image.new('RGB', (crop_w, crop_h), 'white')
            source_left = max(0, left)
            source_top = max(0, top)
            source_right = min(img_width, left + crop_w)
            source_bottom = min(img_height, top + crop_h)
            if source_left < source_right and source_top < source_bottom:
                visible = image.crop((source_left, source_top, source_right, source_bottom))
                cropped.paste(visible, (source_left - left, source_top - top))
        else:
            left = max(0, min(img_width - crop_w, left))
            top = max(0, min(img_height - crop_h, top))
            cropped = image.crop((left, top, left + crop_w, top + crop_h))
        return ImageOps.fit(cropped, (cell_width, cell_height), Image.Resampling.LANCZOS)

    @staticmethod
    def _content_aware_crop_box(image_size, cell_size, regions):
        """Select a cover crop centered on faces, then visual detail."""
        width, height = image_size
        target_ratio = cell_size[0] / cell_size[1]
        if width / height > target_ratio:
            crop_w, crop_h = max(1, int(round(height * target_ratio))), height
        else:
            crop_w, crop_h = width, max(1, int(round(width / target_ratio)))
        priority = [region for region in regions if region.type == ImportanceType.FACE] or list(regions)
        if priority:
            left, top = min(r.x for r in priority), min(r.y for r in priority)
            right, bottom = max(r.x + r.width for r in priority), max(r.y + r.height for r in priority)
            center_x, center_y = (left + right) / 2, (top + bottom) / 2
            min_x, max_x = right - crop_w, left
            min_y, max_y = bottom - crop_h, top
            x = min(max(center_x - crop_w / 2, min_x), max_x) if min_x <= max_x else center_x - crop_w / 2
            y = min(max(center_y - crop_h / 2, min_y), max_y) if min_y <= max_y else center_y - crop_h / 2
        else:
            x, y = (width - crop_w) / 2, (height - crop_h) / 2
        x, y = max(0, min(width - crop_w, x)), max(0, min(height - crop_h, y))
        return int(x), int(y), int(x + crop_w), int(y + crop_h)
    
    def _create_dynamic_grid_template(self, num_images: int) -> CollageTemplate:
        """Crea un template de grid dinámico para cualquier número de imágenes."""
        # Calcular dimensiones óptimas del grid
        cols = int(np.ceil(np.sqrt(num_images)))
        rows = int(np.ceil(num_images / cols))
        
        cell_width = 1.0 / cols
        cell_height = 1.0 / rows
        
        cells = []
        for i in range(num_images):
            row = i // cols
            col = i % cols
            
            cells.append(CollageCell(
                x=col * cell_width,
                y=row * cell_height,
                width=cell_width,
                height=cell_height,
                priority=1
            ))
        
        return CollageTemplate(
            name=f"grid_{cols}x{rows}",
            cells=cells,
            min_images=num_images,
            max_images=num_images,
            description=f"Grid dinámico {cols}x{rows}"
        )
