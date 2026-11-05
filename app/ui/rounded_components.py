"""Componentes visuales reutilizables sin lógica de negocio."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

from PIL import Image, ImageDraw, ImageTk

from app.ui.theme import COLORS, RADIUS, SEMANTIC_COLORS, SPACE, UI_FONT


class RoundedCard(tk.Frame):
    """Tarjeta redondeada para paneles de baja frecuencia.

    El contenido debe agregarse mediante ``card.content``. ``padding`` admite
    un entero o una tupla ``(horizontal, vertical)``.
    """

    def __init__(
        self,
        parent,
        *,
        background: str = SEMANTIC_COLORS.surface_elevated,
        outer_background: str | None = None,
        border_color: str = SEMANTIC_COLORS.border,
        border_width: int = 1,
        radius_px: int = RADIUS.medium_px,
        padding: int | tuple[int, int] = SPACE.sm,
        **kwargs,
    ):
        outer_background = outer_background or self._resolve_outer_background(parent)
        self._padding_x, self._padding_y = self._normalize_padding(padding)
        self._background = background
        self._border_color = border_color
        self._border_width = max(0, int(border_width))
        self._radius_px = max(0, int(radius_px))
        self._outer_background = outer_background
        self._layout_after_id: str | None = None
        self._last_requested_height: int | None = None
        self._last_content_width: int | None = None
        self._rounded_background_image = None
        self._rounded_background_item = None
        self._rounded_background_cache_key = None

        super().__init__(
            parent,
            background=outer_background,
            borderwidth=0,
            highlightthickness=0,
            **kwargs,
        )
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            self,
            width=1,
            height=1,
            background=outer_background,
            borderwidth=0,
            highlightthickness=0,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")

        self.content = tk.Frame(
            self.canvas,
            background=background,
            borderwidth=0,
            highlightthickness=0,
        )
        self._content_window = self.canvas.create_window(
            0,
            0,
            anchor="nw",
            window=self.content,
        )

        self.canvas.bind("<Configure>", self._schedule_layout, add="+")
        self.content.bind("<Configure>", self._schedule_layout, add="+")
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._schedule_layout()

    @staticmethod
    def _normalize_padding(padding: int | tuple[int, int]) -> tuple[int, int]:
        if isinstance(padding, int):
            value = max(0, padding)
            return value, value
        if len(padding) != 2:
            raise ValueError("padding debe ser un entero o una tupla (horizontal, vertical)")
        return max(0, int(padding[0])), max(0, int(padding[1]))

    @staticmethod
    def _resolve_outer_background(parent) -> str:
        try:
            value = parent.cget("background")
            if value:
                return str(value)
        except (AttributeError, tk.TclError):
            pass
        return SEMANTIC_COLORS.surface

    def _schedule_layout(self, _event=None):
        if self._layout_after_id is not None:
            return
        try:
            self._layout_after_id = self.after_idle(self._layout)
        except tk.TclError:
            self._layout_after_id = None

    def _on_destroy(self, event):
        if event.widget is not self:
            return
        if self._layout_after_id is not None:
            try:
                self.after_cancel(self._layout_after_id)
            except tk.TclError:
                pass
            self._layout_after_id = None

    def _layout(self):
        self._layout_after_id = None
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return

        required_height = (
            self.content.winfo_reqheight()
            + 2 * (self._padding_y + self._border_width)
        )
        if required_height != self._last_requested_height:
            self._last_requested_height = required_height
            self.canvas.configure(height=max(1, required_height))
            self.configure(height=max(1, required_height))

        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width < 1 or height < 1:
            return

        inset_x = self._padding_x + self._border_width
        inset_y = self._padding_y + self._border_width
        content_width = max(1, width - 2 * inset_x)
        self.canvas.coords(self._content_window, inset_x, inset_y)
        if content_width != self._last_content_width:
            self._last_content_width = content_width
            self.canvas.itemconfigure(
                self._content_window,
                width=content_width,
            )

        draw_x2 = max(0, width - 1)
        draw_y2 = max(0, height - 1)
        self._create_rounded_rectangle(0, 0, draw_x2, draw_y2)
        self.canvas.tag_lower("rounded_background", self._content_window)

    def _create_rounded_rectangle(self, x1: int, y1: int, x2: int, y2: int):
        width = max(1, x2 - x1 + 1)
        height = max(1, y2 - y1 + 1)
        cache_key = (
            width, height, self._radius_px, self._border_width,
            self._outer_background, self._background, self._border_color,
        )
        if cache_key == self._rounded_background_cache_key:
            return

        # Los arcos Canvas se unen con pequeños picos en ciertos escalados de
        # Windows. Dibujar a mayor resolución y reducir con LANCZOS elimina
        # esas uniones sin alterar el tamaño ni el layout de la tarjeta.
        scale = 4
        scaled_width, scaled_height = width * scale, height * scale
        radius = min(self._radius_px * scale, scaled_width // 2, scaled_height // 2)
        border = self._border_width * scale
        image = Image.new("RGBA", (scaled_width, scaled_height), self._outer_background)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (0, 0, scaled_width - 1, scaled_height - 1),
            radius=radius,
            fill=self._border_color if border else self._background,
        )
        if border and scaled_width > 2 * border and scaled_height > 2 * border:
            draw.rounded_rectangle(
                (border, border, scaled_width - border - 1, scaled_height - border - 1),
                radius=max(0, radius - border),
                fill=self._background,
            )
        image = image.resize((width, height), Image.Resampling.LANCZOS)
        self._rounded_background_image = ImageTk.PhotoImage(image, master=self.canvas)
        self._rounded_background_cache_key = cache_key
        self.canvas.delete("rounded_background")
        self._rounded_background_item = self.canvas.create_image(
            x1, y1, anchor="nw", image=self._rounded_background_image,
            tags="rounded_background",
        )
        self.canvas.tag_lower("rounded_background", self._content_window)

    def _draw_rounded_fill(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        radius: int,
        color: str,
    ):
        tags = ("rounded_background",)
        if radius <= 0:
            self.canvas.create_rectangle(
                x1, y1, x2, y2, fill=color, outline="", tags=tags,
            )
            return

        diameter = radius * 2
        self.canvas.create_rectangle(
            x1 + radius, y1, x2 - radius, y2,
            fill=color, outline="", tags=tags,
        )
        self.canvas.create_rectangle(
            x1, y1 + radius, x2, y2 - radius,
            fill=color, outline="", tags=tags,
        )
        for start, left, top in (
            (90, x1, y1),
            (0, x2 - diameter, y1),
            (270, x2 - diameter, y2 - diameter),
            (180, x1, y2 - diameter),
        ):
            self.canvas.create_arc(
                left,
                top,
                left + diameter,
                top + diameter,
                start=start,
                extent=90,
                fill=color,
                outline="",
                style="pieslice",
                tags=tags,
            )


class RoundedToolbar(RoundedCard):
    """Contenedor expansible para toolbars con una o dos filas."""

    def __init__(
        self,
        parent,
        *,
        background: str = SEMANTIC_COLORS.surface,
        outer_background: str | None = None,
        border_color: str = SEMANTIC_COLORS.border,
        border_width: int = 1,
        radius_px: int = 10,
        padding: int | tuple[int, int] = SPACE.xs,
        **kwargs,
    ):
        super().__init__(
            parent,
            background=background,
            outer_background=outer_background,
            border_color=border_color,
            border_width=border_width,
            radius_px=radius_px,
            padding=padding,
            **kwargs,
        )


class RoundedNavigationButton(tk.Canvas):
    """Botón Canvas de navegación con radio real y contrato básico de tk.Button."""

    def __init__(
        self,
        parent,
        *,
        text,
        command,
        state="normal",
        radius_px: int = RADIUS.medium_px,
        padx: int = 14,
        pady: int = 9,
        **kwargs,
    ):
        self._text = text
        self._command = command
        self._state = state
        self._active = False
        self._hovered = False
        self._mouse_pressed = False
        self._keyboard_pressed = False
        self._focus_visible = False
        self._suppress_next_focus_ring = False
        self._radius_px = max(0, int(radius_px))
        self._padx = padx
        self._background_image = None
        self._background_image_item = None
        self._background_cache_key = None
        self._font = tkfont.Font(
            root=parent,
            family=UI_FONT,
            size=10,
            weight="bold",
        )
        self._cursor = kwargs.pop("cursor", "hand2")
        self._canvas_ready = False
        native_height = self._measure_native_reqheight(
            parent,
            text=text,
            padx=padx,
            pady=pady,
        )

        super().__init__(
            parent,
            background=COLORS.background_secondary,
            borderwidth=0,
            cursor=self._cursor if state == "normal" else "",
            height=native_height,
            highlightthickness=0,
            takefocus=1 if state == "normal" else 0,
            **kwargs,
        )
        self._canvas_ready = True
        self.bind("<Configure>", self._on_configure, add="+")
        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")
        self.bind("<ButtonPress-1>", self._on_press, add="+")
        self.bind("<ButtonRelease-1>", self._on_release, add="+")
        self.bind("<FocusIn>", self._on_focus_in, add="+")
        self.bind("<FocusOut>", self._on_focus_out, add="+")
        self.bind("<KeyPress-space>", self._on_key_press_space, add="+")
        self.bind("<KeyRelease-space>", self._on_key_release_space, add="+")
        self._redraw()

    @staticmethod
    def _measure_native_reqheight(parent, *, text, padx, pady) -> int:
        probe = tk.Button(
            parent,
            text=text,
            anchor="w",
            justify="left",
            borderwidth=0,
            relief="flat",
            highlightthickness=0,
            padx=padx,
            pady=pady,
            font=(UI_FONT, 10, "bold"),
        )
        try:
            return probe.winfo_reqheight()
        finally:
            probe.destroy()

    def configure(self, cnf=None, **kwargs):
        if cnf is None and not kwargs:
            return super().configure()
        if isinstance(cnf, str):
            return super().configure(cnf, **kwargs)
        if cnf is not None and not isinstance(cnf, dict):
            return super().configure(cnf, **kwargs)

        options = dict(cnf or {})
        options.update(kwargs)
        if "text" in options:
            self._text = options.pop("text")
        if "command" in options:
            self._command = options.pop("command")
        if "state" in options:
            self._state = options.pop("state")
            if self._state != "normal":
                self._keyboard_pressed = False
                self._mouse_pressed = False
                self._hovered = False
                self._focus_visible = False
                self._suppress_next_focus_ring = False
                self._release_mouse_grab()
        if "cursor" in options:
            self._cursor = options.pop("cursor")
        if options:
            result = super().configure(**options)
        else:
            result = None

        if self._canvas_ready:
            super().configure(
                cursor=self._cursor if self._state == "normal" else "",
                takefocus=1 if self._state == "normal" else 0,
            )
            self._redraw()
        return result

    config = configure

    def cget(self, key):
        if key == "text":
            return self._text
        if key == "command":
            return self._command
        if key == "state":
            return self._state
        return super().cget(key)

    def invoke(self):
        if self._state == "normal" and self._command is not None:
            return self._command()
        return None

    def _release_mouse_grab(self) -> None:
        try:
            if self.grab_current() is self:
                self.grab_release()
        except tk.TclError:
            pass

    def set_active(self, active: bool) -> None:
        self._active = active
        self._redraw()

    def _is_visually_pressed(self) -> bool:
        return self._keyboard_pressed or (
            self._mouse_pressed and self._hovered
        )

    def _on_configure(self, _event=None):
        self._redraw()

    def _on_enter(self, _event=None):
        if self._state == "normal":
            self._hovered = True
            self._redraw()

    def _on_leave(self, _event=None):
        self._hovered = False
        self._redraw()

    def _on_press(self, _event=None):
        if self._state != "normal" or self._keyboard_pressed:
            return
        self._focus_visible = False
        self._suppress_next_focus_ring = True
        self.focus_set()
        self._mouse_pressed = True
        self._hovered = True
        self.grab_set()
        self._redraw()

    def _on_release(self, event):
        had_mouse_press = self._mouse_pressed
        released_inside = (
            0 <= event.x < self.winfo_width()
            and 0 <= event.y < self.winfo_height()
        )
        self._mouse_pressed = False
        self._release_mouse_grab()
        self._redraw()
        if (
            had_mouse_press
            and self._state == "normal"
            and released_inside
            and not self._keyboard_pressed
        ):
            self.invoke()

    def _on_focus_in(self, _event=None):
        if self._suppress_next_focus_ring:
            self._focus_visible = False
            self._suppress_next_focus_ring = False
        else:
            self._focus_visible = True
        self._redraw()

    def _on_focus_out(self, _event=None):
        self._keyboard_pressed = False
        self._mouse_pressed = False
        self._focus_visible = False
        self._suppress_next_focus_ring = False
        self._release_mouse_grab()
        self._redraw()

    def _on_key_press_space(self, _event=None):
        if self._state != "normal":
            return "break"
        if self._keyboard_pressed or self._mouse_pressed:
            return "break"
        self._keyboard_pressed = True
        self._redraw()
        return "break"

    def _on_key_release_space(self, _event=None):
        was_keyboard_pressed = self._keyboard_pressed
        self._keyboard_pressed = False
        should_invoke = (
            was_keyboard_pressed
            and self._state == "normal"
            and self.focus_displayof() is self
        )
        self._redraw()
        if should_invoke:
            self.invoke()
        return "break"

    def _update_background_image(
        self,
        width: int,
        height: int,
        fill: str,
        border: str,
    ) -> None:
        cache_key = (
            width,
            height,
            self._radius_px,
            fill,
            border,
            COLORS.background_secondary,
        )
        if cache_key == self._background_cache_key:
            return

        scale = 4
        scaled_width = width * scale
        scaled_height = height * scale
        scaled_radius = min(
            self._radius_px * scale,
            scaled_width // 2,
            scaled_height // 2,
        )
        image = Image.new(
            "RGBA",
            (scaled_width, scaled_height),
            COLORS.background_secondary,
        )
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (0, 0, scaled_width - 1, scaled_height - 1),
            radius=scaled_radius,
            fill=border,
        )
        inset = scale
        if scaled_width > 2 * inset and scaled_height > 2 * inset:
            draw.rounded_rectangle(
                (
                    inset,
                    inset,
                    scaled_width - inset - 1,
                    scaled_height - inset - 1,
                ),
                radius=max(0, scaled_radius - inset),
                fill=fill,
            )

        image = image.resize(
            (width, height),
            Image.Resampling.LANCZOS,
        )
        self._background_image = ImageTk.PhotoImage(image, master=self)
        self._background_cache_key = cache_key
        if self._background_image_item is None:
            self._background_image_item = self.create_image(
                0,
                0,
                anchor="nw",
                image=self._background_image,
                tags="navigation_background",
            )
        else:
            self.itemconfigure(
                self._background_image_item,
                image=self._background_image,
            )
        self.tag_lower("navigation_background")

    def _redraw(self):
        width = self.winfo_width()
        height = self.winfo_height()
        if width < 1 or height < 1:
            return

        pressed = self._is_visually_pressed()
        if self._state != "normal":
            fill = COLORS.background_secondary
            foreground = COLORS.disabled
            border = COLORS.background_secondary
        elif self._active and pressed:
            fill = COLORS.wine_dark
            foreground = COLORS.text
            border = COLORS.wine_active
        elif self._active:
            fill = COLORS.wine
            foreground = COLORS.text
            border = COLORS.wine_active
        elif pressed:
            fill = COLORS.background
            foreground = COLORS.text
            border = COLORS.border
        elif self._hovered:
            fill = COLORS.panel_elevated
            foreground = COLORS.text
            border = COLORS.border
        else:
            fill = COLORS.background_secondary
            foreground = COLORS.muted
            border = COLORS.background_secondary

        if (
            self._focus_visible
            and self.focus_displayof() is self
            and self._state == "normal"
        ):
            border = COLORS.primary_active

        self._update_background_image(width, height, fill, border)
        self.delete("navigation_text")
        self.create_text(
            self._padx,
            height // 2,
            anchor="w",
            fill=foreground,
            font=self._font,
            text=self._text,
            tags="navigation_text",
        )
