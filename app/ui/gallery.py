import tkinter as tk
import unicodedata
from collections import deque
from tkinter import ttk

from app.indexer.thumbnails import load_thumbnail
from app.ui.theme import COLORS, IDENTITY_FONT, UI_FONT, configure_menu

# Umbral en píxeles: si el arrastre no supera esta distancia se trata como
# un clic simple (deseleccionar todo) en lugar de un rubber-band.
_DRAG_THRESHOLD = 5


class Gallery(ttk.Frame):
    """Biblioteca visual con vistas, tamaños de miniatura y arrastre."""

    SIZES = {0: (66, 52), 1: (100, 78), 2: (150, 118)}
    MAX_ROWS = 10
    FIXED_COLUMNS = 10
    TILE_SIZE = 72
    TILE_GAP = 6
    VIEW_LABELS = {
        "list": "☷  Lista",
        "grid": "▦  Cuadrícula",
        "vertical": "▥  Mosaico vertical",
        "horizontal": "▤  Mosaico horizontal",
    }

    def __init__(self, master, on_preview, on_add_tag, on_remove_tag, on_capacity_change,
                 on_toggle_selection=None, is_selected=None, drag_paths=None, on_trash=None,
                 responsive_columns: bool = False):
        super().__init__(master, padding=(12, 0, 12, 12))
        self.on_preview = on_preview
        self.on_add_tag = on_add_tag
        self.on_remove_tag = on_remove_tag
        self.on_capacity_change = on_capacity_change
        self.on_toggle_selection = on_toggle_selection
        self.is_selected = is_selected or (lambda _image: False)
        self.on_trash = on_trash
        self.drag_paths = drag_paths or (lambda image: [image["path"]])
        self.responsive_columns = bool(responsive_columns)
        self.layout = tk.StringVar(value="grid")
        self.thumbnail_scale = tk.IntVar(value=0)
        # El usuario elige cuántos diseños revisar. Las columnas permanecen
        # estables para mantener una biblioteca visual ordenada.
        self.display_limit = 100
        self.current_items: list[dict] = []
        self.images = []
        self.context_image = None
        self.tag_hint = None
        self._last_render_signature: tuple[tuple[str, object, object, object, object], ...] | None = None
        self._last_capacity = None
        self._last_render_width = 0
        self._resize_render_pending = False
        self.cards_by_path = {}
        self.selection_outlines = {}
        self.card_backgrounds = {}
        self.render_generation = 0
        self.thumbnail_queue = deque()
        self.search_context = ""
        # Imagen bajo el cursor (para selección con Ctrl sin clic)
        self._hovered_image: dict | None = None
        # Estado del rubber-band (selección por área)
        self._band_start: tuple[int, int] | None = None
        self._band_rect: int | None = None
        self._band_dragging: bool = False

        self.canvas = tk.Canvas(self, highlightthickness=0, background=COLORS.background)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=lambda *a, _fn=self.canvas.yview: _fn(*a))
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.bind("<Configure>", self.on_canvas_resize)
        self.canvas.bind("<MouseWheel>", self.scroll_with_wheel)
        self.canvas.bind("<KeyPress>", self._on_key_press)
        self.content = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.content.bind("<MouseWheel>", self.scroll_with_wheel)
        # Rubber-band: se activa sobre self.content (donde caen los clics
        # en el espacio vacío entre tarjetas). Las tarjetas absorben sus
        # propio clicks con "break" para no interferir.
        self.content.bind("<ButtonPress-1>", self._band_press)
        self.content.bind("<B1-Motion>", self._band_motion)
        self.content.bind("<ButtonRelease-1>", self._band_release)
        # Fallback: si el mouse se suelta fuera del content, limpiar el rectángulo.
        self.canvas.bind("<ButtonRelease-1>", self._band_release)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.menu = tk.Menu(self, tearoff=0)
        configure_menu(self.menu)
        self.menu.add_command(label="Vista previa", command=lambda: self.on_preview(self.context_image))
        self.menu.add_command(label="Agregar etiqueta", command=lambda: self.on_add_tag(self.context_image))
    def grid_columns(self) -> int:
        """Columnas que caben en el área visible, sin dejar huecos a la derecha."""
        if self.responsive_columns:
            width = self.canvas.winfo_width()
            if width <= 1:
                width = 780
            return max(1, min(self.FIXED_COLUMNS, width // (self.TILE_SIZE + self.TILE_GAP)))
        return self.FIXED_COLUMNS

    def display_capacity(self) -> int:
        return self.display_limit

    def set_display_limit(self, limit: int) -> None:
        """Actualiza el máximo visible sin regenerar miniaturas por sí solo."""
        try:
            self.display_limit = max(1, int(limit))
        except (TypeError, ValueError):
            return
        self.notify_capacity_change()

    def tile_dimension(self) -> int:
        """Reparte el ancho completo entre las columnas visibles."""
        width = self.canvas.winfo_width()
        if width <= 1:
            width = 780
        columns = self.grid_columns()
        return max(self.TILE_SIZE, (width - self.TILE_GAP * (columns - 1)) // columns)

    def on_canvas_resize(self, _event):
        self.notify_capacity_change()
        width = self.canvas.winfo_width()
        if self.current_items and width > 1 and width != self._last_render_width and not self._resize_render_pending:
            self._last_render_width = width
            self._resize_render_pending = True
            self.after_idle(self.render_after_resize)

    def render_after_resize(self):
        """Solo redimensiona las tarjetas: no consulta ni cambia los diseños."""
        self._resize_render_pending = False
        self.render()

    def notify_capacity_change(self):
        capacity = self.display_capacity()
        if capacity != self._last_capacity:
            self._last_capacity = capacity
            self.after_idle(self.on_capacity_change)

    @staticmethod
    def render_signature(images: list[dict]) -> tuple[tuple[str, object, object, object, object], ...]:
        return tuple(
            (
                str(item.get("path", "")),
                item.get("modified"),
                item.get("tags"),
                item.get("visual_match_score"),
                item.get("caption"),
            )
            for item in images
        )

    def show_images(self, images: list[dict]) -> None:
        signature = self.render_signature(images)
        if signature == self._last_render_signature:
            return
        self._last_render_signature = signature
        self.current_items = images
        self.render()

    def set_search_context(self, query: str) -> None:
        """Conserva el término para explicar por qué apareció cada tarjeta."""
        self.search_context = str(query or "").strip()

    @staticmethod
    def _plain(value: object) -> str:
        return "".join(
            char for char in unicodedata.normalize("NFKD", str(value or "").casefold())
            if not unicodedata.combining(char)
        )

    def match_reason(self, item: dict) -> str:
        tokens = [token for token in self._plain(self.search_context).split() if token]
        if not tokens:
            return ""
        fields = (("Etiqueta", item.get("tags")), ("Categoría", item.get("category")),
                  ("Nombre", item.get("caption")), ("Cliente", item.get("design_client")),
                  ("Texto detectado", item.get("recognized_text")))
        for label, value in fields:
            text = self._plain(value)
            if text and all(token in text for token in tokens):
                return f"Por {label.lower()}"
        return ""

    def render(self):
        self.render_generation += 1
        generation = self.render_generation
        for widget in self.content.winfo_children():
            widget.destroy()
        self.images = []
        self.cards_by_path = {}
        self.selection_outlines = {}
        self.card_backgrounds = {}
        if not self.current_items:
            ttk.Label(self.content, text="No hay diseños para mostrar.", padding=20).grid(row=0, column=0)
            return
        tile_size = self.tile_dimension()
        self.thumbnail_queue = deque()
        for index, item in enumerate(self.current_items):
            row, column, sticky = self.position_for(index)
            selected = self.is_selected(item)
            card = tk.Canvas(self.content, width=tile_size, height=tile_size, background=COLORS.background, highlightthickness=0)
            card.grid(row=row, column=column, padx=3, pady=3, sticky=sticky)
            self.card_backgrounds[item["path"]] = self.rounded_rect(card, 1, 1, tile_size - 1, tile_size - 1, 10, fill=COLORS.wine_soft if selected else COLORS.panel)
            self.cards_by_path[item["path"]] = card
            placeholder = card.create_text(tile_size // 2, tile_size // 2, text="Cargando…", fill=COLORS.muted, width=tile_size - 8)
            self.thumbnail_queue.append((card, item, tile_size, placeholder, self.match_reason(item)))
            score = item.get("visual_match_score")
            if score is not None:
                score = float(score)
                if score >= 99.95:
                    label, color = "Exacta", "#168d4d"
                elif score >= 88:
                    label, color = "Muy alta", "#1677aa"
                elif score >= 76:
                    label, color = "Probable", "#a96b00"
                else:
                    label, color = "Baja", "#6d6f72"
                badge_width = min(tile_size - 10, 82)
                card.create_rectangle(5, tile_size - 27, 5 + badge_width, tile_size - 5, fill=color, outline="")
                card.create_text(5 + badge_width // 2, tile_size - 16, text=f"{score:.0f}% · {label}", fill=COLORS.text, font=(UI_FONT, 8, "bold"))
            tags = item.get("tags") or ""
            card.bind("<Button-3>", lambda event, current=item: self.show_context(event, current))
            card.bind("<MouseWheel>", self.scroll_with_wheel)
            card.bind("<Double-Button-1>", lambda _event, current=item: self.on_preview(current))
            # Ctrl + clic alterna la tarjeta sin abrir la ficha: es la forma
            # habitual de armar una selección múltiple en Windows. El clic
            # normal sigue reservado para arrastrar y el doble clic para ver.
            card.bind("<ButtonPress-1>", lambda event, current=item: self._on_card_click(event, current))
            card.bind("<Enter>", lambda event, current=item, text=tags: self._on_card_enter(event, current, text))
            card.bind("<Leave>", lambda _event: self._on_card_leave())
            if selected:
                self.set_selection_visual(item["path"], True)
            self._register_drag(card, item)
        # Las tarjetas aparecen enseguida; las miniaturas se cargan luego en
        # tandas cortas para que el inicio y el scroll no se congelen.
        self.after_idle(lambda: self.load_thumbnail_batch(generation))

    def scroll_with_wheel(self, event):
        """Permite recorrer la biblioteca con la rueda aun sobre una tarjeta."""
        delta = int(-event.delta / 120) if event.delta else 0
        if delta:
            self.canvas.yview_scroll(delta, "units")
        return "break"

    # ------------------------------------------------------------------
    # Selección por área (rubber-band)
    # ------------------------------------------------------------------

    def _band_coords(self, event) -> tuple[float, float]:
        """Convierte coordenadas del evento a coordenadas lógicas del canvas."""
        canvas_x = self.canvas.canvasx(event.x_root - self.canvas.winfo_rootx())
        canvas_y = self.canvas.canvasy(event.y_root - self.canvas.winfo_rooty())
        return canvas_x, canvas_y

    def _band_press(self, event):
        """Registra el punto de inicio del rubber-band en coordenadas del canvas."""
        self._band_start = self._band_coords(event)
        self._band_dragging = False
        if self._band_rect is not None:
            self.canvas.delete(self._band_rect)
            self._band_rect = None

    def _band_motion(self, event):
        """Actualiza el rectángulo de selección mientras se arrastra."""
        if self._band_start is None:
            return
        cx, cy = self._band_coords(event)
        x0, y0 = self._band_start
        # Activar solo si se supera el umbral para no interferir con clics normales.
        if not self._band_dragging:
            if abs(cx - x0) < _DRAG_THRESHOLD and abs(cy - y0) < _DRAG_THRESHOLD:
                return
            self._band_dragging = True
        if self._band_rect is None:
            self._band_rect = self.canvas.create_rectangle(
                x0, y0, cx, cy,
                outline=COLORS.wine_active, fill=COLORS.wine_soft,
                width=1, stipple="gray25",
            )
        else:
            # Conservar el mismo objeto evita borrar/crear elementos Tcl por
            # cada píxel recorrido durante la selección múltiple.
            self.canvas.coords(self._band_rect, x0, y0, cx, cy)

    def _band_release(self, event):
        """Al soltar: selecciona las tarjetas contenidas en el rectángulo."""
        if self._band_rect is not None:
            self.canvas.delete(self._band_rect)
            self._band_rect = None

        if self._band_start is None:
            return

        cx, cy = self._band_coords(event)
        x0, y0 = self._band_start
        self._band_start = None

        if not self._band_dragging:
            # Clic simple sobre el fondo → deseleccionar todo.
            if self.on_toggle_selection is not None:
                self._clear_all_selections()
            return

        self._band_dragging = False

        if self.on_toggle_selection is None:
            return

        # Normalizar el rectángulo de selección.
        rx1, ry1 = min(x0, cx), min(y0, cy)
        rx2, ry2 = max(x0, cx), max(y0, cy)

        # Obtener el desplazamiento del frame de contenido dentro del canvas.
        content_x = self.content.winfo_x()
        content_y = self.content.winfo_y()

        hit_paths: list[str] = []
        for path, card in self.cards_by_path.items():
            if not card.winfo_exists():
                continue
            # Posición de la tarjeta en coordenadas del canvas (incluyendo scroll).
            cx_card = content_x + card.winfo_x()
            cy_card = content_y + card.winfo_y()
            cw = card.winfo_width()
            ch = card.winfo_height()
            # Basta con que haya intersección (no se requiere contener completo).
            if cx_card < rx2 and cx_card + cw > rx1 and cy_card < ry2 and cy_card + ch > ry1:
                hit_paths.append(path)

        if not hit_paths:
            return

        # Seleccionar todas las tarjetas tocadas por el rectángulo.
        for item in self.current_items:
            if item["path"] in hit_paths:
                if not self.is_selected(item):
                    self.on_toggle_selection(item)
                self.set_selection_visual(item["path"], True)

    def _clear_all_selections(self):
        """Deselecciona todos los diseños actualmente marcados."""
        for item in list(self.current_items):
            if self.is_selected(item):
                self.on_toggle_selection(item)
                self.set_selection_visual(item["path"], False)

    def load_thumbnail_batch(self, generation: int):
        if generation != self.render_generation:
            return
        for _ in range(10):
            if not self.thumbnail_queue:
                return
            card, item, tile_size, placeholder, reason = self.thumbnail_queue.popleft()
            if not card.winfo_exists():
                continue
            thumb = load_thumbnail(item["path"], (tile_size - 6, tile_size - 6))
            card.delete(placeholder)
            if thumb:
                card.create_image(tile_size // 2, tile_size // 2, image=thumb)
                card.image = thumb
                self.images.append(thumb)
            else:
                card.create_text(tile_size // 2, tile_size // 2, text="Sin vista previa", fill=COLORS.text, width=tile_size - 8)
            if reason:
                card.create_rectangle(5, 5, min(tile_size - 5, 72), 23, fill="#31445a", outline="")
                card.create_text(min(tile_size - 5, 72) // 2 + 5, 14, text=reason, fill=COLORS.text, font=(UI_FONT, 7, "bold"))
        if self.thumbnail_queue:
            self.after(1, lambda: self.load_thumbnail_batch(generation))

    def position_for(self, index: int) -> tuple[int, int, str]:
        columns = self.grid_columns()
        return index // columns, index % columns, "n"

    def toggle_selection(self, image: dict):
        if self.on_toggle_selection is None:
            return
        self.on_toggle_selection(image)
        # Los controladores actualizan su propio estado; no todos devuelven
        # un booleano. Consultarlo de nuevo evita perder el borde al hacer
        # Ctrl + clic.
        self.set_selection_visual(image["path"], self.is_selected(image))

    def _on_card_click(self, event, image: dict):
        """Gestiona Ctrl + clic sin bloquear el arrastre nativo de archivos."""
        if event.state & 0x0004:  # Control en Tk/Windows
            self.toggle_selection(image)
            return "break"
        # tkinterdnd2 necesita recibir la pulsación y el movimiento normales
        # para iniciar un arrastre. No devolver "break" en este caso.
        return None

    def _on_card_enter(self, _event, image: dict, tags: str):
        """Registra la imagen bajo el cursor y otorga foco para recibir teclas."""
        self._hovered_image = image
        self.canvas.focus_set()
        if tags:
            self.show_tag_hint(_event, tags)

    def _on_card_leave(self):
        """Limpia la imagen bajo el cursor."""
        self._hovered_image = None
        self.hide_tag_hint()

    def _on_key_press(self, event):
        """Selección con Ctrl: alterna la selección de la tarjeta bajo el cursor."""
        if event.keysym in ("Control_L", "Control_R") and self._hovered_image is not None:
            self.toggle_selection(self._hovered_image)

    def set_selection_visual(self, path: str, selected: bool):
        card = self.cards_by_path.get(path)
        if not card:
            return
        old_outline = self.selection_outlines.pop(path, None)
        if old_outline:
            card.delete(old_outline)
        background = self.card_backgrounds.get(path)
        if background:
            card.itemconfigure(background, fill=COLORS.wine_soft if selected else COLORS.panel)
        if selected:
            size = int(card.cget("width"))
            self.selection_outlines[path] = card.create_rectangle(2, 2, size - 2, size - 2, outline=COLORS.wine_active, width=3)

    def clear_selection_visuals(self):
        for path in list(self.cards_by_path):
            self.set_selection_visual(path, False)

    @staticmethod
    def rounded_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
        points = [x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius, x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2, x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1]
        return canvas.create_polygon(points, smooth=True, **kwargs)

    def _register_drag(self, widget: ttk.Label, image: dict) -> None:
        try:
            from tkinterdnd2 import COPY, DND_FILES
            widget.drag_source_register(1, DND_FILES)
            def drag_init(_event):
                paths = self.drag_paths(image)
                # La lista de Tcl conserva correctamente rutas de Windows con espacios.
                return (COPY, DND_FILES, widget.tk.call("list", *paths))
            widget.dnd_bind("<<DragInitCmd>>", drag_init)
        # En algunos equipos Windows protege la carpeta de dependencias. La
        # biblioteca debe seguir abriendo aunque el arrastre no esté disponible.
        except (AttributeError, ImportError, OSError, PermissionError, tk.TclError):
            pass

    def show_tag_hint(self, event, tags: str):
        """La etiqueta aparece al pasar el cursor sin ocupar espacio en la tarjeta."""
        self.hide_tag_hint()
        hint = tk.Toplevel(self)
        self.tag_hint = hint
        hint.overrideredirect(True)
        hint.attributes("-topmost", True)
        hint.configure(background=COLORS.panel_elevated)
        tk.Label(hint, text=tags.title(), background=COLORS.panel_elevated, foreground=COLORS.muted, padx=6, pady=3, font=(UI_FONT, 9)).pack()
        hint.geometry(f"+{event.x_root + 10}+{event.y_root + 12}")

    def hide_tag_hint(self):
        if self.tag_hint and self.tag_hint.winfo_exists():
            self.tag_hint.destroy()
        self.tag_hint = None

    def show_context(self, event, image):
        self.context_image = image
        self.menu.delete(0, tk.END)
        self.menu.add_command(label="Vista previa", command=lambda: self.on_preview(self.context_image))
        self.menu.add_command(label="Agregar etiqueta", command=lambda: self.on_add_tag(self.context_image))
        tags = self.tag_names(image.get("tags") or "")
        if tags:
            remove_menu = tk.Menu(self.menu, tearoff=0)
            configure_menu(remove_menu)
            for tag in tags:
                remove_menu.add_command(label=tag.title(), command=lambda current=image, name=tag: self.on_remove_tag(current, name))
            self.menu.add_cascade(label="Borrar etiqueta", menu=remove_menu)
        if self.on_trash is not None:
            self.menu.add_separator()
            self.menu.add_command(
                label="Enviar a papelera",
                command=lambda: self.on_trash(self.context_image),
            )
        self.menu.tk_popup(event.x_root, event.y_root)
        self.menu.grab_release()

    @staticmethod
    def tag_names(tags: str) -> list[str]:
        for separator in (" · ", " \u00c2\u00b7 "):
            if separator in tags:
                return [tag.strip() for tag in tags.split(separator) if tag.strip()]
        return [tags] if tags else []
