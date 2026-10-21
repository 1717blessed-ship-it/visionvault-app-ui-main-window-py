"""Canvas interactivo de previsualización, aislado de la salida final."""

from __future__ import annotations

import tkinter as tk
from collections import OrderedDict
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

from app.ui.theme import COLORS, UI_FONT
from .adapter import PipelineViewAdapter
from .state import CanvasState
from app.stickers.mask_contraction import offset_alpha_signed_distance


class StickerCanvas(ttk.Frame):
    def __init__(self, master, on_stroke=None, brush_provider=None):
        super().__init__(master, style="Card.TFrame")
        self.canvas = tk.Canvas(self, background=COLORS.canvas, highlightthickness=0,
                                cursor="crosshair", takefocus=True)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self.render())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda e: self._wheel(e, 1))
        self.canvas.bind("<Button-5>", lambda e: self._wheel(e, -1))
        self.canvas.bind("<ButtonPress-2>", self._pan_start)
        self.canvas.bind("<B2-Motion>", self._pan_move)
        self.canvas.bind("<ButtonRelease-2>", self._pan_end)
        self.canvas.bind("<ButtonPress-1>", self._primary_start)
        self.canvas.bind("<B1-Motion>", self._primary_move)
        self.canvas.bind("<ButtonRelease-1>", self._primary_end)
        self.canvas.bind("<Double-Button-1>", self._double_click)
        self.canvas.bind("<KeyPress-space>", self._space_down)
        self.canvas.bind("<KeyRelease-space>", self._space_up)
        self._job: dict | None = None
        self._state = CanvasState()
        self._photo = None
        self._image_cache: OrderedDict[tuple[str, int, bool], Image.Image] = OrderedDict()
        self._image_cache_bytes = 0
        self._image_cache_limit = 192 * 1024 * 1024
        self._render_after = None
        self._image_item = None
        self._image_item_offset = (0.0, 0.0)
        self._background_mode = "Damero"
        self._compare_split = .5
        self._drag_origin = (0, 0, 0.0, 0.0)
        self._on_stroke = on_stroke
        self._brush_provider = brush_provider
        self._edit_tool = None
        self._stroke_points = []
        self._display_geometry = None
        self._space_panning = False

    def set_edit_tool(self, tool: str | None):
        self._edit_tool = tool
        self.canvas.configure(cursor="pencil" if tool else "crosshair")

    def show_job(self, job: dict | None, state: CanvasState) -> None:
        self._job, self._state = job, state
        self.render()

    def fit(self) -> None:
        self._state.fitted = True
        self._state.pan_x = self._state.pan_y = 0
        self.render()

    def actual_size(self) -> None:
        self._state.fitted = False
        self._state.zoom = 1.0
        self.center()

    def center(self) -> None:
        self._state.pan_x = self._state.pan_y = 0
        self.render()

    def set_mode(self, mode: str) -> None:
        self._state.mode = mode
        self.render()

    def toggle_cut(self, enabled: bool) -> None:
        self._state.show_cut = bool(enabled)
        self.render()

    def toggle_compare(self, enabled: bool) -> None:
        self._state.compare = bool(enabled)
        self.render()

    def set_background(self, mode: str) -> None:
        self._background_mode = mode
        self.render()

    def set_compare_split(self, percent: float) -> None:
        self._compare_split = max(0.0, min(1.0, float(percent) / 100.0))
        if self._state.compare:
            self.render()

    def _load(self, path: str, grayscale=False) -> Image.Image:
        stamp = Path(path).stat().st_mtime_ns
        key = (str(path), stamp, bool(grayscale))
        image = self._image_cache.get(key)
        if image is None:
            with Image.open(path) as source:
                image = source.convert("L" if grayscale else "RGBA").copy()
            estimated = image.width * image.height * (1 if grayscale else 4)
            self._image_cache[key] = image
            self._image_cache_bytes += estimated
            while self._image_cache_bytes > self._image_cache_limit and len(self._image_cache) > 1:
                _old_key, old = self._image_cache.popitem(last=False)
                self._image_cache_bytes -= old.width * old.height * (1 if old.mode == "L" else 4)
        else:
            self._image_cache.move_to_end(key)
        return image.copy()

    @staticmethod
    def _checker(size: tuple[int, int], cell=12) -> Image.Image:
        out = Image.new("RGBA", size, (232, 232, 232, 255))
        draw = ImageDraw.Draw(out)
        for y in range(0, size[1], cell):
            for x in range(0, size[0], cell):
                if (x // cell + y // cell) % 2:
                    draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=(195, 195, 195, 255))
        return out

    def _background(self, size: tuple[int, int]) -> Image.Image:
        colors = {
            "Blanco": (255, 255, 255, 255), "Negro": (0, 0, 0, 255),
            "Gris": (128, 128, 128, 255), "Magenta": (255, 0, 180, 255),
        }
        return (Image.new("RGBA", size, colors[self._background_mode])
                if self._background_mode in colors else self._checker(size))

    @staticmethod
    def preview_adds_border(job: dict) -> bool:
        treatment = job.get("border_treatment") or "Automático"
        if treatment == "Automático":
            result = job.get("result")
            analysis = getattr(result, "analysis", {}) if result else {}
            treatment = (analysis.get("border_treatment") or {}).get("effective", "Automático")
        return treatment in {"Reemplazar", "Agregar nuevo"}

    def _compose(self) -> Image.Image | None:
        if not self._job:
            return None
        # Final siempre representa el master real que también se exporta.
        # Las guías no aplicadas sólo se componen en Máscara/Resultado.
        if self._job.get("v2_preview_active") and self._state.mode != "Final":
            preview = self._compose_contraction_preview()
            if preview is not None:
                return preview
        source = PipelineViewAdapter.preview_source(self._job, self._state.mode)
        if not source.path:
            return None
        if self._state.mode == "Máscara":
            mask = self._load(source.path, grayscale=True)
            image = Image.new("RGBA", mask.size, (255, 255, 255, 255))
            image.putalpha(mask)
        else:
            image = self._load(source.path)
        board = self._background(image.size)
        board.alpha_composite(image)
        image = board
        if self._state.compare:
            original_path = PipelineViewAdapter.preview_source(self._job, "Original").path
            if original_path:
                original = self._load(original_path)
                original.thumbnail(image.size, Image.Resampling.LANCZOS)
                left = self._background(image.size)
                left.alpha_composite(original, ((image.width-original.width)//2, (image.height-original.height)//2))
                split = round(image.width * self._compare_split)
                left.paste(image.crop((split, 0, image.width, image.height)), (split, 0))
                ImageDraw.Draw(left).line((split, 0, split, image.height), fill=(255, 62, 111, 255), width=2)
                image = left
        if self._state.show_cut and source.cut_path and Path(source.cut_path).exists():
            cut = self._load(source.cut_path, grayscale=True).resize(image.size, Image.Resampling.NEAREST)
            # Un borde rojo de un píxel en coordenadas de origen hace visible
            # el troquel sin modificar el artefacto real.
            from PIL import ImageFilter
            edge = cut.filter(ImageFilter.FIND_EDGES).point(lambda value: 255 if value > 24 else 0)
            overlay = Image.new("RGBA", image.size, (255, 35, 70, 0))
            overlay.putalpha(edge)
            image.alpha_composite(overlay)
        return image

    def _compose_contraction_preview(self):
        artifacts = PipelineViewAdapter.artifacts(self._job)
        source_path = artifacts.get("source_editable") or self._job.get("source_path")
        mask_path = (artifacts.get("selection_alpha_original")
                     or artifacts.get("border_treatment_alpha")
                     or artifacts.get("mask_editable") or artifacts.get("mask"))
        if not source_path or not mask_path or not Path(source_path).exists() or not Path(mask_path).exists():
            return None
        source = self._load(source_path)
        original = self._load(mask_path, grayscale=True)
        document = self._job.get("v2_mask_document")
        edit_base_path = self._job.get("v2_mask_base_path")
        if document is not None and edit_base_path and Path(edit_base_path).exists():
            original = self._load(edit_base_path, grayscale=True)
        if original.size != source.size:
            return None
        contracted = self._job.get("v2_preview_mask_image")
        protection = self._job.get("v2_preview_protection_image")
        if contracted is None:
            return None
        design = source.copy()
        design.putalpha(contracted)
        # Conservar significa que el blanco existente forma parte del diseño;
        # nunca se dilata otra capa encima durante la vista previa.
        adds_border = self.preview_adds_border(self._job)
        border_mm = float(self._job.get("v2_preview_border_mm", 0.0)) if adds_border else 0.0
        if border_mm > 0:
            import cv2
            import numpy as np
            result = self._job.get("result")
            dpi = float(getattr(result, "analysis", {}).get("source_processing_dpi") or 300)
            pixels = max(0, round(border_mm * dpi / 25.4))
            data = np.asarray(contracted, dtype=np.uint8)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (pixels*2+1, pixels*2+1))
            base = Image.fromarray(cv2.dilate(data, kernel), mode="L")
            composed = Image.new("RGBA", source.size, "white")
            composed.putalpha(base)
            composed.alpha_composite(design)
            design = composed
        board = self._background(source.size)
        board.alpha_composite(design)
        show = self._job.get("v2_selection_view", "Ambas")
        from PIL import ImageFilter, ImageChops
        if show in {"Ambas", "Original"}:
            edge = original.filter(ImageFilter.FIND_EDGES).point(lambda v: 220 if v > 24 else 0)
            cyan = Image.new("RGBA", source.size, (0, 220, 255, 0)); cyan.putalpha(edge)
            board.alpha_composite(cyan)
        if show in {"Ambas", "Contraída"}:
            edge = contracted.filter(ImageFilter.FIND_EDGES).point(lambda v: 235 if v > 24 else 0)
            magenta = Image.new("RGBA", source.size, (255, 40, 130, 0)); magenta.putalpha(edge)
            board.alpha_composite(magenta)
        if protection is not None:
            protected = protection.point(lambda v: 150 if v > 8 else 0)
            green = Image.new("RGBA", source.size, (50, 255, 120, 0)); green.putalpha(protected)
            board.alpha_composite(green)
        return board

    def render(self) -> None:
        self.canvas.delete("all")
        self._image_item = None
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        image = self._compose()
        if image is None:
            self.canvas.create_text(width/2, height/2, text="Importá una imagen para comenzar",
                                    fill=COLORS.muted, font=(UI_FONT, 12))
            return
        fit = min((width-48)/image.width, (height-48)/image.height)
        if self._state.fitted:
            self._state.zoom = max(.05, fit)
        scale = self._state.zoom
        display_size = (max(1, round(image.width*scale)), max(1, round(image.height*scale)))
        x = width/2 + self._state.pan_x
        y = height/2 + self._state.pan_y
        # A zoom alto sólo se interpola la región visible. Las coordenadas del
        # documento siguen referidas al raster completo para que pinceles y pan
        # conserven precisión 1:1.
        margin = 3
        left = max(0, int((0 - (x-display_size[0]/2)) / scale) - margin)
        top = max(0, int((0 - (y-display_size[1]/2)) / scale) - margin)
        right = min(image.width, int((width - (x-display_size[0]/2)) / scale) + margin + 1)
        bottom = min(image.height, int((height - (y-display_size[1]/2)) / scale) + margin + 1)
        if right <= left or bottom <= top:
            self._display_geometry = (x, y, display_size[0], display_size[1], image.width, image.height)
            return
        crop = image.crop((left, top, right, bottom))
        crop_size = (max(1, round(crop.width*scale)), max(1, round(crop.height*scale)))
        display = crop.resize(crop_size, Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(display)
        self._display_geometry = (x, y, display_size[0], display_size[1], image.width, image.height)
        crop_x = x + ((left + right)/2 - image.width/2) * scale
        crop_y = y + ((top + bottom)/2 - image.height/2) * scale
        self._image_item_offset = (crop_x - x, crop_y - y)
        self._image_item = self.canvas.create_image(crop_x, crop_y, image=self._photo, anchor="center")
        self.canvas.create_text(12, 12, anchor="nw", text=f"{self._state.mode}  ·  {scale*100:.0f}%",
                                fill=COLORS.text, font=(UI_FONT, 9, "bold"))

    def _wheel(self, event, linux_delta=None):
        delta = linux_delta if linux_delta is not None else (1 if event.delta > 0 else -1)
        before = self._state.zoom
        after = self._state.set_zoom(before * (1.12 if delta > 0 else 1/1.12))
        cx, cy = self.canvas.winfo_width()/2, self.canvas.winfo_height()/2
        # Conserva bajo el cursor el mismo punto de la imagen.
        ratio = after / before if before else 1
        self._state.pan_x = event.x - cx - (event.x - cx - self._state.pan_x) * ratio
        self._state.pan_y = event.y - cy - (event.y - cy - self._state.pan_y) * ratio
        self._schedule_render()
        return "break"

    def _schedule_render(self):
        if self._render_after is None:
            self._render_after = self.after(16, self._render_scheduled)

    def _render_scheduled(self):
        self._render_after = None
        self.render()

    def _pan_start(self, event):
        self._drag_origin = (event.x, event.y, self._state.pan_x, self._state.pan_y)

    def _pan_move(self, event):
        x, y, ox, oy = self._drag_origin
        self._state.fitted = False
        self._state.pan_x, self._state.pan_y = ox + event.x-x, oy + event.y-y
        if self._image_item is not None:
            cx, cy = self.canvas.winfo_width()/2, self.canvas.winfo_height()/2
            dx, dy = self._image_item_offset
            self.canvas.coords(self._image_item, cx + self._state.pan_x + dx, cy + self._state.pan_y + dy)
            if self._display_geometry:
                _x, _y, dw, dh, iw, ih = self._display_geometry
                self._display_geometry = (cx + self._state.pan_x, cy + self._state.pan_y, dw, dh, iw, ih)

    def _pan_end(self, _event=None):
        self._schedule_render()

    def _double_click(self, _event=None):
        if self._edit_tool:
            return None
        if self._state.fitted:
            self.actual_size()
        else:
            self.fit()
        return "break"

    def _image_point(self, event):
        if not self._display_geometry:
            return None
        cx, cy, dw, dh, iw, ih = self._display_geometry
        x = (event.x - (cx - dw/2)) * iw / dw
        y = (event.y - (cy - dh/2)) * ih / dh
        if not (0 <= x < iw and 0 <= y < ih):
            return None
        return (x, y)

    def _primary_start(self, event):
        self.canvas.focus_set()
        if not self._edit_tool or self._space_panning:
            return self._pan_start(event)
        point = self._image_point(event)
        self._stroke_points = [point] if point else []

    def _primary_move(self, event):
        if not self._edit_tool or self._space_panning:
            return self._pan_move(event)
        point = self._image_point(event)
        if point:
            self._stroke_points.append(point)

    def _primary_end(self, event):
        if self._space_panning or not self._edit_tool:
            self._pan_end(event)
            return
        if not self._stroke_points or not self._on_stroke:
            return
        point = self._image_point(event)
        if point and point != self._stroke_points[-1]:
            self._stroke_points.append(point)
        settings = self._brush_provider() if self._brush_provider else {}
        self._on_stroke(self._edit_tool, tuple(self._stroke_points), settings)
        self._stroke_points = []

    def _space_down(self, _event=None):
        self._space_panning = True
        self.canvas.configure(cursor="fleur")
        return "break"

    def _space_up(self, _event=None):
        self._space_panning = False
        self.canvas.configure(cursor="pencil" if self._edit_tool else "crosshair")
        return "break"
