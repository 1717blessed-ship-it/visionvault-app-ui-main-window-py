"""Interfaz de cola, revisión y aprobación para crear stickers."""
from __future__ import annotations
import json
import inspect
import math
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk
from app.indexer.scanner import IMAGE_EXTENSIONS
from app.stickers.pipeline import (
    ProcessingProfile, ProcessingResult, StickerProcessor,
    ProcessingCancelled,
    VISUAL_STICKER_TYPES, VISUAL_STICKER_TYPE_IDS_BY_LABEL,
)
from app.stickers.profile_editor import ProcessingProfileEditor
from app.ui.theme import COLORS, IDENTITY_FONT, UI_FONT, apply_ttk_theme


def _fit_window_to_screen(window, default_width, default_height, min_width, min_height,
                          width_ratio=0.92, height_ratio=0.85):
    screen_w = window.winfo_screenwidth()
    screen_h = window.winfo_screenheight()
    width = min(default_width, round(screen_w * width_ratio))
    height = min(default_height, round(screen_h * height_ratio))
    width = max(width, min_width)
    height = max(height, min_height)
    window.geometry(f"{width}x{height}")
    window.minsize(min_width, min_height)


def _build_superposition_image(original_path, mask_path):
    from PIL import Image
    import cv2
    import numpy as np
    
    orig_img = Image.open(original_path).convert("RGBA")
    mask_img = Image.open(mask_path).convert("L")
    
    w, h = orig_img.size
    orig_arr = np.array(orig_img)
    mask_arr = np.array(mask_img)
    
    base_arr = orig_arr.copy()
    base_arr[:, :, 3] = (base_arr[:, :, 3] * 0.5).astype(np.uint8)
    base_img = Image.fromarray(base_arr, mode="RGBA")
    
    overlay_arr = np.zeros((h, w, 4), dtype=np.uint8)
    overlay_arr[mask_arr == 0] = [20, 20, 20, 100]
    
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask_arr, connectivity=8)
    largest_idx = -1
    if num_labels > 1:
        areas = stats[1:, cv2.CC_STAT_AREA]
        largest_idx = int(np.argmax(areas)) + 1
        
    if largest_idx != -1:
        overlay_arr[labels == largest_idx] = [0, 255, 0, 50]
        
    for i in range(1, num_labels):
        if i == largest_idx:
            continue
        overlay_arr[labels == i] = [255, 165, 0, 160]
        
    alpha = orig_arr[:, :, 3]
    ref_mask = alpha > 12
    incorrect_removed = ref_mask & (mask_arr == 0)
    overlay_arr[incorrect_removed] = [0, 255, 255, 200]
    
    overlay_img = Image.fromarray(overlay_arr, mode="RGBA")
    result_img = Image.new("RGBA", orig_img.size, (17, 19, 20, 255))
    result_img.alpha_composite(base_img)
    result_img.alpha_composite(overlay_img)
    return result_img


def make_checkerboard_preview(image, tile_size=12):
    """Crea una vista previa con patrón cuadriculado para mostrar transparencia."""
    from PIL import Image, ImageDraw
    
    rgba = image.convert("RGBA")
    width, height = rgba.size

    checker = Image.new("RGBA", (width, height), (238, 238, 238, 255))
    draw = ImageDraw.Draw(checker)

    secondary = (205, 205, 205, 255)

    for y in range(0, height, tile_size):
        for x in range(0, width, tile_size):
            if (x // tile_size + y // tile_size) % 2:
                draw.rectangle(
                    (x, y, min(x + tile_size - 1, width - 1), min(y + tile_size - 1, height - 1)),
                    fill=secondary,
                )

    checker.alpha_composite(rgba)
    return checker.convert("RGB")


def make_white_background_preview(image):
    """Crea una vista previa con fondo blanco para mostrar transparencia."""
    from PIL import Image
    
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    background.alpha_composite(rgba)
    return background.convert("RGB")


def make_black_background_preview(image):
    """Crea una vista previa con fondo negro para mostrar transparencia."""
    from PIL import Image
    
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (17, 19, 20, 255))
    background.alpha_composite(rgba)
    return background.convert("RGB")


