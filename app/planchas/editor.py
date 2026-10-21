"""Editor visual de la primera etapa del Constructor de planchas."""

from __future__ import annotations

import base64
import copy
import json
import os
import tkinter as tk
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from app.indexer.thumbnails import load_thumbnail
from app.performance import record_performance
from app.planchas.model import A4_HEIGHT_CM, A4_WIDTH_CM, A5_PRINT_MARGIN_CM, DEFAULT_EXTRA_LAYOUT_CM, FIVE_ROW_SIZE_CM, HITBOX_INNER_CLEARANCE_CM, MAX_SIZE_CM, PRINT_MARGIN_CM, SIZE_OFFSET_CM, SPECIAL_LAYOUT_EXTRA_CM, WORKSPACE_FORMATS, PlanchaItem, PlanchaProject, size_for_image, size_from_visible_dimensions, validate_no_overlaps, visible_bbox
from app.planchas.production_geometry import expected_final_size, production_max_for_nominal, production_min_for_nominal, proportional_production_size
from app.ui.components import icon_button
from app.ui.rounded_components import RoundedCard, RoundedToolbar
from app.ui.theme import (
    COLORS,
    IDENTITY_FONT,
    RADIUS,
    SEMANTIC_COLORS,
    SPACE,
    TYPE,
    UI_FONT,
    configure_plancha_styles,
)

WORKSPACE_COLORS = {
    "a4": ("#38bdf8", "#e0f2fe"),
    "a5": ("#22c55e", "#dcfce7"),
    "franja": ("#d6c45b", "#fffdf0"),
}


def is_round_sticker_mask(mask) -> bool:
    """Reconoce círculos para no confundirlos con una silueta irregular."""
    try:
        from PIL import Image, ImageChops, ImageDraw

        box = mask.getbbox()
        if not box:
            return False
        shape = mask.crop(box)
        width, height = shape.size
        if not (0.90 <= width / max(1, height) <= 1.10):
            return False
        ideal = Image.new("L", shape.size, 0)
        ImageDraw.Draw(ideal).ellipse((0, 0, width - 1, height - 1), fill=255)
        actual = shape.point(lambda value: 255 if value > 8 else 0)
        union = ImageChops.lighter(actual, ideal)
        overlap = ImageChops.darker(actual, ideal)
        union_pixels = sum(value > 0 for value in union.getdata())
        overlap_pixels = sum(value > 0 for value in overlap.getdata())
        return union_pixels > 0 and overlap_pixels / union_pixels >= 0.92
    except Exception:
        return False


def needs_silhouette_outline(image) -> bool:
    """Distingue una silueta recortada de una imagen rectangular o cuadrada."""
    try:
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        mask = alpha.point(lambda opacity: 255 if opacity > 8 else 0)
        visible = sum(1 for value in mask.getdata() if value)
        total = max(1, mask.width * mask.height)
        coverage = visible / total
        if is_round_sticker_mask(mask):
            return False
        # Una imagen rectangular llena casi toda su caja y ocupa la mayor parte
        # de sus cuatro bordes. Una silueta irregular deja aire en ellos.
        edge_values = []
        edge_values.extend(mask.crop((0, 0, mask.width, 1)).getdata())
        edge_values.extend(mask.crop((0, mask.height - 1, mask.width, mask.height)).getdata())
        edge_values.extend(mask.crop((0, 0, 1, mask.height)).getdata())
        edge_values.extend(mask.crop((mask.width - 1, 0, mask.width, mask.height)).getdata())
        edge_coverage = sum(1 for value in edge_values if value) / max(1, len(edge_values))
        return not (coverage >= 0.90 and edge_coverage >= 0.65)
    except Exception:
        return True


