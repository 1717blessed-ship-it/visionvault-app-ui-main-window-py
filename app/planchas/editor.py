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
from app.planchas.model import A4_HEIGHT_CM, A4_WIDTH_CM, FIVE_ROW_SIZE_CM, MAX_SIZE_CM, PRINT_MARGIN_CM, SIZE_OFFSET_CM, PlanchaItem, PlanchaProject, size_for_image, size_from_visible_dimensions, visible_bbox
from app.ui.components import icon_button
from app.ui.theme import COLORS, IDENTITY_FONT, UI_FONT, configure_plancha_styles


def needs_silhouette_outline(image) -> bool:
    """Distingue una silueta recortada de una imagen rectangular o cuadrada."""
    try:
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        mask = alpha.point(lambda opacity: 255 if opacity > 8 else 0)
        visible = sum(1 for value in mask.getdata() if value)
        total = max(1, mask.width * mask.height)
        coverage = visible / total
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


def prepare_sticker_for_target(image, target: tuple[int, int], outlined: bool | None = None):
    """Prepara el sticker igual para pantalla y PNG, a una caja final exacta."""
    from PIL import Image

    sticker = image.convert("RGBA")
    sticker.thumbnail((max(1, target[0] - 2), max(1, target[1] - 2)), Image.Resampling.LANCZOS)
    if outlined is None:
        outlined = needs_silhouette_outline(sticker)
    if outlined:
        # Reserva la banda blanca de seguridad y el contorno negro antes de
        # volver a llevar el resultado a la misma hitbox final.
        sticker.thumbnail((max(1, target[0] - 36), max(1, target[1] - 36)), Image.Resampling.LANCZOS)
        sticker = add_inner_black_outline(sticker, pixels=2)
    else:
        sticker = round_rectangular_corners(sticker)
    final_box = sticker.getchannel("A").getbbox()
    if final_box:
        sticker = sticker.crop(final_box)
    return sticker.resize(target, Image.Resampling.LANCZOS)


