"""Impresi\u00f3n continua de p\u00f3sters en hojas A4."""

from __future__ import annotations

import json
import math
import tempfile
import tkinter as tk
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app.planchas.poster_packing import (
    MarginConfig,
    MixedPosterItem,
    Orientation,
    PaperSize,
    SizePolicy,
    pack_mixed_posters,
)
from app.printing.windows_print import default_printer, print_png
from app.ui.theme import COLORS, IDENTITY_FONT, UI_FONT, configure_plancha_styles


class Debounce:
    """Implementación simple de debounce para evitar recálculos excesivos."""
    
    def __init__(self, delay_ms: int = 500):
        self.delay_ms = delay_ms
        self.timer_id = None
        self.callback = None
    
    def __call__(self, callback):
        self.callback = callback
        return self._debounced
    
    def _debounced(self, *args, **kwargs):
        if self.timer_id:
            self.callback.after_cancel(self.timer_id)
        self.timer_id = self.callback.after(self.delay_ms, lambda: self._execute(*args, **kwargs))
    
    def _execute(self, *args, **kwargs):
        self.timer_id = None
        if self.callback:
            self.callback(*args, **kwargs)


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
# La hoja de trabajo siempre es A4 vertical: 210 mm de ancho por 297 mm de alto.
# Mantener este único origen evita que una vista previa o un modo de impresión
# adopte accidentalmente la orientación horizontal.
A4_PORTRAIT_MM = (210.0, 297.0)
SHEET_SIZE = (2480, 3508)  # A4 vertical a 300 DPI
LAYOUTS = {
    1: (1, 1), 2: (1, 2), 3: (1, 3), 4: (2, 2), 8: (2, 4), 16: (4, 4), 32: (4, 8),
}
# Los formatos de 2 y 3 fotos reproducen las tiras fotográficas: fotos
# apaisadas, márgenes blancos de corte y separación visible entre ellas.
PHOTO_STRIP_LAYOUTS = {2, 3}
PHOTO_STRIP_MARGIN_PX = round(15 * 300 / 25.4)  # 15 mm a 300 DPI
PHOTO_STRIP_GAP_PX = round(5 * 300 / 25.4)      # 5 mm a 300 DPI
PHOTO_STRIP_TITLE_HEIGHT_PX = round(20 * 300 / 25.4)  # Banda superior reservada para título
PHOTO_STRIP_TITLE_GAP_PX = round(3 * 300 / 25.4)


@lru_cache(maxsize=12)
def _cached_print_source(path_text: str, modified_ns: int, file_size: int):
    """Carga una fuente una vez por versión del archivo, sin dejarlo abierto."""
    from PIL import Image, ImageOps
    with Image.open(path_text) as source:
        return ImageOps.exif_transpose(source).convert("RGBA").copy()


def _load_print_source(path: Path):
    """Entrega una copia editable y segura de la caché de previsualización."""
    details = Path(path).stat()
    return _cached_print_source(str(path), details.st_mtime_ns, details.st_size).copy()


def _choose_auto_collage_template(templates, remaining_count, used_names, previous_name):
    """Elige un estilo automático sin repetirlo mientras haya alternativas.

    Una plantilla solo es candidata si deja una cantidad de imágenes que todavía
    puede completar otra hoja. Esto evita terminar con un resto imposible de
    componer y, a la vez, favorece composiciones con más fotos por página.
    """
    def is_valid(template):
        remainder = remaining_count - template.num_cells
        return remainder == 0 or any(
            other.num_cells <= remainder for other in templates
        )

    candidates = [template for template in templates if template.num_cells <= remaining_count and is_valid(template)]
    if not candidates:
        return None

    # Primero usar cada estilo disponible una vez; cuando ya se usaron todos,
    # evitar al menos repetir el estilo de la página anterior.
    unused = [template for template in candidates if template.name not in used_names]
    if unused:
        candidates = unused
    non_repeated = [template for template in candidates if template.name != previous_name]
    if non_repeated:
        candidates = non_repeated

    return max(candidates, key=lambda template: template.num_cells)


class DistributionMode(Enum):
    """Modos de distribución de pósters."""
    UNIFORM = "uniform"
    MIXED = "mixed"
    SMART_COLLAGE = "smart_collage"
    CARDS_9X5 = "cards_9x5"


class Unit(Enum):
    """Unidades de medida."""
    MM = "mm"
    CM = "cm"


class FitMode(Enum):
    """Modos de ajuste de imagen dentro del marco."""
    CONTAIN = "contain"
    COVER = "cover"
    MANUAL = "manual"


@dataclass
class ImageTransform:
    """Transformación visual de la imagen dentro de su marco."""
    fit_mode: FitMode = FitMode.COVER
    image_offset_x: float = 0.0  # Desplazamiento X en píxeles relativos al tamaño de la imagen
    image_offset_y: float = 0.0  # Desplazamiento Y en píxeles relativos al tamaño de la imagen
    image_scale: float = 1.0  # Escala multiplicativa (1.0 = 100%)
    image_rotation_deg: float = 0.0  # Rotación en grados
    anchor_x: float = 0.5  # Punto de anclaje X (0.0 = izquierda, 1.0 = derecha)
    anchor_y: float = 0.5  # Punto de anclaje Y (0.0 = arriba, 1.0 = abajo)
    auto_fitted: bool = True  # Indica si se aplicó ajuste automático


@dataclass
class CardFace:
    """Contenido independiente de una cara de tarjeta."""
    path: Path | None = None
    transform: ImageTransform = field(default_factory=ImageTransform)


@dataclass
class CardSlot:
    front: CardFace = field(default_factory=CardFace)
    back: CardFace = field(default_factory=CardFace)


@dataclass
class PrinterProfile:
    """Calibración reutilizable de impresora para impresiones fotográficas."""
    name: str
    front_offset_x_mm: float = 0.0
    front_offset_y_mm: float = 0.0
    back_offset_x_mm: float = 0.0
    back_offset_y_mm: float = 0.0
    flip_mode: str = "long_edge"
    scale_percent: float = 100.0
    calibrated_at: str | None = None

    def to_dict(self) -> dict:
        return {"name": self.name, "front_offset_x_mm": self.front_offset_x_mm, "front_offset_y_mm": self.front_offset_y_mm,
                "back_offset_x_mm": self.back_offset_x_mm, "back_offset_y_mm": self.back_offset_y_mm,
                "flip_mode": self.flip_mode, "scale_percent": self.scale_percent, "calibrated_at": self.calibrated_at}

    @classmethod
    def from_dict(cls, data: dict) -> "PrinterProfile":
        return cls(**{key: data.get(key, default) for key, default in {
            "name": "Perfil", "front_offset_x_mm": 0.0, "front_offset_y_mm": 0.0, "back_offset_x_mm": 0.0,
            "back_offset_y_mm": 0.0, "flip_mode": "long_edge", "scale_percent": 100.0, "calibrated_at": None}.items()})


class PrinterProfileStore:
    """Archivo JSON aislado, preparado para ser compartido por otros modos en el futuro."""
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> list[PrinterProfile]:
        if not self.path.exists():
            return []
        return [PrinterProfile.from_dict(item) for item in json.loads(self.path.read_text(encoding="utf-8"))]

    def save(self, profiles: list[PrinterProfile]):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([profile.to_dict() for profile in profiles], ensure_ascii=False, indent=2), encoding="utf-8")


def profile_offsets_for_side(profile: PrinterProfile | None, side: str,
                             manual_back_x_mm: float = 0.0, manual_back_y_mm: float = 0.0) -> tuple[float, float]:
    """Compone el perfil guardado con la corrección puntual del proyecto."""
    if side == "back":
        return (manual_back_x_mm + (profile.back_offset_x_mm if profile else 0.0),
                manual_back_y_mm + (profile.back_offset_y_mm if profile else 0.0))
    return ((profile.front_offset_x_mm if profile else 0.0), (profile.front_offset_y_mm if profile else 0.0))


CARD_SHEET_MM = A4_PORTRAIT_MM
CARD_SIZE_MM = (90.0, 50.0)
CARD_COLUMNS, CARD_ROWS = 2, 5
CARD_BLEED_MM = 3.0


