"""Editor inicial del modo Plantilla regular del Armado de Planchas."""

from __future__ import annotations

import copy
import tkinter as tk
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


class RegularTemplateEditor(tk.Toplevel):
    """Editor de casillas fijas que trabaja con referencias a imágenes."""

    PAPER_RATIO = 21 / 29.7

    def __init__(self, master, images: list[dict] | None = None, project: RegularTemplateProject | None = None,
                 database=None, library_images: list[dict] | None = None):
        super().__init__(master)
        self.title("Plancha regular · Armado de planchas")
        self.geometry("1240x800")
        self.minsize(980, 620)
        self.configure(background=COLORS.background)
        self.project = project or RegularTemplateProject.from_images(images or [], apply_recommendation=False)
        self._pattern_proposal = (
            self.project.recommended_pattern_report(self.project.resources)
            if project is None and self.project.resources else None
        )
        self.database = database
        self.library_images = library_images or []
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
        self.render()
        if self._pattern_proposal and self._pattern_proposal["pattern_id"] != self.project.pattern_id:
            self.after_idle(self.offer_recommended_pattern)

    def _build(self):
        configure_plancha_styles(self)

        toolbar = tk.Frame(self, background=COLORS.panel, pady=9)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Patrones", command=lambda *a, _fn=self.choose_pattern: _fn(*a), style="Template.Primary.TButton").pack(side="left", padx=(12, 5))
        ttk.Button(toolbar, text="Nueva imagen", command=lambda *a, _fn=self.add_images: _fn(*a), style="Template.Primary.TButton").pack(side="left", padx=(12, 5))
        ttk.Button(toolbar, text="Asignar", command=lambda *a, _fn=self.assign_selected_resource: _fn(*a), style="Template.Primary.TButton").pack(side="left", padx=5)
        ttk.Button(toolbar, text="Rellenar", command=lambda: self.apply_mode("Rellenar"), style="Template.Secondary.TButton").pack(side="left", padx=5)
        ttk.Button(toolbar, text="Ajustar", command=lambda: self.apply_mode("Ajustar"), style="Template.Secondary.TButton").pack(side="left", padx=5)
        ttk.Button(toolbar, text="Restablecer", command=lambda *a, _fn=self.reset_cells: _fn(*a), style="Template.Secondary.TButton").pack(side="left", padx=5)
        ttk.Button(toolbar, text="Deshacer", command=lambda *a, _fn=self.undo: _fn(*a), style="Template.Secondary.TButton").pack(side="left", padx=(22, 5))
        ttk.Button(toolbar, text="Rehacer", command=lambda *a, _fn=self.redo: _fn(*a), style="Template.Secondary.TButton").pack(side="left", padx=5)
        ttk.Button(toolbar, text="Convertir a libre", command=lambda *a, _fn=self.convert_to_free_plancha: _fn(*a), style="Template.Primary.TButton").pack(side="right", padx=12)

        body = tk.Frame(self, background=COLORS.background)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        left = tk.Frame(body, background=COLORS.panel, width=250, highlightbackground=COLORS.border, highlightthickness=1)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.grid_propagate(False)
        tk.Label(left, text="IMÁGENES", background=COLORS.panel, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 12, "bold")).pack(anchor="w", padx=12, pady=(13, 5))
        tk.Label(left, text="Recursos del proyecto · no se duplican archivos", background=COLORS.panel, foreground=COLORS.muted, wraplength=220, justify="left", font=(UI_FONT, 10)).pack(anchor="w", padx=12, pady=(0, 8))
        self.resources_canvas = tk.Canvas(left, background=COLORS.panel, highlightthickness=0, borderwidth=0)
        resource_scroll = ttk.Scrollbar(left, orient="vertical", command=lambda *a, _fn=self.resources_canvas.yview: _fn(*a))
        self.resources_canvas.configure(yscrollcommand=resource_scroll.set)
        resource_scroll.pack(side="right", fill="y", pady=(0, 8))
        self.resources_canvas.pack(fill="both", expand=True, padx=(8, 0), pady=(0, 8))
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
        ttk.Button(footer, text="Guardar proyecto", command=lambda *a, _fn=self.save_project: _fn(*a), style="Template.Primary.TButton").pack(side="right", padx=4)
        ttk.Button(footer, text="Exportar · etapa 4", state="disabled", style="Template.Secondary.TButton").pack(side="right", padx=4)

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
        dialog.geometry("760x470")
        dialog.resizable(False, False)
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
        grid = tk.Frame(dialog, background=COLORS.background)
        grid.pack(fill="both", expand=True, padx=18, pady=(0, 12))
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
            card.grid(row=row, column=column, sticky="nsew", padx=5, pady=5)
            tk.Label(card, text=str(pattern["title"]), background=COLORS.panel_elevated, foreground=COLORS.text, font=(IDENTITY_FONT, 11, "bold")).pack(anchor="w", padx=12, pady=(12, 3))
            tk.Label(card, text=str(pattern["detail"]), background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 9)).pack(anchor="w", padx=12)
            ratio = self.project.cell_ratio(pattern_id)
            tk.Label(card, text=f"Celda {ratio:.2f} de proporción", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 9)).pack(anchor="w", padx=12, pady=(4, 8))
            ttk.Button(card, text="Usar patrón", command=lambda value=pattern_id: apply(value), style="Template.Primary.TButton").pack(anchor="w", padx=12, pady=(0, 12))

        ttk.Button(dialog, text="Cancelar", command=dialog.destroy, style="Template.Secondary.TButton").pack(anchor="e", padx=22, pady=(0, 18))

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

    def convert_to_free_plancha(self):
        """Entrega la plancha regular al editor libre conservando cada casilla."""
        if not any(cell.resource_id for cell in self.project.cells):
            messagebox.showinfo("Plancha libre", "Primero agregá o asigná al menos un diseño al patrón.", parent=self)
            return
        if not messagebox.askyesno(
            "Convertir a libre",
            "Se conservará el patrón actual con sus medidas y límites. Después podrás mover los diseños manualmente.\n\n¿Continuar?",
            parent=self,
        ):
            return
        from app.planchas.editor import PlanchaEditor

        project = self.project.to_free_project()
        PlanchaEditor(
            self.master,
            [],
            database=self.database,
            library_images=self.library_images,
            project=project,
            preserve_layout=True,
        )

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
        return next((key for key, box in self._cell_boxes.items() if box[0] <= x <= box[2] and box[1] <= y <= box[3]), None)

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
        key = (cell.cell_id, resource.modified, width, height, cell.frame_mode, round(cell.zoom, 3), round(cell.offset_x, 3), round(cell.offset_y, 3), cell.rotation)
        cached = self._preview_cache.get(key)
        if cached:
            return cached
        try:
            from PIL import Image, ImageTk
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
            card = tk.Frame(self.resources_inner, background="#3c1014" if selected else "#1a1d1e", highlightbackground="#d60916" if selected else "#303436", highlightthickness=1, padx=6, pady=6)
            card.pack(fill="x", padx=3, pady=3)
            thumb = self.resource_thumbnail(resource.resource_id)
            self._resource_photos.append(thumb)
            image_label = tk.Label(card, image=thumb, text="Sin vista previa" if thumb is None else "", compound="center", width=62, height=62, background="#0c0d0e", foreground="#b9a79b")
            image_label.pack(side="left", padx=(0, 7))
            details = tk.Frame(card, background=card.cget("background"))
            details.pack(fill="x")
            tk.Label(details, text=resource.name, background=card.cget("background"), foreground="#fff4ec", wraplength=142, justify="left", font=("Bahnschrift", 9, "bold")).pack(anchor="w")
            tk.Label(details, text=f"Usado: {self.project.usage_count(resource.resource_id)} casilla(s)", background=card.cget("background"), foreground="#c7b6aa", justify="left").pack(anchor="w", pady=(4, 0))
            tk.Label(details, text=f"{resource.width_px} × {resource.height_px} px" if resource.width_px else "Calidad sin verificar", background=card.cget("background"), foreground="#a1bca7", justify="left").pack(anchor="w")
            for widget in (card, image_label, details):
                widget.bind("<Button-1>", lambda _event, value=resource.resource_id: self.select_resource(value))

    def select_resource(self, resource_id: str):
        self.selected_resource_id = resource_id
        self.render_resources()

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
                canvas.create_rectangle(x1 + 2, y1 + 2, x2 - 2, y2 - 2, fill="#ebe8e2", outline="", stipple="gray25")
                canvas.create_text((x1 + x2) // 2, (y1 + y2) // 2, text="Vacío", fill="#8a8179", font=("Bahnschrift", 9, "italic"))
            outline = "#d60916" if cell.cell_id in self.selected_cells else "#55585a"
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

    def save_project(self):
        path = filedialog.asksaveasfilename(title="Guardar plancha regular", defaultextension=".doccione-plantilla.json", filetypes=[("Plancha regular Doccione", "*.doccione-plantilla.json"), ("JSON", "*.json")])
        if not path:
            return
        self.project.save(path)
        messagebox.showinfo("Proyecto guardado", "La plantilla se guardó con referencias a las imágenes originales; no se creó ninguna copia.", parent=self)

    def open_project(self):
        path = filedialog.askopenfilename(title="Abrir plancha regular", filetypes=[("Plancha regular Doccione", "*.doccione-plantilla.json *.json")])
        if not path:
            return
        try:
            self.project = RegularTemplateProject.load(path)
            self.selected_cells.clear()
            self.selected_resource_id = self.project.resources[0].resource_id if self.project.resources else None
            self.history.clear()
            self.future.clear()
            self._source_cache.clear()
            self._preview_cache.clear()
            self.render()
        except Exception as error:
            messagebox.showerror("No se pudo abrir", str(error), parent=self)