class AreaSelectionEditor(tk.Toplevel):
    """Recorte rectangular no destructivo para fotos, capturas y publicaciones."""

    def __init__(self, master, original_path: str | Path, on_selected):
        super().__init__(master)
        from PIL import Image, ImageOps
        self.title("Seleccionar área de la imagen")
        self.geometry("930x760")
        self.minsize(680, 540)
        self.configure(background=COLORS.background)
        self.transient(master)
        self.grab_set()
        self.original_path = Path(original_path)
        self.on_selected = on_selected
        with Image.open(self.original_path) as source:
            self.original = ImageOps.exif_transpose(source).convert("RGBA")

        self.photo = None
        self.image_item = None
        self.display_scale = 1.0
        self.display_offset = (0, 0)
        self.zoom = 1.0
        self.drag_start = None
        self.drag_start_image = None
        self.selection_action = None
        self.selection_handle = None
        self.selection_box = None
        self.selection_angle = tk.DoubleVar(value=0.0)
        self.selection_item = None
        self.selection_handle_items = []
        self._build()
        self.after_idle(self.render)

    def _initialize_default_selection(self):
        if self.original.width < 20 or self.original.height < 20:
            return
        margin_w = max(1, round(self.original.width * 0.12))
        margin_h = max(1, round(self.original.height * 0.12))
        self.selection_box = (
            margin_w,
            margin_h,
            max(margin_w + 10, self.original.width - margin_w),
            max(margin_h + 10, self.original.height - margin_h),
        )

    def _build(self):
        header = tk.Frame(self, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        header.pack(fill="x", padx=12, pady=12)
        title = tk.Frame(header, background=COLORS.panel)
        title.pack(side="left", padx=12, pady=8)
        tk.Label(title, text="SELECCIONAR ÁREA", background=COLORS.panel, foreground=COLORS.text,
                 font=(IDENTITY_FONT, 14, "bold")).pack(anchor="w")
        tk.Label(
            title,
            text="Arrastrá sobre la foto: se conservará esa zona íntegra y el borde se agregará solo alrededor de ella.",
            background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 9),
        ).pack(anchor="w", pady=(2, 0))
        ttk.Button(header, text="Cancelar", command=self.destroy,
                   style="Secondary.TButton").pack(side="right", padx=(3, 10), pady=10)
        ttk.Button(header, text="Usar imagen completa", command=self.use_full_image,
                   style="Secondary.TButton").pack(side="right", padx=3, pady=10)
        ttk.Button(header, text="Aplicar borde a selección", command=lambda: self.confirm_selection("selection"),
                   style="Primary.TButton").pack(side="right", padx=3, pady=10)

        rotation = tk.Frame(self, background=COLORS.panel)
        rotation.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(rotation, text="Rotación libre", background=COLORS.panel,
                 foreground=COLORS.text, font=(UI_FONT, 9, "bold")).pack(side="left", padx=(12, 8), pady=7)
        self.rotation_value = tk.Label(rotation, text="0°", width=6,
                                       background=COLORS.panel, foreground=COLORS.muted,
                                       font=(UI_FONT, 9))
        self.rotation_value.pack(side="right", padx=(4, 12))
        ttk.Button(rotation, text="Restablecer", command=self.reset_rotation,
                   style="Secondary.TButton").pack(side="right", padx=4, pady=4)
        self.rotation_scale = tk.Scale(
            rotation, from_=-180, to=180, resolution=1, orient="horizontal",
            showvalue=False, variable=self.selection_angle, command=self.update_rotation,
            background=COLORS.panel, foreground=COLORS.text, troughcolor=COLORS.border,
            highlightthickness=0, borderwidth=0,
        )
        self.rotation_scale.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=2)

        view = tk.Frame(self, background=COLORS.background)
        view.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.canvas = tk.Canvas(
            view, background="#0d0f10", highlightthickness=1,
            highlightbackground=COLORS.border, cursor="crosshair",
        )
        vert = ttk.Scrollbar(view, orient="vertical", command=self.canvas.yview)
        horz = ttk.Scrollbar(view, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vert.set, xscrollcommand=horz.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vert.grid(row=0, column=1, sticky="ns")
        horz.grid(row=1, column=0, sticky="ew")
        view.grid_rowconfigure(0, weight=1)
        view.grid_columnconfigure(0, weight=1)
        self.canvas.bind("<Configure>", lambda _event: self.render())
        self.canvas.bind("<ButtonPress-1>", self.start_selection)
        self.canvas.bind("<B1-Motion>", self.update_selection)
        self.canvas.bind("<ButtonRelease-1>", self.finish_selection)
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.canvas.bind("<Shift-MouseWheel>", lambda e: self.canvas.xview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.canvas.bind("<Control-MouseWheel>", self.zoom_with_wheel)
        self.bind("<Escape>", lambda _event: self.destroy())

    def zoom_with_wheel(self, event):
        factor = 1.18 if event.delta > 0 else 1 / 1.18
        self.zoom = min(6.0, max(0.35, self.zoom * factor))
        self.render()
        return "break"

    def update_rotation(self, value):
        angle = float(value)
        self.rotation_value.configure(text=f"{angle:.0f}°")
        self._draw_selection()

    def reset_rotation(self):
        self.selection_angle.set(0.0)
        self.update_rotation(0.0)

    def render(self):
        from PIL import Image, ImageTk

        available_w = max(100, self.canvas.winfo_width() - 32)
        available_h = max(100, self.canvas.winfo_height() - 32)
        fit_scale = min(available_w / self.original.width, available_h / self.original.height)
        self.display_scale = fit_scale * self.zoom
        size = (
            max(1, round(self.original.width * self.display_scale)),
            max(1, round(self.original.height * self.display_scale)),
        )
        preview = self.original.resize(size, Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(preview)
        self.display_offset = (0, 0)
        self.canvas.delete("all")
        self.selection_item = None
        self.selection_handle_items = []
        self.image_item = self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.configure(scrollregion=(0, 0, size[0], size[1]))
        if self.selection_box:
            self._draw_selection()

    def _canvas_to_image(self, x, y):
        offset_x, offset_y = self.display_offset
        image_x = round((x - offset_x) / max(self.display_scale, .001))
        image_y = round((y - offset_y) / max(self.display_scale, .001))
        return (
            min(self.original.width, max(0, image_x)),
            min(self.original.height, max(0, image_y)),
        )

    def start_selection(self, event):
        point = self._canvas_to_image(event.x, event.y)
        if self.selection_box:
            handle = self._get_handle_under_point(*point)
            if handle:
                self.selection_action = "resize"
                self.selection_handle = handle
                self.drag_start = point
                return
            if self._point_in_box(point, self.selection_box):
                self.selection_action = "move"
                self.drag_start = point
                self.drag_start_image = self.selection_box
                return
        self.selection_action = "draw"
        self.drag_start = point
        self.selection_box = (*point, *point)
        self._draw_selection()

    def update_selection(self, event):
        if self.selection_action is None or self.drag_start is None:
            return
        current = self._canvas_to_image(event.x, event.y)
        if self.selection_action == "draw":
            x1, y1 = self.drag_start
            self.selection_box = (min(x1, current[0]), min(y1, current[1]), max(x1, current[0]), max(y1, current[1]))
        elif self.selection_action == "move":
            ox1, oy1, ox2, oy2 = self.drag_start_image
            dx = current[0] - self.drag_start[0]
            dy = current[1] - self.drag_start[1]
            self.selection_box = self._clip_box_to_bounds(
                ox1 + dx, oy1 + dy, ox2 + dx, oy2 + dy,
            )
        elif self.selection_action == "resize":
            x1, y1, x2, y2 = self.selection_box
            if self.selection_handle == "tl":
                x1, y1 = current
            elif self.selection_handle == "tr":
                x2, y1 = current
            elif self.selection_handle == "bl":
                x1, y2 = current
            elif self.selection_handle == "br":
                x2, y2 = current
            self.selection_box = self._clip_box_to_bounds(x1, y1, x2, y2)
        self._draw_selection()

    def finish_selection(self, event):
        self.update_selection(event)
        self.drag_start = None
        self.drag_start_image = None
        self.selection_action = None
        self.selection_handle = None

    def _clear_selection_items(self):
        if self.selection_item:
            self.canvas.delete(self.selection_item)
            self.selection_item = None
        if self.selection_handle_items:
            for item in self.selection_handle_items:
                self.canvas.delete(item)
            self.selection_handle_items = []

    def _draw_selection(self):
        if not self.selection_box:
            self._clear_selection_items()
            return
        x1, y1, x2, y2 = self.selection_box
        offset_x, offset_y = self.display_offset
        coords = (
            offset_x + x1 * self.display_scale,
            offset_y + y1 * self.display_scale,
            offset_x + x2 * self.display_scale,
            offset_y + y2 * self.display_scale,
        )
        # Dibujar la selección con el ángulo elegido para que la vista previa
        # coincida con el recorte que se guardará.
        x1c, y1c, x2c, y2c = coords
        cx, cy = (x1c + x2c) / 2, (y1c + y2c) / 2
        angle = math.radians(float(self.selection_angle.get()))
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        polygon = []
        for px, py in ((x1c, y1c), (x2c, y1c), (x2c, y2c), (x1c, y2c)):
            dx, dy = px - cx, py - cy
            polygon.extend((cx + dx * cos_a - dy * sin_a,
                            cy + dx * sin_a + dy * cos_a))
        if self.selection_item is None:
            self.selection_item = self.canvas.create_polygon(
                *polygon, outline=COLORS.wine_active, fill="", width=3,
                dash=(8, 4)
            )
        else:
            self.canvas.coords(self.selection_item, *polygon)
        self._draw_selection_handles()

    def _draw_selection_handles(self):
        if not self.selection_box:
            return
        x1, y1, x2, y2 = self.selection_box
        offset_x, offset_y = self.display_offset
        size = 10
        half = size // 2
        handle_coordinates = []
        for cx, cy in ((x1, y1), (x2, y1), (x1, y2), (x2, y2)):
            canvas_coords = (
                offset_x + cx * self.display_scale - half,
                offset_y + cy * self.display_scale - half,
                offset_x + cx * self.display_scale + half,
                offset_y + cy * self.display_scale + half,
            )
            handle_coordinates.append(canvas_coords)
        if len(self.selection_handle_items) == len(handle_coordinates):
            for handle, canvas_coords in zip(self.selection_handle_items, handle_coordinates):
                self.canvas.coords(handle, *canvas_coords)
        else:
            for handle in self.selection_handle_items:
                self.canvas.delete(handle)
            self.selection_handle_items = [
                self.canvas.create_rectangle(
                    *canvas_coords, fill=COLORS.wine_active,
                    outline=COLORS.panel, width=1,
                )
                for canvas_coords in handle_coordinates
            ]

    def _clip_box_to_bounds(self, x1, y1, x2, y2):
        min_x = min(x1, x2)
        min_y = min(y1, y2)
        max_x = max(x1, x2)
        max_y = max(y1, y2)
        min_x = max(0, min(min_x, self.original.width))
        min_y = max(0, min(min_y, self.original.height))
        max_x = max(0, min(max_x, self.original.width))
        max_y = max(0, min(max_y, self.original.height))
        return (min_x, min_y, max_x, max_y)

    def _point_in_box(self, point, box):
        x, y = point
        x1, y1, x2, y2 = box
        return x1 <= x <= x2 and y1 <= y <= y2

    def _get_handle_under_point(self, x, y):
        if not self.selection_box:
            return None
        x1, y1, x2, y2 = self.selection_box
        threshold = max(8, round(12 / self.display_scale))
        candidates = {
            "tl": (x1, y1),
            "tr": (x2, y1),
            "bl": (x1, y2),
            "br": (x2, y2),
        }
        for name, (hx, hy) in candidates.items():
            if abs(x - hx) <= threshold and abs(y - hy) <= threshold:
                return name
        return None

    def confirm_selection(self, mode):
        if not self.selection_box:
            messagebox.showinfo("Seleccionar área", "Arrastrá sobre la imagen para marcar el contenido.", parent=self)
            return
        x1, y1, x2, y2 = self.selection_box
        if x2 - x1 < 12 or y2 - y1 < 12:
            messagebox.showwarning("Selección pequeña", "Marcá un área un poco más grande.", parent=self)
            return
        self.grab_release()
        self.destroy()
        self._notify_selected(
            self.selection_box, self.original.copy(), mode,
            float(self.selection_angle.get()),
        )

    def _notify_selected(self, box, image, mode, angle):
        """Notifica con ángulo y conserva callbacks antiguos de tres args."""
        try:
            parameters = inspect.signature(self.on_selected).parameters.values()
            accepts_angle = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in parameters) or len(
                [p for p in parameters if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)]
            ) >= 4
        except (TypeError, ValueError):
            accepts_angle = True
        if accepts_angle:
            self.on_selected(box, image, mode, angle)
        else:
            self.on_selected(box, image, mode)

    def use_full_image(self):
        self.grab_release()
        self.destroy()
        self._notify_selected(None, None, "full", 0.0)


class ProtectionZoneEditor(tk.Toplevel):
    """Editor de zonas de protección: el usuario pinta rectángulos sobre la
    imagen original marcando las áreas que el pipeline NO debe tocar.

    Las zonas se muestran en rojo semitransparente.  Se pueden agregar
    múltiples rectángulos, deshacer el último y limpiar todo.

    Al confirmar devuelve: on_confirmed(zones: list[tuple[int,int,int,int]])
    Cada zona es (x1, y1, x2, y2) en coordenadas de la imagen original.
    """

    _FILL_COLOR   = "#cc2200"   # rojo para el overlay
    _FILL_ALPHA   = 90          # 0–255, semitransparente
    _OUTLINE      = "#ff4422"

    def __init__(self, master, original_path: str | Path,
                 existing_zones: list | None,
                 on_confirmed):
        super().__init__(master)
        from PIL import Image, ImageOps

        self.title("Proteger zonas de la imagen")
        _fit_window_to_screen(self, 960, 780, 700, 560)
        self.configure(background=COLORS.background)
        self.transient(master)
        self.grab_set()

        self.original_path  = Path(original_path)
        self.on_confirmed   = on_confirmed
        self._zones: list[tuple[int,int,int,int]] = list(existing_zones or [])
        self._drag_start    = None
        self._live_rect     = None   # ítem canvas del rect en curso
        self.display_scale  = 1.0
        self.display_offset = (0, 0)
        self.zoom           = 1.0
        self._photo_base    = None   # foto base sin overlay
        self._photo_overlay = None   # foto con overlay renderizado

        with Image.open(self.original_path) as src:
            self._original = ImageOps.exif_transpose(src).convert("RGBA")

        self._build()
        self.after_idle(self._render)

    # ── UI ────────────────────────────────────────────────────────────────

    def _build(self):
        header = tk.Frame(self, background=COLORS.panel,
                          highlightthickness=1, highlightbackground=COLORS.border)
        header.pack(fill="x", padx=12, pady=12)

        title_col = tk.Frame(header, background=COLORS.panel)
        title_col.pack(side="left", padx=12, pady=10)
        tk.Label(title_col, text="PROTEGER ZONAS",
                 background=COLORS.panel, foreground=COLORS.text,
                 font=(IDENTITY_FONT, 14, "bold")).pack(anchor="w")
        tk.Label(
            title_col,
            text="Arrastrá para marcar zonas que el pipeline NO debe eliminar. "
                 "Podés agregar varias. El archivo original no cambia.",
            background=COLORS.panel, foreground=COLORS.muted,
            font=(UI_FONT, 9),
        ).pack(anchor="w", pady=(2, 0))

        btn_col = tk.Frame(header, background=COLORS.panel)
        btn_col.pack(side="right", padx=10, pady=10)
        ttk.Button(btn_col, text="Cancelar",
               command=lambda *a, _fn=self.destroy: _fn(*a),
               style="Secondary.TButton").pack(side="right", padx=(3, 0))
        ttk.Button(btn_col, text="Sin protección",
               command=lambda *a, _fn=self._clear_and_confirm: _fn(*a),
               style="Secondary.TButton").pack(side="right", padx=3)
        ttk.Button(btn_col, text="Limpiar zonas",
               command=lambda *a, _fn=self._clear_zones: _fn(*a),
               style="Secondary.TButton").pack(side="right", padx=3)
        ttk.Button(btn_col, text="Deshacer",
               command=lambda *a, _fn=self._undo: _fn(*a),
               style="Secondary.TButton").pack(side="right", padx=3)
        ttk.Button(btn_col, text="Confirmar zonas",
               command=lambda *a, _fn=self._confirm: _fn(*a),
               style="Primary.TButton").pack(side="right", padx=3)

        # Contador de zonas
        self._zone_count_var = tk.StringVar(value="0 zonas marcadas")
        tk.Label(header, textvariable=self._zone_count_var,
                 background=COLORS.panel, foreground=COLORS.wine_active,
                 font=(UI_FONT, 9, "bold")).pack(side="right", padx=12)

        view = tk.Frame(self, background=COLORS.background)
        view.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._canvas = tk.Canvas(
            view, background="#0d0f10",
            highlightthickness=1, highlightbackground=COLORS.border,
            cursor="crosshair",
        )
        vert = ttk.Scrollbar(view, orient="vertical", command=self._canvas.yview)
        horz = ttk.Scrollbar(view, orient="horizontal", command=self._canvas.xview)
        self._canvas.configure(yscrollcommand=vert.set, xscrollcommand=horz.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        vert.grid(row=0, column=1, sticky="ns")
        horz.grid(row=1, column=0, sticky="ew")
        view.grid_rowconfigure(0, weight=1)
        view.grid_columnconfigure(0, weight=1)
        self._canvas.bind("<Configure>", lambda _e: self._render())
        self._canvas.bind("<ButtonPress-1>",   self._on_press)
        self._canvas.bind("<B1-Motion>",       self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<MouseWheel>", lambda e: self._canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self._canvas.bind("<Shift-MouseWheel>", lambda e: self._canvas.xview_scroll(-1 if e.delta > 0 else 1, "units"))
        self._canvas.bind("<Control-MouseWheel>", self.zoom_with_wheel)
        self.bind("<Control-z>", lambda _e: self._undo())
        self.bind("<Escape>",    lambda _e: self.destroy())

    # ── Conversión de coordenadas ─────────────────────────────────────────

    def _canvas_to_image(self, cx, cy):
        ox, oy = self.display_offset
        ix = round((cx - ox) / max(self.display_scale, 1e-6))
        iy = round((cy - oy) / max(self.display_scale, 1e-6))
        return (
            min(self._original.width,  max(0, ix)),
            min(self._original.height, max(0, iy)),
        )

    def _image_to_canvas(self, ix, iy):
        ox, oy = self.display_offset
        return ox + ix * self.display_scale, oy + iy * self.display_scale

    # ── Render ────────────────────────────────────────────────────────────

    def zoom_with_wheel(self, event):
        factor = 1.18 if event.delta > 0 else 1 / 1.18
        self.zoom = min(6.0, max(0.35, self.zoom * factor))
        self._render()
        return "break"

    def _render(self):
        from PIL import Image, ImageDraw, ImageTk

        cw = max(100, self._canvas.winfo_width()  - 32)
        ch = max(100, self._canvas.winfo_height() - 32)
        fit_scale = min(cw / self._original.width,
                        ch / self._original.height)
        self.display_scale = fit_scale * self.zoom
        sw = max(1, round(self._original.width  * self.display_scale))
        sh = max(1, round(self._original.height * self.display_scale))

        self.display_offset = (0, 0)

        # Base: imagen escalada sobre fondo oscuro
        base = Image.new("RGBA", (sw, sh), "#111314")
        scaled = self._original.resize((sw, sh), Image.Resampling.LANCZOS)
        base.alpha_composite(scaled)

        # Overlay: zonas protegidas en rojo semitransparente
        if self._zones:
            overlay = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
            draw    = ImageDraw.Draw(overlay)
            r, g, b = 0xcc, 0x22, 0x00
            for x1, y1, x2, y2 in self._zones:
                cx1 = round(x1 * self.display_scale)
                cy1 = round(y1 * self.display_scale)
                cx2 = round(x2 * self.display_scale)
                cy2 = round(y2 * self.display_scale)
                draw.rectangle([cx1, cy1, cx2, cy2],
                               fill=(r, g, b, self._FILL_ALPHA),
                               outline=(0xff, 0x44, 0x22, 220), width=2)
            base.alpha_composite(overlay)

        self._photo_overlay = ImageTk.PhotoImage(base)
        self._canvas.delete("all")
        self._live_rect = None
        self._canvas.create_image(0, 0, anchor="nw",
                                  image=self._photo_overlay)
        self._canvas.configure(scrollregion=(0, 0, sw, sh))
        self._update_counter()

    def _update_counter(self):
        n = len(self._zones)
        self._zone_count_var.set(
            "Sin zonas marcadas" if n == 0
            else f"{n} zona{'s' if n != 1 else ''} marcada{'s' if n != 1 else ''}"
        )

    # ── Interacción ───────────────────────────────────────────────────────

    def _on_press(self, event):
        self._drag_start = self._canvas_to_image(event.x, event.y)

    def _on_drag(self, event):
        if not self._drag_start:
            return
        x1, y1 = self._drag_start
        x2, y2 = self._canvas_to_image(event.x, event.y)
        cx1, cy1 = self._image_to_canvas(min(x1,x2), min(y1,y2))
        cx2, cy2 = self._image_to_canvas(max(x1,x2), max(y1,y2))
        if self._live_rect is None:
            self._live_rect = self._canvas.create_rectangle(
                cx1, cy1, cx2, cy2,
                outline=self._OUTLINE, width=2, dash=(6, 3),
            )
        else:
            self._canvas.coords(self._live_rect, cx1, cy1, cx2, cy2)

    def _on_release(self, event):
        if not self._drag_start:
            return
        x1, y1 = self._drag_start
        x2, y2 = self._canvas_to_image(event.x, event.y)
        self._drag_start = None
        if self._live_rect:
            self._canvas.delete(self._live_rect)
            self._live_rect = None
        bx1, by1 = min(x1, x2), min(y1, y2)
        bx2, by2 = max(x1, x2), max(y1, y2)
        # Ignorar rectángulos demasiado pequeños
        if bx2 - bx1 < 8 or by2 - by1 < 8:
            return
        self._zones.append((bx1, by1, bx2, by2))
        self._render()

    def _undo(self):
        if self._zones:
            self._zones.pop()
            self._render()

    def _clear_zones(self):
        self._zones.clear()
        self._render()

    # ── Confirmación ──────────────────────────────────────────────────────

    def _confirm(self):
        self.grab_release()
        self.destroy()
        self.on_confirmed(list(self._zones))

    def _clear_and_confirm(self):
        """Quita todas las zonas y confirma → el pipeline trabaja sin restricciones."""
        self.grab_release()
        self.destroy()
        self.on_confirmed([])


class MaskEditor(tk.Toplevel):
    """Edición no destructiva: silueta, pincel, cuentagotas y zoom."""

    _VIEW_LEGENDS = {
        "Superposición": (
            "Verde = se conserva · rojo = se quita · el color original permanece como referencia."
        ),
        "Máscara": "Blanco = se conserva · negro = transparencia. Esta vista no muestra el diseño.",
        "Original": "Referencia original: esta vista no aplica la máscara.",
        "Recorte": "Vista del recorte actual sobre el fondo elegido; el borde final se genera al reprocesar.",
    }

    def __init__(self, master, original_path, mask_path, on_saved, *, editing_target="mask"):
        super().__init__(master)
        from PIL import Image

        self.title("Modificar sticker")
        _fit_window_to_screen(self, 900, 720, 660, 520)
        self.configure(background=COLORS.background)
        self.transient(master)
        self.original_path = Path(original_path)
        self.mask_path = Path(mask_path)
        self.on_saved = on_saved
        self.editing_target = editing_target
        with Image.open(self.original_path) as source:
            self.original = source.convert("RGBA")
        with Image.open(self.mask_path) as source:
            # Usar NEAREST para mantener la precisión de la máscara al redimensionar
            self.mask = source.convert("L").resize(self.original.size, Image.Resampling.NEAREST)
        # La máscara se guarda sobre el artefacto de trabajo al confirmar. Esta
        # copia permite volver al estado con el que se abrió el editor sin tocar
        # ningún archivo hasta que el usuario aplique los cambios.
        self._opened_mask = self.mask.copy()
        self.mode = tk.StringVar(value="erase")
        self.brush = tk.IntVar(value=36)
        self.brush_label = tk.StringVar(value="36 px")
        self.lasso_action = tk.StringVar(value="Quitar")
        self.preview_mode = tk.StringVar(value="Superposición")
        self.preview_background = tk.StringVar(value="Cuadriculado")
        self.preview_legend = tk.StringVar()
        self.zoom_label = tk.StringVar(value="Ajustar")
        self._lasso_points: list[tuple[float, float]] = []
        self.brush_color = "#ffffff"
        self.zoom = 1.0
        self.image_modified = False
        self.photo = None
        self.display_scale = 1.0
        self._render_after = None
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._active_stroke: dict | None = None
        self._build()
        self.preview_mode.trace_add("write", self._preview_options_changed)
        self.preview_background.trace_add("write", self._preview_options_changed)
        self._update_preview_legend()
        self.after_idle(self.render)

    def _build(self):
        bar = tk.Frame(self, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        bar.pack(fill="x", padx=12, pady=12)
        title_row = tk.Frame(bar, background=COLORS.panel)
        title_row.pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(title_row, text="MODIFICAR STICKER", background=COLORS.panel, foreground=COLORS.text,
                 font=(IDENTITY_FONT, 13, "bold")).pack(side="left")
        tk.Label(
            title_row,
            text="La máscara se edita sobre una copia hasta aplicar.",
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 9),
        ).pack(side="right")

        # Separar las herramientas de la vista evita que una ventana angosta
        # oculte los controles más importantes.
        tools_row = tk.Frame(bar, background=COLORS.panel)
        tools_row.pack(fill="x", padx=12, pady=(2, 2))
        ttk.Radiobutton(tools_row, text="Quitar", value="erase", variable=self.mode).pack(side="left", padx=(0, 4), pady=3)
        ttk.Radiobutton(tools_row, text="Recuperar", value="restore", variable=self.mode).pack(side="left", padx=4, pady=3)
        ttk.Radiobutton(tools_row, text="Pincel", value="paint", variable=self.mode).pack(side="left", padx=4, pady=3)
        ttk.Radiobutton(tools_row, text="Lazo", value="lasso", variable=self.mode).pack(side="left", padx=4, pady=3)
        ttk.Radiobutton(tools_row, text="Lazo poligonal", value="polygon_lasso", variable=self.mode).pack(side="left", padx=4, pady=3)

        brush_row = tk.Frame(bar, background=COLORS.panel)
        brush_row.pack(fill="x", padx=12, pady=(0, 2))
        ttk.Combobox(brush_row, textvariable=self.lasso_action, values=("Quitar", "Recuperar"),
                     state="readonly", width=10).pack(side="left", padx=(0, 6))
        ttk.Button(brush_row, text="Cuentagotas", command=lambda: self.mode.set("eyedropper")).pack(side="left", padx=(0, 5))
        self.color_button = tk.Button(brush_row, text="   ", background=self.brush_color, activebackground=self.brush_color,
                          command=lambda *a, _fn=self.choose_color: _fn(*a), relief="flat", cursor="hand2")
        self.color_button.pack(side="left", padx=3)
        tk.Label(brush_row, text="Pincel", background=COLORS.panel, foreground=COLORS.muted).pack(side="left", padx=(12, 4))
        ttk.Scale(brush_row, from_=6, to=140, variable=self.brush, orient="horizontal", length=105).pack(side="left")
        tk.Label(brush_row, textvariable=self.brush_label, background=COLORS.panel,
                 foreground=COLORS.muted, width=6, anchor="e").pack(side="left", padx=(4, 10))
        self.brush.trace_add("write", self._refresh_brush_label)

        preview_row = tk.Frame(bar, background=COLORS.panel)
        preview_row.pack(fill="x", padx=12, pady=(0, 2))
        tk.Label(preview_row, text="Vista", background=COLORS.panel, foreground=COLORS.muted).pack(side="left", padx=(0, 4))
        preview_mode = ttk.Combobox(
            preview_row,
            textvariable=self.preview_mode,
            values=("Superposición", "Máscara", "Original", "Recorte"),
            state="readonly",
            width=13,
        )
        preview_mode.pack(side="left", padx=(0, 10))
        tk.Label(preview_row, text="Fondo", background=COLORS.panel, foreground=COLORS.muted).pack(side="left", padx=(0, 4))
        preview_background = ttk.Combobox(
            preview_row,
            textvariable=self.preview_background,
            values=("Cuadriculado", "Blanco", "Negro"),
            state="readonly",
            width=12,
        )
        preview_background.pack(side="left", padx=(0, 12))
        ttk.Button(preview_row, text="−", width=3, command=self.zoom_out).pack(side="left")
        ttk.Button(preview_row, text="Ajustar", command=self.fit_to_screen).pack(side="left", padx=(3, 0))
        ttk.Button(preview_row, text="100 %", command=self.actual_size).pack(side="left", padx=(3, 0))
        ttk.Button(preview_row, text="+", width=3, command=self.zoom_in).pack(side="left", padx=(3, 0))
        tk.Label(preview_row, textvariable=self.zoom_label, background=COLORS.panel,
                 foreground=COLORS.muted, width=7, anchor="e").pack(side="left", padx=(5, 0))
        tk.Label(bar, textvariable=self.preview_legend, background=COLORS.panel,
                 foreground=COLORS.muted, font=(UI_FONT, 8), anchor="w").pack(fill="x", padx=12, pady=(0, 7))
        view = tk.Frame(self, background=COLORS.background)
        view.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.canvas = tk.Canvas(view, background="#111314", highlightthickness=1, highlightbackground=COLORS.border, cursor="crosshair")
        vertical = ttk.Scrollbar(view, orient="vertical", command=lambda *a, _fn=self.canvas.yview: _fn(*a))
        horizontal = ttk.Scrollbar(view, orient="horizontal", command=lambda *a, _fn=self.canvas.xview: _fn(*a))
        self.canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        view.grid_rowconfigure(0, weight=1)
        view.grid_columnconfigure(0, weight=1)
        self.canvas.bind("<Configure>", lambda _event: self.render())
        self.canvas.bind("<ButtonPress-1>", self.begin_stroke)
        self.canvas.bind("<B1-Motion>", self.continue_stroke)
        self.canvas.bind("<ButtonRelease-1>", self.end_stroke)
        self.canvas.bind("<Double-Button-1>", self.finish_polygon_lasso)
        self.canvas.bind("<Button-3>", self.remove_polygon_point)
        self.canvas.bind("<Control-MouseWheel>", self.zoom_with_wheel)
        self.canvas.bind("<MouseWheel>", lambda event: self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units"))
        self.canvas.bind("<Shift-MouseWheel>", lambda event: self.canvas.xview_scroll(-1 if event.delta > 0 else 1, "units"))
        self.bind("<Control-z>", self.undo)
        self.bind("<Control-Z>", self.undo)
        self.bind("<Control-y>", self.redo)
        self.bind("<Control-Shift-Z>", self.redo)
        self.bind("<KeyPress>", self._handle_shortcut, add="+")
        self.bind("<Return>", self.finish_polygon_lasso)
        self.bind("<BackSpace>", self.remove_polygon_point)
        self.bind("<Escape>", lambda _event: self.destroy())

        # Las acciones se separan de las herramientas para que no queden
        # truncadas cuando la ventana es angosta y el reprocesado sea evidente.
        footer = tk.Frame(self, background=COLORS.background)
        footer.pack(fill="x", padx=12, pady=(0, 12))
        tk.Label(footer, text="Los cambios se aplican sobre una copia y se reprocesan al confirmar.",
                 background=COLORS.background, foreground=COLORS.muted, font=(UI_FONT, 9)).pack(side="left")
        ttk.Button(footer, text="Cancelar", command=self.destroy,
                   style="Secondary.TButton").pack(side="right")
        ttk.Button(footer, text="Aplicar y reprocesar", command=self.save,
                   style="Primary.TButton").pack(side="right", padx=(0, 8))
        ttk.Button(footer, text="Deshacer", command=self.undo,
                   style="Secondary.TButton").pack(side="right", padx=(0, 8))
        ttk.Button(footer, text="Rehacer", command=self.redo,
                   style="Secondary.TButton").pack(side="right", padx=(0, 8))
        ttk.Button(footer, text="Restaurar al abrir", command=self.restore_opened_mask,
                   style="Secondary.TButton").pack(side="right", padx=(0, 8))

    def _refresh_brush_label(self, *_):
        self.brush_label.set(f"{int(float(self.brush.get()))} px")

    def choose_color(self):
        chosen = colorchooser.askcolor(self.brush_color, parent=self, title="Color del pincel")[1]
        if chosen:
            self.brush_color = chosen
            self.color_button.configure(background=chosen, activebackground=chosen)
            self.mode.set("paint")

    def _preview_options_changed(self, *_):
        self._update_preview_legend()
        self.request_render()

    def _update_preview_legend(self):
        self.preview_legend.set(self._VIEW_LEGENDS.get(self.preview_mode.get(), ""))

    def _fit_scale(self):
        width = max(100, self.canvas.winfo_width() - 20)
        height = max(100, self.canvas.winfo_height() - 20)
        return min(width / self.original.width, height / self.original.height, 1.0)

    def _canvas_point_to_image(self, canvas_x, canvas_y):
        x = (self.canvas.canvasx(canvas_x) - 10) / max(self.display_scale, .001)
        y = (self.canvas.canvasy(canvas_y) - 10) / max(self.display_scale, .001)
        if not (0 <= x < self.mask.width and 0 <= y < self.mask.height):
            return None
        return x, y

    def _set_zoom(self, zoom, event=None):
        if event is None:
            viewport_x = self.canvas.winfo_width() / 2
            viewport_y = self.canvas.winfo_height() / 2
        else:
            viewport_x, viewport_y = event.x, event.y
        anchor = self._canvas_point_to_image(viewport_x, viewport_y)
        self.zoom = min(6.0, max(0.35, zoom))
        self.render()
        if anchor is not None:
            self.after_idle(lambda: self._anchor_zoom(anchor, viewport_x, viewport_y))
        return "break"

    def _anchor_zoom(self, point, viewport_x, viewport_y):
        """Mantiene visible el punto que estaba bajo el cursor al cambiar el zoom."""
        if not self.winfo_exists():
            return
        region = self.canvas.bbox("all")
        if not region:
            return
        content_width = region[2] - region[0]
        content_height = region[3] - region[1]
        max_x = max(1, content_width - self.canvas.winfo_width())
        max_y = max(1, content_height - self.canvas.winfo_height())
        desired_x = 10 + point[0] * self.display_scale - viewport_x
        desired_y = 10 + point[1] * self.display_scale - viewport_y
        self.canvas.xview_moveto(min(1.0, max(0.0, desired_x / max_x)))
        self.canvas.yview_moveto(min(1.0, max(0.0, desired_y / max_y)))

    def zoom_in(self):
        return self._set_zoom(self.zoom * 1.18)

    def zoom_out(self):
        return self._set_zoom(self.zoom / 1.18)

    def fit_to_screen(self):
        return self._set_zoom(1.0)

    def actual_size(self):
        return self._set_zoom(1.0 / max(self._fit_scale(), .001))

    def zoom_with_wheel(self, event):
        factor = 1.18 if event.delta > 0 else 1 / 1.18
        return self._set_zoom(self.zoom * factor, event)

    def _apply_preview_background(self, image):
        """Compone una copia de la vista; nunca modifica el original ni la máscara."""
        if self.preview_background.get() == "Cuadriculado":
            return make_checkerboard_preview(image)
        if self.preview_background.get() == "Blanco":
            return make_white_background_preview(image)
        return make_black_background_preview(image)

    def _build_preview_image(self, image, mask):
        """Construye la vista elegida a partir de las copias ya escaladas."""
        from PIL import Image, ImageChops, ImageOps

        mode = self.preview_mode.get()
        if mode == "Máscara":
            return mask.convert("RGB")
        if mode == "Original":
            return self._apply_preview_background(image)

        retained = image.copy()
        retained.putalpha(mask)
        if mode == "Recorte":
            return self._apply_preview_background(retained)

        # Superposición: lo retenido se marca en verde y lo que se quitó del
        # original se marca en rojo. Las zonas transparentes originales no se
        # tiñen, para no confundir el fondo real con un borrado manual.
        preview = self._apply_preview_background(image).convert("RGBA")
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        overlay.paste((34, 184, 91, 78), mask=mask)
        removed = ImageChops.multiply(ImageOps.invert(mask), image.getchannel("A"))
        overlay.paste((220, 66, 66, 145), mask=removed)
        preview.alpha_composite(overlay)
        return preview.convert("RGB")

    def render(self):
        from PIL import Image, ImageTk

        fit_scale = self._fit_scale()
        self.display_scale = fit_scale * self.zoom
        size = (max(1, round(self.original.width * self.display_scale)), max(1, round(self.original.height * self.display_scale)))
        image = self.original.resize(size, Image.Resampling.LANCZOS)
        mask = self.mask.resize(size, Image.Resampling.NEAREST)
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        preview = self._build_preview_image(image, mask)
        self.photo = ImageTk.PhotoImage(preview)
        self.zoom_label.set(f"{round(self.display_scale * 100)} %")
        self.canvas.delete("all")
        self.canvas.create_image(10, 10, anchor="nw", image=self.photo)
        if len(self._lasso_points) > 1:
            lasso_preview = [
                coordinate
                for point in self._lasso_points
                for coordinate in (10 + point[0] * self.display_scale, 10 + point[1] * self.display_scale)
            ]
            self.canvas.create_line(*lasso_preview, fill=COLORS.wine_active, width=2, dash=(4, 3))
            if self.mode.get() == "polygon_lasso":
                for x, y in self._lasso_points:
                    px, py = 10 + x * self.display_scale, 10 + y * self.display_scale
                    self.canvas.create_oval(px - 3, py - 3, px + 3, py + 3, fill=COLORS.wine_active, outline="")
        self.canvas.create_text(
            18,
            size[1] + 28,
            anchor="sw",
            fill=COLORS.muted,
            text="E quitar · R recuperar · B pincel · L/P lazo · I cuentagotas · Ctrl+Z deshacer · Ctrl+rueda: zoom",
        )
        self.canvas.configure(scrollregion=(0, 0, size[0] + 30, size[1] + 45))

    def request_render(self, delay_ms: int = 16):
        """Limita la vista del pincel/lazo a un repintado por cuadro."""
        if self._render_after is None:
            self._render_after = self.after(delay_ms, self._flush_render)

    def _flush_render(self):
        self._render_after = None
        if self.winfo_exists():
            self.render()

    def image_point(self, event):
        """Convierte la posición visible en un punto de la imagen original."""
        return self._canvas_point_to_image(event.x, event.y)

    def _handle_shortcut(self, event):
        """Atajos de herramientas, sin interceptar texto de los combos."""
        widget = event.widget
        if isinstance(widget, (tk.Entry, ttk.Combobox)):
            return None
        # Dejar que los atajos con modificadores existentes sigan su propio
        # flujo; en particular no convertir Ctrl+Z en una herramienta.
        if event.state & 0x0004:
            return None
        key = event.keysym.lower()
        modes = {
            "e": "erase",
            "r": "restore",
            "b": "paint",
            "l": "lasso",
            "p": "polygon_lasso",
            "i": "eyedropper",
        }
        if key in modes:
            self.mode.set(modes[key])
            return "break"
        if key in {"plus", "kp_add"}:
            return self.zoom_in()
        if key in {"minus", "kp_subtract"}:
            return self.zoom_out()
        if key in {"0", "kp_0"}:
            return self.fit_to_screen()
        return None

    def begin_stroke(self, event):
        point = self.image_point(event)
        if point is None:
            return
        if self.mode.get() == "lasso":
            self._lasso_points = [point]
            self._active_stroke = None
            return
        if self.mode.get() == "polygon_lasso":
            if not self._lasso_points or math.dist(point, self._lasso_points[-1]) > 1:
                self._lasso_points.append(point)
            self._active_stroke = None
            self.render()
            return
        if self.mode.get() == "eyedropper":
            red, green, blue, _alpha = self.original.getpixel((int(point[0]), int(point[1])))
            self.brush_color = f"#{red:02x}{green:02x}{blue:02x}"
            self.color_button.configure(background=self.brush_color, activebackground=self.brush_color)
            self.mode.set("paint")
            return
        self._active_stroke = {
            "patches": [],
            "image_modified_before": self.image_modified,
        }
        self.paint_at(*point)

    def continue_stroke(self, event):
        if self.mode.get() == "lasso" and self._lasso_points:
            point = self.image_point(event)
            if point is not None:
                self._lasso_points.append(point)
                self.request_render()
            return
        if self._active_stroke is None:
            return
        point = self.image_point(event)
        if point is not None:
            self.paint_at(*point)

    def end_stroke(self, _event=None):
        if self.mode.get() == "lasso" and self._lasso_points:
            self._apply_lasso()
            return
        if self._active_stroke is None:
            return
        if self._active_stroke["patches"]:
            self._redo_stack = []
            self._undo_stack.append(self._active_stroke)
            # Un historial acotado evita cargar en memoria imágenes completas.
            del self._undo_stack[:-30]
        self._active_stroke = None

    def finish_polygon_lasso(self, event=None):
        """Cierra el lazo de vértices y aplica la acción elegida sobre la máscara."""
        if self.mode.get() != "polygon_lasso":
            return
        point = self.image_point(event) if event is not None else None
        if point and (not self._lasso_points or math.dist(point, self._lasso_points[-1]) > 1):
            self._lasso_points.append(point)
        self._apply_lasso()
        return "break"

    def remove_polygon_point(self, _event=None):
        """Permite corregir el último vértice antes de cerrar el polígono."""
        if self.mode.get() != "polygon_lasso" or not self._lasso_points:
            return
        self._lasso_points.pop()
        self.render()
        return "break"

    def _apply_lasso(self):
        """Cierra el lazo y actualiza la máscara dentro del área delimitada."""
        from PIL import ImageDraw

        points = self._lasso_points
        self._lasso_points = []
        if len(points) < 3:
            self.render()
            return
        left = max(0, math.floor(min(x for x, _y in points) - 2))
        top = max(0, math.floor(min(y for _x, y in points) - 2))
        right = min(self.mask.width, math.ceil(max(x for x, _y in points) + 2))
        bottom = min(self.mask.height, math.ceil(max(y for _x, y in points) + 2))
        if right <= left or bottom <= top:
            self.render()
            return
        self._redo_stack = []
        self._undo_stack.append({
            "patches": [{
                "box": (left, top, right, bottom),
                "original": self.original.crop((left, top, right, bottom)),
                "mask": self.mask.crop((left, top, right, bottom)),
            }],
            "image_modified_before": self.image_modified,
        })
        del self._undo_stack[:-30]
        ImageDraw.Draw(self.mask).polygon(
            points, fill=0 if self.lasso_action.get() == "Quitar" else 255,
        )
        self.render()

    def paint_at(self, x, y):
        from PIL import ImageDraw

        radius = max(1, int(self.brush.get() / max(self.display_scale, .001) / 2))
        box = (
            max(0, math.floor(x - radius - 2)),
            max(0, math.floor(y - radius - 2)),
            min(self.mask.width, math.ceil(x + radius + 2)),
            min(self.mask.height, math.ceil(y + radius + 2)),
        )
        if self._active_stroke is not None and box[2] > box[0] and box[3] > box[1]:
            self._active_stroke["patches"].append({
                "box": box,
                "original": self.original.crop(box),
                "mask": self.mask.crop(box),
            })
        if self.mode.get() == "paint":
            ImageDraw.Draw(self.original).ellipse(
                (x - radius, y - radius, x + radius, y + radius),
                fill=self.brush_color,
            )
            ImageDraw.Draw(self.mask).ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
            self.image_modified = True
        else:
            fill = 0 if self.mode.get() == "erase" else 255
            ImageDraw.Draw(self.mask).ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
        self.request_render(delay_ms=24)

    def restore_opened_mask(self, _event=None, *, confirm=True):
        """Restaura la máscara que estaba cargada al abrir este editor.

        Esto no toca la imagen pintada manualmente: "Pincel" modifica el arte
        original de trabajo y por eso se conserva de forma explícita.
        """
        self.end_stroke()
        if self.mask.tobytes() == self._opened_mask.tobytes():
            return "break"
        if confirm and not messagebox.askyesno(
            "Restaurar máscara",
            "Se descartarán los cambios de máscara de esta sesión. "
            "Los trazos de color del pincel se conservarán.",
            parent=self,
        ):
            return "break"
        self.mask = self._opened_mask.copy()
        self._undo_stack.clear()
        self._redo_stack = []
        self._active_stroke = None
        self._lasso_points = []
        if self._render_after:
            self.after_cancel(self._render_after)
            self._render_after = None
        self.render()
        return "break"

    def undo(self, _event=None):
        """Revierte de una vez la última pincelada, recuperación o borrado."""
        self.end_stroke()
        if not self._undo_stack:
            return "break"
        stroke = self._undo_stack.pop()
        inverse = {"patches": [], "image_modified_before": self.image_modified}
        for patch in reversed(stroke["patches"]):
            inverse["patches"].append({
                "box": patch["box"],
                "original": self.original.crop(patch["box"]),
                "mask": self.mask.crop(patch["box"]),
            })
            left, top, _right, _bottom = patch["box"]
            self.original.paste(patch["original"], (left, top))
            self.mask.paste(patch["mask"], (left, top))
        self.image_modified = stroke["image_modified_before"]
        if not hasattr(self, "_redo_stack"):
            self._redo_stack = []
        self._redo_stack.append(inverse)
        if self._render_after:
            self.after_cancel(self._render_after)
            self._render_after = None
        self.render()
        return "break"

    def redo(self, _event=None):
        self.end_stroke()
        if not getattr(self, "_redo_stack", []):
            return "break"
        stroke = self._redo_stack.pop()
        inverse = {"patches": [], "image_modified_before": self.image_modified}
        for patch in reversed(stroke["patches"]):
            inverse["patches"].append({
                "box": patch["box"], "original": self.original.crop(patch["box"]),
                "mask": self.mask.crop(patch["box"]),
            })
            self.original.paste(patch["original"], patch["box"][:2])
            self.mask.paste(patch["mask"], patch["box"][:2])
        self.image_modified = stroke["image_modified_before"]
        self._undo_stack.append(inverse)
        self.render()
        return "break"

    def save(self):
        # Asegurar que la máscara esté en modo L y se guarde correctamente
        if self.mask.mode != "L":
            self.mask = self.mask.convert("L")
        # La automática permanece disponible para comparar/restablecer.
        filename = "cut_manual.png" if getattr(self, "editing_target", "mask") == "cut" else "mask_manual.png"
        self.mask_path = self.mask_path.with_name(filename)
        self.mask.save(self.mask_path, dpi=(300, 300), optimize=False)
        edited_path = ""
        if self.image_modified:
            edited = self.mask_path.with_name("edicion_manual.png")
            # Asegurar que la imagen editada esté en modo RGBA con canal alfa correcto
            if self.original.mode != "RGBA":
                self.original = self.original.convert("RGBA")
            self.original.save(edited, dpi=(300, 300), optimize=False)
            edited_path = str(edited)
        self.on_saved(str(self.mask_path), edited_path)
        self.destroy()


class StickerStudio(tk.Toplevel):
    def __init__(self, master, database, refresh_callback=None, semantic_analyzer=None,
                 target_order_id=None, nominal_size_cm=None):
        super().__init__(master)
        self.database = database
        self.refresh_callback = refresh_callback or (lambda: None)
        self.semantic_analyzer = semantic_analyzer
        self.target_order_id = target_order_id  # ID del pedido al que se vincularán los stickers aprobados
        self.nominal_size_cm = nominal_size_cm
        self.title("Creador de stickers")
        # El creador también puede abrirse desde accesos directos o pruebas
        # aisladas: instala el tema aquí para no depender de la ventana padre.
        apply_ttk_theme(self)
        _fit_window_to_screen(self, 1240, 790, 980, 650, width_ratio=0.96, height_ratio=0.88)
        self.configure(background=COLORS.background)
        self.profile = ProcessingProfile(nominal_size_cm=nominal_size_cm)
        workspace = Path(__file__).parents[2] / "work" / "stickers"
        self.processor = StickerProcessor(workspace, self.profile)
        self.inbox = workspace / "inbox"
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.jobs: list[dict] = []
        self.current_index: int | None = None
        self.worker: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.preview_images = []
        self._candidate_jobs: set[int] = set()
        self.empty_requested = False
        self._paste_worker: threading.Thread | None = None
        self._folder_worker: threading.Thread | None = None
        self._note_mode = False  # Estado para modo nota (solo cola)
        self._header_frame = None  # Referencia al header para ocultar/mostrar
        self._status_strip = None  # Referencia al status strip para ocultar/mostrar
        self._note_mode_back_btn = None  # Botón para volver al modo completo
        self._order_info_label = None  # Label para mostrar info del pedido vinculado
        self._build()
        self._load_saved_jobs()
        self.bind("<Control-v>", lambda _event: (self.paste_image(), "break")[1])
        self.bind("<Control-V>", lambda _event: (self.paste_image(), "break")[1])
        self.bind("<Control-r>", lambda _event: (self.reprocess_current(), "break")[1])
        self.bind("<Control-R>", lambda _event: (self.reprocess_current(), "break")[1])
        self.protocol("WM_DELETE_WINDOW", self.close)


    def _build(self):
        self._header_frame = tk.Frame(self, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        self._header_frame.pack(fill="x", padx=14, pady=(14, 8))
        header = self._header_frame
        title = tk.Frame(header, background=COLORS.panel)
        title.pack(side="left", padx=16, pady=12)
        tk.Label(title, text="CREADOR DE STICKERS", background=COLORS.panel, foreground=COLORS.text,
                 font=(IDENTITY_FONT, 18, "bold")).pack(anchor="w")
        
        # Mostrar información del pedido vinculado si existe
        subtitle_text = "Procesamiento genérico legacy (maestro 5,70 cm; sin nominal comercial)."
        if self.target_order_id is not None:
            try:
                order = self.database.order(self.target_order_id)
                client_name = order.get("client") or f"Pedido #{self.target_order_id}"
                if self.nominal_size_cm is not None:
                    subtitle_text = (f"🎯 Vinculado a: {client_name} · Nominal: "
                                     f"{self.nominal_size_cm:.2f} cm · asset preparado al máximo productivo.")
                else:
                    subtitle_text = (f"🎯 Vinculado a: {client_name} · Sin tamaño nominal único: "
                                     "el procesamiento queda en modo legacy y no se vincula automáticamente.")
            except Exception:
                subtitle_text = f"🎯 Vinculado a pedido #{self.target_order_id} · Los stickers aprobados se guardarán automáticamente."
        
        self._order_info_label = tk.Label(title, text=subtitle_text, background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 9))
        self._order_info_label.pack(anchor="w")
        
        actions = tk.Frame(header, background=COLORS.panel)
        actions.pack(side="right", padx=12, pady=8)
        # Fila superior: agregar archivos + perfil + modo nota
        row1 = tk.Frame(actions, background=COLORS.panel)
        row1.pack(anchor="e")
        for text, command, style in (
            ("Pegar", self.paste_image, "Secondary.TButton"),
            ("Elegir archivos", self.choose_files, "Secondary.TButton"),
            ("Importar carpeta", self.choose_folder, "Secondary.TButton"),
            ("Perfil", self.open_profile_editor, "Secondary.TButton"),
            ("📝 Modo Nota", self.toggle_note_mode, "Secondary.TButton"),
        ):
            ttk.Button(row1, text=text, command=command, style=style).pack(side="left", padx=3, pady=(0, 3))
        # Fila inferior: acciones de cola
        row2 = tk.Frame(actions, background=COLORS.panel)
        row2.pack(anchor="e")
        for text, command, style in (
            ("Procesar cola", self.process_queue, "Primary.TButton"),
            ("Cancelar", self.cancel_processing, "Danger.TButton"),
            ("Vaciar creador", self.empty_studio, "Danger.TButton"),
        ):
            ttk.Button(row2, text=text, command=command, style=style).pack(side="left", padx=3)

        self.progress_value = tk.DoubleVar(value=0)
        self._status_strip = tk.Frame(self, background=COLORS.panel_elevated)
        self._status_strip.pack(fill="x", padx=14, pady=(0, 8))
        status_strip = self._status_strip
        self.status = tk.StringVar(value="Agregá imágenes para comenzar.")
        tk.Label(status_strip, textvariable=self.status, background=COLORS.panel_elevated, foreground=COLORS.text,
                 font=(UI_FONT, 9), anchor="w").pack(side="left", fill="x", expand=True, padx=12, pady=7)
        # Estilo local: gris neutro para no confundir con errores (tema usa rojo)
        _pb_style = ttk.Style(self)
        _pb_style.configure(
            "Studio.Horizontal.TProgressbar",
            background="#4a4a4a",
            troughcolor=COLORS.panel_elevated,
            bordercolor=COLORS.border,
        )
        pb = ttk.Progressbar(
            status_strip, variable=self.progress_value,
            maximum=100, length=260,
            style="Studio.Horizontal.TProgressbar",
        )
        pb.pack(side="right", padx=12)

        body = tk.PanedWindow(self, orient="horizontal", sashwidth=7, background=COLORS.background, borderwidth=0)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.queue_panel = tk.Frame(body, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        self.review_panel = tk.Frame(body, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        self.main_body = body  # Guardar referencia para ocultar/mostrar
        body.add(self.queue_panel, minsize=400, width=465)
        body.add(self.review_panel, minsize=550)

        queue_heading = tk.Frame(self.queue_panel, background=COLORS.panel)
        queue_heading.pack(fill="x", padx=12, pady=(12, 7))
        tk.Label(queue_heading, text="COLA DE PROCESAMIENTO", background=COLORS.panel, foreground=COLORS.wine_active,
                 font=(IDENTITY_FONT, 12, "bold")).pack(side="left")
        self.queue_summary = tk.StringVar(value="Sin archivos")
        tk.Label(queue_heading, textvariable=self.queue_summary, background=COLORS.panel,
                 foreground=COLORS.muted, font=(UI_FONT, 9)).pack(side="right")
        columns = ("archivo", "estado", "motor", "calidad")
        self.queue = ttk.Treeview(self.queue_panel, columns=columns, show="headings", selectmode="extended")
        for column, label, width in (("archivo", "Archivo", 175), ("estado", "Estado", 105), ("motor", "Motor", 75), ("calidad", "Calidad", 80)):
            self.queue.heading(column, text=label)
            self.queue.column(column, width=width, anchor="w")
        scrollbar = ttk.Scrollbar(self.queue_panel, orient="vertical", command=lambda *a, _fn=self.queue.yview: _fn(*a))
        self.queue.configure(yscrollcommand=scrollbar.set)
        self.queue.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 10))
        scrollbar.pack(side="right", fill="y", padx=(0, 10), pady=(0, 10))
        self.queue.bind("<<TreeviewSelect>>", self.select_job)
        self.queue.bind("<Double-Button-1>", self.open_decision_dialog)
        self.queue.bind("<Button-3>", self._show_queue_context_menu)
        self.queue.bind("<Delete>", self._delete_selected_job)
        self.queue.bind("<BackSpace>", self._delete_selected_job)

        review_header = tk.Frame(self.review_panel, background=COLORS.panel)
        review_header.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(review_header, text="STICKER FINAL", background=COLORS.panel, foreground=COLORS.wine_active,
                 font=(IDENTITY_FONT, 12, "bold")).pack(side="left")
        self.review_state = tk.StringVar(value="Sin selección")
        tk.Label(review_header, textvariable=self.review_state, background=COLORS.panel, foreground=COLORS.muted,
                 font=(UI_FONT, 9)).pack(side="right")

        # Canvas con scrollbar para el contenido del panel de revisión
        review_canvas_container = tk.Frame(self.review_panel, background=COLORS.panel)
        review_canvas_container.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        
        self._review_canvas = tk.Canvas(review_canvas_container, background=COLORS.panel, highlightthickness=0)
        review_scrollbar = ttk.Scrollbar(review_canvas_container, orient="vertical", command=self._review_canvas.yview)
        self._review_canvas.configure(yscrollcommand=review_scrollbar.set)
        
        self._review_canvas.pack(side="left", fill="both", expand=True)
        review_scrollbar.pack(side="right", fill="y")
        
        review_content_frame = tk.Frame(self._review_canvas, background=COLORS.panel)
        self._review_canvas.create_window(0, 0, window=review_content_frame, anchor="nw")
        review_content_frame.bind("<Configure>", lambda e: self._review_canvas.configure(scrollregion=self._review_canvas.bbox("all")))
        
        # Bind mousewheel directly to canvas and all children to ensure events are captured
        self._review_canvas.bind("<MouseWheel>", self._on_studio_mousewheel)
        self._review_canvas.bind("<Button-4>", self._on_studio_mousewheel_linux)
        self._review_canvas.bind("<Button-5>", self._on_studio_mousewheel_linux)
        
        # Recursively bind to all children
        def bind_review_mousewheel(widget):
            widget.bind("<MouseWheel>", self._on_studio_mousewheel, add="+")
            widget.bind("<Button-4>", self._on_studio_mousewheel_linux, add="+")
            widget.bind("<Button-5>", self._on_studio_mousewheel_linux, add="+")
            for child in widget.winfo_children():
                bind_review_mousewheel(child)
        
        self.after_idle(lambda: bind_review_mousewheel(review_content_frame))

        final_card = tk.Frame(review_content_frame, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
        final_card.pack(fill="both", expand=True, padx=12)

        preview_header_bar = tk.Frame(final_card, background=COLORS.panel_elevated)
        preview_header_bar.pack(fill="x", padx=12, pady=(9, 5))

        tk.Label(preview_header_bar, text="VISTA EXACTA DEL PNG QUE SE VA A GUARDAR", background=COLORS.panel_elevated,
                 foreground=COLORS.muted, font=(IDENTITY_FONT, 9, "bold")).pack(side="left")

        self.view_mode = tk.StringVar(value="Resultado final")
        self.background_mode = tk.StringVar(value="Cuadriculado")
        mode_cb = ttk.Combobox(preview_header_bar, textvariable=self.view_mode,
                               values=("Resultado final", "Máscara cruda", "Original", "Superposición", "Contorno de corte"),
                               state="readonly", width=16)
        mode_cb.pack(side="right")
        mode_cb.bind("<<ComboboxSelected>>", lambda _: self.render_current())
        
        background_cb = ttk.Combobox(preview_header_bar, textvariable=self.background_mode,
                                     values=("Cuadriculado", "Blanco", "Negro"),
                                     state="readonly", width=12)
        background_cb.pack(side="right", padx=(0, 8))
        background_cb.bind("<<ComboboxSelected>>", lambda _: self.render_current())

        self.final_preview = tk.Canvas(final_card, background="#111314", highlightthickness=0, width=570, height=440)
        self.final_preview.pack(fill="both", expand=True, padx=9, pady=(0, 9))
        self.final_preview.bind("<Double-Button-1>", self.open_decision_dialog)
        self.final_preview.configure(cursor="hand2")
        
        # Label explaining transparency visualization
        self.transparency_label = tk.Label(final_card, text="Fondo cuadriculado = transparencia",
                                          background=COLORS.panel_elevated, foreground=COLORS.muted,
                                          font=(UI_FONT, 8))
        self.transparency_label.pack(pady=(0, 6))
        
        # White brush mode variables
        self.brush_mode = tk.BooleanVar(value=False)
        self.brush_size = tk.IntVar(value=10)
        self.brush_drawing = False
        self.brush_last_x = None
        self.brush_last_y = None
        self._brush_points: list[tuple[int, int]] = []
        self._preview_display_size: tuple[int, int] = (0, 0)
        self._preview_offset: tuple[int, int] = (0, 0)

        # Panel de análisis de calidad
        reasons_card = tk.Frame(review_content_frame, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
        reasons_card.pack(fill="x", padx=12, pady=(0, 10))
        
        tk.Label(reasons_card, text="ANÁLISIS DE CALIDAD", background=COLORS.panel_elevated,
                 foreground=COLORS.wine_active, font=(IDENTITY_FONT, 10, "bold")).pack(anchor="w", padx=12, pady=(8, 4))
        
        self.reasons_content = tk.Label(reasons_card, text="Seleccioná un sticker de la cola para ver el análisis.",
                                        background=COLORS.panel_elevated, foreground=COLORS.text,
                                        justify="left", anchor="nw", wraplength=680, font=(UI_FONT, 9))
        self.reasons_content.pack(fill="x", padx=12, pady=(0, 8))

        controls = tk.Frame(review_content_frame, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
        controls.pack(fill="x", padx=12, pady=10)
        self.category = tk.StringVar()
        self.tags = tk.StringVar()
        self.processing_mode = tk.StringVar(value="Automático")
        # Estos controles expresan la intención del usuario. El tratamiento
        # del fondo de la fila siguiente continúa siendo independiente.
        self.creation_mode = tk.StringVar(value="Sticker de silueta")
        self.full_image_shape = tk.StringVar(value="Rectangular")
        self.visual_classification = tk.StringVar(value="Automática")
        self.selected_components = tk.StringVar(value="")
        self.cut_inset = tk.DoubleVar(value=self.profile.cut_inset_mm)
        fields = tk.Frame(controls, background=COLORS.panel_elevated)
        fields.pack(fill="x", padx=10, pady=9)
        for column, label in enumerate(("Categoría", "Etiquetas separadas por coma", "Corte hacia adentro (mm)")):
            tk.Label(fields, text=label, background=COLORS.panel_elevated, foreground=COLORS.text,
                     font=(UI_FONT, 9, "bold")).grid(row=0, column=column, sticky="w", padx=4)
        categories = [name for name, _count in self.database.category_counts()]
        ttk.Combobox(fields, textvariable=self.category, values=categories, state="normal").grid(row=1, column=0, sticky="ew", padx=4, pady=(3, 0))
        ttk.Entry(fields, textvariable=self.tags).grid(row=1, column=1, sticky="ew", padx=4, pady=(3, 0))
        ttk.Spinbox(fields, textvariable=self.cut_inset, from_=0, to=3, increment=.25, width=8).grid(row=1, column=2, sticky="ew", padx=4, pady=(3, 0))
        fields.grid_columnconfigure(0, weight=1)
        fields.grid_columnconfigure(1, weight=2)

        mode_row = tk.Frame(controls, background=COLORS.panel_elevated)
        mode_row.pack(fill="x", padx=14, pady=(0, 8))
        tk.Label(mode_row, text="Tratamiento del fondo", background=COLORS.panel_elevated,
                 foreground=COLORS.text, font=(UI_FONT, 9, "bold")).pack(side="left", padx=(0, 8))
        ttk.Combobox(
            mode_row, textvariable=self.processing_mode, state="readonly", width=23,
            values=("Automático", "Fondo uniforme", "Foto / sujeto", "Sticker existente"),
        ).pack(side="left")
        tk.Label(mode_row, text="Se aplica al reprocesar.",
                 background=COLORS.panel_elevated, foreground=COLORS.muted,
                 font=(UI_FONT, 8)).pack(side="left", padx=8)

        creation_row = tk.Frame(controls, background=COLORS.panel_elevated)
        creation_row.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(creation_row, text="Modo de creación", background=COLORS.panel_elevated,
                 foreground=COLORS.text, font=(UI_FONT, 9, "bold")).pack(side="left", padx=(0, 8))
        ttk.Combobox(
            creation_row, textvariable=self.creation_mode, state="readonly", width=27,
            values=("Sticker de silueta", "Sticker de imagen completa", "Sticker de múltiples objetos"),
        ).pack(side="left")
        tk.Label(creation_row, text="Forma completa", background=COLORS.panel_elevated,
                 foreground=COLORS.text, font=(UI_FONT, 9, "bold")).pack(side="left", padx=(14, 6))
        ttk.Combobox(
            creation_row, textvariable=self.full_image_shape, state="readonly", width=14,
            values=("Rectangular", "Circular", "Ovalado", "Personalizado"),
        ).pack(side="left")

        visual_row = tk.Frame(controls, background=COLORS.panel_elevated)
        visual_row.pack(fill="x", padx=14, pady=(0, 8))
        tk.Label(visual_row, text="Clasificación visual", background=COLORS.panel_elevated,
                 foreground=COLORS.text, font=(UI_FONT, 9, "bold")).pack(side="left", padx=(0, 8))
        ttk.Combobox(
            visual_row, textvariable=self.visual_classification, state="readonly", width=40,
            values=("Automática", *(label for _identifier, label in VISUAL_STICKER_TYPES)),
        ).pack(side="left")
        tk.Label(visual_row, text="Objetos (IDs)", background=COLORS.panel_elevated,
                 foreground=COLORS.text, font=(UI_FONT, 9, "bold")).pack(side="left", padx=(14, 6))
        ttk.Entry(visual_row, textvariable=self.selected_components, width=11).pack(side="left")
        tk.Label(visual_row, text="Ej.: 1, 3 · vacío = todos",
                 background=COLORS.panel_elevated, foreground=COLORS.muted,
                 font=(UI_FONT, 8)).pack(side="left", padx=7)
        self.notes = tk.StringVar(value="")
        tk.Label(controls, textvariable=self.notes, background=COLORS.panel_elevated, foreground=COLORS.muted,
                 justify="left", anchor="w", wraplength=700, font=(UI_FONT, 9)).pack(fill="x", padx=14, pady=(0, 8))
        buttons = tk.Frame(controls, background=COLORS.panel_elevated)
        buttons.pack(fill="x", padx=10, pady=(0, 10))
        self.review_buttons = {}
        for text, command, style in (
            ("Reprocesar", self.reprocess_current, "Secondary.TButton"),
            ("Seleccionar área", self.open_area_selection, "Secondary.TButton"),
            ("Proteger zonas", self.open_protection_editor, "Secondary.TButton"),
            ("Corregir silueta", self.open_mask, "Secondary.TButton"),
            ("Alternativa anterior", self.restore_previous_result, "Secondary.TButton"),
            ("Separar objetos", self.create_individual_objects, "Secondary.TButton"),
            ("Corregir corte", self.open_cut_editor, "Secondary.TButton"),
            ("Probar alternativa", self.try_mask_alternative, "Secondary.TButton"),
        ):
            button = ttk.Button(buttons, text=text, command=command, style=style)
            index = len(self.review_buttons)
            button.grid(row=index // 4, column=index % 4, padx=3, pady=3, sticky="ew")
            self.review_buttons[text] = button
        
        # White brush controls
        brush_controls = tk.Frame(controls, background=COLORS.panel_elevated)
        brush_controls.pack(fill="x", padx=10, pady=(0, 10))
        
        tk.Checkbutton(brush_controls, text="Pincel blanco (guarda en PNG)", variable=self.brush_mode,
                      command=self.toggle_brush_mode, background=COLORS.panel_elevated,
                      foreground=COLORS.text, selectcolor=COLORS.panel_elevated).pack(side="left", padx=3)
        
        tk.Label(brush_controls, text="Tamaño:", background=COLORS.panel_elevated, 
                 foreground=COLORS.text, font=(UI_FONT, 9)).pack(side="left", padx=(10, 3))
        
        ttk.Scale(brush_controls, from_=1, to=50, variable=self.brush_size, 
                  orient="horizontal", length=100).pack(side="left", padx=3)

        review_actions = tk.Frame(controls, background=COLORS.panel_elevated)
        review_actions.pack(fill="x", padx=10, pady=(0, 10))
        self.reject_button = ttk.Button(
            review_actions, text="Rechazar", command=self.discard_current,
            style="Danger.TButton",
        )
        self.reject_button.pack(side="left", padx=3)
        self.approve_button = ttk.Button(
            review_actions, text="Enviar a Últimos Procesados", command=self.approve_current,
            style="Primary.TButton",
        )
        self.approve_button.pack(side="right", padx=3)
        self._update_review_actions()
        self._register_drop()
        self._bind_studio_mousewheel()

    def _register_drop(self):
        try:
            from tkinterdnd2 import DND_FILES
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self.drop_files)
        except (ImportError, AttributeError, OSError, PermissionError, Exception):
            # Drag & drop es opcional - si falla, el usuario puede usar los botones
            pass

    def drop_files(self, event):
        paths = [Path(value) for value in self.tk.splitlist(event.data)]
        self.add_paths(paths)

    def choose_files(self):
        paths = filedialog.askopenfilenames(
            parent=self,
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff")],
        )
        if not paths:
            return
        self.add_paths([Path(path) for path in paths])

    def choose_folder(self):
        """Pide la carpeta en el hilo principal y escanea en segundo plano."""
        folder = filedialog.askdirectory(parent=self)
        if not folder:
            return
        folder_path = Path(folder)
        # Si ya hay un escaneo corriendo para esta carpeta, ignorar.
        if self._folder_worker and self._folder_worker.is_alive():
            self.status.set("Esperando el escaneo anterior…")
            return
        self.status.set(f"Buscando imágenes en {folder_path.name}…")

        def scan():
            found = [
                path for path in folder_path.rglob("*")
                if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
            ]
            self.after(0, lambda: self.add_paths(found))

        self._folder_worker = threading.Thread(target=scan, daemon=True)
        self._folder_worker.start()

    def _prompt_area_selection_for_recent(self):
        if self.current_index is None or self.current_index >= len(self.jobs):
            return
        job = self.current_job()
        if not job:
            return
        self.open_area_selection()

    def _should_prompt_selection(self, path: Path) -> bool:
        try:
            from collections import deque
            from PIL import Image

            with Image.open(path) as source:
                image = source.convert("RGB")
                w, h = image.size
                if min(w, h) < 80:
                    return False
                if abs(w - h) / max(w, h) <= 0.12:
                    return True
                thumb = image.resize((128, 128), Image.Resampling.LANCZOS)
                pixels = thumb.load()

                edge_colors = []
                for x in range(0, 128, 16):
                    edge_colors.append(pixels[x, 0])
                    edge_colors.append(pixels[x, 127])
                for y in range(16, 112, 16):
                    edge_colors.append(pixels[0, y])
                    edge_colors.append(pixels[127, y])

                base = tuple(
                    int(sum(c[i] for c in edge_colors) / len(edge_colors))
                    for i in range(3)
                )
                tol = 28

                def similar(color1, color2):
                    return max(abs(color1[i] - color2[i]) for i in range(3)) <= tol

                visited = [[False] * 128 for _ in range(128)]
                queue = deque()
                for x in range(128):
                    for y in (0, 127):
                        if similar(pixels[x, y], base):
                            visited[y][x] = True
                            queue.append((x, y))
                for y in range(1, 127):
                    for x in (0, 127):
                        if similar(pixels[x, y], base):
                            visited[y][x] = True
                            queue.append((x, y))

                neighbors = ((1, 0), (-1, 0), (0, 1), (0, -1),
                             (1, 1), (1, -1), (-1, 1), (-1, -1))
                while queue:
                    cx, cy = queue.popleft()
                    for dx, dy in neighbors:
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < 128 and 0 <= ny < 128 and not visited[ny][nx]:
                            if similar(pixels[nx, ny], base):
                                visited[ny][nx] = True
                                queue.append((nx, ny))

                border_fraction = sum(sum(row) for row in visited) / (128.0 * 128.0)
                if border_fraction >= 0.28:
                    return True

                if w >= h and w / h >= 1.8:
                    return True
                if h >= w and h / w >= 1.8:
                    return True
        except Exception:
            return False
        return False

    def paste_image(self):
        """Lee el portapapeles en segundo plano para no congelar la UI."""
        if self._paste_worker and self._paste_worker.is_alive():
            return  # ya hay un paste en vuelo
        self.status.set("Leyendo portapapeles…")

        def _read():
            try:
                from PIL import Image, ImageGrab

                clipboard = ImageGrab.grabclipboard()
                if isinstance(clipboard, list):
                    valid = [Path(p) for p in clipboard if Path(p).suffix.lower() in IMAGE_EXTENSIONS]
                    self.after(0, lambda: self.add_paths(valid))
                    return
                if isinstance(clipboard, Image.Image):
                    path = self.inbox / f"pegado_{time.strftime('%Y%m%d_%H%M%S')}.png"
                    clipboard.convert("RGBA").save(path)
                    # Agregar directamente a la cola sin selección de área
                    # La selección de área está disponible como botón en el panel de modificación
                    self.after(0, lambda p=path: self.add_paths([p]))
                    return
                self.after(0, lambda: (
                    self.status.set("Portapapeles vacío. Copiá una imagen o archivo e intentá de nuevo."),
                ))
            except Exception as error:
                self.after(0, lambda e=error: messagebox.showerror("No se pudo pegar", str(e), parent=self))

        self._paste_worker = threading.Thread(target=_read, daemon=True)
        self._paste_worker.start()

    def add_paths(self, paths, run_queue: bool = True):
        """Agrega archivos nuevos en un solo batch y actualiza la UI una sola vez."""
        if not paths:
            return
        known = {job["source_path"] for job in self.jobs}
        first_new_index = len(self.jobs)
        added = 0
        rejected = []
        for path in paths:
            path = Path(path)
            if not path.is_file():
                rejected.append((path.name or str(path), "El archivo no existe o no se puede leer."))
                continue
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                rejected.append((path.name, "El formato no está habilitado para el creador de stickers."))
                continue
            try:
                StickerProcessor.validate_source(path)
            except ValueError as error:
                rejected.append((path.name, str(error)))
                continue
            resolved = str(path.resolve())
            if resolved in known:
                continue
            self.jobs.append({
                "source_path": resolved,
                "status": "Pendiente",
                "result": None,
                "force": False,
                "is_png": path.suffix.lower() == ".png",
                "protection_zones": [],
            })
            known.add(resolved)
            added += 1

        if rejected:
            details = "\n".join(f"• {name}: {reason}" for name, reason in rejected[:8])
            if len(rejected) > 8:
                details += f"\n• Y {len(rejected) - 8} archivo(s) más."
            messagebox.showerror(
                "Archivo incompatible",
                "No se pudieron agregar algunos archivos al creador de stickers.\n\n"
                f"{details}\n\n"
                "Elegí una imagen válida o convertí el archivo a PNG/JPG e intentá nuevamente.",
                parent=self,
            )

        if not added:
            self.status.set("No se encontraron imágenes compatibles nuevas.")
            return

        # Actualizar la Treeview una sola vez para todo el batch.
        self.refresh_queue(scroll_to=first_new_index)

        png_count = sum(1 for job in self.jobs if job.get("is_png"))
        if png_count:
            self.status.set(
                f"{len(self.jobs)} archivo(s) en la cola · "
                f"{png_count} PNG: los huecos internos se completarán con blanco."
            )
        else:
            self.status.set(f"{len(self.jobs)} archivo(s) en la cola.")

        # Si la cola estaba vacía, seleccionar el primer elemento recién agregado.
        if first_new_index == 0:
            self.current_index = 0
            self.queue.selection_set("0")
            self.render_current()

        # Preparar es automático; aprobar sigue siendo siempre una decisión.
        if run_queue:
            self.after(60, self.process_queue)

    # ──────────────────────────────────────────────────────────────────────
    # Eliminación con teclado
    # ──────────────────────────────────────────────────────────────────────

    def _delete_selected_job(self, _event=None):
        """Elimina el job seleccionado con Supr/Delete.

        - Jobs pendientes o con error: se eliminan sin confirmación.
        - Jobs con resultado (procesado, listo, revisar): pide confirmación.
        - Jobs en proceso activo: no se puede borrar hasta que terminen.
        """
        job = self.current_job()
        if not job:
            return "break"

        status = job.get("status", "")
        # No permitir borrar mientras está siendo procesado activamente.
        if status in {"Buscando duplicados", "Procesando"}:
            self.status.set("Esperá a que termine el procesamiento actual antes de eliminar.")
            return "break"

        # Confirmar solo si ya hay un resultado generado.
        has_result = job.get("result") is not None
        if has_result and status not in {"Confirmado", "Rechazado", "Error"}:
            if not messagebox.askyesno(
                "Eliminar de la cola",
                f"Eliminar '{Path(job['source_path']).name}' del creador?\n\n"
                "El sticker procesado se marcará como descartado. El archivo original no cambia.",
                parent=self,
            ):
                return "break"

        # Un aprobado ya está en la biblioteca. Quitar su fila de la cola no
        # debe convertir ese registro aprobado en un descarte.
        if has_result and status != "Confirmado":
            try:
                self.database.discard_processed_sticker(job["result"].job_id)
            except Exception:
                pass

        index = self.current_index
        self.jobs.pop(index)

        # Ajustar current_index tras la eliminación.
        if not self.jobs:
            self.current_index = None
            self.refresh_queue()
            self._reset_empty_view()
        else:
            self.current_index = min(index, len(self.jobs) - 1)
            self.refresh_queue()
            self.queue.selection_set(str(self.current_index))
            self.queue.see(str(self.current_index))
            self.render_current()
            self.status.set(f"{len(self.jobs)} archivo(s) en la cola.")

        return "break"

    def _load_saved_jobs(self):
        """No restaura resultados: su revisión se hace en Últimos Procesados."""
        # Los resultados persistidos salen del Creador al completar el pipeline.
        # La única cola de decisiones es la galería principal.
        recoverable: set[str] = set()
        known = {job["source_path"] for job in self.jobs}
        
        try:
            rows = list(self.database.sticker_processing_jobs(limit=500))
        except Exception:
            return
        
        for row in reversed(rows):
            if row.get("status") not in recoverable or row.get("source_path") in known:
                continue
            
            source_path = row["source_path"]
            if not Path(source_path).exists():
                continue
                
            try:
                artifacts = json.loads(row.get("artifacts") or "{}")
                profile = json.loads(row.get("profile") or "{}")
                notes = json.loads(row.get("quality_notes") or "[]")
                saved_tags = json.loads(row.get("tags") or "[]")
                saved_analysis = json.loads(row.get("analysis") or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                artifacts = {}
                profile = {}
                notes = []
                saved_tags = []
                saved_analysis = {}
            
            # Si tiene artifacts válidos, es un job ya procesado que se puede revisar
            if artifacts and len(artifacts) > 0:
                result = ProcessingResult(
                    job_id=row["id"], source_path=source_path,
                    output_dir=str(Path(next(iter(artifacts.values()))).parent),
                    status=row.get("status") or "Procesado",
                    quality_status=row.get("quality_status") or "Revisar",
                    quality_notes=notes, analysis=saved_analysis or {"engine": row.get("engine") or ""},
                    artifacts=artifacts, profile=profile,
                    duplicate_path=row.get("duplicate_path") or "",
                    duplicate_score=float(row.get("duplicate_score") or 0),
                )
                job_status = row.get("status") or "Procesado"
                self.jobs.append({
                    "source_path": source_path, "status": job_status,
                    "result": result, "force": False,
                    "category": row.get("category") or "", "tags": saved_tags,
                    "is_png": Path(source_path).suffix.lower() == ".png",
                    "protection_zones": [tuple(int(v) for v in zone) for zone in (result.analysis.get("protection_zones") or []) if hasattr(zone, "__iter__")],
                })
            else:
                # No tiene artifacts, debe procesarse desde cero
                self.jobs.append({
                    "source_path": source_path, "status": "Pendiente",
                    "result": None, "force": False,
                    "category": row.get("category") or "", "tags": saved_tags,
                    "is_png": Path(source_path).suffix.lower() == ".png",
                    "protection_zones": [],
                })
            
            known.add(source_path)
        
        if self.jobs:
            self.current_index = 0
            self.refresh_queue()
            self.queue.selection_set("0")
            self.render_current()
            
            # Contar pendientes
            pending_count = sum(1 for job in self.jobs if job["status"] == "Pendiente")
            
            if pending_count > 0:
                self.status.set(f"Se recuperaron {len(self.jobs)} trabajo(s): {pending_count} pendiente(s).")
                # Procesar automáticamente después de cargar
                self.after(300, self.process_queue)
            else:
                self.status.set(f"Se recuperaron {len(self.jobs)} trabajo(s) para revisar.")
    def _evaluate_job_candidates(self, job):
        """Evalúa propuestas sin sustituir correcciones ni errores técnicos."""
        if (job.get("mask_override") or job.get("creation_mode") == "Sticker de imagen completa"
                or (job.get("result") and job["result"].analysis.get("quality_report", {}).get("errors"))):
            return
        if not job.get("result"):
            return
        if "winner" in job:
            return
        try:
            from app.stickers.mask_candidates import generate_and_score_all_candidates, select_candidate
            processing_source = job.get("processing_source_path") or job["source_path"]
            
            # Validar que el archivo exista antes de procesar
            if not Path(processing_source).exists():
                print(f"Warning: Source file not found for candidate evaluation: {processing_source}")
                return
            
            candidates = generate_and_score_all_candidates(processing_source)
            winner, decision = select_candidate(candidates)
            job["candidates"] = candidates
            job["winner"] = winner
            job["decision"] = decision
            
            # Ajustar estado de calidad basado en la decisión
            if decision.requires_review or winner.scores.get("suspicious_component_count", 0.0) > 0.0:
                job["result"].quality_status = "Revisar"

            else:
                job["result"].quality_status = "Listo"
                
        except FileNotFoundError as e:
            print(f"Error: File not found when evaluating candidates: {e}")
            job["result"].quality_status = "Revisar"
        except ValueError as e:
            print(f"Error: Invalid data when evaluating candidates: {e}")
            job["result"].quality_status = "Revisar"
        except Exception as e:
            print(f"Error evaluating candidates for job: {e}")
            # En caso de error, marcar como revisar por seguridad
            if job.get("result"):
                job["result"].quality_status = "Revisar"

    def _schedule_candidate_evaluation(self, index: int, job: dict):
        """Calcula el diagnóstico pesado fuera del hilo de Tk."""
        if "winner" in job or index in self._candidate_jobs:
            return
        self._candidate_jobs.add(index)

        def evaluate():
            try:
                self._evaluate_job_candidates(job)
            finally:
                def update_ui():
                    self._candidate_jobs.discard(index)
                    if self.empty_requested or index >= len(self.jobs) or self.jobs[index] is not job:
                        return
                    self.refresh_queue()
                    if self.current_index == index:
                        self.render_current()
                self.after(0, update_ui)

        threading.Thread(target=evaluate, daemon=True).start()

    def _format_queue_filename(self, job) -> str:
        path_str = job.get("source_path")
        result = job.get("result")
        if result and result.analysis and "original_source_path" in result.analysis:
            path_str = result.analysis["original_source_path"]
            
        p = Path(path_str)
        stem = p.stem
        ext = p.suffix
        
        if len(stem) > 16:
            stem = stem[:13] + "..."
            
        same_name_indices = []
        for idx, other_job in enumerate(self.jobs):
            other_path_str = other_job.get("source_path")
            other_res = other_job.get("result")
            if other_res and other_res.analysis and "original_source_path" in other_res.analysis:
                other_path_str = other_res.analysis["original_source_path"]
            other_p = Path(other_path_str)
            if other_p.stem == p.stem and other_p.suffix.lower() == p.suffix.lower():
                same_name_indices.append(idx)
                
        try:
            current_idx = self.jobs.index(job)
        except ValueError:
            current_idx = -1
            
        if len(same_name_indices) > 1 and current_idx in same_name_indices:
            dup_num = same_name_indices.index(current_idx) + 1
            return f"{stem} ({dup_num}){ext}"
        else:
            return f"{stem}{ext}"

    def refresh_queue(self, scroll_to: int | None = None):
        selected = self.current_index
        self.queue.delete(*self.queue.get_children())
        for index, job in enumerate(self.jobs):
            # NO evaluar candidatos aquí - es muy lento y bloquea la UI
            # Solo se evaluará cuando el usuario seleccione el job
            result = job.get("result")
            analysis = result.analysis if result else {}
            
            filename_val = self._format_queue_filename(job)
            status_val = job["status"]
            engine_val = analysis.get("engine", "—")
            
            if "winner" in job and job["winner"] is not None:
                calidad_val = f"{round(job['winner'].score * 100)} %"
            else:
                calidad_val = "—"
            
            self.queue.insert("", "end", iid=str(index), values=(filename_val, status_val, engine_val, calidad_val))

        self._refresh_queue_summary()
            
        if selected is not None and selected < len(self.jobs):
            self.queue.selection_set(str(selected))
        if scroll_to is not None and scroll_to < len(self.jobs):
            self.queue.see(str(scroll_to))

    def _refresh_queue_summary(self):
        """Muestra un resumen corto de la cola sin recalcular el análisis."""
        if not hasattr(self, "queue_summary"):
            return
        total = len(self.jobs)
        if not total:
            self.queue_summary.set("Sin archivos")
            return
        ready = sum(job.get("status") == "Procesado" for job in self.jobs)
        processing = sum(job.get("status") in {"Procesando", "Buscando duplicados"} for job in self.jobs)
        pending = sum(job.get("status") in {"Pendiente", "Reprocesar"} for job in self.jobs)
        parts = []
        if ready:
            parts.append(f"{ready} listo{'s' if ready != 1 else ''}")
        if processing:
            parts.append(f"{processing} procesando")
        if pending:
            parts.append(f"{pending} pendiente{'s' if pending != 1 else ''}")
        self.queue_summary.set(" · ".join(parts) or f"{total} archivo{'s' if total != 1 else ''}")

    def select_job(self, _event=None):
        selection = self.queue.selection()
        if not selection:
            return
        if self.current_index is not None and self.current_index < len(self.jobs):
            current_job = self.jobs[self.current_index]
            current_job["category"] = self.category.get().strip()
            current_job["tags"] = [tag.strip() for tag in self.tags.get().split(",") if tag.strip()]
            current_job["processing_mode"] = self.processing_mode.get()
            current_job["creation_mode"] = self.creation_mode.get()
            current_job["full_image_shape"] = self.full_image_shape.get()
            visual_label = self.visual_classification.get()
            current_job["visual_type_label_override"] = visual_label
            current_job["visual_type_override"] = (
                VISUAL_STICKER_TYPE_IDS_BY_LABEL.get(visual_label)
                if visual_label != "Automática" else None)
            current_job["selected_component_ids"] = sorted({
                int(raw_identifier.strip())
                for raw_identifier in self.selected_components.get().split(",")
                if raw_identifier.strip().isdigit() and int(raw_identifier.strip()) > 0
            })
        # En selección múltiple la fila con foco es la que se previsualiza.
        focused = self.queue.focus()
        self.current_index = int(focused if focused in selection else selection[-1])
        self.render_current()

    def _selected_queue_indices(self) -> list[int]:
        """Índices válidos seleccionados, en el orden visual de la cola."""
        return sorted(
            int(item) for item in self.queue.selection()
            if item.isdigit() and int(item) < len(self.jobs)
        )

    def _show_queue_context_menu(self, event):
        """Acciones de revisión disponibles con clic derecho en la cola."""
        item = self.queue.identify_row(event.y)
        if not item:
            return "break"
        if item not in self.queue.selection():
            self.queue.selection_set(item)
        self.queue.focus(item)
        self.current_index = int(item)
        self.render_current()

        selected = self._selected_queue_indices()
        can_modify = len(selected) == 1 and bool(
            self.jobs[selected[0]].get("result"))
        can_confirm = any(
            self.jobs[index].get("result") and self.jobs[index].get("status") == "Procesado"
            for index in selected
        )
        can_reject = any(
            self.jobs[index].get("status") not in {"Confirmado", "Rechazado"}
            for index in selected
        )

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label="Modificar sticker",
            command=self.open_mask,
            state="normal" if can_modify else "disabled",
        )
        menu.add_separator()
        menu.add_command(
            label=f"Enviar a revisión seleccionado{'s' if len(selected) != 1 else ''}",
            command=self.confirm_selected_jobs,
            state="normal" if can_confirm else "disabled",
        )
        menu.add_command(
            label=f"Rechazar seleccionado{'s' if len(selected) != 1 else ''}",
            command=self.reject_selected_jobs,
            state="normal" if can_reject else "disabled",
        )
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()
        return "break"

    def confirm_selected_jobs(self):
        """Envía los seleccionados al segundo control, uno por uno."""
        selected_jobs = [self.jobs[index] for index in self._selected_queue_indices()]
        ready = [job for job in selected_jobs if job.get("result") and job.get("status") == "Procesado"]
        if not ready:
            self.status.set("No hay stickers listos para enviar a revisión.")
            return
        if len(ready) > 1 and not messagebox.askyesno(
                "Enviar stickers a revisión",
                f"¿Enviar {len(ready)} stickers a Últimos Procesados para el segundo control?",
                parent=self):
            return
        for job in ready:
            if job not in self.jobs:
                continue
            self.current_index = self.jobs.index(job)
            self.approve_current()

    def reject_selected_jobs(self):
        """Rechaza los trabajos seleccionados sin tocar los demás."""
        selected_jobs = [self.jobs[index] for index in self._selected_queue_indices()]
        candidates = [job for job in selected_jobs if job.get("status") not in {"Confirmado", "Rechazado"}]
        if not candidates:
            self.status.set("No hay stickers que se puedan rechazar.")
            return
        if len(candidates) > 1 and not messagebox.askyesno(
                "Rechazar stickers",
                f"¿Rechazar {len(candidates)} stickers seleccionados?",
                parent=self):
            return
        for job in candidates:
            if job not in self.jobs:
                continue
            self.current_index = self.jobs.index(job)
            self.discard_current(confirm=False)

    def render_current(self):
        if self.current_index is None or self.current_index >= len(self.jobs):
            self._update_review_actions()
            return
            
        job = self.jobs[self.current_index]
        if self.brush_mode.get():
            # Un cambio de archivo no debe dejar activo un pincel que escribe
            # directamente sobre el maestro anterior.
            self.brush_mode.set(False)
            self.toggle_brush_mode()
        result: ProcessingResult | None = job.get("result")
        self.category.set(job.get("category", ""))
        self.tags.set(", ".join(job.get("tags", [])))
        self.processing_mode.set(job.get("processing_mode", "Automático"))
        self.creation_mode.set(job.get("creation_mode", "Sticker de silueta"))
        self.full_image_shape.set(job.get("full_image_shape", "Rectangular"))
        self.visual_classification.set(
            job.get("visual_type_label_override", "Automática"))
        self.selected_components.set(
            ", ".join(str(item) for item in job.get("selected_component_ids", [])))
        
        reasons_text = ""
        if result:
            self._schedule_candidate_evaluation(self.current_index, job)
            confidence_str = ""
            if "decision" in job:
                confidence_str = f" — confianza {job['decision'].confidence} %"
            sticker_type_label = result.analysis.get("sticker_type_label", "")
            quality_state = result.analysis.get("quality_report", {}).get("status", result.quality_status)
            state_detail = sticker_type_label or result.analysis.get("engine", "")
            self.review_state.set(f"{job['status']} · {quality_state} · {state_detail}")
            
            reasons = []
            if sticker_type_label:
                reasons.append(f"• Tipo visual: {sticker_type_label}")
            detected_types = result.analysis.get("detected_types", [])
            complementary = [item for item in detected_types[1:] if item]
            if complementary:
                labels = dict(VISUAL_STICKER_TYPES)
                reasons.append("• Rasgos: " + ", ".join(
                    labels.get(item, item.replace("_", " "))
                    for item in complementary))
            if "winner" in job:
                winner = job["winner"]
                decision = job["decision"]
                scores = winner.scores
                
                if scores.get("suspicious_component_count", 0.0) > 0.0:
                    reasons.append("• Componente separado detectado")
                    
                comp_count = int(scores.get("component_count", 1))
                if comp_count > 1:
                    reasons.append(f"• {comp_count} componentes de foreground")
                    
                sec_comps = winner.diagnostics.get("secondary_components", [])
                for sc in sec_comps:
                    reasons.append(f"  - Componente secundario: {round(sc['area_pct'], 1)} % del área")
                    reasons.append(f"  - Distancia al principal: {round(sc['distance_pct'], 1)} % de la diagonal")
                
                if decision.confidence < 70.0:
                    reasons.append("• Confianza de máscara baja")
                    
                if scores.get("edge_occupancy_ratio", 0.0) > 0.15:
                    reasons.append("• Fondo residual probable")
                    
                if scores.get("area_ratio", 0.0) < 0.05:
                    reasons.append("• Posible eliminación del diseño")
                    
                if scores.get("edge_occupancy_ratio", 0.0) > 0.0:
                    reasons.append("• Objeto tocando el borde")
                    
                if decision.confidence < 80.0:
                    reasons.append("• Baja coincidencia entre candidatos")
                    
                if scores.get("contour_complexity", 0.0) > 8.0:
                    reasons.append("• Trazo exterior irregular")
            
            if reasons:
                reasons_text = "\n".join(reasons)
            else:
                reasons_text = "• No hay alertas significativas detectadas en el diseño."
                
            if "winner" in job:
                reasons_text += (
                    f"\n\nCandidato elegido: {job['winner'].name} | Score: {round(job['winner'].score * 100, 1)} %\n"
                    f"Área conservada: {round(job['winner'].scores.get('area_ratio', 0.0) * 100, 1)} % | "
                    f"Fondo eliminado: {round(job['winner'].scores.get('background_removed_ratio', 0.0) * 100, 1)} %\n"
                    f"Ancho del borde blanco: {self.profile.final_white_px} px | Motor: {result.analysis.get('engine', '—')}"
                )
        else:
            self.review_state.set(job["status"])
            reasons_text = "Procesando el sticker para evaluar la calidad..."
            
        self.reasons_content.configure(text=reasons_text)
        
        if result:
            notes = list(result.quality_notes or [])
            if job.get("category"):
                notes.append(f"Categoría sugerida: {job['category']}")
            if job.get("tags"):
                notes.append(f"Etiquetas sugeridas: {', '.join(job['tags'][:6])}")
            if result.analysis.get("kind") == "Fotografía" and not job.get("selection_box"):
                notes.append("Es una foto o captura: usa 'Seleccionar area' para aislar el sticker.")
            if job.get("selection_box"):
                notes.append(
                    "Se conservó el recorte rectangular completo, incluido su fondo."
                    if job.get("selection_mode") == "selection"
                    else "Se conservó solamente la silueta detectada dentro del área seleccionada."
                )
                notes.append("El archivo original permanece completo y sin modificaciones.")
            if job.get("protection_zones"):
                notes.append("Se aplicaron zonas protegidas: el pipeline no modificará esas áreas.")
            if result.analysis.get("png_holes_filled_white"):
                notes.append("Los huecos internos del PNG se completaron automáticamente con blanco.")
            creation_mode = result.analysis.get("creation_mode", "")
            if creation_mode:
                shape = result.analysis.get("full_image_shape", "Rectangular")
                notes.append(f"Modo de creación: {creation_mode} · forma: {shape}.")
            object_components = result.analysis.get("object_components", [])
            if object_components:
                selected = [str(item["id"]) for item in object_components if item.get("selected")]
                notes.append(
                    f"Se guardaron {len(object_components)} máscaras de objetos"
                    f" (seleccionados: {', '.join(selected)}).")
            if result.analysis.get("object_selection_warning"):
                notes.append(result.analysis["object_selection_warning"])
            recovery = result.analysis.get("automatic_recovery", {})
            if recovery:
                notes.append("Recuperación automática evaluada. Usá ‘Alternativa anterior’ para comparar las propuestas conservadas.")
            if (result.analysis.get("creation_mode") == "Sticker de imagen completa"
                    and result.analysis.get("full_image_shape") == "Personalizado"
                    and not job.get("mask_override")):
                notes.append(
                    "Para una forma personalizada, usá ‘Corregir silueta’ y reprocesá.")
            notes.append("Propuesta automática lista. Confirmá únicamente si el sticker final está correcto.")
            self.notes.set("\n".join(f"- {note}" for note in notes))
        else:
            if job.get("is_png"):
                self.notes.set("PNG detectado: los huecos internos se completaran con blanco al procesar.")
            elif job.get("protection_zones"):
                n = len(job["protection_zones"])
                self.notes.set(f"{n} zona(s) protegida(s) activas. Procesando cuando este listo.")
            else:
                self.notes.set("La aplicacion esta preparando una propuesta automatica.")

        photo = None
        mode = self.view_mode.get()
        original_path = job.get("source_path")
        
        # Verificar que result existe antes de acceder a sus atributos
        mask_path = result.artifacts.get("mask") if result and result.artifacts else None
        master_path = (result.artifacts.get("master") or result.artifacts.get("print") or "") if result and result.artifacts else ""
        cut_path = result.artifacts.get("cut") if result and result.artifacts else None
        
        # Inicializar logger antes de usarlo
        import logging
        logger = logging.getLogger(__name__)
        
        # Usar manifiesto si está disponible para garantizar rutas correctas de la ejecución actual
        manifest_path = result.artifacts.get("manifest") if result and result.artifacts else None
        if manifest_path and Path(manifest_path).exists():
            try:
                import json
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
                    # Usar rutas explícitas del manifiesto
                    if mode == "Resultado final" and manifest.get("final_path"):
                        master_path = manifest["final_path"]
                        logger.info("STICKER_EDITOR_USING_MANIFEST_FINAL=%s", master_path)
            except Exception as e:
                logger.exception("STICKER_EDITOR_MANIFEST_ERROR")
        
        try:
            from PIL import Image, ImageTk
            import numpy as np
            
            # Logging para diagnóstico
            if master_path:
                logger.info("STICKER_EDITOR_MASTER_PATH=%s", master_path)
                logger.info("STICKER_EDITOR_MASTER_EXISTS=%s", Path(master_path).exists() if master_path else False)
            if mask_path:
                logger.info("STICKER_EDITOR_MASK_PATH=%s", mask_path)
            if original_path:
                logger.info("STICKER_EDITOR_SOURCE_PATH=%s", original_path)

            
            img = None
            if mode == "Resultado final" and master_path:
                logger.error(
                    "UI_OPENING_PREVIEW=%s",
                    Path(master_path).resolve(),
                )

                with Image.open(master_path) as src:
                    img = src.convert("RGBA").copy()

                extrema = img.getchannel("A").getextrema()
                logger.error("UI_PREVIEW_ALPHA=%s", extrema)

                # Apply selected background for preview only (not saved to file)
                background_mode = self.background_mode.get()
                if background_mode == "Cuadriculado":
                    img = make_checkerboard_preview(img)
                elif background_mode == "Blanco":
                    img = make_white_background_preview(img)
                else:  # Negro
                    img = make_black_background_preview(img)
            elif mode == "Original" and original_path:
                with Image.open(original_path) as src:
                    img = src.convert("RGBA").copy()
                background = Image.new("RGBA", img.size, (17, 19, 20, 255))
                background.alpha_composite(img)
                img = background
            elif mode == "Máscara cruda" and mask_path:
                with Image.open(mask_path) as src:
                    m = src.convert("L").copy()
                m_arr = np.array(m)
                rgba_arr = np.zeros((m.size[1], m.size[0], 4), dtype=np.uint8)
                rgba_arr[m_arr == 255] = [255, 255, 255, 255]
                rgba_arr[m_arr == 0] = [17, 19, 20, 255]
                img = Image.fromarray(rgba_arr, mode="RGBA")
            elif mode == "Superposición" and original_path and mask_path:
                img = _build_superposition_image(original_path, mask_path)
            elif mode == "Contorno de corte" and cut_path:
                with Image.open(cut_path) as src:
                    c = src.convert("L").copy()
                c_arr = np.array(c)
                import cv2
                contours, _ = cv2.findContours(c_arr, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                outline_arr = np.zeros((c.size[1], c.size[0], 4), dtype=np.uint8)
                cv2.drawContours(outline_arr, contours, -1, (255, 0, 0, 255), 2)
                background = Image.new("RGBA", c.size, (17, 19, 20, 255))
                background.alpha_composite(Image.fromarray(outline_arr, mode="RGBA"))
                img = background
                
            if img:
                img.thumbnail((570, 440), Image.Resampling.LANCZOS)
                self._preview_display_size = img.size
                photo = ImageTk.PhotoImage(img)
        except Exception as e:
            print(f"Error loading preview image in mode {mode}: {e}")
            photo = None
            
        self.preview_images = [photo] if photo else []
        self.final_preview.delete("all")
        if photo:
            canvas_w = max(self.final_preview.winfo_width(), 1)
            canvas_h = max(self.final_preview.winfo_height(), 1)
            x = max(0, (canvas_w - self._preview_display_size[0]) // 2)
            y = max(0, (canvas_h - self._preview_display_size[1]) // 2)
            self._preview_offset = (x, y)
            self.final_preview.create_image(x, y, image=photo, anchor="nw", tags="preview_image")
            self.final_preview.image = photo
            
            # Update transparency label based on background mode
            background_mode = self.background_mode.get()
            if background_mode == "Cuadriculado":
                self.transparency_label.config(text="Fondo cuadriculado = transparencia")
            elif background_mode == "Blanco":
                self.transparency_label.config(text="Fondo blanco = transparencia")
            else:  # Negro
                self.transparency_label.config(text="Fondo negro = transparencia")
        else:
            self._preview_display_size = (0, 0)
            self._preview_offset = (0, 0)
            self.final_preview.create_text(
                self.final_preview.winfo_width() // 2 if self.final_preview.winfo_width() > 1 else 285,
                self.final_preview.winfo_height() // 2 if self.final_preview.winfo_height() > 1 else 220,
                text=(
                    "Preparando el sticker final..."
                    if result
                    else "Agrega una imagen para ver el sticker final"
                ),
                fill=COLORS.disabled,
                font=(UI_FONT, 10)
            )
            self.final_preview.image = None
        self._update_review_actions(job)

    def _update_review_actions(self, job=None):
        """Activa únicamente las acciones válidas para el estado seleccionado."""
        buttons = getattr(self, "review_buttons", {})
        status = job.get("status", "") if job else ""
        result = job.get("result") if job else None
        busy = status in {"Buscando duplicados", "Procesando"}
        editable = bool(job and not busy and status != "Confirmado")
        enabled = {
            "Reprocesar": editable,
            "Seleccionar área": editable,
            "Proteger zonas": editable,
            "Corregir silueta": bool(result and result.artifacts.get("mask") and editable),
        }
        for text, button in buttons.items():
            button.state(["!disabled"] if enabled.get(text, False) else ["disabled"])
        can_decide = bool(job and result and status == "Procesado")
        if hasattr(self, "approve_button"):
            self.approve_button.state(["!disabled"] if can_decide else ["disabled"])
        if hasattr(self, "reject_button"):
            self.reject_button.state(["!disabled"] if editable else ["disabled"])

    @staticmethod
    def _thumbnail(path: str | None, maximum: tuple[int, int] = (310, 220)):
        """Genera una ImageTk.PhotoImage escalada para la vista previa.

        Retorna None ante cualquier fallo sin propagar excepciones.
        Usa una copia explícita de la imagen antes de cerrar el archivo
        para que PIL no pierda los datos al salir del context manager.
        """
        if not path:
            return None
        try:
            from PIL import Image, ImageTk

            p = Path(path)
            if not p.exists() or p.stat().st_size == 0:
                return None

            with Image.open(p) as src:
                image = src.convert("RGBA").copy()  # copia antes de cerrar

            background = Image.new("RGBA", image.size, (17, 19, 20, 255))
            background.alpha_composite(image)
            background.thumbnail(maximum, Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(background)
        except Exception:
            return None

    def process_queue(self):
        debug_log = Path("debug_processing.txt")
        def log(msg):
            try:
                with open(debug_log, "a", encoding="utf-8") as f:
                    from datetime import datetime
                    f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
                    f.flush()
            except:
                pass
        
        log("="*60)
        log("process_queue() llamado")
        log(f"Total de jobs: {len(self.jobs)}")
        
        if self.worker and self.worker.is_alive():
            log("Worker ya está corriendo, saliendo")
            return
        
        # Listar status de todos los jobs
        for i, job in enumerate(self.jobs):
            log(f"  Job {i}: status={job.get('status', '???')}, path={Path(job['source_path']).name}")
        
        pending = next((index for index, job in enumerate(self.jobs) if job["status"] in {"Pendiente", "Reprocesar"}), None)
        
        if pending is None:
            log("No se encontraron jobs pendientes")
            self.status.set("No quedan archivos pendientes.")
            return
        
        log(f"Job pendiente encontrado en índice {pending}")
        self.cancel_event.clear()
        self.empty_requested = False
        self._process_index(pending)

    def _process_index(self, index: int):
        if self.cancel_event.is_set():
            return
        job = self.jobs[index]
        job["status"] = "Procesando"
        self.current_index = index
        self.refresh_queue()
        self.render_current()
        
        cut_inset = float(self.cut_inset.get())
        mask_override = job.get("mask_override")

        active_engine = [None]

        def progress(percent, message):
            if "Análisis: " in message:
                active_engine[0] = message.split("Análisis: ")[1].strip()
            
            eng = active_engine[0]
            mapped_message = message
            
            if percent > 10 and percent < 90:
                if eng == "Rápido":
                    mapped_message = "Analizando imagen con el motor rápido..."
                elif eng == "Híbrido":
                    mapped_message = "Analizando imagen con el motor híbrido..."
                elif eng in ("IA", "Gemini"):
                    mapped_message = "Enviando imagen a Gemini para analizarla..."
                elif eng == "Comparación":
                    mapped_message = "Comparando candidatos de máscara..."
            elif percent >= 90:
                if eng == "Rápido":
                    mapped_message = "Analizando imagen con el motor rápido..."
                elif eng == "Híbrido":
                    mapped_message = "Analizando imagen con el motor híbrido..."
                elif eng in ("IA", "Gemini"):
                    mapped_message = "Enviando imagen a Gemini para analizarla..."
            
            self.after(0, lambda: (self.progress_value.set(percent), self.status.set(mapped_message)))

        def work():
            debug_log = Path("debug_processing.txt")
            def log(msg):
                try:
                    with open(debug_log, "a", encoding="utf-8") as f:
                        from datetime import datetime
                        f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
                        f.flush()
                except:
                    pass
            
            try:
                log("="*60)
                log("Iniciando procesamiento")
                processing_source = job.get("processing_source_path") or job["source_path"]
                log(f"Source: {processing_source}")
                
                # Procesar el sticker directamente sin buscar duplicados
                # La búsqueda se hará al confirmar, no al procesar
                self.after(0, lambda: self.status.set("Procesando sticker..."))
                log("Status actualizado")
                
                if self.cancel_event.is_set():
                    log("Cancelado antes de procesar")
                    return
                
                log("Llamando a processor.process()...")
                # Studio 2.0 conserva ajustes por trabajo. La cola es serial,
                # por lo que aplicar el snapshot inmediatamente antes de esta
                # corrida evita que cambiar de miniatura mezcle perfiles.
                if job.get("v2_border_mm") is not None:
                    self.processor.profile.final_white_px = round(
                        float(job["v2_border_mm"]) / 25.4
                        * self.processor.profile.dpi)
                if job.get("v2_quality"):
                    self.processor.profile.quality = job["v2_quality"]
                result = self.processor.process(
                    processing_source, progress=progress, cut_inset_mm=cut_inset,
                    mask_override=mask_override,
                    preserve_full_image=job.get("selection_mode") == "selection",
                    preserve_orientation=job.get("selection_mode") == "selection",
                    mode_override=job.get("mode_override"),
                    protection_zones=job.get("protection_zones"),
                    creation_mode=job.get("creation_mode"),
                    full_image_shape=job.get("full_image_shape", "Rectangular"),
                    selected_component_ids=job.get("selected_component_ids"),
                    visual_type_override=job.get("visual_type_override"),
                    previous_object_components=job.get("previous_object_components"),
                    cut_mask_override=job.get("cut_mask_override"),
                    border_treatment=job.get("border_treatment"),
                    selection_contraction_mm=job.get("selection_contraction_mm", 0.0),
                    selection_expansion_mm=job.get("selection_expansion_mm", 0.0),
                    selection_protection_mask=job.get("selection_protection_mask"),
                    selection_smoothing_mm=job.get("selection_smoothing_mm", 0.08),
                    cancelled=self.cancel_event.is_set,
                )
                log("processor.process() completado")
                
                if processing_source != job["source_path"]:
                    result.analysis["original_source_path"] = job["source_path"]
                if job.get("selection_box"):
                    result.analysis["selected_area"] = list(job["selection_box"])
                    result.analysis["selected_area_rotation_deg"] = float(
                        job.get("selection_angle", 0.0))
                    result.analysis["source_mode"] = (
                        "Selección completa"
                        if job.get("selection_mode") == "selection"
                        else "Silueta de la selección"
                    )
                else:
                    result.analysis["source_mode"] = "Imagen completa"
                
                log("Metadata agregado")
                
                if self.semantic_analyzer and not self.cancel_event.is_set():
                    log("Iniciando análisis semántico...")
                    progress(92, "Reconociendo contenido y etiquetas")
                    try:
                        import threading
                        import time
                        
                        semantic_result = [None]
                        semantic_error = [None]
                        
                        def run_semantic():
                            try:
                                semantic_result[0] = self.semantic_analyzer(processing_source, lambda message: progress(94, message)) or {}
                            except Exception as e:
                                semantic_error[0] = e
                        
                        semantic_thread = threading.Thread(target=run_semantic, daemon=True)
                        semantic_thread.start()
                        semantic_thread.join(timeout=30)  # 30 second timeout
                        
                        if semantic_thread.is_alive():
                            log("Análisis semántico timeout - continuando sin análisis")
                            result.analysis["semantic"] = {}
                            progress(94, "Análisis semántico omitido por timeout")
                        elif semantic_error[0]:
                            log(f"Error en análisis semántico: {semantic_error[0]}")
                            result.analysis["semantic"] = {}
                            progress(94, "Análisis semántico omitido por error")
                        else:
                            result.analysis["semantic"] = semantic_result[0]
                            log("Análisis semántico completado")
                    except Exception as e:
                        log(f"Error en análisis semántico: {e}")
                        result.analysis["semantic"] = {}
                        progress(94, "Análisis semántico omitido por error")
                else:
                    log("Sin análisis semántico")
                
                if self.cancel_event.is_set():
                    log("Cancelado después de procesar")
                    self.after(0, lambda: self._finish_cancelled(index))
                    return
                
                log("Llamando a _finish_result()...")
                self.after(0, lambda: self._finish_result(index, result))
                log("Work completado exitosamente")
                
            except ProcessingCancelled:
                self.after(0, lambda: self._finish_cancelled(index))
            except Exception as error:
                log(f"ERROR: {type(error).__name__}: {error}")
                import traceback
                log(traceback.format_exc())
                error_str = str(error)
                self.after(0, lambda e=error_str: self._finish_error(index, e))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _finish_cancelled(self, index):
        if index < len(self.jobs):
            self.jobs[index]["status"] = "Cancelado"
            self.refresh_queue()
            self.render_current()
        self.status.set("Procesamiento cancelado. El original y las alternativas previas se conservaron.")

    def _finish_duplicate(self, index, candidate, score, state):
        if index >= len(self.jobs) or self.empty_requested:
            return
        self.jobs[index]["status"] = state
        self.jobs[index]["duplicate"] = candidate
        self.status.set(f"{state}: {score:.1f} % de similitud. Reprocesá para continuar igualmente.")
        self.progress_value.set(100)
        self.refresh_queue()
        self.render_current()
        self._continue_queue()

    def _finish_result(self, index, result):
        if index >= len(self.jobs) or self.empty_requested:
            return
        job = self.jobs[index]
        # Un nuevo resultado no puede reutilizar el diagnóstico de la corrida
        # anterior, incluso si este terminó en segundo plano un instante antes.
        for key in ("winner", "decision", "candidates", "error", "duplicate"):
            job.pop(key, None)
        job["result"] = result
        job["previous_object_components"] = result.analysis.get("object_components", [])
        recovery = result.analysis.get("automatic_recovery", {})
        for key in ("primary_metadata", "alternative_metadata"):
            path = recovery.get(key)
            if path and Path(path).exists():
                other = ProcessingResult.from_metadata(path)
                if other.job_id != result.job_id:
                    alternatives = job.setdefault("alternatives", [])
                    if all(item.job_id != other.job_id for item in alternatives):
                        alternatives.append(other)
                        del alternatives[:-5]
        job["status"] = "Procesado"
        semantic = result.analysis.get("semantic") or {}
        job["category"] = semantic.get("category", "")
        job["tags"] = list(dict.fromkeys(semantic.get("suggestions") or []))[:10]
        
        filename = Path(result.source_path).name
        self.progress_value.set(100)
        self.refresh_queue()
        self.current_index = index
        self.queue.selection_set(str(index))
        self.render_current()
        self.status.set(
            f"Procesado: {filename}. Revisalo, modificálo o rechazalo; "
            "solo ‘Confirmar’ lo enviará a Últimos Procesados."
        )
        
        try:
            self._continue_queue()
        except Exception as e:
            print(f"Error en _continue_queue: {e}")

    def _finish_error(self, index, error):
        """Maneja errores de procesamiento y muestra un diálogo informativo al usuario."""
        if index >= len(self.jobs) or self.empty_requested:
            return
        job = self.jobs[index]
        job["status"] = "Error"
        job["error"] = error
        
        # Actualizar el estado visual
        self.status.set(f"Error: {error[:100]}")
        self.refresh_queue()
        
        # Mostrar cuadro de diálogo detallado con el error
        source_name = Path(job["source_path"]).name
        error_title = "Error al procesar sticker"
        
        # Clasificar el tipo de error y dar contexto
        error_details = str(error)
        suggestions = []
        
        normalized_error = error_details.lower()
        if "no es una imagen compatible" in normalized_error or "está dañado" in normalized_error:
            error_type = "Archivo incompatible o dañado"
            suggestions = [
                "• Abrí el archivo en un visor para comprobar que no esté corrupto",
                "• Convertí la imagen a PNG o JPG estándar e intentá nuevamente",
                "• Verificá que el archivo no esté siendo usado por otra aplicación"
            ]
        elif "ya no existe" in normalized_error or "no se pudo acceder" in normalized_error:
            error_type = "Archivo no disponible"
            suggestions = [
                "• Verificá que el archivo no haya sido movido, eliminado o bloqueado",
                "• Volvé a agregarlo desde su ubicación actual"
            ]
        elif "demasiado grande" in normalized_error:
            error_type = "Imagen demasiado grande"
            suggestions = [
                "• Reducí la resolución de la imagen antes de procesarla",
                "• Exportala nuevamente en PNG o JPG"
            ]
        elif "permission denied" in normalized_error or "acceso denegado" in normalized_error:
            error_type = "Permiso insuficiente"
            suggestions = [
                "• Cerrá la aplicación que pueda estar usando la imagen",
                "• Mové el archivo a una carpeta local con permisos de escritura",
                "• Intentá nuevamente"
            ]
        elif "no space" in normalized_error or "espacio" in normalized_error:
            error_type = "Espacio insuficiente"
            suggestions = [
                "• Liberá espacio en el disco antes de volver a procesar",
                "• Verificá que la carpeta de trabajo esté disponible"
            ]
        elif "no transparency detected" in error_details or "fully opaque" in error_details:
            error_type = "Falta de transparencia"
            suggestions = [
                "• La imagen es completamente opaca y no tiene canal alpha",
                "• Intentá usar 'Seleccionar área' para recortar el fondo manualmente",
                "• O usá 'Proteger zonas' para marcar el diseño a conservar"
            ]
        elif "too little subject area" in error_details or "too small" in error_details:
            error_type = "Área muy pequeña"
            suggestions = [
                "• El diseño detectado es demasiado pequeño para ser un sticker",
                "• Verificá que la imagen tenga contenido visible",
                "• Revisá la resolución de la imagen original"
            ]
        elif "covers too much" in error_details or "too large" in error_details:
            error_type = "Área muy grande"
            suggestions = [
                "• No se pudo distinguir el diseño del fondo",
                "• Intentá usar 'Seleccionar área' para delimitar el diseño",
                "• O ajustá el fondo de la imagen original"
            ]
        elif "Mask size mismatch" in error_details or "shape" in error_details.lower():
            error_type = "Error de dimensiones"
            suggestions = [
                "• Hay un problema con las dimensiones de la máscara",
                "• Intentá reprocesar la imagen",
                "• Si el error persiste, verificá la integridad del archivo"
            ]
        elif "Generation failed" in error_details:
            error_type = "Error de generación"
            suggestions = [
                "• Hubo un problema al generar los candidatos de máscara",
                "• Intentá reprocesar con diferentes ajustes",
                "• Revisá que la imagen no esté corrupta"
            ]
        elif "Flood fill failed" in error_details or "Component analysis failed" in error_details:
            error_type = "Error de análisis"
            suggestions = [
                "• El análisis automático de la imagen falló",
                "• Usá 'Seleccionar área' para delimitar manualmente",
                "• Verificá que la imagen sea válida"
            ]
        else:
            error_type = "Error inesperado"
            suggestions = [
                "• Ocurrió un error no clasificado durante el procesamiento",
                "• Intentá reprocesar la imagen",
                "• Reportá este error si persiste"
            ]
        
        # Construir mensaje del diálogo
        message_parts = [
            f"No se pudo procesar: {source_name}\n",
            f"\n{error_type}:",
            f"{error_details}\n",
            "\nSugerencias:"
        ]
        message_parts.extend(suggestions)
        
        error_message = "\n".join(message_parts)
        
        # Mostrar diálogo con opciones
        self.after(0, lambda: self._show_error_dialog(error_title, error_message, job))
        
        self._continue_queue()
    
    def _show_error_dialog(self, title, message, job):
        """Muestra un cuadro de diálogo de error con opciones de acción."""
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.configure(background=COLORS.background)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        
        # Título
        header = tk.Frame(dialog, background=COLORS.panel, highlightthickness=1, 
                         highlightbackground=COLORS.border)
        header.pack(fill="x", padx=12, pady=12)
        
        tk.Label(header, text="⚠️ ERROR DE PROCESAMIENTO", 
                background=COLORS.panel, foreground=COLORS.wine_active,
                font=(IDENTITY_FONT, 14, "bold")).pack(padx=16, pady=12)
        
        # Contenido del mensaje
        content = tk.Frame(dialog, background=COLORS.background)
        content.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        
        text_widget = tk.Text(content, wrap="word", height=15, width=65,
                             background=COLORS.panel_elevated, foreground=COLORS.text,
                             font=(UI_FONT, 9), relief="flat", padx=12, pady=12)
        text_widget.insert("1.0", message)
        text_widget.configure(state="disabled")
        text_widget.pack(fill="both", expand=True)
        
        # Botones de acción
        actions = tk.Frame(dialog, background=COLORS.background)
        actions.pack(fill="x", padx=12, pady=(0, 12))
        
        def close_and_action(action_fn):
            dialog.grab_release()
            dialog.destroy()
            if action_fn:
                action_fn()
        
        ttk.Button(actions, text="Seleccionar área", 
                  command=lambda: close_and_action(self.open_area_selection),
                  style="Primary.TButton").pack(side="left", padx=4)
        ttk.Button(actions, text="Proteger zonas", 
                  command=lambda: close_and_action(self.open_protection_editor),
                  style="Secondary.TButton").pack(side="left", padx=4)
        ttk.Button(actions, text="Descartar", 
                  command=lambda: close_and_action(lambda: self.discard_current(confirm=False)),
                  style="Danger.TButton").pack(side="left", padx=4)
        ttk.Button(actions, text="Cerrar", 
                  command=lambda: close_and_action(None),
                  style="Secondary.TButton").pack(side="right", padx=4)

    def _continue_queue(self):
        pending = next((index for index, job in enumerate(self.jobs) if job["status"] in {"Pendiente", "Reprocesar"}), None)
        if pending is not None and not self.cancel_event.is_set():
            self.after(80, lambda: self._process_index(pending))

    def cancel_processing(self):
        self.cancel_event.set()
        self.status.set("Procesamiento cancelado por el usuario.")

    def empty_studio(self):
        if not self.jobs:
            self._reset_empty_view()
            return
        if not messagebox.askyesno(
            "Vaciar creador",
            "¿Vaciar toda la cola y las revisiones del creador?\n\nLos archivos originales y los stickers ya aprobados no se eliminarán.",
            parent=self,
        ):
            return
        self.empty_requested = True
        self.cancel_event.set()
        self.status.set("Cancelando tareas antes de vaciar el creador…")
        self._empty_when_idle()

    def _empty_when_idle(self):
        if self.worker and self.worker.is_alive():
            self.after(80, self._empty_when_idle)
            return
        for job in self.jobs:
            result = job.get("result")
            if result and job.get("status") != "Confirmado":
                self.database.discard_processed_sticker(result.job_id)
        self.jobs.clear()
        self.current_index = None
        self.refresh_queue()
        self._reset_empty_view()
        self.empty_requested = False

    def _reset_empty_view(self):
        self.preview_images = []
        self.final_preview.delete("all")
        self.final_preview.create_text(
            self.final_preview.winfo_width() // 2 if self.final_preview.winfo_width() > 1 else 285,
            self.final_preview.winfo_height() // 2 if self.final_preview.winfo_height() > 1 else 220,
            text="Agregá una imagen para ver el sticker final",
            fill=COLORS.disabled,
            font=(UI_FONT, 10)
        )
        self.final_preview.image = None
        self.category.set("")
        self.tags.set("")
        self.notes.set("")
        self.review_state.set("Sin selección")
        self.progress_value.set(0)
        self.status.set("Creador vacío. Agregá o pegá una imagen para comenzar.")
        self._update_review_actions()

    def open_decision_dialog(self, _event=None):
        job = self.current_job()
        if not job or not job.get("result") or job.get("status") != "Procesado":
            messagebox.showinfo("Sticker final", "Esperá a que el sticker final esté listo para revisarlo.", parent=self)
            return
        messagebox.showinfo(
            "Primer control: Creador de stickers",
            "Revisá el resultado aquí. Podés modificarlo, rechazarlo o confirmarlo. "
            "Al confirmarlo se enviará a Últimos Procesados para el segundo control.",
            parent=self,
        )

    def toggle_brush_mode(self):
        """Activa una correcci\u00f3n blanca que se guarda en el PNG maestro."""
        if self.brush_mode.get():
            job = self.current_job()
            if not job or not job.get("result"):
                self.brush_mode.set(False)
                self.status.set("Proces\u00e1 y seleccion\u00e1 un sticker antes de usar el pincel blanco.")
                return
            if self.view_mode.get() != "Resultado final":
                self.view_mode.set("Resultado final")
                self.render_current()
            self.status.set("Pincel blanco activo: cada trazo se guarda en el PNG maestro al soltar el mouse.")
            self.final_preview.bind("<ButtonPress-1>", self._brush_start)
            self.final_preview.bind("<B1-Motion>", self._brush_draw)
            self.final_preview.bind("<ButtonRelease-1>", self._brush_end)
            self.final_preview.configure(cursor="crosshair")
        else:
            self.final_preview.unbind("<ButtonPress-1>")
            self.final_preview.unbind("<B1-Motion>")
            self.final_preview.unbind("<ButtonRelease-1>")
            self.final_preview.configure(cursor="hand2")

    def _brush_start(self, event):
        """Inicia un trazo sobre la vista previa del PNG maestro."""
        offset_x, offset_y = self._preview_offset
        display_w, display_h = self._preview_display_size
        if not (offset_x <= event.x < offset_x + display_w and
                offset_y <= event.y < offset_y + display_h):
            return
        self.brush_drawing = True
        self.brush_last_x = event.x
        self.brush_last_y = event.y
        self._brush_points = [(event.x, event.y)]
        self._brush_draw(event)

    def _brush_draw(self, event):
        """Draw white brush stroke."""
        if not self.brush_drawing:
            return
        
        brush_size = self.brush_size.get()
        x, y = event.x, event.y
        
        # Draw a line from last position to current position
        if self.brush_last_x is not None and self.brush_last_y is not None:
            self.final_preview.create_line(
                self.brush_last_x, self.brush_last_y,
                x, y,
                fill="white",
                width=brush_size,
                capstyle=tk.ROUND,
                smooth=True,
                tags="brush_stroke"
            )
        
        self.brush_last_x = x
        self.brush_last_y = y
        self._brush_points.append((x, y))

    def _brush_end(self, event):
        """Persiste el trazo en el maestro y actualiza su miniatura."""
        self.brush_drawing = False
        if self._brush_points:
            self._save_white_brush_stroke(self._brush_points)
        self._brush_points = []
        self.brush_last_x = None
        self.brush_last_y = None

    def _save_white_brush_stroke(self, points: list[tuple[int, int]]):
        """Traduce el trazo de pantalla a p\u00edxeles reales del PNG maestro."""
        job = self.current_job()
        result = job.get("result") if job else None
        master_path = Path(result.artifacts.get("master", "")) if result else None
        display_w, display_h = self._preview_display_size
        if not master_path or not master_path.exists() or not display_w or not display_h:
            self.status.set("No se pudo guardar el trazo: falta el PNG maestro.")
            self.render_current()
            return

        try:
            from PIL import Image, ImageDraw

            with Image.open(master_path) as source:
                master = source.convert("RGBA")
                dpi = source.info.get("dpi", (self.profile.dpi, self.profile.dpi))
            scale_x = master.width / display_w
            scale_y = master.height / display_h
            offset_x, offset_y = self._preview_offset
            scaled_points = [
                (round(max(0, min(display_w - 1, x - offset_x)) * scale_x),
                 round(max(0, min(display_h - 1, y - offset_y)) * scale_y))
                for x, y in points
            ]
            width = max(1, round(self.brush_size.get() * (scale_x + scale_y) / 2))
            draw = ImageDraw.Draw(master)
            if len(scaled_points) == 1:
                x, y = scaled_points[0]
                radius = width / 2
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(255, 255, 255, 255))
            else:
                draw.line(scaled_points, fill=(255, 255, 255, 255), width=width, joint="curve")
                radius = width / 2
                for x, y in (scaled_points[0], scaled_points[-1]):
                    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(255, 255, 255, 255))
            master.save(master_path, dpi=dpi, optimize=False)

            thumbnail_path = Path(result.artifacts.get("thumbnail", ""))
            if thumbnail_path:
                thumbnail = master.copy()
                thumbnail.thumbnail((256, 256), Image.Resampling.LANCZOS)
                thumbnail.save(thumbnail_path, optimize=True)
            self.status.set("Correcci\u00f3n blanca guardada en el PNG maestro.")
        except Exception as exc:
            self.status.set("No se pudo guardar la correcci\u00f3n blanca.")
            print(f"Error saving white brush stroke: {exc}")
        finally:
            self.render_current()

    def approve_current(self, keep_in_session: bool = False):
        job = self.current_job()
        if not job or not job.get("result"):
            messagebox.showwarning("Sin resultado", "Procesá el archivo antes de aprobarlo.", parent=self)
            return
        
        # Buscar duplicados antes de aprobar - OPTIMIZADO
        result = job["result"]
        if result.analysis.get("quality_report", {}).get("errors"):
            messagebox.showerror(
                "Resultado inválido", "El control detectó errores técnicos. "
                "Corregí la silueta o reprocesá antes de confirmar.", parent=self)
            return
        processing_source = job.get("processing_source_path") or job["source_path"]
        
        # Usar indexed_visual_search_images que ya tiene filtros y es más eficiente
        self.status.set("Buscando duplicados antes de aprobar...")
        self.update_idletasks()
        
        duplicate_found = False
        duplicate_info = None
        
        try:
            from app.ai.visual_search import find_similar
            # OPTIMIZACIÓN: Usar indexed_visual_search_images que filtra por índice vigente
            candidates = self.database.indexed_visual_search_images()
            
            # OPTIMIZACIÓN: Limitar a 50 candidatos más recientes para búsqueda rápida
            # Ordenar por modified descendente para obtener los más recientes
            candidates.sort(key=lambda x: x.get("modified", 0), reverse=True)
            limited_candidates = candidates[:50] if len(candidates) > 50 else candidates
            
            # OPTIMIZACIÓN: Usar modo estrito y límite más bajo
            matches = find_similar(
                processing_source, limited_candidates, limit=2, minimum_score=92,
                cancelled=lambda: False,
                signature_ready=lambda _: None,
                mode="estricto",
                search_duplicates_only=True,  # Solo buscar duplicados exactos
            )
            
            if matches and len(matches) > 0:
                best_match, score = matches[0]
                if score >= 92:  # Umbral más estricto para reducir falsos positivos
                    duplicate_found = True
                    duplicate_info = (best_match, score)
                    
        except Exception as e:
            print(f"Error en búsqueda de duplicados: {e}")
            # Continuar sin búsqueda si falla
        
        # Si se encontró un duplicado, preguntar al usuario
        if duplicate_found:
            match_path, score = duplicate_info
            match_name = Path(match_path).name
            
            response = messagebox.askyesno(
                "Posible duplicado detectado",
                f"Se encontró un sticker muy similar ({score:.1f}% de coincidencia):\n\n"
                f"{match_name}\n\n"
                f"¿Querés aprobar este sticker de todas formas?",
                parent=self,
                icon='warning'
            )
            
            if not response:
                self.status.set("Aprobación cancelada por duplicado.")
                return
        
        # Aprobar el sticker
        category = self.category.get().strip()
        tags = [tag.strip() for tag in self.tags.get().split(",") if tag.strip()]
        job["category"], job["tags"] = category, tags
        self.database.save_sticker_processing(job["result"], category, tags)
        if keep_in_session:
            job["sent_to_processed"] = True
        else:
            job["status"] = "Confirmado"
        filename = Path(job["source_path"]).name
        # Primera confirmación: se persiste como pendiente de la segunda
        # revisión. No se publica en el banco ni se vincula a pedidos todavía.
        if keep_in_session:
            self.refresh_queue()
            self.status.set(
                f"Enviado a revisión: {filename}. El trabajo permanece abierto para exportar o corregir."
            )
            self.refresh_callback()
            return True
        self.jobs.pop(self.current_index)
        self.current_index = 0 if self.jobs else None
        self.refresh_queue()
        if self.current_index is None:
            self._reset_empty_view()
        else:
            self.queue.selection_set("0")
            self.render_current()
        self.status.set(
            f"Enviado a revisión: {filename}. Está disponible en Últimos Procesados; todavía no fue publicado en Biblioteca."
        )
        self.refresh_callback()
        self._select_next_review()
        return True

    def try_mask_alternative(self):
        job = self.current_job()
        if not job or not job.get("result") or job.get("status") == "Procesando":
            return
        if job.get("mask_override") or job.get("creation_mode") == "Sticker de imagen completa":
            self.status.set("Se conserva la corrección manual o el modo de imagen completa.")
            return
        if job.get("recovery_attempts", 0) >= 1:
            self.status.set("Ya se generó una alternativa. Podés comparar o corregir la silueta.")
            return
        winner = job.get("winner")
        if winner is None:
            self.status.set("Esperá a que termine la evaluación de las máscaras alternativas.")
            return
        from PIL import Image
        import numpy as np
        mask = np.asarray(winner.mask)
        if mask.dtype == bool or mask.max() <= 1:
            mask = mask.astype(np.uint8) * 255
        path = Path(job["result"].output_dir) / "mask_alternative.png"
        Image.fromarray(mask.astype(np.uint8)).save(path)
        job["recovery_attempts"] = 1
        self._reprocess_edited_mask(job, str(path))

    def restore_previous_result(self):
        job = self.current_job()
        if not job or not job.get("alternatives"):
            self.status.set("No hay alternativas anteriores para esta imagen.")
            return
        if job.get("status") == "Procesando":
            return
        previous = job["alternatives"].pop()
        if job.get("result"):
            job["alternatives"].insert(0, job["result"])
        job["result"] = previous
        job["status"] = "Procesado"
        for key in ("winner", "decision", "candidates"):
            job.pop(key, None)
        self.refresh_queue()
        self.render_current()
        self.status.set("Alternativa anterior restaurada para revisión.")

    def reprocess_current(self):
        job = self.current_job()
        if not job:
            self.status.set("Elegí un archivo de la cola para reprocesarlo.")
            return
        if job.get("status") in {"Procesando", "Buscando duplicados"}:
            self.status.set("Ese sticker ya se está procesando.")
            return
        # La evaluación anterior corresponde al resultado anterior.  Limpiarla
        # evita mostrar una confianza o alerta vieja mientras llega la nueva.
        for key in ("winner", "decision", "candidates", "error", "duplicate"):
            job.pop(key, None)
        if job.get("result"):
            alternatives = job.setdefault("alternatives", [])
            alternatives.append(job["result"])
            del alternatives[:-5]
        job["result"] = None
        mode_overrides = {
            "Automático": None,
            "Fondo uniforme": "Ilustración",
            "Foto / sujeto": "Fotografía",
            "Sticker existente": "Sticker existente",
        }
        job["processing_mode"] = self.processing_mode.get()
        job["mode_override"] = mode_overrides.get(job["processing_mode"])
        job["creation_mode"] = self.creation_mode.get()
        job["full_image_shape"] = self.full_image_shape.get()
        visual_label = self.visual_classification.get()
        job["visual_type_label_override"] = visual_label
        job["visual_type_override"] = (
            VISUAL_STICKER_TYPE_IDS_BY_LABEL.get(visual_label)
            if visual_label != "Automática" else None)
        component_ids: list[int] = []
        for raw_identifier in self.selected_components.get().split(","):
            raw_identifier = raw_identifier.strip()
            if raw_identifier.isdigit() and int(raw_identifier) > 0:
                component_ids.append(int(raw_identifier))
        job["selected_component_ids"] = sorted(set(component_ids))
        job["force"] = True
        job["status"] = "Reprocesar"
        self.progress_value.set(0)
        self.refresh_queue()
        self.render_current()
        self.status.set(f"Reprocesando: {Path(job['source_path']).name}")
        self.process_queue()

    def open_area_selection(self):
        job = self.current_job()
        if not job:
            messagebox.showinfo("Seleccionar área", "Elegí primero una imagen de la cola.", parent=self)
            return
        AreaSelectionEditor(
            self, job["source_path"],
            lambda box, image, mode, angle: self._apply_area_selection(
                job, box, image, mode, angle),
        )

    def _apply_area_selection(self, job, box, oriented_image, mode, angle=0.0):
        job.pop("mask_override", None)
        if box is None:
            job.pop("processing_source_path", None)
            job.pop("selection_box", None)
            job.pop("selection_mode", None)
            job.pop("selection_angle", None)
            message = "Se restauró la imagen completa. Reprocesando el sticker final."
        else:
            from PIL import Image
            crop = oriented_image.crop(box)
            # La selección se rota antes de entrar al pipeline. Las esquinas
            # transparentes quedan fuera del contenido y el borde se calcula
            # desde su alfa, por lo que acompaña la rotación exactamente.
            if abs(float(angle)) > 0.001:
                crop = crop.rotate(
                    -float(angle), expand=True,
                    resample=Image.Resampling.BICUBIC,
                )
            selected_path = self.inbox / f"seleccion_{time.strftime('%Y%m%d_%H%M%S')}_{id(job)}.png"
            crop.save(selected_path, dpi=(300, 300), optimize=False)
            job["processing_source_path"] = str(selected_path)
            job["selection_box"] = tuple(int(value) for value in box)
            job["selection_mode"] = mode
            job["selection_angle"] = float(angle)
            message = (
                "Área seleccionada y rotada: el borde se aplicará solamente alrededor de este recorte."
                if abs(float(angle)) > 0.001
                else "Área seleccionada: el borde se aplicará solamente alrededor de este recorte."
            )
        job["force"] = True
        job["status"] = "Reprocesar"
        self.refresh_queue()
        self.status.set(message)
        self.process_queue()

    def open_protection_editor(self):
        job = self.current_job()
        if not job:
            messagebox.showinfo("Proteger zonas", "Elegí primero una imagen de la cola.", parent=self)
            return
        source_path = job.get("processing_source_path") or job["source_path"]
        ProtectionZoneEditor(
            self, source_path,
            job.get("protection_zones", []),
            lambda zones: self._apply_protection_zones(job, zones),
        )

    def _apply_protection_zones(self, job, zones):
        job["protection_zones"] = [tuple(int(value) for value in zone) for zone in zones]
        job["force"] = True
        job["status"] = "Reprocesar"
        self.refresh_queue()
        if job["protection_zones"]:
            self.status.set(
                f"{len(job['protection_zones'])} zona(s) protegida(s) guardadas. Reprocesando el resultado final."
            )
        else:
            self.status.set("No hay zonas protegidas. Reprocesando sin restricciones.")
        self.process_queue()

    def create_individual_objects(self):
        job = self.current_job()
        result = job.get("result") if job else None
        components = result.analysis.get("object_components", []) if result else []
        if not components:
            self.status.set("Procesá primero en modo múltiples objetos para separarlos.")
            return
        source = result.artifacts.get("source_editable") or job["source_path"]
        for component in components:
            if not component.get("selected", True):
                continue
            self.jobs.append({
                "source_path": job["source_path"], "processing_source_path": source,
                "mask_override": component["artifact"], "status": "Pendiente",
                "creation_mode": "Sticker de silueta", "result": None,
                "category": job.get("category", ""), "tags": job.get("tags", []),
                "force": True, "is_png": True, "parent_object_id": component["id"],
            })
        self.refresh_queue()
        self.process_queue()

    def open_cut_editor(self):
        job = self.current_job()
        result = job.get("result") if job else None
        if not result:
            return
        def saved(path, _edited):
            job["cut_mask_override"] = path
            job.setdefault("alternatives", []).append(result)
            del job["alternatives"][:-5]
            job["status"] = "Reprocesar"
            job["force"] = True
            self.process_queue()
        MaskEditor(self, result.artifacts["master"],
                   job.get("cut_mask_override") or result.artifacts["cut"], saved,
                   editing_target="cut")

    def open_mask(self):
        job = self.current_job()
        result = job.get("result") if job else None
        path = (result.artifacts.get("mask_editable") or result.artifacts.get("mask")) if result else ""
        if path and Path(path).exists():
            source = result.artifacts.get("source_editable") or job.get("processing_source_path") or job["source_path"]
            MaskEditor(self, source, path, lambda saved, edited: self._reprocess_edited_mask(job, saved, edited))

    def _reprocess_edited_mask(self, job, path, edited_path=""):
        if job.get("result"):
            job.setdefault("alternatives", []).append(job["result"])
            del job["alternatives"][:-5]
        job["mask_override"] = path
        if edited_path:
            job["processing_source_path"] = edited_path
        job["force"] = True
        job["status"] = "Reprocesar"
        self.refresh_queue()
        self.status.set("Máscara guardada. Reprocesando el resultado final.")
        self.process_queue()

    def discard_current(self, confirm=True):
        job = self.current_job()
        if not job:
            return
        if confirm and not messagebox.askyesno("Descartar", "¿Descartar este proceso? El original no será eliminado.", parent=self):
            return
        job["status"] = "Rechazado"
        if job.get("result"):
            self.database.discard_processed_sticker(job["result"].job_id)
        self.refresh_queue()
        self._select_next_review()

    def current_job(self):
        if self.current_index is None or self.current_index >= len(self.jobs):
            return None
        return self.jobs[self.current_index]

    def _select_next_review(self):
        next_index = next((i for i, job in enumerate(self.jobs) if job["status"] == "Procesado"), None)
        if next_index is not None:
            self.current_index = next_index
            self.queue.selection_set(str(next_index))
            self.queue.see(str(next_index))
            self.render_current()

    def open_profile_editor(self):
        """Abre el editor de perfil de procesamiento."""
        def _apply(new_profile):
            self.profile = new_profile
            self.processor.profile = new_profile
            self.cut_inset.set(new_profile.cut_inset_mm)
            self.status.set(
                f"Perfil actualizado: '{new_profile.name}'. "
                "Los próximos stickers usarán esta configuración."
            )

        ProcessingProfileEditor(self, self.profile, on_save=_apply)

    def _widget_is_inside(self, widget, ancestor):
        current = widget
        while current is not None:
            if current == ancestor:
                return True
            current = getattr(current, "master", None)
        return False

    def _widget_under_pointer(self):
        try:
            return self.winfo_containing(
                self.winfo_pointerx(),
                self.winfo_pointery(),
            )
        except tk.TclError:
            return None

    def _is_native_wheel_widget(self, widget):
        if widget is None:
            return False

        try:
            widget_class = str(widget.winfo_class())
        except tk.TclError:
            return False

        return widget_class in {
            "TCombobox",
            "Combobox",
            "Listbox",
            "Text",
            "Entry",
            "TEntry",
            "Spinbox",
            "TSpinbox",
        }

    def _scroll_queue_with_direction(self, direction):
        if not hasattr(self, "queue"):
            return None
        try:
            self.queue.yview_scroll(direction, "units")
        except Exception:
            return None
        return "break"

    def _on_queue_mousewheel(self, event):
        delta = getattr(event, "delta", 0)
        if delta == 0:
            return None
        direction = -1 if delta > 0 else 1
        return self._scroll_queue_with_direction(direction)

    def _on_queue_mousewheel_linux(self, event):
        if event.num == 4:
            return self._scroll_queue_with_direction(-1)
        if event.num == 5:
            return self._scroll_queue_with_direction(1)
        return None

    def _on_studio_mousewheel(self, event):
        if not self.winfo_exists():
            return None
        widget = self._widget_under_pointer()
        if widget is None:
            return None

        # PRIORIDAD 1: panel derecho STICKER FINAL
        if self._widget_is_inside(widget, getattr(self, "review_panel", None)):
            if self._is_native_wheel_widget(widget):
                return None

            delta = getattr(event, "delta", 0)

            if delta == 0:
                return None

            if abs(delta) >= 120:
                units = -int(delta / 120)
            else:
                units = -1 if delta > 0 else 1

            # Scroll the review panel content
            if hasattr(self, '_review_canvas'):
                try:
                    self._review_canvas.yview_scroll(units, "units")
                except Exception:
                    pass

            return "break"

        # PRIORIDAD 2: cola de procesamiento
        if self._widget_is_inside(widget, self.queue_panel):
            if isinstance(widget, ttk.Scrollbar):
                return None
            protected_types = (
                ttk.Scale,
                tk.Scale,
                ttk.Combobox,
                tk.Text,
                tk.Listbox,
                tk.Spinbox,
            )
            if hasattr(ttk, "Spinbox"):
                protected_types = protected_types + (ttk.Spinbox,)
            if isinstance(widget, protected_types):
                return None
            return self._on_queue_mousewheel(event)

        # MUY IMPORTANTE:
        # No bloquear la rueda fuera de los dos paneles.
        return None

    def _on_studio_mousewheel_linux(self, event):
        if not self.winfo_exists():
            return None
        widget = self._widget_under_pointer()
        if widget is None:
            return None

        if event.num == 4:
            units = -1
        elif event.num == 5:
            units = 1
        else:
            return None

        # PRIORIDAD 1: STICKER FINAL
        if self._widget_is_inside(widget, getattr(self, "review_panel", None)):
            if self._is_native_wheel_widget(widget):
                return None

            # Scroll the review panel content
            if hasattr(self, '_review_canvas'):
                try:
                    self._review_canvas.yview_scroll(units, "units")
                except Exception:
                    pass

            return "break"

        # PRIORIDAD 2: COLA
        if self._widget_is_inside(widget, self.queue_panel):
            if widget == self.queue or self._widget_is_inside(widget, self.queue):
                return None
            if isinstance(widget, ttk.Scrollbar):
                return None
            self.queue.yview_scroll(units, "units")
            return "break"

        return None

    def _bind_studio_mousewheel(self):
        self._mousewheel_bindings = [
            "<MouseWheel>",
            "<Button-4>",
            "<Button-5>",
        ]
        self.bind_all("<MouseWheel>", self._on_studio_mousewheel)
        self.bind_all("<Button-4>", self._on_studio_mousewheel_linux)
        self.bind_all("<Button-5>", self._on_studio_mousewheel_linux)

        if hasattr(self, "queue"):
            self.queue.bind("<Enter>", lambda event: self.queue.focus_set(), add="+")
        # Los enlaces locales mantienen el desplazamiento de la cola aun
        # cuando otro control toma el foco antes de que actúe bind_all.
        for widget in (getattr(self, "queue_panel", None), getattr(self, "queue", None)):
            if widget is not None:
                widget.bind("<MouseWheel>", self._on_queue_mousewheel, add="+")
                widget.bind("<Button-4>", self._on_queue_mousewheel_linux, add="+")
                widget.bind("<Button-5>", self._on_queue_mousewheel_linux, add="+")

    def _unbind_studio_mousewheel(self):
        for sequence in getattr(self, "_mousewheel_bindings", []):
            try:
                self.unbind_all(sequence)
            except tk.TclError:
                pass
        self._mousewheel_bindings = []

    def toggle_note_mode(self):
        """Alterna entre vista completa y vista simplificada de nota (solo cola)."""
        print(f"[toggle_note_mode] Iniciando, modo actual: {self._note_mode}")
        self._note_mode = not self._note_mode
        
        if self._note_mode:
            print("[toggle_note_mode] Entrando en modo nota")
            # Entrar en modo nota: ocultar header, status strip y panel de revisión
            # Guardar estado actual
            self._original_geometry = self.geometry()
            
            # Ocultar header y status strip
            if hasattr(self, '_header_frame'):
                print("[toggle_note_mode] Ocultando header")
                self._header_frame.pack_forget()
            if hasattr(self, '_status_strip'):
                print("[toggle_note_mode] Ocultando status strip")
                self._status_strip.pack_forget()
            
            # Ocultar panel de revisión del PanedWindow
            if hasattr(self, 'main_body'):
                print("[toggle_note_mode] Ocultando panel de revisión")
                self.main_body.remove(self.review_panel)
            
            # Crear botón para volver al modo completo
            print("[toggle_note_mode] Creando botón de volver")
            self._note_mode_back_btn = tk.Frame(self, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
            self._note_mode_back_btn.pack(fill="x", padx=5, pady=5)
            ttk.Button(self._note_mode_back_btn, text="← Volver al Creador de Stickers", 
                      command=self.toggle_note_mode, style="Primary.TButton").pack(pady=5)
            
            # Cambiar título para indicar modo nota
            self.title("📝 Cola de Procesamiento - Modo Nota")
            
            # Redimensionar ventana para formato compacto de nota
            self.geometry("450x500")
            self.minsize(350, 300)
            self.resizable(True, True)
            
            self.status.set("Modo nota: Solo cola visible para copiar/pegar fácilmente")
            print("[toggle_note_mode] Modo nota activado")
        else:
            print("[toggle_note_mode] Volviendo a vista completa")
            # Volver a vista completa
            # Eliminar botón de volver si existe
            if hasattr(self, '_note_mode_back_btn') and self._note_mode_back_btn:
                print("[toggle_note_mode] Eliminando botón de volver")
                self._note_mode_back_btn.pack_forget()
                self._note_mode_back_btn = None
            
            # Restaurar header y status strip
            if hasattr(self, '_header_frame'):
                print("[toggle_note_mode] Restaurando header")
                self._header_frame.pack(fill="x", padx=14, pady=(14, 8), before=self.main_body)
            if hasattr(self, '_status_strip'):
                print("[toggle_note_mode] Restaurando status strip")
                self._status_strip.pack(fill="x", padx=14, pady=(0, 8), before=self.main_body)
            
            # Restaurar panel de revisión
            if hasattr(self, 'main_body') and hasattr(self, 'review_panel'):
                print("[toggle_note_mode] Restaurando panel de revisión")
                self.main_body.add(self.review_panel, minsize=550)
            
            # Restaurar título original
            self.title("Creador de stickers")
            
            # Restaurar geometría original
            if hasattr(self, '_original_geometry'):
                print("[toggle_note_mode] Restaurando geometría")
                self.geometry(self._original_geometry)
                _fit_window_to_screen(self, 1240, 790, 980, 650, width_ratio=0.96, height_ratio=0.88)
            
            self.status.set("Vista completa restaurada")
            print("[toggle_note_mode] Vista completa restaurada")

    def set_target_order(self, order_id: int | None, nominal_size_cm: float | None = None):
        """Configura o cambia el pedido vinculado para guardar stickers automáticamente."""
        self.target_order_id = order_id
        self.nominal_size_cm = nominal_size_cm
        self.profile.nominal_size_cm = nominal_size_cm
        
        # Actualizar el label de información si existe
        if self._order_info_label is not None and self._order_info_label.winfo_exists():
            if order_id is not None:
                try:
                    order = self.database.order(order_id)
                    client_name = order.get("client") or f"Pedido #{order_id}"
                    if nominal_size_cm is not None:
                        subtitle_text = (f"🎯 Vinculado a: {client_name} · Nominal: "
                                         f"{nominal_size_cm:.2f} cm · asset preparado al máximo productivo.")
                    else:
                        subtitle_text = (f"🎯 Vinculado a: {client_name} · Sin tamaño nominal único: "
                                         "el procesamiento queda en modo legacy y no se vincula automáticamente.")
                except Exception:
                    subtitle_text = f"🎯 Vinculado a pedido #{order_id}."
            else:
                subtitle_text = "Procesamiento genérico legacy (maestro 5,70 cm; sin nominal comercial)."
            
            self._order_info_label.config(text=subtitle_text)
        
        # Actualizar el título de la ventana
        if order_id is not None:
            try:
                order = self.database.order(order_id)
                client_name = order.get("client") or f"Pedido #{order_id}"
                self.title(f"Creador de stickers - {client_name}")
            except Exception:
                self.title(f"Creador de stickers - Pedido #{order_id}")
        else:
            self.title("Creador de stickers")

    def close(self):
        self.cancel_event.set()
        self._unbind_studio_mousewheel()
        self.destroy()