def card_slot_rect_mm(index: int) -> tuple[float, float, float, float]:
    """Rectángulo de corte de una de las diez tarjetas, en milímetros."""
    if not 0 <= index < CARD_COLUMNS * CARD_ROWS:
        raise IndexError("La tarjeta debe estar entre 0 y 9.")
    total_w, total_h = CARD_COLUMNS * CARD_SIZE_MM[0], CARD_ROWS * CARD_SIZE_MM[1]
    left, top = (CARD_SHEET_MM[0] - total_w) / 2, (CARD_SHEET_MM[1] - total_h) / 2
    return (left + (index % CARD_COLUMNS) * CARD_SIZE_MM[0],
            top + (index // CARD_COLUMNS) * CARD_SIZE_MM[1], *CARD_SIZE_MM)


def reverse_card_slot_index(index: int, flip_mode: str) -> int:
    """Ubicación física del reverso tras reinserción de la hoja A4."""
    col, row = index % CARD_COLUMNS, index // CARD_COLUMNS
    if flip_mode == "long_edge":
        col = CARD_COLUMNS - 1 - col
    elif flip_mode == "short_edge":
        row = CARD_ROWS - 1 - row
    return row * CARD_COLUMNS + col


def card_back_paint_rect_mm(index: int, bleed_mm: float) -> tuple[float, float, float, float]:
    """Zona que un reverso puede ocupar sin invadir otra tarjeta tras el corte.

    No hay canal entre tarjetas: el sangrado se admite solo hacia el borde
    exterior de la matriz, donde hay papel físico disponible.
    """
    x, y, width, height = card_slot_rect_mm(index)
    col, row = index % CARD_COLUMNS, index // CARD_COLUMNS
    left = x - (bleed_mm if col == 0 else 0.0)
    top = y - (bleed_mm if row == 0 else 0.0)
    right = x + width + (bleed_mm if col == CARD_COLUMNS - 1 else 0.0)
    bottom = y + height + (bleed_mm if row == CARD_ROWS - 1 else 0.0)
    return max(0.0, left), max(0.0, top), min(CARD_SHEET_MM[0], right), min(CARD_SHEET_MM[1], bottom)


def render_cards_9x5_page(slots: list[CardSlot], side: str = "front", *,
                           double_sided: bool = False, bleed_mm: float = CARD_BLEED_MM,
                           offset_x_mm: float = 0.0, offset_y_mm: float = 0.0,
                           flip_mode: str = "long_edge", dpi: int = 300) -> object:
    """Renderiza una hoja A4 real a 300 DPI; las guías no se incluyen."""
    from PIL import Image, ImageOps
    mm_to_px = dpi / 25.4
    page = Image.new("RGB", (round(CARD_SHEET_MM[0] * mm_to_px), round(CARD_SHEET_MM[1] * mm_to_px)), "white")
    for index, slot in enumerate(slots[:10]):
        face = slot.front if side == "front" else slot.back
        if not face.path:
            continue
        target_index = index if side == "front" else reverse_card_slot_index(index, flip_mode)
        x, y, w, h = card_slot_rect_mm(target_index)
        # Los perfiles de impresora pueden compensar también el frente.  El
        # desplazamiento debe aplicarse al contenido, nunca a las guías/cortes.
        # En ambos lados se conserva como límite de pintura el rectángulo de la
        # tarjeta para que una corrección no llegue a contaminar su vecina.
        safe_x, safe_y = x, y
        safe_right, safe_bottom = x + w, y + h
        if side == "back" and double_sided:
            x, y, w, h = x - bleed_mm + offset_x_mm, y - bleed_mm + offset_y_mm, w + 2 * bleed_mm, h + 2 * bleed_mm
        else:
            x, y = x + offset_x_mm, y + offset_y_mm
        frame_w, frame_h = round(w * mm_to_px), round(h * mm_to_px)
        try:
            with _load_print_source(face.path) as source:
                # El render no debe modificar la transformación persistida.
                image, px, py = _apply_image_transform(source, deepcopy(face.transform), frame_w, frame_h)
                frame = Image.new("RGBA", (frame_w, frame_h), "white")
                frame.paste(image, (px, py), image)
                paste_x, paste_y = round(x * mm_to_px), round(y * mm_to_px)
                if side == "back" and double_sided:
                    # Impide que un reverso diferente sea visible dentro del
                    # área de corte de su vecino. El offset es global y se
                    # conserva, pero la propiedad de cada zona sigue siendo
                    # exclusiva de su tarjeta.
                    safe_x, safe_y, safe_right, safe_bottom = card_back_paint_rect_mm(target_index, bleed_mm)
                    crop_left = max(0, round(safe_x * mm_to_px) - paste_x)
                    crop_top = max(0, round(safe_y * mm_to_px) - paste_y)
                    crop_right = min(frame.width, round(safe_right * mm_to_px) - paste_x)
                    crop_bottom = min(frame.height, round(safe_bottom * mm_to_px) - paste_y)
                    if crop_right > crop_left and crop_bottom > crop_top:
                        page.paste(frame.crop((crop_left, crop_top, crop_right, crop_bottom)).convert("RGB"),
                                   (paste_x + crop_left, paste_y + crop_top))
                else:
                    crop_left = max(0, round(safe_x * mm_to_px) - paste_x)
                    crop_top = max(0, round(safe_y * mm_to_px) - paste_y)
                    crop_right = min(frame.width, round(safe_right * mm_to_px) - paste_x)
                    crop_bottom = min(frame.height, round(safe_bottom * mm_to_px) - paste_y)
                    if crop_right > crop_left and crop_bottom > crop_top:
                        page.paste(frame.crop((crop_left, crop_top, crop_right, crop_bottom)).convert("RGB"),
                                   (paste_x + crop_left, paste_y + crop_top))
        except (OSError, ValueError):
            continue
    return page


def render_cards_calibration_page(side: str, *, flip_mode: str = "long_edge", dpi: int = 300) -> object:
    """Hoja A4 de registro; independiente de cualquier proyecto de tarjetas."""
    from PIL import Image, ImageDraw, ImageFont
    mm_to_px = dpi / 25.4
    page = Image.new("RGB", (round(210 * mm_to_px), round(297 * mm_to_px)), "white")
    draw = ImageDraw.Draw(page)
    font = ImageFont.load_default()
    labels = [f"{row}{col}" for row in "ABCDE" for col in (1, 2)]
    for index, label in enumerate(labels):
        target = index if side == "front" else reverse_card_slot_index(index, flip_mode)
        x, y, width, height = card_slot_rect_mm(target)
        box = tuple(round(value * mm_to_px) for value in (x, y, x + width, y + height))
        draw.rectangle(box, outline="black", width=max(1, round(.3 * mm_to_px)))
        draw.text((box[0] + round(3 * mm_to_px), box[1] + round(3 * mm_to_px)), f"{side.upper()} {label}", fill="black", font=font)
        draw.line((box[0], (box[1] + box[3]) // 2, box[2], (box[1] + box[3]) // 2), fill="black", width=1)
        draw.line(((box[0] + box[2]) // 2, box[1], (box[0] + box[2]) // 2, box[3]), fill="black", width=1)
    # Patrón de escala real: línea 100 mm, rectángulo 90x50 y marcas de 10 mm.
    ox, oy = round(15 * mm_to_px), round(282 * mm_to_px)
    draw.line((ox, oy, ox + round(100 * mm_to_px), oy), fill="black", width=max(1, round(.4 * mm_to_px)))
    for millimeter in range(0, 101, 10):
        x = ox + round(millimeter * mm_to_px)
        draw.line((x, oy - round(2 * mm_to_px), x, oy + round(2 * mm_to_px)), fill="black", width=1)
        draw.text((x, oy + round(2.5 * mm_to_px)), str(millimeter), fill="black", font=font)
    draw.text((ox, oy - round(6 * mm_to_px)), "CONTROL: 100 mm - imprimir al 100%, sin ajustar a pagina", fill="black", font=font)
    return page


def export_a4_pdf(pages: list[object], target: Path, dpi: int = 300):
    """Escribe páginas A4 exactas (210 x 297 mm) sin escalado del contenido."""
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.pdfbase.pdfdoc import PDFArray
    from io import BytesIO
    mm_to_pt = 72 / 25.4
    canvas = Canvas(str(target), pagesize=(210 * mm_to_pt, 297 * mm_to_pt))
    for page in pages:
        if page.size != (round(210 * dpi / 25.4), round(297 * dpi / 25.4)):
            raise ValueError("El PDF A4 requiere un render A4 al DPI indicado.")
        data = BytesIO(); page.save(data, format="PNG", dpi=(dpi, dpi)); data.seek(0)
        canvas.drawImage(ImageReader(data), 0, 0, width=210 * mm_to_pt, height=297 * mm_to_pt, mask="auto")
        canvas.showPage()
        # ReportLab redondea los float del MediaBox a seis cifras
        # significativas. Literales decimales conservan el A4 calculado,
        # sin cambiar escala, calibración ni geometría del contenido.
        canvas._doc.Pages.pages[-1].MediaBox = PDFArray([
            0, 0, f"{210 * mm_to_pt:.9f}", f"{297 * mm_to_pt:.9f}",
        ])
    canvas.save()


def cards_9x5_project_state(slots: list[CardSlot], *, double_sided: bool,
                            bleed_mm: float, offset_x_mm: float, offset_y_mm: float,
                            flip_mode: str, selected: set[int] | None = None) -> dict:
    """Serializa por completo el subtipo de impresión de tarjetas."""
    def face_data(face: CardFace) -> dict:
        transform = face.transform
        return {"image": str(face.path) if face.path else None, "fit_mode": transform.fit_mode.value,
                "scale": transform.image_scale, "position_x": transform.image_offset_x,
                "position_y": transform.image_offset_y, "rotation": transform.image_rotation_deg}
    return {"photo_print_mode": DistributionMode.CARDS_9X5.value, "sheet_mm": CARD_SHEET_MM,
            "card_size_mm": CARD_SIZE_MM, "positions": [{"front": face_data(slot.front), "back": face_data(slot.back)} for slot in slots],
            "backside_bleed_mm": bleed_mm, "backside_offset_x_mm": offset_x_mm,
            "backside_offset_y_mm": offset_y_mm, "backside_flip_mode": flip_mode,
            "double_sided": double_sided, "selected_positions": sorted(selected or ())}


def cards_9x5_from_project_state(project: dict) -> tuple[list[CardSlot], dict]:
    """Restaura un proyecto de tarjetas y valida su geometría fija."""
    if project.get("photo_print_mode") != DistributionMode.CARDS_9X5.value:
        raise ValueError("El proyecto no corresponde a Tarjetas 9x5.")
    if tuple(project.get("sheet_mm", ())) != CARD_SHEET_MM or tuple(project.get("card_size_mm", ())) != CARD_SIZE_MM:
        raise ValueError("La geometría del proyecto no es A4 / 90x50 mm.")
    def face_from(data: dict) -> CardFace:
        data = data or {}
        transform = ImageTransform(fit_mode=FitMode(data.get("fit_mode", FitMode.COVER.value)),
                                   image_scale=float(data.get("scale", 1.0)),
                                   image_offset_x=float(data.get("position_x", 0.0)),
                                   image_offset_y=float(data.get("position_y", 0.0)),
                                   image_rotation_deg=float(data.get("rotation", 0.0)))
        return CardFace(path=Path(data["image"]) if data.get("image") else None, transform=transform)
    positions = project.get("positions", [])
    if len(positions) != 10:
        raise ValueError("Un proyecto de tarjetas debe contener exactamente 10 posiciones.")
    slots = [CardSlot(front=face_from(item.get("front")), back=face_from(item.get("back"))) for item in positions]
    settings = {"double_sided": bool(project.get("double_sided", False)),
                "bleed_mm": float(project.get("backside_bleed_mm", CARD_BLEED_MM)),
                "offset_x_mm": float(project.get("backside_offset_x_mm", 0.0)),
                "offset_y_mm": float(project.get("backside_offset_y_mm", 0.0)),
                "flip_mode": project.get("backside_flip_mode", "long_edge"),
                "selected": set(project.get("selected_positions", []))}
    return slots, settings


@dataclass
class MixedElement:
    """Elemento en modo mixto con dimensiones personalizables."""
    path: Path
    width_mm: float
    height_mm: float
    quantity: int = 1
    orientation: Orientation = Orientation.AUTOMATIC
    allow_rotation: bool = True
    preset: PaperSize | None = None
    _id: str = field(default_factory=lambda: str(uuid.uuid4()))
    transform: ImageTransform = field(default_factory=ImageTransform)
    
    @property
    def id(self) -> str:
        return self._id
    
    @property
    def display_name(self) -> str:
        return self.path.stem


def render_poster_pages(paths: list[Path], per_sheet: int,
                        transforms: dict[str, ImageTransform] | None = None,
                        title: str = "") -> list[object]:
    """Devuelve hojas A4; 2 y 3 por hoja usan formato de tira fotográfica."""
    from PIL import Image, ImageOps

    if per_sheet not in LAYOUTS:
        raise ValueError("La cantidad por hoja no es v\u00e1lida.")
    columns, rows = LAYOUTS[per_sheet]
    has_title = per_sheet in PHOTO_STRIP_LAYOUTS and bool(title.strip())
    if per_sheet in PHOTO_STRIP_LAYOUTS:
        # Mantener margen blanco y calles de corte como en una tira/díptico
        # o tríptico fotográfico. Las celdas son deliberadamente apaisadas.
        usable_w = SHEET_SIZE[0] - 2 * PHOTO_STRIP_MARGIN_PX
        title_space = PHOTO_STRIP_TITLE_HEIGHT_PX + PHOTO_STRIP_TITLE_GAP_PX if has_title else 0
        usable_h = (SHEET_SIZE[1] - 2 * PHOTO_STRIP_MARGIN_PX - title_space
                    - (rows - 1) * PHOTO_STRIP_GAP_PX)
        cell_w, cell_h = usable_w, usable_h // rows
        origin_x = PHOTO_STRIP_MARGIN_PX
        origin_y = PHOTO_STRIP_MARGIN_PX + title_space
        step_x, step_y = cell_w, cell_h + PHOTO_STRIP_GAP_PX
    else:
        # Sin márgenes ni separación: cada pieza llega al borde de su celda.
        cell_w, cell_h = SHEET_SIZE[0] // columns, SHEET_SIZE[1] // rows
        origin_x = origin_y = 0
        step_x, step_y = cell_w, cell_h
    pages = []
    for start in range(0, len(paths), per_sheet):
        page = Image.new("RGBA", SHEET_SIZE, "white")
        if has_title:
            from PIL import ImageDraw, ImageFont
            draw = ImageDraw.Draw(page)
            font = ImageFont.load_default(size=32)
            draw.text((SHEET_SIZE[0] // 2, PHOTO_STRIP_MARGIN_PX + PHOTO_STRIP_TITLE_HEIGHT_PX // 2),
                      title.strip(), fill="black", font=font, anchor="mm")
        for position, path in enumerate(paths[start:start + per_sheet]):
            with _load_print_source(path) as source:
                transform = (transforms or {}).get(str(path), ImageTransform())
                poster, paste_x, paste_y = _apply_image_transform(
                    source, transform, cell_w, cell_h,
                )
                cell = Image.new("RGBA", (cell_w, cell_h), "white")
                cell.paste(poster, (paste_x, paste_y), poster)
                col, row = position % columns, position // columns
                x, y = origin_x + col * step_x, origin_y + row * step_y
                page.alpha_composite(cell, (x, y))
        pages.append(page.convert("RGB"))
    return pages


def uniform_preview_page(paths: list[Path], per_sheet: int, selected_index: int,
                         transforms: dict[str, ImageTransform] | None = None,
                         title: str = "") -> tuple[object, int, int]:
    """Devuelve la hoja real que contiene la imagen seleccionada.

    La vista previa de "Individuales por hoja" debe representar exactamente la
    salida: para un díptico o tríptico no puede mostrar una A4 individual.
    """
    if per_sheet not in LAYOUTS:
        raise ValueError("La cantidad por hoja no es válida.")
    if not paths:
        raise ValueError("No hay imágenes para previsualizar.")
    selected_index = max(0, min(selected_index, len(paths) - 1))
    page_index = selected_index // per_sheet
    first = page_index * per_sheet
    return render_poster_pages(paths[first:first + per_sheet], per_sheet, transforms, title)[0], page_index, first


def _calculate_contain_scale(source_w: int, source_h: int, target_w: int, target_h: int) -> float:
    """Calcula la escala para modo contain (imagen completa, sin recorte)."""
    if source_w <= 0 or source_h <= 0:
        return 1.0
    return min(target_w / source_w, target_h / source_h)


def _calculate_cover_scale(source_w: int, source_h: int, target_w: int, target_h: int) -> float:
    """Calcula la escala para modo cover (llena el marco, puede recortar)."""
    if source_w <= 0 or source_h <= 0:
        return 1.0
    return max(target_w / source_w, target_h / source_h)


def _apply_image_transform(
    source, 
    transform: ImageTransform, 
    frame_w: int, 
    frame_h: int
) -> tuple:
    """Aplica transformación visual a una imagen dentro de su marco.
    
    Args:
        source: Imagen PIL fuente
        transform: Objeto ImageTransform con la configuración
        frame_w: Ancho del marco en píxeles
        frame_h: Alto del marco en píxeles
    
    Returns:
        Tupla (imagen_transformada, paste_x, paste_y) lista para pegar
    """
    from PIL import Image
    
    source_w, source_h = source.size
    
    # Determinar escala base según modo
    if transform.fit_mode == FitMode.CONTAIN:
        base_scale = _calculate_contain_scale(source_w, source_h, frame_w, frame_h)
    elif transform.fit_mode == FitMode.COVER:
        base_scale = _calculate_cover_scale(source_w, source_h, frame_w, frame_h)
    else:  # MANUAL
        base_scale = 1.0
    
    # Aplicar escala manual si está en modo manual o si se modificó
    final_scale = base_scale * transform.image_scale
    
    # Calcular tamaño después de escala
    scaled_w = int(source_w * final_scale)
    scaled_h = int(source_h * final_scale)
    
    # Redimensionar
    if scaled_w > 0 and scaled_h > 0:
        resized = source.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
    else:
        resized = source
    
    # Aplicar rotación visual
    if transform.image_rotation_deg != 0:
        resized = resized.rotate(
            -transform.image_rotation_deg, 
            expand=True,
            # Pillow no admite LANCZOS para transformaciones afines.
            resample=Image.Resampling.BICUBIC
        )
    
    # Calcular posición de pegado con offset
    # Centrar primero
    paste_x = (frame_w - resized.width) // 2
    paste_y = (frame_h - resized.height) // 2
    
    # Aplicar offset (en píxeles relativos al tamaño original de la imagen)
    offset_x_px = int(transform.image_offset_x * final_scale)
    offset_y_px = int(transform.image_offset_y * final_scale)
    
    paste_x += offset_x_px
    paste_y += offset_y_px

    # La imagen siempre queda dentro de su marco: al arrastrarla no puede
    # revelar espacios vacíos ni desplazarse sobre otro póster.
    if transform.fit_mode in (FitMode.COVER, FitMode.MANUAL):
        min_x = frame_w - resized.width if resized.width >= frame_w else (frame_w - resized.width) // 2
        max_x = 0 if resized.width >= frame_w else min_x
        min_y = frame_h - resized.height if resized.height >= frame_h else (frame_h - resized.height) // 2
        max_y = 0 if resized.height >= frame_h else min_y
        paste_x = max(min_x, min(max_x, paste_x))
        paste_y = max(min_y, min(max_y, paste_y))

        # Guardar el valor efectivo para que los campos X/Y coincidan con lo
        # que se ve en la vista previa y también con la impresión final.
        if final_scale:
            transform.image_offset_x = (paste_x - (frame_w - resized.width) // 2) / final_scale
            transform.image_offset_y = (paste_y - (frame_h - resized.height) // 2) / final_scale
    
    return resized, paste_x, paste_y


def render_mixed_poster_pages(packing_result, items_by_id: dict, dpi: int = 300) -> list[object]:
    """Renderiza páginas A4 desde un PackingResult del modo mixto.
    
    Args:
        packing_result: Resultado de pack_mixed_posters()
        items_by_id: Diccionario de MixedElement por ID
        dpi: Resolución en DPI para el renderizado
    
    Returns:
        Lista de imágenes PIL listas para imprimir
    """
    from PIL import Image, ImageOps
    
    # Calcular tamaño de hoja A4 en píxeles
    mm_to_px = dpi / 25.4
    a4_width_px = int(A4_PORTRAIT_MM[0] * mm_to_px)
    a4_height_px = int(A4_PORTRAIT_MM[1] * mm_to_px)
    
    pages = []
    
    for page in packing_result.pages:
        page_img = Image.new("RGB", (a4_width_px, a4_height_px), "white")
        
        for placement in page.placements:
            # Obtener el elemento original
            element = items_by_id.get(placement.item_id)
            if not element:
                continue
            
            # Calcular posición y tamaño en píxeles
            x_px = int(placement.x_mm * mm_to_px)
            y_px = int(placement.y_mm * mm_to_px)
            w_px = int(placement.width_mm * mm_to_px)
            h_px = int(placement.height_mm * mm_to_px)
            
            # Cargar y procesar la imagen
            with Image.open(element.path) as source:
                # Aplicar orientación EXIF
                source = ImageOps.exif_transpose(source)
                
                # Si está rotado físicamente por el packing, rotar la imagen
                if placement.rotation:
                    source = source.rotate(-90, expand=True)
                
                # Convertir a RGBA para transparencia
                source = source.convert("RGBA")
                
                # Aplicar transformación visual
                transformed, paste_offset_x, paste_offset_y = _apply_image_transform(
                    source, 
                    element.transform, 
                    w_px, 
                    h_px
                )
                
                # Calcular posición final en la página
                final_paste_x = x_px + paste_offset_x
                final_paste_y = y_px + paste_offset_y
                
                # Crear máscara de recorte al marco si es necesario
                if (element.transform.fit_mode == FitMode.COVER or 
                    element.transform.fit_mode == FitMode.MANUAL):
                    # Para cover y manual, recortar al área del marco
                    mask = Image.new("L", (w_px, h_px), 0)
                    # Calcular región de la imagen transformada que cae dentro del marco
                    crop_x = max(0, -paste_offset_x)
                    crop_y = max(0, -paste_offset_y)
                    crop_w = min(transformed.width, w_px - paste_offset_x)
                    crop_h = min(transformed.height, h_px - paste_offset_y)
                    
                    if crop_w > 0 and crop_h > 0:
                        cropped = transformed.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))
                        
                        # Centrar el recorte en el marco
                        final_x = x_px + (w_px - cropped.width) // 2
                        final_y = y_px + (h_px - cropped.height) // 2
                        
                        # Pegar con máscara
                        page_img.paste(cropped, (final_x, final_y), cropped)
                else:
                    # Para contain, pegar normalmente (puede haber bordes vacíos)
                    page_img.paste(transformed, (final_paste_x, final_paste_y), transformed)
        
        pages.append(page_img)
    
    return pages


class PosterPrintEditor(tk.Frame):
    """Editor embebido de impresiones fotográficas en hojas A4."""

    def __init__(self, master, database=None):
        super().__init__(master, background=COLORS.background)
        self.database = database
        
        # Estado del modo uniforme (existente)
        self.paths: list[Path] = []
        self.uniform_transforms: dict[str, ImageTransform] = {}
        self.per_sheet_var = tk.IntVar(value=1)
        self.photo_strip_title_var = tk.StringVar(value="")
        
        # Estado del modo mixto (nuevo)
        self.mixed_elements: list[MixedElement] = []
        # La impresión individual es el flujo base: permite seleccionar cuántos
        # pósters del mismo formato salen por hoja.
        self.mode_var = tk.StringVar(value=DistributionMode.UNIFORM.value)
        self.size_policy_var = tk.StringVar(value=SizePolicy.EXACTO.value)
        
        # Estado del modo collage inteligente
        self.collage_template_var = tk.StringVar(value="auto")
        # Sin separación el collage utiliza el 100% de la hoja por defecto.
        self.collage_gap_var = tk.IntVar(value=0)
        self.collage_pages: list[object] = []
        self.collage_layouts: list[tuple[list[Path], object]] = []
        self.collage_offsets: dict[str, tuple[float, float]] = {}
        self.collage_scales: dict[str, float] = {}
        self.collage_rotations: dict[str, int] = {}
        self.collage_manual_images: set[str] = set()
        self.dragging_collage_path: Path | None = None
        self.dragging_collage_cell = None
        self.collage_selected_path: Path | None = None
        self._collage_generator = None
        self._collage_render_after = None

        # Tarjetas 9x5: composición A4 fija, con estado por cara y por posición.
        self.card_slots: list[CardSlot] = [CardSlot() for _ in range(10)]
        self.card_selected: set[int] = set()
        self.card_side_var = tk.StringVar(value="front")
        self.card_double_sided_var = tk.BooleanVar(value=False)
        self.card_bleed_var = tk.DoubleVar(value=CARD_BLEED_MM)
        self.card_offset_x_var = tk.DoubleVar(value=0.0)
        self.card_offset_y_var = tk.DoubleVar(value=0.0)
        self.card_flip_var = tk.StringVar(value="long_edge")
        self.card_drag_last: tuple[int, int] | None = None
        self.card_profile_store = PrinterProfileStore(Path(__file__).resolve().parents[2] / "outputs" / "impresiones_fotograficas" / "printer_profiles.json")
        self.card_profiles = self.card_profile_store.load()
        self.card_profile_var = tk.StringVar(value="")
        
        # Configuración de márgenes y separación (mm)
        self.margin_top_var = tk.DoubleVar(value=0.0)
        self.margin_bottom_var = tk.DoubleVar(value=0.0)
        self.margin_left_var = tk.DoubleVar(value=0.0)
        self.margin_right_var = tk.DoubleVar(value=0.0)
        self.gap_horizontal_var = tk.DoubleVar(value=0.0)
        self.gap_vertical_var = tk.DoubleVar(value=0.0)
        self.rotation_var = tk.DoubleVar(value=0.0)
        
        # Estado de la vista previa mixta
        self.current_page_index = 0
        self.packing_result = None
        self.preview_photo = None
        self.summary_var = tk.StringVar()
        self._thumbnail_cache: dict[str, object] = {}
        
        # Estado para manipulación directa en canvas
        self.dragging_element = None
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.element_offsets = {}  # Cache de offsets por elemento ID
        self.view_zoom = 1.0
        
        # Debounce para recálculos
        self._debounce_refresh = Debounce(delay_ms=500)
        
        self._build()
        self._register_drop()
        
        # Inicializar editor vacío
        self._clear_element_editor()
        self._enable_element_editor(False)
        
        self.on_mode_change()

    def _build(self):
        configure_plancha_styles(self)
        header = tk.Frame(self, background=COLORS.background)
        header.pack(fill="x", padx=18, pady=(16, 10))
        tk.Label(header, text="IMPRESIONES FOTOGRÁFICAS", background=COLORS.background,
                 foreground=COLORS.text, font=(IDENTITY_FONT, 17, "bold")).pack(anchor="w")
        tk.Label(header, text="Armá hojas A4 listas para imprimir. Elegí un formato, acomodá cada foto y exportá el resultado a tamaño real.",
                 background=COLORS.background, foreground=COLORS.muted, font=(UI_FONT, 10), wraplength=1150).pack(anchor="w", pady=(3, 0))

        # Selector de modo
        mode_controls = tk.Frame(self, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        mode_controls.pack(fill="x", padx=18, pady=(0, 10))
        tk.Label(mode_controls, text="ARMADO DE HOJA", background=COLORS.panel,
                 foreground=COLORS.text, font=(UI_FONT, 10, "bold")).pack(side="left", padx=(12, 10), pady=10)
        ttk.Radiobutton(mode_controls, text="Distribución uniforme", value=DistributionMode.UNIFORM.value,
                        variable=self.mode_var, command=self.on_mode_change).pack(side="left", padx=5)
        ttk.Radiobutton(mode_controls, text="Composición mixta", value=DistributionMode.MIXED.value,
                        variable=self.mode_var, command=self.on_mode_change).pack(side="left", padx=5)
        ttk.Radiobutton(mode_controls, text="Collage inteligente", value=DistributionMode.SMART_COLLAGE.value,
                        variable=self.mode_var, command=self.on_mode_change).pack(side="left", padx=5)
        ttk.Radiobutton(mode_controls, text="Tarjetas 9×5", value=DistributionMode.CARDS_9X5.value,
                        variable=self.mode_var, command=self.on_mode_change).pack(side="left", padx=5)
        for control in mode_controls.winfo_children():
            if isinstance(control, ttk.Radiobutton):
                if control.cget("value") == DistributionMode.MIXED.value:
                    control.pack_forget()
                elif control.cget("value") == DistributionMode.UNIFORM.value:
                    control.configure(text="Individuales por hoja")
        # Los ajustes manuales pertenecen a este editor; no reutilizan el
        # comportamiento ni el estado del módulo de planchas regulares.

        toolbar = tk.Frame(self, background=COLORS.background)
        toolbar.pack(fill="x", padx=18, pady=(0, 10))
        ttk.Button(toolbar, text="+ Agregar fotos", command=self.choose_files,
                   style="Plancha.Primary.TButton").pack(side="left", padx=(0, 7))
        ttk.Button(toolbar, text="Pegar imagen", command=self.paste,
                   style="Plancha.Primary.TButton").pack(side="left", padx=(0, 7))
        ttk.Button(toolbar, text="Rellenar", command=lambda: self._set_uniform_fit(FitMode.COVER),
                   style="Plancha.Secondary.TButton").pack(side="left", padx=(0, 7))
        ttk.Button(toolbar, text="Ajustar", command=lambda: self._set_uniform_fit(FitMode.CONTAIN),
                   style="Plancha.Secondary.TButton").pack(side="left", padx=(0, 7))
        ttk.Button(toolbar, text="Restablecer", command=self.reset_uniform_image,
                   style="Plancha.Secondary.TButton").pack(side="left")
        self.quick_save_png_button = ttk.Button(
            toolbar, text="Exportar PNG", command=self.print_continuous,
            style="Plancha.Primary.TButton",
        )
        self.quick_save_png_button.pack(side="right")

        # Contenedor principal con tres sectores usando PanedWindow
        main_body = tk.PanedWindow(self, orient="horizontal", background=COLORS.background, sashwidth=4)
        main_body.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        
        # Sector izquierdo: lista de elementos (35%)
        self.left_panel = tk.Frame(main_body, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        main_body.add(self.left_panel, minsize=210, width=int(1200 * 0.24))
        self._build_left_panel()
        
        # Sector central: edición (27%)
        self.center_panel = tk.Frame(main_body, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        self._build_center_panel()
        
        # Panel de collage (inicialmente oculto)
        self.collage_controls = tk.Frame(self.center_panel, background=COLORS.panel)
        self._build_collage_controls()
        self.cards_controls = tk.Frame(self.center_panel, background=COLORS.panel)
        self._build_cards_controls()
        
        # Sector derecho: vista previa (38%)
        self.right_panel = tk.Frame(main_body, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        self._build_right_panel()
        # Orden visual propio: imágenes, hoja A4 y propiedades.
        main_body.add(self.right_panel, minsize=350, width=int(1200 * 0.42))
        main_body.add(self.center_panel, minsize=290, width=int(1200 * 0.34))

        footer = tk.Frame(self, background=COLORS.background)
        footer.pack(fill="x", padx=18, pady=(0, 16))
        tk.Label(footer, textvariable=self.summary_var, background=COLORS.background,
                 foreground=COLORS.text, font=(UI_FONT, 10)).pack(side="left")
        ttk.Button(footer, text="Cerrar", command=self.destroy).pack(side="right")
        self.print_button = ttk.Button(footer, text="Exportar PNG", command=self.print_continuous,
                                       style="Plancha.Primary.TButton")
        self.print_button.pack(side="right", padx=(0, 7))
        self.pdf_button = ttk.Button(footer, text="Exportar PDF", command=self.export_cards_pdf,
                                     style="Plancha.Secondary.TButton")
        self.continuous_button = ttk.Button(
            footer, text="Enviar a impresión continua", command=self.send_to_continuous,
            style="Plancha.Secondary.TButton",
        )
        self.continuous_button.pack(side="right", padx=(0, 7))
        self.pdf_button.pack(side="right", padx=(0, 7))

    def _build_left_panel(self):
        """Construye el panel izquierdo con lista de elementos."""
        tk.Label(self.left_panel, text="ARCHIVOS", background=COLORS.panel, foreground=COLORS.wine_active,
                 font=(IDENTITY_FONT, 11, "bold")).pack(anchor="w", padx=12, pady=(12, 5))
        tk.Label(self.left_panel, text="Arrastrá imágenes aquí, elegí archivos o pegá desde el portapapeles.",
                 wraplength=190, justify="left", background=COLORS.panel, foreground=COLORS.muted,
                 font=(UI_FONT, 9)).pack(anchor="w", padx=12, pady=(0, 7))
        
        holder = tk.Frame(self.left_panel, background=COLORS.panel)
        holder.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        
        # Treeview único dinámico
        self.tree = ttk.Treeview(holder, columns=("name", "size", "qty"), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="")
        self.tree.column("#0", width=44, minwidth=44, stretch=False, anchor="center")
        
        # Configurar columnas iniciales para modo uniforme
        self.tree.heading("name", text="Foto")
        self.tree.column("name", width=200, anchor="w", stretch=True)
        self.tree.heading("size", text="")
        self.tree.column("size", width=0, stretch=False)
        self.tree.heading("qty", text="")
        self.tree.column("qty", width=0, stretch=False)
        
        # Tooltip para nombres largos
        self.tree.bind("<Motion>", self.on_tree_motion)
        
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        
        # Botones de acción
        actions = tk.Frame(self.left_panel, background=COLORS.panel)
        actions.pack(fill="x", padx=10, pady=(0, 10))
        self.btn_choose = ttk.Button(actions, text="Elegir archivos", command=self.choose_files)
        self.btn_choose.pack(side="left", fill="x", expand=True)
        self.btn_paste = ttk.Button(actions, text="Pegar", command=self.paste)
        self.btn_paste.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.btn_remove = ttk.Button(actions, text="Quitar", command=self.remove_selected, state="disabled")
        self.btn_remove.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.btn_clear = ttk.Button(actions, text="Limpiar", command=self.clear, state="disabled")
        self.btn_clear.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.btn_move_up = ttk.Button(actions, text="↑", width=3, command=lambda: self.move_uniform_photo(-1), state="disabled")
        self.btn_move_up.pack(side="left", padx=(6, 0))
        self.btn_move_down = ttk.Button(actions, text="↓", width=3, command=lambda: self.move_uniform_photo(1), state="disabled")
        self.btn_move_down.pack(side="left", padx=(3, 0))

    def _build_center_panel(self):
        """Construye el panel central con controles de edición."""
        tk.Label(self.center_panel, text="CONFIGURACIÓN", background=COLORS.panel, foreground=COLORS.wine_active,
                 font=(IDENTITY_FONT, 11, "bold")).pack(anchor="w", padx=12, pady=(12, 5))
        
        # Contenedor para controles uniformes
        self.uniform_controls = tk.Frame(self.center_panel, background=COLORS.panel)
        self.uniform_controls.pack(fill="both", expand=True, padx=12, pady=10)
        tk.Label(self.uniform_controls, text="FORMATO DE HOJA", background=COLORS.panel,
                 foreground=COLORS.wine_active, font=(IDENTITY_FONT, 10, "bold")).pack(anchor="w")
        tk.Label(self.uniform_controls, text="La vista previa muestra exactamente la hoja A4 que se va a exportar.",
                 background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 9),
                 wraplength=250, justify="left").pack(anchor="w", pady=(3, 8))
        layout_labels = {
            1: "1 · Foto completa",
            2: "2 · Díptico",
            3: "3 · Tríptico",
            4: "4 · Cuadrícula 2 × 2",
            8: "8 · Cuadrícula 2 × 4",
            16: "16 · Cuadrícula 4 × 4",
            32: "32 · Cuadrícula 4 × 8",
        }
        for count in LAYOUTS:
            ttk.Radiobutton(
                self.uniform_controls,
                text=layout_labels.get(count, f"{count} por hoja"),
                value=count,
                variable=self.per_sheet_var,
                command=self.on_uniform_layout_change,
            ).pack(anchor="w")
        title_row = tk.Frame(self.uniform_controls, background=COLORS.panel)
        title_row.pack(fill="x", pady=(8, 0))
        tk.Label(title_row, text="Título (díptico / tríptico)", background=COLORS.panel,
                 foreground=COLORS.text, font=(UI_FONT, 9)).pack(anchor="w")
        self.title_entry = ttk.Entry(title_row, textvariable=self.photo_strip_title_var)
        self.title_entry.pack(fill="x", pady=(2, 0))
        self.title_entry.bind("<KeyRelease>", lambda _event: self._debounce_refresh(self._refresh_uniform_preview))
        self.title_hint_label = tk.Label(title_row, text="Solo en díptico o tríptico. La franja se agrega únicamente si escribís un título.",
                 background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 8),
                 wraplength=250, justify="left")
        self.title_hint_label.pack(anchor="w", pady=(2, 0))

        self.uniform_adjustments = tk.Frame(self.uniform_controls, background=COLORS.panel)
        self.uniform_adjustments.pack(fill="x", pady=(16, 0))
        tk.Label(self.uniform_adjustments, text="AJUSTE DE IMAGEN", background=COLORS.panel,
                 foreground=COLORS.wine_active, font=(IDENTITY_FONT, 10, "bold")).pack(anchor="w")
        self.uniform_selection_label = tk.Label(self.uniform_adjustments, text="Seleccioná una imagen para editarla.",
                                                background=COLORS.panel, foreground=COLORS.muted,
                                                wraplength=230, justify="left", font=(UI_FONT, 9))
        self.uniform_selection_label.pack(anchor="w", pady=(3, 6))
        self.uniform_fit_var = tk.StringVar(value=FitMode.COVER.value)
        fit_row = tk.Frame(self.uniform_adjustments, background=COLORS.panel)
        fit_row.pack(fill="x")
        for label, value in (("Rellenar", FitMode.COVER.value), ("Ajustar", FitMode.CONTAIN.value)):
            ttk.Radiobutton(fit_row, text=label, value=value, variable=self.uniform_fit_var,
                            command=self.on_uniform_transform_change).pack(side="left", padx=(0, 7))
        self.uniform_x_var = tk.DoubleVar(value=0.0)
        self.uniform_y_var = tk.DoubleVar(value=0.0)
        self.uniform_scale_var = tk.DoubleVar(value=100.0)
        self.uniform_rotation_var = tk.DoubleVar(value=0.0)
        for label, variable, minimum, maximum in (
            ("Posición horizontal", self.uniform_x_var, -1000, 1000),
            ("Posición vertical", self.uniform_y_var, -1000, 1000),
            ("Escala %", self.uniform_scale_var, 10, 500),
            ("Rotación °", self.uniform_rotation_var, -180, 180),
        ):
            row = tk.Frame(self.uniform_adjustments, background=COLORS.panel)
            row.pack(fill="x", pady=(5, 0))
            tk.Label(row, text=label, width=18, anchor="w", background=COLORS.panel,
                     foreground=COLORS.text, font=(UI_FONT, 9)).pack(side="left")
            control = ttk.Spinbox(row, from_=minimum, to=maximum, increment=1, textvariable=variable, width=7,
                                  command=self.on_uniform_transform_change)
            control.pack(side="left")
            control.bind("<KeyRelease>", lambda _event: self._debounce_refresh(self.on_uniform_transform_change))
        actions = tk.Frame(self.uniform_adjustments, background=COLORS.panel)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="Centrar", command=self.center_uniform_image).pack(side="left", fill="x", expand=True)
        ttk.Button(actions, text="Auto", command=self.reset_uniform_image).pack(side="left", fill="x", expand=True, padx=(5, 0))
        
        # Contenedor para controles mixtos con scroll
        self.mixed_controls = tk.Frame(self.center_panel, background=COLORS.panel)
        # No se muestra inicialmente, se activa en on_mode_change
        
        # Canvas para scroll
        self.mixed_canvas = tk.Canvas(self.mixed_controls, background=COLORS.panel, highlightthickness=0)
        self.mixed_scroll = ttk.Scrollbar(self.mixed_controls, orient="vertical", command=self.mixed_canvas.yview)
        self.mixed_canvas.configure(yscrollcommand=self.mixed_scroll.set)
        
        self.mixed_scroll.pack(side="right", fill="y")
        self.mixed_canvas.pack(side="left", fill="both", expand=True)
        
        # Frame de contenido dentro del canvas
        self.mixed_content = tk.Frame(self.mixed_canvas, background=COLORS.panel)
        self.mixed_canvas.create_window((0, 0), window=self.mixed_content, anchor="nw")
        self.mixed_content.bind("<Configure>", lambda e: self.mixed_canvas.configure(scrollregion=self.mixed_canvas.bbox("all")))
        
        # Indicadores compactos
        self.indicators_frame = tk.Frame(self.mixed_content, background=COLORS.panel, relief="ridge", borderwidth=1)
        self.indicators_frame.pack(fill="x", pady=(5, 5))
        self.indicators_label = tk.Label(self.indicators_frame, text="Hojas: 0 | Colocados: 0 | Sin colocar: 0 | Ocupación: 0%",
                                        background=COLORS.panel, foreground=COLORS.text, font=(UI_FONT, 9))
        self.indicators_label.pack(anchor="center", padx=5, pady=2)
        
        # Edición de elemento seleccionado - Fila compacta 1: Preset + Unidad
        tk.Label(self.mixed_content, text="Elemento seleccionado", background=COLORS.panel,
                 foreground=COLORS.text, font=(UI_FONT, 10, "bold")).pack(anchor="w", pady=(5, 2))
        
        # Mensaje cuando no hay selección
        self.no_selection_label = tk.Label(self.mixed_content, text="Click en imagen para editar",
                                           background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 9))
        self.no_selection_label.pack(anchor="w", pady=(2, 2))
        
        # Fila 1: Preset + Dimensiones + Cantidad
        row1 = tk.Frame(self.mixed_content, background=COLORS.panel)
        row1.pack(fill="x", pady=(0, 2))
        tk.Label(row1, text="Preset:", background=COLORS.panel, foreground=COLORS.text).pack(side="left")
        self.preset_var = tk.StringVar(value="Personalizado")
        preset_combo = ttk.Combobox(row1, textvariable=self.preset_var, width=10, state="readonly")
        preset_combo['values'] = ["Personalizado", "A5", "A6", "A7", "10×15 cm", "13×18 cm"]
        preset_combo.pack(side="left", padx=2)
        preset_combo.bind("<<ComboboxSelected>>", self.on_preset_change)
        
        tk.Label(row1, text="Ancho:", background=COLORS.panel, foreground=COLORS.text).pack(side="left", padx=(5, 0))
        self.width_var = tk.StringVar()
        self.width_entry = ttk.Entry(row1, textvariable=self.width_var, width=6)
        self.width_entry.pack(side="left", padx=1)
        self.width_entry.bind("<KeyRelease>", lambda e: self._debounce_refresh(self.on_dimension_change))
        
        tk.Label(row1, text="Alto:", background=COLORS.panel, foreground=COLORS.text).pack(side="left", padx=(2, 0))
        self.height_var = tk.StringVar()
        self.height_entry = ttk.Entry(row1, textvariable=self.height_var, width=6)
        self.height_entry.pack(side="left", padx=1)
        self.height_entry.bind("<KeyRelease>", lambda e: self._debounce_refresh(self.on_dimension_change))
        
        tk.Label(row1, text="Cant:", background=COLORS.panel, foreground=COLORS.text).pack(side="left", padx=(5, 0))
        self.quantity_var = tk.IntVar(value=1)
        self.quantity_spinbox = ttk.Spinbox(row1, from_=1, to=100, textvariable=self.quantity_var, width=4)
        self.quantity_spinbox.pack(side="left", padx=1)
        
        # Fila 2: Orientación + Rotación
        row2 = tk.Frame(self.mixed_content, background=COLORS.panel)
        row2.pack(fill="x", pady=(0, 2))
        self.orientation_var = tk.StringVar(value=Orientation.AUTOMATIC.value)
        ttk.Radiobutton(row2, text="Auto", value=Orientation.AUTOMATIC.value,
                        variable=self.orientation_var, width=4).pack(side="left", padx=1)
        ttk.Radiobutton(row2, text="Vert", value=Orientation.PORTRAIT.value,
                        variable=self.orientation_var, width=4).pack(side="left", padx=1)
        ttk.Radiobutton(row2, text="Horiz", value=Orientation.LANDSCAPE.value,
                        variable=self.orientation_var, width=4).pack(side="left", padx=1)
        self.allow_rotation_var = tk.BooleanVar(value=True)
        self.rotation_checkbutton = ttk.Checkbutton(row2, text="Rotar", variable=self.allow_rotation_var)
        self.rotation_checkbutton.pack(side="left", padx=(5, 0))
        
        # Fila 3: Botones de acción
        row3 = tk.Frame(self.mixed_content, background=COLORS.panel)
        row3.pack(fill="x", pady=(3, 2))
        self.btn_duplicate = ttk.Button(row3, text="Duplicar", command=self.duplicate_element, state="disabled")
        self.btn_duplicate.pack(side="left", fill="x", expand=True)
        self.btn_apply = ttk.Button(
            row3,
            text="Aplicar cambios",
            command=self.apply_to_selected,
            state="disabled",
        )
        self.btn_apply.pack(side="left", fill="x", expand=True, padx=(5, 0))
        
        # Transformación de imagen
        tk.Label(self.mixed_content, text="Ajuste de imagen", background=COLORS.panel,
                 foreground=COLORS.text, font=(UI_FONT, 9, "bold")).pack(anchor="w", pady=(5, 2))
        
        # Modo de ajuste
        transform_row1 = tk.Frame(self.mixed_content, background=COLORS.panel)
        transform_row1.pack(fill="x", pady=(0, 2))
        self.fit_mode_var = tk.StringVar(value=FitMode.COVER.value)
        ttk.Radiobutton(transform_row1, text="Cover", value=FitMode.COVER.value,
                        variable=self.fit_mode_var, command=self.on_transform_change).pack(side="left", padx=2)
        ttk.Radiobutton(transform_row1, text="Contain", value=FitMode.CONTAIN.value,
                        variable=self.fit_mode_var, command=self.on_transform_change).pack(side="left", padx=2)
        ttk.Radiobutton(transform_row1, text="Manual", value=FitMode.MANUAL.value,
                        variable=self.fit_mode_var, command=self.on_transform_change).pack(side="left", padx=2)
        
        # Offset X y Y
        transform_row2 = tk.Frame(self.mixed_content, background=COLORS.panel)
        transform_row2.pack(fill="x", pady=(0, 2))
        tk.Label(transform_row2, text="X:", background=COLORS.panel, foreground=COLORS.text).pack(side="left")
        self.offset_x_var = tk.DoubleVar(value=0.0)
        offset_x_entry = ttk.Entry(transform_row2, textvariable=self.offset_x_var, width=6)
        offset_x_entry.pack(side="left", padx=2)
        offset_x_entry.bind("<KeyRelease>", lambda _event: self._debounce_refresh(self.on_transform_change))
        tk.Label(transform_row2, text="Y:", background=COLORS.panel, foreground=COLORS.text).pack(side="left", padx=(5, 0))
        self.offset_y_var = tk.DoubleVar(value=0.0)
        offset_y_entry = ttk.Entry(transform_row2, textvariable=self.offset_y_var, width=6)
        offset_y_entry.pack(side="left", padx=2)
        offset_y_entry.bind("<KeyRelease>", lambda _event: self._debounce_refresh(self.on_transform_change))
        
        # Escala
        transform_row3 = tk.Frame(self.mixed_content, background=COLORS.panel)
        transform_row3.pack(fill="x", pady=(0, 2))
        tk.Label(transform_row3, text="Escala %:", background=COLORS.panel, foreground=COLORS.text).pack(side="left")
        self.scale_var = tk.DoubleVar(value=100.0)
        scale_spinbox = ttk.Spinbox(transform_row3, from_=10, to=500, textvariable=self.scale_var, width=6)
        scale_spinbox.pack(side="left", padx=2)
        scale_spinbox.bind("<KeyRelease>", lambda e: self._debounce_refresh(self.on_transform_change))

        rotation_row = tk.Frame(self.mixed_content, background=COLORS.panel)
        rotation_row.pack(fill="x", pady=(0, 2))
        tk.Label(rotation_row, text="Rotación °:", background=COLORS.panel,
                 foreground=COLORS.text).pack(side="left")
        rotation_spinbox = ttk.Spinbox(
            rotation_row, from_=-180, to=180, increment=1,
            textvariable=self.rotation_var, width=6, command=self.on_transform_change,
        )
        rotation_spinbox.pack(side="left", padx=2)
        rotation_spinbox.bind("<KeyRelease>", lambda _event: self._debounce_refresh(self.on_transform_change))
        
        # Botón único de acción
        transform_row4 = tk.Frame(self.mixed_content, background=COLORS.panel)
        transform_row4.pack(fill="x", pady=(3, 2))
        ttk.Button(transform_row4, text="Centrar", command=self.center_image).pack(side="left", fill="x", expand=True)
        ttk.Button(transform_row4, text="Auto", command=self.auto_fit_image).pack(side="left", fill="x", expand=True, padx=(3, 0))
        
        # Márgenes - Fila 1: 4 márgenes
        tk.Label(self.mixed_content, text="Márgenes (mm)", background=COLORS.panel,
                 foreground=COLORS.text, font=(UI_FONT, 9, "bold")).pack(anchor="w", pady=(5, 2))
        
        margin_row1 = tk.Frame(self.mixed_content, background=COLORS.panel)
        margin_row1.pack(fill="x", pady=(0, 2))
        tk.Label(margin_row1, text="Sup:", background=COLORS.panel, foreground=COLORS.text).pack(side="left")
        ttk.Entry(margin_row1, textvariable=self.margin_top_var, width=6).pack(side="left", padx=2)
        tk.Label(margin_row1, text="Inf:", background=COLORS.panel, foreground=COLORS.text).pack(side="left", padx=(5, 0))
        ttk.Entry(margin_row1, textvariable=self.margin_bottom_var, width=6).pack(side="left", padx=2)
        tk.Label(margin_row1, text="Izq:", background=COLORS.panel, foreground=COLORS.text).pack(side="left", padx=(5, 0))
        ttk.Entry(margin_row1, textvariable=self.margin_left_var, width=6).pack(side="left", padx=2)
        tk.Label(margin_row1, text="Der:", background=COLORS.panel, foreground=COLORS.text).pack(side="left", padx=(5, 0))
        ttk.Entry(margin_row1, textvariable=self.margin_right_var, width=6).pack(side="left", padx=2)
        
        # Fila 2: Separaciones
        margin_row2 = tk.Frame(self.mixed_content, background=COLORS.panel)
        margin_row2.pack(fill="x", pady=(0, 1))
        tk.Label(margin_row2, text="Sep. H:", background=COLORS.panel, foreground=COLORS.text).pack(side="left")
        ttk.Entry(margin_row2, textvariable=self.gap_horizontal_var, width=6).pack(side="left", padx=2)
        tk.Label(margin_row2, text="Sep. V:", background=COLORS.panel, foreground=COLORS.text).pack(side="left", padx=(5, 0))
        ttk.Entry(margin_row2, textvariable=self.gap_vertical_var, width=6).pack(side="left", padx=2)
        
        # Accesos rápidos
        quick_frame = tk.Frame(self.mixed_content, background=COLORS.panel)
        quick_frame.pack(fill="x", pady=(2, 0))
        ttk.Button(quick_frame, text="Sin márgenes", command=self.set_no_margins).pack(side="left", fill="x", expand=True)
        ttk.Button(quick_frame, text="Optimizar", command=self.optimize_distribution).pack(side="left", fill="x", expand=True, padx=(3, 0))
        
        # Política de tamaño con explicación
        tk.Label(self.mixed_content, text="Política de tamaño", background=COLORS.panel,
                 foreground=COLORS.text, font=(UI_FONT, 9, "bold")).pack(anchor="w", pady=(5, 2))
        policy_frame = tk.Frame(self.mixed_content, background=COLORS.panel)
        policy_frame.pack(fill="x")
        ttk.Radiobutton(policy_frame, text="Tamaño exacto", value=SizePolicy.EXACTO.value,
                        variable=self.size_policy_var, command=self.on_policy_change).pack(anchor="w")
        self.policy_info = tk.Label(self.mixed_content, text="Las medidas no se modifican. Los elementos que no entren quedarán sin colocar.",
                                    background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 8), wraplength=280)
        self.policy_info.pack(anchor="w", pady=(0, 2))
        ttk.Radiobutton(policy_frame, text="Ajustar al área imprimible", value=SizePolicy.AJUSTAR_AL_AREA_IMPRIMIBLE.value,
                        variable=self.size_policy_var, command=self.on_policy_change).pack(anchor="w")

    def _build_cards_controls(self):
        tk.Label(self.cards_controls, text="TARJETAS 9×5", background=COLORS.panel,
                 foreground=COLORS.wine_active, font=(IDENTITY_FONT, 11, "bold")).pack(anchor="w")
        tk.Label(self.cards_controls, text="A4 vertical: 10 tarjetas de 90 × 50 mm (2 × 5). Elegí un diseño de la lista y aplicalo a las posiciones seleccionadas.",
                 background=COLORS.panel, foreground=COLORS.muted, wraplength=260, justify="left").pack(anchor="w", pady=(4, 8))
        side = tk.Frame(self.cards_controls, background=COLORS.panel); side.pack(fill="x")
        ttk.Radiobutton(side, text="Frente", value="front", variable=self.card_side_var, command=self.refresh_cards).pack(side="left")
        ttk.Radiobutton(side, text="Reverso", value="back", variable=self.card_side_var, command=self.refresh_cards).pack(side="left", padx=6)
        ttk.Checkbutton(self.cards_controls, text="Tarjeta doble faz", variable=self.card_double_sided_var,
                        command=self.refresh_cards).pack(anchor="w", pady=(6, 2))
        profile_row = tk.Frame(self.cards_controls, background=COLORS.panel); profile_row.pack(fill="x", pady=(4, 2))
        tk.Label(profile_row, text="Perfil impresora", background=COLORS.panel).pack(side="left")
        self.card_profile_combo = ttk.Combobox(profile_row, textvariable=self.card_profile_var, state="readonly", width=16)
        self.card_profile_combo.pack(side="left", padx=4, fill="x", expand=True)
        self.card_profile_combo.bind("<<ComboboxSelected>>", lambda _event: self.apply_selected_card_profile())
        self._refresh_card_profile_choices()
        ttk.Button(self.cards_controls, text="Calibrar impresión", command=self.open_cards_calibration).pack(fill="x", pady=2)
        buttons = tk.Frame(self.cards_controls, background=COLORS.panel); buttons.pack(fill="x", pady=4)
        ttk.Button(buttons, text="Seleccionar todas", command=self.select_all_cards).pack(side="left", fill="x", expand=True)
        ttk.Button(buttons, text="Aplicar a seleccionadas", command=self.apply_design_to_selected_cards).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(self.cards_controls, text="Aplicar diseño a todas", command=lambda: self.apply_design_to_cards(range(10))).pack(fill="x", pady=2)
        ttk.Button(self.cards_controls, text="Restaurar diseño general", command=self.restore_card_general_design).pack(fill="x", pady=2)
        ttk.Button(self.cards_controls, text="Rotar seleccionadas 90°", command=self.rotate_selected_cards).pack(fill="x", pady=2)
        fit = tk.Frame(self.cards_controls, background=COLORS.panel); fit.pack(fill="x", pady=(5, 0))
        tk.Label(fit, text="Ajuste:", background=COLORS.panel).pack(side="left")
        self.card_fit_var = tk.StringVar(value=FitMode.COVER.value)
        for label, value in (("Cubrir", FitMode.COVER.value), ("Contener", FitMode.CONTAIN.value), ("Manual", FitMode.MANUAL.value)):
            ttk.Radiobutton(fit, text=label, value=value, variable=self.card_fit_var, command=self.set_selected_cards_fit).pack(side="left", padx=2)
        scale = tk.Frame(self.cards_controls, background=COLORS.panel); scale.pack(fill="x", pady=3)
        ttk.Button(scale, text="Escala −", command=lambda: self.scale_selected_cards(.9)).pack(side="left", fill="x", expand=True)
        ttk.Button(scale, text="Escala +", command=lambda: self.scale_selected_cards(1.1)).pack(side="left", fill="x", expand=True, padx=4)
        adjustments = tk.Frame(self.cards_controls, background=COLORS.panel); adjustments.pack(fill="x", pady=(8, 2))
        tk.Label(adjustments, text="Sangrado / corrección reverso (mm)", background=COLORS.panel, foreground=COLORS.text).pack(anchor="w")
        tk.Label(adjustments, text="Las tarjetas no tienen canal: el sangrado se imprime solo hacia el borde exterior de la matriz.",
                 background=COLORS.panel, foreground=COLORS.muted, wraplength=250, justify="left", font=(UI_FONT, 8)).pack(anchor="w")
        for label, var in (("Sangrado", self.card_bleed_var), ("Offset X", self.card_offset_x_var), ("Offset Y", self.card_offset_y_var)):
            row = tk.Frame(adjustments, background=COLORS.panel); row.pack(anchor="w")
            tk.Label(row, text=label, width=10, anchor="w", background=COLORS.panel).pack(side="left")
            ttk.Spinbox(row, from_=-20, to=20, increment=0.1, textvariable=var, width=8, command=self.refresh_cards).pack(side="left")
        tk.Label(self.cards_controls, text="Volteo", background=COLORS.panel, foreground=COLORS.text).pack(anchor="w", pady=(5, 0))
        for label, value in (("Borde largo", "long_edge"), ("Borde corto", "short_edge"), ("Manual", "manual")):
            ttk.Radiobutton(self.cards_controls, text=label, value=value, variable=self.card_flip_var, command=self.refresh_cards).pack(anchor="w")
        tk.Label(self.cards_controls, text="Producción: imprimir/exportar a tamaño real (100 %). No usar ‘Ajustar a página’.",
                 background=COLORS.panel, foreground=COLORS.wine_active, wraplength=260, justify="left", font=(UI_FONT, 8, "bold")).pack(anchor="w", pady=(8, 0))

    def _build_collage_controls(self):
        """Construye los controles para el modo collage inteligente."""
        # Título
        tk.Label(self.collage_controls, text="COLLAGE INTELIGENTE", background=COLORS.panel,
                 foreground=COLORS.wine_active, font=(IDENTITY_FONT, 11, "bold")).pack(anchor="w", padx=0, pady=(0, 5))
        
        tk.Label(self.collage_controls, text="Crea layouts automáticos que detectan caras y elementos importantes para evitar cortarlos.",
                 background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 8),
                 wraplength=260, justify="left").pack(anchor="w", padx=0, pady=(0, 10))
        
        # Scrollable content
        canvas = tk.Canvas(self.collage_controls, background=COLORS.panel, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.collage_controls, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, background=COLORS.panel)
        
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        
        self.collage_content = scrollable_frame
        
        # Template selector
        tk.Label(self.collage_content, text="Estilo de collage", background=COLORS.panel,
                 foreground=COLORS.text, font=(UI_FONT, 9, "bold")).pack(anchor="w", pady=(0, 2))
        
        template_frame = tk.Frame(self.collage_content, background=COLORS.panel)
        template_frame.pack(fill="x", pady=(0, 10))
        
        templates = [
            ("Automático", "auto"),
            ("1 grande", "single_large"),
            ("2 verticales", "two_vertical"),
            ("2 horizontales", "two_horizontal"),
            ("3 mixtas", "three_mixed"),
            ("Grid 2x2", "four_grid"),
            ("5 con foco", "five_focus"),
            ("Grid 3x2", "six_grid"),
            ("Estilo revista", "magazine_style"),
            ("Hero + strip", "hero_strip"),
        ]
        
        for text, value in templates:
            ttk.Radiobutton(template_frame, text=text, value=value,
                           variable=self.collage_template_var,
                           command=self.on_collage_settings_change).pack(anchor="w", pady=1)
        
        # Gap/separación
        tk.Label(self.collage_content, text="Separación entre imágenes", background=COLORS.panel,
                 foreground=COLORS.text, font=(UI_FONT, 9, "bold")).pack(anchor="w", pady=(10, 2))
        
        gap_frame = tk.Frame(self.collage_content, background=COLORS.panel)
        gap_frame.pack(fill="x", pady=(0, 5))
        
        tk.Label(gap_frame, text="Píxeles:", background=COLORS.panel, foreground=COLORS.muted,
                 font=(UI_FONT, 8)).pack(side="left", padx=(0, 5))
        
        gap_spinbox = ttk.Spinbox(gap_frame, from_=0, to=100, increment=5,
                                   textvariable=self.collage_gap_var, width=8,
                                   command=self.on_collage_settings_change)
        gap_spinbox.pack(side="left")

        tk.Label(self.collage_content, text="Imagen seleccionada", background=COLORS.panel,
                 foreground=COLORS.text, font=(UI_FONT, 9, "bold")).pack(anchor="w", pady=(10, 3))
        edit_frame = tk.Frame(self.collage_content, background=COLORS.panel)
        edit_frame.pack(anchor="w")
        ttk.Button(edit_frame, text="←", width=3, command=lambda: self.move_collage_selection(-60, 0)).grid(row=1, column=0, padx=2, pady=2)
        ttk.Button(edit_frame, text="↑", width=3, command=lambda: self.move_collage_selection(0, -60)).grid(row=0, column=1, padx=2, pady=2)
        ttk.Button(edit_frame, text="↓", width=3, command=lambda: self.move_collage_selection(0, 60)).grid(row=1, column=1, padx=2, pady=2)
        ttk.Button(edit_frame, text="→", width=3, command=lambda: self.move_collage_selection(60, 0)).grid(row=1, column=2, padx=2, pady=2)
        ttk.Button(edit_frame, text="−", width=3, command=lambda: self.adjust_collage_zoom(0.9)).grid(row=0, column=3, padx=(12, 2), pady=2)
        ttk.Button(edit_frame, text="+", width=3, command=lambda: self.adjust_collage_zoom(1.1)).grid(row=1, column=3, padx=(12, 2), pady=2)
        ttk.Button(edit_frame, text="Rotar 90°", command=self.rotate_collage_selection).grid(row=0, column=4, rowspan=2, padx=(12, 2), pady=2)

        
        # Información
        info_text = ("💡 El sistema detecta automáticamente caras y elementos importantes "
                    "en las imágenes para evitar cortarlos al crear el collage. "
                    "Las imágenes se ajustan inteligentemente para ocupar el 100% de la hoja.")
        
        info_label = tk.Label(self.collage_content, text=info_text,
                             background=COLORS.panel, foreground=COLORS.muted,
                             font=(UI_FONT, 8), wraplength=260, justify="left")
        info_label.pack(anchor="w", pady=(15, 5))
        
        # Botón para regenerar
        ttk.Button(self.collage_content, text="🔄 Regenerar collage",
                  command=self.on_collage_settings_change,
                  style="Plancha.Primary.TButton").pack(fill="x", pady=(10, 0))

    def _build_right_panel(self):
        """Construye el panel derecho con vista previa."""
        tk.Label(self.right_panel, text="VISTA PREVIA", background=COLORS.panel, foreground=COLORS.wine_active,
                 font=(IDENTITY_FONT, 11, "bold")).pack(anchor="w", padx=12, pady=(12, 5))
        
        # Información de hoja actual (simplificada)
        self.sheet_info_label = tk.Label(self.right_panel, text="",
                                          background=COLORS.panel, foreground=COLORS.text, font=(UI_FONT, 9))
        self.sheet_info_label.pack(anchor="w", padx=12, pady=(0, 5))
        
        # Toolbar de edición de imagen sobre la vista previa
        preview_toolbar = tk.Frame(self.right_panel, background=COLORS.panel)
        preview_toolbar.pack(fill="x", padx=12, pady=(0, 8))
        for index, (label, command) in enumerate((
            ("Ajustar", self.contain_selected_image),
            ("Rellenar", self.cover_selected_image),
            ("Centrar", self.center_selected_image),
            ("Escala -", lambda: self.scale_selected_image(-2)),
            ("Escala +", lambda: self.scale_selected_image(2)),
            ("Rotar ←", lambda: self.rotate_selected_image(-90)),
            ("Rotar →", lambda: self.rotate_selected_image(90)),
            ("Restablecer", self.reset_selected_image),
        )):
            ttk.Button(preview_toolbar, text=label, command=command, width=11).grid(
                row=index // 4, column=index % 4, padx=2, pady=2, sticky="ew",
            )
        for column in range(4):
            preview_toolbar.grid_columnconfigure(column, weight=1)

        # Contenedor para vista previa sin scrollbars en vista normal
        preview_container = tk.Frame(self.right_panel, background=COLORS.panel)
        preview_container.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        preview_container.grid_rowconfigure(0, weight=1)
        preview_container.grid_columnconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(preview_container, background=COLORS.canvas,
                                        highlightthickness=0, cursor="hand2")
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")

        self.preview_vscroll = ttk.Scrollbar(preview_container, orient="vertical", command=self.preview_canvas.yview)
        self.preview_hscroll = ttk.Scrollbar(preview_container, orient="horizontal", command=self.preview_canvas.xview)
        self.preview_canvas.configure(yscrollcommand=self.preview_vscroll.set, xscrollcommand=self.preview_hscroll.set)

        # Bind eventos de mouse para manipulación directa
        self.preview_canvas.bind("<ButtonPress-1>", self.on_preview_mouse_down)
        self.preview_canvas.bind("<B1-Motion>", self.on_preview_mouse_drag)
        self.preview_canvas.bind("<ButtonRelease-1>", self.on_preview_mouse_up)
        self.preview_canvas.bind("<Left>", self.on_arrow_key)
        self.preview_canvas.bind("<Right>", self.on_arrow_key)
        self.preview_canvas.bind("<Up>", self.on_arrow_key)
        self.preview_canvas.bind("<Down>", self.on_arrow_key)
        self.preview_canvas.bind("<Delete>", self.on_delete_key)
        self.preview_canvas.bind("<plus>", self.on_scale_key)
        self.preview_canvas.bind("<minus>", self.on_scale_key)
        self.preview_canvas.bind("<KP_Add>", self.on_scale_key)
        self.preview_canvas.bind("<KP_Subtract>", self.on_scale_key)
        self.preview_canvas.bind("<MouseWheel>", self.on_preview_wheel)
        self.preview_canvas.bind("<Button-4>", self.on_preview_wheel)
        self.preview_canvas.bind("<Button-5>", self.on_preview_wheel)
        self.preview_canvas.bind("<Configure>", lambda _event: self._debounce_refresh(self._render_current_preview))

        # Footer fijo con navegación y zoom de hoja
        footer_frame = tk.Frame(self.right_panel, background=COLORS.panel, relief="ridge", borderwidth=1)
        footer_frame.pack(fill="x", padx=12, pady=(0, 10))

        nav_row = tk.Frame(footer_frame, background=COLORS.panel)
        nav_row.pack(fill="x", padx=5, pady=5)
        ttk.Button(nav_row, text="|◀", command=self.first_page, width=4).pack(side="left", padx=2)
        ttk.Button(nav_row, text="◀", command=self.prev_page, width=4).pack(side="left", padx=2)
        self.page_label = tk.Label(nav_row, text="Hoja 1 de 1", background=COLORS.panel, foreground=COLORS.text, font=(UI_FONT, 9))
        self.page_label.pack(side="left", padx=10)
        ttk.Button(nav_row, text="▶", command=self.next_page, width=4).pack(side="left", padx=2)
        ttk.Button(nav_row, text="▶|", command=self.last_page, width=4).pack(side="left", padx=2)

        zoom_row = tk.Frame(footer_frame, background=COLORS.panel)
        zoom_row.pack(fill="x", padx=5, pady=(0, 5))
        ttk.Button(zoom_row, text="Zoom -", command=lambda: self._change_view_zoom(0.9), width=7).pack(side="left", padx=2)
        self.zoom_label = tk.Label(zoom_row, text="100%", background=COLORS.panel, foreground=COLORS.text, font=(UI_FONT, 9))
        self.zoom_label.pack(side="left", padx=5)
        ttk.Button(zoom_row, text="Zoom +", command=lambda: self._change_view_zoom(1.1), width=7).pack(side="left", padx=2)
        ttk.Button(zoom_row, text="Encajar hoja", command=self.fit_to_window, width=12).pack(side="right", padx=2)

    def _event_is_on_preview(self, event) -> bool:
        """Indica si el puntero está dentro de la hoja mostrada en el canvas."""
        if not hasattr(self, "preview_img_offset") or not hasattr(self, "preview_img_size"):
            return False
        x_offset, y_offset = self.preview_img_offset
        width, height = self.preview_img_size
        return x_offset <= event.x <= x_offset + width and y_offset <= event.y <= y_offset + height

    def on_preview_mouse_down(self, event):
        if self.mode_var.get() == DistributionMode.SMART_COLLAGE.value:
            self._start_collage_drag(event)
            return
        if self.mode_var.get() == DistributionMode.UNIFORM.value:
            current = self._selected_uniform_transform()
            if not current or not self._event_is_on_preview(event):
                return
            self.dragging_element = current[1]
            self.drag_start_x, self.drag_start_y = event.x, event.y
            self.preview_canvas.focus_set()
            self.preview_canvas.config(cursor="fleur")
            return
        if self.mode_var.get() == DistributionMode.CARDS_9X5.value:
            self.on_cards_mouse_down(event)
            return
        """Maneja el click del mouse en la vista previa."""
        if not self.packing_result or not self.packing_result.pages:
            return
        
        # Verificar si tenemos las dimensiones de la imagen
        if not hasattr(self, 'preview_img_offset') or not hasattr(self, 'preview_img_size'):
            return
        
        # Ajustar coordenadas del mouse al offset de la imagen
        img_offset_x, img_offset_y = self.preview_img_offset
        img_width, img_height = self.preview_img_size
        orig_width, orig_height = self.preview_original_size
        
        # Verificar si el click está dentro de la imagen
        if not (img_offset_x <= event.x <= img_offset_x + img_width and
                img_offset_y <= event.y <= img_offset_y + img_height):
            return
        
        # Convertir coordenadas del canvas a coordenadas de la imagen original
        scale_x = orig_width / img_width
        scale_y = orig_height / img_height
        
        orig_x = (event.x - img_offset_x) * scale_x
        orig_y = (event.y - img_offset_y) * scale_y
        
        # Buscar elemento bajo el click y seleccionarlo automáticamente
        page = self.packing_result.pages[self.current_page_index]
        dpi_preview = 72
        mm_to_px = dpi_preview / 25.4
        
        for placement in page.placements:
            # Calcular posición del marco en la imagen original
            frame_x = int(placement.x_mm * mm_to_px)
            frame_y = int(placement.y_mm * mm_to_px)
            frame_w = int(placement.width_mm * mm_to_px)
            frame_h = int(placement.height_mm * mm_to_px)
            
            # Verificar si el click está dentro del marco
            if (frame_x <= orig_x <= frame_x + frame_w and 
                frame_y <= orig_y <= frame_y + frame_h):
                # Encontrar el elemento correspondiente
                for i, element in enumerate(self.mixed_elements):
                    if element.id == placement.item_id:
                        # Seleccionar en treeview
                        self.tree.selection_set(str(i))
                        self.tree.focus(str(i))
                        
                        # Habilitar arrastre
                        self.dragging_element = element
                        self.drag_start_x = event.x
                        self.drag_start_y = event.y
                        self.preview_canvas.config(cursor="hand2")
                        
                        # Actualizar editor con el elemento seleccionado
                        self._populate_element_editor(element)
                        self._enable_element_editor(True)
                        break
                break

    def on_preview_mouse_drag(self, event):
        if self.dragging_collage_path is not None:
            self._drag_collage_image(event)
            return
        if self.mode_var.get() == DistributionMode.UNIFORM.value:
            if not self.dragging_element or not hasattr(self, "preview_img_size"):
                return
            img_width, img_height = self.preview_img_size
            orig_width, orig_height = self.preview_original_size
            self.dragging_element.image_offset_x += (event.x - self.drag_start_x) * orig_width / img_width
            self.dragging_element.image_offset_y += (event.y - self.drag_start_y) * orig_height / img_height
            self.dragging_element.auto_fitted = False
            self.drag_start_x, self.drag_start_y = event.x, event.y
            self.uniform_x_var.set(self.dragging_element.image_offset_x)
            self.uniform_y_var.set(self.dragging_element.image_offset_y)
            self.render_single_image_in_a4()
            return
        if self.mode_var.get() == DistributionMode.CARDS_9X5.value:
            self.on_cards_mouse_drag(event)
            return
        """Maneja el arrastre del mouse en la vista previa."""
        if not self.dragging_element:
            return
        
        # Verificar si tenemos las dimensiones de la imagen
        if not hasattr(self, 'preview_img_offset') or not hasattr(self, 'preview_img_size'):
            return
        
        # Calcular delta del movimiento
        dx = event.x - self.drag_start_x
        dy = event.y - self.drag_start_y
        
        # Convertir delta del canvas a delta de la imagen original
        img_width, img_height = self.preview_img_size
        orig_width, orig_height = self.preview_original_size
        
        scale_x = orig_width / img_width
        scale_y = orig_height / img_height
        
        # Actualizar offsets del elemento (convertir de píxeles de canvas a píxeles de imagen)
        self.dragging_element.transform.image_offset_x += dx * scale_x
        self.dragging_element.transform.image_offset_y += dy * scale_y
        self.dragging_element.transform.auto_fitted = False
        
        # Actualizar posición inicial para el siguiente movimiento
        self.drag_start_x = event.x
        self.drag_start_y = event.y
        
        # Actualizar UI controls
        self.offset_x_var.set(self.dragging_element.transform.image_offset_x)
        self.offset_y_var.set(self.dragging_element.transform.image_offset_y)
        
        # Refrescar vista previa (sin recalcular packing)
        self.render_mixed_preview()
        # El render limita el desplazamiento al rango válido del marco.
        self.offset_x_var.set(self.dragging_element.transform.image_offset_x)
        self.offset_y_var.set(self.dragging_element.transform.image_offset_y)

    def on_preview_mouse_up(self, event):
        if self.dragging_collage_path is not None:
            self.dragging_collage_path = None
            self.dragging_collage_cell = None
            self.preview_canvas.config(cursor="hand2")
            if self._collage_render_after is not None:
                self.after_cancel(self._collage_render_after)
                self._collage_render_after = None
            self._render_selected_collage_page()
            return
        if self.mode_var.get() == DistributionMode.UNIFORM.value:
            self.dragging_element = None
            self.preview_canvas.config(cursor="hand2")
            return
        if self.mode_var.get() == DistributionMode.CARDS_9X5.value:
            self.card_drag_last = None
            return
        """Maneja la liberación del mouse en la vista previa."""
        if self.dragging_element:
            self.dragging_element = None
            self.preview_canvas.config(cursor="crosshair")

    def on_preview_wheel(self, event):
        """Maneja la rueda del mouse para zoom en la vista previa."""
        if self.mode_var.get() == DistributionMode.UNIFORM.value:
            current = self._selected_uniform_transform()
            if not current:
                return
            factor = 0.9 if event.num == 5 or event.delta < 0 else 1.1
            transform = current[1]
            transform.image_scale = max(0.1, min(5.0, transform.image_scale * factor))
            transform.auto_fitted = False
            self.uniform_scale_var.set(transform.image_scale * 100.0)
            self.render_single_image_in_a4()
            return
        if self.mode_var.get() != DistributionMode.MIXED.value:
            return
        # Obtener elemento seleccionado
        selected = self.tree.selection()
        if not selected:
            return
        
        index = int(selected[0])
        if 0 <= index < len(self.mixed_elements):
            element = self.mixed_elements[index]
            
            # Determinar dirección del zoom
            if event.num == 5 or event.delta < 0:
                # Zoom out
                zoom_factor = 0.9
            else:
                # Zoom in
                zoom_factor = 1.1
            
            # Aplicar zoom a la escala del elemento
            new_scale = element.transform.image_scale * zoom_factor
            
            # Limitar escala entre 0.1 y 5.0
            new_scale = max(0.1, min(5.0, new_scale))
            
            element.transform.image_scale = new_scale
            element.transform.auto_fitted = False
            
            # Actualizar UI control
            self.scale_var.set(new_scale * 100.0)
            
            # Refrescar vista previa
            self.render_mixed_preview()

    def on_policy_change(self):
        """Maneja el cambio de política de tamaño."""
        policy = self.size_policy_var.get()
        if policy == SizePolicy.EXACTO.value:
            self.policy_info.config(text="Las medidas no se modifican. Los elementos que no entren quedarán sin colocar.")
        else:
            self.policy_info.config(text="Puede reducir uniformemente las medidas para que la composición entre.")
        self.refresh_mixed_preview()

    def on_tree_motion(self, event):
        """Muestra tooltip para nombres largos en el treeview."""
        # Identificar la fila y columna bajo el cursor
        item_id = self.tree.identify_row(event.y)
        column_id = self.tree.identify_column(event.x)
        
        if item_id and column_id == "#1":  # Columna de nombre
            try:
                index = int(item_id)
                mode = self.mode_var.get()
                
                if mode == DistributionMode.MIXED.value and 0 <= index < len(self.mixed_elements):
                    full_name = self.mixed_elements[index].display_name
                    # Mostrar tooltip si el nombre es largo
                    if len(full_name) > 30:
                        self.tooltip = tk.Label(self, text=full_name, background="lightyellow", 
                                               relief="solid", borderwidth=1, padx=2, pady=1)
                        self.tooltip.place(x=event.x_root - self.winfo_rootx() + 15, 
                                           y=event.y_root - self.winfo_rooty() + 15)
                        self.tooltip.after(3000, self.tooltip.destroy)
            except (ValueError, IndexError):
                pass
    
    def _sync_scroll(self, *args):
        """Sincroniza el scroll entre los dos treeviews (obsoleto)."""
        pass

    def select_all_cards(self):
        self.card_selected = set(range(10)); self.refresh_cards()

    def apply_design_to_cards(self, indexes):
        selected = self.tree.selection()
        if not selected or not self.paths:
            messagebox.showinfo("Tarjetas", "Seleccioná un diseño cargado en la lista de archivos.", parent=self); return
        design = self.paths[int(selected[0])]
        for index in indexes:
            face = self.card_slots[index].front if self.card_side_var.get() == "front" else self.card_slots[index].back
            face.path = design
            face.transform = ImageTransform()
        self.refresh_cards()

    def apply_design_to_selected_cards(self):
        if not self.card_selected:
            messagebox.showinfo("Tarjetas", "Seleccioná una o más tarjetas en la vista previa.", parent=self); return
        self.apply_design_to_cards(self.card_selected)

    def restore_card_general_design(self):
        if not self.paths:
            return
        self.apply_design_to_cards(range(10))

    def rotate_selected_cards(self):
        for index in self.card_selected:
            face = self.card_slots[index].front if self.card_side_var.get() == "front" else self.card_slots[index].back
            face.transform.image_rotation_deg = (face.transform.image_rotation_deg + 90) % 360
            face.transform.fit_mode = FitMode.MANUAL
        self.refresh_cards()

    def set_selected_cards_fit(self):
        for index in self.card_selected:
            face = self.card_slots[index].front if self.card_side_var.get() == "front" else self.card_slots[index].back
            face.transform.fit_mode = FitMode(self.card_fit_var.get())
        self.refresh_cards()

    def scale_selected_cards(self, factor):
        for index in self.card_selected:
            face = self.card_slots[index].front if self.card_side_var.get() == "front" else self.card_slots[index].back
            face.transform.image_scale = max(.1, min(5., face.transform.image_scale * factor)); face.transform.fit_mode = FitMode.MANUAL
        self.refresh_cards()

    def refresh_cards(self):
        self.tree.delete(*self.tree.get_children())
        for index, path in enumerate(self.paths):
            self.tree.insert("", "end", iid=str(index), values=(path.name,))
        self.print_button.configure(state="normal" if any(slot.front.path for slot in self.card_slots) else "disabled")
        self.pdf_button.configure(state="normal" if any(slot.front.path for slot in self.card_slots) else "disabled")
        self.continuous_button.configure(state="disabled")
        self.summary_var.set("Tarjetas 9×5 · A4 · 10 posiciones · " + ("doble faz" if self.card_double_sided_var.get() else "solo frente"))
        self.render_cards_preview()

    def _refresh_card_profile_choices(self):
        if hasattr(self, "card_profile_combo"):
            self.card_profile_combo["values"] = [profile.name for profile in self.card_profiles]

    def selected_card_profile(self) -> PrinterProfile | None:
        return next((profile for profile in self.card_profiles if profile.name == self.card_profile_var.get()), None)

    def apply_selected_card_profile(self):
        profile = self.selected_card_profile()
        if not profile:
            return
        self.card_flip_var.set(profile.flip_mode)
        self.refresh_cards()

    def _effective_card_offsets(self, side: str) -> tuple[float, float]:
        profile = self.selected_card_profile()
        return profile_offsets_for_side(profile, side, self.card_offset_x_var.get(), self.card_offset_y_var.get())

    def open_cards_calibration(self):
        """Asistente manual: exporta frente/reverso y guarda la corrección medida."""
        dialog = tk.Toplevel(self); dialog.title("Calibrar impresión de tarjetas 9×5"); dialog.transient(self.winfo_toplevel()); dialog.grab_set()
        tk.Label(dialog, text="1. Exportá e imprimí el frente al 100 %.\n2. Reinsertá la hoja según el modo elegido.\n3. Imprimí el reverso y medí el error.\nSi el reverso quedó 1 mm a la derecha, ingresá -1,0 mm para moverlo a la izquierda.", justify="left", padx=14, pady=12).pack()
        name = tk.StringVar(value=self.card_profile_var.get() or "Nueva impresora")
        dx, dy = tk.DoubleVar(value=0.0), tk.DoubleVar(value=0.0)
        for label, variable in (("Nombre", name), ("Corrección X (mm)", dx), ("Corrección Y (mm)", dy)):
            row = tk.Frame(dialog); row.pack(fill="x", padx=14, pady=2); tk.Label(row, text=label, width=18, anchor="w").pack(side="left")
            ttk.Entry(row, textvariable=variable, width=18).pack(side="left")
        flip = tk.StringVar(value=self.card_flip_var.get())
        ttk.Combobox(dialog, textvariable=flip, values=("long_edge", "short_edge", "manual"), state="readonly").pack(padx=14, pady=4)
        def export_sheet():
            target = filedialog.asksaveasfilename(parent=dialog, title="Guardar calibración frente", initialfile="calibracion_tarjetas_frente.png", defaultextension=".png", filetypes=[("PNG", "*.png")])
            if not target: return
            root = Path(target); render_cards_calibration_page("front").save(root, dpi=(300, 300))
            render_cards_calibration_page("back", flip_mode=flip.get()).save(root.with_name(root.stem + "_reverso.png"), dpi=(300, 300))
            messagebox.showinfo("Calibración", "Frente y reverso guardados. Imprimí a 100 %, sin ajustar a página.", parent=dialog)
        def save_profile():
            profile = PrinterProfile(name=name.get().strip() or "Perfil", back_offset_x_mm=round(dx.get(), 1), back_offset_y_mm=round(dy.get(), 1),
                                     flip_mode=flip.get(), calibrated_at=datetime.now(timezone.utc).isoformat())
            self.card_profiles = [item for item in self.card_profiles if item.name != profile.name] + [profile]
            self.card_profile_store.save(self.card_profiles); self.card_profile_var.set(profile.name); self._refresh_card_profile_choices(); self.apply_selected_card_profile(); dialog.destroy()
        ttk.Button(dialog, text="Exportar hojas de calibración", command=export_sheet).pack(fill="x", padx=14, pady=(8, 3))
        ttk.Button(dialog, text="Guardar perfil", command=save_profile).pack(fill="x", padx=14, pady=(0, 14))

    def render_cards_preview(self):
        from PIL import ImageDraw, ImageTk
        side = self.card_side_var.get()
        offset_x, offset_y = self._effective_card_offsets(side)
        page = render_cards_9x5_page(self.card_slots, side, double_sided=self.card_double_sided_var.get(),
                                     bleed_mm=self.card_bleed_var.get(), offset_x_mm=offset_x,
                                     offset_y_mm=offset_y, flip_mode=self.card_flip_var.get())
        preview, xoff, yoff = self._prepare_preview_image(page)
        draw = ImageDraw.Draw(preview)
        sx, sy = preview.width / SHEET_SIZE[0], preview.height / SHEET_SIZE[1]
        for index in range(10):
            target = index if side == "front" else reverse_card_slot_index(index, self.card_flip_var.get())
            x, y, w, h = card_slot_rect_mm(target)
            box = [x * 300 / 25.4 * sx, y * 300 / 25.4 * sy, (x+w) * 300 / 25.4 * sx, (y+h) * 300 / 25.4 * sy]
            if side == "back":
                bleed = self.card_bleed_var.get() * 300 / 25.4
                draw.rectangle([box[0]-bleed*sx, box[1]-bleed*sy, box[2]+bleed*sx, box[3]+bleed*sy], outline="#f59e0b", width=1)
                inset = 3 * 300 / 25.4
                draw.rectangle([box[0]+inset*sx, box[1]+inset*sy, box[2]-inset*sx, box[3]-inset*sy], outline="#22c55e", width=1)
            draw.rectangle(box, outline="#36a8ff" if index in self.card_selected else "#555555", width=2)
        self.preview_photo = ImageTk.PhotoImage(preview)
        self.preview_canvas.delete("all")
        item = self.preview_canvas.create_image(xoff, yoff, anchor="nw", image=self.preview_photo)
        self.preview_canvas.tag_bind(item, "<ButtonPress-1>", self.on_cards_mouse_down)
        self.preview_canvas.tag_bind(item, "<B1-Motion>", self.on_cards_mouse_drag)
        self.preview_canvas.tag_bind(item, "<ButtonRelease-1>", lambda _event: setattr(self, "card_drag_last", None))
        self.preview_img_offset, self.preview_img_size, self.preview_original_size = (xoff, yoff), preview.size, page.size
        self.page_label.configure(text="Frente" if side == "front" else "Reverso")

    def cards_project_state(self) -> dict:
        """Estado serializable del subtipo de composición Tarjetas 9x5."""
        return cards_9x5_project_state(
            self.card_slots, double_sided=self.card_double_sided_var.get(), bleed_mm=self.card_bleed_var.get(),
            offset_x_mm=self.card_offset_x_var.get(), offset_y_mm=self.card_offset_y_var.get(),
            flip_mode=self.card_flip_var.get(), selected=self.card_selected,
        )

    def load_cards_project_state(self, project: dict):
        """Restaura el estado de un .cards_9x5.json en el editor actual."""
        slots, settings = cards_9x5_from_project_state(project)
        self.card_slots = slots
        self.card_double_sided_var.set(settings["double_sided"])
        self.card_bleed_var.set(settings["bleed_mm"])
        self.card_offset_x_var.set(settings["offset_x_mm"])
        self.card_offset_y_var.set(settings["offset_y_mm"])
        self.card_flip_var.set(settings["flip_mode"])
        self.card_selected = settings["selected"]
        self.paths = list(dict.fromkeys(face.path for slot in slots for face in (slot.front, slot.back) if face.path))
        self.refresh_cards()

    def on_cards_mouse_down(self, event):
        xoff, yoff = self.preview_img_offset; pw, ph = self.preview_img_size
        if not (xoff <= event.x <= xoff + pw and yoff <= event.y <= yoff + ph): return
        x_mm = (event.x - xoff) / pw * CARD_SHEET_MM[0]; y_mm = (event.y - yoff) / ph * CARD_SHEET_MM[1]
        for index in range(10):
            target = index if self.card_side_var.get() == "front" else reverse_card_slot_index(index, self.card_flip_var.get())
            x, y, w, h = card_slot_rect_mm(target)
            if x <= x_mm <= x+w and y <= y_mm <= y+h:
                if event.state & 0x4:
                    self.card_selected.symmetric_difference_update({index})
                else:
                    self.card_selected = {index}
                self.card_drag_last = (event.x, event.y)
                self.refresh_cards(); return

    def on_cards_mouse_drag(self, event):
        if not self.card_selected or not self.card_drag_last:
            return
        old_x, old_y = self.card_drag_last
        dx_mm = (event.x - old_x) / self.preview_img_size[0] * CARD_SHEET_MM[0]
        dy_mm = (event.y - old_y) / self.preview_img_size[1] * CARD_SHEET_MM[1]
        # Los offsets del transform se expresan en píxeles fuente; usar el marco
        # a 300 DPI mantiene una respuesta equivalente a la vista previa.
        dx, dy = dx_mm * 300 / 25.4, dy_mm * 300 / 25.4
        for index in self.card_selected:
            face = self.card_slots[index].front if self.card_side_var.get() == "front" else self.card_slots[index].back
            face.transform.image_offset_x += dx; face.transform.image_offset_y += dy; face.transform.fit_mode = FitMode.MANUAL
        self.card_drag_last = (event.x, event.y)
        self.render_cards_preview()

    def on_uniform_layout_change(self):
        """Actualiza la ayuda del formato y evita títulos donde no aplican."""
        supports_title = self.per_sheet_var.get() in PHOTO_STRIP_LAYOUTS
        self.title_entry.configure(state="normal" if supports_title else "disabled")
        self.title_hint_label.configure(
            text=("La franja se agrega únicamente si escribís un título."
                  if supports_title else "El título está disponible para los formatos Díptico y Tríptico.")
        )
        self.refresh()

    def _uniform_thumbnail(self, path: Path):
        """Crea una miniatura pequeña, reutilizable y segura para la lista de fotos."""
        key = str(path)
        cached = self._thumbnail_cache.get(key)
        if cached is not None:
            return cached
        try:
            from PIL import Image, ImageOps, ImageTk
            with Image.open(path) as image:
                thumbnail = ImageOps.exif_transpose(image).convert("RGB")
                thumbnail.thumbnail((36, 36), Image.Resampling.LANCZOS)
                canvas = Image.new("RGB", (36, 36), "#2a2a2d")
                canvas.paste(thumbnail, ((36 - thumbnail.width) // 2, (36 - thumbnail.height) // 2))
            photo = ImageTk.PhotoImage(canvas)
            self._thumbnail_cache[key] = photo
            return photo
        except Exception:
            return None

    def move_uniform_photo(self, direction: int):
        """Reordena la foto seleccionada y conserva su selección."""
        if self.mode_var.get() != DistributionMode.UNIFORM.value:
            return
        selected = self.tree.selection()
        if not selected:
            return
        current = int(selected[0])
        target = current + direction
        if not 0 <= target < len(self.paths):
            return
        self.paths[current], self.paths[target] = self.paths[target], self.paths[current]
        self.refresh_uniform(selected_index=target)

    def on_mode_change(self):
        """Maneja el cambio entre modo uniforme, mixto y collage."""
        mode = self.mode_var.get()
        if mode != DistributionMode.CARDS_9X5.value and hasattr(self, "pdf_button"):
            self.pdf_button.configure(state="disabled")
        if mode == DistributionMode.UNIFORM.value:
            # Ocultar controles mixtos y collage, mostrar uniformes
            self.mixed_controls.pack_forget()
            self.collage_controls.pack_forget()
            self.uniform_controls.pack(fill="both", expand=True, padx=12, pady=10)
            
            # Configurar treeview para modo uniforme
            self.tree["columns"] = ("name",)
            self.tree.heading("name", text="Foto")
            self.tree.column("name", width=250, anchor="w", stretch=True)
            self.tree.bind("<<TreeviewSelect>>", self.on_uniform_selection)
            self.btn_move_up.configure(state="disabled")
            self.btn_move_down.configure(state="disabled")
            
            # Ocultar botón duplicar en modo uniforme
            if hasattr(self, 'btn_duplicate'):
                self.btn_duplicate.pack_forget()
            
            self.on_uniform_layout_change()

        elif mode == DistributionMode.CARDS_9X5.value:
            self.uniform_controls.pack_forget()
            self.mixed_controls.pack_forget()
            self.collage_controls.pack_forget()
            self.cards_controls.pack(fill="both", expand=True, padx=12, pady=10)
            self.tree["columns"] = ("name",)
            self.tree.heading("name", text="Diseño")
            self.tree.column("name", width=250, anchor="w", stretch=True)
            self.tree.bind("<<TreeviewSelect>>", lambda _event: None)
            self.btn_move_up.configure(state="disabled")
            self.btn_move_down.configure(state="disabled")
            if hasattr(self, 'btn_duplicate'):
                self.btn_duplicate.pack_forget()
            self.refresh_cards()
            
        elif mode == DistributionMode.SMART_COLLAGE.value:
            # Ocultar otros controles, mostrar collage
            self.uniform_controls.pack_forget()
            self.mixed_controls.pack_forget()
            self.cards_controls.pack_forget()
            self.collage_controls.pack(fill="both", expand=True, padx=12, pady=10)
            
            # Configurar treeview para modo collage (simple)
            self.tree["columns"] = ("name",)
            self.tree.heading("name", text="Imagen")
            self.tree.column("name", width=250, anchor="w", stretch=True)
            self.tree.bind("<<TreeviewSelect>>", self.on_collage_tree_selection)
            self.btn_move_up.configure(state="disabled")
            self.btn_move_down.configure(state="disabled")
            
            # Ocultar botón duplicar
            if hasattr(self, 'btn_duplicate'):
                self.btn_duplicate.pack_forget()

            # El collage usa `paths`; recuperar las imágenes ya cargadas en
            # composición mixta al cambiar de modo.
            if not self.paths and self.mixed_elements:
                self.paths = list(dict.fromkeys(element.path for element in self.mixed_elements))
            
            self.refresh_collage()
            
        else:  # MIXED
            # Ocultar controles uniformes y collage, mostrar mixtos
            self.uniform_controls.pack_forget()
            self.collage_controls.pack_forget()
            self.cards_controls.pack_forget()
            self.mixed_controls.pack(fill="both", expand=True, padx=12, pady=10)
            
            # Configurar treeview para modo mixto
            self.tree["columns"] = ("name", "size", "qty")
            self.tree.heading("name", text="Archivo")
            self.tree.column("name", width=150, anchor="w", stretch=True)
            self.tree.heading("size", text="Tamaño")
            self.tree.column("size", width=70, anchor="center", stretch=False)
            self.tree.heading("qty", text="Cant.")
            self.tree.column("qty", width=45, anchor="center", stretch=False)
            self.tree.bind("<<TreeviewSelect>>", self.on_mixed_selection)
            self.btn_move_up.configure(state="disabled")
            self.btn_move_down.configure(state="disabled")
            
            # Mostrar botón duplicar en modo mixto
            if hasattr(self, 'btn_duplicate'):
                self.btn_duplicate.pack(side="left", fill="x", expand=True)
            
            # Convertir archivos de uniform a mixto si es la primera vez
            if not self.mixed_elements and self.paths:
                for path in self.paths:
                    element = MixedElement(
                        path=path,
                        width_mm=105.0,
                        height_mm=148.0,
                        quantity=1,
                        orientation=Orientation.AUTOMATIC,
                        allow_rotation=True,
                        preset=PaperSize.A6,
                    )
                    self.mixed_elements.append(element)
            
            # Limpiar editor al cambiar a modo mixto (sin selección inicial)
            self._clear_element_editor()
            self._enable_element_editor(False)
            self.no_selection_label.pack(anchor="w", pady=(2, 2))
            
            self.refresh_mixed()

    def on_mixed_selection(self, event):
        """Maneja la selección en el treeview mixto."""
        selected = self.tree.selection()
        if selected:
            index = int(selected[0])
            if 0 <= index < len(self.mixed_elements):
                element = self.mixed_elements[index]
                self._populate_element_editor(element)
                self._enable_element_editor(True)
                self.no_selection_label.pack_forget()
                
                # Actualizar texto del botón aplicar
                if len(selected) > 1:
                    self.btn_apply.config(text=f"Aplicar a seleccionados ({len(selected)})")
                else:
                    self.btn_apply.config(text="Aplicar cambios")
                
                # Habilitar botones
                self.btn_duplicate.config(state="normal")
                self.btn_apply.config(state="normal")
                self.btn_remove.config(state="normal")
                
                # Actualizar vista previa cuando cambia la selección
                self.refresh_mixed_preview()
        else:
            # Limpiar editor cuando no hay selección
            self._clear_element_editor()
            self._enable_element_editor(False)
            self.no_selection_label.pack(anchor="w", pady=(2, 2))
            
            # Deshabilitar botones
            self.btn_duplicate.config(state="disabled")
            self.btn_apply.config(text="Aplicar cambios", state="disabled")
            self.btn_remove.config(state="disabled")

    def _clear_element_editor(self):
        """Limpia el editor cuando no hay selección."""
        self.width_var.set("")
        self.height_var.set("")
        self.quantity_var.set(1)
        self.allow_rotation_var.set(True)
        self.orientation_var.set(Orientation.AUTOMATIC.value)
        self.preset_var.set("Personalizado")
        
        # Limpiar controles de transformación
        self.fit_mode_var.set(FitMode.COVER.value)
        self.offset_x_var.set(0.0)
        self.offset_y_var.set(0.0)
        self.scale_var.set(100.0)
        self.rotation_var.set(0.0)
    
    def _enable_element_editor(self, enable: bool):
        """Habilita o deshabilita los controles del editor."""
        state = "normal" if enable else "disabled"
        self.width_entry.config(state=state)
        self.height_entry.config(state=state)
        self.quantity_spinbox.config(state=state)
        self.rotation_checkbutton.config(state=state)
    
    def _populate_element_editor(self, element: MixedElement):
        """Popula el editor con los datos del elemento seleccionado."""
        self.width_var.set(f"{element.width_mm:.1f}")
        self.height_var.set(f"{element.height_mm:.1f}")
        self.quantity_var.set(element.quantity)
        self.allow_rotation_var.set(element.allow_rotation)
        self.orientation_var.set(element.orientation.value)
        
        # Populate transformation controls
        self.fit_mode_var.set(element.transform.fit_mode.value)
        self.offset_x_var.set(element.transform.image_offset_x)
        self.offset_y_var.set(element.transform.image_offset_y)
        self.scale_var.set(element.transform.image_scale * 100.0)
        self.rotation_var.set(element.transform.image_rotation_deg)
        
        # Determinar preset basado en las dimensiones exactas del elemento
        preset_sizes = {
            "A5": (148.0, 210.0),
            "A6": (105.0, 148.0),
            "A7": (74.0, 105.0),
            "10×15 cm": (100.0, 150.0),
            "13×18 cm": (130.0, 180.0),
        }
        
        preset_found = None
        for preset_name, (w, h) in preset_sizes.items():
            if abs(element.width_mm - w) < 0.1 and abs(element.height_mm - h) < 0.1:
                preset_found = preset_name
                break
            # También verificar versión rotada
            if abs(element.width_mm - h) < 0.1 and abs(element.height_mm - w) < 0.1:
                preset_found = preset_name
                break
        
        if preset_found:
            self.preset_var.set(preset_found)
        elif element.preset:
            self.preset_var.set(element.preset.value)
        else:
            self.preset_var.set("Personalizado")

    def on_unit_change(self):
        """Maneja el cambio de unidades."""
        selected = self.tree.selection()
        if selected:
            index = int(selected[0])
            if 0 <= index < len(self.mixed_elements):
                element = self.mixed_elements[index]
                self._populate_element_editor(element)

    def on_preset_change(self, event):
        """Maneja la selección de preset."""
        preset = self.preset_var.get()
        
        preset_sizes = {
            "A5": (148.0, 210.0),
            "A6": (105.0, 148.0),
            "A7": (74.0, 105.0),
            "10×15 cm": (100.0, 150.0),
            "13×18 cm": (130.0, 180.0),
        }
        
        if preset in preset_sizes:
            width_mm, height_mm = preset_sizes[preset]
            self.width_var.set(f"{width_mm:.1f}")
            self.height_var.set(f"{height_mm:.1f}")
            
            selected = self.tree.selection()
            if selected:
                index = int(selected[0])
                if 0 <= index < len(self.mixed_elements):
                    element = self.mixed_elements[index]
                    element.width_mm = width_mm
                    element.height_mm = height_mm
                    element.preset = None  # Volver a Personalizado
                    self.preset_var.set("Personalizado")
                    self.refresh_mixed_tree()
                    self.refresh_mixed_preview()

    def on_dimension_change(self):
        """Maneja el cambio de dimensiones con debounce."""
        selected = self.tree.selection()
        if selected:
            index = int(selected[0])
            if 0 <= index < len(self.mixed_elements):
                try:
                    width_str = self.width_var.get().replace(",", ".")
                    height_str = self.height_var.get().replace(",", ".")
                    
                    width_mm = float(width_str)
                    height_mm = float(height_str)
                    
                    if width_mm > 0 and height_mm > 0:
                        element = self.mixed_elements[index]
                        element.width_mm = width_mm
                        element.height_mm = height_mm
                        element.preset = None  # Volver a Personalizado
                        self.preset_var.set("Personalizado")
                        self.refresh_mixed_tree()
                        self.refresh_mixed_preview()
                except ValueError:
                    pass  # Ignorar entradas inválidas mientras se escribe

    def on_transform_change(self):
        """Maneja el cambio de transformación de imagen."""
        selected = self.tree.selection()
        if selected:
            index = int(selected[0])
            if 0 <= index < len(self.mixed_elements):
                try:
                    element = self.mixed_elements[index]
                    
                    # Actualizar transformación
                    element.transform.fit_mode = FitMode(self.fit_mode_var.get())
                    element.transform.image_offset_x = self.offset_x_var.get()
                    element.transform.image_offset_y = self.offset_y_var.get()
                    element.transform.image_scale = self.scale_var.get() / 100.0
                    element.transform.image_rotation_deg = self.rotation_var.get()
                    element.transform.auto_fitted = False  # Ya no es autoajustado
                    
                    # Refrescar vista previa sin recalcular packing
                    self.render_mixed_preview()
                except ValueError:
                    pass

    def center_image(self):
        """Centra la imagen en su marco."""
        selected = self.tree.selection()
        if selected:
            index = int(selected[0])
            if 0 <= index < len(self.mixed_elements):
                element = self.mixed_elements[index]
                element.transform.image_offset_x = 0.0
                element.transform.image_offset_y = 0.0
                element.transform.auto_fitted = False
                
                # Actualizar UI
                self.offset_x_var.set(0.0)
                self.offset_y_var.set(0.0)
                self.render_mixed_preview()

    def auto_fit_image(self):
        """Aplica ajuste automático según el modo actual."""
        selected = self.tree.selection()
        if selected:
            index = int(selected[0])
            if 0 <= index < len(self.mixed_elements):
                element = self.mixed_elements[index]
                element.transform.image_offset_x = 0.0
                element.transform.image_offset_y = 0.0
                element.transform.image_scale = 1.0
                element.transform.auto_fitted = True
                
                # Actualizar UI
                self.offset_x_var.set(0.0)
                self.offset_y_var.set(0.0)
                self.scale_var.set(100.0)
                self.render_mixed_preview()

    def reset_transform(self):
        """Restablece la transformación a valores por defecto."""
        selected = self.tree.selection()
        if selected:
            index = int(selected[0])
            if 0 <= index < len(self.mixed_elements):
                element = self.mixed_elements[index]
                element.transform = ImageTransform()  # Reset to defaults
                
                # Actualizar UI
                self.fit_mode_var.set(FitMode.COVER.value)
                self.offset_x_var.set(0.0)
                self.offset_y_var.set(0.0)
                self.scale_var.set(100.0)
                self.render_mixed_preview()

    def duplicate_element(self):
        """Duplica el elemento seleccionado."""
        selected = self.tree.selection()
        if selected:
            index = int(selected[0])
            if 0 <= index < len(self.mixed_elements):
                original = self.mixed_elements[index]
                from dataclasses import replace
                new_element = MixedElement(
                    path=original.path,
                    width_mm=original.width_mm,
                    height_mm=original.height_mm,
                    quantity=original.quantity,
                    orientation=original.orientation,
                    allow_rotation=original.allow_rotation,
                    preset=original.preset,
                    transform=replace(original.transform),  # Copy transform
                )
                self.mixed_elements.insert(index + 1, new_element)
                self.refresh_mixed_tree()
                self.refresh_mixed_preview()

    def apply_to_selected(self):
        """Aplica las configuraciones actuales a los elementos seleccionados."""
        try:
            width_str = self.width_var.get().replace(",", ".")
            height_str = self.height_var.get().replace(",", ".")
            
            width_mm = float(width_str)
            height_mm = float(height_str)
            
            quantity = self.quantity_var.get()
            allow_rotation = self.allow_rotation_var.get()
            orientation = Orientation(self.orientation_var.get())
            
            selected = self.tree.selection()
            for item_id in selected:
                index = int(item_id)
                if 0 <= index < len(self.mixed_elements):
                    element = self.mixed_elements[index]
                    element.width_mm = width_mm
                    element.height_mm = height_mm
                    element.quantity = quantity
                    element.allow_rotation = allow_rotation
                    element.orientation = orientation
            
            self.refresh_mixed_tree()
            self.refresh_mixed_preview()
        except ValueError:
            messagebox.showwarning("Error", "Las dimensiones deben ser valores numéricos válidos.", parent=self)

    def set_no_margins(self):
        """Establece márgenes y separación en cero."""
        self.margin_top_var.set(0.0)
        self.margin_bottom_var.set(0.0)
        self.margin_left_var.set(0.0)
        self.margin_right_var.set(0.0)
        self.gap_horizontal_var.set(0.0)
        self.gap_vertical_var.set(0.0)
        self.refresh_mixed_preview()

    def optimize_distribution(self):
        """Ejecuta el packing completo nuevamente."""
        self.refresh_mixed_preview()

    def first_page(self):
        if self.mode_var.get() == DistributionMode.SMART_COLLAGE.value:
            if self.collage_pages and self.current_page_index > 0:
                self.current_page_index = 0
                self.render_collage_preview()
            return
        """Navega a la primera página."""
        if self.packing_result and self.current_page_index > 0:
            self.current_page_index = 0
            self.render_mixed_preview()
            self.update_mixed_info()

    def prev_page(self):
        if self.mode_var.get() == DistributionMode.SMART_COLLAGE.value:
            if self.collage_pages and self.current_page_index > 0:
                self.current_page_index -= 1
                self.render_collage_preview()
            return
        """Navega a la página anterior."""
        if self.packing_result and self.current_page_index > 0:
            self.current_page_index -= 1
            self.render_mixed_preview()
            self.update_mixed_info()

    def next_page(self):
        if self.mode_var.get() == DistributionMode.SMART_COLLAGE.value:
            if self.collage_pages and self.current_page_index < len(self.collage_pages) - 1:
                self.current_page_index += 1
                self.render_collage_preview()
            return
        """Navega a la página siguiente."""
        if self.packing_result and self.current_page_index < len(self.packing_result.pages) - 1:
            self.current_page_index += 1
            self.render_mixed_preview()
            self.update_mixed_info()

    def last_page(self):
        if self.mode_var.get() == DistributionMode.SMART_COLLAGE.value:
            if self.collage_pages and self.current_page_index < len(self.collage_pages) - 1:
                self.current_page_index = len(self.collage_pages) - 1
                self.render_collage_preview()
            return
        """Navega a la última página."""
        if self.packing_result and self.current_page_index < len(self.packing_result.pages) - 1:
            self.current_page_index = len(self.packing_result.pages) - 1
            self.render_mixed_preview()
            self.update_mixed_info()

    def zoom_in(self):
        """Aumenta el zoom de la vista previa."""
        if self.mode_var.get() == DistributionMode.SMART_COLLAGE.value:
            self.adjust_collage_zoom(1.1)

    def zoom_out(self):
        """Disminuye el zoom de la vista previa."""
        if self.mode_var.get() == DistributionMode.SMART_COLLAGE.value:
            self.adjust_collage_zoom(0.9)

    def fit_to_window(self):
        """Ajusta la vista previa al tamaño de la ventana y centra la hoja A4."""
        self.view_zoom = 1.0
        self.zoom_label.configure(text="100%")
        self._render_current_preview()

    def _change_view_zoom(self, factor: float):
        """Cambia el zoom de la vista previa de la hoja sin afectar la escala de la imagen."""
        self.view_zoom = max(0.2, min(3.0, self.view_zoom * factor))
        self.zoom_label.configure(text=f"{int(self.view_zoom * 100)}%")
        self._render_current_preview()

    def _render_current_preview(self):
        """Re-renderiza la vista previa actual según el modo activo y el zoom de hoja."""
        if self.mode_var.get() == DistributionMode.SMART_COLLAGE.value:
            self.render_collage_preview()
        elif self.mode_var.get() == DistributionMode.MIXED.value:
            self.render_mixed_preview()
        else:
            self.render_single_image_in_a4()

    def contain_selected_image(self):
        """Aplica el modo Ajustar a la imagen seleccionada."""
        if self.mode_var.get() == DistributionMode.UNIFORM.value:
            self._set_uniform_fit(FitMode.CONTAIN)
            return
        self._apply_selected_transform(lambda transform: setattr(transform, 'fit_mode', FitMode.CONTAIN))

    def cover_selected_image(self):
        """Aplica el modo Rellenar a la imagen seleccionada."""
        if self.mode_var.get() == DistributionMode.UNIFORM.value:
            self._set_uniform_fit(FitMode.COVER)
            return
        self._apply_selected_transform(lambda transform: setattr(transform, 'fit_mode', FitMode.COVER))

    def center_selected_image(self):
        """Centra la imagen seleccionada dentro de su marco."""
        if self.mode_var.get() == DistributionMode.UNIFORM.value:
            self.center_uniform_image()
            return
        self._apply_selected_transform(lambda transform: (setattr(transform, 'image_offset_x', 0.0), setattr(transform, 'image_offset_y', 0.0)))

    def scale_selected_image(self, delta_percent: float):
        """Escala la imagen seleccionada en porcentaje."""
        if self.mode_var.get() == DistributionMode.UNIFORM.value:
            current = self._selected_uniform_transform()
            if not current:
                return
            transform = current[1]
            transform.image_scale = max(0.1, min(5.0, transform.image_scale * (1 + delta_percent / 100.0)))
            transform.auto_fitted = False
            self.uniform_scale_var.set(transform.image_scale * 100.0)
            self.render_single_image_in_a4()
            return
        def update(transform: ImageTransform):
            transform.image_scale = max(0.1, min(5.0, transform.image_scale * (1 + delta_percent / 100.0)))
        self._apply_selected_transform(update)

    def rotate_selected_image(self, degrees: int):
        """Rota la imagen seleccionada en el lugar."""
        if self.mode_var.get() == DistributionMode.UNIFORM.value:
            current = self._selected_uniform_transform()
            if not current:
                return
            transform = current[1]
            transform.image_rotation_deg = (transform.image_rotation_deg + degrees) % 360
            transform.auto_fitted = False
            self.uniform_rotation_var.set(transform.image_rotation_deg)
            self.render_single_image_in_a4()
            return
        def update(transform: ImageTransform):
            transform.image_rotation_deg = (transform.image_rotation_deg + degrees) % 360
        self._apply_selected_transform(update)

    def reset_selected_image(self):
        """Restablece la transformación completa de la imagen seleccionada."""
        if self.mode_var.get() == DistributionMode.UNIFORM.value:
            self.reset_uniform_image()
            return
        selected = self.tree.selection()
        if not selected:
            return
        index = int(selected[0])
        if 0 <= index < len(self.mixed_elements):
            self.mixed_elements[index].transform = ImageTransform()
            self._populate_element_editor(self.mixed_elements[index])
            self._render_current_preview()

    def on_arrow_key(self, event):
        """Mueve la imagen seleccionada con las flechas."""
        if self.mode_var.get() == DistributionMode.CARDS_9X5.value:
            step = 5 if event.state & 0x1 else 1
            dx = -step if event.keysym == 'Left' else step if event.keysym == 'Right' else 0
            dy = -step if event.keysym == 'Up' else step if event.keysym == 'Down' else 0
            for index in self.card_selected:
                face = self.card_slots[index].front if self.card_side_var.get() == "front" else self.card_slots[index].back
                face.transform.image_offset_x += dx; face.transform.image_offset_y += dy; face.transform.fit_mode = FitMode.MANUAL
            self.refresh_cards(); return
        if self.mode_var.get() != DistributionMode.MIXED.value:
            return
        selected = self.tree.selection()
        if not selected:
            return
        index = int(selected[0])
        if not 0 <= index < len(self.mixed_elements):
            return
        step = 5 if event.state & 0x1 else 1
        dx, dy = 0.0, 0.0
        if event.keysym == 'Left':
            dx = -step
        elif event.keysym == 'Right':
            dx = step
        elif event.keysym == 'Up':
            dy = -step
        elif event.keysym == 'Down':
            dy = step
        element = self.mixed_elements[index]
        element.transform.image_offset_x += dx
        element.transform.image_offset_y += dy
        element.transform.auto_fitted = False
        self.offset_x_var.set(element.transform.image_offset_x)
        self.offset_y_var.set(element.transform.image_offset_y)
        self._render_current_preview()

    def on_scale_key(self, event):
        """Escala la imagen con + y - desde el teclado."""
        if self.mode_var.get() == DistributionMode.CARDS_9X5.value:
            factor = 1.02 if event.keysym in ('plus', 'KP_Add') else 0.98
            for index in self.card_selected:
                face = self.card_slots[index].front if self.card_side_var.get() == "front" else self.card_slots[index].back
                face.transform.image_scale = max(.1, min(5., face.transform.image_scale * factor)); face.transform.fit_mode = FitMode.MANUAL
            self.refresh_cards(); return
        if self.mode_var.get() != DistributionMode.MIXED.value:
            return
        select = self.tree.selection()
        if not select:
            return
        index = int(select[0])
        if not 0 <= index < len(self.mixed_elements):
            return
        delta = 0.02 if not (event.state & 0x1) else 0.10
        self.scale_selected_image(delta * 100.0)

    def on_delete_key(self, event):
        """Deselecciona la imagen si se pulsa Suprimir fuera del entorno de collage."""
        if self.mode_var.get() == DistributionMode.MIXED.value:
            self.dragging_element = None
            self.preview_canvas.config(cursor='hand2')

    def _apply_selected_transform(self, updater):
        """Aplica una función de actualización sobre la imagen seleccionada y refresca la vista."""
        selected = self.tree.selection()
        if not selected:
            return
        index = int(selected[0])
        if 0 <= index < len(self.mixed_elements):
            element = self.mixed_elements[index]
            updater(element.transform)
            element.transform.auto_fitted = False
            self._populate_element_editor(element)
            self._render_current_preview()

    def _register_drop(self):
        try:
            from tkinterdnd2 import DND_FILES
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self.drop_files)
        except Exception:
            pass

    def drop_files(self, event):
        self.add_paths([Path(value) for value in self.tk.splitlist(event.data)])

    def choose_files(self):
        paths = filedialog.askopenfilenames(parent=self, title="Elegir pósters",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff")])
        self.add_paths([Path(item) for item in paths])

    def paste(self):
        """Admite imagen copiada o rutas de archivos copiadas desde el Explorador."""
        from PIL import ImageGrab
        try:
            content = ImageGrab.grabclipboard()
            if hasattr(content, "save"):
                with tempfile.NamedTemporaryFile(prefix="doccione_poster_", suffix=".png", delete=False) as file:
                    target = Path(file.name)
                content.convert("RGBA").save(target)
                self.add_paths([target])
                return
            if isinstance(content, list):
                self.add_paths([Path(item) for item in content])
                return
        except Exception:
            pass
        messagebox.showinfo("Pegar", "El portapapeles no contiene una imagen ni archivos compatibles.", parent=self)

    def add_paths(self, paths: list[Path]):
        mode = self.mode_var.get()
        added = 0
        invalid_files = []
        
        for path in paths:
            try:
                if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                    from PIL import Image
                    with Image.open(path) as image:
                        image.verify()
                    
                    if mode in (DistributionMode.UNIFORM.value, DistributionMode.SMART_COLLAGE.value, DistributionMode.CARDS_9X5.value):
                        if path not in self.paths:
                            self.paths.append(path)
                            added += 1
                    else:  # MIXED mode
                        # Crear MixedElement con dimensiones por defecto (A6)
                        element = MixedElement(
                            path=path,
                            width_mm=105.0,
                            height_mm=148.0,
                            quantity=1,
                            orientation=Orientation.AUTOMATIC,
                            allow_rotation=True,
                            preset=PaperSize.A6,
                        )
                        self.mixed_elements.append(element)
                        added += 1
                else:
                    invalid_files.append(path.name)
            except Exception as e:
                invalid_files.append(f"{path.name} ({str(e)[:50]})")
                continue
        
        if not added and paths:
            if invalid_files:
                messagebox.showwarning("Pósters", 
                    f"No se encontraron imágenes compatibles.\nArchivos inválidos: {', '.join(invalid_files[:5])}", 
                    parent=self)
            else:
                messagebox.showwarning("Pósters", "No se encontraron imágenes compatibles para agregar.", parent=self)
        elif invalid_files:
            messagebox.showinfo("Pósters", 
                f"Se agregaron {added} imágenes.\nArchivos inválidos omitidos: {', '.join(invalid_files[:5])}", 
                parent=self)
        self.refresh()
        
        # Limpiar editor si no hay selección después de agregar
        if mode == DistributionMode.MIXED.value:
            selected = self.tree.selection()
            if not selected:
                self._clear_element_editor()
                self._enable_element_editor(False)
                self.no_selection_label.pack(anchor="w", pady=(2, 2))

    def remove_selected(self):
        mode = self.mode_var.get()
        if mode in (DistributionMode.UNIFORM.value, DistributionMode.SMART_COLLAGE.value, DistributionMode.CARDS_9X5.value):
            selected = self.tree.selection()
            if selected:
                self.paths.pop(int(selected[0]))
        else:
            selected = self.tree.selection()
            if selected:
                # Eliminar en orden inverso para no afectar índices
                for item_id in sorted(selected, key=int, reverse=True):
                    index = int(item_id)
                    if 0 <= index < len(self.mixed_elements):
                        self.mixed_elements.pop(index)
        self.refresh()

    def clear(self):
        mode = self.mode_var.get()
        if mode in (DistributionMode.UNIFORM.value, DistributionMode.SMART_COLLAGE.value, DistributionMode.CARDS_9X5.value):
            self.paths.clear()
        else:
            self.mixed_elements.clear()
        self.refresh()

    def refresh(self):
        mode = self.mode_var.get()
        
        if mode == DistributionMode.UNIFORM.value:
            self.refresh_uniform()
        elif mode == DistributionMode.SMART_COLLAGE.value:
            self.refresh_collage()
        elif mode == DistributionMode.CARDS_9X5.value:
            self.refresh_cards()
        else:
            self.refresh_mixed()

    def refresh_uniform(self, selected_index: int | None = None):
        """Actualiza la vista en modo uniforme."""
        # Recordar la selección actual antes de limpiar
        current_selection = self.tree.selection()
        current_index = selected_index if selected_index is not None else (int(current_selection[0]) if current_selection else None)
        
        self.tree.delete(*self.tree.get_children())
        for index, path in enumerate(self.paths):
            self.tree.insert("", "end", iid=str(index), text="", image=self._uniform_thumbnail(path), values=(path.name,))
        
        count = self.per_sheet_var.get()
        pages = math.ceil(len(self.paths) / count) if self.paths else 0
        self.summary_var.set(
            f"{len(self.paths)} foto(s) · {count} por hoja · {pages} hoja(s) A4 lista(s)"
            if self.paths else "Agregá fotos para empezar a armar tu hoja A4"
        )
        export_state = "normal" if self.paths else "disabled"
        self.print_button.configure(state=export_state)
        self.quick_save_png_button.configure(state=export_state)
        self.continuous_button.configure(state="normal" if self.paths and self.database else "disabled")
        
        # Restaurar o seleccionar la primera imagen
        if self.paths:
            if current_index is not None and current_index < len(self.paths):
                # Restaurar la selección anterior
                self.tree.selection_set(str(current_index))
            else:
                # Seleccionar la primera imagen automáticamente
                self.tree.selection_set("0")
            
            # Forzar actualización de la vista previa y controles
            self.on_uniform_selection()
        else:
            # No hay imágenes, mostrar vista vacía
            self.render_uniform_preview()
        
        # Actualizar estado de botones
        selected = self.tree.selection()
        self.btn_remove.config(state="normal" if selected else "disabled")
        self.btn_clear.config(state="normal" if self.paths else "disabled")
        selected_index = int(selected[0]) if selected else -1
        self.btn_move_up.configure(state="normal" if selected_index > 0 else "disabled")
        self.btn_move_down.configure(state="normal" if 0 <= selected_index < len(self.paths) - 1 else "disabled")

    def _refresh_uniform_preview(self):
        """Actualiza solo la hoja visible, sin reconstruir la lista de archivos."""
        if self.mode_var.get() != DistributionMode.UNIFORM.value:
            return
        if self._selected_uniform_transform():
            self.render_single_image_in_a4()
        else:
            self.render_uniform_preview()

    def _selected_uniform_transform(self) -> tuple[Path, ImageTransform] | None:
        selected = self.tree.selection()
        if not selected:
            return None
        index = int(selected[0])
        if not 0 <= index < len(self.paths):
            return None
        path = self.paths[index]
        return path, self.uniform_transforms.setdefault(str(path), ImageTransform())

    def on_uniform_selection(self, _event=None):
        current = self._selected_uniform_transform()
        if not current:
            self.uniform_selection_label.configure(text="Seleccioná una imagen para editarla.")
            self.btn_move_up.configure(state="disabled")
            self.btn_move_down.configure(state="disabled")
            return
        path, transform = current
        selected_index = int(self.tree.selection()[0])
        self.btn_move_up.configure(state="normal" if selected_index > 0 else "disabled")
        self.btn_move_down.configure(state="normal" if selected_index < len(self.paths) - 1 else "disabled")
        self.uniform_selection_label.configure(text=path.name)
        self.uniform_fit_var.set(transform.fit_mode.value)
        self.uniform_x_var.set(transform.image_offset_x)
        self.uniform_y_var.set(transform.image_offset_y)
        self.uniform_scale_var.set(transform.image_scale * 100.0)
        self.uniform_rotation_var.set(transform.image_rotation_deg)
        # Actualizar vista previa mostrando solo la imagen seleccionada en una hoja A4
        self.render_single_image_in_a4()

    def on_uniform_transform_change(self):
        current = self._selected_uniform_transform()
        if not current:
            return
        _path, transform = current
        try:
            transform.fit_mode = FitMode(self.uniform_fit_var.get())
            transform.image_offset_x = self.uniform_x_var.get()
            transform.image_offset_y = self.uniform_y_var.get()
            transform.image_scale = self.uniform_scale_var.get() / 100.0
            transform.image_rotation_deg = self.uniform_rotation_var.get()
            transform.auto_fitted = False
        except tk.TclError:
            return
        # Actualizar vista previa mostrando la imagen seleccionada en A4
        self.render_single_image_in_a4()

    def _set_uniform_fit(self, fit_mode: FitMode):
        """Acción de la barra superior para la imagen seleccionada."""
        if self.mode_var.get() != DistributionMode.UNIFORM.value:
            return
        if not self._selected_uniform_transform():
            messagebox.showinfo("Impresiones fotográficas", "Seleccioná una imagen primero.", parent=self)
            return
        self.uniform_fit_var.set(fit_mode.value)
        self.on_uniform_transform_change()

    def center_uniform_image(self):
        current = self._selected_uniform_transform()
        if not current:
            return
        _path, transform = current
        transform.image_offset_x = transform.image_offset_y = 0.0
        self.uniform_x_var.set(0.0)
        self.uniform_y_var.set(0.0)
        self.render_single_image_in_a4()

    def reset_uniform_image(self):
        current = self._selected_uniform_transform()
        if not current:
            return
        path, _transform = current
        self.uniform_transforms[str(path)] = ImageTransform()
        self.on_uniform_selection()
        self.render_single_image_in_a4()

    def refresh_mixed(self):
        """Actualiza la vista en modo mixto."""
        self.refresh_mixed_tree()
        self.refresh_mixed_preview()
        self.update_mixed_info()
        
        # Actualizar estado de botones
        selected = self.tree.selection()
        self.btn_remove.config(state="normal" if selected else "disabled")
        self.btn_clear.config(state="normal" if self.mixed_elements else "disabled")
        
        # Actualizar botones de edición basado en selección
        if selected:
            index = int(selected[0])
            if 0 <= index < len(self.mixed_elements):
                element = self.mixed_elements[index]
                self._populate_element_editor(element)
                self._enable_element_editor(True)
                self.no_selection_label.pack_forget()
            
            self.btn_duplicate.config(state="normal")
        else:
            # Limpiar editor cuando no hay selección
            self._clear_element_editor()
            self._enable_element_editor(False)
            self.no_selection_label.pack(anchor="w", pady=(2, 2))
            
            self.btn_duplicate.config(state="disabled")

    def refresh_mixed_tree(self):
        """Actualiza el treeview del modo mixto."""
        self.tree.delete(*self.tree.get_children())
        for index, element in enumerate(self.mixed_elements):
            # Mostrar siempre las dimensiones en mm
            if element.width_mm >= 100:
                size_str = f"{element.width_mm:.0f}×{element.height_mm:.0f}"
            else:
                size_str = f"{element.width_mm/10:.1f}×{element.height_mm/10:.1f}"
            self.tree.insert("", "end", iid=str(index), 
                                  values=(element.display_name, size_str, element.quantity))

    def refresh_mixed_preview(self):
        """Ejecuta el packing y actualiza la vista previa mixta."""
        if not self.mixed_elements:
            self.packing_result = None
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(
                self.preview_canvas.winfo_width() // 2,
                self.preview_canvas.winfo_height() // 2,
                text="Agregá imágenes para generar la vista previa.",
                fill=COLORS.muted
            )
            self.page_label.configure(text="Hoja 0 de 0")
            self.indicators_label.config(text="Hojas: 0 | Colocados: 0 | Sin colocar: 0 | Ocupación: 0%")
            self.summary_var.set("0 elementos · 0 hojas A4")
            self.print_button.configure(state="disabled")
            return
        
        try:
            # Validar márgenes y separaciones
            margins = MarginConfig(
                top=max(0, self.margin_top_var.get()),
                bottom=max(0, self.margin_bottom_var.get()),
                left=max(0, self.margin_left_var.get()),
                right=max(0, self.margin_right_var.get()),
                horizontal_gap=max(0, self.gap_horizontal_var.get()),
                vertical_gap=max(0, self.gap_vertical_var.get()),
            )
            
            # Convertir MixedElement a MixedPosterItem
            items = []
            for element in self.mixed_elements:
                item = MixedPosterItem(
                    id=element.id,
                    source_path=str(element.path),
                    width_mm=element.width_mm,
                    height_mm=element.height_mm,
                    quantity=element.quantity,
                    orientation=element.orientation,
                    allow_rotation=element.allow_rotation,
                    paper_size=element.preset,
                )
                items.append(item)
            
            # Determinar política de tamaño
            size_policy = SizePolicy(self.size_policy_var.get())
            
            # Ejecutar packing
            self.packing_result = pack_mixed_posters(items, margins=margins, size_policy=size_policy)
            
            # Actualizar información
            self.current_page_index = 0
            self.update_mixed_info()
            self.render_mixed_preview()
            
            # Habilitar botón de impresión si hay elementos colocados
            self.print_button.configure(state="normal" if self.packing_result.total_placements > 0 else "disabled")
            
        except Exception as error:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(
                self.preview_canvas.winfo_width() // 2,
                self.preview_canvas.winfo_height() // 2,
                text=f"No se pudo calcular la distribución.\n{error}",
                fill="red"
            )

    def update_mixed_info(self):
        """Actualiza la información de aprovechamiento."""
        if not self.packing_result:
            self.indicators_label.config(text="Hojas: 0 | Colocados: 0 | Sin colocar: 0 | Ocupación: 0%")
            self.sheet_info_label.config(text="")
            return
        
        total_pages = self.packing_result.total_pages
        total_placements = self.packing_result.total_placements
        unplaced = len(self.packing_result.unplaced_items)
        total_util = self.packing_result.total_utilization_percent
        scale = self.packing_result.scale_factor * 100
        
        # Actualizar indicadores compactos en panel central (resumen completo)
        self.indicators_label.config(text=f"Hojas: {total_pages} | Colocados: {total_placements} | Sin colocar: {unplaced} | Ocupación: {total_util:.1f}% | Escala: {scale:.0f}%")
        
        # Actualizar información de hoja actual en vista previa (solo info de hoja)
        if self.packing_result.pages:
            current_page = self.packing_result.pages[self.current_page_index]
            page_util = current_page.utilization_percent
            self.sheet_info_label.config(text=f"Hoja {self.current_page_index + 1} de {total_pages} · Ocupación: {page_util:.1f}%")
            self.page_label.configure(text=f"Hoja {self.current_page_index + 1} de {total_pages}")
        else:
            self.sheet_info_label.config(text="")
            self.page_label.configure(text="Hoja 0 de 0")
        
        self.summary_var.set(f"{total_placements} elementos · {total_pages} hojas A4")

    def render_mixed_preview(self):
        """Renderiza la vista previa de la página actual con transformaciones visuales."""
        if not self.packing_result or not self.packing_result.pages:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(
                self.preview_canvas.winfo_width() // 2,
                self.preview_canvas.winfo_height() // 2,
                text="No hay páginas para mostrar.",
                fill=COLORS.muted
            )
            return
        
        try:
            from PIL import Image, ImageOps, ImageTk
            
            page = self.packing_result.pages[self.current_page_index]
            
            # Crear imagen A4 a 72 DPI para vista previa
            dpi_preview = 72
            mm_to_px = dpi_preview / 25.4
            a4_width_px = int(A4_PORTRAIT_MM[0] * mm_to_px)
            a4_height_px = int(A4_PORTRAIT_MM[1] * mm_to_px)
            
            preview_img = Image.new("RGB", (a4_width_px, a4_height_px), "white")
            
            # Crear diccionario de elementos por ID
            items_by_id = {element.id: element for element in self.mixed_elements}
            
            # Obtener elemento seleccionado para resaltar
            selected = self.tree.selection()
            selected_id = None
            if selected:
                index = int(selected[0])
                if 0 <= index < len(self.mixed_elements):
                    selected_id = self.mixed_elements[index].id
            
            # Dibujar elementos con sus transformaciones visuales
            for placement in page.placements:
                element = items_by_id.get(placement.item_id)
                if not element:
                    continue
                
                # Calcular posición y tamaño en píxeles
                x_px = int(placement.x_mm * mm_to_px)
                y_px = int(placement.y_mm * mm_to_px)
                w_px = int(placement.width_mm * mm_to_px)
                h_px = int(placement.height_mm * mm_to_px)
                
                try:
                    # Cargar y procesar la imagen
                    with Image.open(element.path) as source:
                        # Aplicar orientación EXIF
                        source = ImageOps.exif_transpose(source)
                        
                        # Si está rotado físicamente por el packing, rotar la imagen
                        if placement.rotation:
                            source = source.rotate(-90, expand=True)
                        
                        # Convertir a RGBA para transparencia
                        source = source.convert("RGBA")
                        
                        # Aplicar transformación visual
                        transformed, paste_offset_x, paste_offset_y = _apply_image_transform(
                            source, 
                            element.transform, 
                            w_px, 
                            h_px
                        )
                        
                        # Calcular posición final
                        final_paste_x = x_px + paste_offset_x
                        final_paste_y = y_px + paste_offset_y
                        
                        # Recortar al marco si es necesario
                        if (element.transform.fit_mode == FitMode.COVER or 
                            element.transform.fit_mode == FitMode.MANUAL):
                            # Calcular región que cae dentro del marco
                            crop_x = max(0, -paste_offset_x)
                            crop_y = max(0, -paste_offset_y)
                            crop_w = min(transformed.width, w_px - paste_offset_x)
                            crop_h = min(transformed.height, h_px - paste_offset_y)
                            
                            if crop_w > 0 and crop_h > 0:
                                cropped = transformed.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))
                                preview_img.paste(cropped, (final_paste_x, final_paste_y), cropped)
                        else:
                            # Contain: pegar normalmente
                            preview_img.paste(transformed, (final_paste_x, final_paste_y), transformed)
                        
                        # Dibujar borde del marco
                        from PIL import ImageDraw
                        draw = ImageDraw.Draw(preview_img)
                        
                        # Resaltar elemento seleccionado
                        if placement.item_id == selected_id:
                            draw.rectangle([x_px, y_px, x_px + w_px, y_px + h_px], 
                                         outline="blue", width=3)
                        else:
                            draw.rectangle([x_px, y_px, x_px + w_px, y_px + h_px], 
                                         outline="gray", width=1)
                        
                except Exception as e:
                    # Si falla al cargar la imagen, dibujar rectángulo vacío
                    from PIL import ImageDraw
                    draw = ImageDraw.Draw(preview_img)
                    draw.rectangle([x_px, y_px, x_px + w_px, y_px + h_px], outline="red", width=2)
                    draw.text((x_px + 2, y_px + 2), placement.item_id, fill="black")
            
            preview_img, x_offset, y_offset = self._prepare_preview_image(preview_img)
            self.preview_photo = ImageTk.PhotoImage(preview_img)
            
            # Limpiar canvas y dibujar imagen
            self.preview_canvas.delete("all")
            preview_item = self.preview_canvas.create_image(x_offset, y_offset, anchor="nw", image=self.preview_photo)
            # Enlazar también al objeto visible: asegura el arrastre cuando el
            # clic cae sobre la imagen y no sobre el fondo del canvas.
            self.preview_canvas.tag_bind(preview_item, "<ButtonPress-1>", self.on_preview_mouse_down)
            self.preview_canvas.tag_bind(preview_item, "<B1-Motion>", self.on_preview_mouse_drag)
            self.preview_canvas.tag_bind(preview_item, "<ButtonRelease-1>", self.on_preview_mouse_up)
            
            # Guardar dimensiones para detección de clicks
            self.preview_img_offset = (x_offset, y_offset)
            self.preview_img_size = (preview_img.width, preview_img.height)
            self.preview_original_size = (a4_width_px, a4_height_px)
        except Exception as error:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(
                self.preview_canvas.winfo_width() // 2,
                self.preview_canvas.winfo_height() // 2,
                text=f"Error al renderizar: {error}",
                fill="red"
            )

    def _prepare_preview_image(self, image):
        """Prepara la imagen de vista previa con ajuste A4 y zoom visual."""
        from PIL import Image

        panel_width = self.preview_canvas.winfo_width()
        panel_height = self.preview_canvas.winfo_height()
        if panel_width < 100:
            panel_width = 400
        if panel_height < 100:
            panel_height = 500

        a4_ratio = A4_PORTRAIT_MM[0] / A4_PORTRAIT_MM[1]
        target_width = panel_width
        target_height = int(panel_width / a4_ratio)
        if target_height > panel_height:
            target_height = panel_height
            target_width = int(panel_height * a4_ratio)

        image = image.resize((target_width, target_height), Image.Resampling.LANCZOS)
        zoomed_width = max(1, int(target_width * self.view_zoom))
        zoomed_height = max(1, int(target_height * self.view_zoom))
        image = image.resize((zoomed_width, zoomed_height), Image.Resampling.LANCZOS)

        canvas_width = self.preview_canvas.winfo_width()
        canvas_height = self.preview_canvas.winfo_height()
        x_offset = max(0, (canvas_width - image.width) // 2)
        y_offset = max(0, (canvas_height - image.height) // 2)
        return image, x_offset, y_offset

    def render_uniform_preview(self):
        """Renderiza la vista previa en modo uniforme (existente)."""
        if not self.paths:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(
                self.preview_canvas.winfo_width() // 2,
                self.preview_canvas.winfo_height() // 2,
                text="Agregá imágenes para generar la vista previa.",
                fill=COLORS.muted
            )
            self.page_label.configure(text="Hoja 0 de 0")
            self.preview_photo = None
            return
        try:
            from PIL import ImageTk
            page = render_poster_pages(
                self.paths[:self.per_sheet_var.get()], self.per_sheet_var.get(), self.uniform_transforms,
                self.photo_strip_title_var.get(),
            )[0]
            preview_img, x_offset, y_offset = self._prepare_preview_image(page)
            self.preview_photo = ImageTk.PhotoImage(preview_img)

            self.preview_canvas.delete("all")
            preview_item = self.preview_canvas.create_image(x_offset, y_offset, anchor="nw", image=self.preview_photo)
            self.preview_canvas.tag_bind(preview_item, "<ButtonPress-1>", self.on_preview_mouse_down)
            self.preview_canvas.tag_bind(preview_item, "<B1-Motion>", self.on_preview_mouse_drag)
            self.preview_canvas.tag_bind(preview_item, "<ButtonRelease-1>", self.on_preview_mouse_up)
            
            # Actualizar contador de páginas
            count = self.per_sheet_var.get()
            pages = math.ceil(len(self.paths) / count)
            self.page_label.configure(text=f"Hoja 1 de {pages}")
            self.preview_img_offset = (x_offset, y_offset)
            self.preview_img_size = (preview_img.width, preview_img.height)
            self.preview_original_size = page.size
        except Exception as error:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(
                self.preview_canvas.winfo_width() // 2,
                self.preview_canvas.winfo_height() // 2,
                text=f"No se pudo crear la vista previa.\n{error}",
                fill="red"
            )

    def render_single_image_in_a4(self):
        """Muestra la hoja A4 real que contiene a la imagen seleccionada."""
        current = self._selected_uniform_transform()
        if not current:
            # Si no hay selección, mostrar la página completa
            self.render_uniform_preview()
            return
        
        path, transform = current
        
        try:
            from PIL import Image, ImageTk
            
            selected_index = int(self.tree.selection()[0])
            page, page_index, first_index = uniform_preview_page(
                self.paths, self.per_sheet_var.get(), selected_index,
                self.uniform_transforms, self.photo_strip_title_var.get(),
            )
            preview_img, x_offset, y_offset = self._prepare_preview_image(page)
            self.preview_photo = ImageTk.PhotoImage(preview_img)
            self.preview_canvas.delete("all")
            preview_item = self.preview_canvas.create_image(x_offset, y_offset, anchor="nw", image=self.preview_photo)
            self.preview_canvas.tag_bind(preview_item, "<ButtonPress-1>", self.on_preview_mouse_down)
            self.preview_canvas.tag_bind(preview_item, "<B1-Motion>", self.on_preview_mouse_drag)
            self.preview_canvas.tag_bind(preview_item, "<ButtonRelease-1>", self.on_preview_mouse_up)
            self.preview_img_offset = (x_offset, y_offset)
            self.preview_img_size = (preview_img.width, preview_img.height)
            self.preview_original_size = page.size
            total = len(self.paths)
            count = self.per_sheet_var.get()
            page_count = math.ceil(total / count)
            last_index = min(first_index + count, total)
            self.page_label.configure(
                text=f"Hoja {page_index + 1} de {page_count} · fotos {first_index + 1}–{last_index}",
            )
            
        except Exception as error:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(
                self.preview_canvas.winfo_width() // 2,
                self.preview_canvas.winfo_height() // 2,
                text=f"No se pudo crear la vista previa.\n{error}",
                fill="red"
            )

    def send_to_continuous(self):
        """Guarda las hojas fotográficas como planchas disponibles para una tira."""
        if not self.database:
            messagebox.showerror("Impresión continua", "No está disponible la base de Producción.", parent=self)
            return
        if self.mode_var.get() != DistributionMode.UNIFORM.value:
            messagebox.showinfo(
                "Impresión continua",
                "Para enviar a impresión continua usá «Individuales por hoja».", parent=self,
            )
            return
        try:
            pages = render_poster_pages(self.paths, self.per_sheet_var.get(), self.uniform_transforms,
                                        self.photo_strip_title_var.get())
        except Exception as error:
            messagebox.showerror("Impresión continua", f"No se pudieron preparar las hojas: {error}", parent=self)
            return
        if not pages:
            messagebox.showwarning("Impresión continua", "No hay hojas para enviar.", parent=self)
            return

        folder = Path(__file__).resolve().parents[2] / "outputs" / "impresiones_fotograficas"
        folder.mkdir(parents=True, exist_ok=True)
        batch = uuid.uuid4().hex[:10]
        created = 0
        try:
            for number, page in enumerate(pages, start=1):
                png_path = folder / f"fotografica_{batch}_{number:02d}.png"
                page.save(png_path, "PNG", dpi=(300, 300), compress_level=3)
                project = {
                    "mode": "Impresiones fotográficas", "workspace_format": "a4",
                    "source_paths": [str(path) for path in self.paths], "per_sheet": self.per_sheet_var.get(),
                }
                project_path = png_path.with_suffix(".json")
                project_path.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
                plancha_id = self.database.save_plancha_project(
                    None, f"Impresión fotográfica · Hoja {number}", "Papel fotográfico A4",
                    json.dumps(project, ensure_ascii=False), str(project_path), workspace_format="a4",
                )
                self.database.set_plancha_final_png(plancha_id, str(png_path))
                self.database.confirm_plancha_for_continuous(plancha_id)
                created += 1
        except Exception as error:
            messagebox.showerror("Impresión continua", f"No se pudieron enviar las hojas: {error}", parent=self)
            return
        self.summary_var.set(f"{created} hoja(s) fotográfica(s) listas para impresión continua.")
        messagebox.showinfo(
            "Impresión continua",
            f"Se agregaron {created} hoja(s) a Producción continua. Abrí la pestaña «Impresión continua» para armar la tira.",
            parent=self,
        )

    def export_cards_pdf(self):
        if self.mode_var.get() != DistributionMode.CARDS_9X5.value:
            messagebox.showinfo("Exportar PDF", "El PDF A4 exacto está disponible actualmente para Tarjetas 9×5.", parent=self)
            return
        offset_x, offset_y = self._effective_card_offsets("back")
        pages = [render_cards_9x5_page(self.card_slots, "front", offset_x_mm=self._effective_card_offsets("front")[0], offset_y_mm=self._effective_card_offsets("front")[1])]
        if self.card_double_sided_var.get():
            pages.append(render_cards_9x5_page(self.card_slots, "back", double_sided=True, bleed_mm=self.card_bleed_var.get(),
                                                offset_x_mm=offset_x, offset_y_mm=offset_y, flip_mode=self.card_flip_var.get()))
        target = filedialog.asksaveasfilename(parent=self, title="Exportar PDF A4 exacto", initialfile="tarjetas_9x5.pdf", defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
        if not target: return
        export_a4_pdf(pages, Path(target))
        messagebox.showinfo("PDF exportado", "PDF A4 generado. Imprimí a tamaño real / 100 %, sin ‘Ajustar a página’.", parent=self)

    def print_continuous(self):
        """Exporta las hojas A4 generadas como PNG consecutivos."""
        mode = self.mode_var.get()
        
        if mode == DistributionMode.UNIFORM.value:
            try:
                pages = render_poster_pages(self.paths, self.per_sheet_var.get(), self.uniform_transforms,
                                            self.photo_strip_title_var.get())
            except Exception as error:
                messagebox.showerror("Guardar PNG", f"No se pudieron preparar los pósters: {error}", parent=self)
                return
            prefix = "poster"
        elif mode == DistributionMode.SMART_COLLAGE.value:
            pages = self.collage_pages
            prefix = "collage"
        elif mode == DistributionMode.CARDS_9X5.value:
            front_offset_x, front_offset_y = self._effective_card_offsets("front")
            pages = [render_cards_9x5_page(
                self.card_slots, "front", offset_x_mm=front_offset_x,
                offset_y_mm=front_offset_y,
            )]
            if self.card_double_sided_var.get():
                offset_x, offset_y = self._effective_card_offsets("back")
                pages.append(render_cards_9x5_page(
                    self.card_slots, "back", double_sided=True,
                    bleed_mm=self.card_bleed_var.get(), offset_x_mm=offset_x,
                    offset_y_mm=offset_y, flip_mode=self.card_flip_var.get(),
                ))
            prefix = "tarjetas_9x5_frente"
        else:
            if not self.packing_result or not self.packing_result.pages:
                messagebox.showwarning("Guardar PNG", "No hay páginas para guardar.", parent=self)
                return
            try:
                items_by_id = {element.id: element for element in self.mixed_elements}
                pages = render_mixed_poster_pages(self.packing_result, items_by_id, dpi=300)
            except Exception as error:
                messagebox.showerror("Guardar PNG", f"No se pudieron preparar los pósters: {error}", parent=self)
                return
            prefix = "mixto"

        if not pages:
            messagebox.showwarning("Guardar PNG", "No hay páginas para guardar.", parent=self)
            return

        selected = filedialog.asksaveasfilename(
            parent=self,
            title="Guardar hojas A4 como PNG",
            initialfile=f"{prefix}.png",
            defaultextension=".png",
            filetypes=[("Imagen PNG", "*.png")],
        )
        if not selected:
            return

        selected_path = Path(selected)
        targets = []
        for number, page in enumerate(pages, 1):
            target = selected_path if len(pages) == 1 else selected_path.with_name(
                f"{selected_path.stem}_{number:03}.png"
            )
            page.save(target, "PNG", dpi=(300, 300))
            targets.append(target)

        if mode == DistributionMode.CARDS_9X5.value:
            selected_path.with_suffix(".cards_9x5.json").write_text(
                json.dumps(self.cards_project_state(), ensure_ascii=False, indent=2), encoding="utf-8",
            )

        self.summary_var.set(f"{len(targets)} hoja(s) PNG guardada(s)")
        messagebox.showinfo(
            "PNG guardado",
            f"Se guardaron {len(targets)} hoja(s) A4 en:\n{selected_path.parent}",
            parent=self,
        )

    def print_uniform(self):
        """Imprime en modo uniforme (existente)."""
        printer = default_printer()
        if not printer:
            messagebox.showwarning("Imprimir", "No se detectó una impresora predeterminada.", parent=self)
            return
        try:
            pages = render_poster_pages(self.paths, self.per_sheet_var.get(), self.uniform_transforms,
                                        self.photo_strip_title_var.get())
        except Exception as error:
            messagebox.showerror("Imprimir", f"No se pudieron preparar los pósters: {error}", parent=self)
            return
        self.print_button.configure(state="disabled")
        self.update_idletasks()
        with tempfile.TemporaryDirectory(prefix="doccione_posters_") as output:
            for number, page in enumerate(pages, 1):
                target = Path(output) / f"poster_{number:03}.png"
                page.save(target, dpi=(300, 300))
                result = print_png(printer, target, document_name=f"Doccione · Pósters {number}/{len(pages)}")
                if not result.success:
                    self.print_button.configure(state="normal")
                    messagebox.showerror("Impresión detenida", f"Hoja {number} de {len(pages)}: {result.message}", parent=self)
                    return
                self.summary_var.set(f"Enviada hoja {number} de {len(pages)} a {printer}…")
                self.update_idletasks()
        self.refresh()
        messagebox.showinfo("Impresión continua", f"Se enviaron {len(pages)} hoja(s) consecutivas a {printer}.", parent=self)

    def print_mixed(self):
        """Imprime en modo mixto usando render_mixed_poster_pages()."""
        if not self.packing_result or not self.packing_result.pages:
            messagebox.showwarning("Imprimir", "No hay páginas para imprimir.", parent=self)
            return
        
        if self.packing_result.unplaced_items:
            response = messagebox.askyesno(
                "Elementos sin colocar",
                f"Hay {len(self.packing_result.unplaced_items)} elementos que no caben en las hojas. ¿Desea imprimir solo los colocados?",
                parent=self
            )
            if not response:
                return
        
        printer = default_printer()
        if not printer:
            messagebox.showwarning("Imprimir", "No se detectó una impresora predeterminada.", parent=self)
            return
        
        try:
            # Crear diccionario de elementos por ID
            items_by_id = {element.id: element for element in self.mixed_elements}
            pages = render_mixed_poster_pages(self.packing_result, items_by_id, dpi=300)
        except Exception as error:
            messagebox.showerror("Imprimir", f"No se pudieron preparar los pósters: {error}", parent=self)
            return
        
        self.print_button.configure(state="disabled")
        self.update_idletasks()
        
        with tempfile.TemporaryDirectory(prefix="doccione_mixed_") as output:
            for number, page in enumerate(pages, 1):
                target = Path(output) / f"mixed_{number:03}.png"
                page.save(target, dpi=(300, 300))
                result = print_png(printer, target, document_name=f"Doccione · Mixto {number}/{len(pages)}")
                if not result.success:
                    self.print_button.configure(state="normal")
                    messagebox.showerror("Impresión detenida", f"Hoja {number} de {len(pages)}: {result.message}", parent=self)
                    return
                self.summary_var.set(f"Enviada hoja {number} de {len(pages)} a {printer}…")
                self.update_idletasks()
        
        self.refresh()
        messagebox.showinfo("Impresión mixta", f"Se enviaron {len(pages)} hoja(s) a {printer}.", parent=self)

    # ========================================================================
    # MÉTODOS PARA COLLAGE INTELIGENTE
    # ========================================================================
    
    def _get_collage_generator(self):
        if self._collage_generator is None:
            from app.planchas.smart_collage import SmartCollageGenerator
            self._collage_generator = SmartCollageGenerator()
        return self._collage_generator

    def _render_selected_collage_page(self):
        """Regenera solo la hoja afectada usando el análisis de imágenes en caché."""
        if not self.collage_layouts:
            return
        paths, template = self.collage_layouts[self.current_page_index]
        self.collage_pages[self.current_page_index] = self._get_collage_generator().create_collage(
            paths, canvas_width=SHEET_SIZE[0], canvas_height=SHEET_SIZE[1],
            template=template, gap=self.collage_gap_var.get(),
            image_offsets=self.collage_offsets, image_scales=self.collage_scales,
            image_rotations=self.collage_rotations,
            manual_image_keys=self.collage_manual_images,
        )
        self.render_collage_preview()

    def _schedule_collage_render(self):
        """Limita el redibujado durante el arrastre para conservar fluidez."""
        if self._collage_render_after is not None:
            return
        self._collage_render_after = self.after(45, self._flush_collage_render)

    def _flush_collage_render(self):
        self._collage_render_after = None
        self._render_selected_collage_page()

    def refresh_collage(self):
        """Actualiza la vista en modo collage inteligente."""
        self.refresh_collage_tree()
        self.refresh_collage_preview()
        
        # Actualizar estado de botones
        selected = self.tree.selection()
        self.btn_remove.config(state="normal" if selected else "disabled")
        self.btn_clear.config(state="normal" if self.paths else "disabled")
    
    def refresh_collage_tree(self):
        """Actualiza el treeview del modo collage."""
        self.tree.delete(*self.tree.get_children())
        for index, path in enumerate(self.paths):
            self.tree.insert("", "end", iid=str(index), values=(path.name,))
    
    def refresh_collage_preview(self):
        """Genera y muestra la vista previa del collage."""
        if not self.paths:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(
                self.preview_canvas.winfo_width() // 2,
                self.preview_canvas.winfo_height() // 2,
                text="Agregá imágenes para generar el collage.",
                fill=COLORS.muted
            )
            self.page_label.configure(text="Hoja 0 de 0")
            self.summary_var.set("0 imágenes · 0 hojas A4")
            self.print_button.configure(state="disabled")
            return
        
        try:
            from app.planchas.smart_collage import SmartCollageGenerator, CollageTemplateLibrary
            
            # Obtener configuración
            template_name = self.collage_template_var.get()
            gap = self.collage_gap_var.get()
            
            generator = self._get_collage_generator()
            
            # Generar collages para todas las imágenes (agrupadas según template)
            self.collage_pages = []
            self.collage_layouts = []
            
            # Si es "auto", agrupar por mejor template
            if template_name == "auto":
                # Procesar imágenes en lotes según templates disponibles
                templates = CollageTemplateLibrary.get_all_templates()
                remaining = list(self.paths)
                used_template_names = set()
                previous_template_name = None
                
                while remaining:
                    best_template = _choose_auto_collage_template(
                        templates, len(remaining), used_template_names,
                        previous_template_name,
                    )
                    if not best_template:
                        # Si quedan menos que el mínimo, usar single_large
                        best_template = CollageTemplateLibrary.single_large()
                    
                    # Tomar imágenes para este template
                    batch = remaining[:best_template.num_cells]
                    remaining = remaining[best_template.num_cells:]
                    
                    # Generar collage
                    collage = generator.create_collage(
                        batch,
                        canvas_width=SHEET_SIZE[0],
                        canvas_height=SHEET_SIZE[1],
                        template=best_template,
                        gap=gap, image_offsets=self.collage_offsets, image_scales=self.collage_scales,
                        image_rotations=self.collage_rotations,
                        manual_image_keys=self.collage_manual_images
                    )
                    self.collage_pages.append(collage)
                    self.collage_layouts.append((batch, best_template))
                    used_template_names.add(best_template.name)
                    previous_template_name = best_template.name
            else:
                # Template específico seleccionado
                template = None
                for t in CollageTemplateLibrary.get_all_templates():
                    if t.name == template_name:
                        template = t
                        break
                
                if not template:
                    template = CollageTemplateLibrary.single_large()
                
                # Procesar imágenes en lotes del tamaño del template
                for i in range(0, len(self.paths), template.num_cells):
                    batch = self.paths[i:i + template.num_cells]
                    
                    collage = generator.create_collage(
                        batch,
                        canvas_width=SHEET_SIZE[0],
                        canvas_height=SHEET_SIZE[1],
                        template=template,
                        gap=gap, image_offsets=self.collage_offsets, image_scales=self.collage_scales,
                        image_rotations=self.collage_rotations,
                        manual_image_keys=self.collage_manual_images
                    )
                    self.collage_pages.append(collage)
                    self.collage_layouts.append((batch, template))
            
            # Resetear página actual
            self.current_page_index = 0
            
            # Actualizar información
            self.summary_var.set(f"{len(self.paths)} imágenes · {len(self.collage_pages)} hojas A4")
            self.page_label.configure(text=f"Hoja 1 de {len(self.collage_pages)}")
            self.print_button.configure(state="normal")
            
            # Renderizar vista previa
            self.render_collage_preview()
            
        except Exception as error:
            import traceback
            traceback.print_exc()
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(
                self.preview_canvas.winfo_width() // 2,
                self.preview_canvas.winfo_height() // 2,
                text=f"Error al generar collage:\n{str(error)}",
                fill="red",
                width=350
            )
            self.summary_var.set("Error al generar collage")
            self.print_button.configure(state="disabled")
    
    def render_collage_preview(self):
        """Renderiza la vista previa de la página de collage actual."""
        if not self.collage_pages:
            return
        
        try:
            from PIL import ImageTk
            
            # Obtener página actual
            page = self.collage_pages[self.current_page_index]
            
            preview_img, x_offset, y_offset = self._prepare_preview_image(page.copy())
            self.preview_photo = ImageTk.PhotoImage(preview_img)
            
            # Limpiar canvas y dibujar imagen
            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(x_offset, y_offset, anchor="nw", image=self.preview_photo)
            
            # Actualizar contador de páginas
            self.preview_img_offset = (x_offset, y_offset)
            self.preview_img_size = (preview_img.width, preview_img.height)
            self.preview_original_size = page.size
            preview_item = self.preview_canvas.find_all()[-1]
            self.preview_canvas.tag_bind(preview_item, "<ButtonPress-1>", self.on_preview_mouse_down)
            self.preview_canvas.tag_bind(preview_item, "<B1-Motion>", self.on_preview_mouse_drag)
            self.preview_canvas.tag_bind(preview_item, "<ButtonRelease-1>", self.on_preview_mouse_up)
            
            self.preview_canvas.create_image(x_offset, y_offset, anchor="nw", image=self.preview_photo)
            
            # Actualizar contador de páginas
            self.preview_img_offset = (x_offset, y_offset)
            self.preview_img_size = (img_width, img_height)
            self.preview_original_size = page.size
            preview_item = self.preview_canvas.find_all()[-1]
            self.preview_canvas.tag_bind(preview_item, "<ButtonPress-1>", self.on_preview_mouse_down)
            self.preview_canvas.tag_bind(preview_item, "<B1-Motion>", self.on_preview_mouse_drag)
            self.preview_canvas.tag_bind(preview_item, "<ButtonRelease-1>", self.on_preview_mouse_up)
            self.sheet_info_label.config(text="Hacé clic y arrastrá una foto para reencuadrarla")
            self.page_label.configure(text=f"Hoja {self.current_page_index + 1} de {len(self.collage_pages)}")
            self._draw_collage_selection()
            
        except Exception as error:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(
                self.preview_canvas.winfo_width() // 2,
                self.preview_canvas.winfo_height() // 2,
                text=f"Error al renderizar: {error}",
                fill="red"
            )
    
    def _preview_event_position(self, event):
        """Obtiene la posición respecto del canvas aun si el evento viene del padre."""
        if hasattr(event, "x_root") and event.x_root is not None:
            return (event.x_root - self.preview_canvas.winfo_rootx(),
                    event.y_root - self.preview_canvas.winfo_rooty())
        return event.x, event.y

    def _draw_collage_selection(self):
        """Restaura el marco de la imagen seleccionada después de redibujar."""
        if self.collage_selected_path is None or not self.collage_layouts:
            return
        paths, template = self.collage_layouts[self.current_page_index]
        if self.collage_selected_path not in paths:
            return
        cell = template.cells[paths.index(self.collage_selected_path)]
        original_w, original_h = self.preview_original_size
        x0, y0 = self.preview_img_offset
        width, height = self.preview_img_size
        cx, cy, cw, ch = cell.to_pixels(original_w, original_h)
        self.preview_canvas.create_rectangle(
            x0 + cx * width / original_w, y0 + cy * height / original_h,
            x0 + (cx + cw) * width / original_w, y0 + (cy + ch) * height / original_h,
            outline="#36a8ff", width=2, tags="collage_selection",
        )

    def _start_collage_drag(self, event):
        """Select the collage image under the pointer for direct reframing."""
        if not self.collage_layouts or not hasattr(self, "preview_img_offset"):
            return
        x0, y0 = self.preview_img_offset
        event_x, event_y = self._preview_event_position(event)
        width, height = self.preview_img_size
        if not (x0 <= event_x <= x0 + width and y0 <= event_y <= y0 + height):
            return
        original_w, original_h = self.preview_original_size
        x = (event_x - x0) * original_w / width
        y = (event_y - y0) * original_h / height
        paths, template = self.collage_layouts[self.current_page_index]
        for path, cell in zip(paths, template.cells):
            cx, cy, cw, ch = cell.to_pixels(original_w, original_h)
            if cx <= x <= cx + cw and cy <= y <= cy + ch:
                self.dragging_collage_path = path
                self.collage_selected_path = path
                self.dragging_collage_cell = cell
                self.drag_start_x, self.drag_start_y = event_x, event_y
                self.preview_canvas.config(cursor="hand2")
                self.preview_canvas.focus_set()
                self.preview_canvas.delete("collage_selection")
                px = x0 + cx * width / original_w
                py = y0 + cy * height / original_h
                pw = cw * width / original_w
                ph = ch * height / original_h
                self.preview_canvas.create_rectangle(px, py, px + pw, py + ph,
                                                    outline="#36a8ff", width=2,
                                                    tags="collage_selection")
                self.sheet_info_label.config(text="Imagen seleccionada: arrastrá para reencuadrarla")
                return

    def _drag_collage_image(self, event):
        """Move only the selected image inside its own collage cell."""
        if self.dragging_collage_path is None:
            return
        width, height = self.preview_img_size
        original_w, original_h = self.preview_original_size
        event_x, event_y = self._preview_event_position(event)
        dx = (event_x - self.drag_start_x) * original_w / width
        dy = (event_y - self.drag_start_y) * original_h / height
        key = str(self.dragging_collage_path)
        old_x, old_y = self.collage_offsets.get(key, (0.0, 0.0))
        self.collage_offsets[key] = (old_x + dx, old_y + dy)
        self.sheet_info_label.config(text="Posición actualizada")
        self.drag_start_x, self.drag_start_y = event_x, event_y
        self._schedule_collage_render()

    def on_collage_tree_selection(self, _event=None):
        """Selecciona una foto de la lista para reencuadrarla con los botones."""
        selected = self.tree.selection()
        if not selected:
            return
        index = int(selected[0])
        if 0 <= index < len(self.paths):
            self.collage_selected_path = self.paths[index]
            self.sheet_info_label.config(text="Imagen seleccionada: usá las flechas para reencuadrarla")
            # Actualizar vista previa cuando cambia la selección
            self._render_selected_collage_page()

    def adjust_collage_zoom(self, factor):
        """Amplía o reduce el recorte de la imagen seleccionada."""
        if self.collage_selected_path is None:
            self.sheet_info_label.config(text="Tocá una foto de la vista previa primero")
            return
        key = str(self.collage_selected_path)
        scale = max(1.0, min(3.0, self.collage_scales.get(key, 1.0) * factor))
        self.collage_scales[key] = scale
        self.collage_manual_images.add(key)
        self.move_collage_selection(0, 0)
        self.sheet_info_label.config(text=f"Zoom de imagen: {scale * 100:.0f}%")

    def rotate_collage_selection(self):
        """Rota 90° en sentido horario la imagen seleccionada del collage."""
        if self.collage_selected_path is None:
            self.sheet_info_label.config(text="Seleccioná una imagen antes de rotarla")
            return
        key = str(self.collage_selected_path)
        rotation = (self.collage_rotations.get(key, 0) + 90) % 360
        if rotation:
            self.collage_rotations[key] = rotation
        else:
            self.collage_rotations.pop(key, None)
        self._render_selected_collage_page()
        self.sheet_info_label.config(text=f"Imagen rotada: {rotation}°")

    def delete_collage_selected(self):
        """Quita la foto seleccionada y recompone el collage automáticamente."""
        if self.mode_var.get() != DistributionMode.SMART_COLLAGE.value:
            return
        if self.collage_selected_path is None:
            self.sheet_info_label.config(text="Tocá una foto antes de presionar Suprimir")
            return
        removed_path = self.collage_selected_path
        page_before_delete = self.current_page_index
        self.paths = [path for path in self.paths if path != removed_path]
        key = str(removed_path)
        self.collage_offsets.pop(key, None)
        self.collage_scales.pop(key, None)
        self.collage_rotations.pop(key, None)
        self.collage_manual_images.discard(key)
        self.collage_selected_path = None
        self.dragging_collage_path = None
        self.refresh_collage()
        if self.collage_pages:
            self.current_page_index = min(page_before_delete, len(self.collage_pages) - 1)
            self.render_collage_preview()
        self.sheet_info_label.config(text="Imagen eliminada; collage recompuesto")

    def move_collage_selection(self, dx, dy):
        """Desplaza de forma confiable la foto seleccionada dentro de su celda."""
        if self.collage_selected_path is None:
            self.sheet_info_label.config(text="Seleccioná una imagen de la lista primero")
            return
        for page_index, (paths, template) in enumerate(self.collage_layouts):
            if self.collage_selected_path not in paths:
                continue
            key = str(self.collage_selected_path)
            old_x, old_y = self.collage_offsets.get(key, (0.0, 0.0))
            self.collage_offsets[key] = (old_x + dx, old_y + dy)
            self.current_page_index = page_index
            self._render_selected_collage_page()
            self.sheet_info_label.config(text="Posición actualizada")
            return

    def on_collage_settings_change(self):
        """Maneja el cambio de configuración del collage."""
        self.refresh_collage_preview()
    
    def print_collage(self):
        """Imprime en modo collage inteligente."""
        if not self.collage_pages:
            messagebox.showwarning("Imprimir", "No hay páginas para imprimir.", parent=self)
            return
        
        printer = default_printer()
        if not printer:
            messagebox.showwarning("Imprimir", "No se detectó una impresora predeterminada.", parent=self)
            return
        
        self.print_button.configure(state="disabled")
        self.update_idletasks()
        
        with tempfile.TemporaryDirectory(prefix="doccione_collage_") as output:
            for number, page in enumerate(self.collage_pages, 1):
                target = Path(output) / f"collage_{number:03}.png"
                page.save(target, dpi=(300, 300))
                result = print_png(printer, target, document_name=f"Doccione · Collage {number}/{len(self.collage_pages)}")
                if not result.success:
                    self.print_button.configure(state="normal")
                    messagebox.showerror("Impresión detenida", f"Hoja {number} de {len(self.collage_pages)}: {result.message}", parent=self)
                    return
                self.summary_var.set(f"Enviada hoja {number} de {len(self.collage_pages)} a {printer}…")
                self.update_idletasks()
        
        self.refresh()
        messagebox.showinfo("Impresión collage", f"Se enviaron {len(self.collage_pages)} hoja(s) a {printer}.", parent=self)
