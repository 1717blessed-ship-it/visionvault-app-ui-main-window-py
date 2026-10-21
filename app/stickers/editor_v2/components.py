"""Componentes visuales de Sticker Studio 2.0."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageTk

from app.ui.theme import COLORS, IDENTITY_FONT, UI_FONT
from .adapter import PipelineViewAdapter
from .session import DISPLAY_STATUS


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text, self.popup = widget, text, None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _event=None):
        if self.popup or not self.text:
            return
        self.popup = tk.Toplevel(self.widget)
        self.popup.wm_overrideredirect(True)
        self.popup.wm_geometry(f"+{self.widget.winfo_rootx()+12}+{self.widget.winfo_rooty()+self.widget.winfo_height()+6}")
        tk.Label(self.popup, text=self.text, background="#fff7cf", foreground="#181818",
                 relief="solid", borderwidth=1, font=(UI_FONT, 8), padx=6, pady=3).pack()

    def _hide(self, _event=None):
        if self.popup:
            self.popup.destroy(); self.popup = None


def add_tooltip(widget, text):
    widget._sticker_tooltip = Tooltip(widget, text)
    return widget


def section_label(parent, text):
    return tk.Label(parent, text=text.upper(), background=COLORS.panel,
                    foreground=COLORS.muted, font=(IDENTITY_FONT, 9, "bold"))


class ToolRail(tk.Frame):
    TOOLS = (
        ("Seleccionar", "select", True),
        ("Procesar este sticker", "auto", True),
        ("Reprocesar fondo", "background", True),
        ("Pincel restaurar", "mask", True),
        ("Borrador", "erase", True),
        ("Proteger zonas", "protect", True),
        ("Refinar contorno", "refine", True),
        ("Seleccionar objetos", "objects", True),
        ("Contorno", "cut", True),
        ("Zoom / mover", "zoom", True),
    )

    def __init__(self, master, command):
        super().__init__(master, background=COLORS.panel, width=184,
                         highlightthickness=1, highlightbackground=COLORS.border)
        self.pack_propagate(False)
        section_label(self, "Herramientas").pack(anchor="w", padx=12, pady=(14, 8))
        self.buttons = {}
        for label, identifier, enabled in self.TOOLS:
            button = ttk.Button(self, text=label, command=lambda key=identifier: command(key),
                                style="Secondary.TButton")
            button.pack(fill="x", padx=8, pady=3)
            if not enabled:
                button.state(["disabled"])
            self.buttons[identifier] = button
            add_tooltip(button, label if enabled else f"{label}: no disponible en este sprint")
        self.active = None

    def set_active(self, identifier: str | None):
        self.active = identifier
        for key, button in self.buttons.items():
            button.configure(style="Primary.TButton" if key == identifier else "Secondary.TButton")


class Inspector(tk.Frame):
    def __init__(self, master, studio, on_apply, on_preview, on_undo, on_redo,
                 on_reset, on_approve_reference, on_review, on_send):
        super().__init__(master, background=COLORS.panel, width=280,
                         highlightthickness=1, highlightbackground=COLORS.border)
        self.pack_propagate(False)
        self.studio, self.on_apply = studio, on_apply
        self.scroll_canvas = tk.Canvas(self, background=COLORS.panel, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.scroll_canvas.yview)
        self.scroll_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.scroll_canvas.pack(fill="both", expand=True)
        self.content = tk.Frame(self.scroll_canvas, background=COLORS.panel)
        self._content_window = self.scroll_canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda _e: self.scroll_canvas.configure(
            scrollregion=self.scroll_canvas.bbox("all")))
        self.scroll_canvas.bind("<Configure>", lambda e: self.scroll_canvas.itemconfigure(
            self._content_window, width=e.width))
        self.scroll_canvas.bind("<MouseWheel>", self._wheel)
        self.content.bind("<MouseWheel>", self._wheel)
        section_label(self.content, "Inspector").pack(anchor="w", padx=14, pady=(14, 8))
        self.name = tk.StringVar(value="Sin selección")
        tk.Label(self.content, textvariable=self.name, wraplength=245, justify="left",
                 background=COLORS.panel, foreground=COLORS.text,
                 font=(UI_FONT, 10, "bold")).pack(anchor="w", padx=14)
        self.dimensions = tk.StringVar(value="—")
        self.resolution = tk.StringVar(value="—")
        self.quality_state = tk.StringVar(value="Sin procesar")
        self.indicators = tk.StringVar(value="")
        for title, variable in (("Tamaño físico", self.dimensions),
                                ("Resolución efectiva", self.resolution),
                                ("Estado de calidad", self.quality_state)):
            section_label(self.content, title).pack(anchor="w", padx=14, pady=(14, 2))
            tk.Label(self.content, textvariable=variable, background=COLORS.panel,
                     foreground=COLORS.text, font=(UI_FONT, 9)).pack(anchor="w", padx=14)
        tk.Label(self.content, textvariable=self.indicators, wraplength=245, justify="left",
                 background=COLORS.panel, foreground=COLORS.warning,
                 font=(UI_FONT, 8)).pack(anchor="w", padx=14, pady=(8, 0))

        section_label(self.content, "Configuración").pack(anchor="w", padx=14, pady=(18, 6))
        self._scale("Contraer selección (mm)", studio._v2_contraction_mm,
                    0, 2, .1, on_preview)
        self._scale("Expandir selección (mm)", studio._v2_expansion_mm,
                    0, 2, .1, on_preview)
        self._field("Borde blanco (mm)", studio._v2_border_mm)
        self._scale("Suavizado del borde (mm)", studio._v2_smoothing_mm,
                    0, 1, .05, on_preview)
        self._scale("Tamaño del pincel (px)", studio._v2_brush_size,
                    1, 160, 1, lambda: None)
        self._scale("Dureza", studio._v2_brush_hardness,
                    0, 1, .05, lambda: None)
        self._scale("Opacidad", studio._v2_brush_opacity,
                    0, 1, .05, lambda: None)
        self._combo("Mostrar selección", studio._v2_selection_view,
                    ("Ambas", "Original", "Contraída"), on_preview)
        self._field("Corte interior (mm)", studio.cut_inset)
        self._combo("Tratamiento del borde", studio._v2_border_treatment,
                    ("Automático", "Conservar y limpiar", "Reemplazar", "Agregar nuevo"))
        self._combo("Tratamiento del fondo", studio.processing_mode,
                    ("Automático", "Fondo uniforme", "Foto / sujeto", "Sticker existente"))
        self._combo("Calidad", studio._v2_quality,
                    ("Rápida", "Balanceada", "Comercial", "Premium"))
        apply_button = ttk.Button(self.content, text="Aplicar contracción y generar borde", command=on_apply,
                                  style="Primary.TButton")
        apply_button.pack(fill="x", padx=14, pady=(18, 5))
        add_tooltip(apply_button, "Guarda la corrección manual y reprocesa desde la máscara base.")
        history = tk.Frame(self.content, background=COLORS.panel)
        history.pack(fill="x", padx=14, pady=3)
        undo_button = ttk.Button(history, text="Deshacer", command=on_undo, style="Secondary.TButton")
        undo_button.pack(side="left", fill="x", expand=True, padx=(0, 2))
        redo_button = ttk.Button(history, text="Rehacer", command=on_redo, style="Secondary.TButton")
        redo_button.pack(side="left", fill="x", expand=True, padx=(2, 0))
        reset_button = ttk.Button(self.content, text="Restablecer edición", command=on_reset, style="Secondary.TButton")
        reset_button.pack(fill="x", padx=14, pady=3)
        section_label(self.content, "Control de calidad avanzado").pack(anchor="w", padx=14, pady=(16, 4))
        reference_button = ttk.Button(self.content, text="Aprobar máscara de referencia", command=on_approve_reference, style="Secondary.TButton")
        reference_button.pack(fill="x", padx=14, pady=3)
        review_button = ttk.Button(self.content, text="Revisar master actual",
                                   command=on_review, style="Primary.TButton")
        review_button.pack(fill="x", padx=14, pady=(10, 3))
        send_button = ttk.Button(self.content, text="Enviar a Últimos Procesados",
                                 command=on_send, style="Secondary.TButton")
        send_button.pack(fill="x", padx=14, pady=3)
        for button, tip in ((undo_button, "Deshace la última operación manual."),
                            (redo_button, "Rehace la última operación deshecha."),
                            (reset_button, "Vuelve a la máscara base sin modificar el original."),
                            (reference_button, "Requiere confirmación humana y genera la comparación de referencia."),
                            (review_button, "Valida el master actual para permitir su exportación."),
                            (send_button, "Envía una copia del trabajo a la bandeja de revisión sin cerrar esta sesión.")):
            add_tooltip(button, tip)
        tk.Label(self.content, text="La aprobación siempre es explícita.", background=COLORS.panel,
                 foreground=COLORS.warning, font=(UI_FONT, 8)).pack(anchor="w", padx=14, pady=5)

    def _wheel(self, event):
        self.scroll_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _field(self, label, variable):
        tk.Label(self.content, text=label, background=COLORS.panel, foreground=COLORS.muted,
                 font=(UI_FONT, 8)).pack(anchor="w", padx=14, pady=(7, 2))
        ttk.Entry(self.content, textvariable=variable).pack(fill="x", padx=14)

    def _scale(self, label, variable, lower, upper, resolution, command):
        row = tk.Frame(self.content, background=COLORS.panel)
        row.pack(fill="x", padx=14, pady=(7, 0))
        tk.Label(row, text=label, background=COLORS.panel, foreground=COLORS.muted,
                 font=(UI_FONT, 8)).pack(side="left")
        value = tk.Label(row, width=5, anchor="e", background=COLORS.panel,
                         foreground=COLORS.text, font=(UI_FONT, 8))
        value.pack(side="right")
        def changed(raw):
            rounded = round(round(float(raw) / resolution) * resolution, 2)
            variable.set(rounded)
            value.configure(text=f"{rounded:.2f}")
            command()
        scale = tk.Scale(self.content, variable=variable, from_=lower, to=upper,
                         resolution=resolution, orient="horizontal", showvalue=False,
                         command=changed, background=COLORS.panel,
                         foreground=COLORS.text, troughcolor=COLORS.field,
                         highlightthickness=0)
        scale.pack(fill="x", padx=14)
        def sync_value(*_args):
            try:
                value.configure(text=f"{float(variable.get()):.2f}")
            except (TypeError, ValueError, tk.TclError):
                value.configure(text="—")
        variable.trace_add("write", sync_value)
        sync_value()

    def _combo(self, label, variable, values, command=None):
        tk.Label(self.content, text=label, background=COLORS.panel, foreground=COLORS.muted,
                 font=(UI_FONT, 8)).pack(anchor="w", padx=14, pady=(7, 2))
        combo = ttk.Combobox(self.content, textvariable=variable, values=values,
                             state="readonly")
        combo.pack(fill="x", padx=14)
        if command:
            combo.bind("<<ComboboxSelected>>", lambda _event: command())

    def update_job(self, job):
        if not job:
            self.name.set("Sin selección")
            self.dimensions.set("—")
            self.resolution.set("—")
            self.quality_state.set("Sin procesar")
            self.indicators.set("")
            return
        self.name.set(Path(job.get("source_path", "")).name)
        metrics = PipelineViewAdapter.metrics(job, self.studio.profile.dpi)
        w, h = metrics["millimeters"]
        px = metrics["pixels"]
        dpi = metrics["dpi"]
        self.dimensions.set(f"{w:.1f} × {h:.1f} mm  ·  {px[0]} × {px[1]} px")
        self.resolution.set(f"{dpi[0]:.0f} × {dpi[1]:.0f} ppp")
        result = job.get("result")
        self.quality_state.set(getattr(result, "quality_status", None) or job.get("status", "Pendiente"))
        flags = []
        if job.get("v2_mask_document") and job["v2_mask_document"].operations:
            flags.append("● Máscara modificada manualmente")
        if job.get("approved_mask_reference"):
            flags.append("✓ Referencia humana aprobada")
        if job.get("reviewed_master_sha256"):
            flags.append("✓ Master revisado")
        if job.get("sent_to_processed"):
            flags.append("✓ Enviado a Últimos Procesados")
        analysis = getattr(result, "analysis", {}) if result else {}
        border = analysis.get("border_treatment") or {}
        if border.get("effective") and border.get("effective") != "Automático":
            flags.append(f"Borde: {border['effective']}")
        report = analysis.get("quality_report") or {}
        for warning in (report.get("warnings") or [])[:2]:
            flags.append("⚠ " + (warning.get("message", "Requiere revisión") if isinstance(warning, dict) else str(warning)))
        self.indicators.set("\n".join(flags))


class ThumbnailTray(tk.Frame):
    def __init__(self, master, on_select, on_remove=None, on_process=None):
        super().__init__(master, background=COLORS.panel, height=132,
                         highlightthickness=1, highlightbackground=COLORS.border)
        self.pack_propagate(False)
        self.on_select = on_select
        self.on_remove, self.on_process = on_remove, on_process
        self.canvas = tk.Canvas(self, height=116, background=COLORS.panel, highlightthickness=0)
        self.scroll = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=self.scroll.set)
        self.canvas.pack(fill="both", expand=True)
        self.scroll.pack(fill="x")
        self.inner = tk.Frame(self.canvas, background=COLORS.panel)
        self.window = self.canvas.create_window(0, 0, anchor="nw", window=self.inner)
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._photos = []
        self._signature = None
        self.canvas.bind("<Shift-MouseWheel>", self._horizontal_wheel)
        self.canvas.bind("<MouseWheel>", self._horizontal_wheel)
        self.menu = tk.Menu(self, tearoff=False)
        self.menu.add_command(label="Procesar seleccionados", command=lambda: self.on_process and self.on_process())
        self.menu.add_command(label="Quitar de esta sesión", command=lambda: self.on_remove and self.on_remove())

    def _horizontal_wheel(self, event):
        self.canvas.xview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def refresh(self, jobs, selected):
        selected_set = set(selected if isinstance(selected, (set, list, tuple)) else
                           (() if selected is None else (selected,)))
        signature = tuple((j.get("source_path"), j.get("status"), id(j.get("result")), j.get("error")) for j in jobs), tuple(sorted(selected_set))
        if signature == self._signature:
            return
        self._signature = signature
        for child in self.inner.winfo_children():
            child.destroy()
        self._photos.clear()
        for index, job in enumerate(jobs):
            active = index in selected_set
            color = COLORS.primary_dark if active else COLORS.panel_elevated
            card = tk.Frame(self.inner, width=150, height=102, background=color,
                            highlightthickness=2 if active else 1,
                            highlightbackground=COLORS.primary_active if active else COLORS.border)
            card.pack(side="left", padx=5, pady=7)
            card.pack_propagate(False)
            photo = self._thumbnail(job)
            if photo:
                self._photos.append(photo)
                label = tk.Label(card, image=photo, background=color)
            else:
                label = tk.Label(card, text="SIN VISTA", background=color,
                                 foreground=COLORS.disabled, font=(UI_FONT, 8))
            label.pack(side="left", padx=5, pady=5)
            meta = tk.Frame(card, background=color)
            meta.pack(fill="both", expand=True, padx=(0, 4), pady=5)
            tk.Label(meta, text=Path(job.get("source_path", "")).name[:15], background=color,
                     foreground=COLORS.text, font=(UI_FONT, 8, "bold")).pack(anchor="w")
            status = DISPLAY_STATUS.get(job.get("status"), job.get("status", "Pendiente"))
            tk.Label(meta, text=("⚠ " if job.get("status") == "Error" else "") + status, background=color,
                     foreground=COLORS.warning if job.get("status") in {"Procesando", "Error"} else COLORS.muted,
                     font=(UI_FONT, 8)).pack(anchor="w")
            result = job.get("result")
            tk.Label(meta, text=getattr(result, "quality_status", "—"), background=color,
                     foreground=COLORS.muted, font=(UI_FONT, 8)).pack(anchor="w")
            for widget in (card, label, meta, *meta.winfo_children()):
                widget.bind("<Button-1>", lambda e, i=index: self.on_select(i, e))
                widget.bind("<Button-3>", lambda e, i=index: self._context(e, i))

    def _context(self, event, index):
        self.on_select(index, event, context=True)
        self.menu.tk_popup(event.x_root, event.y_root)

    @staticmethod
    def _thumbnail(job):
        path = PipelineViewAdapter.preview_source(job, "Final").path
        if not path:
            return None
        try:
            with Image.open(path) as source:
                image = source.convert("RGBA").copy()
            image.thumbnail((58, 78), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(image)
        except Exception:
            return None
