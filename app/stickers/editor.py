"""Interfaz de cola, revisión y aprobación para crear stickers."""
from __future__ import annotations
import json
import math
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk
from app.indexer.scanner import IMAGE_EXTENSIONS
from app.stickers.pipeline import ProcessingProfile, ProcessingResult, StickerProcessor
from app.stickers.profile_editor import ProcessingProfileEditor
from app.ui.theme import COLORS, IDENTITY_FONT, UI_FONT


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
        self.drag_start = None
        self.drag_start_image = None
        self.selection_action = None
        self.selection_handle = None
        self.selection_box = None
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
            text="Arrastrá sobre la foto para conservar solamente esa zona. El archivo original no cambia.",
            background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 9),
        ).pack(anchor="w", pady=(2, 0))
        ttk.Button(header, text="Cancelar", command=self.destroy,
                   style="Secondary.TButton").pack(side="right", padx=(3, 10), pady=10)
        ttk.Button(header, text="Usar imagen completa", command=self.use_full_image,
                   style="Secondary.TButton").pack(side="right", padx=3, pady=10)
        ttk.Button(header, text="Extraer silueta", command=lambda: self.confirm_selection("silhouette"),
                   style="Primary.TButton").pack(side="right", padx=3, pady=10)
        ttk.Button(header, text="Guardar selección", command=lambda: self.confirm_selection("selection"),
                   style="Secondary.TButton").pack(side="right", padx=3, pady=10)

        self.canvas = tk.Canvas(
            self, background="#0d0f10", highlightthickness=1,
            highlightbackground=COLORS.border, cursor="crosshair",
        )
        self.canvas.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.canvas.bind("<Configure>", lambda _event: self.render())
        self.canvas.bind("<ButtonPress-1>", self.start_selection)
        self.canvas.bind("<B1-Motion>", self.update_selection)
        self.canvas.bind("<ButtonRelease-1>", self.finish_selection)
        self.bind("<Escape>", lambda _event: self.destroy())

    def render(self):
        from PIL import Image, ImageTk

        available_w = max(100, self.canvas.winfo_width() - 32)
        available_h = max(100, self.canvas.winfo_height() - 32)
        self.display_scale = min(available_w / self.original.width, available_h / self.original.height)
        size = (
            max(1, round(self.original.width * self.display_scale)),
            max(1, round(self.original.height * self.display_scale)),
        )
        preview = self.original.resize(size, Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(preview)
        offset_x = max(8, (self.canvas.winfo_width() - size[0]) // 2)
        offset_y = max(8, (self.canvas.winfo_height() - size[1]) // 2)
        self.display_offset = (offset_x, offset_y)
        self.canvas.delete("all")
        self.selection_item = None
        self.selection_handle_items = []
        self.image_item = self.canvas.create_image(offset_x, offset_y, anchor="nw", image=self.photo)
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
        self._clear_selection_items()
        if not self.selection_box:
            return
        x1, y1, x2, y2 = self.selection_box
        offset_x, offset_y = self.display_offset
        coords = (
            offset_x + x1 * self.display_scale,
            offset_y + y1 * self.display_scale,
            offset_x + x2 * self.display_scale,
            offset_y + y2 * self.display_scale,
        )
        self.selection_item = self.canvas.create_rectangle(
            *coords, outline=COLORS.wine_active, width=3, dash=(8, 4)
        )
        self._draw_selection_handles()

    def _draw_selection_handles(self):
        if not self.selection_box:
            return
        x1, y1, x2, y2 = self.selection_box
        offset_x, offset_y = self.display_offset
        size = 10
        half = size // 2
        for cx, cy in ((x1, y1), (x2, y1), (x1, y2), (x2, y2)):
            canvas_coords = (
                offset_x + cx * self.display_scale - half,
                offset_y + cy * self.display_scale - half,
                offset_x + cx * self.display_scale + half,
                offset_y + cy * self.display_scale + half,
            )
            handle = self.canvas.create_rectangle(
                *canvas_coords, fill=COLORS.wine_active,
                outline=COLORS.panel, width=1,
            )
            self.selection_handle_items.append(handle)

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
        self.on_selected(self.selection_box, self.original.copy(), mode)

    def use_full_image(self):
        self.grab_release()
        self.destroy()
        self.on_selected(None, None, "full")


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

        self._canvas = tk.Canvas(
            self, background="#0d0f10",
            highlightthickness=1, highlightbackground=COLORS.border,
            cursor="crosshair",
        )
        self._canvas.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._canvas.bind("<Configure>", lambda _e: self._render())
        self._canvas.bind("<ButtonPress-1>",   self._on_press)
        self._canvas.bind("<B1-Motion>",       self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
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

    def _render(self):
        from PIL import Image, ImageDraw, ImageTk

        cw = max(100, self._canvas.winfo_width()  - 32)
        ch = max(100, self._canvas.winfo_height() - 32)
        self.display_scale = min(cw / self._original.width,
                                 ch / self._original.height)
        sw = max(1, round(self._original.width  * self.display_scale))
        sh = max(1, round(self._original.height * self.display_scale))

        ox = max(8, (self._canvas.winfo_width()  - sw) // 2)
        oy = max(8, (self._canvas.winfo_height() - sh) // 2)
        self.display_offset = (ox, oy)

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
        self._canvas.create_image(ox, oy, anchor="nw",
                                  image=self._photo_overlay)
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
        if self._live_rect:
            self._canvas.delete(self._live_rect)
        self._live_rect = self._canvas.create_rectangle(
            cx1, cy1, cx2, cy2,
            outline=self._OUTLINE, width=2, dash=(6, 3),
        )

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

    def __init__(self, master, original_path, mask_path, on_saved):
        super().__init__(master)
        from PIL import Image

        self.title("Modificar sticker")
        _fit_window_to_screen(self, 900, 720, 660, 520)
        self.configure(background=COLORS.background)
        self.transient(master)
        self.original_path = Path(original_path)
        self.mask_path = Path(mask_path)
        self.on_saved = on_saved
        with Image.open(self.original_path) as source:
            self.original = source.convert("RGBA")
        with Image.open(self.mask_path) as source:
            self.mask = source.convert("L").resize(self.original.size, Image.Resampling.LANCZOS)
        self.mode = tk.StringVar(value="erase")
        self.brush = tk.IntVar(value=36)
        self.brush_color = "#ffffff"
        self.zoom = 1.0
        self.image_modified = False
        self.photo = None
        self.display_scale = 1.0
        self._render_after = None
        self._undo_stack: list[dict] = []
        self._active_stroke: dict | None = None
        self._build()
        self.after_idle(self.render)

    def _build(self):
        bar = tk.Frame(self, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        bar.pack(fill="x", padx=12, pady=12)
        tk.Label(bar, text="MODIFICAR STICKER", background=COLORS.panel, foreground=COLORS.text,
                 font=(IDENTITY_FONT, 13, "bold")).pack(side="left", padx=12)
        ttk.Radiobutton(bar, text="Quitar", value="erase", variable=self.mode).pack(side="left", padx=(20, 4), pady=10)
        ttk.Radiobutton(bar, text="Recuperar", value="restore", variable=self.mode).pack(side="left", padx=4, pady=10)
        ttk.Radiobutton(bar, text="Pincel", value="paint", variable=self.mode).pack(side="left", padx=4, pady=10)
        ttk.Button(bar, text="Cuentagotas", command=lambda *a, _fn=(lambda: self.mode.set("eyedropper")): _fn(),).pack(side="left", padx=(8, 3))
        self.color_button = tk.Button(bar, text="   ", background=self.brush_color, activebackground=self.brush_color,
                          command=lambda *a, _fn=self.choose_color: _fn(*a), relief="flat", cursor="hand2")
        self.color_button.pack(side="left", padx=3)
        tk.Label(bar, text="Pincel", background=COLORS.panel, foreground=COLORS.muted).pack(side="left", padx=(18, 4))
        ttk.Scale(bar, from_=6, to=140, variable=self.brush, orient="horizontal", length=140).pack(side="left")
        ttk.Button(bar, text="Guardar y reprocesar", command=lambda *a, _fn=self.save: _fn(*a), style="Primary.TButton").pack(side="right", padx=10)
        ttk.Button(bar, text="Cancelar", command=lambda *a, _fn=self.destroy: _fn(*a), style="Secondary.TButton").pack(side="right")
        ttk.Button(bar, text="Deshacer", command=lambda *a, _fn=self.undo: _fn(*a), style="Secondary.TButton").pack(side="right", padx=6)
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
        self.canvas.bind("<Control-MouseWheel>", self.zoom_with_wheel)
        self.canvas.bind("<MouseWheel>", lambda event: self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units"))
        self.canvas.bind("<Shift-MouseWheel>", lambda event: self.canvas.xview_scroll(-1 if event.delta > 0 else 1, "units"))
        self.bind("<Control-z>", self.undo)
        self.bind("<Control-Z>", self.undo)
        self.bind("<Escape>", lambda _event: self.destroy())

    def choose_color(self):
        chosen = colorchooser.askcolor(self.brush_color, parent=self, title="Color del pincel")[1]
        if chosen:
            self.brush_color = chosen
            self.color_button.configure(background=chosen, activebackground=chosen)
            self.mode.set("paint")

    def zoom_with_wheel(self, event):
        factor = 1.18 if event.delta > 0 else 1 / 1.18
        self.zoom = min(6.0, max(0.35, self.zoom * factor))
        self.render()
        return "break"

    def render(self):
        from PIL import Image, ImageTk

        width = max(100, self.canvas.winfo_width() - 20)
        height = max(100, self.canvas.winfo_height() - 20)
        fit_scale = min(width / self.original.width, height / self.original.height, 1.0)
        self.display_scale = fit_scale * self.zoom
        size = (max(1, round(self.original.width * self.display_scale)), max(1, round(self.original.height * self.display_scale)))
        image = self.original.resize(size, Image.Resampling.LANCZOS)
        mask = self.mask.resize(size, Image.Resampling.NEAREST)
        retained = image.copy()
        retained.putalpha(mask)
        preview = Image.new("RGBA", size, (34, 36, 38, 255))
        preview.alpha_composite(retained)
        self.photo = ImageTk.PhotoImage(preview)
        self.canvas.delete("all")
        self.canvas.create_image(10, 10, anchor="nw", image=self.photo)
        self.canvas.create_text(18, size[1] + 28, anchor="sw", fill=COLORS.muted,
                                text="Ctrl + Z: deshacer · Ctrl + rueda: zoom · rueda: desplazar · se trabaja sobre una copia.")
        self.canvas.configure(scrollregion=(0, 0, size[0] + 30, size[1] + 45))

    def image_point(self, event):
        """Convierte la posición visible en un punto de la imagen original."""
        x = (self.canvas.canvasx(event.x) - 10) / max(self.display_scale, .001)
        y = (self.canvas.canvasy(event.y) - 10) / max(self.display_scale, .001)
        if not (0 <= x < self.mask.width and 0 <= y < self.mask.height):
            return None
        return x, y

    def begin_stroke(self, event):
        point = self.image_point(event)
        if point is None:
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
        if self._active_stroke is None:
            return
        point = self.image_point(event)
        if point is not None:
            self.paint_at(*point)

    def end_stroke(self, _event=None):
        if self._active_stroke is None:
            return
        if self._active_stroke["patches"]:
            self._undo_stack.append(self._active_stroke)
            # Un historial acotado evita cargar en memoria imágenes completas.
            del self._undo_stack[:-30]
        self._active_stroke = None

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
        if self._render_after:
            self.after_cancel(self._render_after)
        self._render_after = self.after(24, self.render)

    def undo(self, _event=None):
        """Revierte de una vez la última pincelada, recuperación o borrado."""
        self.end_stroke()
        if not self._undo_stack:
            return "break"
        stroke = self._undo_stack.pop()
        for patch in reversed(stroke["patches"]):
            left, top, _right, _bottom = patch["box"]
            self.original.paste(patch["original"], (left, top))
            self.mask.paste(patch["mask"], (left, top))
        self.image_modified = stroke["image_modified_before"]
        if self._render_after:
            self.after_cancel(self._render_after)
            self._render_after = None
        self.render()
        return "break"

    def save(self):
        self.mask.save(self.mask_path, dpi=(300, 300), optimize=False)
        edited_path = ""
        if self.image_modified:
            edited = self.mask_path.with_name("edicion_manual.png")
            self.original.save(edited, dpi=(300, 300), optimize=False)
            edited_path = str(edited)
        self.on_saved(str(self.mask_path), edited_path)
        self.destroy()


class StickerStudio(tk.Toplevel):
    def __init__(self, master, database, refresh_callback=None, semantic_analyzer=None):
        super().__init__(master)
        self.database = database
        self.refresh_callback = refresh_callback or (lambda: None)
        self.semantic_analyzer = semantic_analyzer
        self.title("Creador predictivo de stickers")
        _fit_window_to_screen(self, 1240, 790, 980, 650, width_ratio=0.96, height_ratio=0.88)
        self.configure(background=COLORS.background)
        self.transient(master)
        self.profile = ProcessingProfile()
        workspace = Path(__file__).parents[2] / "work" / "stickers"
        self.processor = StickerProcessor(workspace, self.profile)
        self.inbox = workspace / "inbox"
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.jobs: list[dict] = []
        self.current_index: int | None = None
        self.worker: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.preview_images = []
        self.empty_requested = False
        self._paste_worker: threading.Thread | None = None
        self._folder_worker: threading.Thread | None = None
        self._build()
        self._load_saved_jobs()
        self.bind("<Control-v>", lambda _event: (self.paste_image(), "break")[1])
        self.bind("<Control-V>", lambda _event: (self.paste_image(), "break")[1])
        self.protocol("WM_DELETE_WINDOW", self.close)


    def _build(self):
        header = tk.Frame(self, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        header.pack(fill="x", padx=14, pady=(14, 8))
        title = tk.Frame(header, background=COLORS.panel)
        title.pack(side="left", padx=16, pady=12)
        tk.Label(title, text="CREADOR PREDICTIVO DE STICKERS", background=COLORS.panel, foreground=COLORS.text,
                 font=(IDENTITY_FONT, 18, "bold")).pack(anchor="w")
        tk.Label(title, text="La aplicación prepara y propone; vos confirmás solamente el resultado final de 5,70 cm.",
                 background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 9)).pack(anchor="w")
        actions = tk.Frame(header, background=COLORS.panel)
        actions.pack(side="right", padx=12, pady=8)
        # Fila superior: agregar archivos + perfil
        row1 = tk.Frame(actions, background=COLORS.panel)
        row1.pack(anchor="e")
        for text, command, style in (
            ("Pegar", self.paste_image, "Secondary.TButton"),
            ("Elegir archivos", self.choose_files, "Secondary.TButton"),
            ("Importar carpeta", self.choose_folder, "Secondary.TButton"),
            ("Perfil", self.open_profile_editor, "Secondary.TButton"),
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
        status_strip = tk.Frame(self, background=COLORS.panel_elevated)
        status_strip.pack(fill="x", padx=14, pady=(0, 8))
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
        queue_panel = tk.Frame(body, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        review_panel = tk.Frame(body, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        body.add(queue_panel, minsize=400, width=465)
        body.add(review_panel, minsize=550)

        tk.Label(queue_panel, text="COLA DE PROCESAMIENTO", background=COLORS.panel, foreground=COLORS.wine_active,
                 font=(IDENTITY_FONT, 12, "bold")).pack(anchor="w", padx=12, pady=(12, 7))
        columns = ("archivo", "estado", "motor", "calidad")
        self.queue = ttk.Treeview(queue_panel, columns=columns, show="headings", selectmode="browse")
        for column, label, width in (("archivo", "Archivo", 175), ("estado", "Estado", 105), ("motor", "Motor", 75), ("calidad", "Calidad", 80)):
            self.queue.heading(column, text=label)
            self.queue.column(column, width=width, anchor="w")
        scrollbar = ttk.Scrollbar(queue_panel, orient="vertical", command=lambda *a, _fn=self.queue.yview: _fn(*a))
        self.queue.configure(yscrollcommand=scrollbar.set)
        self.queue.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 10))
        scrollbar.pack(side="right", fill="y", padx=(0, 10), pady=(0, 10))
        self.queue.bind("<<TreeviewSelect>>", self.select_job)
        self.queue.bind("<Double-Button-1>", self.open_decision_dialog)
        self.queue.bind("<Delete>", self._delete_selected_job)
        self.queue.bind("<BackSpace>", self._delete_selected_job)

        review_header = tk.Frame(review_panel, background=COLORS.panel)
        review_header.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(review_header, text="STICKER FINAL", background=COLORS.panel, foreground=COLORS.wine_active,
                 font=(IDENTITY_FONT, 12, "bold")).pack(side="left")
        self.review_state = tk.StringVar(value="Sin selección")
        tk.Label(review_header, textvariable=self.review_state, background=COLORS.panel, foreground=COLORS.muted,
                 font=(UI_FONT, 9)).pack(side="right")

        final_card = tk.Frame(review_panel, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
        final_card.pack(fill="both", expand=True, padx=12)

        preview_header_bar = tk.Frame(final_card, background=COLORS.panel_elevated)
        preview_header_bar.pack(fill="x", padx=12, pady=(9, 5))

        tk.Label(preview_header_bar, text="VISTA EXACTA DEL PNG QUE SE VA A GUARDAR", background=COLORS.panel_elevated,
                 foreground=COLORS.muted, font=(IDENTITY_FONT, 9, "bold")).pack(side="left")

        self.view_mode = tk.StringVar(value="Resultado final")
        mode_cb = ttk.Combobox(preview_header_bar, textvariable=self.view_mode,
                               values=("Resultado final", "Máscara cruda", "Original", "Superposición", "Contorno de corte"),
                               state="readonly", width=16)
        mode_cb.pack(side="right")
        mode_cb.bind("<<ComboboxSelected>>", lambda _: self.render_current())

        self.final_preview = tk.Label(final_card, text="Agregá una imagen para ver el sticker final",
                                      background="#111314", foreground=COLORS.disabled, compound="center")
        self.final_preview.pack(fill="both", expand=True, padx=9, pady=(0, 9))
        self.final_preview.bind("<Double-Button-1>", self.open_decision_dialog)
        self.final_preview.configure(cursor="hand2")

        # Panel de análisis de calidad
        reasons_card = tk.Frame(review_panel, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
        reasons_card.pack(fill="x", padx=12, pady=(0, 10))
        
        tk.Label(reasons_card, text="ANÁLISIS DE CALIDAD", background=COLORS.panel_elevated,
                 foreground=COLORS.wine_active, font=(IDENTITY_FONT, 10, "bold")).pack(anchor="w", padx=12, pady=(8, 4))
        
        self.reasons_content = tk.Label(reasons_card, text="Seleccioná un sticker de la cola para ver el análisis.",
                                        background=COLORS.panel_elevated, foreground=COLORS.text,
                                        justify="left", anchor="nw", wraplength=680, font=(UI_FONT, 9))
        self.reasons_content.pack(fill="x", padx=12, pady=(0, 8))

        controls = tk.Frame(review_panel, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
        controls.pack(fill="x", padx=12, pady=10)
        self.category = tk.StringVar()
        self.tags = tk.StringVar()
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
        self.notes = tk.StringVar(value="")
        tk.Label(controls, textvariable=self.notes, background=COLORS.panel_elevated, foreground=COLORS.muted,
                 justify="left", anchor="w", wraplength=700, font=(UI_FONT, 9)).pack(fill="x", padx=14, pady=(0, 8))
        buttons = tk.Frame(controls, background=COLORS.panel_elevated)
        buttons.pack(fill="x", padx=10, pady=(0, 10))
        self.review_buttons = {}
        for text, command, style in (
            ("Confirmar sticker", self.approve_current, "Primary.TButton"),
            ("Recalcular automáticamente", self.reprocess_current, "Secondary.TButton"),
            ("Seleccionar área", self.open_area_selection, "Secondary.TButton"),
            ("Proteger zonas", self.open_protection_editor, "Secondary.TButton"),
            ("Corregir silueta", self.open_mask, "Secondary.TButton"),
            ("Descartar", self.discard_current, "Danger.TButton"),
        ):
            button = ttk.Button(buttons, text=text, command=command, style=style)
            button.pack(side="left", padx=3)
            self.review_buttons[text] = button
        self._update_review_actions()
        self._register_drop()

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
        if len(paths) == 1 and self._should_prompt_selection(paths[0]):
            def add_and_prompt():
                self.add_paths([paths[0]], run_queue=False)
                self.current_index = len(self.jobs) - 1
                self.refresh_queue()
                self.queue.selection_set(str(self.current_index))
                self.open_area_selection()
            self.after(0, add_and_prompt)
            return
        self.add_paths(paths)

    def choose_files(self):
        paths = filedialog.askopenfilenames(
            parent=self,
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff")],
        )
        if not paths:
            return
        if len(paths) == 1 and self._should_prompt_selection(Path(paths[0])):
            self.add_paths([Path(paths[0])], run_queue=False)
            self.current_index = len(self.jobs) - 1
            self.refresh_queue()
            self.queue.selection_set(str(self.current_index))
            self.open_area_selection()
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
                    if self._should_prompt_selection(path):
                        def add_and_prompt():
                            self.add_paths([path], run_queue=False)
                            self.current_index = len(self.jobs) - 1
                            self.refresh_queue()
                            self.queue.selection_set(str(self.current_index))
                            self.open_area_selection()
                        self.after(0, add_and_prompt)
                    else:
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
        if has_result and status not in {"Aprobado", "Descartado", "Error"}:
            if not messagebox.askyesno(
                "Eliminar de la cola",
                f"Eliminar '{Path(job['source_path']).name}' del creador?\n\n"
                "El sticker procesado se marcará como descartado. El archivo original no cambia.",
                parent=self,
            ):
                return "break"

        # Un aprobado ya está en la biblioteca. Quitar su fila de la cola no
        # debe convertir ese registro aprobado en un descarte.
        if has_result and status != "Aprobado":
            try:
                self.database.set_sticker_processing_status(job["result"].job_id, "Descartado")
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
        """Recupera revisiones pendientes sin volver a procesar los originales."""
        recoverable = {"Procesado", "Listo", "Revisar", "Error", "Pendiente"}
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
                job_status = row.get("quality_status") or "Revisar"
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
        """Evalúa los candidatos de máscara para un trabajo y ajusta el estado de calidad."""
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
                job["status"] = "Revisar"
            else:
                job["result"].quality_status = "Listo"
                job["status"] = "Listo"
                
        except FileNotFoundError as e:
            print(f"Error: File not found when evaluating candidates: {e}")
            job["result"].quality_status = "Revisar"
            job["status"] = "Revisar"
        except ValueError as e:
            print(f"Error: Invalid data when evaluating candidates: {e}")
            job["result"].quality_status = "Revisar"
            job["status"] = "Revisar"
        except Exception as e:
            print(f"Error evaluating candidates for job: {e}")
            # En caso de error, marcar como revisar por seguridad
            if job.get("result"):
                job["result"].quality_status = "Revisar"
                job["status"] = "Revisar"

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
            
        if selected is not None and selected < len(self.jobs):
            self.queue.selection_set(str(selected))
        if scroll_to is not None and scroll_to < len(self.jobs):
            self.queue.see(str(scroll_to))

    def select_job(self, _event=None):
        selection = self.queue.selection()
        if not selection:
            return
        if self.current_index is not None and self.current_index < len(self.jobs):
            self.jobs[self.current_index]["category"] = self.category.get().strip()
            self.jobs[self.current_index]["tags"] = [tag.strip() for tag in self.tags.get().split(",") if tag.strip()]
        self.current_index = int(selection[0])
        self.render_current()

    def render_current(self):
        if self.current_index is None or self.current_index >= len(self.jobs):
            self._update_review_actions()
            return
            
        job = self.jobs[self.current_index]
        result: ProcessingResult | None = job.get("result")
        self.category.set(job.get("category", ""))
        self.tags.set(", ".join(job.get("tags", [])))
        
        reasons_text = ""
        if result:
            self._evaluate_job_candidates(job)
            confidence_str = ""
            if "decision" in job:
                confidence_str = f" — confianza {job['decision'].confidence} %"
            self.review_state.set(f"{job['status']}{confidence_str} · {result.analysis.get('engine', '')}")
            
            reasons = []
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
        
        try:
            from PIL import Image, ImageTk
            import numpy as np
            
            img = None
            if mode == "Resultado final" and master_path:
                with Image.open(master_path) as src:
                    img = src.convert("RGBA").copy()
                background = Image.new("RGBA", img.size, (17, 19, 20, 255))
                background.alpha_composite(img)
                img = background
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
                photo = ImageTk.PhotoImage(img)
        except Exception as e:
            print(f"Error loading preview image in mode {mode}: {e}")
            photo = None
            
        self.preview_images = [photo] if photo else []
        if photo:
            self.final_preview.configure(image=photo, text="")
            self.final_preview.image = photo
        else:
            self.final_preview.configure(image="", text=(
                "Preparando el sticker final..."
                if result
                else "Agrega una imagen para ver el sticker final"
            ))
            self.final_preview.image = None
        self._update_review_actions(job)

    def _update_review_actions(self, job=None):
        """Activa únicamente las acciones válidas para el estado seleccionado."""
        buttons = getattr(self, "review_buttons", {})
        status = job.get("status", "") if job else ""
        result = job.get("result") if job else None
        busy = status in {"Buscando duplicados", "Procesando"}
        ready = bool(result and status in {"Listo", "Revisar"})
        editable = bool(job and not busy and status != "Aprobado")
        enabled = {
            "Confirmar sticker": ready,
            "Recalcular automáticamente": editable,
            "Seleccionar área": editable,
            "Proteger zonas": editable,
            "Corregir silueta": bool(result and result.artifacts.get("mask") and editable),
            "Descartar": editable,
        }
        for text, button in buttons.items():
            button.state(["!disabled"] if enabled.get(text, False) else ["disabled"])

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
                result = self.processor.process(
                    processing_source, progress=progress, cut_inset_mm=cut_inset,
                    mask_override=mask_override,
                    preserve_full_image=job.get("selection_mode") == "selection",
                    protection_zones=job.get("protection_zones"),
                )
                log("processor.process() completado")
                
                if processing_source != job["source_path"]:
                    result.analysis["original_source_path"] = job["source_path"]
                if job.get("selection_box"):
                    result.analysis["selected_area"] = list(job["selection_box"])
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
                    semantic = self.semantic_analyzer(processing_source, lambda message: progress(94, message)) or {}
                    result.analysis["semantic"] = semantic
                    log("Análisis semántico completado")
                else:
                    log("Sin análisis semántico")
                
                if self.cancel_event.is_set():
                    log("Cancelado después de procesar")
                    return
                
                log("Llamando a _finish_result()...")
                self.after(0, lambda: self._finish_result(index, result))
                log("Work completado exitosamente")
                
            except Exception as error:
                log(f"ERROR: {type(error).__name__}: {error}")
                import traceback
                log(traceback.format_exc())
                self.after(0, lambda: self._finish_error(index, str(error)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

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
        job["result"] = result
        job["status"] = result.quality_status
        semantic = result.analysis.get("semantic") or {}
        job["category"] = semantic.get("category", "")
        job["tags"] = list(dict.fromkeys(semantic.get("suggestions") or []))[:10]
        self.database.save_sticker_processing(result, job["category"], job["tags"])
        self.progress_value.set(100)
        self.status.set(f"Procesado: {Path(result.source_path).name}")
        self.refresh_queue()
        self.render_current()
        self._continue_queue()

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
            if result and job.get("status") != "Aprobado":
                self.database.set_sticker_processing_status(result.job_id, "Descartado")
        self.jobs.clear()
        self.current_index = None
        self.refresh_queue()
        self._reset_empty_view()
        self.empty_requested = False

    def _reset_empty_view(self):
        self.preview_images = []
        self.final_preview.configure(image="", text="Agregá una imagen para ver el sticker final")
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
        if not job or not job.get("result") or job.get("status") not in {"Listo", "Revisar"}:
            messagebox.showinfo("Sticker final", "Esperá a que el sticker final esté listo para revisarlo.", parent=self)
            return
        dialog = tk.Toplevel(self)
        dialog.title("Decidir sticker")
        dialog.configure(background=COLORS.panel)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        tk.Label(dialog, text="¿QUÉ QUERÉS HACER?", background=COLORS.panel, foreground=COLORS.text,
                 font=(IDENTITY_FONT, 15, "bold")).pack(padx=28, pady=(24, 5))
        tk.Label(dialog, text="La vista mostrada es el sticker final.", background=COLORS.panel,
                 foreground=COLORS.muted, font=(UI_FONT, 10)).pack(padx=28, pady=(0, 18))
        actions = tk.Frame(dialog, background=COLORS.panel)
        actions.pack(padx=22, pady=(0, 22))

        def decide(callback):
            dialog.grab_release()
            dialog.destroy()
            callback()

        ttk.Button(actions, text="Confirmar", command=lambda: decide(self.approve_current), style="Primary.TButton").pack(side="left", padx=4)
        ttk.Button(actions, text="Modificar", command=lambda: decide(self.open_mask), style="Secondary.TButton").pack(side="left", padx=4)
        ttk.Button(actions, text="Rechazar", command=lambda: decide(lambda: self.discard_current(confirm=False)), style="Danger.TButton").pack(side="left", padx=4)

    def approve_current(self):
        job = self.current_job()
        if not job or not job.get("result"):
            messagebox.showwarning("Sin resultado", "Procesá el archivo antes de aprobarlo.", parent=self)
            return
        
        # Buscar duplicados antes de aprobar
        result = job["result"]
        processing_source = job.get("processing_source_path") or job["source_path"]
        
        # Mostrar diálogo de búsqueda
        self.status.set("Buscando duplicados antes de aprobar...")
        self.update_idletasks()
        
        duplicate_found = False
        duplicate_info = None
        
        try:
            from app.ai.visual_search import find_similar
            candidates = self.database.visual_search_images()
            
            # Limitar a 200 candidatos para búsqueda rápida
            limited_candidates = candidates[:200] if len(candidates) > 200 else candidates
            
            matches = find_similar(
                processing_source, limited_candidates, limit=3, minimum_score=90,
                cancelled=lambda: False,
                signature_ready=lambda _: None,
            )
            
            if matches and len(matches) > 0:
                best_match, score = matches[0]
                if score >= 90:
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
        image = self.database.approve_processed_sticker(job["result"], category, tags)
        job["status"] = "Aprobado"
        self.refresh_queue()
        self.refresh_callback()
        self.status.set(f"Aprobado e indexado: {Path(image['path']).name}")
        self._select_next_review()

    def reprocess_current(self):
        job = self.current_job()
        if not job:
            return
        job["force"] = True
        job["status"] = "Reprocesar"
        self.refresh_queue()
        self.process_queue()

    def open_area_selection(self):
        job = self.current_job()
        if not job:
            messagebox.showinfo("Seleccionar área", "Elegí primero una imagen de la cola.", parent=self)
            return
        AreaSelectionEditor(
            self, job["source_path"],
            lambda box, image, mode: self._apply_area_selection(job, box, image, mode),
        )

    def _apply_area_selection(self, job, box, oriented_image, mode):
        job.pop("mask_override", None)
        if box is None:
            job.pop("processing_source_path", None)
            job.pop("selection_box", None)
            job.pop("selection_mode", None)
            message = "Se restauró la imagen completa. Reprocesando el sticker final."
        else:
            crop = oriented_image.crop(box)
            selected_path = self.inbox / f"seleccion_{time.strftime('%Y%m%d_%H%M%S')}_{id(job)}.png"
            crop.save(selected_path, dpi=(300, 300), optimize=False)
            job["processing_source_path"] = str(selected_path)
            job["selection_box"] = tuple(int(value) for value in box)
            job["selection_mode"] = mode
            message = (
                "Selección guardada completa, sin quitar el fondo."
                if mode == "selection"
                else "Área seleccionada. Extrayendo solamente la silueta."
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

    def open_mask(self):
        job = self.current_job()
        result = job.get("result") if job else None
        path = result.artifacts.get("mask") if result else ""
        if path and Path(path).exists():
            source = job.get("processing_source_path") or job["source_path"]
            MaskEditor(self, source, path, lambda saved, edited: self._reprocess_edited_mask(job, saved, edited))

    def _reprocess_edited_mask(self, job, path, edited_path=""):
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
        job["status"] = "Descartado"
        if job.get("result"):
            self.database.set_sticker_processing_status(job["result"].job_id, "Descartado")
        self.refresh_queue()
        self._select_next_review()

    def current_job(self):
        if self.current_index is None or self.current_index >= len(self.jobs):
            return None
        return self.jobs[self.current_index]

    def _select_next_review(self):
        next_index = next((i for i, job in enumerate(self.jobs) if job["status"] in {"Listo", "Revisar"}), None)
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

    def close(self):
        self.cancel_event.set()
        self.destroy()
