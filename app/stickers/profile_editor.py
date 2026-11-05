"""Editor visual de perfiles de procesamiento para el Creador de Stickers.

Permite al usuario activar / desactivar cada paso del pipeline y ajustar
sus parámetros numéricos sin tocar código.  Los cambios se aplican al
ProcessingProfile activo del StickerProcessor al guardar.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import asdict, replace
from tkinter import ttk
from typing import Callable

from app.stickers.pipeline import ProcessingProfile
from app.ui.theme import COLORS, IDENTITY_FONT, UI_FONT


# ── Definición declarativa de los pasos ──────────────────────────────────────
# Cada entrada describe un paso del pipeline.  El orden aquí es el orden
# que ve el usuario en pantalla (= orden de ejecución del pipeline).
#
# Formato:
#   (título, descripción breve, campo_bool, campo_num | None, unidad, min, max, incremento)

STEPS: list[tuple] = [
    (
        "Rellenar huecos internos",
        "Rellena zonas transparentes completamente encerradas por la silueta.",
        "fill_holes",
        "fill_holes_max_px",
        "px²", 100, 20_000, 100,
    ),
    (
        "Eliminar partículas",
        "Quita regiones opacas aisladas más pequeñas que el área mínima.",
        "remove_particles",
        "remove_particles_min_px",
        "px²", 10, 5_000, 10,
    ),
    (
        "Cerrar canales estrechos",
        "Une los bordes de pasillos y canales más angostos que el ancho máximo.",
        "close_channels",
        "close_channels_mm",
        "mm", 0.5, 10.0, 0.5,
    ),
    (
        "Unir regiones cercanas",
        "Fusiona piezas separadas por menos que la distancia máxima.",
        "merge_regions",
        "merge_regions_mm",
        "mm", 0.5, 10.0, 0.5,
    ),
    (
        "Redondear esquinas",
        "Aplica un radio mínimo a las esquinas agudas del contorno.",
        "round_corners",
        "round_corners_mm",
        "mm", 0.1, 5.0, 0.1,
    ),
    (
        "Eliminar picos",
        "Suprime puntas y salientes agudos mediante análisis del casco convexo.",
        "remove_spikes",
        None, "", 0, 0, 0,
    ),
    (
        "Simplificar y suavizar curvas",
        "Reduce vértices (Douglas-Peucker) y aplica suavizado Chaikin.",
        "simplify_curves",
        "simplify_curves_mm",
        "mm", 0.1, 2.0, 0.1,
    ),
    (
        "Umbral anti-fantasmas (fotos)",
        "Alpha interno por debajo de este valor se descarta completamente. "
        "Elimina zonas difuminadas que no pertenecen al sujeto.",
        None,
        "ghost_threshold",
        "0–255", 64, 240, 4,
    ),
    (
        "Suavidad del borde exterior",
        "Ancho en píxeles de la franja perimetral donde se conserva "
        "la transición suave (cabello, bordes difusos).",
        None,
        "edge_feather_px",
        "px", 0, 12, 1,
    ),
    (
        "Suavizar borde de la máscara",
        "Radio del desenfoque gaussiano aplicado antes de construir los bordes.",
        None,               # este campo no tiene bool independiente
        "smooth_px",
        "px", 0, 30, 1,
    ),
    (
        "Limpieza del borde blanco final",
        "0 conserva todos los detalles; 1 elimina microburbujas; 2 suaviza más para fondos con halo.",
        None,
        "final_white_polish_strength",
        "nivel", 0, 2, 1,
    ),
    (
        "Borde blanco exterior",
        "Ancho del borde blanco alrededor del diseño (capa de impresión).",
        None,
        "final_white_px",
        "px", 10, 80, 1,
    ),
    (
        "Borde negro de registro",
        "Grosor del anillo negro de control/troquel.",
        None,
        "control_black_px",
        "px", 1, 10, 1,
    ),
]

# Perfil con todos los parámetros en sus valores por defecto.
_DEFAULT_PROFILE = ProcessingProfile()


class _StepRow:
    """Fila visual de un paso: checkbox + label + campo numérico + unidad."""

    def __init__(self, parent: tk.Frame, title: str, description: str,
                 bool_field: str | None, num_field: str | None,
                 unit: str, min_val: float, max_val: float, increment: float,
                 profile: ProcessingProfile):
        self.bool_field = bool_field
        self.num_field  = num_field
        self._increment = increment
        self._min       = min_val
        self._max       = max_val

        # Variables Tk
        default_bool = bool(getattr(profile, bool_field)) if bool_field else None
        default_num  = getattr(profile, num_field) if num_field else None

        self.bool_var = tk.BooleanVar(value=default_bool) if bool_field else None
        self.num_var  = tk.StringVar(value=str(default_num)) if num_field else None

        # ── Contenedor de la fila ─────────────────────────────────────────
        self.frame = tk.Frame(parent, background=COLORS.panel_elevated,
                              highlightthickness=1,
                              highlightbackground=COLORS.border)
        self.frame.pack(fill="x", padx=0, pady=(0, 4))

        # Columna izquierda: checkbox (o espacio) + nombre + descripción
        left = tk.Frame(self.frame, background=COLORS.panel_elevated)
        left.pack(side="left", fill="x", expand=True, padx=(10, 6), pady=8)

        if self.bool_var is not None:
            cb = ttk.Checkbutton(left, variable=self.bool_var,
                                 style="Step.TCheckbutton",
                                 command=lambda *a, _fn=self._on_toggle: _fn(*a))
            cb.pack(side="left", padx=(0, 6))
        else:
            # Espacio fijo para alinear con las filas que sí tienen checkbox
            tk.Frame(left, width=22, background=COLORS.panel_elevated).pack(
                side="left", padx=(0, 6))

        text_col = tk.Frame(left, background=COLORS.panel_elevated)
        text_col.pack(side="left", fill="x", expand=True)
        tk.Label(text_col, text=title, background=COLORS.panel_elevated,
                 foreground=COLORS.text,
                 font=(UI_FONT, 10, "bold")).pack(anchor="w")
        tk.Label(text_col, text=description, background=COLORS.panel_elevated,
                 foreground=COLORS.muted,
                 font=(UI_FONT, 8), wraplength=380,
                 justify="left").pack(anchor="w", pady=(1, 0))

        # Columna derecha: campo numérico + unidad
        if self.num_var is not None:
            right = tk.Frame(self.frame, background=COLORS.panel_elevated)
            right.pack(side="right", padx=(6, 12), pady=8)

            tk.Label(right, text=unit, background=COLORS.panel_elevated,
                     foreground=COLORS.muted,
                     font=(UI_FONT, 9)).pack(side="right", padx=(4, 0))

            is_int = isinstance(default_num, int)
            self._spinbox = ttk.Spinbox(
                right,
                textvariable=self.num_var,
                from_=min_val, to=max_val,
                increment=increment,
                width=7,
                format="%.0f" if is_int else "%.2f",
            )
            self._spinbox.pack(side="right")

            # Etiqueta descriptiva encima del campo
            tk.Label(right, text="Valor", background=COLORS.panel_elevated,
                     foreground=COLORS.disabled,
                     font=(UI_FONT, 8)).pack(side="top", anchor="e",
                                             pady=(0, 2))

        # Estado inicial
        self._on_toggle()

    # ─────────────────────────────────────────────────────────────────────────

    def _on_toggle(self):
        """Deshabilita el campo numérico cuando el paso está desactivado."""
        if self.bool_var is None or self.num_var is None:
            return
        enabled = self.bool_var.get()
        if hasattr(self, "_spinbox"):
            self._spinbox.configure(
                state="normal" if enabled else "disabled")

    def get_bool(self) -> bool | None:
        return self.bool_var.get() if self.bool_var else None

    def get_num(self) -> float | int | None:
        if self.num_var is None:
            return None
        raw = self.num_var.get().replace(",", ".")
        try:
            val = float(raw)
            val = max(self._min, min(self._max, val))
            # Devolver int si el campo original era int
            default = getattr(_DEFAULT_PROFILE, self.num_field)
            return int(round(val)) if isinstance(default, int) else val
        except ValueError:
            return getattr(_DEFAULT_PROFILE, self.num_field)

    def reset_to_default(self):
        if self.bool_var and self.bool_field:
            self.bool_var.set(bool(getattr(_DEFAULT_PROFILE, self.bool_field)))
        if self.num_var and self.num_field:
            self.num_var.set(str(getattr(_DEFAULT_PROFILE, self.num_field)))
        self._on_toggle()


# ─────────────────────────────────────────────────────────────────────────────

class ProcessingProfileEditor(tk.Toplevel):
    """Ventana de configuración del perfil de procesamiento.

    Parámetros
    ──────────
    master      widget padre (normalmente StickerStudio)
    profile     ProcessingProfile actual (se usa como estado inicial)
    on_save     callback(ProcessingProfile) llamado al guardar
    """

    def __init__(self, master: tk.Widget, profile: ProcessingProfile,
                 on_save: Callable[[ProcessingProfile], None]):
        super().__init__(master)
        self.title("Configurar perfil de procesamiento")
        self.geometry("640x740")
        self.minsize(540, 520)
        self.configure(background=COLORS.background)
        self.transient(master)
        self.grab_set()
        self.resizable(True, True)

        self._profile  = profile
        self._on_save  = on_save
        self._rows: list[_StepRow] = []
        self._name_var = tk.StringVar(value=profile.name)

        self._build()
        self.bind("<Escape>", lambda _e: self.destroy())

    # ─────────────────────────────────────────────────────────────────────────

    def _build(self):
        # ── Encabezado ────────────────────────────────────────────────────
        header = tk.Frame(self, background=COLORS.panel,
                          highlightthickness=1,
                          highlightbackground=COLORS.border)
        header.pack(fill="x", padx=14, pady=(14, 0))

        title_col = tk.Frame(header, background=COLORS.panel)
        title_col.pack(side="left", padx=14, pady=12, fill="x", expand=True)

        tk.Label(title_col, text="PERFIL DE PROCESAMIENTO",
                 background=COLORS.panel, foreground=COLORS.text,
                 font=(IDENTITY_FONT, 16, "bold")).pack(anchor="w")
        tk.Label(
            title_col,
            text="Activá o desactivá cada paso y ajustá sus parámetros. "
                 "Los cambios se aplican al procesar nuevos stickers.",
            background=COLORS.panel, foreground=COLORS.muted,
            font=(UI_FONT, 9), wraplength=440, justify="left",
        ).pack(anchor="w", pady=(3, 0))

        # Campo de nombre del perfil
        name_row = tk.Frame(header, background=COLORS.panel)
        name_row.pack(fill="x", padx=14, pady=(6, 12))
        tk.Label(name_row, text="Nombre del perfil",
                 background=COLORS.panel, foreground=COLORS.muted,
                 font=(UI_FONT, 9)).pack(side="left", padx=(0, 8))
        ttk.Entry(name_row, textvariable=self._name_var,
                  width=34).pack(side="left")

        # ── Área de pasos con scroll ──────────────────────────────────────
        scroll_container = tk.Frame(self, background=COLORS.background)
        scroll_container.pack(fill="both", expand=True,
                              padx=14, pady=(10, 0))

        canvas = tk.Canvas(scroll_container, background=COLORS.background,
                           highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_container, orient="vertical",
                                  command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._steps_frame = tk.Frame(canvas, background=COLORS.background)
        self._window_id = canvas.create_window(
            (0, 0), window=self._steps_frame, anchor="nw")

        def _on_frame_configure(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(e):
            canvas.itemconfigure(self._window_id, width=e.width)

        self._steps_frame.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(
                        -1 if e.delta > 0 else 1, "units"))

        # ── Sección "Pipeline de la máscara" ─────────────────────────────
        self._section("PIPELINE DE LA MÁSCARA",
                      "Pasos que transforman la selección inicial en un "
                      "contorno limpio listo para producción.")

        for step in STEPS:
            title, desc, bool_f, num_f, unit, mn, mx, inc = step
            row = _StepRow(
                self._steps_frame, title, desc,
                bool_f, num_f, unit, mn, mx, inc,
                self._profile,
            )
            self._rows.append(row)

        # ── Barra de botones ──────────────────────────────────────────────
        bar = tk.Frame(self, background=COLORS.panel,
                       highlightthickness=1,
                       highlightbackground=COLORS.border)
        bar.pack(fill="x", padx=14, pady=14)

        ttk.Button(bar, text="Restablecer valores por defecto",
               command=lambda *a, _fn=self._reset: _fn(*a),
               style="Secondary.TButton").pack(side="left", padx=(10, 3),
                               pady=10)
        ttk.Button(bar, text="Cancelar",
               command=lambda *a, _fn=self.destroy: _fn(*a),
               style="Secondary.TButton").pack(side="right", padx=(3, 10),
                               pady=10)
        ttk.Button(bar, text="Guardar y aplicar",
               command=lambda *a, _fn=self._save: _fn(*a),
               style="Primary.TButton").pack(side="right", padx=3, pady=10)

    def _section(self, title: str, subtitle: str):
        f = tk.Frame(self._steps_frame, background=COLORS.background)
        f.pack(fill="x", pady=(8, 6))
        tk.Label(f, text=title, background=COLORS.background,
                 foreground=COLORS.wine_active,
                 font=(IDENTITY_FONT, 11, "bold")).pack(anchor="w", padx=2)
        tk.Label(f, text=subtitle, background=COLORS.background,
                 foreground=COLORS.muted,
                 font=(UI_FONT, 8), wraplength=560,
                 justify="left").pack(anchor="w", padx=2, pady=(2, 4))

    # ─────────────────────────────────────────────────────────────────────────

    def _collect(self) -> ProcessingProfile:
        """Lee todos los widgets y construye un ProcessingProfile nuevo."""
        kwargs: dict = {"name": self._name_var.get().strip()
                        or _DEFAULT_PROFILE.name}
        for row in self._rows:
            if row.bool_field and row.bool_var is not None:
                kwargs[row.bool_field] = row.get_bool()
            if row.num_field and row.num_var is not None:
                kwargs[row.num_field] = row.get_num()
        # Copiar todos los demás campos del perfil actual sin modificar.
        current = asdict(self._profile)
        current.update(kwargs)
        return ProcessingProfile(**current)

    def _save(self):
        profile = self._collect()
        self._on_save(profile)
        self.grab_release()
        self.destroy()

    def _reset(self):
        for row in self._rows:
            row.reset_to_default()
        self._name_var.set(_DEFAULT_PROFILE.name)
