"""Editor inicial del modo Plantilla regular del Armado de Planchas."""

from __future__ import annotations

import copy
import json
import tkinter as tk
import time
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app.planchas.template_model import (
    REGULAR_GAP_CM,
    REGULAR_MARGIN_CM,
    REGULAR_PATTERNS,
    RegularTemplateProject,
    TemplateCell,
    TemplateResource,
)
from app.ui.theme import COLORS, IDENTITY_FONT, UI_FONT, configure_menu, configure_plancha_styles


class RegularTemplateEditor(tk.Frame):
    """Editor de casillas fijas que trabaja con referencias a imágenes."""

    PAPER_RATIO = 21 / 29.7
    PRINT_SCALE = 0.9727
    PRINT_OUTLINE_PX = 4

    def __init__(self, master, images: list[dict] | None = None, project: RegularTemplateProject | None = None,
                 database=None, library_images: list[dict] | None = None, order_id: int | None = None,
                 plancha_id: int | None = None, person_name: str = "", person_phone: str = "", host=None):
        self.app = master
        self._standalone_window = None
        parent = host
        if parent is None:
            self._standalone_window = tk.Toplevel(master)
            self._standalone_window.title("Plancha regular · Armado de planchas")
            self._standalone_window.geometry("1240x800")
            self._standalone_window.minsize(980, 620)
            parent = self._standalone_window
        super().__init__(parent)
        self.configure(background=COLORS.background)
        self.project = project or RegularTemplateProject.from_images(images or [], apply_recommendation=False)
        self._pattern_proposal = (
            self.project.recommended_pattern_report(self.project.resources)
            if project is None and self.project.resources else None
        )
        self.database = database
        self.library_images = library_images or []
        self.order_id = order_id
        self.plancha_id = plancha_id
        self.person_name = person_name.strip()
        self.person_phone = person_phone.strip()
        self.project_path = ""
        self.final_png_path = ""
        self.selected_cells: set[str] = set()
        self.selected_resource_id: str | None = self.project.resources[0].resource_id if self.project.resources else None
        self.history: list[dict] = []
        self.future: list[dict] = []
        self._source_cache: dict[str, object] = {}
        self._preview_cache: dict[tuple, object] = {}
        self._photos: list[object] = []
        self._resource_photos: list[object] = []
        self._cell_boxes: dict[str, tuple[int, int, int, int]] = {}
        self._drag_cell: str | None = None
        self._drag_at = (0, 0)
        self._drag_snapshot_taken = False
        self._property_editing = False
        self.copied_cell_content: dict | None = None
        self._updating_properties = False
        self.zoom_value = tk.DoubleVar(value=1.0)
        self.offset_x_value = tk.DoubleVar(value=0.0)
        self.offset_y_value = tk.DoubleVar(value=0.0)
        self.mode_value = tk.StringVar(value="Rellenar")
        self.status_value = tk.StringVar()
        self._build()
        if self._standalone_window is not None:
            self.pack(fill="both", expand=True)
        self.render()
        if self._pattern_proposal and self._pattern_proposal["pattern_id"] != self.project.pattern_id:
            self.after_idle(self.offer_recommended_pattern)

    def _build(self):
        configure_plancha_styles(self)

        toolbar = tk.Frame(self, background=COLORS.panel, pady=9)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Patrones", command=lambda *a, _fn=self.choose_pattern: _fn(*a), style="Template.Primary.TButton").pack(side="left", padx=(12, 5))
        ttk.Button(toolbar, text="Nueva imagen", command=lambda *a, _fn=self.add_images: _fn(*a), style="Template.Primary.TButton").pack(side="left", padx=(12, 5))
        ttk.Button(toolbar, text="Pegar imagen", command=lambda *a, _fn=self.paste_image: _fn(*a), style="Template.Primary.TButton").pack(side="left", padx=5)
        ttk.Button(toolbar, text="Asignar todos", command=lambda *a, _fn=self.assign_all_cells: _fn(*a), style="Template.Primary.TButton").pack(side="left", padx=5)
        ttk.Button(toolbar, text="Asignar individual", command=lambda *a, _fn=self.assign_selected_resource: _fn(*a), style="Template.Secondary.TButton").pack(side="left", padx=5)
        ttk.Button(toolbar, text="Rellenar", command=lambda: self.apply_mode("Rellenar"), style="Template.Secondary.TButton").pack(side="left", padx=5)
        ttk.Button(toolbar, text="Ajustar", command=lambda: self.apply_mode("Ajustar"), style="Template.Secondary.TButton").pack(side="left", padx=5)
        ttk.Button(toolbar, text="Restablecer", command=lambda *a, _fn=self.reset_cells: _fn(*a), style="Template.Secondary.TButton").pack(side="left", padx=5)
        ttk.Button(toolbar, text="Deshacer", command=lambda *a, _fn=self.undo: _fn(*a), style="Template.Secondary.TButton").pack(side="left", padx=(22, 5))
        ttk.Button(toolbar, text="Rehacer", command=lambda *a, _fn=self.redo: _fn(*a), style="Template.Secondary.TButton").pack(side="left", padx=5)

        body = tk.Frame(self, background=COLORS.background)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        body.grid_columnconfigure(0, minsize=120, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        # El panel de recursos acompaña al armado: la previsualización es la
        # zona principal y necesita conservar la mayor parte del ancho.
        left = tk.Frame(body, background=COLORS.panel, width=120, highlightbackground=COLORS.border, highlightthickness=1)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.grid_propagate(False)
        tk.Label(left, text="IMÁGENES", background=COLORS.panel, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 10, "bold")).pack(anchor="w", padx=8, pady=(10, 3))
        tk.Label(left, text="Clic derecho para quitar.", background=COLORS.panel, foreground=COLORS.muted, wraplength=100, justify="left", font=(UI_FONT, 8)).pack(anchor="w", padx=8, pady=(0, 6))
        # Canvas fija su solicitud de ancho; sin este valor Tk conserva el
        # predeterminado (muy ancho) aunque el panel lateral sea angosto.
        self.resources_canvas = tk.Canvas(left, width=105, background=COLORS.panel, highlightthickness=0, borderwidth=0)
        resource_scroll = ttk.Scrollbar(left, orient="vertical", command=lambda *a, _fn=self.resources_canvas.yview: _fn(*a))
        self.resources_canvas.configure(yscrollcommand=resource_scroll.set)
        resource_scroll.pack(side="right", fill="y", pady=(0, 8))
        self.resources_canvas.pack(fill="both", expand=True, padx=(5, 0), pady=(0, 5))
        self.resources_inner = tk.Frame(self.resources_canvas, background=COLORS.panel)
        self.resources_window = self.resources_canvas.create_window((0, 0), window=self.resources_inner, anchor="nw")
        self.resources_inner.bind("<Configure>", lambda _event: self.resources_canvas.configure(scrollregion=self.resources_canvas.bbox("all")))
        self.resources_canvas.bind("<Configure>", lambda event: self.resources_canvas.itemconfigure(self.resources_window, width=event.width))

        center = tk.Frame(body, background=COLORS.canvas, highlightbackground=COLORS.border, highlightthickness=1)
        center.grid(row=0, column=1, sticky="nsew")
        self.template_canvas = tk.Canvas(center, background=COLORS.canvas, highlightthickness=0, borderwidth=0)
        self.template_canvas.pack(fill="both", expand=True, padx=10, pady=10)
        self.template_canvas.bind("<Configure>", lambda _event: self.render())
        self.template_canvas.bind("<Button-1>", self.on_canvas_click)
        self.template_canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.template_canvas.bind("<ButtonRelease-1>", self.finish_canvas_drag)
        self.template_canvas.bind("<Button-3>", self.show_context_menu)
        self.template_canvas.bind("<Control-MouseWheel>", self.on_zoom_wheel)
        self.template_canvas.bind("<MouseWheel>", self.on_zoom_wheel)
        self.bind("<Delete>", self.clear_shortcut)

        self.context_menu = tk.Menu(self, tearoff=False)
        configure_menu(self.context_menu)
        self.context_menu.add_command(label="Copiar contenido y parámetros", command=lambda *a, _fn=self.copy_cell_content: _fn(*a))
        self.context_menu.add_command(label="Pegar contenido y parámetros", command=lambda *a, _fn=self.paste_cell_content: _fn(*a))
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Vaciar casilla", command=lambda *a, _fn=self.clear_cells: _fn(*a))

        right = tk.Frame(body, background=COLORS.panel, width=250, highlightbackground=COLORS.border, highlightthickness=1)
        right.grid(row=0, column=2, sticky="nsew", padx=(10, 0))
        right.grid_propagate(False)
        tk.Label(right, text="PROPIEDADES", background=COLORS.panel, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 12, "bold")).pack(anchor="w", padx=13, pady=(13, 8))
        self.selection_label = tk.StringVar(value="Seleccioná una casilla.")
        tk.Label(right, textvariable=self.selection_label, background=COLORS.panel, foreground=COLORS.text, wraplength=220, justify="left", font=(UI_FONT, 10)).pack(anchor="w", padx=13, pady=(0, 12))
        tk.Label(right, text="Modo de encuadre", background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 10)).pack(anchor="w", padx=13)
        mode = ttk.Combobox(right, textvariable=self.mode_value, values=("Rellenar", "Ajustar", "Tamaño original"), state="readonly")
        mode.pack(fill="x", padx=13, pady=(3, 12))
        mode.bind("<<ComboboxSelected>>", lambda _event: self.apply_mode(self.mode_value.get()))
        self._property_scale(right, "Zoom", self.zoom_value, 0.25, 3.0, 0.05, self.apply_properties)
        self._property_scale(right, "Posición horizontal", self.offset_x_value, -1.0, 1.0, 0.02, self.apply_properties)
        self._property_scale(right, "Posición vertical", self.offset_y_value, -1.0, 1.0, 0.02, self.apply_properties)
        ttk.Button(right, text="Centrar imagen", command=lambda *a, _fn=self.center_cells: _fn(*a), style="Template.Secondary.TButton").pack(fill="x", padx=13, pady=(12, 5))
        ttk.Button(right, text="Vaciar casilla", command=lambda *a, _fn=self.clear_cells: _fn(*a), style="Template.Secondary.TButton").pack(fill="x", padx=13, pady=5)
        tk.Label(right, text="Rellenar recorta sin deformar. Ajustar muestra la imagen completa.", background=COLORS.panel, foreground=COLORS.muted, wraplength=215, justify="left", font=(UI_FONT, 10)).pack(anchor="w", padx=13, pady=(18, 0))

        footer = tk.Frame(self, background=COLORS.panel, pady=9)
        footer.pack(fill="x")
        tk.Label(footer, textvariable=self.status_value, background=COLORS.panel, foreground=COLORS.text, font=(UI_FONT, 10)).pack(side="left", padx=14)
        ttk.Button(footer, text="Abrir proyecto", command=lambda *a, _fn=self.open_project: _fn(*a), style="Template.Secondary.TButton").pack(side="right", padx=(4, 12))
        ttk.Button(footer, text="Guardar proyecto", command=lambda *a, _fn=self.save_project: _fn(*a), style="Template.Secondary.TButton").pack(side="right", padx=4)
        ttk.Button(footer, text="Guardar en Producción e impresión", command=lambda *a, _fn=self.save_to_production: _fn(*a), style="Template.Primary.TButton").pack(side="right", padx=4)

    def _property_scale(self, parent, label, variable, start, end, resolution, command):
        tk.Label(parent, text=label, background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 10)).pack(anchor="w", padx=13)
        control = tk.Scale(parent, variable=variable, from_=start, to=end, resolution=resolution, orient="horizontal", showvalue=True, command=lambda _value: command(), background=COLORS.panel, foreground=COLORS.text, troughcolor=COLORS.border, activebackground=COLORS.wine_active, highlightthickness=0, borderwidth=0)
        control.pack(fill="x", padx=10, pady=(0, 9))
        control.bind("<ButtonRelease-1>", lambda _event: setattr(self, "_property_editing", False))

    def current_cell(self) -> TemplateCell | None:
        return self.project.cell(next(iter(self.selected_cells), None))

    def snapshot(self):
        state = {"project": copy.deepcopy(self.project.to_dict()), "cells": list(self.selected_cells), "resource": self.selected_resource_id}
        if not self.history or self.history[-1] != state:
            self.history.append(state)
            self.history = self.history[-60:]
        self.future.clear()

    def restore(self, state: dict):
        data = state["project"]
        self.project = RegularTemplateProject(
            cells=[TemplateCell.from_dict(item) for item in data["cells"]],
            resources=[TemplateResource.from_dict(item) for item in data["resources"]],
            name=data.get("name", "Plantilla de prueba"),
            pattern_id=data.get("pattern_id", "circular_4x5"),
        )
        self.selected_cells = set(state.get("cells", []))
        self.selected_resource_id = state.get("resource")
        self._source_cache.clear()
        self._preview_cache.clear()
        self.render()

    def undo(self):
        if not self.history:
            return
        current = {"project": copy.deepcopy(self.project.to_dict()), "cells": list(self.selected_cells), "resource": self.selected_resource_id}
        self.future.append(current)
        self.restore(self.history.pop())

    def redo(self):
        if not self.future:
            return
        current = {"project": copy.deepcopy(self.project.to_dict()), "cells": list(self.selected_cells), "resource": self.selected_resource_id}
        self.history.append(current)
        self.restore(self.future.pop())

    def choose_pattern(self):
        """Muestra patrones A4 calculados con margen y separación reales."""
        dialog = tk.Toplevel(self)
        dialog.title("Patrones de plancha regular")
        dialog.configure(background=COLORS.background)
        dialog.transient(self)
        dialog.grab_set()
        # Seven patterns require three rows.  The old 470 px dialog clipped
        # the final row, making a valid option inaccessible.
        dialog.resizable(True, True)
        dialog.minsize(700, 500)
        self.update_idletasks()
        width = min(900, max(700, self.winfo_screenwidth() - 120))
        height = min(650, max(500, self.winfo_screenheight() - 120))
        x = max(0, self.winfo_rootx() + (self.winfo_width() - width) // 2)
        y = max(0, self.winfo_rooty() + (self.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        margin_text = f"{REGULAR_MARGIN_CM:.2f}".replace(".", ",")
        gap_text = f"{REGULAR_GAP_CM:.2f}".replace(".", ",")
        tk.Label(dialog, text="PATRONES REGULARES", background=COLORS.background, foreground=COLORS.text, font=(IDENTITY_FONT, 18, "bold")).pack(anchor="w", padx=22, pady=(20, 3))
        tk.Label(
            dialog,
            text=(
                "Cada opción ocupa el A4 hasta el límite seguro: "
                f"margen de {margin_text} cm y separación de {gap_text} cm."
            ),
            background=COLORS.background,
            foreground=COLORS.muted,
            font=(UI_FONT, 10),
        ).pack(anchor="w", padx=22, pady=(0, 14))
        content = tk.Frame(dialog, background=COLORS.background)
        content.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        pattern_canvas = tk.Canvas(content, background=COLORS.background, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(content, orient="vertical", command=pattern_canvas.yview)
        pattern_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        pattern_canvas.pack(side="left", fill="both", expand=True)
        grid = tk.Frame(pattern_canvas, background=COLORS.background)
        grid_window = pattern_canvas.create_window((0, 0), window=grid, anchor="nw")
        grid.bind("<Configure>", lambda _event: pattern_canvas.configure(scrollregion=pattern_canvas.bbox("all")))
        pattern_canvas.bind("<Configure>", lambda event: pattern_canvas.itemconfigure(grid_window, width=event.width))
        pattern_canvas.bind("<MouseWheel>", lambda event: pattern_canvas.yview_scroll(-1 * (event.delta // 120), "units"))
        for column in range(3):
            grid.grid_columnconfigure(column, weight=1)

        def apply(pattern_id: str):
            self.snapshot()
            self.project.apply_pattern(pattern_id, preserve_content=True)
            self.selected_cells.clear()
            self._preview_cache.clear()
            self.render()
            dialog.destroy()

        for index, (pattern_id, pattern) in enumerate(REGULAR_PATTERNS.items()):
            row, column = divmod(index, 3)
            selected = pattern_id == self.project.pattern_id
            card = tk.Frame(
                grid,
                background=COLORS.panel_elevated,
                highlightthickness=2 if selected else 1,
                highlightbackground=COLORS.wine_active if selected else COLORS.border,
            )
            card.grid(row=row, column=column, sticky="nsew", padx=5, pady=5, ipady=2)
            tk.Label(card, text=str(pattern["title"]), background=COLORS.panel_elevated, foreground=COLORS.text, font=(IDENTITY_FONT, 11, "bold")).pack(anchor="w", padx=12, pady=(12, 3))
            tk.Label(card, text=str(pattern["detail"]), background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 9)).pack(anchor="w", padx=12)
            ratio = self.project.cell_ratio(pattern_id)
            tk.Label(card, text=f"Celda {ratio:.2f} de proporción", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 9)).pack(anchor="w", padx=12, pady=(4, 8))
            ttk.Button(card, text="Usar patrón", command=lambda value=pattern_id: apply(value), style="Template.Primary.TButton").pack(anchor="w", padx=12, pady=(0, 12))

        actions = tk.Frame(dialog, background=COLORS.panel, pady=10)
        actions.pack(fill="x")
        tk.Label(
            actions,
            text="Selecciona el formato que mejor acompane la proporcion de tus disenos.",
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 9),
        ).pack(side="left", padx=18)
        ttk.Button(actions, text="Cancelar", command=dialog.destroy, style="Template.Secondary.TButton").pack(side="right", padx=18)

    def offer_recommended_pattern(self):
        """Presenta la recomendación; nunca cambia la plancha silenciosamente."""
        report = self._pattern_proposal or {}
        pattern_id = str(report.get("pattern_id") or "")
        pattern = REGULAR_PATTERNS.get(pattern_id)
        if not pattern or pattern_id == self.project.pattern_id:
            return
        confidence = float(report.get("confidence") or 0.0) * 100
        suitability = "ajuste claro" if report.get("auto_suitable") else "requiere revisión"
        if not messagebox.askyesno(
            "Patrón sugerido",
            f"Doccione propone «{pattern['title']}» ({pattern['detail']}).\n"
            f"Confianza: {confidence:.0f}% · {suitability}.\n\n"
            f"{report.get('reason', '')}\n\n¿Querés aplicarlo?",
            parent=self,
        ):
            return
        self.snapshot()
        self.project.apply_pattern(pattern_id, preserve_content=False)
        self._preview_cache.clear()
        self.render()

    def add_images(self):
        paths = filedialog.askopenfilenames(title="Cargar imágenes para la plantilla", filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"), ("Todos los archivos", "*.*")])
        if not paths:
            return
        self.snapshot()
        for path in paths:
            resource = self.project.add_resource(path)
            self.selected_resource_id = resource.resource_id
        # El patrón vuelve a calcularse con la proporción real de los
        # recursos y se completa en cadena, como las planchas de referencia.
        recommended = self.project.recommended_pattern(self.project.resources)
        self.project.apply_pattern(recommended, preserve_content=False)
        self.selected_cells.clear()
        self._preview_cache.clear()
        self.render()

    def paste_image(self):
        """Agrega al banco una imagen o archivo de imagen del portapapeles."""
        try:
            from PIL import Image, ImageGrab

            content = ImageGrab.grabclipboard()
            if isinstance(content, Image.Image):
                folder = Path(__file__).resolve().parents[2] / "outputs" / "imagenes_pegadas"
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / f"plancha_regular_{time.strftime('%Y%m%d_%H%M%S')}.png"
                counter = 1
                while target.exists():
                    target = folder / f"plancha_regular_{time.strftime('%Y%m%d_%H%M%S')}_{counter}.png"
                    counter += 1
                content.convert("RGBA").save(target)
                paths = [target]
            elif isinstance(content, list):
                paths = [Path(item) for item in content if Path(item).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}]
            else:
                paths = []
        except Exception as error:
            messagebox.showerror("Pegar imagen", f"No se pudo leer el portapapeles:\n{error}", parent=self)
            return

        if not paths:
            messagebox.showinfo("Pegar imagen", "Copiá una imagen o un archivo de imagen e intentá nuevamente.", parent=self)
            return
        self.snapshot()
        for path in paths:
            if path.is_file():
                resource = self.project.add_resource(str(path))
                self.selected_resource_id = resource.resource_id
        if self.project.resources:
            self.project.apply_pattern(self.project.recommended_pattern(self.project.resources), preserve_content=False)
        self.selected_cells.clear()
        self._preview_cache.clear()
        self.render()
        self.status_value.set(f"{len(paths)} imagen(es) pegada(s) en el banco.")

    def assign_selected_resource(self):
        if not self.selected_resource_id:
            messagebox.showinfo("Plancha regular", "Primero cargá o seleccioná una imagen.", parent=self)
            return
        if not self.selected_cells:
            messagebox.showinfo("Plancha regular", "Seleccioná una o más casillas para aplicar la imagen.", parent=self)
            return
        self.snapshot()
        self.project.assign(self.selected_cells, self.selected_resource_id)
        self.render()

    def assign_all_cells(self):
        """Completa el patrón con el recurso elegido, sin requerir selección."""
        if not self.selected_resource_id:
            messagebox.showinfo("Plancha regular", "Primero cargá o seleccioná una imagen.", parent=self)
            return
        self.snapshot()
        self.project.assign({cell.cell_id for cell in self.project.cells}, self.selected_resource_id)
        self.selected_cells.clear()
        self.render()

    def apply_mode(self, mode: str):
        if not self.selected_cells:
            return
        self.snapshot()
        for cell in self.project.cells:
            if cell.cell_id in self.selected_cells:
                cell.frame_mode = mode
                cell.zoom = 1.0
                cell.offset_x = cell.offset_y = 0.0
        self.mode_value.set(mode)
        self.render()

    def apply_properties(self):
        if self._updating_properties or not self.selected_cells:
            return
        if not self._property_editing:
            self.snapshot()
            self._property_editing = True
        for cell in self.project.cells:
            if cell.cell_id in self.selected_cells:
                cell.zoom = float(self.zoom_value.get())
                cell.offset_x = float(self.offset_x_value.get())
                cell.offset_y = float(self.offset_y_value.get())
        self.render_template()

    def center_cells(self):
        if not self.selected_cells:
            return
        self.snapshot()
        for cell in self.project.cells:
            if cell.cell_id in self.selected_cells:
                cell.offset_x = cell.offset_y = 0.0
        self.render()

    def reset_cells(self):
        if not self.selected_cells:
            return
        self.snapshot()
        for cell in self.project.cells:
            if cell.cell_id in self.selected_cells:
                cell.frame_mode = "Rellenar"
                cell.zoom = 1.0
                cell.offset_x = cell.offset_y = 0.0
                cell.rotation = 0
        self.render()

    def clear_cells(self):
        if not self.selected_cells:
            return
        self.snapshot()
        self.project.clear(self.selected_cells)
        self.render()

    def clear_shortcut(self, _event=None):
        """Supr vacía la selección actual sin tocar las imágenes originales."""
        if self.selected_cells:
            self.clear_cells()
            return "break"
        return None

    def cell_at(self, x: int, y: int) -> str | None:
        for key, box in self._cell_boxes.items():
            if not (box[0] <= x <= box[2] and box[1] <= y <= box[3]):
                continue
            cell = self.project.cell(key)
            if cell and cell.shape == "circle":
                radius_x = max(1, (box[2] - box[0]) / 2)
                radius_y = max(1, (box[3] - box[1]) / 2)
                normalized_x = (x - (box[0] + radius_x)) / radius_x
                normalized_y = (y - (box[1] + radius_y)) / radius_y
                if normalized_x * normalized_x + normalized_y * normalized_y > 1:
                    continue
            return key
        return None

    def show_context_menu(self, event):
        cell_id = self.cell_at(event.x, event.y)
        if not cell_id:
            return
        if cell_id not in self.selected_cells:
            self.selected_cells = {cell_id}
            self.sync_properties()
            self.render_template()
        has_content = bool(self.current_cell() and self.current_cell().resource_id)
        self.context_menu.entryconfigure(0, state="normal" if has_content else "disabled")
        self.context_menu.entryconfigure(1, state="normal" if self.copied_cell_content else "disabled")
        self.context_menu.tk_popup(event.x_root, event.y_root)
        self.context_menu.grab_release()

    def copy_cell_content(self):
        cell = self.current_cell()
        if not cell or not cell.resource_id:
            return
        self.copied_cell_content = {
            "resource_id": cell.resource_id,
            "frame_mode": cell.frame_mode,
            "zoom": cell.zoom,
            "offset_x": cell.offset_x,
            "offset_y": cell.offset_y,
            "rotation": cell.rotation,
        }
        self.status_value.set("Contenido y encuadre copiados. Seleccioná una casilla y usá clic derecho para pegar.")

    def paste_cell_content(self):
        if not self.copied_cell_content or not self.selected_cells:
            return
        self.snapshot()
        for cell in self.project.cells:
            if cell.cell_id not in self.selected_cells:
                continue
            for field, value in self.copied_cell_content.items():
                setattr(cell, field, value)
        self.render()

    def on_canvas_click(self, event):
        cell_id = self.cell_at(event.x, event.y)
        if not cell_id:
            self.selected_cells.clear()
            self.render()
            return
        if event.state & 0x0004:
            if cell_id in self.selected_cells:
                self.selected_cells.remove(cell_id)
            else:
                self.selected_cells.add(cell_id)
        else:
            self.selected_cells = {cell_id}
        self._drag_cell = cell_id
        self._drag_at = (event.x, event.y)
        self._drag_snapshot_taken = False
        self.sync_properties()
        self.render_template()

    def on_canvas_drag(self, event):
        cell = self.project.cell(self._drag_cell)
        box = self._cell_boxes.get(self._drag_cell or "")
        if not cell or not cell.resource_id or not box:
            return
        if not self._drag_snapshot_taken:
            self.snapshot()
            self._drag_snapshot_taken = True
        dx = (event.x - self._drag_at[0]) / max(1, box[2] - box[0])
        dy = (event.y - self._drag_at[1]) / max(1, box[3] - box[1])
        cell.offset_x = max(-1.0, min(1.0, cell.offset_x + dx))
        cell.offset_y = max(-1.0, min(1.0, cell.offset_y + dy))
        self._drag_at = (event.x, event.y)
        self.sync_properties()
        self.render_template()

    def finish_canvas_drag(self, _event):
        self._drag_cell = None
        self._drag_snapshot_taken = False

    def on_zoom_wheel(self, event):
        cell = self.current_cell()
        if not cell or not cell.resource_id:
            return
        self.snapshot()
        direction = 1 if event.delta > 0 else -1
        cell.zoom = max(0.25, min(3.0, round(cell.zoom + direction * 0.05, 2)))
        self.sync_properties()
        self.render_template()

    def _paper_box(self) -> tuple[int, int, int, int]:
        width = max(260, self.template_canvas.winfo_width() - 36)
        height = max(340, self.template_canvas.winfo_height() - 36)
        paper_height = min(height, int(width / self.PAPER_RATIO))
        paper_width = int(paper_height * self.PAPER_RATIO)
        left = (self.template_canvas.winfo_width() - paper_width) // 2
        top = (self.template_canvas.winfo_height() - paper_height) // 2
        return left, top, left + paper_width, top + paper_height

    def resource_image(self, resource_id: str):
        cached = self._source_cache.get(resource_id)
        if cached is not None:
            return cached.copy()
        resource = self.project.resource(resource_id)
        if not resource:
            return None
        try:
            from PIL import Image
            with Image.open(resource.path) as image:
                result = image.convert("RGBA")
            self._source_cache[resource_id] = result
            return result.copy()
        except Exception:
            return None

    def cell_preview(self, cell: TemplateCell, width: int, height: int):
        resource = self.project.resource(cell.resource_id)
        if not resource:
            return None
        key = (cell.cell_id, resource.modified, width, height, cell.shape, cell.frame_mode, round(cell.zoom, 3), round(cell.offset_x, 3), round(cell.offset_y, 3), cell.rotation)
        cached = self._preview_cache.get(key)
        if cached:
            return cached
        try:
            from PIL import Image, ImageChops, ImageTk
            image = self.resource_image(resource.resource_id)
            if image is None:
                return None
            if cell.rotation:
                image = image.rotate(-cell.rotation, expand=True, resample=Image.Resampling.BICUBIC)
            if cell.frame_mode == "Rellenar":
                scale = max(width / image.width, height / image.height)
            else:
                scale = min(width / image.width, height / image.height)
            if cell.frame_mode == "Tamaño original":
                scale = min(width / image.width, height / image.height)
            scale *= cell.zoom
            target = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
            result = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            x = round((width - target.width) / 2 + cell.offset_x * width)
            y = round((height - target.height) / 2 + cell.offset_y * height)
            result.alpha_composite(target, (x, y))
            if cell.shape == "circle":
                from PIL import ImageDraw
                mask = Image.new("L", (width, height), 0)
                ImageDraw.Draw(mask).ellipse((0, 0, width - 1, height - 1), fill=255)
                result.putalpha(ImageChops.multiply(result.getchannel("A"), mask))
            photo = ImageTk.PhotoImage(result)
            self._preview_cache[key] = photo
            return photo
        except Exception:
            return None

    def resource_thumbnail(self, resource_id: str, size: int = 58):
        try:
            from PIL import Image, ImageTk
            image = self.resource_image(resource_id)
            if image is None:
                return None
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(image)
        except Exception:
            return None

    def render_resources(self):
        for child in self.resources_inner.winfo_children():
            child.destroy()
        self._resource_photos.clear()
        if not self.project.resources:
            tk.Label(self.resources_inner, text="Todavía no hay imágenes.\nUsá Nueva imagen.", background="#111314", foreground="#b9a79b", justify="left").pack(anchor="w", padx=10, pady=10)
            return
        for resource in self.project.resources:
            selected = resource.resource_id == self.selected_resource_id
            card = tk.Frame(self.resources_inner, background="#3c1014" if selected else "#1a1d1e", highlightbackground="#d60916" if selected else "#303436", highlightthickness=1, padx=4, pady=4)
            card.pack(fill="x", padx=3, pady=3)
            thumb = self.resource_thumbnail(resource.resource_id)
            self._resource_photos.append(thumb)
            image_label = tk.Label(card, image=thumb, text="Sin vista previa" if thumb is None else "", compound="center", width=62, height=62, background="#0c0d0e", foreground="#b9a79b")
            image_label.pack(anchor="w")
            details = tk.Frame(card, background=card.cget("background"))
            details.pack(fill="x", pady=(4, 0))
            title = tk.Label(details, text=resource.name, background=card.cget("background"), foreground="#fff4ec", wraplength=92, justify="left", font=("Bahnschrift", 8, "bold"))
            title.pack(anchor="w")
            usage = tk.Label(details, text=f"Usado: {self.project.usage_count(resource.resource_id)}", background=card.cget("background"), foreground="#c7b6aa", justify="left", font=(UI_FONT, 8))
            usage.pack(anchor="w", pady=(2, 0))
            for widget in (card, image_label, details, title, usage):
                widget.bind("<Button-1>", lambda _event, value=resource.resource_id: self.select_resource(value))
                widget.bind("<Button-3>", lambda event, value=resource.resource_id: self.show_resource_menu(event, value))

    def select_resource(self, resource_id: str):
        self.selected_resource_id = resource_id
        self.render_resources()

    def remove_resource(self, resource_id: str):
        """Quita el recurso del banco y vacía las casillas que lo usaban."""
        resource = self.project.resource(resource_id)
        if not resource:
            return
        used = self.project.usage_count(resource_id)
        if not messagebox.askyesno(
            "Quitar imagen",
            f"¿Quitar «{resource.name}» de esta plancha?"
            + (f"\n\nTambién se vaciarán {used} casilla(s)." if used else "")
            + "\n\nEl archivo original no se elimina.",
            parent=self,
        ):
            return
        self.snapshot()
        self.project.resources = [item for item in self.project.resources if item.resource_id != resource_id]
        for cell in self.project.cells:
            if cell.resource_id == resource_id:
                cell.resource_id = None
                cell.zoom = 1.0
                cell.offset_x = cell.offset_y = 0.0
        if self.selected_resource_id == resource_id:
            self.selected_resource_id = self.project.resources[0].resource_id if self.project.resources else None
        self._source_cache.pop(resource_id, None)
        self._preview_cache.clear()
        self.render()
        self.status_value.set(f"Imagen quitada del banco. El archivo original se conserva.")

    def show_resource_menu(self, event, resource_id: str):
        self.select_resource(resource_id)
        menu = tk.Menu(self, tearoff=False)
        configure_menu(menu)
        menu.add_command(label="Quitar imagen de la plancha", command=lambda: self.remove_resource(resource_id))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def render_template(self):
        canvas = self.template_canvas
        canvas.delete("all")
        self._photos.clear()
        self._cell_boxes.clear()
        left, top, right, bottom = self._paper_box()
        canvas.create_rectangle(left, top, right, bottom, fill="#f8f5ef", outline="#e51a27", width=2)
        for position, cell in enumerate(self.project.cells, start=1):
            x1 = round(left + cell.x * (right - left))
            y1 = round(top + cell.y * (bottom - top))
            x2 = round(x1 + cell.width * (right - left))
            y2 = round(y1 + cell.height * (bottom - top))
            self._cell_boxes[cell.cell_id] = (x1, y1, x2, y2)
            photo = self.cell_preview(cell, max(1, x2 - x1 - 4), max(1, y2 - y1 - 4)) if cell.resource_id else None
            if photo:
                self._photos.append(photo)
                canvas.create_image(x1 + 2, y1 + 2, image=photo, anchor="nw")
            elif not cell.resource_id:
                if cell.shape == "circle":
                    canvas.create_oval(x1 + 2, y1 + 2, x2 - 2, y2 - 2, fill="#ebe8e2", outline="", stipple="gray25")
                else:
                    canvas.create_rectangle(x1 + 2, y1 + 2, x2 - 2, y2 - 2, fill="#ebe8e2", outline="", stipple="gray25")
                canvas.create_text((x1 + x2) // 2, (y1 + y2) // 2, text="Vacío", fill="#8a8179", font=("Bahnschrift", 9, "italic"))
            outline = "#d60916" if cell.cell_id in self.selected_cells else "#55585a"
            if cell.shape == "circle":
                canvas.create_oval(x1, y1, x2, y2, outline=outline, width=3 if cell.cell_id in self.selected_cells else 1)
            else:
                canvas.create_rectangle(x1, y1, x2, y2, outline=outline, width=3 if cell.cell_id in self.selected_cells else 1)
            canvas.create_text(x1 + 7, y1 + 7, text=str(position), fill="#d60916" if cell.cell_id in self.selected_cells else "#827d77", anchor="nw", font=("Bahnschrift", 8, "bold"))

    def sync_properties(self):
        cell = self.current_cell()
        self._updating_properties = True
        if cell:
            self.selection_label.set(f"{len(self.selected_cells)} casilla(s) seleccionada(s).\nPodés mover la imagen arrastrándola dentro de la casilla.")
            self.mode_value.set(cell.frame_mode)
            self.zoom_value.set(cell.zoom)
            self.offset_x_value.set(cell.offset_x)
            self.offset_y_value.set(cell.offset_y)
        else:
            self.selection_label.set("Seleccioná una casilla. Con Ctrl + clic podés sumar más.")
        self._updating_properties = False

    def render_status(self):
        occupied = sum(bool(cell.resource_id) for cell in self.project.cells)
        total = len(self.project.cells)
        pattern = self.project.pattern
        self.status_value.set(
            f"{pattern['title']} · {pattern['detail']} · "
            f"{occupied} espacios ocupados · {total - occupied} vacíos · {len(self.project.resources)} imágenes distintas"
        )

    def render(self):
        self.render_resources()
        self.render_template()
        self.sync_properties()
        self.render_status()

    def render_final_sheet(self):
        """Genera el PNG A4 a 97,27 %, con solo el borde negro externo."""
        from PIL import Image, ImageChops, ImageDraw

        dpi = 300
        page = Image.new("RGBA", (2480, 3508), (0, 0, 0, 0))
        for cell in self.project.cells:
            resource = self.project.resource(cell.resource_id)
            if not resource:
                continue
            try:
                with Image.open(resource.path) as source:
                    image = source.convert("RGBA")
                if cell.rotation:
                    image = image.rotate(-cell.rotation, expand=True, resample=Image.Resampling.BICUBIC)
                width = max(1, round(cell.width * page.width))
                height = max(1, round(cell.height * page.height))
                scale = max(width / image.width, height / image.height) if cell.frame_mode == "Rellenar" else min(width / image.width, height / image.height)
                target = image.resize((max(1, round(image.width * scale * cell.zoom)), max(1, round(image.height * scale * cell.zoom))), Image.Resampling.LANCZOS)
                frame = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                frame.alpha_composite(target, (round((width - target.width) / 2 + cell.offset_x * width), round((height - target.height) / 2 + cell.offset_y * height)))
                if cell.shape == "circle":
                    mask = Image.new("L", (width, height), 0)
                    ImageDraw.Draw(mask).ellipse((0, 0, width - 1, height - 1), fill=255)
                    frame.putalpha(ImageChops.multiply(frame.getchannel("A"), mask))
                # El contorno se dibuja al final, por encima del diseño: no se
                # agrega borde blanco ni una línea interior a la ilustración.
                outline = ImageDraw.Draw(frame)
                border = self.PRINT_OUTLINE_PX // 2
                box = (border, border, width - 1 - border, height - 1 - border)
                if cell.shape == "circle":
                    outline.ellipse(box, outline="black", width=self.PRINT_OUTLINE_PX)
                else:
                    outline.rectangle(box, outline="black", width=self.PRINT_OUTLINE_PX)
                page.alpha_composite(frame, (round(cell.x * page.width), round(cell.y * page.height)))
            except Exception:
                continue
        # La escala se aplica una sola vez, en la capa común de impresión.
        # Guardar el PNG a tamaño nominal evita una doble reducción al enviarlo.
        return page

    def save_to_production(self):
        """Registra la plantilla y su PNG final para Producción e impresión."""
        if not self.database:
            messagebox.showinfo("Producción e impresión", "Abrí el creador desde Doccione Studio para guardar esta plancha en Producción.", parent=self)
            return
        if not any(cell.resource_id for cell in self.project.cells):
            messagebox.showinfo("Producción e impresión", "Asigná al menos un diseño antes de guardar.", parent=self)
            return
        root = Path(__file__).resolve().parents[2]
        folder = root / "outputs" / "planchas_regulares"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        base_name = f"plancha_regular_{stamp}"
        project_path = folder / f"{base_name}.doccione-plantilla.json"
        png_path = folder / f"{base_name}.png"
        try:
            self.project.save(project_path)
            self.render_final_sheet().save(png_path, "PNG", dpi=(300, 300), compress_level=3)
            material = ((self.database.order(self.order_id) or {}).get("material", "") if self.order_id else "")
            self.plancha_id = self.database.save_plancha_project(
                self.order_id, self.project.name or "Plancha regular", material,
                json.dumps(self.project.to_dict(), ensure_ascii=False), str(project_path), self.plancha_id,
                self.person_name, self.person_phone, "a4",
            )
            self.database.set_plancha_final_png(self.plancha_id, str(png_path))
            self.database.update_plancha_production_status(self.plancha_id, "lista")
            self.project_path = str(project_path)
            self.final_png_path = str(png_path)
            self.status_value.set("Guardada en Producción e impresión.")
            messagebox.showinfo("Producción e impresión", "La plancha regular y su PNG final quedaron disponibles en Producción.", parent=self)
            if hasattr(self.app, "show_production_planchas"):
                self.app.show_production_planchas()
            self.close()
        except Exception as error:
            messagebox.showerror("Producción e impresión", f"No se pudo guardar la plancha: {error}", parent=self)

    def close(self):
        """Cierra la ventana independiente o la ficha integrada."""
        if self._standalone_window is not None and self._standalone_window.winfo_exists():
            self._standalone_window.destroy()
        else:
            self.destroy()

    def save_project(self):
        path = filedialog.asksaveasfilename(title="Guardar plancha regular", defaultextension=".doccione-plantilla.json", filetypes=[("Plancha regular Doccione", "*.doccione-plantilla.json"), ("JSON", "*.json")])
        if not path:
            return
        self.project.save(path)
        self.project_path = path
        messagebox.showinfo("Proyecto guardado", "La plantilla se guardó con referencias a las imágenes originales; no se creó ninguna copia.", parent=self)

    def open_project(self):
        path = filedialog.askopenfilename(title="Abrir plancha regular", filetypes=[("Plancha regular Doccione", "*.doccione-plantilla.json *.json")])
        if not path:
            return
        try:
            self.project = RegularTemplateProject.load(path)
            self.project_path = path
            self.selected_cells.clear()
            self.selected_resource_id = self.project.resources[0].resource_id if self.project.resources else None
            self.history.clear()
            self.future.clear()
            self._source_cache.clear()
            self._preview_cache.clear()
            self.render()
        except Exception as error:
            messagebox.showerror("No se pudo abrir", str(error), parent=self)