def round_rectangular_corners(image, radius: int = 6):
    """Suaviza las esquinas de diseños rectangulares sin agregar bordes."""
    try:
        from PIL import Image, ImageChops, ImageDraw

        result = image.convert("RGBA")
        rounded = Image.new("L", result.size, 0)
        ImageDraw.Draw(rounded).rounded_rectangle(
            (0, 0, result.width - 1, result.height - 1),
            radius=min(radius, result.width // 4, result.height // 4),
            fill=255,
        )
        result.putalpha(ImageChops.multiply(result.getchannel("A"), rounded))
        return result
    except Exception:
        return image


def prepare_sticker_for_target(
    image, target: tuple[int, int], outlined: bool | None = None, remove_inner_white_border: bool = False,
):
    """Prepara el sticker igual para pantalla y PNG, a una caja final exacta."""
    from PIL import Image

    sticker = image.convert("RGBA")
    sticker.thumbnail((max(1, target[0] - 2), max(1, target[1] - 2)), Image.Resampling.LANCZOS)
    # Los diseños que pasan por el creador de stickers ya pueden traer su
    # propio borde blanco (y, a veces, negro). No se les suma otro contorno:
    # hacerlo duplica visualmente el borde en la plancha final.
    try:
        from app.stickers.pipeline import StickerProcessor

        has_existing_outline = StickerProcessor._has_white_outer_border(
            sticker, sticker.getchannel("A"), threshold=0.35,
        )
    except Exception:
        has_existing_outline = False
    if has_existing_outline:
        # El blanco de la silueta se conserva como guarda interna y se agrega
        # el trazo negro externo de corte. No se elimina ni se recorta el
        # relleno blanco propio del sticker.
        sticker = add_inner_black_outline(
            sticker, pixels=2, inner_border=True, force=True,
        )
        return sticker.resize(target, Image.Resampling.LANCZOS)
    if outlined is None:
        outlined = needs_silhouette_outline(sticker)
    if outlined:
        # Reserva la banda blanca de seguridad y el contorno negro antes de
        # volver a llevar el resultado a la misma hitbox final.
        sticker.thumbnail((max(1, target[0] - 36), max(1, target[1] - 36)), Image.Resampling.LANCZOS)
        # Un solo borde de corte exterior. El borde blanco interno duplicaba
        # visualmente el contorno de las siluetas.
        sticker = add_inner_black_outline(sticker, pixels=2, inner_border=False)
    else:
        # Círculos, cuadrados y rectángulos usan únicamente el trazo negro
        # exterior: no llevan la banda blanca interna de las siluetas.
        sticker.thumbnail((max(1, target[0] - 36), max(1, target[1] - 36)), Image.Resampling.LANCZOS)
        sticker = add_inner_black_outline(sticker, pixels=2, inner_border=False, force=True)
    final_box = sticker.getchannel("A").getbbox()
    if final_box:
        sticker = sticker.crop(final_box)
    return sticker.resize(target, Image.Resampling.LANCZOS)


def load_visible_thumbnail(path: str, size: tuple[int, int], rotation: int = 0, remove_inner_white_border: bool = False):
    """Miniatura de la silueta: no dibuja el lienzo vacío del archivo."""
    try:
        from PIL import Image, ImageTk

        with Image.open(path) as source:
            image = source.convert("RGBA").crop(visible_bbox(source))
        # Se usa exactamente la misma preparación que la exportación final,
        # solo reducida al tamaño visual de la tarjeta del editor.
        if rotation:
            image = image.rotate(-rotation, expand=True)
        final_size = (max(1, size[0] - 8), max(1, size[1] - 8))
        preview_scale = 6
        production_size = (final_size[0] * preview_scale, final_size[1] * preview_scale)
        processed = prepare_sticker_for_target(
            image, production_size, outlined=needs_silhouette_outline(image),
            remove_inner_white_border=remove_inner_white_border,
        )
        processed.thumbnail(final_size, Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(processed)
    except Exception:
        return load_thumbnail(path, size)


def add_inner_black_outline(image, pixels: int = 2, inner_border: bool = True, force: bool = False):
    """Genera el borde de corte: diseño → 5 px blancos → 2 px negros."""
    try:
        from PIL import Image, ImageChops, ImageFilter

        sticker = image.convert("RGBA")
        if not force and not needs_silhouette_outline(sticker):
            return sticker
        # Se agrega aire transparente para que las dos capas de borde jamás se
        # recorten, incluso cuando el PNG original llega ajustado a la silueta.
        # 1,25 mm de protección real a 300 DPI: cubre los microbordes grises
        # del archivo antes del corte configurado en el plotter.
        white_pixels = 15
        padding = white_pixels + pixels + 2
        base = Image.new("RGBA", (sticker.width + padding * 2, sticker.height + padding * 2), (0, 0, 0, 0))
        base.alpha_composite(sticker, (padding, padding))
        # Se binariza el alfa: Photoshop recibe negro pleno, no un borde gris
        # causado por transparencias parciales o antialias del archivo.
        mask = base.getchannel("A").point(lambda opacity: 255 if opacity > 8 else 0)
        # Suaviza únicamente la silueta de corte: redondea microángulos y
        # dientes que obligan al plotter a frenar, sin modificar la ilustración.
        cut_mask = mask.filter(ImageFilter.GaussianBlur(radius=1.25)).point(lambda opacity: 255 if opacity > 24 else 0)
        # La imagen ya fue reducida a su tamaño final de impresión (300 DPI),
        # por eso no hace falta calcular el borde a 4×. Trabajar directamente
        # aquí conserva el resultado nítido y evita millones de píxeles extra.
        white_kernel = white_pixels * 2 + 1
        black_kernel = pixels * 2 + 1
        white_shape = cut_mask.filter(ImageFilter.MaxFilter(white_kernel))
        black_shape = white_shape.filter(ImageFilter.MaxFilter(black_kernel))
        white_ring = ImageChops.subtract(white_shape, cut_mask)
        black_ring = ImageChops.subtract(black_shape, white_shape)
        # Esta franja se superpone al borde original. Es la que oculta dientes,
        # halos grises y pequeños defectos del PNG antes del negro de corte.
        inner_mask = cut_mask.filter(ImageFilter.MinFilter(white_kernel))
        white_inner = ImageChops.subtract(cut_mask, inner_mask)

        result = Image.new("RGBA", base.size, (0, 0, 0, 0))
        black_outline = Image.new("RGBA", base.size, (0, 0, 0, 0))
        black_outline.putalpha(black_ring)
        result.alpha_composite(black_outline)
        white_outline = Image.new("RGBA", base.size, (255, 255, 255, 0))
        white_outline.putalpha(white_ring)
        result.alpha_composite(white_outline)
        result.alpha_composite(base)
        if inner_border:
            white_inside_outline = Image.new("RGBA", base.size, (255, 255, 255, 0))
            white_inside_outline.putalpha(white_inner)
            result.alpha_composite(white_inside_outline)
        return result
    except Exception:
        return image


def add_outer_black_outline(image, pixels: int = 2):
    """Añade solo el trazo negro exterior, sin tocar ni recortar el diseño."""
    try:
        from PIL import Image, ImageChops, ImageFilter

        source = image.convert("RGBA")
        padding = max(2, pixels + 2)
        base = Image.new(
            "RGBA", (source.width + padding * 2, source.height + padding * 2), (0, 0, 0, 0),
        )
        base.alpha_composite(source, (padding, padding))
        mask = base.getchannel("A").point(lambda opacity: 255 if opacity > 8 else 0)
        outline = mask.filter(ImageFilter.MaxFilter(pixels * 2 + 1))
        ring = ImageChops.subtract(outline, mask)
        result = Image.new("RGBA", base.size, (0, 0, 0, 0))
        black = Image.new("RGBA", base.size, (0, 0, 0, 0))
        black.putalpha(ring)
        result.alpha_composite(black)
        result.alpha_composite(base)
        return result
    except Exception:
        return image


def size_for_record(image: dict, requested_size_cm: float = 5.0) -> tuple[float, float]:
    """Deriva el tamaño productivo desde el nominal, sin agrandado de UI."""
    if image.get("visible_width") and image.get("visible_height"):
        return proportional_production_size(requested_size_cm, image["visible_width"], image["visible_height"])
    width, height = size_for_image(image["path"], requested_size_cm)
    major = max(width, height)
    production_major = proportional_production_size(requested_size_cm, 1, 1)[0]
    return width * production_major / major, height * production_major / major


def preview_geometry(item: PlanchaItem, page_number: int = 1) -> dict[str, float | int | str]:
    """Geometría única que consume la vista A4; no recalcula el packing.

    ``x_cm`` e ``y_cm`` son la esquina superior izquierda de la hitbox. El
    diseño se centra en la hitbox exactamente como en ``render_sheet``.
    """
    return {
        "item_id": item.item_id,
        "page": page_number,
        "x_cm": item.x_cm,
        "y_cm": item.y_cm,
        "width_cm": item.width_cm,
        "height_cm": item.height_cm,
        "production_width_cm": item.production_width_cm,
        "production_height_cm": item.production_height_cm,
        "layout_width_cm": item.reserved_width_cm,
        "layout_height_cm": item.reserved_height_cm,
        "rotation": item.rotation,
        "design_x_cm": item.x_cm + (item.reserved_width_cm - item.width_cm) / 2,
        "design_y_cm": item.y_cm + (item.reserved_height_cm - item.height_cm) / 2,
    }


class PlanchaEditor(tk.Frame):
    SCALE = 22
    SIZE_PRESETS = tuple(range(5, 30))

    def __init__(self, master, images: list[dict], database=None, library_images: list[dict] | None = None,
                 project: PlanchaProject | None = None, order_id: int | None = None, plancha_id: int | None = None,
                 preserve_layout: bool = False, plancha_number: int = 1, max_planchas: int = 2,
                 layout_mode: str = "classic", workspace_format: str = "a4", auto_paginate: bool = True,
                 host: tk.Widget | None = None, on_close=None, person_name: str = "", person_phone: str = ""):
        # El editor puede vivir como una vista dentro de la ventana principal.
        # ``app`` conserva el acceso a los servicios de VisionVault, mientras
        # que ``host`` es la pestaña que lo contiene.
        self.app = master
        self._on_close = on_close
        # Un Frame vacío se evalúa como falso en Tkinter (su longitud es la
        # cantidad de hijos). Usar ``host or master`` montaba el editor fuera
        # de la ficha recién creada y dejaba el Creador aparentemente vacío.
        super().__init__(host if host is not None else master)
        self.plancha_number = max(1, int(plancha_number))
        self.max_planchas = max(self.plancha_number, int(max_planchas))
        self.layout_mode = "special" if layout_mode == "special" else "classic"
        self.packing_mode: str | None = None
        self.auto_paginate = auto_paginate
        title_kind = "especial" if self.layout_mode == "special" else "clásica"
        self.configure(background=COLORS.background)
        self.loading_screen, self.loading_message = self.create_loading_screen()
        self.loading_message.set("Midiendo los diseños seleccionados…")
        self.loading_screen.update_idletasks()
        
        # Lista de todos los proyectos (planchas) cuando hay paginación
        self.all_projects: list[PlanchaProject] = []
        self.current_project_index = 0
        
        # Crear proyecto inicial
        self.project = project or PlanchaProject.from_images(images)
        self.project.layout_mode = self.layout_mode
        if project is None:
            self.project.workspace_format = workspace_format if workspace_format in WORKSPACE_FORMATS else "a4"
        self.project.margin_cm = A5_PRINT_MARGIN_CM if self.project.workspace_format == "a5" else PRINT_MARGIN_CM
        self.format_heading = tk.StringVar(value=f"PLANCHA {self.project.workspace_label.upper()}")
        self.preserve_layout = preserve_layout
        self.use_experimental_packing = False
        self.database = database
        self.order_id = order_id
        self.plancha_id = plancha_id
        self.person_name = person_name.strip()
        self.person_phone = person_phone.strip()
        self.project_path = ""
        self.final_png_path = ""
        self.print_queue_paused = False
        self.active_print_job_id: int | None = None
        self.print_worker: threading.Thread | None = None
        self._devmode_bytes: bytes | None = None
        self.library_images = library_images or []
        if self.database and self.plancha_id:
            saved_plancha = self.database.plancha_project(self.plancha_id)
            if saved_plancha:
                self.order_id = self.order_id or saved_plancha.get("order_id")
                self.project_path = saved_plancha.get("project_path") or ""
                self.final_png_path = saved_plancha.get("final_png_path") or ""
                self.person_name = self.person_name or (saved_plancha.get("person_name") or "")
                self.person_phone = self.person_phone or (saved_plancha.get("person_phone") or "")
        if not self.preserve_layout and self.layout_mode == "classic":
            self.normalize_project_size()
        self.loading_message.set("Preparando el constructor de planchas…")
        self.loading_screen.update_idletasks()
        self.selected_id: str | None = None
        self.selected_ids: set[str] = set()
        self.sticker_clipboard: list[dict] = []
        self.clipboard_band_index: int | None = None
        # La vista inicial representa la impresión: las guías sólo aparecen
        # al pasar explícitamente a Vista técnica.
        self.show_hitboxes = False
        self.drag_offset = (0, 0)
        self.drag_band_index: int | None = None
        self.area_selection_start: tuple[float, float] | None = None
        self.area_selection_base: set[str] = set()
        self.area_selection_rect: int | None = None
        self.zoom = 1.0
        self.auto_fit_view = True
        self.zoom_label = tk.StringVar(value="100%")
        self.zoom_render_pending = False
        self.history: list[dict] = []
        self.future: list[dict] = []
        self.thumbnails = []
        # LRU: al navegar o hacer zoom no descartamos todas las miniaturas
        # anteriores de golpe (lo que provocaba repintados costosos).
        self.thumbnail_cache: OrderedDict[tuple, object] = OrderedDict()
        self.thumbnail_mtime_cache: dict[str, tuple[float, float]] = {}
        self._legend_signature = None
        # Vista previa, exportación e impresión usan exactamente el mismo
        # sticker preparado. Se conserva una caché acotada por píxeles para no
        # recalcular contornos y máscaras sin disparar el uso de memoria.
        self.production_sticker_cache: OrderedDict[tuple, object] = OrderedDict()
        self.production_sticker_cache_pixels = 0
        # Las medidas visibles se reutilizan al buscar rellenos. Así no se
        # vuelve a abrir la misma imagen cada vez que se completa una plancha.
        self.fill_size_cache: dict[str, tuple[float, float]] = {}
        self.render_pending = False
        self.pending_overflow: list[PlanchaItem] = []
        self._build()
        self.workspace_button.configure(text={"a4": "A4", "a5": "A5", "franja": "1/5"}[self.project.workspace_format])
        self.loading_screen.destroy()
        # El constructor embebido se crea inicialmente vacío y recibe los
        # seleccionados después. No abrir un progreso modal vacío: bloqueaba
        # visualmente la ventana mientras la app terminaba de anexarlos.
        if self.project.items and not self.preserve_layout:
            progress_dialog, report_progress = self.creation_progress_dialog(len(self.project.items))
        else:
            progress_dialog = None
            report_progress = lambda *_args, **_kwargs: None
        report_progress(0, 4, "Preparando los stickers seleccionados")
        
        # Usar paginación automática si está habilitado y no es un proyecto preservado
        if self.auto_paginate and not self.preserve_layout and not project:
            initial_overflow = self.organize_with_pagination(progress=report_progress)
        else:
            initial_overflow = [] if self.preserve_layout else self.organize_automatically(progress=report_progress)
        
        report_progress(4, 4, "Generando la vista previa de la plancha")
        self.snapshot()
        self.render()
        self.update_plancha_navigation()
        self.after_idle(self.fit_sheet_to_view)
        report_progress(5, 5, "Plancha lista")
        if progress_dialog is not None:
            self.after(180, lambda: progress_dialog.destroy() if progress_dialog.winfo_exists() else None)
        if initial_overflow and not self.auto_paginate:
            self.after(120, lambda: self.offer_overflow(initial_overflow))

    def close_embedded(self):
        """Cierra la vista integrada y devuelve el control a la aplicación."""
        callback = self._on_close
        if callback:
            callback()

    def title(self, _value=None):
        """Compatibilidad con el editor anterior basado en ``Toplevel``."""
        # El título pertenece ahora a la pestaña de la aplicación principal.
        return "Constructor de planchas"

    def create_loading_screen(self):
        """Pantalla inicial breve: evita mostrar el Constructor vacío."""
        parent_window = self.winfo_toplevel()
        dialog = tk.Toplevel(parent_window)
        dialog.title("Preparando plancha")
        dialog.configure(background=COLORS.panel)
        dialog.resizable(False, False)
        dialog.transient(parent_window)
        dialog.geometry("360x150")
        dialog.update_idletasks()
        x = parent_window.winfo_rootx() + max(0, (parent_window.winfo_width() - 360) // 2)
        y = parent_window.winfo_rooty() + max(0, (parent_window.winfo_height() - 150) // 2)
        dialog.geometry(f"360x150+{x}+{y}")
        tk.Label(dialog, text="CONSTRUCTOR DE PLANCHAS", background=COLORS.panel, foreground=COLORS.text, font=(IDENTITY_FONT, 15, "bold")).pack(pady=(30, 8))
        message = tk.StringVar(value="Preparando…")
        tk.Label(dialog, textvariable=message, background=COLORS.panel, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 11, "bold")).pack()
        progress = ttk.Progressbar(dialog, mode="indeterminate", length=250)
        progress.pack(pady=(14, 0))
        progress.start(10)
        dialog.wm_protocol("WM_DELETE_WINDOW", lambda: None)
        dialog.update_idletasks()
        return dialog, message

    def normalize_project_size(self):
        """Reconstruye producción desde el nominal; la hitbox estándar no cambia."""
        for item in self.project.items:
            nominal = item.nominal_size_cm if item.nominal_size_cm is not None else 5.0
            width, height = size_for_record({"path": item.path}, nominal)
            if item.rotation % 180:
                width, height = height, width
            item.width_cm, item.height_cm = width, height
            item.nominal_size_cm = nominal

    def creation_progress_dialog(self, sticker_count: int, title_text: str = "Creando plancha"):
        """Muestra progreso real para operaciones largas del constructor."""
        dialog = tk.Toplevel(self)
        dialog.title(title_text)
        dialog.configure(background=COLORS.panel)
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        dialog.geometry("390x155")
        title = tk.Label(dialog, text=title_text, background=COLORS.panel, foreground=COLORS.text, font=(IDENTITY_FONT, 16, "bold"))
        title.pack(anchor="w", padx=18, pady=(16, 4))
        detail = tk.StringVar(value=f"Preparando {sticker_count} stickers…")
        tk.Label(dialog, textvariable=detail, background=COLORS.panel, foreground=COLORS.text, anchor="w", font=(UI_FONT, 10)).pack(fill="x", padx=18)
        bar = ttk.Progressbar(dialog, mode="determinate", maximum=100, length=350)
        bar.pack(fill="x", padx=18, pady=(12, 5))
        timing = tk.StringVar(value="Calculando tiempo estimado…")
        tk.Label(dialog, textvariable=timing, background=COLORS.panel, foreground=COLORS.muted, anchor="w", font=(UI_FONT, 10)).pack(fill="x", padx=18)
        started = time.perf_counter()

        def report(step: int, total: int, message: str):
            total = max(1, total)
            fraction = min(1.0, max(0.0, step / total))
            # El armado usa cuatro alternativas de distribución y el render final.
            percent = 8 + fraction * 84 if step < total else 94
            elapsed = time.perf_counter() - started
            remaining = max(0.0, elapsed / fraction * (1 - fraction)) if fraction else 0.0
            bar["value"] = 100 if message == "Plancha lista" else percent
            detail.set(f"{message} · {sticker_count} stickers")
            if message == "Plancha lista":
                timing.set(f"100 % · terminado en {elapsed:.1f} s")
            elif fraction:
                timing.set(f"{bar['value']:.0f} % · tiempo restante estimado: {max(1, round(remaining))} s")
            else:
                timing.set("8 % · calculando tiempo estimado…")
            dialog.update_idletasks()
            self.update_idletasks()

        dialog.update_idletasks()
        return dialog, report

    def _build(self):
        configure_plancha_styles(self)

        # La barra organiza controles existentes; no interviene en el Canvas.
        toolbar = RoundedToolbar(
            self,
            background=SEMANTIC_COLORS.surface,
            outer_background=COLORS.background,
            border_color=SEMANTIC_COLORS.border,
            border_width=1,
            radius_px=10,
            padding=SPACE.xs,
        )
        toolbar.pack(
            fill="x",
            padx=SPACE.sm,
            pady=(SPACE.xs, SPACE.xs),
        )
        toolbar_inner = tk.Frame(
            toolbar.content,
            background=COLORS.panel,
        )
        toolbar_inner.pack(fill="x")
        toolbar_main = tk.Frame(toolbar_inner, background=COLORS.panel)
        toolbar_archive = tk.Frame(toolbar_inner, background=COLORS.panel)
        toolbar_action = tk.Frame(toolbar_inner, background=COLORS.panel)
        if self._on_close:
            ttk.Button(
                toolbar_main,
                text="← Dejar abierto",
                command=self.close_embedded,
                style="Plancha.Secondary.TButton",
                padding=(SPACE.sm, SPACE.xs),
            ).pack(side="left", padx=(0, SPACE.xs))

        def tool_group(parent, title: str, padding: tuple[int, int] = (0, 0)):
            group = tk.Frame(
                parent,
                background=SEMANTIC_COLORS.surface_elevated,
                highlightthickness=1,
                highlightbackground=SEMANTIC_COLORS.border,
            )
            group.pack(side="left", padx=padding)
            tk.Label(
                group,
                text=title,
                background=SEMANTIC_COLORS.surface_elevated,
                foreground=SEMANTIC_COLORS.text_muted,
                font=(IDENTITY_FONT, TYPE.auxiliary, "bold"),
            ).pack(anchor="w", padx=SPACE.xs, pady=(1, 0))
            actions = tk.Frame(group, background=SEMANTIC_COLORS.surface_elevated)
            actions.pack(padx=2, pady=(0, 2))
            return actions

        def toolbar_icon(parent, icon: str, description: str, command, *, tone: str = "secondary", width: int = 2):
            """Reutiliza icon_button y su tooltip con una presentación compacta."""
            button = icon_button(parent, icon, description, command, tone=tone)
            button.configure(width=width, padding=(5, 4))
            return button

        output = tool_group(toolbar_archive, "ARCHIVO")
        toolbar_icon(output, "↗", "Abrir proyecto", lambda *a, _fn=self.open_project: _fn(*a)).pack(side="left")
        toolbar_icon(output, "▣", "Guardar proyecto", lambda *a, _fn=self.save_project: _fn(*a)).pack(side="left", padx=(2, 0))
        toolbar_icon(output, "◉", "Generar vista previa", lambda *a, _fn=self.export_preview: _fn(*a)).pack(side="left", padx=(2, 0))
        toolbar_icon(output, "⇩", "Guardar PNG final", lambda *a, _fn=self.export_final: _fn(*a), tone="primary").pack(side="left", padx=(2, 0))
        toolbar_icon(output, "SVG", "Guardar SVG final", lambda *a, _fn=self.export_svg: _fn(*a), tone="primary", width=3).pack(side="left", padx=(2, 0))

        toolbar_icon(output, "▦", "Guardar todas las planchas de esta ficha", lambda *a, _fn=self.save_all_planchas: _fn(*a), tone="primary").pack(side="left", padx=(2, 0))

        work = tool_group(toolbar_main, "ARMADO")
        toolbar_icon(work, "＋", "Buscar y agregar diseños", lambda *a, _fn=self.add_images: _fn(*a), tone="primary").pack(side="left")
        self.regenerate_mixed_button = toolbar_icon(
            work, "↻", "Regenerar plancha mixta", lambda *a, _fn=self.regenerate_sticker_mixed: _fn(*a), tone="primary",
        )
        self.convert_mixed_button = toolbar_icon(
            work, "⇄", "Convertir plancha mixta a Libre", lambda *a, _fn=self.convert_sticker_mixed_to_free: _fn(*a),
        )
        toolbar_icon(work, "◈", "Optimizar distribución", lambda *a, _fn=self.optimize: _fn(*a), tone="primary").pack(side="left", padx=(2, 0))
        self.workspace_button = toolbar_icon(work, "▭", "Elegir formato de venta", lambda *a, _fn=self.show_workspace_options: _fn(*a), width=3)
        self.workspace_button.pack(side="left", padx=(2, 0))
        self.regenerate_mixed_button.pack_forget()
        self.convert_mixed_button.pack_forget()
        toolbar_icon(work, "▦", "Completar plancha", lambda *a, _fn=self.show_completion_options: _fn(*a)).pack(side="left", padx=(2, 0))
        toolbar_icon(work, "▤", "Abrir producción continua", lambda *a, _fn=self.open_continuous_production: _fn(*a)).pack(side="left", padx=(2, 0))

        edit = tool_group(toolbar_main, "EDICIÓN", (SPACE.xs, 0))
        toolbar_icon(edit, "☷", "Seleccionar todos", lambda *a, _fn=self.select_all_items: _fn(*a)).pack(side="left")
        self.hitbox_button = toolbar_icon(edit, "⌗", "Ocultar guías", lambda *a, _fn=self.toggle_hitboxes: _fn(*a))
        self.hitbox_button.pack(side="left", padx=(2, 0))
        self.experimental_packing_button = toolbar_icon(edit, "⌘", "Motor geométrico experimental", lambda *a, _fn=self.toggle_experimental_packing: _fn(*a))
        self.experimental_packing_button.pack(side="left", padx=(2, 0))
        toolbar_icon(edit, "↔", "Separar equitativamente por franja", lambda *a, _fn=self.distribute_evenly: _fn(*a)).pack(side="left", padx=(2, 0))
        toolbar_icon(edit, "↶", "Deshacer", lambda *a, _fn=self.undo: _fn(*a)).pack(side="left", padx=(2, 0))
        toolbar_icon(edit, "↷", "Rehacer", lambda *a, _fn=self.redo: _fn(*a)).pack(side="left", padx=(2, 0))
        toolbar_icon(edit, "⌫", "Eliminar diseño seleccionado", lambda *a, _fn=self.delete_selected: _fn(*a), tone="danger").pack(side="left", padx=(2, 0))

        toolbar_icon(edit, "×", "Descartar plancha", lambda *a, _fn=self.discard_plancha: _fn(*a), tone="danger").pack(side="left", padx=(2, 0))
        preview_tools = tool_group(toolbar_main, "VISTA", (SPACE.xs, 0))
        self.view_mode_button = ttk.Button(
            preview_tools, text="Vista: Normal", command=self.toggle_hitboxes,
            style="Plancha.Secondary.TButton", padding=(SPACE.sm, SPACE.xs),
        )
        self.view_mode_button.pack(side="left")
        ttk.Button(preview_tools, text="−", command=lambda: self.change_preview_zoom(-0.1), style="Plancha.Secondary.TButton", width=2).pack(side="left", padx=(2, 0))
        ttk.Label(preview_tools, textvariable=self.zoom_label, background=SEMANTIC_COLORS.surface_elevated, foreground=COLORS.text, width=5, anchor="center").pack(side="left")
        ttk.Button(preview_tools, text="+", command=lambda: self.change_preview_zoom(0.1), style="Plancha.Secondary.TButton", width=2).pack(side="left")
        ttk.Button(preview_tools, text="Ajustar", command=self.fit_sheet_to_view, style="Plancha.Secondary.TButton", padding=(SPACE.xs, SPACE.xs)).pack(side="left", padx=(2, 0))
        ttk.Button(toolbar_action, text="Enviar a cola", command=lambda *a, _fn=self.send_to_print_queue: _fn(*a), style="Plancha.Primary.TButton", padding=(SPACE.sm, SPACE.xs)).pack(side="right")

        toolbar_layout = {"stacked": None}

        def arrange_toolbar(event=None):
            available_width = event.width if event is not None else toolbar_inner.winfo_width()
            # Dentro de Producción el editor comparte ancho con paneles y
            # barras laterales. A 850 px el grupo ARCHIVO ya queda cortado a
            # la derecha; apilar antes conserva Guardar/PNG/SVG accesibles.
            stacked = available_width < 1150
            if toolbar_layout["stacked"] == stacked:
                return
            toolbar_layout["stacked"] = stacked
            toolbar_main.grid_forget()
            toolbar_archive.grid_forget()
            toolbar_action.grid_forget()
            if stacked:
                toolbar_main.grid(row=0, column=0, columnspan=3, sticky="w")
                toolbar_archive.grid(row=1, column=0, sticky="w", pady=(SPACE.xs, 0))
                toolbar_action.grid(row=1, column=2, sticky="e", pady=(SPACE.xs, 0))
            else:
                toolbar_main.grid(row=0, column=0, sticky="w")
                toolbar_archive.grid(row=0, column=1, sticky="w", padx=(SPACE.xs, 0))
                toolbar_action.grid(row=0, column=2, sticky="e", padx=(SPACE.xs, 0))

        toolbar_inner.columnconfigure(0, weight=0)
        toolbar_inner.columnconfigure(1, weight=1)
        toolbar_inner.columnconfigure(2, weight=0)
        toolbar_inner.bind("<Configure>", arrange_toolbar, add="+")
        toolbar_inner.after_idle(arrange_toolbar)

        body = ttk.Frame(self, padding=(12, 0, 12, 12))
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, background=COLORS.canvas, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.click_canvas)
        self.canvas.bind("<B1-Motion>", self.drag_item)
        self.canvas.bind("<ButtonRelease-1>", self.release_item)
        self.canvas.bind("<Button-3>", self.show_canvas_context_menu)
        self.canvas.bind("<Delete>", lambda _event: self.delete_selected())
        self.canvas.bind("<Control-c>", self.copy_selected_items)
        self.canvas.bind("<Control-v>", self.paste_selected_items)
        self.canvas.bind("<Alt-MouseWheel>", self.zoom_with_wheel)
        self.canvas.bind("<Control-MouseWheel>", self.pan_horizontally_with_wheel)
        self.canvas.bind("<Configure>", self._on_preview_canvas_resize, add="+")

        # El lateral es el área de trabajo del diseño: más ancho y ordenado
        # por tareas para que los controles no compitan con el resumen.
        details_host = tk.Frame(body, width=330, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        details_host.pack(side="right", fill="y", padx=(12, 0))
        details_host.pack_propagate(False)
        details_tabs = ttk.Notebook(details_host)
        details_tabs.pack(fill="both", expand=True)
        details_tab = tk.Frame(details_tabs, background=COLORS.panel)
        approval = tk.Frame(details_tabs, background=COLORS.panel)
        details_tabs.add(details_tab, text="Diseño")
        details_tabs.add(approval, text="Aprobación")
        details_canvas = tk.Canvas(details_tab, background=COLORS.panel, highlightthickness=0, borderwidth=0)
        # ttk comparte estilos por intérprete: estas variantes se aíslan por
        # nombre exclusivo y por asignarse solamente a este panel Diseño.
        # Reconfigurarlas por instancia es idempotente y usa siempre los
        # mismos valores, sin alterar estilos compartidos.
        details_style = ttk.Style(self)
        details_style.configure(
            "Plancha.Batch.Secondary.TButton",
            background=COLORS.panel,
            foreground=COLORS.text,
            bordercolor=COLORS.border_strong,
            lightcolor="#eeebe7",
            darkcolor="#cfcdc8",
            relief="flat",
            padding=(SPACE.sm, SPACE.xs),
            font=(UI_FONT, TYPE.body, "bold"),
            focuscolor=COLORS.primary_active,
        )
        details_style.map(
            "Plancha.Batch.Secondary.TButton",
            background=[
                ("active", COLORS.border_strong),
                ("pressed", COLORS.background_secondary),
            ],
            foreground=[("disabled", COLORS.disabled)],
        )
        details_style.configure(
            "Plancha.Details.Vertical.TScrollbar",
            background=COLORS.border,
            troughcolor=COLORS.panel,
            arrowcolor=COLORS.disabled,
            bordercolor=COLORS.panel,
            width=10,
        )
        details_style.map(
            "Plancha.Details.Vertical.TScrollbar",
            background=[
                ("active", COLORS.border_strong),
                ("pressed", COLORS.background_secondary),
            ],
        )
        details_scrollbar = ttk.Scrollbar(
            details_tab,
            orient="vertical",
            command=details_canvas.yview,
            style="Plancha.Details.Vertical.TScrollbar",
        )
        details_canvas.configure(yscrollcommand=details_scrollbar.set)
        details_scrollbar.pack(side="right", fill="y")
        details_canvas.pack(side="left", fill="both", expand=True)
        details = tk.Frame(details_canvas, background=COLORS.panel)
        details_window = details_canvas.create_window((0, 0), window=details, anchor="nw")
        details.bind("<Configure>", lambda _event: details_canvas.configure(scrollregion=details_canvas.bbox("all")))
        details_canvas.bind("<Configure>", lambda event: details_canvas.itemconfigure(details_window, width=event.width))
        details_canvas.bind("<MouseWheel>", lambda event: details_canvas.yview_scroll(-max(1, event.delta // 120), "units"))
        def rounded_section(parent, title: str, *, pady=(0, SPACE.sm)):
            card = RoundedCard(
                parent,
                background=SEMANTIC_COLORS.surface_elevated,
                outer_background=COLORS.panel,
                border_color=SEMANTIC_COLORS.border,
                border_width=1,
                radius_px=RADIUS.large_px,
                padding=SPACE.sm,
            )
            card.pack(fill="x", padx=SPACE.sm, pady=pady)
            tk.Label(
                card.content,
                text=title.upper(),
                background=SEMANTIC_COLORS.surface_elevated,
                foreground=COLORS.wine_active,
                font=(IDENTITY_FONT, TYPE.auxiliary, "bold"),
            ).pack(anchor="w", pady=(0, SPACE.xs))
            return card.content

        summary = rounded_section(
            details,
            "Resumen de plancha",
            pady=(SPACE.sm, SPACE.sm),
        )
        tk.Label(summary, textvariable=self.format_heading, background=COLORS.panel_elevated, foreground=COLORS.text, font=(IDENTITY_FONT, 12, "bold")).pack(anchor="w")
        self.stats = tk.StringVar()
        tk.Label(summary, textvariable=self.stats, background=COLORS.panel_elevated, foreground=COLORS.text, justify="left", wraplength=280, font=(UI_FONT, TYPE.body)).pack(anchor="w", pady=(SPACE.xs, 0))
        
        # Navegación entre planchas
        self.plancha_nav_frame = tk.Frame(summary, background=COLORS.panel_elevated)
        self.plancha_nav_frame.pack(fill="x", pady=(SPACE.sm, 0))
        separator = tk.Frame(self.plancha_nav_frame, height=1, background=SEMANTIC_COLORS.border)
        separator.pack(fill="x", pady=(0, SPACE.sm))
        
        self.plancha_stats_text = tk.StringVar(value="1 plancha")
        tk.Label(self.plancha_nav_frame, textvariable=self.plancha_stats_text, background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, TYPE.auxiliary)).pack(anchor="w")
        
        nav_buttons = tk.Frame(self.plancha_nav_frame, background=COLORS.panel_elevated)
        nav_buttons.pack(fill="x", pady=(SPACE.xs, 0))
        nav_buttons.columnconfigure(0, weight=0)
        nav_buttons.columnconfigure(1, weight=1)
        nav_buttons.columnconfigure(2, weight=0)
        
        self.prev_plancha_btn = ttk.Button(nav_buttons, text="◀ Anterior", command=self.previous_plancha, style="Plancha.Secondary.TButton", padding=(SPACE.xs, SPACE.xs))
        self.prev_plancha_btn.grid(row=0, column=0, sticky="w")
        
        self.plancha_counter_text = tk.StringVar(value="Plancha 1 de 1")
        self.plancha_picker = ttk.Combobox(nav_buttons, state="readonly", width=15)
        self.plancha_picker.grid(row=0, column=1, sticky="ew", padx=SPACE.xs)
        self.plancha_picker.bind("<<ComboboxSelected>>", self._pick_plancha)
        
        self.next_plancha_btn = ttk.Button(nav_buttons, text="Siguiente ▶", command=self.next_plancha, style="Plancha.Secondary.TButton", padding=(SPACE.xs, SPACE.xs))
        self.next_plancha_btn.grid(row=0, column=2, sticky="e")
        
        # Botones de acciones para todas las planchas
        all_planchas_card = RoundedCard(
            details,
            background=SEMANTIC_COLORS.surface_elevated,
            outer_background=COLORS.panel,
            border_color=SEMANTIC_COLORS.border,
            border_width=1,
            radius_px=RADIUS.large_px,
            padding=SPACE.sm,
        )
        all_planchas_card.pack(fill="x", padx=SPACE.sm, pady=(0, SPACE.sm))
        tk.Label(
            all_planchas_card.content,
            text="ACCIONES DE LOTE",
            background=SEMANTIC_COLORS.surface_elevated,
            foreground=COLORS.wine_active,
            font=(IDENTITY_FONT, TYPE.auxiliary, "bold"),
        ).pack(anchor="w", pady=(0, SPACE.xs))
        all_planchas_frame = tk.Frame(
            all_planchas_card.content,
            background=SEMANTIC_COLORS.surface_elevated,
        )
        all_planchas_frame.pack(fill="x")
        all_planchas_frame.columnconfigure(0, weight=1)

        ttk.Button(all_planchas_frame, text="Generar todas las planchas", command=self.generate_all_planchas, style="Plancha.Batch.Secondary.TButton").grid(row=0, column=0, sticky="ew")
        ttk.Button(all_planchas_frame, text="Exportar todas", command=self.export_all_planchas, style="Plancha.Batch.Secondary.TButton").grid(row=1, column=0, sticky="ew", pady=(SPACE.xs, 0))
        ttk.Button(all_planchas_frame, text="Enviar lote a impresión continua", command=self.send_batch_to_continuous, style="Plancha.Primary.TButton", padding=(SPACE.sm, SPACE.xs)).grid(row=2, column=0, sticky="ew", pady=(SPACE.xs, 0))
        ttk.Button(all_planchas_frame, text="Imprimir todas", command=self.print_all_planchas, style="Plancha.Primary.TButton", padding=(SPACE.sm, SPACE.xs)).grid(row=3, column=0, sticky="ew", pady=(SPACE.xs, 0))
        
        references = tk.Frame(details, background=COLORS.panel)
        references.pack(fill="x", padx=SPACE.sm, pady=(0, SPACE.sm))
        tk.Frame(
            references,
            height=1,
            background=SEMANTIC_COLORS.border,
        ).pack(fill="x", pady=(0, SPACE.sm))
        tk.Label(references, text="REFERENCIAS DEL ARMADO", background=COLORS.panel, foreground=COLORS.muted, font=(IDENTITY_FONT, TYPE.auxiliary, "bold")).pack(anchor="w", pady=(0, SPACE.xs))
        self.legend_frame = tk.Frame(references, background=COLORS.panel)
        self.legend_frame.pack(fill="x")
        selection = rounded_section(details, "Diseño seleccionado")
        self.selected_label = tk.StringVar(value="Elegí un diseño de la plancha.")
        tk.Label(selection, textvariable=self.selected_label, background=COLORS.panel_elevated, foreground=COLORS.text, justify="left", wraplength=280, font=(UI_FONT, TYPE.body)).pack(anchor="w", pady=(0, SPACE.sm))
        measurements = tk.Frame(selection, background=COLORS.panel_elevated)
        measurements.pack(fill="x")
        measurements.columnconfigure(0, weight=1)
        measurements.columnconfigure(1, weight=1)
        tk.Label(measurements, text="Tamaño (cm)", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, TYPE.body)).grid(row=0, column=0, sticky="w")
        tk.Label(measurements, text="Cantidad", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, TYPE.body)).grid(row=0, column=1, sticky="w", padx=(SPACE.sm, 0))
        self.size_value = tk.StringVar(value="5cm")
        size = ttk.Combobox(measurements, textvariable=self.size_value, values=tuple(f"{value}cm" for value in self.SIZE_PRESETS), state="readonly", width=14)
        size.grid(row=1, column=0, sticky="ew", pady=(SPACE.xs, 0))
        self.quantity_value = tk.IntVar(value=1)
        ttk.Spinbox(measurements, from_=1, to=100, textvariable=self.quantity_value, width=10).grid(row=1, column=1, sticky="ew", padx=(SPACE.sm, 0), pady=(SPACE.xs, 0))
        ttk.Button(selection, text="Aplicar tamaño y cantidad", command=self.apply_size_and_quantity, style="Plancha.Primary.TButton", padding=(SPACE.sm, SPACE.xs)).pack(fill="x", pady=(SPACE.sm, 0))
        ttk.Button(selection, text="Igualar por lado mayor", command=lambda *a, _fn=self.normalize_by_longest_side: _fn(*a), style="Plancha.Secondary.TButton", padding=(SPACE.sm, SPACE.xs)).pack(fill="x", pady=(SPACE.xs, 0))
        self.productive_resize_controls = tk.Frame(selection, background=COLORS.panel_elevated)
        ttk.Button(self.productive_resize_controls, text="−", width=3, command=lambda: self.resize_selected_productive(-1)).pack(side="left")
        ttk.Button(self.productive_resize_controls, text="+", width=3, command=lambda: self.resize_selected_productive(1)).pack(side="left", padx=(SPACE.xs, 0))
        ttk.Button(self.productive_resize_controls, text="Usar mínimo", command=lambda: self.resize_selected_productive("min")).pack(side="left", padx=(SPACE.sm, 0))
        ttk.Button(self.productive_resize_controls, text="Usar máximo", command=lambda: self.resize_selected_productive("max")).pack(side="left", padx=(SPACE.xs, 0))
        ttk.Button(self.productive_resize_controls, text="Cambiar tamaño nominal", command=self.change_selected_nominal).pack(side="left", padx=(SPACE.sm, 0))
        self.productive_resize_controls.pack_forget()
        details_data = rounded_section(
            details,
            "Datos del pedido",
            pady=(0, SPACE.sm),
        )
        tk.Label(details_data, text="Origen", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 10)).pack(anchor="w")
        self.source_value = tk.StringVar(value="Stock")
        ttk.Combobox(details_data, textvariable=self.source_value, values=("Pedido", "Stock", "Relleno"), state="readonly").pack(fill="x", pady=(SPACE.xs, SPACE.sm))
        self.client_value = tk.StringVar()
        self.order_value = tk.StringVar()
        tk.Label(details_data, text="Cliente", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 10)).pack(anchor="w")
        ttk.Entry(details_data, textvariable=self.client_value).pack(fill="x", pady=(SPACE.xs, SPACE.sm))
        tk.Label(details_data, text="N.º de pedido", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 10)).pack(anchor="w")
        ttk.Entry(details_data, textvariable=self.order_value).pack(fill="x", pady=(SPACE.xs, 0))
        self.rotation_allowed = tk.BooleanVar(value=False)
        tk.Checkbutton(details_data, text="Autorizar rotación 90°", variable=self.rotation_allowed, background=COLORS.panel_elevated, foreground=COLORS.text, activebackground=COLORS.panel_elevated, activeforeground=COLORS.text, selectcolor=COLORS.wine).pack(anchor="w", pady=(SPACE.sm, SPACE.xs))
        ttk.Button(details_data, text="Aplicar datos", command=lambda *a, _fn=self.apply_details: _fn(*a), style="Plancha.Secondary.TButton", padding=(SPACE.sm, SPACE.xs)).pack(fill="x")
        actions = rounded_section(
            details,
            "Acciones del diseño",
            pady=(0, SPACE.sm),
        )
        ttk.Button(actions, text="Rotar", command=lambda *a, _fn=self.rotate_selected: _fn(*a), style="Plancha.Secondary.TButton", padding=(SPACE.sm, SPACE.xs)).pack(fill="x")
        self.lock_button = ttk.Button(actions, text="Bloquear posición", command=lambda *a, _fn=self.toggle_lock: _fn(*a), style="Plancha.Secondary.TButton")
        self.lock_button.configure(padding=(SPACE.sm, SPACE.xs))
        self.lock_button.pack(fill="x", pady=(SPACE.xs, 0))
        ttk.Button(actions, text="Eliminar diseño", command=lambda *a, _fn=self.delete_selected: _fn(*a), style="Plancha.Danger.TButton", padding=(SPACE.sm, SPACE.xs)).pack(fill="x", pady=(SPACE.xs, 0))
        ttk.Label(details, text="Los originales no se modifican.", background=COLORS.panel, foreground=COLORS.muted, wraplength=290).pack(side="bottom", anchor="w", padx=SPACE.sm, pady=SPACE.sm)
        self._build_approval_panel(approval)

    # Aprobación ---------------------------------------------------------
    def _build_approval_panel(self, parent):
        tk.Label(parent, text="APROBACIÓN", background=COLORS.panel, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 13, "bold")).pack(anchor="w", padx=14, pady=(16, 5))
        tk.Label(parent, text="La vista previa orienta al cliente. La aprobación siempre se registra de forma explícita.", background=COLORS.panel, foreground=COLORS.muted, justify="left", wraplength=235, font=(UI_FONT, 10)).pack(anchor="w", padx=14)
        self.approval_text = tk.StringVar(value="Guardá la plancha para iniciar su aprobación.")
        tk.Label(parent, textvariable=self.approval_text, background=COLORS.panel, foreground=COLORS.text, justify="left", wraplength=235, font=(UI_FONT, 10)).pack(anchor="w", padx=14, pady=(14, 10))
        ttk.Button(parent, text="Generar vista previa", command=lambda *a, _fn=self.export_preview: _fn(*a), style="Plancha.Secondary.TButton").pack(fill="x", padx=14)
        ttk.Button(parent, text="Guardar vista en pedido", command=lambda *a, _fn=self.save_preview_in_order: _fn(*a), style="Plancha.Secondary.TButton").pack(fill="x", padx=14, pady=(6, 0))
        ttk.Button(parent, text="Abrir vista previa", command=lambda *a, _fn=self.open_approval_preview: _fn(*a), style="Plancha.Secondary.TButton").pack(fill="x", padx=14, pady=(6, 0))
        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=14, pady=12)
        ttk.Button(parent, text="Marcar como aprobada", command=lambda: self.decide_approval(True), style="Plancha.Primary.TButton").pack(fill="x", padx=14)
        ttk.Button(parent, text="Solicitar cambios", command=lambda: self.decide_approval(False), style="Plancha.Secondary.TButton").pack(fill="x", padx=14, pady=(6, 0))
        tk.Label(parent, text="Al aprobar se confirma diseño, cantidad, material, tamaño y distribución de esta plancha.", background=COLORS.panel, foreground=COLORS.muted, justify="left", wraplength=235, font=(UI_FONT, 10)).pack(anchor="w", padx=14, pady=(14, 0))
        self.refresh_approval_panel()

    def refresh_approval_panel(self):
        if not hasattr(self, "approval_text"):
            return
        if not self.database or not self.plancha_id:
            self.approval_text.set("Estado: Borrador\nGuardá el proyecto para solicitar aprobación.")
            return
        plancha = self.database.plancha_project(self.plancha_id) or {}
        status = plancha.get("approval_status") or "Borrador"
        preview = plancha.get("approval_preview_path") or "Sin vista previa"
        requested = (plancha.get("approval_requested_at") or "-").replace("T", " ")
        note = plancha.get("approval_note") or "Sin notas"
        self.approval_text.set(
            f"Estado: {status}\nVista: {Path(preview).name if preview != 'Sin vista previa' else preview}\n"
            f"Solicitada: {requested}\nNota: {note}"
        )

    def open_approval_preview(self):
        if not self.database or not self.plancha_id:
            messagebox.showinfo("Aprobación", "Todavía no hay una vista previa asociada a esta plancha.", parent=self)
            return
        plancha = self.database.plancha_project(self.plancha_id) or {}
        path = Path(plancha.get("approval_preview_path") or "")
        if not path.exists():
            messagebox.showinfo("Aprobación", "Todavía no se generó una vista previa guardada.", parent=self)
            return
        try:
            os.startfile(str(path))
        except OSError as error:
            messagebox.showerror("Aprobación", f"No se pudo abrir la vista previa: {error}", parent=self)

    def decide_approval(self, approved: bool):
        if not self.database or not self.plancha_id:
            messagebox.showwarning("Aprobación", "Guardá el proyecto antes de registrar la decisión del cliente.", parent=self)
            return
        plancha = self.database.plancha_project(self.plancha_id) or {}
        if not plancha.get("approval_preview_path"):
            messagebox.showwarning("Aprobación", "Generá la vista previa antes de registrar la decisión.", parent=self)
            return
        title = "Confirmar aprobación" if approved else "Registrar cambios"
        question = "¿El cliente aprobó diseño, cantidad, material, tamaño y distribución?" if approved else "Indicá los cambios solicitados por el cliente (opcional):"
        if approved and not messagebox.askyesno(title, question, parent=self):
            return
        note = "" if approved else (simpledialog.askstring(title, question, parent=self) or "")
        self.database.decide_plancha_approval(self.plancha_id, approved, note)
        self._sync_open_order_after_approval()
        self.refresh_approval_panel()
        self.refresh_printing_panel()
        self.status_message("Plancha aprobada. Ya se puede generar el PNG final." if approved else "Se registraron cambios solicitados para esta plancha.")

    def _sync_open_order_after_approval(self):
        """Evita que un autoguardado abierto vuelva a un estado anterior."""
        if not self.database or not self.order_id or not hasattr(self.app, "order_tabs"):
            return
        tab = self.app.order_tabs.get(int(self.order_id))
        order = self.database.order(int(self.order_id))
        if not tab or not order or not hasattr(tab, "order_values"):
            return
        status_value = tab.order_values.get("status")
        if status_value and status_value.get() != order["status"]:
            status_value.set(order["status"])
        if hasattr(self.app, "render_order_workspace"):
            self.app.render_order_workspace(tab)

    # Impresión directa --------------------------------------------------
    def _build_printing_panel(self, parent):
        tk.Label(parent, text="IMPRESIÓN", background=COLORS.panel, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 13, "bold")).pack(anchor="w", padx=14, pady=(16, 5))
        tk.Label(parent, text="Configuración fija de producción", background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 10)).pack(anchor="w", padx=14)
        self.print_config_text = tk.StringVar()
        tk.Label(parent, textvariable=self.print_config_text, background=COLORS.panel, foreground=COLORS.text, justify="left", wraplength=235, font=(UI_FONT, 10)).pack(anchor="w", padx=14, pady=(7, 10))
        ttk.Button(parent, text="Configurar impresora", command=lambda *a, _fn=self.configure_printer: _fn(*a), style="Plancha.Secondary.TButton").pack(fill="x", padx=14)
        self.print_state_text = tk.StringVar(value="Estado: No lista")
        tk.Label(parent, textvariable=self.print_state_text, background=COLORS.panel, foreground=COLORS.text, justify="left", wraplength=235, font=(UI_FONT, 10)).pack(anchor="w", padx=14, pady=(14, 7))
        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=14, pady=(0, 10))
        ttk.Button(parent, text="Vista previa", command=lambda *a, _fn=self.show_print_preview: _fn(*a), style="Plancha.Secondary.TButton").pack(fill="x", padx=14)
        ttk.Button(parent, text="Imprimir", command=lambda *a, _fn=self.queue_current_print: _fn(*a), style="Plancha.Primary.TButton").pack(fill="x", padx=14, pady=(6, 0))
        ttk.Button(parent, text="Reimprimir", command=lambda *a, _fn=self.reprint_current: _fn(*a), style="Plancha.Secondary.TButton").pack(fill="x", padx=14, pady=(6, 0))
        ttk.Button(parent, text="Cancelar impresión", command=lambda *a, _fn=self.cancel_current_print: _fn(*a), style="Plancha.Danger.TButton").pack(fill="x", padx=14, pady=(6, 0))
        ttk.Button(parent, text="Marcar como impresa", command=lambda *a, _fn=self.mark_current_printed: _fn(*a), style="Plancha.Secondary.TButton").pack(fill="x", padx=14, pady=(6, 0))
        ttk.Button(parent, text="Confirmar terminación", command=lambda *a, _fn=self.confirm_finished: _fn(*a), style="Plancha.Secondary.TButton").pack(fill="x", padx=14, pady=(6, 0))
        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=14, pady=12)
        tk.Label(parent, text="COLA DE IMPRESIÓN", background=COLORS.panel, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 11, "bold")).pack(anchor="w", padx=14)
        self.print_queue_text = tk.StringVar()
        tk.Label(parent, textvariable=self.print_queue_text, background=COLORS.panel, foreground=COLORS.muted, justify="left", wraplength=235, font=(UI_FONT, 10)).pack(anchor="w", padx=14, pady=(4, 7))
        queue_actions = tk.Frame(parent, background=COLORS.panel)
        queue_actions.pack(fill="x", padx=14)
        ttk.Button(queue_actions, text="Siguiente", command=lambda *a, _fn=self.process_next_print_job: _fn(*a), style="Plancha.Secondary.TButton").pack(side="left", fill="x", expand=True)
        ttk.Button(queue_actions, text="Imprimir todas", command=lambda *a, _fn=self.print_all_queued: _fn(*a), style="Plancha.Primary.TButton").pack(side="left", fill="x", expand=True, padx=5)
        self.pause_queue_button = ttk.Button(queue_actions, text="Pausar", command=lambda *a, _fn=self.toggle_print_queue: _fn(*a), style="Plancha.Secondary.TButton")
        self.pause_queue_button.pack(side="left", fill="x", expand=True)
        ttk.Button(parent, text="Reintentar último error", command=lambda *a, _fn=self.reprint_current: _fn(*a), style="Plancha.Secondary.TButton").pack(fill="x", padx=14, pady=(8, 0))
        ttk.Button(parent, text="Ver historial", command=lambda *a, _fn=self.show_print_history: _fn(*a), style="Plancha.Secondary.TButton").pack(fill="x", padx=14, pady=(8, 0))
        self.refresh_printing_panel()

    def _linked_order_id(self) -> int | None:
        if self.order_id:
            return int(self.order_id)
        for item in self.project.items:
            value = str(item.order_number or "").strip()
            if value.isdigit():
                self.order_id = int(value)
                return self.order_id
        return None

    def _current_print_config(self) -> dict:
        if not self.database:
            return {"printer_name": "", "paper": "A4", "orientation": "Vertical", "scale": 97.27, "quality": "Alta", "color": "Color", "copies": 1}
        return self.database.printing_config()

    def _print_role(self) -> str:
        """Hasta que exista el módulo de usuarios, la sesión local es administrador."""
        return getattr(self.app, "current_role", "Administrador")

    def refresh_printing_panel(self):
        if not hasattr(self, "print_config_text"):
            return
        config = self._current_print_config()
        from app.printing.windows_print import printer_status

        printer = config.get("printer_name") or "Sin impresora configurada"
        available, availability = printer_status(config.get("printer_name") or "")
        availability = availability if config.get("printer_name") else "Pendiente de configurar"
        
        # Mostrar resumen de configuración guardada
        if self._load_devmode():
            format_info = config.get("devmode_summary", "Configurada según Epson")
        else:
            format_info = "Sin configurar"
        
        self.print_config_text.set(
            f"Impresora: {printer}\nEstado: {availability}\n"
            f"Configuración: {format_info}\n"
            f"Copias: {int(config.get('copies', 1) or 1)}"
        )
        plancha_status = "No lista"
        error = ""
        if self.database and self.plancha_id:
            saved = self.database.plancha_project(self.plancha_id)
            if saved:
                plancha_status = saved.get("print_status") or plancha_status
                error = saved.get("print_error") or ""
        extra = f"\nDetalle: {error}" if error else ""
        self.print_state_text.set(f"Estado de esta plancha: {plancha_status}{extra}")
        if self.database:
            counts = self.database.print_queue_counts()
            paused = " · Pausada" if self.print_queue_paused else ""
            self.print_queue_text.set(
                f"Pendientes: {counts['Pendiente']} · Enviando: {counts['Enviando a impresora']}\n"
                f"En cola: {counts['En cola']} · Impresas: {counts['Impresa']}\n"
                f"Con error: {counts['Error de impresión']}{paused}"
            )
        if hasattr(self, "pause_queue_button"):
            self.pause_queue_button.configure(text="Reanudar" if self.print_queue_paused else "Pausar")
        if hasattr(self.app, "refresh_orders"):
            self.app.refresh_orders()
        if hasattr(self.app, "refresh_production"):
            self.app.refresh_production()

    def _load_devmode(self) -> bytes | None:
        """Recupera el DEVMODE guardado en la sesión o en la base de datos."""
        if hasattr(self, "_devmode_bytes") and self._devmode_bytes:
            return self._devmode_bytes
        if not self.database:
            return None
        config = self._current_print_config()
        encoded = config.get("devmode_b64") or ""
        if encoded:
            try:
                return base64.b64decode(encoded)
            except Exception:
                pass
        return None

    def _save_devmode(self, devmode: bytes, summary: str | None = None) -> None:
        """Persiste el DEVMODE elegido en la sesión y en la base de datos."""
        self._devmode_bytes = devmode
        if self.database:
            encoded = base64.b64encode(devmode).decode()
            config = self._current_print_config()
            printer = config.get("printer_name") or ""
            copies = config.get("copies", 1)
            save_data = {"copies": copies, "devmode_b64": encoded}
            if summary:
                save_data["devmode_summary"] = summary
            self.database.save_printing_config(printer, save_data)

    def configure_printer(self):
        if not self.database:
            return
        if self._print_role() != "Administrador":
            messagebox.showerror("Configuración de impresión", "Solo un administrador puede cambiar la impresora de producción.", parent=self)
            return
        from app.printing.windows_print import default_printer, list_printers, open_print_dialog

        printers = list_printers()
        if not printers:
            messagebox.showerror("Configuración de impresión", "No se detectaron impresoras disponibles en Windows.", parent=self)
            return
        
        config = self._current_print_config()
        saved_printer = (config.get("printer_name") or "").strip()
        printer_name = saved_printer or default_printer() or printers[0]
        
        # Obtener el HWND de la ventana para que el diálogo sea modal
        try:
            parent_hwnd = int(self.wm_frame(), 16)
        except Exception:
            parent_hwnd = 0
        
        # Abrir directamente el diálogo estándar de configuración de impresión de Windows
        devmode_bytes = open_print_dialog(printer_name, parent_hwnd)
        
        if devmode_bytes is None:
            # Usuario canceló el diálogo
            self.status_message("Configuración de impresora cancelada.")
            return
        
        # Guardar la configuración DEVMODE con resumen genérico
        self._save_devmode(devmode_bytes, "Configurada según preferencias")
        self.database.save_printing_config(printer_name, {"copies": config.get("copies", 1)})
        
        self.refresh_printing_panel()
        self.status_message("Configuración de impresora guardada.")

    def status_message(self, message: str):
        """Envía un mensaje al estado general si el editor se abrió desde Doccione."""
        if hasattr(self.app, "status"):
            self.app.status.set(message)

    def _prepare_temporary_print_version(self) -> bool:
        """Crea una versión A4 temporal cuando se necesita imprimir un borrador."""
        already_ready = (
            self.plancha_id and self.project_path and Path(self.project_path).exists()
            and self.final_png_path and Path(self.final_png_path).exists()
        )
        if already_ready:
            return True
        if not messagebox.askyesno(
            "Imprimir borrador",
            "La plancha no fue guardada como proyecto.\n\n"
            "¿Querés generar una versión temporal A4 a 300 DPI para imprimir ahora? "
            "No modifica los archivos originales ni reemplaza un proyecto guardado.",
            parent=self,
        ):
            return False
        try:
            root = Path(__file__).resolve().parents[2]
            folder = root / "outputs" / "impresiones_temporales"
            folder.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
            temporary_project = folder / f"plancha_temporal_{stamp}.doccione-plancha.json"
            temporary_png = folder / f"plancha_temporal_{stamp}.png"
            self.project.save(temporary_project)
            sheet = self.render_sheet(preview=False)
            sheet.save(temporary_png, "PNG", dpi=(300, 300), compress_level=3)
            order_id = self._linked_order_id()
            material = ""
            if order_id:
                material = (self.database.order(order_id) or {}).get("material") or ""
            self.plancha_id = self.database.save_plancha_project(
                order_id,
                f"Impresión temporal {stamp}",
                material,
                json.dumps(self.project.to_dict(), ensure_ascii=False),
                str(temporary_project),
                self.plancha_id,
            )
            self.project_path = str(temporary_project)
            self.final_png_path = str(temporary_png)
            self.database.set_plancha_final_png(self.plancha_id, self.final_png_path)
            self.refresh_printing_panel()
            self.status_message("Se generó una versión temporal A4 para imprimir el borrador.")
            return True
        except Exception as error:
            messagebox.showerror("Imprimir borrador", f"No se pudo generar la versión temporal: {error}", parent=self)
            return False

    def _print_validation_error(self) -> str | None:
        if not self.database:
            return "No se pudo acceder a la configuración de impresión."
        if not self.plancha_id or not self.project_path or not Path(self.project_path).exists():
            return "La plancha todavía no fue guardada."
        if not self.final_png_path or not Path(self.final_png_path).exists():
            return "El archivo final todavía no fue generado."
        from app.printing.windows_print import printer_status, validate_a4_png

        valid, message = validate_a4_png(self.final_png_path)
        if not valid:
            return message
        margin = self.project.margin_cm
        for item in self.project.items:
            if (item.x_cm < margin - 0.001 or item.y_cm < margin - 0.001 or
                    item.x_cm + item.width_cm > A4_WIDTH_CM - margin + 0.001 or
                    item.y_cm + item.height_cm > A4_HEIGHT_CM - margin + 0.001):
                return "Hay elementos fuera del área imprimible."
        order_id = self._linked_order_id()
        if order_id and not self.database.order(order_id):
            return "La plancha no está asociada a un pedido."
        order = self.database.order(order_id) if order_id else None
        if order and order["status"] not in {"Aprobado", "En diseño", "Listo para plancha"}:
            return "El estado del pedido no permite impresión."
        config = self._current_print_config()
        if config.get("paper") != "A4" or config.get("orientation") != "Vertical" or int(config.get("scale", 0)) != 100:
            return "La configuración fija no coincide con A4 vertical y escala 100 %."
        available, message = printer_status(config.get("printer_name") or "")
        if not available:
            return message
        return None

    def show_print_preview(self):
        if not self.project.items:
            return
        try:
            from PIL import ImageTk

            sheet = self.render_sheet(preview=False)
            sheet.thumbnail((520, 690))
            dialog = tk.Toplevel(self)
            dialog.title("Vista previa de impresión")
            dialog.configure(background="#111314")
            dialog.transient(self)
            image = ImageTk.PhotoImage(sheet)
            tk.Label(dialog, image=image, background="#111314").pack(padx=14, pady=14)
            dialog.image = image
            tk.Label(dialog, text="Vista final A4 · 300 DPI · sin guías ni marcas", background="#111314", foreground="#e7d3c4").pack(pady=(0, 14))
        except Exception as error:
            messagebox.showerror("Vista previa", f"No se pudo generar la vista previa: {error}", parent=self)

    def send_to_print_queue(self, silent: bool = False):
        """Registra el PNG final para que Producción decida cuándo enviarlo a Windows."""
        if self._print_role() not in {"Administrador", "Operario"}:
            if not silent:
                messagebox.showerror("Cola de impresión", "Tu perfil no tiene permiso para enviar planchas a impresión.", parent=self)
            return
        if not self.database:
            if not silent:
                messagebox.showerror("Cola de impresión", "No se pudo acceder a la base de datos de Producción.", parent=self)
            return
        if not self.plancha_id or not self.final_png_path or not Path(self.final_png_path).exists():
            if not silent:
                should_prepare = messagebox.askyesno(
                    "Preparar para impresión",
                    "Antes de enviar a la cola, la plancha necesita un proyecto guardado y su PNG final.\n\n"
                    "¿Querés prepararlos ahora?",
                    parent=self,
                )
                if not should_prepare:
                    return
                if not self.plancha_id:
                    self.save_project()
                if not self.plancha_id:
                    return
                if not self.final_png_path or not Path(self.final_png_path).exists():
                    self.export_final()
                if not self.final_png_path or not Path(self.final_png_path).exists():
                    return
            else:
                return
        error = self._print_validation_error()
        if error:
            if not silent:
                messagebox.showerror("No se puede enviar a cola", error, parent=self)
            return
        config = self._current_print_config()
        self.database.create_print_job(
            self.plancha_id, os.environ.get("USERNAME", "Operario"), config["printer_name"], config,
            max(1, int(config.get("copies", 1) or 1)), self.final_png_path,
        )
        if hasattr(self.app, "refresh_production"):
            self.app.refresh_production()
        self.status_message("PNG final enviado a la cola de impresión. Abrí Producción para enviarlo a la impresora.")
        if not silent:
            messagebox.showinfo("Cola de impresión", "Plancha agregada a la cola. La impresión se gestiona desde Producción.", parent=self)

    def queue_current_print(self):
        if self._print_role() not in {"Administrador", "Operario"}:
            messagebox.showerror("Imprimir", "Tu perfil no tiene permiso para imprimir.", parent=self)
            return
        if not self._prepare_temporary_print_version():
            return
        error = self._print_validation_error()
        if error:
            messagebox.showerror("No se puede imprimir", error, parent=self)
            return
        config = self._current_print_config()
        job_id = self.database.create_print_job(
            self.plancha_id, os.environ.get("USERNAME", "Operario"), config["printer_name"], config,
            max(1, int(config.get("copies", 1) or 1)), self.final_png_path,
        )
        self.status_message("Plancha agregada a la cola de impresión.")
        self.refresh_printing_panel()
        self.process_next_print_job()

    def reprint_current(self):
        if self._print_role() not in {"Administrador", "Operario"}:
            messagebox.showerror("Reimprimir", "Tu perfil no tiene permiso para reimprimir.", parent=self)
            return
        if not self.database or not self.plancha_id:
            messagebox.showerror("Reimprimir", "La plancha todavía no fue guardada.", parent=self)
            return
        previous = self.database.latest_print_job(self.plancha_id, ("Impresa", "En cola", "Error de impresión", "Cancelada"))
        if not previous:
            messagebox.showinfo("Reimprimir", "Todavía no hay una impresión previa de esta plancha.", parent=self)
            return
        if not Path(previous["final_png_path"]).exists():
            messagebox.showerror("Reimprimir", "No se encontró el archivo final de la impresión anterior.", parent=self)
            return
        config = json.loads(previous["configuration_json"])
        job_id = self.database.create_print_job(
            self.plancha_id, os.environ.get("USERNAME", "Operario"), previous["printer_name"], config,
            previous["copies"], previous["final_png_path"], parent_job_id=previous["id"],
        )
        self.status_message(f"Reimpresión #{job_id} agregada con la configuración original.")
        self.refresh_printing_panel()
        self.process_next_print_job()

    def process_next_print_job(self):
        if not self.database or self.print_queue_paused or self.active_print_job_id:
            return
        job = self.database.next_print_job()
        if not job:
            self.refresh_printing_panel()
            return
        self.active_print_job_id = job["id"]
        self.database.update_print_job(job["id"], "Enviando a impresora")
        self.refresh_printing_panel()

        def work():
            from app.printing.windows_print import print_png_strip
            # Cargar el DEVMODE guardado desde la configuración de la base de datos
            devmode_bytes = None
            config_json = job.get("configuration_json", "{}")
            try:
                config = json.loads(config_json) if isinstance(config_json, str) else config_json
                devmode_b64 = config.get("devmode_b64") or config.get("devmode")
                if devmode_b64:
                    devmode_bytes = base64.b64decode(devmode_b64)
            except Exception:
                pass
            # Usar print_png_strip con la configuración del driver guardada
            result = print_png_strip(
                job["printer_name"],
                job["final_png_path"],
                job["copies"],
                f"Doccione · Plancha {job['plancha_id']}",
                devmode_bytes=devmode_bytes
            )
            self.after(0, lambda: self._finish_print_job(job["id"], result))

        self.print_worker = threading.Thread(target=work, daemon=True)
        self.print_worker.start()

    def _finish_print_job(self, job_id: int, result):
        self.active_print_job_id = None
        if result.success:
            self.database.update_print_job(job_id, "En cola", result.message, result.spool_job_id)
            self.status_message("Trabajo enviado correctamente a la cola de impresión.")
        else:
            self.database.update_print_job(job_id, "Error de impresión", result.message)
            self.status_message("La impresión no se pudo enviar. Revisá el detalle en Impresión.")
        self.refresh_printing_panel()
        if not self.print_queue_paused:
            self.after(80, self.process_next_print_job)

    def print_all_queued(self):
        self.print_queue_paused = False
        self.refresh_printing_panel()
        self.process_next_print_job()

    def toggle_print_queue(self):
        self.print_queue_paused = not self.print_queue_paused
        self.refresh_printing_panel()
        if not self.print_queue_paused:
            self.process_next_print_job()

    def cancel_current_print(self):
        if not self.database or not self.plancha_id:
            return
        if self._print_role() not in {"Administrador", "Operario"}:
            messagebox.showerror("Cancelar impresión", "Tu perfil no tiene permiso para cancelar impresiones.", parent=self)
            return
        job = self.database.latest_print_job(self.plancha_id, ("Pendiente", "Enviando a impresora", "En cola"))
        if not job:
            messagebox.showinfo("Cancelar impresión", "No hay una impresión pendiente para esta plancha.", parent=self)
            return
        if job["status"] == "En cola":
            from app.printing.windows_print import cancel_spool_job
            result = cancel_spool_job(job["printer_name"], job.get("spool_job_id"))
            if not result.success:
                messagebox.showerror("Cancelar impresión", result.message, parent=self)
                return
        self.database.cancel_print_job(job["id"])
        self.active_print_job_id = None if self.active_print_job_id == job["id"] else self.active_print_job_id
        self.refresh_printing_panel()
        self.status_message("Impresión cancelada.")

    def mark_current_printed(self):
        if not self.database or not self.plancha_id:
            return
        if self._print_role() not in {"Administrador", "Operario"}:
            messagebox.showerror("Marcar como impresa", "Tu perfil no tiene permiso para registrar impresiones.", parent=self)
            return
        job = self.database.latest_print_job(self.plancha_id, ("En cola",))
        if not job:
            messagebox.showinfo("Marcar como impresa", "La plancha debe estar primero en la cola de impresión.", parent=self)
            return
        if not messagebox.askyesno("Marcar como impresa", "Confirmá que la impresora terminó correctamente esta plancha.", parent=self):
            return
        self.database.update_print_job(job["id"], "Impresa", "Confirmada tras salida de impresora.")
        self.refresh_printing_panel()
        self._notify_production_change()
        self.status_message("Plancha marcada como impresa y registrada en el historial.")

    def confirm_finished(self):
        """Confirma terminación de la selección, o de todo lo impreso si no hay selección."""
        if not self.database or not self.plancha_id:
            messagebox.showinfo("Terminación", "Guardá la plancha antes de confirmar terminación.", parent=self)
            return
        selected = sorted(self.selected_ids) if self.selected_ids else None
        scope = f"{len(selected)} elemento(s) seleccionados" if selected else "todas las unidades impresas de la plancha"
        if not messagebox.askyesno(
            "Confirmar terminación", f"¿Confirmar como terminadas {scope}?\n\nEsta acción no entrega ni cobra el pedido.", parent=self,
        ):
            return
        changed = self.database.confirm_plancha_finished_assignments(self.plancha_id, selected)
        if changed:
            self.status_message(f"Se confirmaron {changed} unidad(es) terminadas.")
        else:
            messagebox.showinfo(
                "Terminación", "No había unidades impresas pendientes de terminar en ese alcance.", parent=self,
            )
        self.refresh_printing_panel()
        self._notify_production_change()

    def _notify_production_change(self):
        """Actualiza las vistas de Producción abiertas sin acoplar el editor."""
        owner = self
        while owner is not None:
            callback = getattr(owner, "notify_production_change", None)
            if callable(callback):
                callback()
                return
            owner = getattr(owner, "master", None)

    def show_print_history(self):
        if not self.database or not self.plancha_id:
            messagebox.showinfo("Historial de impresión", "Guardá la plancha para consultar su historial.", parent=self)
            return
        history = self.database.print_history(self.plancha_id)
        if not history:
            messagebox.showinfo("Historial de impresión", "Todavía no hay intentos registrados para esta plancha.", parent=self)
            return
        lines = []
        for event in history[:12]:
            lines.append(f"{event['created_at']} · {event['status']} · {event['printer_name']}\n{event['message'] or 'Sin detalle'}")
        messagebox.showinfo("Historial de impresión", "\n\n".join(lines), parent=self)

    def cm_to_px(self, value: float) -> float:
        return value * self.SCALE * self.zoom

    def toggle_hitboxes(self):
        """Alterna las cajas de trabajo sin cambiar el diseño ni la exportación."""
        self.show_hitboxes = not self.show_hitboxes
        if hasattr(self, "view_mode_button"):
            self.view_mode_button.configure(text="Vista técnica" if self.show_hitboxes else "Vista normal")
        self.hitbox_button.configure(text="⌗" if self.show_hitboxes else "◌")
        self.render()

    def _set_preview_zoom(self, value: float, *, auto_fit: bool) -> None:
        """Modifica sólo la escala de pantalla; nunca cm ni geometría."""
        self.zoom = min(2.5, max(0.25, value))
        self.auto_fit_view = auto_fit
        self.zoom_label.set(f"{self.zoom * 100:.0f}%")
        self.render()

    def change_preview_zoom(self, delta: float) -> None:
        self._set_preview_zoom(self.zoom + delta, auto_fit=False)

    def fit_sheet_to_view(self) -> None:
        """Ajusta la hoja A4 completa al área disponible conservando 21:29,7."""
        if not hasattr(self, "canvas"):
            return
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if width <= 2 or height <= 2:
            self.after_idle(self.fit_sheet_to_view)
            return
        scale = min((width - 60) / (A4_WIDTH_CM * self.SCALE), (height - 60) / (A4_HEIGHT_CM * self.SCALE))
        self._set_preview_zoom(scale, auto_fit=True)

    def _on_preview_canvas_resize(self, _event=None) -> None:
        if not self.auto_fit_view:
            return
        if getattr(self, "_fit_after", None):
            self.after_cancel(self._fit_after)
        self._fit_after = self.after(50, self.fit_sheet_to_view)

    def toggle_experimental_packing(self):
        """Activa o desactiva el motor geométrico paralelo para revisión."""
        self.use_experimental_packing = not self.use_experimental_packing
        self.experimental_packing_button.configure(text="⌘" if not self.use_experimental_packing else "⛶")
        self.status_message(
            "Motor geométrico experimental activado." if self.use_experimental_packing else "Motor geométrico experimental desactivado."
        )
        if not self.preserve_layout:
            self.optimize()

    def px_to_cm(self, value: float) -> float:
        return value / (self.SCALE * self.zoom)

    def zoom_with_wheel(self, event):
        """Alt + rueda acerca o aleja solo la vista del constructor."""
        factor = 1.12 if event.delta > 0 else 1 / 1.12
        new_zoom = min(2.5, max(0.5, self.zoom * factor))
        if abs(new_zoom - self.zoom) < 0.001:
            return "break"
        self.zoom = new_zoom
        self.auto_fit_view = False
        self.zoom_label.set(f"{self.zoom * 100:.0f}%")
        if not self.zoom_render_pending:
            self.zoom_render_pending = True
            self.after(16, self.flush_zoom_render)
        return "break"

    def flush_zoom_render(self):
        self.zoom_render_pending = False
        if self.winfo_exists():
            self.render()

    def pan_horizontally_with_wheel(self, event):
        """Ctrl + rueda desplaza la vista lateralmente, sin tocar diseños."""
        direction = -1 if event.delta > 0 else 1
        self.canvas.xview_scroll(direction * 2, "units")
        return "break"

    def snapshot(self):
        self.history.append(copy.deepcopy(self.project.to_dict()))
        self.history = self.history[-40:]
        self.future.clear()
        # El banco abierto se persiste de forma diferida. No genera PNG ni
        # reempaqueta: sólo conserva el snapshot editable para el próximo inicio.
        schedule = getattr(self.app, "schedule_plancha_workspace_save", None)
        if self.project.items and callable(schedule):
            schedule()

    def restore(self, data: dict):
        self.project = PlanchaProject(
            [PlanchaItem.from_dict(item) for item in data["items"]], data["margin_cm"], data["gap_cm"],
            data.get("layout_mode", self.layout_mode), data.get("workspace_format", "a4"),
            data.get("project_type", "legacy"), data.get("manual_from_mixed", False),
        )
        self.selected_id = None
        self.selected_ids.clear()
        self.render()

    def undo(self):
        if len(self.history) < 2:
            return
        self.future.append(self.history.pop())
        self.restore(copy.deepcopy(self.history[-1]))

    def redo(self):
        if not self.future:
            return
        data = self.future.pop()
        self.history.append(copy.deepcopy(data))
        self.restore(data)

    def selected_item(self) -> PlanchaItem | None:
        return next((item for item in self.project.items if item.item_id == self.selected_id), None)

    def selected_size_cm(self) -> float:
        """5 cm representa el máximo real para cinco filas A4."""
        try:
            visible_size = int(str(self.size_value.get()).replace("cm", "").strip())
        except ValueError:
            visible_size = 5
        return min(MAX_SIZE_CM, max(0.5, float(visible_size)))

    def size_label_for(self, item: PlanchaItem) -> str:
        if item.nominal_size_cm is not None:
            return f"{item.nominal_size_cm:g}cm"
        longest_side = max(item.width_cm, item.height_cm)
        visible_size = 5 if longest_side <= FIVE_ROW_SIZE_CM + 0.02 else min(29, max(5, round(longest_side - SIZE_OFFSET_CM)))
        return f"{visible_size}cm"

    def render(self):
        self.project.keep_inside_print_area()
        self.canvas.delete("all")
        # La preview siempre representa la hoja física A4 completa. El formato
        # comercial sólo se indica con guías en la vista técnica.
        visible_height_cm = A4_HEIGHT_CM
        page_w, page_h = self.cm_to_px(A4_WIDTH_CM), self.cm_to_px(visible_height_cm)
        accent, workspace_fill = WORKSPACE_COLORS[self.project.workspace_format]
        self.canvas.configure(scrollregion=(0, 0, page_w + 60, page_h + 60))
        self.canvas.create_rectangle(25, 25, page_w + 25, page_h + 25, fill=COLORS.paper, outline=accent, width=3)
        if self.show_hitboxes:
            margin = self.cm_to_px(self.project.margin_cm)
            if margin:
                self.canvas.create_rectangle(25 + margin, 25 + margin, 25 + page_w - margin, 25 + page_h - margin, outline="#c9bbb0", dash=(3, 3))
            workspace_bottom = 25 + self.cm_to_px(self.project.workspace_bottom_cm)
            self.canvas.create_rectangle(25 + margin, 25 + margin, 25 + page_w - margin, workspace_bottom,
                                         fill=workspace_fill, outline=accent, width=2, tags=("workspace",))
            band_y = 25 + margin
            for band_height in self.project.production_band_heights()[:-1]:
                band_y += self.cm_to_px(band_height)
                self.canvas.create_line(25 + margin, band_y, 25 + page_w - margin, band_y,
                                        fill=accent, dash=(3, 3), tags=("workspace",))
            self.canvas.create_text(25 + margin + 7, 25 + margin + 7, anchor="nw", text=self.project.workspace_label.upper(),
                                    fill=accent, font=(IDENTITY_FONT, 9, "bold"), tags=("workspace",))
        for item in self.project.items:
            geometry = preview_geometry(item, self.current_project_index + 1)
            x1, y1 = 25 + self.cm_to_px(geometry["x_cm"]), 25 + self.cm_to_px(geometry["y_cm"])
            x2, y2 = x1 + self.cm_to_px(geometry["layout_width_cm"]), y1 + self.cm_to_px(geometry["layout_height_cm"])
            if self.show_hitboxes:
                selected = item.item_id in self.selected_ids
                outline = COLORS.wine_active if selected else (item.client_color if item.client else COLORS.border_strong)
                self.canvas.create_rectangle(x1, y1, x2, y2, fill="#FFFDF9", outline=outline, width=3 if selected else 2, tags=("item", item.item_id))
            render_w, render_h = self.cm_to_px(geometry["production_width_cm"]), self.cm_to_px(geometry["production_height_cm"])
            thumb = self.cached_thumbnail(
                item.path, max(10, int(render_w - 8)), max(10, int(render_h - 8)),
                item.rotation, item.remove_inner_white_border,
            )
            if thumb:
                self.canvas.create_image(25 + self.cm_to_px(geometry["design_x_cm"]) + render_w / 2,
                                         25 + self.cm_to_px(geometry["design_y_cm"]) + render_h / 2,
                                         image=thumb, tags=("item", item.item_id))
            else:
                self.canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2, text="Sin\nvista previa", fill="#252525", tags=("item", item.item_id))
        free = 100 - self.project.occupancy()
        legend = self.project.legend()
        pending = f"\nSobrantes pendientes: {len(self.pending_overflow)}" if self.pending_overflow else ""
        self.stats.set(f"A4 vertical · 21 × 29,7 cm\nMargen: {self.project.margin_cm:g} cm · Separación: {self.project.gap_cm:g} cm\nOcupación: {self.project.occupancy():.1f}%\nEspacio libre: {free:.1f}%\nStickers: {len(self.project.items)} · Vista: {self.zoom * 100:.0f}%{pending}")
        for widget in self.legend_frame.winfo_children():
            widget.destroy()
        for color, client, order, count in legend[:4]:
            tk.Label(self.legend_frame, text=f"● {client}" + (f" · pedido {order}" if order else "") + f" · {count}", background=COLORS.panel, foreground=color, anchor="w", wraplength=215, font=(UI_FONT, 9)).pack(fill="x")
        item = self.selected_item()
        if len(self.selected_ids) > 1:
            self.selected_label.set(f"{len(self.selected_ids)} diseños seleccionados.\nLos controles editan el último diseño elegido.")
        else:
            self.selected_label.set(f"{item.name}\nCopia {item.copy_number} de {item.quantity} · {item.width_cm:g} × {item.height_cm:g} cm" if item else "Elegí un diseño de la plancha.")
        if item:
            nominal_text = f"{item.nominal_size_cm:g} cm" if item.nominal_size_cm is not None else "No registrado"
            production_min_text = f"{production_min_for_nominal(item.nominal_size_cm):.2f} cm" if item.nominal_size_cm is not None else "No registrado"
            production_max_text = f"{production_max_for_nominal(item.nominal_size_cm):.2f} cm" if item.nominal_size_cm is not None else "No registrado"
            bonus = expected_final_size(max(item.production_width_cm, item.production_height_cm)) - (item.nominal_size_cm or 0)
            self.selected_label.set(
                f"Diseño: {item.name}\n"
                f"Pedido: {item.order_number or (('#' + str(item.order_id)) if item.order_id else '—')}\n"
                f"Cliente: {item.client or '—'}\n"
                f"Trabajo: {item.order_job_title or (('#' + str(item.order_job_id)) if item.order_job_id else '—')}\n"
                f"Copia: {item.copy_number}\n"
                f"Tamaño nominal: {nominal_text}\n"
                f"{'Tamaño modificado en plancha\\n' if item.nominal_size_cm is not None and item.order_nominal_size_cm not in (None, item.nominal_size_cm) else ''}"
                f"Producción mínima: {production_min_text}\n"
                f"Máximo comercial: {production_max_text}\n"
                f"Producción usada: {item.production_width_cm:g} × {item.production_height_cm:g} cm\n"
                f"Hitbox: {item.reserved_width_cm:g} × {item.reserved_height_cm:g} cm\n"
                f"Final estimado (lado mayor): {expected_final_size(max(item.production_width_cm, item.production_height_cm)):.2f} cm\n"
                f"Extra estimado: {bonus:+.2f} cm · Rotación: {item.rotation}° · Página: {self.current_project_index + 1}"
            )
            self.size_value.set(self.size_label_for(item))
            self.quantity_value.set(item.quantity)
            self.source_value.set(item.source)
            self.client_value.set(item.client)
            self.order_value.set(item.order_number)
            self.rotation_allowed.set(item.rotation_allowed)
            self.lock_button.configure(text="Desbloquear posición" if item.locked else "Bloquear posición")

    def cached_thumbnail(
        self, path: str, width: int, height: int, rotation: int = 0, remove_inner_white_border: bool = False,
    ):
        now = time.monotonic()
        cached_mtime = self.thumbnail_mtime_cache.get(path)
        if cached_mtime and now - cached_mtime[1] < 1.0:
            modified = cached_mtime[0]
        else:
            try:
                modified = Path(path).stat().st_mtime
            except OSError:
                modified = -1.0
            self.thumbnail_mtime_cache[path] = (modified, now)
        key = (path, modified, width, height, rotation, remove_inner_white_border)
        thumbnail = self.thumbnail_cache.get(key)
        if thumbnail is None:
            thumbnail = load_visible_thumbnail(path, (width, height), rotation, remove_inner_white_border)
            if len(self.thumbnail_cache) >= 700:
                self.thumbnail_cache.popitem(last=False)
            self.thumbnail_cache[key] = thumbnail
        else:
            self.thumbnail_cache.move_to_end(key)
        return thumbnail

    def request_render(self):
        """Agrupa movimientos rápidos del mouse en un único repintado."""
        if not self.render_pending:
            self.render_pending = True
            self.after(16, self.flush_render)

    def flush_render(self):
        self.render_pending = False
        if self.winfo_exists():
            self.render()

    def move_item_preview(self, item: PlanchaItem, old_x_cm: float, old_y_cm: float) -> bool:
        """Mueve sólo el dibujo activo; el repintado completo queda para soltar.

        Reconstruir el canvas durante cada evento de mouse volvía a cargar la
        hoja, todas las imágenes, la leyenda y los campos laterales. Todos los
        objetos visuales de un sticker comparten su ``item_id`` como tag, así
        que Tk puede desplazarlos juntos en una única operación.
        """
        canvas = getattr(self, "canvas", None)
        move = getattr(canvas, "move", None)
        if not callable(move):
            return False
        delta_x = self.cm_to_px(item.x_cm - old_x_cm)
        delta_y = self.cm_to_px(item.y_cm - old_y_cm)
        if abs(delta_x) > 0.0001 or abs(delta_y) > 0.0001:
            move(item.item_id, delta_x, delta_y)
        return True

    def item_at(self, x: float, y: float) -> PlanchaItem | None:
        for item in reversed(self.project.items):
            left, top = 25 + self.cm_to_px(item.x_cm), 25 + self.cm_to_px(item.y_cm)
            if left <= x <= left + self.cm_to_px(item.width_cm) and top <= y <= top + self.cm_to_px(item.height_cm):
                return item
        return None

    def item_ids_in_area(self, left: float, top: float, right: float, bottom: float) -> set[str]:
        """Devuelve todos los stickers que tocan el rectángulo de selección."""
        left, right = sorted((left, right))
        top, bottom = sorted((top, bottom))
        selected = set()
        for item in self.project.items:
            item_left = 25 + self.cm_to_px(item.x_cm)
            item_top = 25 + self.cm_to_px(item.y_cm)
            item_right = item_left + self.cm_to_px(item.width_cm)
            item_bottom = item_top + self.cm_to_px(item.height_cm)
            if not (item_right < left or right < item_left
                    or item_bottom < top or bottom < item_top):
                selected.add(item.item_id)
        return selected

    def canvas_event_position(self, event) -> tuple[float, float]:
        return self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

    def click_canvas(self, event):
        self.canvas.focus_set()
        x, y = self.canvas_event_position(event)
        item = self.item_at(x, y)
        is_multi_select = bool(event.state & 0x0004)
        previous_selection = set(self.selected_ids)
        self.area_selection_start = None
        self.area_selection_rect = None
        if is_multi_select and item:
            if item.item_id in self.selected_ids:
                self.selected_ids.remove(item.item_id)
            else:
                self.selected_ids.add(item.item_id)
        elif item and item.item_id in self.selected_ids:
            pass
        else:
            self.selected_ids = {item.item_id} if item else set()
        self.selected_id = item.item_id if item else None
        if item:
            self.drag_offset = (x - 25 - self.cm_to_px(item.x_cm), y - 25 - self.cm_to_px(item.y_cm))
            self.drag_origin = (item.x_cm, item.y_cm)
            self.drag_band_index = self.band_for_item(item)
            self.request_render()
        else:
            self.drag_band_index = None
            self.area_selection_start = (x, y)
            self.area_selection_base = previous_selection if is_multi_select else set()
            self.render()

    def select_all_items(self):
        self.selected_ids = {item.item_id for item in self.project.items}
        self.selected_id = self.project.items[0].item_id if self.project.items else None
        self.render()

    def distribute_evenly(self):
        """Reparte horizontalmente los diseños de cada franja actual."""
        bands: dict[int, list[PlanchaItem]] = {}
        for item in self.project.items:
            if not item.locked:
                bands.setdefault(self.band_for_item(item), []).append(item)

        changed = False
        for items in bands.values():
            if len(items) < 2:
                continue
            items.sort(key=lambda item: item.x_cm)
            used_width = sum(item.width_cm for item in items)
            free_space = self.project.usable_width - used_width
            if free_space < 0:
                continue
            gap = free_space / (len(items) - 1)
            x = self.project.margin_cm
            for item in items:
                item.x_cm = round(x, 3)
                x += item.width_cm + gap
            changed = True

        if changed:
            self.snapshot()
            self.render()
            self.status_message("Diseños separados equitativamente por franja.")

    def copy_selected_items(self, _event=None):
        """Copia los stickers elegidos al portapapeles interno del editor."""
        selected = [
            item.to_dict() for item in self.project.items
            if item.item_id in self.selected_ids
        ]
        if not selected and self.selected_id:
            item = self.selected_item()
            selected = [item.to_dict()] if item else []
        self.sticker_clipboard = copy.deepcopy(selected)
        selected_ids = {item["item_id"] for item in selected}
        selected_items = [
            item for item in self.project.items if item.item_id in selected_ids
        ]
        bands = {self.band_for_item(item) for item in selected_items}
        self.clipboard_band_index = None
        if len(bands) == 1:
            band_index = next(iter(bands))
            band_ids = {
                item.item_id for item in self.project.items
                if self.band_for_item(item) == band_index
            }
            if selected_ids == band_ids:
                self.clipboard_band_index = band_index
        if selected:
            self.status_message(
                f"{len(selected)} diseño(s) copiado(s). Usá Ctrl+V para pegar y acomodar."
            )
        return "break"

    def paste_selected_items(self, _event=None):
        """Pega copias independientes y vuelve a optimizar la plancha."""
        if not self.sticker_clipboard:
            return "break"

        # La instantánea anterior permite deshacer todo el pegado de una vez.
        self.snapshot()
        group_ids: dict[str, str] = {}
        pasted: list[PlanchaItem] = []
        for source in self.sticker_clipboard:
            data = copy.deepcopy(source)
            original_group = str(data.get("group_id") or "")
            data["group_id"] = group_ids.setdefault(original_group, uuid.uuid4().hex)
            data.update({
                "item_id": uuid.uuid4().hex,
                "quantity": 1,
                "copy_number": 1,
                "locked": False,
            })
            pasted.append(PlanchaItem.from_dict(data))

        self.project.items.extend(pasted)
        self.selected_ids = {item.item_id for item in pasted}
        self.selected_id = pasted[-1].item_id
        copied_band = getattr(self, "clipboard_band_index", None)
        next_band = copied_band + 1 if copied_band is not None else None
        band_heights = self.project.production_band_heights()
        can_repeat_band = next_band is not None and next_band < len(band_heights)
        if can_repeat_band:
            source_top = self.project.margin_cm + sum(band_heights[:copied_band])
            target_top = self.project.margin_cm + sum(band_heights[:next_band])
            target_bottom = target_top + band_heights[next_band]
            # item_id cambia al pegar; la posición fuente se conserva por el
            # mismo orden en que se copió cada sticker.
            for item, source in zip(pasted, self.sticker_clipboard):
                item.y_cm = round(target_top + (float(source["y_cm"]) - source_top), 3)
                if item.y_cm < target_top or item.y_cm + item.height_cm > target_bottom + 0.0001:
                    can_repeat_band = False
                    break
        if can_repeat_band:
            # La franja se pega tal como fue armada (misma X y posiciones
            # relativas). No se reordena el resto de la plancha.
            self.render()
        else:
            self.optimize()
        self.status_message(
            f"{len(pasted)} diseño(s) pegado(s) y plancha reorganizada."
        )
        return "break"

    def drag_item(self, event):
        if self.project.project_type == "sticker_mixed":
            return
        x, y = self.canvas_event_position(event)
        if self.area_selection_start is not None:
            start_x, start_y = self.area_selection_start
            if self.area_selection_rect is None:
                self.area_selection_rect = self.canvas.create_rectangle(
                    start_x, start_y, x, y,
                    outline=COLORS.wine_active, width=2, dash=(5, 3),
                    fill="", tags=("area_selection",),
                )
            else:
                self.canvas.coords(self.area_selection_rect, start_x, start_y, x, y)
            return
        item = self.selected_item()
        if not item or item.locked:
            return
        max_x = A4_WIDTH_CM - self.project.margin_cm - item.width_cm
        if self.project.layout_mode != "special":
            pointer_y = self.px_to_cm(y - 25 - self.drag_offset[1])
            self.drag_band_index = self.project.band_index_for_y(
                pointer_y + item.height_cm / 2
            )
        min_y, max_y = self.drag_band_bounds(item)
        step = max(0.05, self.project.gap_cm)
        raw_x = min(max(self.project.margin_cm, self.px_to_cm(x - 25 - self.drag_offset[0])), max_x)
        raw_y = min(max(min_y, self.px_to_cm(y - 25 - self.drag_offset[1])), max_y)
        # Imán base: al mover se alinea a la grilla real de separación de la plancha.
        if self.show_hitboxes:
            new_x = round(round((raw_x - self.project.margin_cm) / step) * step + self.project.margin_cm, 3)
            new_y = round(round((raw_y - self.project.margin_cm) / step) * step + self.project.margin_cm, 3)
            new_x, new_y = self.magnetic_position(item, min(new_x, max_x), min(new_y, max_y))
        else:
            new_x, new_y = round(raw_x, 3), round(raw_y, 3)
        new_y = min(max(min_y, new_y), max_y)
        old_x, old_y = item.x_cm, item.y_cm
        # Nunca permite que una hitbox invada a otra. Si el cursor llega a una
        # zona ocupada, mantiene la última posición válida del diseño.
        # Las validaciones de separación pertenecen a las hitboxes. Sin
        # guías, el usuario puede superponer y ajustar visualmente diseños;
        # solo se conservan los límites físicos de su franja.
        if not self.show_hitboxes or self.can_place(item, new_x, new_y):
            item.x_cm, item.y_cm = new_x, new_y
        if not self.move_item_preview(item, old_x, old_y):
            # Compatibilidad con pruebas y hosts que no exponen un Canvas real.
            self.request_render()

    def band_for_item(self, item: PlanchaItem) -> int:
        """Devuelve la franja de producción (1 a 5) donde está el diseño."""
        center_y = item.y_cm + (item.height_cm / 2)
        return self.project.band_index_for_y(center_y)

    def drag_band_bounds(self, item: PlanchaItem) -> tuple[float, float]:
        """Fija el arrastre a la línea común de una de las cinco franjas."""
        margin = self.project.margin_cm
        paper_max_y = self.project.workspace_bottom_cm - item.height_cm
        if self.project.layout_mode == "special":
            return margin, paper_max_y
        band_heights = self.project.production_band_heights()
        row_count = len(band_heights)
        band_index = self.drag_band_index if self.drag_band_index is not None else self.band_for_item(item)
        band_top = margin + sum(band_heights[:band_index])
        band_bottom = band_top + band_heights[band_index]
        if item.height_cm > band_heights[band_index]:
            return margin, paper_max_y
        # Cada hitbox de una franja comparte exactamente la misma Y. Esto
        # mantiene el orden de corte aunque el usuario haga ajustes manuales.
        if self.show_hitboxes:
            return band_top, band_top
        # Sin hitboxes no se reserva aire adicional, pero el diseño sigue
        # centrado verticalmente en la franja de producción.
        centered_y = max(band_top, (band_top + band_bottom - item.height_cm) / 2)
        return centered_y, centered_y

    def magnetic_position(self, item: PlanchaItem, x_cm: float, y_cm: float) -> tuple[float, float]:
        """Acerca el diseño al borde derecho de otro sin salir de su hitbox.

        La prioridad es el borde derecho, tal como se arma la plancha de
        izquierda a derecha. Los otros bordes solo ayudan a mantener una fila
        visualmente prolija cuando ya se está muy cerca de ellos.
        """
        margin = self.project.margin_cm
        gap = self.project.gap_cm
        max_x = A4_WIDTH_CM - margin - item.width_cm
        max_y = self.project.workspace_bottom_cm - item.height_cm
        tolerance = max(0.12, gap * 3)
        candidates: list[tuple[float, float, float]] = []
        for other in self.project.items:
            if other.item_id == item.item_id:
                continue
            vertical_overlap = not (y_cm + item.height_cm <= other.y_cm or other.y_cm + other.height_cm <= y_cm)
            # Acople principal: inmediatamente a la derecha del diseño que
            # comparte el renglón, respetando siempre la separación elegida.
            right_x = other.x_cm + other.width_cm + gap
            if vertical_overlap and abs(x_cm - right_x) <= tolerance:
                candidates.append((abs(x_cm - right_x), right_x, y_cm))
            # Alineaciones suaves para que no queden escalones innecesarios.
            for target_y in (other.y_cm, other.y_cm + other.height_cm - item.height_cm):
                if abs(y_cm - target_y) <= tolerance:
                    candidates.append((abs(y_cm - target_y) + tolerance / 2, x_cm, target_y))
        # También reconoce el borde imprimible como imán.
        if abs(x_cm - margin) <= tolerance:
            candidates.append((abs(x_cm - margin), margin, y_cm))
        if abs(x_cm - max_x) <= tolerance:
            candidates.append((abs(x_cm - max_x), max_x, y_cm))
        for _distance, candidate_x, candidate_y in sorted(candidates, key=lambda candidate: candidate[0]):
            candidate_x = round(min(max(margin, candidate_x), max_x), 3)
            candidate_y = round(min(max(margin, candidate_y), max_y), 3)
            if self.can_place(item, candidate_x, candidate_y):
                return candidate_x, candidate_y
        return round(x_cm, 3), round(y_cm, 3)

    def can_place(self, item: PlanchaItem, x_cm: float, y_cm: float,
                  clearance_cm: float | None = None) -> bool:
        """Comprueba superposición, con holgura de producción opcional."""
        gap = self.project.gap_cm if clearance_cm is None else max(0.0, clearance_cm)
        for other in self.project.items:
            if other.item_id == item.item_id:
                continue
            separated = (
                x_cm + item.width_cm + gap <= other.x_cm
                or other.x_cm + other.width_cm + gap <= x_cm
                or y_cm + item.height_cm + gap <= other.y_cm
                or other.y_cm + other.height_cm + gap <= y_cm
            )
            if not separated:
                return False
        return True

    def release_item(self, event):
        if self.area_selection_start is not None:
            end_x, end_y = self.canvas_event_position(event)
            start_x, start_y = self.area_selection_start
            if abs(end_x - start_x) >= 4 or abs(end_y - start_y) >= 4:
                area_ids = self.item_ids_in_area(start_x, start_y, end_x, end_y)
                self.selected_ids = self.area_selection_base | area_ids
                self.selected_id = next(
                    (item.item_id for item in reversed(self.project.items) if item.item_id in self.selected_ids),
                    None,
                )
            self.canvas.delete("area_selection")
            self.area_selection_start = None
            self.area_selection_base.clear()
            self.area_selection_rect = None
            self.render()
            return
        item = self.selected_item()
        if item:
            # Al mover a mano se conserva la decisión del usuario; optimizar
            # solo ocurre al presionar su botón. Esto mantiene el acople
            # magnético y habilita ajustes finos de producción.
            self.snapshot()
            if self.project.manual_from_mixed and not validate_no_overlaps(self.project.items):
                self.status_message("COLISIÓN: las hitboxes se superponen. Reubicá los stickers antes de imprimir.")
            self.render()

    def show_canvas_context_menu(self, event):
        """Acciones locales para los diseños seleccionados de la plancha."""
        x, y = self.canvas_event_position(event)
        item = self.item_at(x, y)
        if item and item.item_id not in self.selected_ids:
            self.selected_ids = {item.item_id}
            self.selected_id = item.item_id
            self.render()
        if not self.selected_ids:
            return
        count = len(self.selected_ids)
        menu = tk.Menu(self, tearoff=False, background=COLORS.panel, foreground=COLORS.text)
        selected_items = [item for item in self.project.items if item.item_id in self.selected_ids]
        has_inner_border = any(not item.remove_inner_white_border for item in selected_items)
        menu.add_command(
            label="Quitar borde blanco interno" if has_inner_border else "Restaurar borde blanco interno",
            command=self.toggle_selected_inner_white_border,
        )
        menu.add_separator()
        label = "Eliminar diseño de la plancha" if count == 1 else f"Eliminar {count} diseños de la plancha"
        menu.add_command(label=label, command=lambda *a, _fn=self.delete_selected: _fn(*a))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def toggle_selected_inner_white_border(self):
        """Activa o restaura el borde interior solo en los stickers elegidos."""
        selected_items = [item for item in self.project.items if item.item_id in self.selected_ids]
        if not selected_items:
            return
        remove_border = any(not item.remove_inner_white_border for item in selected_items)
        self.snapshot()
        for item in selected_items:
            item.remove_inner_white_border = remove_border
        self.thumbnail_cache.clear()
        self.production_sticker_cache.clear()
        self.production_sticker_cache_pixels = 0
        self.render()

    def auto_arrange_around(self, anchor: PlanchaItem):
        """Conserva el diseño soltado y reubica automáticamente los demás."""
        movable = [item for item in self.project.items if not item.locked and item.item_id != anchor.item_id]
        fixed = [item for item in self.project.items if item.locked or item.item_id == anchor.item_id]
        self.project.items = [item for item in fixed if item.item_id != anchor.item_id]
        # Si se soltó sobre una posición bloqueada, busca el hueco más cercano
        # disponible antes de organizar el resto.
        if not self.can_place(anchor, anchor.x_cm, anchor.y_cm):
            position = self.find_free_position(anchor.width_cm, anchor.height_cm)
            if position:
                anchor.x_cm, anchor.y_cm = position
        self.project.items.append(anchor)
        for item in sorted(movable, key=lambda candidate: (candidate.source != "Pedido", -candidate.height_cm, -candidate.width_cm)):
            position = self.find_free_position(item.width_cm, item.height_cm)
            if position:
                item.x_cm, item.y_cm = position
            self.project.items.append(item)

    def organize_automatically(self, progress=None) -> list[PlanchaItem]:
        """Optimiza siempre y separa los stickers que no entran en el A4."""
        if self.use_experimental_packing and self.project.project_type == "legacy":
            from app.planchas.model import geometric_pack

            original_items = list(self.project.items)
            items = [item.to_dict() for item in original_items]
            result = geometric_pack(items, extra_cm=SPECIAL_LAYOUT_EXTRA_CM, allow_rotation=True, strategy="area_desc")
            placed_by_id = {item["item_id"]: item for item in result.placed if "item_id" in item}
            overflow_ids = {item.get("item_id") for item in result.overflow if isinstance(item, dict)}

            for original in original_items:
                placed = placed_by_id.get(original.item_id)
                if placed is None:
                    continue
                cut_w = float(placed["cut_width_cm"])
                cut_h = float(placed["cut_height_cm"])
                if placed.get("rotated"):
                    original.width_cm, original.height_cm = cut_h, cut_w
                    original.rotation = (original.rotation + 90) % 360
                else:
                    original.width_cm, original.height_cm = cut_w, cut_h
                    original.rotation = 0
                original.layout_width_cm = float(placed["layout_width_cm"])
                original.layout_height_cm = float(placed["layout_height_cm"])
                original.x_cm = round(float(placed["x_cm"]), 3)
                original.y_cm = round(float(placed["y_cm"]), 3)

            self.project.items = [item for item in original_items if item.item_id not in overflow_ids]
            self.selected_ids.difference_update(overflow_ids)
            if self.selected_id in overflow_ids:
                self.selected_id = None
            self.pending_overflow.extend(
                item for item in original_items
                if item.item_id in overflow_ids and item not in self.pending_overflow
            )
            return [item for item in original_items if item.item_id in overflow_ids]

        overflow = self.project.optimize(progress=progress)
        if overflow:
            overflow_ids = {item.item_id for item in overflow}
            self.project.items = [item for item in self.project.items if item.item_id not in overflow_ids]
            self.selected_ids.difference_update(overflow_ids)
            if self.selected_id in overflow_ids:
                self.selected_id = None
            self.pending_overflow.extend(item for item in overflow if item not in self.pending_overflow)
        return overflow

    def organize_with_pagination(self, progress=None) -> list[PlanchaItem]:
        """Organiza stickers automáticamente con paginación en múltiples planchas."""
        from app.planchas.model import PlanchaProject
        
        # Obtener todos los items a distribuir
        all_items = self.project.items.copy()

        # Experimental A4: the strategy is selected for the full batch rather
        # than independently per page. Other workspace formats remain classic.
        # Motor histórico: sólo se conserva para proyectos legacy abiertos.
        # Las creaciones nuevas normalizan special_geometric a sticker_mixed
        # antes de llegar aquí.
        if self.use_experimental_packing and self.project.project_type == "legacy" and self.project.workspace_format == "a4":
            from app.planchas.model import maximize_special_multipage

            result, global_scale = maximize_special_multipage(
                all_items,
                margin_cm=self.project.margin_cm,
            )
            self.global_production_scale = global_scale
            originals = {item.item_id: item for item in all_items}
            self.all_projects = []
            for page in result.pages:
                page_items: list[PlanchaItem] = []
                for placed in page.placed:
                    original = originals.get(placed.get("item_id"))
                    if original is None:
                        continue
                    item = PlanchaItem.from_dict(original.to_dict())
                    cut_w, cut_h = float(placed["cut_width_cm"]), float(placed["cut_height_cm"])
                    if placed.get("rotated"):
                        item.width_cm, item.height_cm = cut_h, cut_w
                        item.rotation = (item.rotation + 90) % 360
                    else:
                        item.width_cm, item.height_cm = cut_w, cut_h
                    item.layout_width_cm = float(placed["layout_width_cm"])
                    item.layout_height_cm = float(placed["layout_height_cm"])
                    item.x_cm, item.y_cm = round(float(placed["x_cm"]), 3), round(float(placed["y_cm"]), 3)
                    page_items.append(item)
                self.all_projects.append(PlanchaProject(
                    page_items,
                    margin_cm=self.project.margin_cm,
                    gap_cm=self.project.gap_cm,
                    layout_mode=self.layout_mode,
                    workspace_format=self.project.workspace_format,
                ))

            self.pending_overflow.extend(
                originals[item["item_id"]] for item in result.impossible
                if item.get("item_id") in originals and originals[item["item_id"]] not in self.pending_overflow
            )
            self.max_planchas = len(self.all_projects)
            self.current_project_index = 0
            if self.all_projects:
                self.project = self.all_projects[0]
                self.plancha_number = 1
                self.title(f"Plancha 1 de {self.max_planchas} · geométrica · {self.project.workspace_label}")
            return [originals[item["item_id"]] for item in result.impossible if item.get("item_id") in originals]
        
        # Calcular paginación usando el método del modelo
        if progress:
            progress(0, 10, "Calculando distribución en planchas...")
        
        self.all_projects = PlanchaProject.calculate_pagination(
            all_items,
            margin_cm=self.project.margin_cm,
            gap_cm=self.project.gap_cm,
            layout_mode=self.layout_mode,
            workspace_format=self.project.workspace_format,
            progress=progress
        )
        # La paginación crea páginas nuevas: conservar explícitamente el modo
        # del flujo que las originó para persistirlas sin reinterpretarlas.
        for page in self.all_projects:
            page.project_type = self.project.project_type
            page.manual_from_mixed = self.project.manual_from_mixed
        
        # Actualizar max_planchas según el resultado
        self.max_planchas = len(self.all_projects)
        self.current_project_index = 0
        
        # Usar la primera plancha como proyecto actual
        if self.all_projects:
            self.project = self.all_projects[0]
            self.plancha_number = 1
            self.title(f"Plancha 1 de {self.max_planchas} · {'especial' if self.layout_mode == 'special' else 'clásica'} · {self.project.workspace_label}")
        
        # No hay overflow porque todos los items están distribuidos
        return []

    def update_plancha_navigation(self):
        """Actualiza la interfaz de navegación entre planchas."""
        if not hasattr(self, 'plancha_nav_frame'):
            return
        
        total_stickers = sum(len(project.items) for project in self.all_projects) if self.all_projects else len(self.project.items)
        self.plancha_stats_text.set(f"{total_stickers} stickers distribuidos en {self.max_planchas} plancha(s)")
        self.plancha_counter_text.set(f"Plancha {self.plancha_number} de {self.max_planchas}")
        
        # Habilitar/deshabilitar botones según posición
        self.prev_plancha_btn.config(state="normal" if self.current_project_index > 0 else "disabled")
        self.next_plancha_btn.config(state="normal" if self.current_project_index < self.max_planchas - 1 else "disabled")
        if hasattr(self, "plancha_picker"):
            choices = [f"Plancha {number}" for number in range(1, self.max_planchas + 1)]
            self.plancha_picker.configure(values=choices)
            self.plancha_picker.set(f"Plancha {self.plancha_number}")

    def _pick_plancha(self, _event=None):
        """Salta directamente a una plancha del trabajo actual."""
        try:
            index = int(self.plancha_picker.current())
        except (TypeError, ValueError):
            return
        self.navigate_to_plancha(index)

    def navigate_to_plancha(self, index: int):
        """Navega a una plancha específica."""
        if not (0 <= index < len(self.all_projects)):
            return
        
        # Guardar estado actual antes de cambiar
        self.snapshot()
        
        self.current_project_index = index
        self.project = self.all_projects[index]
        self.plancha_number = index + 1
        
        # Actualizar título y UI
        self.title(f"Plancha {self.plancha_number} de {self.max_planchas} · {'especial' if self.layout_mode == 'special' else 'clásica'} · {self.project.workspace_label}")
        self.format_heading.set(f"PLANCHA {self.project.workspace_label.upper()}")
        
        # Limpiar selección
        self.selected_id = None
        self.selected_ids.clear()
        
        # Renderizar nueva plancha
        self.render()
        self.update_plancha_navigation()

    def next_plancha(self):
        """Navega a la siguiente plancha."""
        if self.current_project_index < self.max_planchas - 1:
            self.navigate_to_plancha(self.current_project_index + 1)

    def previous_plancha(self):
        """Navega a la plancha anterior."""
        if self.current_project_index > 0:
            self.navigate_to_plancha(self.current_project_index - 1)

    def generate_all_planchas(self):
        """Genera vistas previas de todas las planchas del conjunto."""
        if not self.all_projects or len(self.all_projects) <= 1:
            messagebox.showinfo("Generación", "Solo hay una plancha. Usá 'Generar vista previa' para esta plancha.", parent=self)
            return
        
        progress_dialog = tk.Toplevel(self)
        progress_dialog.title("Generando planchas")
        progress_dialog.configure(background=COLORS.panel)
        progress_dialog.transient(self)
        progress_dialog.geometry("400x150")
        
        tk.Label(progress_dialog, text="Generando vistas previas...", background=COLORS.panel, foreground=COLORS.text, font=(IDENTITY_FONT, 12)).pack(pady=20)
        
        progress = ttk.Progressbar(progress_dialog, mode="determinate", maximum=len(self.all_projects))
        progress.pack(fill="x", padx=20, pady=10)
        
        def generate():
            for index, project in enumerate(self.all_projects):
                # Guardar el proyecto actual temporalmente
                original_project = self.project
                original_index = self.current_project_index
                
                # Cambiar a este proyecto
                self.project = project
                self.current_project_index = index
                
                # Generar vista previa
                try:
                    self.export_preview(silent=True)
                except Exception as e:
                    logger.error(f"Error generando vista previa de plancha {index + 1}: {e}")
                
                # Restaurar proyecto original
                self.project = original_project
                self.current_project_index = original_index
                
                # Actualizar progreso
                progress["value"] = index + 1
                progress_dialog.update_idletasks()
            
            progress_dialog.destroy()
            messagebox.showinfo("Generación completa", f"Se generaron vistas previas de {len(self.all_projects)} planchas.", parent=self)
        
        threading.Thread(target=generate, daemon=True).start()

    def export_all_planchas(self):
        """Exporta PNG finales de todas las planchas del conjunto."""
        if not self.all_projects or len(self.all_projects) <= 1:
            messagebox.showinfo("Exportación", "Solo hay una plancha. Usá 'Guardar PNG final' para esta plancha.", parent=self)
            return
        
        # Pedir directorio de destino
        dest_dir = filedialog.askdirectory(title="Seleccionar directorio para exportar planchas")
        if not dest_dir:
            return
        
        progress_dialog = tk.Toplevel(self)
        progress_dialog.title("Exportando planchas")
        progress_dialog.configure(background=COLORS.panel)
        progress_dialog.transient(self)
        progress_dialog.geometry("400x150")
        
        tk.Label(progress_dialog, text="Exportando PNG finales...", background=COLORS.panel, foreground=COLORS.text, font=(IDENTITY_FONT, 12)).pack(pady=20)
        
        progress = ttk.Progressbar(progress_dialog, mode="determinate", maximum=len(self.all_projects))
        progress.pack(fill="x", padx=20, pady=10)
        
        def export():
            from datetime import datetime
            
            base_name = f"plancha_set_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            exported_count = 0
            
            for index, project in enumerate(self.all_projects):
                # Guardar el proyecto actual temporalmente
                original_project = self.project
                original_index = self.current_project_index
                original_final_path = self.final_png_path
                
                # Cambiar a este proyecto
                self.project = project
                self.current_project_index = index
                
                # Definir ruta de exportación
                export_path = Path(dest_dir) / f"{base_name}_plancha_{index + 1}.png"
                
                try:
                    # Exportar PNG final
                    self.export_final(silent=True, custom_path=str(export_path))
                    exported_count += 1
                except Exception as e:
                    logger.error(f"Error exportando plancha {index + 1}: {e}")
                
                # Restaurar proyecto original
                self.project = original_project
                self.current_project_index = original_index
                self.final_png_path = original_final_path
                
                # Actualizar progreso
                progress["value"] = index + 1
                progress_dialog.update_idletasks()
            
            progress_dialog.destroy()
            messagebox.showinfo("Exportación completa", f"Se exportaron {exported_count} de {len(self.all_projects)} planchas como PNG.", parent=self)
        
        threading.Thread(target=export, daemon=True).start()

    def print_all_planchas(self):
        """Envía todas las planchas del conjunto a la cola de impresión."""
        if not self.all_projects or len(self.all_projects) <= 1:
            messagebox.showinfo("Impresión", "Solo hay una plancha. Usá 'Enviar a cola' para esta plancha.", parent=self)
            return
        
        if not self.database:
            messagebox.showwarning("Impresión", "Se requiere conexión a la base de datos para enviar a cola de impresión.", parent=self)
            return
        
        if not messagebox.askyesno("Imprimir todas", f"¿Enviar {len(self.all_projects)} planchas a la cola de impresión?", parent=self):
            return
        
        progress_dialog = tk.Toplevel(self)
        progress_dialog.title("Enviando a cola")
        progress_dialog.configure(background=COLORS.panel)
        progress_dialog.transient(self)
        progress_dialog.geometry("400x150")
        
        tk.Label(progress_dialog, text="Enviando a cola de impresión...", background=COLORS.panel, foreground=COLORS.text, font=(IDENTITY_FONT, 12)).pack(pady=20)
        
        progress = ttk.Progressbar(progress_dialog, mode="determinate", maximum=len(self.all_projects))
        progress.pack(fill="x", padx=20, pady=10)
        
        def send_to_queue():
            queued_count = 0
            
            for index, project in enumerate(self.all_projects):
                # Guardar el proyecto actual temporalmente
                original_project = self.project
                original_index = self.current_project_index
                original_plancha_id = self.plancha_id
                
                # Cambiar a este proyecto
                self.project = project
                self.current_project_index = index
                
                try:
                    # Enviar a cola
                    self.send_to_print_queue(silent=True)
                    queued_count += 1
                except Exception as e:
                    logger.error(f"Error enviando plancha {index + 1} a cola: {e}")
                
                # Restaurar proyecto original
                self.project = original_project
                self.current_project_index = original_index
                self.plancha_id = original_plancha_id
                
                # Actualizar progreso
                progress["value"] = index + 1
                progress_dialog.update_idletasks()
            
            progress_dialog.destroy()
            messagebox.showinfo("Cola de impresión", f"Se enviaron {queued_count} de {len(self.all_projects)} planchas a la cola de impresión.", parent=self)
            self.refresh_printing_panel()
        
        threading.Thread(target=send_to_queue, daemon=True).start()

    def offer_overflow(self, overflow: list[PlanchaItem]):
        if not overflow:
            return
        if self.project.workspace_format == "a5":
            lower_band = len(self.project.production_band_heights()) - 1
            lower_items = [item for item in self.project.items if self.project.band_index_for_y(item.y_cm + item.height_cm / 2) == lower_band]
            if len(lower_items) <= 1:
                if messagebox.askyesno(
                    "Completar plancha A4",
                    "La media franja inferior de A5 solo admite un sticker fino.\n\n¿Desea completar la plancha A4 con los stickers restantes?",
                    parent=self,
                ):
                    self.project.workspace_format = "a4"
                    self.project.margin_cm = PRINT_MARGIN_CM
                    self.project.items.extend(item for item in overflow if item not in self.project.items)
                    self.pending_overflow = [item for item in self.pending_overflow if item not in overflow]
                    self.workspace_button.configure(text="A4")
                    self.format_heading.set("PLANCHA A4 COMPLETA")
                    self.optimize()
                    return
        if self.plancha_number >= self.max_planchas:
            messagebox.showwarning(
                "Revisar tamaños",
                f"{len(overflow)} sticker(s) no entran en las {self.max_planchas} planchas de 5 franjas.\n\n"
                "Reducí su tamaño o preparalos con un formato especial; no se crearán planchas adicionales automáticamente.",
                parent=self,
            )
            return

        dialog = tk.Toplevel(self)
        dialog.title("Stickers sobrantes")
        dialog.configure(background=COLORS.panel)
        dialog.transient(self)
        dialog.grab_set()
        ttk.Label(dialog, text="Stickers sobrantes", style="Title.TLabel",
                  padding=(18, 14, 18, 4)).pack(anchor="w")
        ttk.Label(
            dialog,
            text=f"Sobraron {len(overflow)} sticker(s).\nLos pasaremos a la plancha especial.",
            style="Muted.TLabel", justify="left", padding=(18, 0, 18, 12),
        ).pack(anchor="w")
        actions = tk.Frame(dialog, background=COLORS.panel)
        actions.pack(fill="x", padx=18, pady=(0, 16))

        def create_special_plancha():
            dialog.grab_release()
            dialog.destroy()
            self.pending_overflow = [item for item in self.pending_overflow if item not in overflow]
            next_project = PlanchaProject(
                list(overflow), margin_cm=PRINT_MARGIN_CM, gap_cm=self.project.gap_cm, layout_mode="special",
            )
            self.app.open_embedded_plancha(
                [], database=self.database, library_images=self.library_images,
                project=next_project, order_id=self.order_id,
                plancha_number=self.plancha_number + 1, max_planchas=self.max_planchas, layout_mode="special",
            )
            self.render()

        ttk.Button(actions, text="Revisar plancha", command=lambda: (dialog.grab_release(), dialog.destroy()),
                   style="Plancha.Secondary.TButton").pack(side="left")
        ttk.Button(actions, text="Crear plancha especial", command=create_special_plancha,
                   style="Plancha.Primary.TButton").pack(side="right")

    def apply_size(self):
        if self.project.project_type == "sticker_free":
            self.status_message("Usá los controles − / + para ajustar producción sin cambiar el nominal.")
            return
        item = self.selected_item()
        if not item:
            return
        selected = self.selected_ids or {item.item_id}
        group_ids = {candidate.group_id for candidate in self.project.items if candidate.item_id in selected}
        for candidate in self.project.items:
            if candidate.group_id not in group_ids:
                continue
            nominal = self.selected_size_cm()
            width, height = size_for_record({"path": candidate.path}, nominal)
            if candidate.rotation % 180:
                width, height = height, width
            candidate.width_cm, candidate.height_cm = width, height
            candidate.nominal_size_cm = nominal
        if self.project.project_type == "sticker_mixed":
            self.regenerate_sticker_mixed()
        else:
            self.optimize()

    def apply_size_and_quantity(self):
        """Aplica ambos controles antes de repintar y redistribuir la plancha."""
        if self.project.project_type == "sticker_free":
            self.status_message("Usá los controles − / + para ajustar producción sin cambiar el nominal.")
            return
        item = self.selected_item()
        if not item:
            return

        # ``apply_size`` repinta el panel y vuelve a cargar la cantidad previa
        # del diseño. Capturamos ambos valores antes de que ocurra ese repintado.
        target_size = self.selected_size_cm()
        try:
            target_quantity = max(1, int(self.quantity_value.get()))
        except (tk.TclError, TypeError, ValueError):
            target_quantity = 1

        selected = self.selected_ids or {item.item_id}
        group_ids = {
            candidate.group_id for candidate in self.project.items
            if candidate.item_id in selected
        }
        for candidate in self.project.items:
            if candidate.group_id not in group_ids:
                continue
            width, height = size_for_record({"path": candidate.path}, target_size)
            if candidate.rotation % 180:
                width, height = height, width
            candidate.width_cm, candidate.height_cm = width, height
            candidate.nominal_size_cm = target_size

        replacement = self.project.set_quantity(item.item_id, target_quantity)
        self.selected_id = replacement.item_id if replacement else None
        self.selected_ids = {self.selected_id} if self.selected_id else set()
        if self.project.project_type == "sticker_mixed":
            self.regenerate_sticker_mixed()
        else:
            self.optimize()

    def normalize_by_longest_side(self):
        """Hace uniforme el lado mayor de todos los stickers elegidos."""
        if self.project.project_type == "sticker_free":
            self.status_message("Usá los controles − / + para ajustar producción sin cambiar el nominal.")
            return
        selected = self.selected_ids or {item.item_id for item in self.project.items}
        group_ids = {candidate.group_id for candidate in self.project.items if candidate.item_id in selected}
        target_size = self.selected_size_cm()
        for candidate in self.project.items:
            if candidate.group_id not in group_ids:
                continue
            width, height = size_for_record({"path": candidate.path}, target_size)
            if candidate.rotation % 180:
                width, height = height, width
            candidate.width_cm, candidate.height_cm = width, height
            candidate.nominal_size_cm = target_size
        if self.project.project_type == "sticker_mixed":
            self.regenerate_sticker_mixed()
        else:
            self.optimize()

    def resize_selected_productive(self, command) -> bool:
        """Única ruta de resize para proyectos libres con nominal."""
        if self.project.project_type != "sticker_free":
            return False
        item = self.selected_item()
        if not item or item.nominal_size_cm is None:
            self.status_message("Elegí un sticker con tamaño nominal definido.")
            return False
        from app.planchas.free_resize import FREE_RESIZE_STEP_CM, resize_productive_item
        from app.planchas.production_geometry import production_max_for_nominal, production_min_for_nominal

        current = max(item.width_cm, item.height_cm)
        if command == "min":
            target = production_min_for_nominal(item.nominal_size_cm)
        elif command == "max":
            target = production_max_for_nominal(item.nominal_size_cm)
        else:
            target = current + float(command) * FREE_RESIZE_STEP_CM
        before = item.to_dict()
        result = resize_productive_item(
            item, target_major_cm=target, margin_cm=self.project.margin_cm,
            bottom_cm=self.project.workspace_bottom_cm,
        )
        if not result.changed:
            if not result.fits_area:
                self.status_message("El tamaño solicitado no entra en el área imprimible manteniendo su posición.")
            return False
        self.snapshot()
        if not validate_no_overlaps(self.project.items):
            self.status_message("COLISIÓN: el resize superpone hitboxes. Reubicá manualmente los stickers.")
        elif result.at_minimum:
            self.status_message("Tamaño productivo mínimo aplicado.")
        elif result.at_maximum:
            self.status_message("Tamaño productivo máximo aplicado.")
        else:
            self.status_message(f"Producción ajustada a {result.major_cm:.2f} cm.")
        self.render()
        return item.to_dict() != before

    def change_selected_nominal(self) -> bool:
        """Acción comercial explícita; distinta del resize productivo libre."""
        if self.project.project_type != "sticker_free":
            return False
        item = self.selected_item()
        if not item or item.nominal_size_cm is None:
            self.status_message("Elegí un sticker con tamaño nominal definido.")
            return False
        nominal = simpledialog.askfloat(
            "Cambiar tamaño nominal", "Nuevo tamaño comercial (cm):",
            initialvalue=item.nominal_size_cm, minvalue=0.01, maxvalue=MAX_SIZE_CM, parent=self,
        )
        if nominal is None:
            return False
        from app.planchas.free_nominal import change_nominal_size, source_supports_nominal_at_300dpi

        if not source_supports_nominal_at_300dpi(item, nominal):
            self.status_message("Resolución insuficiente para este tamaño a 300 DPI.")
            return False
        before = item.to_dict()
        result = change_nominal_size(
            item, new_nominal_cm=nominal, margin_cm=self.project.margin_cm,
            bottom_cm=self.project.workspace_bottom_cm,
        )
        if not result.changed:
            if result.reason == "impossible_a4":
                minimum = production_min_for_nominal(nominal)
                self.status_message(
                    f"NO PRODUCIBLE EN A4: nominal {nominal:.2f} cm, mínimo {minimum:.2f} cm; "
                    f"área {A4_WIDTH_CM - 2 * self.project.margin_cm:.2f} × {self.project.workspace_bottom_cm - self.project.margin_cm:.2f} cm."
                )
            else:
                self.status_message("El nuevo tamaño no entra en la posición actual.")
            return False
        self.snapshot()
        if not validate_no_overlaps(self.project.items):
            self.status_message("COLISIÓN: el nuevo tamaño superpone hitboxes. Reubicá manualmente los stickers.")
        else:
            self.status_message(f"Tamaño nominal cambiado a {nominal:.2f} cm; producción mínima aplicada.")
        self.render()
        return item.to_dict() != before

    def apply_quantity(self):
        item = self.selected_item()
        if not item:
            return
        replacement = self.project.set_quantity(item.item_id, self.quantity_value.get())
        self.selected_id = replacement.item_id if replacement else None
        self.optimize()

    def apply_details(self):
        item = self.selected_item()
        if not item:
            return
        client = self.client_value.get().strip()
        color = self.project.client_color(client)
        for candidate in self.project.group_items(item):
            candidate.source = self.source_value.get()
            candidate.client = client
            candidate.order_number = self.order_value.get().strip()
            candidate.client_color = color
            candidate.rotation_allowed = self.rotation_allowed.get()
        order_number = self.order_value.get().strip()
        if order_number.isdigit():
            self.order_id = int(order_number)
        if self.project.project_type == "sticker_free":
            self.snapshot()
            self.render()
        else:
            self.optimize()

    def rotate_selected(self):
        if self.project.project_type == "sticker_mixed":
            self.status_message("La rotación de Mixta la define el packing automático. Regenerá para recalcularla.")
            return
        item = self.selected_item()
        if not item:
            return
        if not item.rotation_allowed:
            messagebox.showinfo("Rotación", "Marcá «Autorizar rotación 90°» y aplicá los datos antes de rotar.", parent=self)
            return
        if self.project.project_type == "sticker_free":
            center_x = item.x_cm + item.reserved_width_cm / 2
            center_y = item.y_cm + item.reserved_height_cm / 2
            item.width_cm, item.height_cm = item.height_cm, item.width_cm
            item.layout_width_cm, item.layout_height_cm = item.reserved_height_cm, item.reserved_width_cm
            item.x_cm = center_x - item.reserved_width_cm / 2
            item.y_cm = center_y - item.reserved_height_cm / 2
            item.rotation = (item.rotation + 90) % 360
            self.snapshot()
            self.render()
            if not validate_no_overlaps(self.project.items):
                self.status_message("COLISIÓN: la rotación superpone hitboxes. Reubicá manualmente.")
            return
        item.width_cm, item.height_cm = item.height_cm, item.width_cm
        item.rotation = (item.rotation + 90) % 360
        self.optimize()

    def toggle_lock(self):
        item = self.selected_item()
        if not item:
            return
        item.locked = not item.locked
        if self.project.project_type == "sticker_free":
            self.snapshot()
            self.render()
        else:
            self.optimize()

    def delete_selected(self):
        selected = set(self.selected_ids)
        if not selected and self.selected_id:
            selected.add(self.selected_id)
        if not selected:
            return
        count = len(selected)
        message = (
            "¿Eliminar este diseño de la plancha?"
            if count == 1 else f"¿Eliminar los {count} diseños seleccionados de la plancha?"
        )
        if not messagebox.askyesno(
            "Eliminar de la plancha",
            message + "\n\nLos archivos originales no se modificarán.",
            parent=self,
        ):
            return
        self.project.items = [item for item in self.project.items if item.item_id not in selected]
        self.selected_id = None
        self.selected_ids.clear()
        if not self.project.items:
            self.discard_plancha(confirm=False)
            return
        self.optimize()

    def discard_plancha(self, confirm: bool = True):
        """Descarta el armado actual y su registro de Producción, si existe."""
        # Cuando el trabajo fue paginado, una plancha es una página
        # independiente: descartarla no debe cerrar ni eliminar las demás.
        if len(self.all_projects) > 1:
            current_number = self.current_project_index + 1
            if confirm and not messagebox.askyesno(
                "Descartar plancha",
                f"¿Descartar solo la plancha {current_number} de {len(self.all_projects)}?\n\n"
                "Las demás planchas del trabajo se conservarán.",
                parent=self,
            ):
                return False

            del self.all_projects[self.current_project_index]
            self.current_project_index = min(self.current_project_index, len(self.all_projects) - 1)
            self.project = self.all_projects[self.current_project_index]
            self.plancha_number = self.current_project_index + 1
            self.max_planchas = len(self.all_projects)
            self.selected_id = None
            self.selected_ids.clear()
            self.snapshot()
            self.render()
            self.update_plancha_navigation()
            self.status_message(f"Plancha {current_number} descartada; quedan {self.max_planchas} plancha(s).")
            if not confirm:
                messagebox.showinfo(
                    "Plancha descartada",
                    "Se quitó el último sticker: se descartó solo esta plancha.",
                    parent=self,
                )
            return True

        if confirm and not messagebox.askyesno(
            "Descartar plancha",
            "¿Descartar esta plancha? Se eliminará de Producción y se cerrará el constructor.\n\n"
            "Los archivos originales de los stickers no se modificarán.",
            parent=self,
        ):
            return False

        try:
            if self.database and self.plancha_id:
                self.database.delete_plancha_project(self.plancha_id)
        except RuntimeError as error:
            messagebox.showerror("Descartar plancha", str(error), parent=self)
            return False

        self.plancha_id = None
        self.project_path = ""
        self.final_png_path = ""
        self.status_message("Plancha descartada.")
        if not confirm:
            messagebox.showinfo(
                "Plancha descartada",
                "Se quitó el último sticker: la plancha vacía fue descartada.",
                parent=self,
            )
        if self._on_close:
            self._on_close(discard=True)
        else:
            self.destroy()
        return True

    def optimize(self):
        overflow = self.organize_automatically()
        self.snapshot()
        self.render()
        if overflow:
            self.offer_overflow(overflow)

    def show_workspace_options(self):
        """Define el tramo comercial, conservando el soporte físico A4."""
        dialog = tk.Toplevel(self)
        dialog.title("Formato de venta")
        dialog.configure(background=COLORS.panel)
        dialog.transient(self)
        dialog.grab_set()
        ttk.Label(dialog, text="Formato de venta", style="Title.TLabel", padding=(18, 16, 18, 4)).pack(anchor="w")
        ttk.Label(dialog, text="El PNG final sigue siendo A4; el armado se limita al formato elegido.", style="Muted.TLabel", padding=(18, 0, 18, 10), wraplength=390).pack(anchor="w")
        choice = tk.StringVar(value=self.project.workspace_format)
        for key, (label, _ratio) in WORKSPACE_FORMATS.items():
            ttk.Radiobutton(dialog, text=label, value=key, variable=choice).pack(anchor="w", padx=18, pady=3)

        def confirm():
            self.project.workspace_format = choice.get()
            self.project.margin_cm = A5_PRINT_MARGIN_CM if choice.get() == "a5" else PRINT_MARGIN_CM
            self.workspace_button.configure(text={"a4": "A4", "a5": "A5", "franja": "1/5"}[choice.get()])
            self.format_heading.set(f"PLANCHA {self.project.workspace_label.upper()}")
            dialog.grab_release()
            dialog.destroy()
            self.optimize()

        buttons = ttk.Frame(dialog, padding=(18, 12, 18, 16))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Cancelar", command=lambda: (dialog.grab_release(), dialog.destroy())).pack(side="right")
        ttk.Button(buttons, text="Aplicar y acomodar", command=confirm, style="Plancha.Primary.TButton").pack(side="right", padx=(0, 8))

    def add_images(self):
        """Abre el selector visual de biblioteca para sumar diseños a la plancha."""
        self.open_add_designs()

    def _append_designs_to_plancha(self, images: list[dict], fill_gaps: bool = False) -> int:
        """Agrega solo archivos existentes y conserva su medida visible real.

        fill_gaps=True  → coloca cada sticker nuevo en el primer hueco libre
                          sin tocar los ya posicionados. Si alguno no entra,
                          se agrega igual y se lanza optimize() solo para los
                          que no encontraron lugar.
        fill_gaps=False → comportamiento original: agrega todos y reoptimiza.
        """
        new_items: list[PlanchaItem] = []
        for image in images:
            path = str(image.get("path") or "")
            if not path or not Path(path).is_file():
                continue
            supplied_nominal = image.get("nominal_size_cm") or image.get("order_size_cm")
            if False:  # La biblioteca inicia Mixta en el producto estándar 5 cm.
                nominal = simpledialog.askfloat(
                    "Plancha mixta", f"Tamaño nominal para «{image.get('name') or Path(path).stem}» (cm):",
                    parent=self, minvalue=0.5, maxvalue=MAX_SIZE_CM,
                )
                if nominal is None:
                    continue
            else:
                nominal = float(supplied_nominal or 5.0)
            width, height = size_for_record(image, nominal)
            
            # Rotación automática para stickers horizontales
            rotation = 0
            if width > height:
                width, height = height, width
                rotation = 90
            
            modern_layout = self.project.project_type in {"sticker_standard", "sticker_mixed", "sticker_free"}
            new_items.append(
                PlanchaItem(
                    path=path,
                    name=str(image.get("caption") or image.get("name") or "Diseño"),
                    width_cm=width,
                    height_cm=height,
                    nominal_size_cm=nominal,
                    rotation=rotation,
                    rotation_allowed=True,
                    layout_width_cm=width + 2 * HITBOX_INNER_CLEARANCE_CM if modern_layout else width + SPECIAL_LAYOUT_EXTRA_CM,
                    layout_height_cm=height + 2 * HITBOX_INNER_CLEARANCE_CM if modern_layout else height + SPECIAL_LAYOUT_EXTRA_CM,
                    source=str(image.get("source") or "Biblioteca"),
                )
            )

        if not new_items:
            return 0

        if self.project.project_type == "sticker_mixed":
            self.project.items.extend(new_items)
            self.regenerate_sticker_mixed()
            return len(new_items)

        if fill_gaps:
            # Colocar cada sticker en el primer hueco disponible.
            # Los que no encuentran espacio se acumulan para la reoptimización.
            overflow: list[PlanchaItem] = []
            for item in new_items:
                position = self.find_free_position(item.width_cm, item.height_cm)
                if position:
                    item.x_cm, item.y_cm = position
                    item.locked = False
                    self.project.items.append(item)
                else:
                    overflow.append(item)
            if overflow:
                # Solo reoptimiza si hay stickers que no entraron en huecos.
                self.project.items.extend(overflow)
                self.optimize()
            else:
                self.render()
        else:
            self.project.items.extend(new_items)
            if self.project.project_type == "sticker_mixed":
                self.regenerate_sticker_mixed()
            else:
                self.optimize()

        return len(new_items)

    def enable_sticker_mixed_mode(self) -> None:
        """Configura esta ficha como Mixta de stickers, sin tocar fotos."""
        self.project.project_type = "sticker_mixed"
        self.layout_mode = "special"
        self.project.layout_mode = "special"
        self.packing_mode = "sticker_mixed"
        self.format_heading.set("PLANCHA MIXTA")
        self.workspace_button.configure(text="Mixta")
        if hasattr(self, "regenerate_mixed_button"):
            self.regenerate_mixed_button.pack(side="left", padx=(2, 0))
        if hasattr(self, "convert_mixed_button"):
            self.convert_mixed_button.pack(side="left", padx=(2, 0))

    def convert_sticker_mixed_to_free(self) -> bool:
        """Congela la composición actual y habilita edición manual segura."""
        if self.project.project_type != "sticker_mixed":
            return False
        from app.planchas.sticker_mixed_conversion import convert_sticker_mixed_projects_to_free

        projects = self.all_projects or [self.project]
        convert_sticker_mixed_projects_to_free(projects)
        self.all_projects = projects
        self.project = projects[self.current_project_index]
        self.packing_mode = None
        self.format_heading.set("PLANCHA LIBRE")
        self.workspace_button.configure(text="Libre")
        if hasattr(self, "regenerate_mixed_button"):
            self.regenerate_mixed_button.pack_forget()
        if hasattr(self, "convert_mixed_button"):
            self.convert_mixed_button.pack_forget()
        if hasattr(self, "productive_resize_controls"):
            self.productive_resize_controls.pack(fill="x", pady=(SPACE.sm, 0))
        self.snapshot()
        self.render()
        self.status_message("Plancha mixta convertida a Libre. Posiciones y tamaños quedaron congelados.")
        return True

    def regenerate_sticker_mixed(self) -> bool:
        """Reejecuta el núcleo determinista de packing de stickers."""
        if self.project.project_type != "sticker_mixed":
            return False
        source_projects = self.all_projects or [self.project]
        source_items = [item for page in source_projects for item in page.items]
        if not source_items:
            self.status_message("Agregá diseños con tamaño nominal para generar la plancha mixta.")
            return False
        from app.planchas.sticker_mixed import StickerMixedPacker

        try:
            layout = StickerMixedPacker(margin_cm=self.project.margin_cm).pack(source_items)
        except ValueError as error:
            messagebox.showwarning("Plancha mixta", str(error), parent=self)
            return False

        if layout.impossible_items:
            details = "\n".join(
                f"• {item.get('name', 'Diseño')}: {item.get('impossible_reason', 'No producible en A4')}"
                for item in layout.impossible_items
            )
            messagebox.showwarning("Plancha mixta · No producible en A4", details, parent=self)
            return False

        self.all_projects = layout.projects
        self.max_planchas = layout.page_count
        self.current_project_index = 0
        self.plancha_number = 1
        self.project = self.all_projects[0]
        self.project.project_type = "sticker_mixed"
        self.snapshot()
        self.render()
        self.update_plancha_navigation()
        self.status_message(
            f"Mixta generada: {len(source_items)} copias · {layout.page_count} plancha(s)."
        )
        return True

    def add_files_from_computer(self, parent=None) -> None:
        """Permite sumar diseños locales sin modificar ni indexar el original."""
        paths = filedialog.askopenfilenames(
            parent=parent or self,
            title="Buscar archivos para agregar a la plancha",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"), ("Todos los archivos", "*.*")],
        )
        records = [{"path": path, "name": Path(path).name, "source": "Archivo externo"} for path in paths]
        self._append_designs_to_plancha(records)

    def open_add_designs(self) -> None:
        """Selector visual de biblioteca y archivos locales para el armado."""
        dialog = tk.Toplevel(self)
        dialog.title("Agregar diseños a la plancha")
        dialog.configure(background=COLORS.background)
        # Esta pantalla es de selección rápida: priorizamos resultados visibles
        # y conservamos una vista previa compacta para confirmar la elección.
        dialog.geometry("1000x610")
        dialog.minsize(850, 520)
        dialog.transient(self)
        dialog.grab_set()

        header = tk.Frame(dialog, background=COLORS.panel)
        header.pack(fill="x")
        header.grid_columnconfigure(0, weight=1)
        heading = tk.Frame(header, background=COLORS.panel)
        heading.grid(row=0, column=0, sticky="ew", padx=(22, 12), pady=12)
        tk.Label(
            heading,
            text="AGREGAR DISEÑOS",
            background=COLORS.panel,
            foreground=COLORS.text,
            font=(IDENTITY_FONT, 18, "bold"),
        ).pack(anchor="w")
        tk.Label(
            heading,
            text="Buscá por información del diseño, no por el nombre técnico del archivo.",
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 9),
        ).pack(anchor="w", pady=(1, 0))
        add_selection_text = tk.StringVar()
        add_selection_button = ttk.Button(header, textvariable=add_selection_text, style="Plancha.Primary.TButton")
        add_selection_button.grid(row=0, column=1, sticky="e", padx=22, pady=16)
        add_selection_button.grid_remove()

        filters = tk.Frame(dialog, background=COLORS.background)
        filters.pack(fill="x", padx=22, pady=(12, 6))
        for column in range(5):
            filters.grid_columnconfigure(column, weight=1 if column in (0, 2, 3) else 0)

        def field_label(text: str, column: int):
            tk.Label(filters, text=text, background=COLORS.background, foreground=COLORS.muted, font=(IDENTITY_FONT, 9, "bold")).grid(row=0, column=column, sticky="w", padx=(0, 8), pady=(0, 5))

        field_label("BUSCAR", 0)
        field_label("BUSCAR POR", 1)
        field_label("CATEGORÍA", 2)
        field_label("COLECCIÓN", 3)
        query_var = tk.StringVar()
        mode_var = tk.StringVar(value="Todo")
        category_var = tk.StringVar(value="Todas las categorías")
        collection_var = tk.StringVar(value="Todas las colecciones")
        query_box = ttk.Combobox(filters, textvariable=query_var)
        query_box.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        mode_box = ttk.Combobox(
            filters,
            textvariable=mode_var,
            state="readonly",
            values=("Todo", "Etiqueta", "Colección", "Personaje", "Color", "Categoría", "Top 100", "Favoritos comerciales", "Novedades"),
            width=22,
        )
        mode_box.grid(row=1, column=1, sticky="ew", padx=(0, 8))
        categories = ["Todas las categorías"]
        collections = ["Todas las colecciones"]
        if self.database:
            categories.extend(category for category, _count in self.database.category_counts())
            collections.extend(self.database.collection_names())
        category_box = ttk.Combobox(filters, textvariable=category_var, state="readonly", values=categories)
        category_box.grid(row=1, column=2, sticky="ew", padx=(0, 8))
        collection_box = ttk.Combobox(filters, textvariable=collection_var, state="readonly", values=collections)
        collection_box.grid(row=1, column=3, sticky="ew", padx=(0, 8))
        search_button = ttk.Button(filters, text="Buscar", style="Plancha.Primary.TButton")
        search_button.grid(row=1, column=4, sticky="ew")

        content = tk.Frame(dialog, background=COLORS.background)
        content.pack(fill="both", expand=True, padx=22, pady=(6, 8))
        content.grid_columnconfigure(0, weight=3)
        content.grid_columnconfigure(1, weight=2)
        content.grid_rowconfigure(0, weight=1)

        list_panel = tk.Frame(content, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        list_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        # Las miniaturas permiten reconocer cada diseño de inmediato; la lista
        # anterior de códigos obligaba a seleccionar primero para saber qué era.
        results = tk.Canvas(list_panel, background=COLORS.panel, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_panel, orient="vertical", command=results.yview)
        results.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y", padx=(0, 8), pady=8)
        results.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        cards_container = tk.Frame(results, background=COLORS.panel)
        cards_window = results.create_window((0, 0), window=cards_container, anchor="nw")

        # ── Panel de vista previa ────────────────────────────────────────────
        preview_panel = tk.Frame(
            content, background=COLORS.panel,
            highlightthickness=1, highlightbackground=COLORS.border, width=300,
        )
        preview_panel.grid(row=0, column=1, sticky="ns")
        preview_panel.grid_propagate(False)
        tk.Label(
            preview_panel, text="VISTA PREVIA",
            background=COLORS.panel, foreground=COLORS.muted,
            font=(IDENTITY_FONT, 9, "bold"),
        ).pack(anchor="w", padx=14, pady=(14, 8))
        tk.Label(
            preview_panel, text="Escala real · lado mayor: 5,70 cm",
            background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 9),
        ).pack(anchor="w", padx=14, pady=(0, 6))
        preview = tk.Canvas(preview_panel, background=COLORS.panel_elevated, highlightthickness=0, height=245)
        preview.pack(fill="x", padx=14, pady=(0, 8))
        preview_info = tk.Label(
            preview_panel, text="",
            background=COLORS.panel, foreground=COLORS.text,
            justify="left", anchor="nw", wraplength=190, font=(UI_FONT, 9),
        )
        preview_info.pack(fill="x", padx=14)

        # ── Pie de página ────────────────────────────────────────────────────
        footer = tk.Frame(dialog, background=COLORS.background)
        footer.pack(fill="x", padx=22, pady=(0, 12))
        selection_status = tk.StringVar(value="Seleccioná uno o más diseños para agregarlos.")
        tk.Label(
            footer, textvariable=selection_status,
            background=COLORS.background, foreground=COLORS.muted, font=(UI_FONT, 9),
        ).pack(side="left")
        ttk.Button(
            footer, text="Buscar en PC",
            style="Plancha.Secondary.TButton",
            command=lambda: self.add_files_from_computer(dialog),
        ).pack(side="right")
        ttk.Button(footer, text="Cerrar", style="Plancha.Secondary.TButton", command=dialog.destroy).pack(side="right", padx=(0, 8))

        result_state: list[dict] = []
        selected_indexes: set[int] = set()
        result_cards: dict[int, tk.Frame] = {}
        result_titles: dict[int, tk.Label] = {}
        result_thumbnails: list[object] = []  # Conserva las referencias Tk.
        result_thumbnail_labels: dict[int, tk.Label] = {}
        # Las tarjetas usan miniaturas de catálogo, que respetan la proporción
        # y se cargan por tandas. El pipeline de producción por tarjeta abre y
        # contornea el PNG completo y bloqueaba la apertura del selector.
        thumbnail_generation = [0]
        thumbnail_cursor = [0]
        # Identificador del after() pendiente para la predicción mientras se escribe.
        _pending_predict: list[str | None] = [None]

        def selected_records() -> list[dict]:
            return [result_state[index] for index in sorted(selected_indexes) if index < len(result_state)]

        def refresh_card_styles():
            for index, card in result_cards.items():
                selected = index in selected_indexes
                card.configure(
                    background=COLORS.wine_dark if selected else COLORS.panel_elevated,
                    highlightbackground=COLORS.wine_active if selected else COLORS.border,
                    highlightthickness=2 if selected else 1,
                )
                title = result_titles.get(index)
                if title:
                    title.configure(background=COLORS.wine_dark if selected else COLORS.panel_elevated)

        def select_record(index: int, event=None):
            control_pressed = bool(event and (event.state & 0x0004))
            if control_pressed:
                if index in selected_indexes:
                    selected_indexes.remove(index)
                else:
                    selected_indexes.add(index)
            else:
                selected_indexes.clear()
                selected_indexes.add(index)
            refresh_card_styles()
            update_preview()

        def update_preview(_event=None):
            selected = selected_records()
            if not selected:
                preview.delete("all")
                preview.create_text(160, 125, text="Elegí uno o más diseños", fill=COLORS.muted, font=(UI_FONT, 10))
                preview_info.configure(text="")
                add_selection_button.grid_remove()
                selection_status.set("Seleccioná uno o más diseños para agregarlos.")
                return
            image = selected[0]
            physical_px = max(1, round(dialog.winfo_fpixels("1c") * 5.70))
            canvas_width = max(300, physical_px + 34)
            canvas_height = physical_px + 46
            preview.configure(width=canvas_width, height=canvas_height)
            preview.delete("all")
            thumb = load_thumbnail(str(image.get("path") or ""), (physical_px, physical_px))
            if thumb:
                preview.create_image(canvas_width // 2, physical_px // 2 + 6, image=thumb)
                preview.image = thumb
            else:
                preview.create_text(canvas_width // 2, physical_px // 2, text="Sin vista previa", fill=COLORS.muted, font=(UI_FONT, 10))
                preview.image = None
            ruler_y = physical_px + 24
            left, right = (canvas_width - physical_px) // 2, (canvas_width + physical_px) // 2
            preview.create_line(left, ruler_y, right, ruler_y, fill=COLORS.wine_active, width=2)
            preview.create_line(left, ruler_y - 5, left, ruler_y + 5, fill=COLORS.wine_active, width=2)
            preview.create_line(right, ruler_y - 5, right, ruler_y + 5, fill=COLORS.wine_active, width=2)
            preview.create_text(canvas_width // 2, ruler_y + 13, text="5,70 cm", fill=COLORS.text, font=(UI_FONT, 9, "bold"))
            preview_info.configure(text="El lado mayor se muestra a 5,70 cm para comparar junto a la pantalla.")
            quantity = len(selected)
            selection_status.set(f"{quantity} diseño{'s' if quantity != 1 else ''} seleccionado{'s' if quantity != 1 else ''}.")
            add_selection_text.set(f"Agregar a plancha ({quantity}) diseño{'s' if quantity != 1 else ''}")
            if not add_selection_button.winfo_ismapped():
                add_selection_button.grid()

        def refresh_results(_event=None):
            nonlocal result_state
            thumbnail_generation[0] += 1
            if self.database:
                result_state = self.database.plancha_browser_images(
                    query=query_var.get(),
                    mode=mode_var.get(),
                    category=category_var.get(),
                    collection=collection_var.get(),
                    # Cargar cientos de miniaturas en una sola pasada degrada
                    # la apertura del selector; los filtros refinan la búsqueda.
                    limit=120,
                )
            else:
                query = query_var.get().strip().casefold()
                result_state = [
                    image for image in self.library_images
                    if not query or query in str(image.get("caption") or "").casefold() or query in str(image.get("tags") or "").casefold()
                ][:120]
            selected_indexes.clear()
            result_cards.clear()
            result_titles.clear()
            result_thumbnails.clear()
            result_thumbnail_labels.clear()
            for child in cards_container.winfo_children():
                child.destroy()
            for index, image in enumerate(()) :
                caption = str(image.get("caption") or "Diseño sin título")
                results.insert("", "end", iid=f"image:{index}", text=caption)
            for index, image in enumerate(result_state):
                column, row = index % 4, index // 4
                card = tk.Frame(cards_container, background=COLORS.panel_elevated,
                                highlightthickness=1, highlightbackground=COLORS.border,
                                cursor="hand2", width=126, height=156)
                card.grid(row=row, column=column, padx=5, pady=5, sticky="n")
                card.grid_propagate(False)
                image_label = tk.Label(
                    card, text="Cargando…", background=COLORS.panel_elevated,
                    foreground=COLORS.muted, cursor="hand2", height=7,
                )
                image_label.pack(padx=6, pady=(6, 3))
                result_thumbnail_labels[index] = image_label
                caption = str(image.get("caption") or "Diseño sin título")
                title = tk.Label(card, text=caption, background=COLORS.panel_elevated,
                                 foreground=COLORS.text, font=(UI_FONT, 8), wraplength=112,
                                 justify="center", cursor="hand2")
                title.pack(fill="x", padx=5)
                result_cards[index] = card
                result_titles[index] = title
                for widget in (card, image_label, title):
                    widget.bind("<Button-1>", lambda event, idx=index: select_record(idx, event))
                    widget.bind("<Double-Button-1>", lambda _event: add_selection())
            cards_container.update_idletasks()
            results.configure(scrollregion=results.bbox("all"))
            selection_status.set(f"{len(result_state)} diseños disponibles. Los nombres técnicos no se usan para buscar.")
            update_preview()
            thumbnail_cursor[0] = 0
            load_result_thumbnail_batch(thumbnail_generation[0])

        def load_result_thumbnail_batch(generation: int):
            """Carga pocas miniaturas por vuelta para no congelar Tk."""
            if generation != thumbnail_generation[0] or not dialog.winfo_exists():
                return
            end = min(thumbnail_cursor[0] + 4, len(result_state))
            for index in range(thumbnail_cursor[0], end):
                label = result_thumbnail_labels.get(index)
                if not label or not label.winfo_exists():
                    continue
                thumb = load_thumbnail(str(result_state[index].get("path") or ""), (112, 112))
                if thumb:
                    label.configure(image=thumb, text="", height=1)
                    result_thumbnails.append(thumb)
                else:
                    label.configure(text="Sin imagen")
            thumbnail_cursor[0] = end
            if thumbnail_cursor[0] < len(result_state):
                dialog.after(1, lambda: load_result_thumbnail_batch(generation))

        def update_suggestions(*_args):
            """Actualiza sugerencias del combobox y dispara predicción con debounce."""
            if not self.database:
                return
            term = query_var.get().strip()
            # Sugerencias del dropdown
            if len(term) >= 2:
                query_box["values"] = self.database.suggestions(term, limit=8)
            else:
                query_box["values"] = ()
            # Predicción automática: espera 180 ms desde la última tecla para
            # no relanzar la búsqueda completa en cada carácter escrito.
            if _pending_predict[0] is not None:
                try:
                    dialog.after_cancel(_pending_predict[0])
                except tk.TclError:
                    pass
            _pending_predict[0] = dialog.after(180, refresh_results)

        def open_rename_dialog(_event=None):
            """Permite renombrar el archivo físico y actualizar la base de datos."""
            selected = selected_records()
            if not selected:
                return
            image = selected[0]
            path = str(image.get("path") or "")
            if not path or not Path(path).is_file():
                messagebox.showwarning("Renombrar", "El archivo no está disponible.", parent=dialog)
                return
            current_stem = Path(path).stem
            new_stem = simpledialog.askstring(
                "Renombrar archivo",
                f"Nuevo nombre para «{current_stem}»\n(sin extensión):",
                initialvalue=current_stem,
                parent=dialog,
            )
            if not new_stem or new_stem.strip() == current_stem:
                return
            try:
                from app.rename.rename_engine import rename_image
                new_path = rename_image(path, new_stem.strip())
            except (ValueError, FileExistsError, OSError) as error:
                messagebox.showerror("No se pudo renombrar", str(error), parent=dialog)
                return
            # Actualizar la ruta en el registro de la base de datos si existe.
            if self.database:
                old_record = self.database.connection.execute(
                    "SELECT * FROM images WHERE path = ?", (path,)
                ).fetchone()
                if old_record:
                    record = dict(old_record)
                    record["path"] = str(new_path)
                    record["name"] = new_path.stem
                    self.database.remove_image(path)
                    self.database.upsert(record)
            # Actualizar el estado local para que el Treeview refleje el cambio.
            image["path"] = str(new_path)
            image["name"] = new_path.stem
            for idx in selected_indexes:
                if idx >= len(result_state):
                    continue
                caption = str(result_state[idx].get("caption") or new_path.stem)
                if idx in result_titles:
                    result_titles[idx].configure(text=caption)
            selection_status.set(f"Renombrado a «{new_path.stem}».")

        def add_selection(fill_gaps: bool = False, _event=None):
            selected = selected_records()
            if not selected:
                messagebox.showinfo("Agregar diseños", "Seleccioná al menos un diseño de la biblioteca.", parent=dialog)
                return
            added = self._append_designs_to_plancha(selected, fill_gaps=fill_gaps)
            if added:
                dialog.destroy()
            else:
                messagebox.showwarning(
                    "Agregar diseños",
                    "Los diseños elegidos ya no están disponibles en sus rutas originales.",
                    parent=dialog,
                )

        search_button.configure(command=refresh_results)
        add_selection_button.configure(command=lambda: add_selection(fill_gaps=False))
        cards_container.bind("<Configure>", lambda _event: results.configure(scrollregion=results.bbox("all")))
        results.bind("<Configure>", lambda event: results.itemconfigure(cards_window, width=event.width))
        results.bind("<MouseWheel>", lambda event: results.yview_scroll(-max(1, event.delta // 120), "units"))
        query_box.bind("<Return>", refresh_results)
        mode_box.bind("<<ComboboxSelected>>", refresh_results)
        category_box.bind("<<ComboboxSelected>>", refresh_results)
        collection_box.bind("<<ComboboxSelected>>", refresh_results)
        query_var.trace_add("write", update_suggestions)
        dialog.bind("<Return>", lambda _event: add_selection() if selected_indexes else refresh_results())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        refresh_results()
        query_box.focus_set()

    def find_free_position(self, width_cm: float, height_cm: float, bottom_limit: float | None = None) -> tuple[float, float] | None:
        step = min(0.25, self.project.gap_cm)
        margin = self.project.margin_cm
        right_limit = A4_WIDTH_CM - margin
        workspace_bottom = self.project.workspace_bottom_cm
        bottom_limit = min(workspace_bottom, bottom_limit or workspace_bottom)

        # Primero intentar colocar en la misma línea (y_cm) que los items
        # existentes, para que el nuevo sticker quede alineado con su fila.
        existing_ys: list[float] = sorted(
            {item.y_cm for item in self.project.items},
            key=lambda v: v,
        )
        for row_y in existing_ys:
            if row_y + height_cm > bottom_limit + 0.001:
                continue
            x = margin
            while x + width_cm <= right_limit + 0.001:
                trial = PlanchaItem(path="", name="", width_cm=width_cm, height_cm=height_cm)
                if self.can_place(trial, x, row_y):
                    return round(x, 3), round(row_y, 3)
                x += step

        # Si no hay hueco en ninguna fila existente, escanear libremente.
        y = margin
        while y + height_cm <= bottom_limit + 0.001:
            x = margin
            while x + width_cm <= right_limit + 0.001:
                trial = PlanchaItem(path="", name="", width_cm=width_cm, height_cm=height_cm)
                if self.can_place(trial, x, y):
                    return round(x, 3), round(y, 3)
                x += step
            y += step
        return None

    def fill_proposals(self) -> list[dict]:
        """Busca opciones reutilizables que entren realmente en los huecos."""
        proposals = []
        blocked = ("exclusivo", "no reutilizable", "privado", "no usar para completar")
        # Se recorre una muestra repartida de la biblioteca: permite encontrar
        # rellenos variados sin congelar la interfaz en bibliotecas grandes.
        max_candidates = 320
        if self.database:
            candidates = self.database.fill_candidates(limit=max_candidates)
        elif len(self.library_images) > max_candidates:
            step = len(self.library_images) / max_candidates
            candidates = [self.library_images[int(index * step)] for index in range(max_candidates)]
        else:
            candidates = self.library_images
        for image in candidates:
            tags = (image.get("tags") or "").casefold()
            if any(word in tags for word in blocked):
                continue
            path = image["path"]
            if path not in self.fill_size_cache:
                self.fill_size_cache[path] = size_for_record(image)
            width, height = self.fill_size_cache[path]
            
            # Rotación automática para stickers horizontales
            rotation = 0
            if width > height:
                width, height = height, width
                rotation = 90
            
            count = 0
            temporary: list[PlanchaItem] = []
            while True:
                position = self.find_free_position(width, height)
                if not position:
                    break
                trial = PlanchaItem(path=image["path"], name=image.get("name") or Path(image["path"]).name, width_cm=width, height_cm=height, x_cm=position[0], y_cm=position[1], rotation=rotation, rotation_allowed=True, source="Relleno")
                self.project.items.append(trial)
                temporary.append(trial)
                count += 1
                if count >= 20:
                    break
            for trial in temporary:
                self.project.items.remove(trial)
            if count:
                area = count * width * height * 100 / (self.project.usable_width * self.project.usable_height)
                proposals.append({
                    "image": image,
                    "width": width,
                    "height": height,
                    "count": count,
                    "occupancy": area,
                    "origin": image.get("fill_origin", "Biblioteca reutilizable"),
                    "priority": image.get("fill_priority", 3),
                })
            # Una selección amplia deja margen para combinar formatos distintos.
            if len(proposals) >= 80:
                break
        return proposals

    @staticmethod
    def completion_options() -> list[tuple[str, float]]:
        """Alcances de producción expresados como alto útil de la A4."""
        return [
            ("1 franja de stickers", 1 / 5),
            ("2 franjas de stickers", 2 / 5),
            ("3 franjas de stickers", 3 / 5),
            ("4 franjas de stickers", 4 / 5),
            ("5 franjas de stickers", 1.0),
            ("Hoja A5 (media A4)", 1 / 2),
            ("1/4 de plancha", 1 / 4),
            ("Plancha A4 completa", 1.0),
        ]

    def show_completion_options(self):
        """Permite completar solo la porción de material que se va a imprimir."""
        dialog = tk.Toplevel(self)
        dialog.title("Completar plancha")
        dialog.configure(background=COLORS.panel)
        dialog.transient(self)
        dialog.grab_set()
        ttk.Label(dialog, text="¿Qué parte querés completar?", style="Title.TLabel", padding=(18, 16, 18, 4)).pack(anchor="w")
        ttk.Label(dialog, text="El relleno se limita a esa zona de la A4. No agrega stickers debajo del corte elegido.", style="Muted.TLabel", padding=(18, 0, 18, 10), wraplength=360).pack(anchor="w")
        choice = tk.StringVar(value="5 franjas de stickers")
        for label, _ratio in self.completion_options():
            ttk.Radiobutton(dialog, text=label, value=label, variable=choice).pack(anchor="w", padx=18, pady=2)

        def confirm():
            selected = choice.get()
            ratio = next(ratio for label, ratio in self.completion_options() if label == selected)
            dialog.grab_release()
            dialog.destroy()
            self.complete_spaces(target_ratio=ratio, target_label=selected)

        buttons = ttk.Frame(dialog, padding=(18, 12, 18, 16))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Cancelar", command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text="Completar", command=confirm, style="Plancha.Primary.TButton").pack(side="right", padx=(0, 8))

    def complete_spaces(self, target_ratio: float = 1.0, target_label: str = "Plancha A4 completa"):
        """Combina rellenos sin superar el tramo de A4 elegido para producción."""
        proposals = self.fill_proposals()
        if not proposals:
            messagebox.showinfo("Completar espacios", "No encontré diseños reutilizables que entren en los huecos actuales.", parent=self)
            return

        # Cada iteración revisa qué formato entra en el hueco real que queda.
        # Se privilegia llegar a 97,5 %, pero nunca se superan los límites A4;
        # el pequeño bonus por diseños aún no usados evita repetir uno solo.
        target_ratio = min(1.0, max(0.0, target_ratio))
        target = 97.5 * target_ratio
        minimum_target = 95.0 * target_ratio
        bottom_limit = self.project.margin_cm + self.project.usable_height * target_ratio
        used_paths: set[str] = set()
        added = 0
        chosen_names: list[str] = []
        chosen_origins: list[str] = []
        while self.project.occupancy() < minimum_target and added < 120:
            current = self.project.occupancy()
            choices = []
            for proposal in proposals:
                position = self.find_free_position(proposal["width"], proposal["height"], bottom_limit=bottom_limit)
                if not position:
                    continue
                contribution = proposal["width"] * proposal["height"] * 100 / (self.project.usable_width * self.project.usable_height)
                projected = current + contribution
                if projected > 100.001:
                    continue
                path = proposal["image"]["path"]
                variety_bonus = 0.12 if path not in used_paths else 0.0
                # La superficie aprovechada manda; el origen solo desempata entre
                # opciones igualmente buenas, sin imponer un orden rígido.
                origin_bonus = max(0, 3 - proposal.get("priority", 3)) * 0.01
                score = -abs(target - projected) + variety_bonus + origin_bonus
                choices.append((score, proposal, position))
            if not choices:
                break
            _score, proposal, position = max(choices, key=lambda choice: choice[0])
            image = proposal["image"]
            path = image["path"]
            
            # Rotación automática para stickers horizontales
            item_width = proposal["width"]
            item_height = proposal["height"]
            rotation = 0
            if item_width > item_height:
                item_width, item_height = item_height, item_width
                rotation = 90
            
            self.project.items.append(PlanchaItem(
                path=path,
                name=image.get("name") or Path(path).name,
                width_cm=item_width,
                height_cm=item_height,
                x_cm=position[0],
                y_cm=position[1],
                quantity=1,
                copy_number=1,
                group_id=uuid.uuid4().hex,
                rotation=rotation,
                rotation_allowed=True,
                source="Relleno",
            ))
            used_paths.add(path)
            chosen_names.append(image.get("name") or Path(path).name)
            chosen_origins.append(proposal["origin"])
            added += 1
        if not added:
            messagebox.showinfo("Completar espacios", "No quedó un hueco compatible para completar.", parent=self)
            return
        # No se reordena después: cada pieza ya fue colocada específicamente en
        # un hueco libre y se conserva esa distribución más eficiente.
        # En formatos parciales la zona libre debajo es intencional: repartir
        # las filas en toda la A4 movería los stickers fuera del A5/franjas
        # seleccionados.
        if target_ratio >= 1.0:
            self.project.justify_rows()
        self.snapshot()
        self.render()
        variety = len(set(chosen_names))
        origins: dict[str, int] = {}
        for origin in chosen_origins:
            origins[origin] = origins.get(origin, 0) + 1
        sources_text = " · ".join(f"{origin}: {count}" for origin, count in origins.items())
        messagebox.showinfo(
            "Nota de producción · Completar plancha",
            f"Alcance: {target_label}.\n\nEl optimizador incorporó {added} sticker(s) de {variety} diseño(s) para llegar a {self.project.occupancy():.1f}% de ocupación total.\n\n"
            f"Origen: {sources_text or 'Biblioteca'}.\n"
            "La combinación fue elegida por aprovechamiento real del espacio. Revisá la plancha y cerrá esta nota para continuar.",
            parent=self,
        )

    def add_fill_proposal(self, proposal: dict) -> int:
        """Inserta una propuesta hasta que ya no entre, sin crear superposiciones."""
        group_id = uuid.uuid4().hex
        added = 0
        
        # Rotación automática para stickers horizontales
        item_width = proposal["width"]
        item_height = proposal["height"]
        rotation = 0
        if item_width > item_height:
            item_width, item_height = item_height, item_width
            rotation = 90
        
        for copy_number in range(1, proposal["count"] + 1):
            position = self.find_free_position(item_width, item_height)
            if not position:
                break
            image = proposal["image"]
            self.project.items.append(PlanchaItem(path=image["path"], name=image.get("name") or Path(image["path"]).name, width_cm=item_width, height_cm=item_height, x_cm=position[0], y_cm=position[1], quantity=proposal["count"], copy_number=copy_number, group_id=group_id, rotation=rotation, rotation_allowed=True, source="Relleno"))
            added += 1
        return added

    def show_fill_proposals(self):
        proposals = self.fill_proposals()
        if not proposals:
            messagebox.showinfo("Completar espacios", "No encontré diseños reutilizables que entren en los huecos actuales.", parent=self)
            return
        dialog = tk.Toplevel(self)
        dialog.title("Propuesta para completar espacios")
        dialog.configure(background="#080909")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("680x650")
        dialog.minsize(560, 420)
        ttk.Label(dialog, text="Propuesta para completar espacios", style="Title.TLabel", padding=(16, 12, 16, 4)).pack(anchor="w")
        ttk.Label(dialog, text=f"{len(proposals)} diseños compatibles. Elegí los que quieras agregar; solo se muestran los que entran y son reutilizables.", style="Muted.TLabel", padding=(16, 0, 16, 8), wraplength=620).pack(anchor="w")
        list_area = tk.Frame(dialog, background="#080909")
        list_area.pack(fill="both", expand=True, padx=12)
        list_canvas = tk.Canvas(list_area, background="#080909", highlightthickness=0)
        list_scroll = ttk.Scrollbar(list_area, orient="vertical", command=list_canvas.yview)
        list_canvas.configure(yscrollcommand=list_scroll.set)
        list_content = tk.Frame(list_canvas, background="#080909")
        list_canvas.create_window((0, 0), window=list_content, anchor="nw")
        list_content.bind("<Configure>", lambda _event: list_canvas.configure(scrollregion=list_canvas.bbox("all")))
        list_canvas.pack(side="left", fill="both", expand=True)
        list_scroll.pack(side="right", fill="y")
        options = []
        thumbnails = []
        for index, proposal in enumerate(proposals):
            row = tk.Frame(list_content, background="#080909")
            row.pack(fill="x", padx=4, pady=4)
            value = tk.BooleanVar(value=index == 0)
            tk.Checkbutton(row, variable=value, background="#080909", activebackground="#080909", selectcolor="#d60916").pack(side="left")
            thumb = load_visible_thumbnail(proposal["image"]["path"], (50, 50))
            if thumb:
                tk.Label(row, image=thumb, background="#080909").pack(side="left", padx=5)
                thumbnails.append(thumb)
            name = proposal["image"].get("name") or Path(proposal["image"]["path"]).name
            ttk.Label(row, text=f"{name}\n{proposal['width']:g} × {proposal['height']:g} cm · entran hasta {proposal['count']} · {proposal['origin']} · +{proposal['occupancy']:.1f}%", wraplength=455, justify="left").pack(side="left", fill="x", expand=True)
            options.append((proposal, value))
        dialog.thumbnails = thumbnails

        def confirm():
            selected = [proposal for proposal, value in options if value.get()]
            if not selected:
                dialog.destroy()
                return
            for proposal in selected:
                group_id = uuid.uuid4().hex
                
                # Rotación automática para stickers horizontales
                item_width = proposal["width"]
                item_height = proposal["height"]
                rotation = 0
                if item_width > item_height:
                    item_width, item_height = item_height, item_width
                    rotation = 90
                
                for copy_number in range(1, proposal["count"] + 1):
                    position = self.find_free_position(item_width, item_height)
                    if not position:
                        break
                    image = proposal["image"]
                    self.project.items.append(PlanchaItem(path=image["path"], name=image.get("name") or Path(image["path"]).name, width_cm=item_width, height_cm=item_height, x_cm=position[0], y_cm=position[1], quantity=proposal["count"], copy_number=copy_number, group_id=group_id, rotation=rotation, rotation_allowed=True, source="Relleno"))
            self.optimize()
            dialog.grab_release()
            dialog.destroy()

        ttk.Button(dialog, text="Agregar seleccionados", command=confirm).pack(anchor="e", padx=16, pady=14)

    def prepared_production_sticker(self, item: PlanchaItem, target: tuple[int, int], modified: float | None = None):
        """Carga y prepara una vez cada variante del sticker de producción."""
        if modified is None:
            try:
                modified = Path(item.path).stat().st_mtime
            except OSError:
                modified = -1.0
        cache_key = (item.path, modified, target[0], target[1], item.rotation,
                     item.remove_inner_white_border, "contorno-v5")
        sticker = self.production_sticker_cache.get(cache_key)
        if sticker is not None:
            self.production_sticker_cache.move_to_end(cache_key)
            return sticker

        from PIL import Image
        with Image.open(item.path) as original:
            sticker = original.convert("RGBA")
        sticker = sticker.crop(visible_bbox(sticker))
        outlined = needs_silhouette_outline(sticker)
        if item.rotation:
            sticker = sticker.rotate(-item.rotation, expand=True)
        sticker = prepare_sticker_for_target(
            sticker, target, outlined=outlined,
            remove_inner_white_border=item.remove_inner_white_border,
        )
        pixels = sticker.width * sticker.height
        while self.production_sticker_cache and self.production_sticker_cache_pixels + pixels > 30_000_000:
            _old_key, old = self.production_sticker_cache.popitem(last=False)
            self.production_sticker_cache_pixels -= old.width * old.height
        self.production_sticker_cache[cache_key] = sticker
        self.production_sticker_cache_pixels += pixels
        return sticker

    def render_sheet(self, preview: bool = False, progress=None):
        from PIL import Image, ImageDraw

        self.project.keep_inside_print_area()
        dpi = 300
        # La plancha de producción se entrega como un único PNG A4 transparente:
        # solo diseños, sin celdas, guías ni información de UI.
        sheet = Image.new(
            "RGBA",
            (round(A4_WIDTH_CM / 2.54 * dpi), round(A4_HEIGHT_CM / 2.54 * dpi)),
            "white" if preview else (0, 0, 0, 0),
        )
        # Una misma imagen puede aparecer varias veces en la plancha. La copia
        # ya preparada se reutiliza sin volver a abrir, recortar ni contornear.
        total_items = len(self.project.items)
        for index, item in enumerate(self.project.items, start=1):
            if progress:
                progress(index - 1, total_items, f"Preparando diseño {index} de {total_items}")
            try:
                geometry = preview_geometry(item, self.current_project_index + 1)
                target = (
                    max(1, round(geometry["production_width_cm"] / 2.54 * dpi)),
                    max(1, round(geometry["production_height_cm"] / 2.54 * dpi)),
                )
                try:
                    modified = Path(item.path).stat().st_mtime
                except OSError:
                    modified = -1.0
                cache_key = (
                    item.path, modified, target[0], target[1], item.rotation,
                    item.remove_inner_white_border, "contorno-v5",
                )
                sticker = self.prepared_production_sticker(item, target, modified)
                if sticker is None:
                    with Image.open(item.path) as original:
                        sticker = original.convert("RGBA")
                    # La copia temporal se recorta a la silueta visible: los
                    # márgenes transparentes del archivo no consumen área física.
                    sticker = sticker.crop(visible_bbox(sticker))
                    # La forma se decide antes de rotar: un rectángulo girado
                    # sigue siendo rectangular y no debe recibir borde interno.
                    outlined = needs_silhouette_outline(sticker)
                    if item.rotation:
                        sticker = sticker.rotate(-item.rotation, expand=True)
                    sticker = prepare_sticker_for_target(
                        sticker, target, outlined=outlined,
                        remove_inner_white_border=item.remove_inner_white_border,
                    )
                    pixels = sticker.width * sticker.height
                    # Unos 120 MB RGBA como máximo. Las entradas menos usadas
                    # salen primero y se mantienen las de la plancha actual.
                    while self.production_sticker_cache and self.production_sticker_cache_pixels + pixels > 30_000_000:
                        _old_key, old = self.production_sticker_cache.popitem(last=False)
                        self.production_sticker_cache_pixels -= old.width * old.height
                    self.production_sticker_cache[cache_key] = sticker
                    self.production_sticker_cache_pixels += pixels
                else:
                    self.production_sticker_cache.move_to_end(cache_key)
                # Las dimensiones de la plancha ya respetan proporción; solo
                # se centra la copia temporal dentro de esa caja de producción.
                x = round(geometry["design_x_cm"] / 2.54 * dpi) + (target[0] - sticker.width) // 2
                y = round(geometry["design_y_cm"] / 2.54 * dpi) + (target[1] - sticker.height) // 2
                sheet.alpha_composite(sticker, (x, y))
            except Exception:
                continue
            finally:
                if progress:
                    progress(index, total_items, f"Procesando diseño {index} de {total_items}")
        if preview:
            draw = ImageDraw.Draw(sheet)
            for item in self.project.items:
                x1, y1 = round(item.x_cm / 2.54 * dpi), round(item.y_cm / 2.54 * dpi)
                x2, y2 = x1 + round(item.width_cm / 2.54 * dpi), y1 + round(item.height_cm / 2.54 * dpi)
                draw.rectangle((x1, y1, x2, y2), outline=item.client_color if item.client else "#777777", width=5)
            watermark = "VISTA PREVIA — NO IMPRIMIR"
            draw.text((80, sheet.height // 2), watermark, fill=(210, 9, 22, 110), stroke_width=2)
        return sheet

    def export_preview(self, silent: bool = False):
        if not self.project.items:
            return
        if self.database and not self.plancha_id:
            if not silent:
                messagebox.showwarning("Vista previa", "Guardá primero el proyecto editable para vincular la aprobación a esta plancha.", parent=self)
            return
        material = "Vinilo"
        if self.database and self.order_id:
            material = (self.database.order(self.order_id) or {}).get("material") or material
        path = filedialog.asksaveasfilename(title="Guardar vista previa", defaultextension=".jpg", filetypes=[("JPG", "*.jpg")])
        if not path:
            return
        sheet = self.render_client_preview()
        sheet.save(path, "JPEG", quality=95, subsampling=0, dpi=(300, 300), icc_profile=None)
        if self.database and self.plancha_id:
            self.database.request_plancha_approval(self.plancha_id, path)
            self._sync_open_order_after_approval()
            self.refresh_approval_panel()
            self.refresh_printing_panel()
        if not silent:
            messagebox.showinfo("Vista previa", f"Vista previa JPG creada para {material}. Se registró como pendiente de aprobación y no reemplaza la plancha final.", parent=self)

    def save_preview_in_order(self):
        """Genera y conserva una referencia visual dentro del pedido vinculado sin hitboxes."""
        if not self.project.items:
            messagebox.showinfo("Vista del pedido", "Agregá al menos un diseño antes de guardar la vista previa.", parent=self)
            return
        if not self.database:
            messagebox.showwarning("Vista del pedido", "No se pudo acceder a la base de datos de pedidos.", parent=self)
            return
        order_id = self._linked_order_id()
        if not order_id or not self.database.order(order_id):
            messagebox.showwarning("Vista del pedido", "Vinculá esta plancha a un pedido antes de guardar la vista previa.", parent=self)
            return
        try:
            root = Path(__file__).resolve().parents[2]
            folder = root / "outputs" / "pedidos" / f"pedido_{order_id}" / "vistas_previas"
            folder.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            plancha_label = self.plancha_id or "borrador"
            output = folder / f"vista_pedido_{order_id}_plancha_{plancha_label}_{stamp}.jpg"
            
            # La vista que queda en el pedido usa la misma protección que se
            # comparte con el cliente, nunca el PNG apto para producción.
            sheet = self.render_client_preview()
            sheet.save(
                output, "JPEG", quality=95, subsampling=0, dpi=(300, 300), icc_profile=None,
            )
            
            self.database.save_order_preview(order_id, str(output), self.plancha_id)
            self.order_id = order_id
            self._sync_open_order_after_approval()
            self.status_message(f"Vista previa guardada dentro del pedido #{order_id}.")
            messagebox.showinfo("Vista del pedido", f"La vista previa se guardó en el pedido #{order_id}.", parent=self)
        except OSError as error:
            messagebox.showerror("Vista del pedido", f"No se pudo guardar la vista previa: {error}", parent=self)

    def render_client_preview(self):
        """Renderiza una vista de cliente, aplanada y no reutilizable para impresión."""
        from PIL import Image, ImageDraw, ImageFont
        
        self.project.keep_inside_print_area()
        dpi = 300
        target_size = (round(A4_WIDTH_CM / 2.54 * dpi), round(A4_HEIGHT_CM / 2.54 * dpi))
        
        # Cargar fondo de Doccione y ajustar al tamaño A4
        try:
            background_path = Path(__file__).parents[1] / "assets" / "fondo_doccione_bw.png"
            with Image.open(background_path) as bg:
                background = bg.convert("RGB")
                # Redimensionar el fondo para cubrir el área A4 a 300 DPI
                background = background.resize(target_size, Image.Resampling.LANCZOS)
        except Exception:
            # Fallback a fondo blanco si no se encuentra el asset
            background = Image.new("RGB", target_size, "white")
        
        # Crear capa transparente para los diseños
        sheet = Image.new("RGBA", target_size, (0, 0, 0, 0))
        
        # Renderizar cada item sin hitboxes
        for item in self.project.items:
            try:
                target = (max(1, round(item.width_cm / 2.54 * dpi)), max(1, round(item.height_cm / 2.54 * dpi)))
                try:
                    modified = Path(item.path).stat().st_mtime
                except OSError:
                    modified = -1.0
                cache_key = (
                    item.path, modified, target[0], target[1], item.rotation,
                    item.remove_inner_white_border, "contorno-v5",
                )
                sticker = self.prepared_production_sticker(item, target, modified)
                if sticker is None:
                    with Image.open(item.path) as original:
                        sticker = original.convert("RGBA")
                    sticker = sticker.crop(visible_bbox(sticker))
                    outlined = needs_silhouette_outline(sticker)
                    if item.rotation:
                        sticker = sticker.rotate(-item.rotation, expand=True)
                    sticker = prepare_sticker_for_target(
                        sticker, target, outlined=outlined,
                        remove_inner_white_border=item.remove_inner_white_border,
                    )
                    pixels = sticker.width * sticker.height
                    while self.production_sticker_cache and self.production_sticker_cache_pixels + pixels > 30_000_000:
                        _old_key, old = self.production_sticker_cache.popitem(last=False)
                        self.production_sticker_cache_pixels -= old.width * old.height
                    self.production_sticker_cache[cache_key] = sticker
                    self.production_sticker_cache_pixels += pixels
                else:
                    self.production_sticker_cache.move_to_end(cache_key)
                
                x = round((item.x_cm + (item.reserved_width_cm - item.width_cm) / 2) / 2.54 * dpi) + (target[0] - sticker.width) // 2
                y = round((item.y_cm + (item.reserved_height_cm - item.height_cm) / 2) / 2.54 * dpi) + (target[1] - sticker.height) // 2
                sheet.alpha_composite(sticker, (x, y))
            except Exception:
                continue
        
        # Componer la capa de diseños sobre el fondo de Doccione. Luego se
        # aplica una segunda marca encima de los diseños: quitar sólo el fondo
        # no deja los stickers limpios ni listos para reutilizar.
        background.paste(sheet, (0, 0), sheet)
        overlay = Image.new("RGBA", target_size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        try:
            font = ImageFont.truetype("arialbd.ttf", 56)
        except OSError:
            font = ImageFont.load_default()
        identifier = f"VISTA PREVIA · DOCCIONE · NO IMPRIMIBLE · {time.strftime('%Y-%m-%d %H:%M')}"
        step_y = max(210, target_size[1] // 12)
        for y in range(70, target_size[1], step_y):
            # Doble trazo semitransparente para que siga visible sobre fondos
            # claros y oscuros sin ocultar completamente el diseño.
            draw.text((55, y), identifier, font=font, fill=(70, 70, 70, 118), stroke_width=2, stroke_fill=(255, 255, 255, 105))
        background = Image.alpha_composite(background.convert("RGBA"), overlay).convert("RGB")
        return background

    def export_svg(self):
        """Exporta la plancha final como SVG portable.

        Los stickers pueden ser PNG y contener transparencias, sombras o bordes
        ya rasterizados. Para no alterar el resultado de impresión, el SVG los
        incorpora como una imagen PNG embebida, a escala física A4.
        """
        if not self.project.items:
            messagebox.showinfo("Guardar SVG", "Agregá al menos un diseño antes de exportar.", parent=self)
            return

        path = filedialog.asksaveasfilename(
            title="Guardar plancha final como SVG",
            defaultextension=".svg",
            filetypes=[("SVG", "*.svg")],
        )
        if not path:
            return

        try:
            from io import BytesIO

            sheet = self.render_sheet(preview=False)
            png_buffer = BytesIO()
            sheet.save(png_buffer, "PNG", dpi=(300, 300), compress_level=3)
            encoded_png = base64.b64encode(png_buffer.getvalue()).decode("ascii")
            width, height = sheet.size
            svg = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{A4_WIDTH_CM * 10:g}mm" '
                f'height="{A4_HEIGHT_CM * 10:g}mm" viewBox="0 0 {width} {height}">\n'
                f'  <image width="{width}" height="{height}" href="data:image/png;base64,{encoded_png}"/>\n'
                '</svg>\n'
            )
            Path(path).write_text(svg, encoding="utf-8")
        except (OSError, ValueError) as error:
            messagebox.showerror("Guardar SVG", f"No se pudo guardar la plancha como SVG:\n{error}", parent=self)
            return

        self.status_message(f"SVG final guardado: {Path(path).name}")
        messagebox.showinfo(
            "SVG final guardado",
            "La plancha se guardó como SVG con el PNG de producción embebido.\n\n"
            f"{path}",
            parent=self,
        )

    def export_final(self, silent: bool = False, custom_path: str | None = None):
        if not self.project.items:
            return
        if not silent and len(self.all_projects) > 1:
            # En un trabajo paginado, el botón habitual de guardado debe
            # registrar el trabajo completo; nunca una sola página aislada.
            self.save_all_planchas()
            return
        if self.database and self.plancha_id and self._linked_order_id():
            approval = (self.database.plancha_project(self.plancha_id) or {}).get("approval_status")
            if approval != "Aprobada" and not silent:
                messagebox.showwarning("Exportación final", "La plancha debe estar aprobada antes de generar el PNG final.", parent=self)
                return
        
        # Usar ruta personalizada si se proporciona
        if custom_path:
            output = Path(custom_path)
            output.parent.mkdir(parents=True, exist_ok=True)
        else:
            root = Path(__file__).resolve().parents[2]
            order_id = self._linked_order_id()
            folder = root / "outputs" / "planchas_finales"
            if order_id:
                folder = root / "outputs" / "pedidos" / f"pedido_{order_id}" / "planchas_finales"
            folder.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            plancha_label = self.plancha_id or "borrador"
            output = folder / f"plancha_{plancha_label}_{stamp}.png"
        
        export_started = time.perf_counter()
        export_completed = False
        
        if not silent:
            progress_dialog, report_progress = self.creation_progress_dialog(len(self.project.items), "Exportando PNG final")
            report_progress(0, len(self.project.items), "Preparando exportación a 300 DPI")
        
        try:
            sheet = self.render_sheet(preview=False, progress=report_progress if not silent else None)
            if not silent:
                report_progress(len(self.project.items), len(self.project.items), "Guardando PNG final")
            # PNG sigue siendo totalmente sin pérdida; una compresión moderada
            # solo reduce el tiempo de guardado y puede generar un archivo algo mayor.
            sheet.save(output, "PNG", dpi=(300, 300), compress_level=3)
            export_completed = True
            if not silent:
                report_progress(len(self.project.items) + 1, len(self.project.items) + 1, "PNG final listo")
        finally:
            record_performance(
                "export_final_png",
                (time.perf_counter() - export_started) * 1000,
                stickers=len(self.project.items), completed=export_completed,
            )
            if not silent:
                self.after(180, lambda: progress_dialog.destroy() if progress_dialog.winfo_exists() else None)
        if self.database:
            self.database.record_plancha_usage([item.to_dict() for item in self.project.items])
            self.final_png_path = str(output)
            # "Guardar PNG final" es el cierre del armado manual. Hasta acá
            # solo escribía el archivo si la plancha todavía era un borrador,
            # por lo que no había ningún registro que mostrar en Producción.
            if not silent:
                if not self.project_path:
                    self.project_path = str(output.with_suffix(".doccione-plancha.json"))
                self.project.save(self.project_path)
                order_id = self._linked_order_id()
                material = ""
                if order_id:
                    material = (self.database.order(order_id) or {}).get("material", "")
                self.plancha_id = self.database.save_plancha_project(
                    order_id, Path(self.project_path).stem, material,
                    json.dumps(self.project.to_dict(), ensure_ascii=False),
                    self.project_path, self.plancha_id, self.person_name, self.person_phone,
                    self.project.workspace_format,
                )
                self.database.set_plancha_final_png(self.plancha_id, self.final_png_path)
                self.database.update_plancha_production_status(self.plancha_id, "lista")
            elif self.plancha_id:
                self.database.set_plancha_final_png(self.plancha_id, self.final_png_path)
        self.refresh_printing_panel()
        self.refresh_approval_panel()
        if not silent:
            messagebox.showinfo("PNG final guardado", f"El PNG final quedó listo para Producción.\n\n{output}", parent=self)

    def send_batch_to_continuous(self):
        """Genera y registra el conjunto actual para abrirlo como lote continuo.

        El armado permanece en esta única ventana; el usuario no tiene que abrir
        ni guardar una por una las planchas antes de pasar a producción.
        """
        projects = self.all_projects or [self.project]
        if not self.database:
            messagebox.showwarning("Producción continua", "Se requiere la base de datos para enviar un lote a producción continua.", parent=self)
            return
        if not projects:
            return
        if not messagebox.askyesno(
            "Enviar lote a producción continua",
            f"Se generarán y registrarán {len(projects)} plancha(s) para abrirlas juntas en Producción continua.",
            parent=self,
        ):
            return

        order_id = self._linked_order_id()
        material = ((self.database.order(order_id) or {}).get("material") or "") if order_id else ""
        batch_id = uuid.uuid4().hex
        root = Path(__file__).resolve().parents[2]
        folder = root / "outputs" / "lotes_continuos" / batch_id
        folder.mkdir(parents=True, exist_ok=True)
        original_project, original_index = self.project, self.current_project_index
        original_plancha_id, original_final_path = self.plancha_id, self.final_png_path
        plancha_ids: list[int] = []

        progress_dialog, report_progress = self.creation_progress_dialog(len(projects), "Preparando lote para producción continua")
        try:
            for index, project in enumerate(projects, start=1):
                report_progress(index - 1, len(projects), f"Generando plancha {index} de {len(projects)}")
                project_path = folder / f"plancha_{index:02d}.doccione-plancha.json"
                final_path = folder / f"plancha_{index:02d}.png"
                project.save(project_path)
                plancha_id = self.database.save_plancha_project(
                    order_id, f"Lote {batch_id[:8]} · Plancha {index}", material,
                    json.dumps(project.to_dict(), ensure_ascii=False), str(project_path), None,
                )
                self.project = project
                sheet = self.render_sheet(preview=False)
                sheet.save(final_path, "PNG", dpi=(300, 300), compress_level=3)
                self.database.set_plancha_final_png(plancha_id, str(final_path))
                plancha_ids.append(plancha_id)
                report_progress(index, len(projects), f"Plancha {index} lista")
                self.update_idletasks()
        except (OSError, ValueError) as error:
            messagebox.showerror("Producción continua", f"No se pudo preparar el lote: {error}", parent=self)
            return
        finally:
            self.project, self.current_project_index = original_project, original_index
            self.plancha_id, self.final_png_path = original_plancha_id, original_final_path
            self.after(120, lambda: progress_dialog.destroy() if progress_dialog.winfo_exists() else None)

        from app.planchas.continuous_editor import ContinuousProductionEditor
        ContinuousProductionEditor(self, self.database, initial_plancha_ids=plancha_ids)

    def open_continuous_production(self):
        """Abre la etapa de armado de tiras sin modificar esta plancha A4."""
        if not self.database:
            messagebox.showinfo("Producción continua", "Abrí el constructor desde Doccione Studio para usar producciones continuas.", parent=self)
            return
        from app.planchas.continuous_editor import ContinuousProductionEditor

        initial_plancha_id = self.plancha_id if self.plancha_id and self.final_png_path else None
        ContinuousProductionEditor(self, self.database, initial_plancha_id=initial_plancha_id)

    def save_project(self):
        path = filedialog.asksaveasfilename(title="Guardar proyecto de plancha", defaultextension=".doccione-plancha.json", filetypes=[("Proyecto Doccione", "*.doccione-plancha.json"), ("JSON", "*.json")])
        if path:
            # Si hay múltiples planchas, guardar todas como un conjunto
            if self.all_projects and len(self.all_projects) > 1:
                self.save_plancha_set(path)
            else:
                # Guardado tradicional de una sola plancha
                self.project.save(path)
                self.project_path = path
                if self.database:
                    order_id = self._linked_order_id()
                    material = ""
                    if order_id:
                        order = self.database.order(order_id)
                        material = (order or {}).get("material", "")
                    saved_at = time.strftime("%H:%M")
                    source_name = f"Pedido #{order_id}" if order_id else "Plancha Doccione"
                    self.plancha_id = self.database.save_plancha_project(
                        order_id, f"{source_name} · {Path(path).stem} · {saved_at}", material,
                        json.dumps(self.project.to_dict(), ensure_ascii=False), path, self.plancha_id,
                        self.person_name, self.person_phone, self.project.workspace_format,
                    )
                    # Sincronizar production_status y usuario
                    if self.plancha_id:
                        current = self.database.plancha_project(self.plancha_id) or {}
                        prev_status = current.get("production_status") or "borrador"
                        if prev_status == "borrador":
                            new_status = "lista" if self.final_png_path else "guardada"
                            self.database.update_plancha_production_status(self.plancha_id, new_status)
                        username = os.environ.get("USERNAME", "")
                        if username and not current.get("usuario"):
                            self.database.set_plancha_usuario(self.plancha_id, username)
                    self._sync_open_order_after_approval()
                    self.refresh_printing_panel()
                    self.refresh_approval_panel()
                messagebox.showinfo("Proyecto guardado", "La plancha quedó guardada como proyecto editable. Las imágenes originales no se modificaron.", parent=self)
                self.app.after_idle(self.app.show_production_planchas)

    def save_all_planchas(self):
        """Guarda todas las páginas de la ficha como un conjunto desplegable."""
        projects = self.all_projects or [self.project]
        if not any(project.items for project in projects):
            messagebox.showinfo("Guardar todas", "Agregá al menos un diseño antes de guardar.", parent=self)
            return
        if not self.database:
            messagebox.showwarning("Guardar todas", "Se requiere la base de datos para registrar las planchas.", parent=self)
            return

        root = Path(__file__).resolve().parents[2]
        folder = root / "outputs" / "planchas_guardadas"
        order_id = self._linked_order_id()
        if order_id:
            folder = root / "outputs" / "pedidos" / f"pedido_{order_id}" / "planchas_guardadas"
        folder.mkdir(parents=True, exist_ok=True)
        prefix = f"pedido_{order_id}" if order_id else "plancha_doccione"
        base_path = folder / f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.doccione-plancha.json"
        self.all_projects = projects
        self.save_plancha_set(str(base_path))

    def save_plancha_set(self, base_path: str):
        """Guarda un conjunto de planchas múltiples como proyectos individuales vinculados."""
        import uuid
        from datetime import datetime
        
        if not self.database:
            messagebox.showwarning("Guardado", "Se requiere conexión a la base de datos para guardar conjuntos de planchas.", parent=self)
            return
        
        # Generar un ID único para el conjunto
        plancha_set_id = uuid.uuid4().hex
        order_id = self._linked_order_id()
        material = ""
        source_name = "Plancha Doccione"
        if order_id:
            order = self.database.order(order_id)
            material = (order or {}).get("material", "")
            client = (order or {}).get("client_name") or (order or {}).get("client") or "Cliente"
            source_name = f"Pedido #{order_id} - {client}"
        
        base_path_obj = Path(base_path)
        base_name = base_path_obj.stem
        base_dir = base_path_obj.parent
        saved_at = datetime.now().strftime("%H:%M")
        
        saved_plancha_ids = []
        original_project = self.project
        original_index = self.current_project_index
        
        # Guardar cada plancha del conjunto
        for index, project in enumerate(self.all_projects):
            plancha_number = index + 1
            plancha_path = base_dir / f"{base_name}_plancha_{plancha_number}.json"
            final_path = base_dir / f"{base_name}_plancha_{plancha_number}.png"
            project.save(str(plancha_path))
            self.project = project
            sheet = self.render_sheet(preview=False)
            sheet.save(final_path, "PNG", dpi=(300, 300), compress_level=3)
            
            # Guardar en base de datos con metadatos del conjunto
            plancha_id = self.database.save_plancha_project(
                order_id, 
                f"{source_name} · {base_name} · {saved_at} · Plancha {plancha_number}", 
                material, 
                json.dumps(project.to_dict(), ensure_ascii=False), 
                str(plancha_path),
                None,  # Crear nuevo registro
                self.person_name, self.person_phone, project.workspace_format,
            )
            self.database.set_plancha_final_png(plancha_id, str(final_path))
            
            # Actualizar con metadatos de paginación
            now = datetime.now().isoformat(timespec="seconds")
            self.database.connection.execute(
                """UPDATE plancha_projects SET 
                   plancha_set_id = ?, plancha_number = ?, total_planchas = ?, updated_at = ?
                   WHERE id = ?""",
                (plancha_set_id, plancha_number, len(self.all_projects), now, plancha_id)
            )
            self.database.connection.commit()
            
            # Sincronizar production_status y usuario
            current = self.database.plancha_project(plancha_id) or {}
            prev_status = current.get("production_status") or "borrador"
            if prev_status == "borrador":
                new_status = "guardada"
                self.database.update_plancha_production_status(plancha_id, new_status)
            username = os.environ.get("USERNAME", "")
            if username and not current.get("usuario"):
                self.database.set_plancha_usuario(plancha_id, username)
            
            saved_plancha_ids.append(plancha_id)

        self.project = original_project
        self.current_project_index = original_index
        
        # Actualizar plancha_id actual con la primera del conjunto
        if saved_plancha_ids:
            self.plancha_id = saved_plancha_ids[0]
            self.project_path = str(base_dir / f"{base_name}_plancha_1.json")
        
        self._sync_open_order_after_approval()
        self.refresh_printing_panel()
        self.refresh_approval_panel()
        
        messagebox.showinfo("Conjunto guardado", f"Se guardaron {len(self.all_projects)} planchas como un conjunto editable.\n\nCada plancha se guardó como un archivo independiente vinculado al mismo pedido.", parent=self)
        self.app.after_idle(self.app.show_production_planchas)
        self.app.after_idle(self.app.refresh_production)

    def open_project(self):
        path = filedialog.askopenfilename(title="Abrir proyecto de plancha", filetypes=[("Proyecto Doccione", "*.doccione-plancha.json *.json")])
        if not path:
            return
        try:
            self.project = PlanchaProject.load(path)
            self.project.margin_cm = A5_PRINT_MARGIN_CM if self.project.workspace_format == "a5" else PRINT_MARGIN_CM
            self.layout_mode = self.project.layout_mode
            title_kind = "especial" if self.layout_mode == "special" else "clásica"
            self.title(f"Plancha {self.plancha_number} de {self.max_planchas} · {title_kind} · {self.project.workspace_label}")
            if self.project.project_type == "sticker_mixed":
                self.enable_sticker_mixed_mode()
            elif self.project.project_type == "sticker_free" and hasattr(self, "productive_resize_controls"):
                self.productive_resize_controls.pack(fill="x", pady=(SPACE.sm, 0))
            elif hasattr(self, "workspace_button"):
                self.workspace_button.configure(text={"a4": "A4", "a5": "A5", "franja": "1/5"}[self.project.workspace_format])
            self.format_heading.set(f"PLANCHA {self.project.workspace_label.upper()}")
            self.project_path = path
            saved_plancha = self.database.plancha_by_project_path(path) if self.database else None
            self.plancha_id = saved_plancha.get("id") if saved_plancha else None
            self.order_id = saved_plancha.get("order_id") if saved_plancha else None
            self.final_png_path = saved_plancha.get("final_png_path") if saved_plancha else ""
            self.selected_id = None
            self.selected_ids.clear()
            self.history, self.future = [], []
            # Abrir es restaurar un snapshot: nunca reempaqueta ni recalcula
            # geometría, incluido legacy/special histórico.
            self.render()
            self.refresh_printing_panel()
            self.refresh_approval_panel()
        except Exception as error:
            messagebox.showerror("No se pudo abrir", str(error), parent=self)