def load_visible_thumbnail(path: str, size: tuple[int, int], rotation: int = 0):
    """Miniatura de la silueta: no dibuja el lienzo vacío del archivo."""
    try:
        from PIL import Image, ImageTk

        with Image.open(path) as source:
            image = source.convert("RGBA").crop(visible_bbox(source))
        # Se usa exactamente la misma preparación que la exportación final,
        # solo reducida al tamaño visual de la tarjeta del editor.
        outlined = needs_silhouette_outline(image)
        if rotation:
            image = image.rotate(-rotation, expand=True)
        final_size = (max(1, size[0] - 8), max(1, size[1] - 8))
        preview_scale = 6
        production_size = (final_size[0] * preview_scale, final_size[1] * preview_scale)
        processed = prepare_sticker_for_target(image, production_size, outlined=outlined)
        processed.thumbnail(final_size, Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(processed)
    except Exception:
        return load_thumbnail(path, size)


def add_inner_black_outline(image, pixels: int = 2):
    """Genera el borde de corte: diseño → 5 px blancos → 2 px negros."""
    try:
        from PIL import Image, ImageChops, ImageFilter

        sticker = image.convert("RGBA")
        if not needs_silhouette_outline(sticker):
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
        white_inside_outline = Image.new("RGBA", base.size, (255, 255, 255, 0))
        white_inside_outline.putalpha(white_inner)
        result.alpha_composite(white_inside_outline)
        return result
    except Exception:
        return image


def size_for_record(image: dict, requested_size_cm: float = FIVE_ROW_SIZE_CM) -> tuple[float, float]:
    """Usa la hitbox guardada en la base; abre el PNG solo si falta."""
    if image.get("visible_width") and image.get("visible_height"):
        return size_from_visible_dimensions(image["visible_width"], image["visible_height"], requested_size_cm)
    return size_for_image(image["path"], requested_size_cm)


class PlanchaEditor(tk.Toplevel):
    SCALE = 22
    SIZE_PRESETS = tuple(range(5, 30))

    def __init__(self, master, images: list[dict], database=None, library_images: list[dict] | None = None,
                 project: PlanchaProject | None = None, order_id: int | None = None, plancha_id: int | None = None,
                 preserve_layout: bool = False):
        super().__init__(master)
        self.title("Plancha libre · A4")
        self.configure(background=COLORS.background)
        self.geometry("1120x760")
        self.minsize(900, 620)
        self.withdraw()
        self.loading_screen, self.loading_message = self.create_loading_screen()
        self.loading_message.set("Midiendo los diseños seleccionados…")
        self.loading_screen.update_idletasks()
        self.project = project or PlanchaProject.from_images(images)
        self.project.margin_cm = PRINT_MARGIN_CM
        self.preserve_layout = preserve_layout
        self.database = database
        self.order_id = order_id
        self.plancha_id = plancha_id
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
        if not self.preserve_layout:
            self.normalize_project_size()
        self.loading_message.set("Preparando el constructor de planchas…")
        self.loading_screen.update_idletasks()
        self.selected_id: str | None = None
        self.selected_ids: set[str] = set()
        self.show_hitboxes = True
        self.drag_offset = (0, 0)
        self.drag_band_index: int | None = None
        self.area_selection_start: tuple[float, float] | None = None
        self.area_selection_base: set[str] = set()
        self.area_selection_rect: int | None = None
        self.zoom = 1.0
        self.zoom_render_pending = False
        self.history: list[dict] = []
        self.future: list[dict] = []
        self.thumbnails = []
        self.thumbnail_cache: dict[tuple, object] = {}
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
        self.loading_screen.destroy()
        self.deiconify()
        progress_dialog, report_progress = self.creation_progress_dialog(len(self.project.items))
        report_progress(0, 4, "Preparando los stickers seleccionados")
        initial_overflow = [] if self.preserve_layout else self.organize_automatically(progress=report_progress)
        report_progress(4, 4, "Generando la vista previa de la plancha")
        self.snapshot()
        self.render()
        report_progress(5, 5, "Plancha lista")
        self.after(180, lambda: progress_dialog.destroy() if progress_dialog.winfo_exists() else None)
        if initial_overflow:
            self.after(120, lambda: self.offer_overflow(initial_overflow))

    def create_loading_screen(self):
        """Pantalla inicial breve: evita mostrar el Constructor vacío."""
        dialog = tk.Toplevel(self.master)
        dialog.title("Preparando plancha")
        dialog.configure(background=COLORS.panel)
        dialog.resizable(False, False)
        dialog.transient(self.master)
        dialog.geometry("360x150")
        dialog.update_idletasks()
        x = self.master.winfo_rootx() + max(0, (self.master.winfo_width() - 360) // 2)
        y = self.master.winfo_rooty() + max(0, (self.master.winfo_height() - 150) // 2)
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
        """Iguala todas las hitboxes por su lado mayor visible (5,70 cm)."""
        for item in self.project.items:
            width, height = self.database.plancha_dimensions(item.path, FIVE_ROW_SIZE_CM) if self.database else (0.0, 0.0)
            if not width or not height:
                width, height = size_for_image(item.path, FIVE_ROW_SIZE_CM)
            if item.rotation % 180:
                width, height = height, width
            item.width_cm, item.height_cm = width, height

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

        # Barra compacta por tareas: evita una fila extensa de botones sin
        # jerarquía y conserva visibles las acciones de producción.
        toolbar = tk.Frame(self, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        toolbar.pack(fill="x", padx=12, pady=(10, 8))
        toolbar_inner = tk.Frame(toolbar, background=COLORS.panel)
        toolbar_inner.pack(fill="x", padx=9, pady=7)

        def tool_group(title: str, side: str, padding: tuple[int, int] = (0, 0)):
            group = tk.Frame(toolbar_inner, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
            group.pack(side=side, padx=padding)
            tk.Label(group, text=title, background=COLORS.panel_elevated, foreground=COLORS.muted, font=(IDENTITY_FONT, 8, "bold")).pack(anchor="w", padx=8, pady=(4, 0))
            actions = tk.Frame(group, background=COLORS.panel_elevated)
            actions.pack(padx=5, pady=(2, 5))
            return actions

        # El archivo final queda a la derecha y destacado; el operario lo
        # encuentra sin mezclarlo con herramientas de edición.
        output = tool_group("ARCHIVO", "right")
        icon_button(output, "↗", "Abrir proyecto", lambda *a, _fn=self.open_project: _fn(*a)).pack(side="left")
        icon_button(output, "▣", "Guardar proyecto", lambda *a, _fn=self.save_project: _fn(*a)).pack(side="left", padx=(4, 0))
        icon_button(output, "◉", "Generar vista previa", lambda *a, _fn=self.export_preview: _fn(*a)).pack(side="left", padx=(4, 0))
        icon_button(output, "⇩", "Guardar PNG final", lambda *a, _fn=self.export_final: _fn(*a), tone="primary").pack(side="left", padx=(4, 0))
        ttk.Button(output, text="Enviar a cola", command=lambda *a, _fn=self.send_to_print_queue: _fn(*a), style="Plancha.Primary.TButton").pack(side="left", padx=(4, 0))

        work = tool_group("ARMADO", "left")
        icon_button(work, "＋", "Buscar y agregar diseños", lambda *a, _fn=self.add_images: _fn(*a), tone="primary").pack(side="left")
        icon_button(work, "◈", "Optimizar distribución", lambda *a, _fn=self.optimize: _fn(*a), tone="primary").pack(side="left", padx=(4, 0))
        icon_button(work, "▦", "Completar espacios", lambda *a, _fn=self.complete_spaces: _fn(*a)).pack(side="left", padx=(4, 0))
        icon_button(work, "▤", "Abrir producción continua", lambda *a, _fn=self.open_continuous_production: _fn(*a)).pack(side="left", padx=(4, 0))

        edit = tool_group("EDICIÓN", "left", (7, 0))
        icon_button(edit, "☷", "Seleccionar todos", lambda *a, _fn=self.select_all_items: _fn(*a)).pack(side="left")
        self.hitbox_button = icon_button(edit, "⌗", "Ocultar guías", lambda *a, _fn=self.toggle_hitboxes: _fn(*a))
        self.hitbox_button.pack(side="left", padx=(4, 0))
        icon_button(edit, "↶", "Deshacer", lambda *a, _fn=self.undo: _fn(*a)).pack(side="left", padx=(4, 0))
        icon_button(edit, "↷", "Rehacer", lambda *a, _fn=self.redo: _fn(*a)).pack(side="left", padx=(3, 0))
        icon_button(edit, "⌫", "Eliminar diseño seleccionado", lambda *a, _fn=self.delete_selected: _fn(*a), tone="danger").pack(side="left", padx=(4, 0))

        body = ttk.Frame(self, padding=(12, 0, 12, 12))
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, background=COLORS.canvas, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.click_canvas)
        self.canvas.bind("<B1-Motion>", self.drag_item)
        self.canvas.bind("<ButtonRelease-1>", self.release_item)
        self.canvas.bind("<Button-3>", self.show_canvas_context_menu)
        self.canvas.bind("<Delete>", lambda _event: self.delete_selected())
        self.canvas.bind("<Alt-MouseWheel>", self.zoom_with_wheel)
        self.canvas.bind("<Control-MouseWheel>", self.pan_horizontally_with_wheel)

        details_host = tk.Frame(body, width=275, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        details_host.pack(side="right", fill="y", padx=(12, 0))
        details_host.pack_propagate(False)
        details_tabs = ttk.Notebook(details_host)
        details_tabs.pack(fill="both", expand=True)
        details = tk.Frame(details_tabs, background=COLORS.panel)
        approval = tk.Frame(details_tabs, background=COLORS.panel)
        details_tabs.add(details, text="Diseño")
        details_tabs.add(approval, text="Aprobación")
        tk.Label(details, text="PLANCHA A4", background=COLORS.panel, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 12, "bold")).pack(anchor="w", padx=14, pady=(16, 4))
        self.stats = tk.StringVar()
        tk.Label(details, textvariable=self.stats, background=COLORS.panel, foreground=COLORS.text, justify="left", wraplength=220, font=(UI_FONT, 10)).pack(anchor="w", padx=14, pady=(0, 18))
        self.legend_frame = tk.Frame(details, background=COLORS.panel)
        self.legend_frame.pack(fill="x", padx=14, pady=(0, 10))
        tk.Label(details, text="Diseño seleccionado", background=COLORS.panel, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 11, "bold")).pack(anchor="w", padx=14)
        self.selected_label = tk.StringVar(value="Elegí un diseño de la plancha.")
        tk.Label(details, textvariable=self.selected_label, background=COLORS.panel, foreground=COLORS.text, justify="left", wraplength=220, font=(UI_FONT, 10)).pack(anchor="w", padx=14, pady=(5, 10))
        tk.Label(details, text="Tamaño (cm)", background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 10)).pack(anchor="w", padx=14)
        self.size_value = tk.StringVar(value="5cm")
        size = ttk.Combobox(details, textvariable=self.size_value, values=tuple(f"{value}cm" for value in self.SIZE_PRESETS), state="readonly", width=12)
        size.pack(anchor="w", padx=14, pady=(3, 8))
        ttk.Button(details, text="Aplicar tamaño", command=lambda *a, _fn=self.apply_size: _fn(*a), style="Plancha.Primary.TButton").pack(fill="x", padx=14)
        ttk.Button(details, text="Igualar por lado mayor", command=lambda *a, _fn=self.normalize_by_longest_side: _fn(*a), style="Plancha.Secondary.TButton").pack(fill="x", padx=14, pady=(5, 0))
        tk.Label(details, text="Cantidad", background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 10)).pack(anchor="w", padx=14, pady=(10, 0))
        self.quantity_value = tk.IntVar(value=1)
        ttk.Spinbox(details, from_=1, to=100, textvariable=self.quantity_value, width=12).pack(anchor="w", padx=14, pady=(3, 5))
        ttk.Button(details, text="Aplicar cantidad", command=lambda *a, _fn=self.apply_quantity: _fn(*a), style="Plancha.Secondary.TButton").pack(fill="x", padx=14)
        tk.Label(details, text="Origen", background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 10)).pack(anchor="w", padx=14, pady=(10, 0))
        self.source_value = tk.StringVar(value="Stock")
        ttk.Combobox(details, textvariable=self.source_value, values=("Pedido", "Stock", "Relleno"), state="readonly", width=18).pack(anchor="w", padx=14, pady=(3, 5))
        self.client_value = tk.StringVar()
        self.order_value = tk.StringVar()
        tk.Label(details, text="Cliente", background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 10)).pack(anchor="w", padx=14)
        ttk.Entry(details, textvariable=self.client_value).pack(fill="x", padx=14, pady=(3, 7))
        tk.Label(details, text="N.º de pedido", background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 10)).pack(anchor="w", padx=14)
        ttk.Entry(details, textvariable=self.order_value).pack(fill="x", padx=14, pady=(3, 0))
        self.rotation_allowed = tk.BooleanVar(value=False)
        tk.Checkbutton(details, text="Autorizar rotación 90°", variable=self.rotation_allowed, background=COLORS.panel, foreground=COLORS.text, activebackground=COLORS.panel, activeforeground=COLORS.text, selectcolor=COLORS.wine).pack(anchor="w", padx=10, pady=(6, 2))
        ttk.Button(details, text="Aplicar datos", command=lambda *a, _fn=self.apply_details: _fn(*a), style="Plancha.Secondary.TButton").pack(fill="x", padx=14)
        ttk.Button(details, text="Rotar", command=lambda *a, _fn=self.rotate_selected: _fn(*a), style="Plancha.Secondary.TButton").pack(fill="x", padx=14, pady=(6, 0))
        self.lock_button = ttk.Button(details, text="Bloquear posición", command=lambda *a, _fn=self.toggle_lock: _fn(*a), style="Plancha.Secondary.TButton")
        self.lock_button.pack(fill="x", padx=14, pady=(6, 0))
        ttk.Button(details, text="Eliminar", command=lambda *a, _fn=self.delete_selected: _fn(*a), style="Plancha.Danger.TButton").pack(fill="x", padx=14, pady=(6, 0))
        ttk.Label(details, text="Los originales no se modifican.", background=COLORS.panel, foreground=COLORS.muted, wraplength=210).pack(side="bottom", anchor="w", padx=14, pady=14)
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
        if not self.database or not self.order_id or not hasattr(self.master, "order_tabs"):
            return
        tab = self.master.order_tabs.get(int(self.order_id))
        order = self.database.order(int(self.order_id))
        if not tab or not order or not hasattr(tab, "order_values"):
            return
        status_value = tab.order_values.get("status")
        if status_value and status_value.get() != order["status"]:
            status_value.set(order["status"])
        if hasattr(self.master, "render_order_workspace"):
            self.master.render_order_workspace(tab)

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
        return getattr(self.master, "current_role", "Administrador")

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
        if hasattr(self.master, "refresh_orders"):
            self.master.refresh_orders()
        if hasattr(self.master, "refresh_production"):
            self.master.refresh_production()

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
        if hasattr(self.master, "status"):
            self.master.status.set(message)

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

    def send_to_print_queue(self):
        """Registra el PNG final para que Producción decida cuándo enviarlo a Windows."""
        if self._print_role() not in {"Administrador", "Operario"}:
            messagebox.showerror("Cola de impresión", "Tu perfil no tiene permiso para enviar planchas a impresión.", parent=self)
            return
        if not self.database:
            messagebox.showerror("Cola de impresión", "No se pudo acceder a la base de datos de Producción.", parent=self)
            return
        if not self.plancha_id or not self.final_png_path or not Path(self.final_png_path).exists():
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
        error = self._print_validation_error()
        if error:
            messagebox.showerror("No se puede enviar a cola", error, parent=self)
            return
        config = self._current_print_config()
        self.database.create_print_job(
            self.plancha_id, os.environ.get("USERNAME", "Operario"), config["printer_name"], config,
            max(1, int(config.get("copies", 1) or 1)), self.final_png_path,
        )
        if hasattr(self.master, "refresh_production"):
            self.master.refresh_production()
        self.status_message("PNG final enviado a la cola de impresión. Abrí Producción para enviarlo a la impresora.")
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
        self.status_message("Plancha marcada como impresa y registrada en el historial.")

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
        self.hitbox_button.configure(text="⌗" if self.show_hitboxes else "◌")
        self.render()

    def px_to_cm(self, value: float) -> float:
        return value / (self.SCALE * self.zoom)

    def zoom_with_wheel(self, event):
        """Alt + rueda acerca o aleja solo la vista del constructor."""
        factor = 1.12 if event.delta > 0 else 1 / 1.12
        new_zoom = min(2.5, max(0.5, self.zoom * factor))
        if abs(new_zoom - self.zoom) < 0.001:
            return "break"
        self.zoom = new_zoom
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

    def restore(self, data: dict):
        self.project = PlanchaProject([PlanchaItem.from_dict(item) for item in data["items"]], data["margin_cm"], data["gap_cm"])
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
        if visible_size <= 5:
            return FIVE_ROW_SIZE_CM
        return min(MAX_SIZE_CM, float(visible_size) + SIZE_OFFSET_CM)

    def size_label_for(self, item: PlanchaItem) -> str:
        longest_side = max(item.width_cm, item.height_cm)
        visible_size = 5 if longest_side <= FIVE_ROW_SIZE_CM + 0.02 else min(29, max(5, round(longest_side - SIZE_OFFSET_CM)))
        return f"{visible_size}cm"

    def render(self):
        self.project.keep_inside_print_area()
        self.canvas.delete("all")
        page_w, page_h = self.cm_to_px(A4_WIDTH_CM), self.cm_to_px(A4_HEIGHT_CM)
        self.canvas.configure(scrollregion=(0, 0, page_w + 60, page_h + 60))
        self.canvas.create_rectangle(25, 25, page_w + 25, page_h + 25, fill=COLORS.paper, outline=COLORS.wine, width=2)
        margin = self.cm_to_px(self.project.margin_cm)
        if margin:
            self.canvas.create_rectangle(25 + margin, 25 + margin, 25 + page_w - margin, 25 + page_h - margin, outline="#c9bbb0", dash=(3, 3))
        for item in self.project.items:
            x1, y1 = 25 + self.cm_to_px(item.x_cm), 25 + self.cm_to_px(item.y_cm)
            x2, y2 = x1 + self.cm_to_px(item.width_cm), y1 + self.cm_to_px(item.height_cm)
            if self.show_hitboxes:
                selected = item.item_id in self.selected_ids
                outline = COLORS.wine_active if selected else (item.client_color if item.client else COLORS.border_strong)
                self.canvas.create_rectangle(x1, y1, x2, y2, fill="#FFFDF9", outline=outline, width=3 if selected else 2, tags=("item", item.item_id))
            thumb = self.cached_thumbnail(item.path, max(10, int(x2 - x1 - 8)), max(10, int(y2 - y1 - 8)), item.rotation)
            if thumb:
                self.canvas.create_image((x1 + x2) / 2, (y1 + y2) / 2, image=thumb, tags=("item", item.item_id))
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
            self.size_value.set(self.size_label_for(item))
            self.quantity_value.set(item.quantity)
            self.source_value.set(item.source)
            self.client_value.set(item.client)
            self.order_value.set(item.order_number)
            self.rotation_allowed.set(item.rotation_allowed)
            self.lock_button.configure(text="Desbloquear posición" if item.locked else "Bloquear posición")

    def cached_thumbnail(self, path: str, width: int, height: int, rotation: int = 0):
        try:
            modified = Path(path).stat().st_mtime
        except OSError:
            modified = -1.0
        key = (path, modified, width, height, rotation)
        thumbnail = self.thumbnail_cache.get(key)
        if thumbnail is None:
            thumbnail = load_visible_thumbnail(path, (width, height), rotation)
            if len(self.thumbnail_cache) >= 700:
                self.thumbnail_cache.clear()
            self.thumbnail_cache[key] = thumbnail
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

    def item_at(self, x: float, y: float) -> PlanchaItem | None:
        for item in reversed(self.project.items):
            left, top = 25 + self.cm_to_px(item.x_cm), 25 + self.cm_to_px(item.y_cm)
            if left <= x <= left + self.cm_to_px(item.width_cm) and top <= y <= top + self.cm_to_px(item.height_cm):
                return item
        return None

    def item_ids_in_area(self, left: float, top: float, right: float, bottom: float) -> set[str]:
        """Selecciona por el centro de la hitbox para evitar inclusiones accidentales."""
        left, right = sorted((left, right))
        top, bottom = sorted((top, bottom))
        selected = set()
        for item in self.project.items:
            center_x = 25 + self.cm_to_px(item.x_cm + item.width_cm / 2)
            center_y = 25 + self.cm_to_px(item.y_cm + item.height_cm / 2)
            if left <= center_x <= right and top <= center_y <= bottom:
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

    def drag_item(self, event):
        x, y = self.canvas_event_position(event)
        if self.area_selection_start is not None:
            start_x, start_y = self.area_selection_start
            self.canvas.delete("area_selection")
            self.area_selection_rect = self.canvas.create_rectangle(
                start_x, start_y, x, y,
                outline=COLORS.wine_active, width=2, dash=(5, 3),
                fill="", tags=("area_selection",),
            )
            return
        item = self.selected_item()
        if not item or item.locked:
            return
        max_x = A4_WIDTH_CM - self.project.margin_cm - item.width_cm
        min_y, max_y = self.drag_band_bounds(item)
        step = max(0.05, self.project.gap_cm)
        raw_x = min(max(self.project.margin_cm, self.px_to_cm(x - 25 - self.drag_offset[0])), max_x)
        raw_y = min(max(min_y, self.px_to_cm(y - 25 - self.drag_offset[1])), max_y)
        # Imán base: al mover se alinea a la grilla real de separación de la plancha.
        new_x = round(round((raw_x - self.project.margin_cm) / step) * step + self.project.margin_cm, 3)
        new_y = round(round((raw_y - self.project.margin_cm) / step) * step + self.project.margin_cm, 3)
        new_x, new_y = self.magnetic_position(item, min(new_x, max_x), min(new_y, max_y))
        new_y = min(max(min_y, new_y), max_y)
        # Nunca permite que una hitbox invada a otra. Si el cursor llega a una
        # zona ocupada, mantiene la última posición válida del diseño.
        if self.can_place(item, new_x, new_y):
            item.x_cm, item.y_cm = new_x, new_y
        self.request_render()

    def band_for_item(self, item: PlanchaItem) -> int:
        """Devuelve la franja de producción (1 a 5) donde está el diseño."""
        margin = self.project.margin_cm
        band_height = (A4_HEIGHT_CM - (margin * 2)) / 5
        center_y = item.y_cm + (item.height_cm / 2)
        return max(0, min(4, int((center_y - margin) / band_height)))

    def drag_band_bounds(self, item: PlanchaItem) -> tuple[float, float]:
        """Limita el arrastre a una de las cinco franjas imprimibles."""
        margin = self.project.margin_cm
        paper_max_y = A4_HEIGHT_CM - margin - item.height_cm
        band_height = (A4_HEIGHT_CM - (margin * 2)) / 5
        band_index = self.drag_band_index if self.drag_band_index is not None else self.band_for_item(item)
        band_top = margin + (band_index * band_height)
        band_bottom = margin + ((band_index + 1) * band_height)
        if item.height_cm > band_height:
            return margin, paper_max_y
        return band_top, max(band_top, min(paper_max_y, band_bottom - item.height_cm))

    def magnetic_position(self, item: PlanchaItem, x_cm: float, y_cm: float) -> tuple[float, float]:
        """Acerca el diseño al borde derecho de otro sin salir de su hitbox.

        La prioridad es el borde derecho, tal como se arma la plancha de
        izquierda a derecha. Los otros bordes solo ayudan a mantener una fila
        visualmente prolija cuando ya se está muy cerca de ellos.
        """
        margin = self.project.margin_cm
        gap = self.project.gap_cm
        max_x = A4_WIDTH_CM - margin - item.width_cm
        max_y = A4_HEIGHT_CM - margin - item.height_cm
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

    def can_place(self, item: PlanchaItem, x_cm: float, y_cm: float) -> bool:
        """Mantiene la separación mínima al mover manualmente."""
        gap = self.project.gap_cm
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
            self.render()

    def show_canvas_context_menu(self, event):
        """Clic derecho elimina uno o varios diseños de la plancha, nunca el original."""
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
        label = "Eliminar diseño de la plancha" if count == 1 else f"Eliminar {count} diseños de la plancha"
        menu.add_command(label=label, command=lambda *a, _fn=self.delete_selected: _fn(*a))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

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
        overflow = self.project.optimize(progress=progress)
        if overflow:
            overflow_ids = {item.item_id for item in overflow}
            self.project.items = [item for item in self.project.items if item.item_id not in overflow_ids]
            self.selected_ids.difference_update(overflow_ids)
            if self.selected_id in overflow_ids:
                self.selected_id = None
            self.pending_overflow.extend(item for item in overflow if item not in self.pending_overflow)
        return overflow

    def offer_overflow(self, overflow: list[PlanchaItem]):
        if not overflow:
            return
        dialog = tk.Toplevel(self)
        dialog.title("Stickers sobrantes")
        dialog.configure(background="#111314")
        dialog.transient(self)
        dialog.grab_set()
        ttk.Label(dialog, text="Stickers sobrantes", style="Title.TLabel", padding=(18, 14, 18, 4)).pack(anchor="w")
        ttk.Label(dialog, text=f"{len(overflow)} sticker(s) no entran en esta plancha A4.", style="Muted.TLabel", padding=(18, 0, 18, 8)).pack(anchor="w")
        send_to_new = tk.BooleanVar(value=True)
        tk.Checkbutton(dialog, text="¿Quiere enviar los stickers sobrantes a otra plancha?", variable=send_to_new, background="#111314", foreground="#e7d3c4", activebackground="#111314", activeforeground="#fff4ec", selectcolor="#d60916", wraplength=360).pack(anchor="w", padx=14, pady=(2, 12))

        def confirm():
            dialog.grab_release()
            dialog.destroy()
            if send_to_new.get():
                self.pending_overflow = [item for item in self.pending_overflow if item not in overflow]
                next_project = PlanchaProject(list(overflow), margin_cm=PRINT_MARGIN_CM, gap_cm=self.project.gap_cm)
                PlanchaEditor(self.master, [], database=self.database, library_images=self.library_images, project=next_project)
            self.render()

        ttk.Button(dialog, text="Continuar", command=confirm).pack(anchor="e", padx=18, pady=(0, 14))

    def apply_size(self):
        item = self.selected_item()
        if not item:
            return
        selected = self.selected_ids or {item.item_id}
        group_ids = {candidate.group_id for candidate in self.project.items if candidate.item_id in selected}
        for candidate in self.project.items:
            if candidate.group_id not in group_ids:
                continue
            width, height = size_for_image(candidate.path, self.selected_size_cm())
            if candidate.rotation % 180:
                width, height = height, width
            candidate.width_cm, candidate.height_cm = width, height
        self.optimize()

    def normalize_by_longest_side(self):
        """Hace uniforme el lado mayor de todos los stickers elegidos."""
        selected = self.selected_ids or {item.item_id for item in self.project.items}
        group_ids = {candidate.group_id for candidate in self.project.items if candidate.item_id in selected}
        target_size = self.selected_size_cm()
        for candidate in self.project.items:
            if candidate.group_id not in group_ids:
                continue
            width, height = size_for_image(candidate.path, target_size)
            if candidate.rotation % 180:
                width, height = height, width
            candidate.width_cm, candidate.height_cm = width, height
        self.optimize()

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
        self.optimize()

    def rotate_selected(self):
        item = self.selected_item()
        if not item:
            return
        if not item.rotation_allowed:
            messagebox.showinfo("Rotación", "Marcá «Autorizar rotación 90°» y aplicá los datos antes de rotar.", parent=self)
            return
        item.width_cm, item.height_cm = item.height_cm, item.width_cm
        item.rotation = (item.rotation + 90) % 360
        self.optimize()

    def toggle_lock(self):
        item = self.selected_item()
        if not item:
            return
        item.locked = not item.locked
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
        self.optimize()

    def optimize(self):
        overflow = self.organize_automatically()
        self.snapshot()
        self.render()
        if overflow:
            self.offer_overflow(overflow)

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
            width, height = size_for_record(image)
            new_items.append(
                PlanchaItem(
                    path=path,
                    name=str(image.get("caption") or image.get("name") or "Diseño"),
                    width_cm=width,
                    height_cm=height,
                    source=str(image.get("source") or "Biblioteca"),
                )
            )

        if not new_items:
            return 0

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
            self.optimize()

        return len(new_items)

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
        dialog.geometry("1080x670")
        dialog.minsize(900, 560)
        dialog.transient(self)
        dialog.grab_set()

        header = tk.Frame(dialog, background=COLORS.panel)
        header.pack(fill="x")
        tk.Label(
            header,
            text="AGREGAR DISEÑOS",
            background=COLORS.panel,
            foreground=COLORS.text,
            font=(IDENTITY_FONT, 18, "bold"),
        ).pack(anchor="w", padx=22, pady=(18, 2))
        tk.Label(
            header,
            text="Buscá por información del diseño, no por el nombre técnico del archivo.",
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 10),
        ).pack(anchor="w", padx=22, pady=(0, 16))
        add_selection_text = tk.StringVar()
        add_selection_button = ttk.Button(header, textvariable=add_selection_text, style="Plancha.Primary.TButton")

        filters = tk.Frame(dialog, background=COLORS.background)
        filters.pack(fill="x", padx=22, pady=(16, 8))
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
        content.pack(fill="both", expand=True, padx=22, pady=(6, 10))
        content.grid_columnconfigure(0, weight=3)
        content.grid_columnconfigure(1, weight=2)
        content.grid_rowconfigure(0, weight=1)

        list_panel = tk.Frame(content, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        list_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        results = ttk.Treeview(list_panel, show="tree", selectmode="extended", height=17)
        results.column("#0", width=520, minwidth=250, anchor="w")
        scrollbar = ttk.Scrollbar(list_panel, orient="vertical", command=results.yview)
        results.configure(yscrollcommand=scrollbar.set)
        results.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        scrollbar.pack(side="right", fill="y", padx=(0, 8), pady=8)

        # ── Panel de vista previa ────────────────────────────────────────────
        preview_panel = tk.Frame(
            content, background=COLORS.panel,
            highlightthickness=1, highlightbackground=COLORS.border, width=340,
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
        preview = tk.Canvas(preview_panel, background=COLORS.panel_elevated, highlightthickness=0, height=260)
        preview.pack(fill="x", padx=14, pady=(0, 8))
        preview_info = tk.Label(
            preview_panel, text="",
            background=COLORS.panel, foreground=COLORS.text,
            justify="left", anchor="nw", wraplength=190, font=(UI_FONT, 9),
        )
        preview_info.pack(fill="x", padx=14)

        # ── Pie de página ────────────────────────────────────────────────────
        footer = tk.Frame(dialog, background=COLORS.background)
        footer.pack(fill="x", padx=22, pady=(0, 18))
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
        # Identificador del after() pendiente para la predicción mientras se escribe.
        _pending_predict: list[str | None] = [None]

        def selected_records() -> list[dict]:
            selected = []
            for iid in results.selection():
                try:
                    selected.append(result_state[int(iid.split(":", 1)[1])])
                except (IndexError, ValueError):
                    continue
            return selected

        def update_preview(_event=None):
            selected = selected_records()
            if not selected:
                preview.delete("all")
                preview.create_text(160, 125, text="Elegí uno o más diseños", fill=COLORS.muted, font=(UI_FONT, 10))
                preview_info.configure(text="")
                add_selection_button.pack_forget()
                selection_status.set("Seleccioná uno o más diseños para agregarlos.")
                return
            image = selected[0]
            physical_px = max(1, round(dialog.winfo_fpixels("1c") * 5.70))
            canvas_width = max(300, physical_px + 34)
            canvas_height = physical_px + 46
            preview.configure(width=canvas_width, height=canvas_height)
            preview.delete("all")
            thumb = load_visible_thumbnail(str(image.get("path") or ""), (physical_px, physical_px))
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
                add_selection_button.pack(side="right", padx=22, pady=18)

        def refresh_results(_event=None):
            nonlocal result_state
            if self.database:
                result_state = self.database.plancha_browser_images(
                    query=query_var.get(),
                    mode=mode_var.get(),
                    category=category_var.get(),
                    collection=collection_var.get(),
                    limit=300,
                )
            else:
                query = query_var.get().strip().casefold()
                result_state = [
                    image for image in self.library_images
                    if not query or query in str(image.get("caption") or "").casefold() or query in str(image.get("tags") or "").casefold()
                ][:300]
            results.delete(*results.get_children())
            for index, image in enumerate(result_state):
                caption = str(image.get("caption") or "Diseño sin título")
                results.insert("", "end", iid=f"image:{index}", text=caption)
            selection_status.set(f"{len(result_state)} diseños disponibles. Los nombres técnicos no se usan para buscar.")
            update_preview()

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
            for iid in results.selection():
                try:
                    idx = int(iid.split(":", 1)[1])
                    caption = str(result_state[idx].get("caption") or new_path.stem)
                    results.item(iid, text=caption)
                except (IndexError, ValueError):
                    pass
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
        results.bind("<<TreeviewSelect>>", update_preview)
        results.bind("<Control-Button-1>", lambda _event: dialog.after_idle(update_preview), add="+")
        query_box.bind("<Return>", refresh_results)
        mode_box.bind("<<ComboboxSelected>>", refresh_results)
        category_box.bind("<<ComboboxSelected>>", refresh_results)
        collection_box.bind("<<ComboboxSelected>>", refresh_results)
        query_var.trace_add("write", update_suggestions)
        refresh_results()
        query_box.focus_set()

    def find_free_position(self, width_cm: float, height_cm: float) -> tuple[float, float] | None:
        step = min(0.25, self.project.gap_cm)
        margin = self.project.margin_cm
        right_limit = A4_WIDTH_CM - margin
        bottom_limit = A4_HEIGHT_CM - margin

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
            count = 0
            temporary: list[PlanchaItem] = []
            while True:
                position = self.find_free_position(width, height)
                if not position:
                    break
                trial = PlanchaItem(path=image["path"], name=image.get("name") or Path(image["path"]).name, width_cm=width, height_cm=height, x_cm=position[0], y_cm=position[1], source="Relleno")
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

    def complete_spaces(self):
        """Combina rellenos para acercar la plancha al 95–100 % de ocupación."""
        proposals = self.fill_proposals()
        if not proposals:
            messagebox.showinfo("Completar espacios", "No encontré diseños reutilizables que entren en los huecos actuales.", parent=self)
            return

        # Cada iteración revisa qué formato entra en el hueco real que queda.
        # Se privilegia llegar a 97,5 %, pero nunca se superan los límites A4;
        # el pequeño bonus por diseños aún no usados evita repetir uno solo.
        target = 97.5
        minimum_target = 95.0
        used_paths: set[str] = set()
        added = 0
        chosen_names: list[str] = []
        chosen_origins: list[str] = []
        while self.project.occupancy() < minimum_target and added < 120:
            current = self.project.occupancy()
            choices = []
            for proposal in proposals:
                position = self.find_free_position(proposal["width"], proposal["height"])
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
            self.project.items.append(PlanchaItem(
                path=path,
                name=image.get("name") or Path(path).name,
                width_cm=proposal["width"],
                height_cm=proposal["height"],
                x_cm=position[0],
                y_cm=position[1],
                quantity=1,
                copy_number=1,
                group_id=uuid.uuid4().hex,
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
        self.project.justify_rows()
        self.snapshot()
        self.render()
        variety = len(set(chosen_names))
        origins: dict[str, int] = {}
        for origin in chosen_origins:
            origins[origin] = origins.get(origin, 0) + 1
        sources_text = " · ".join(f"{origin}: {count}" for origin, count in origins.items())
        messagebox.showinfo(
            "Nota de producción · Completar espacios",
            f"El optimizador incorporó {added} sticker(s) de {variety} diseño(s) para llegar a {self.project.occupancy():.1f}% de ocupación.\n\n"
            f"Origen: {sources_text or 'Biblioteca'}.\n"
            "La combinación fue elegida por aprovechamiento real del espacio. Revisá la plancha y cerrá esta nota para continuar.",
            parent=self,
        )

    def add_fill_proposal(self, proposal: dict) -> int:
        """Inserta una propuesta hasta que ya no entre, sin crear superposiciones."""
        group_id = uuid.uuid4().hex
        added = 0
        for copy_number in range(1, proposal["count"] + 1):
            position = self.find_free_position(proposal["width"], proposal["height"])
            if not position:
                break
            image = proposal["image"]
            self.project.items.append(PlanchaItem(path=image["path"], name=image.get("name") or Path(image["path"]).name, width_cm=proposal["width"], height_cm=proposal["height"], x_cm=position[0], y_cm=position[1], quantity=proposal["count"], copy_number=copy_number, group_id=group_id, source="Relleno"))
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
                for copy_number in range(1, proposal["count"] + 1):
                    position = self.find_free_position(proposal["width"], proposal["height"])
                    if not position:
                        break
                    image = proposal["image"]
                    self.project.items.append(PlanchaItem(path=image["path"], name=image.get("name") or Path(image["path"]).name, width_cm=proposal["width"], height_cm=proposal["height"], x_cm=position[0], y_cm=position[1], quantity=proposal["count"], copy_number=copy_number, group_id=group_id, source="Relleno"))
            self.optimize()
            dialog.grab_release()
            dialog.destroy()

        ttk.Button(dialog, text="Agregar seleccionados", command=confirm).pack(anchor="e", padx=16, pady=14)

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
                target = (max(1, round(item.width_cm / 2.54 * dpi)), max(1, round(item.height_cm / 2.54 * dpi)))
                try:
                    modified = Path(item.path).stat().st_mtime
                except OSError:
                    modified = -1.0
                cache_key = (item.path, modified, target[0], target[1], item.rotation, "contorno-v4")
                sticker = self.production_sticker_cache.get(cache_key)
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
                    sticker = prepare_sticker_for_target(sticker, target, outlined=outlined)
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
                x = round(item.x_cm / 2.54 * dpi) + (target[0] - sticker.width) // 2
                y = round(item.y_cm / 2.54 * dpi) + (target[1] - sticker.height) // 2
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

    def export_preview(self):
        if not self.project.items:
            return
        if self.database and not self.plancha_id:
            messagebox.showwarning("Vista previa", "Guardá primero el proyecto editable para vincular la aprobación a esta plancha.", parent=self)
            return
        material = "Vinilo"
        if self.database and self.order_id:
            material = (self.database.order(self.order_id) or {}).get("material") or material
        path = filedialog.asksaveasfilename(title="Guardar vista previa", defaultextension=".jpg", filetypes=[("JPG", "*.jpg")])
        if not path:
            return
        sheet = self.render_sheet(preview=True).convert("RGB")
        sheet.save(path, "JPEG", quality=95, subsampling=0, dpi=(300, 300), icc_profile=None)
        if self.database and self.plancha_id:
            self.database.request_plancha_approval(self.plancha_id, path)
            self._sync_open_order_after_approval()
            self.refresh_approval_panel()
            self.refresh_printing_panel()
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
            
            # Renderizar sin hitboxes con fondo de Doccione
            sheet = self.render_sheet_clean()
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

    def render_sheet_clean(self):
        """Renderiza la plancha limpia (sin hitboxes ni watermark) para vistas previas del pedido."""
        from PIL import Image
        
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
                cache_key = (item.path, modified, target[0], target[1], item.rotation, "contorno-v4")
                sticker = self.production_sticker_cache.get(cache_key)
                if sticker is None:
                    with Image.open(item.path) as original:
                        sticker = original.convert("RGBA")
                    sticker = sticker.crop(visible_bbox(sticker))
                    outlined = needs_silhouette_outline(sticker)
                    if item.rotation:
                        sticker = sticker.rotate(-item.rotation, expand=True)
                    sticker = prepare_sticker_for_target(sticker, target, outlined=outlined)
                    pixels = sticker.width * sticker.height
                    while self.production_sticker_cache and self.production_sticker_cache_pixels + pixels > 30_000_000:
                        _old_key, old = self.production_sticker_cache.popitem(last=False)
                        self.production_sticker_cache_pixels -= old.width * old.height
                    self.production_sticker_cache[cache_key] = sticker
                    self.production_sticker_cache_pixels += pixels
                else:
                    self.production_sticker_cache.move_to_end(cache_key)
                
                x = round(item.x_cm / 2.54 * dpi) + (target[0] - sticker.width) // 2
                y = round(item.y_cm / 2.54 * dpi) + (target[1] - sticker.height) // 2
                sheet.alpha_composite(sticker, (x, y))
            except Exception:
                continue
        
        # Componer la capa de diseños sobre el fondo de Doccione
        background.paste(sheet, (0, 0), sheet)
        return background

    def export_final(self):
        if not self.project.items:
            return
        if self.database and self.plancha_id and self._linked_order_id():
            approval = (self.database.plancha_project(self.plancha_id) or {}).get("approval_status")
            if approval != "Aprobada":
                messagebox.showwarning("Exportación final", "La plancha debe estar aprobada antes de generar el PNG final.", parent=self)
                return
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
        progress_dialog, report_progress = self.creation_progress_dialog(len(self.project.items), "Exportando PNG final")
        report_progress(0, len(self.project.items), "Preparando exportación a 300 DPI")
        try:
            sheet = self.render_sheet(preview=False, progress=report_progress)
            report_progress(len(self.project.items), len(self.project.items), "Guardando PNG final")
            # PNG sigue siendo totalmente sin pérdida; una compresión moderada
            # solo reduce el tiempo de guardado y puede generar un archivo algo mayor.
            sheet.save(output, "PNG", dpi=(300, 300), compress_level=3)
            export_completed = True
            report_progress(len(self.project.items) + 1, len(self.project.items) + 1, "PNG final listo")
        finally:
            record_performance(
                "export_final_png",
                (time.perf_counter() - export_started) * 1000,
                stickers=len(self.project.items), completed=export_completed,
            )
            self.after(180, lambda: progress_dialog.destroy() if progress_dialog.winfo_exists() else None)
        if self.database:
            self.database.record_plancha_usage([item.to_dict() for item in self.project.items])
            self.final_png_path = str(output)
            if self.plancha_id:
                self.database.set_plancha_final_png(self.plancha_id, self.final_png_path)
        self.refresh_printing_panel()
        self.refresh_approval_panel()
        messagebox.showinfo("PNG final guardado", f"El PNG final quedó listo para Producción.\n\n{output}", parent=self)

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
            self.project.save(path)
            self.project_path = path
            if self.database:
                order_id = self._linked_order_id()
                material = ""
                if order_id:
                    order = self.database.order(order_id)
                    material = (order or {}).get("material", "")
                self.plancha_id = self.database.save_plancha_project(
                    order_id, Path(path).stem, material, json.dumps(self.project.to_dict(), ensure_ascii=False), path, self.plancha_id,
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

    def open_project(self):
        path = filedialog.askopenfilename(title="Abrir proyecto de plancha", filetypes=[("Proyecto Doccione", "*.doccione-plancha.json *.json")])
        if not path:
            return
        try:
            self.project = PlanchaProject.load(path)
            self.project_path = path
            saved_plancha = self.database.plancha_by_project_path(path) if self.database else None
            self.plancha_id = saved_plancha.get("id") if saved_plancha else None
            self.order_id = saved_plancha.get("order_id") if saved_plancha else None
            self.final_png_path = saved_plancha.get("final_png_path") if saved_plancha else ""
            self.selected_id = None
            self.selected_ids.clear()
            self.history, self.future = [], []
            self.optimize()
            self.refresh_printing_panel()
            self.refresh_approval_panel()
        except Exception as error:
            messagebox.showerror("No se pudo abrir", str(error), parent=self)
