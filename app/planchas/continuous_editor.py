"""Interfaz de la etapa 1 para armar producciones continuas de planchas A4."""

from __future__ import annotations

import base64
import json
import os
import threading
import tkinter as tk
import unicodedata
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from app.planchas.continuous_model import (
    A4_HEIGHT_CM,
    CONTINUOUS_WIDTH_CM,
    MAX_CONTINUOUS_LENGTH_CM,
    PRODUCTION_PROFILES,
    ContinuousProduction,
    ContinuousSection,
    epson_scale_for_sections,
)
from app.planchas.experimental_roll import ExperimentalRollBlock, render_roll_block
from app.ui.theme import COLORS, IDENTITY_FONT, UI_FONT, configure_menu, configure_plancha_styles


class ContinuousProductionEditor(tk.Frame):
    """Arma una tira visual sin imprimir ni alterar las planchas seleccionadas."""

    def __init__(self, master, database, initial_plancha_id: int | None = None,
                 initial_plancha_ids: list[int] | None = None, open_print_queue=None,
                 on_close=None):
        super().__init__(master)
        self.database = database
        self.open_print_queue = open_print_queue
        self.on_close = on_close
        self.configure(background=COLORS.background)
        self.production = ContinuousProduction.new()
        self._saved_section_ids: set[int] = set()
        # Acepta una plancha individual por compatibilidad y un lote desde el
        # creador de planchas. El lote se agrega al abrir la misma ventana.
        self.initial_plancha_ids = list(dict.fromkeys(initial_plancha_ids or ([] if initial_plancha_id is None else [initial_plancha_id])))
        self.batch_pending_count = 0
        self.available: dict[int, dict] = {}
        self.preview_zoom = 1.0
        self.preview_photo = None
        self.dragged_plancha_id: int | None = None
        self.drag_start: tuple[int, int] | None = None
        self.drag_active = False
        self.drag_indicator = None
        self.name_var = tk.StringVar(value=self.production.name)
        self.summary_var = tk.StringVar()
        # Estado de impresión
        self._strip_png_path: str | None = None
        self._print_spool_job_id: int | None = None
        self._print_status_var = tk.StringVar(value="")
        self._devmode_bytes: bytes | None = None   # DEVMODE guardado tras configurar
        # Al volver a abrir Producción continua se recupera la última tira
        # pendiente. Antes las planchas quedaban reservadas en la base, pero
        # la ventana arrancaba vacía y parecía que habían desaparecido.
        if not self.initial_plancha_ids:
            self._restore_latest_pending_production()
        self.name_var.set(self.production.name)
        self._build()
        self._set_title()
        self.bind("<Configure>", self._on_resize, add="+")
        self.refresh_available()
        if self.initial_plancha_ids:
            self.after_idle(self._add_initial_planchas)
        self.refresh_all()

    def _restore_latest_pending_production(self) -> None:
        """Carga la tira pendiente más reciente que todavía tiene secciones."""
        if not self.database:
            return
        for record in self.database.continuous_productions():
            if record.get("status") != "Pendiente":
                continue
            try:
                data = json.loads(record.get("production_json") or "{}")
                production = ContinuousProduction.from_dict(data, production_id=int(record["id"]))
            except (TypeError, ValueError, AttributeError):
                continue
            if not production.sections:
                continue
            self.production = production
            self._saved_section_ids = {section.plancha_id for section in production.sections}
            self._set_title()
            return

    def _add_initial_planchas(self):
        """Carga el primer tramo y deja el resto del lote disponible."""
        if len(self.initial_plancha_ids) > 1:
            largest_profile = max(PRODUCTION_PROFILES, key=PRODUCTION_PROFILES.get)
            self.production.set_profile(largest_profile)
        capacity = self.production.section_capacity
        for plancha_id in self.initial_plancha_ids[:capacity]:
            self._add_plancha_id(plancha_id, quiet=True)
        self.batch_pending_count = max(0, len(self.initial_plancha_ids) - capacity)
        self.refresh_all()

    def create_automatic_strips(self):
        """Guarda el lote en tiras de hasta cuatro A4, separadas por material."""
        plancha_ids = self.initial_plancha_ids or [int(value) for value in self.available_tree.get_children()]
        records = [self.available.get(plancha_id) for plancha_id in plancha_ids]
        records = [record for record in records if record]
        if not records:
            messagebox.showinfo("Tiras automáticas", "No hay planchas disponibles para organizar.", parent=self)
            return

        groups: dict[str, list[dict]] = {}
        for record in records:
            material = (record.get("material") or record.get("order_material") or "Sin material").strip()
            groups.setdefault(material, []).append(record)
        capacity = max(1, int(MAX_CONTINUOUS_LENGTH_CM // A4_HEIGHT_CM))
        strip_count = sum((len(group) + capacity - 1) // capacity for group in groups.values())
        if not messagebox.askyesno(
            "Crear tiras automáticas",
            f"Se crearán {strip_count} tira(s) para {len(records)} plancha(s), separadas por material.",
            parent=self,
        ):
            return

        largest_profile = max(PRODUCTION_PROFILES, key=PRODUCTION_PROFILES.get)
        base_name = self.name_var.get().strip() or "Producción continua"
        created: list[ContinuousProduction] = []
        strip_number = 0
        for material, group in groups.items():
            for start in range(0, len(group), capacity):
                strip_number += 1
                production = ContinuousProduction.new(largest_profile)
                production.name = f"{base_name} · Tira {strip_number}"
                for record in group[start:start + capacity]:
                    plancha_id = int(record["id"])
                    production.add_section(ContinuousSection(
                        plancha_id=plancha_id,
                        name=record.get("name") or f"Plancha {plancha_id}",
                        final_png_path=record.get("final_png_path") or "",
                        project_path=record.get("project_path") or "",
                        order_id=record.get("order_id"),
                        client=record.get("order_client") or "",
                        material=material,
                        stickers=self._sticker_count(record),
                    ))
                production.production_id = self.database.save_continuous_production(
                    production.name, production.mode, production.width_cm, production.length_cm,
                    material, json.dumps(production.to_dict(), ensure_ascii=False),
                )
                for section in production.sections:
                    self.database.save_plancha_status_before_continuous(section.plancha_id)
                    self.database.update_plancha_production_status(section.plancha_id, "usada_en_continua")
                created.append(production)

        self.production = created[0]
        self._saved_section_ids = {section.plancha_id for section in self.production.sections}
        self.initial_plancha_ids = []
        self.batch_pending_count = 0
        self.name_var.set(self.production.name)
        self._set_title()
        self.refresh_available()
        self.refresh_all()
        messagebox.showinfo(
            "Tiras automáticas creadas",
            f"Se guardaron {len(created)} tira(s). La primera quedó abierta; las demás están disponibles en 'Abrir pendiente'.",
            parent=self,
        )

    def _build(self):
        configure_plancha_styles(self)
        header = tk.Frame(self, background=COLORS.background)
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        header.columnconfigure(0, weight=1)
        tk.Label(
            header, text="PRODUCCIÓN CONTINUA", background=COLORS.background, foreground=COLORS.text,
            font=(IDENTITY_FONT, 18, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.production_id_var = tk.StringVar(value="Tira nueva")
        tk.Label(
            header, textvariable=self.production_id_var, background=COLORS.background,
            foreground=COLORS.muted, font=(UI_FONT, 9),
        ).grid(row=1, column=0, sticky="w")
        ttk.Entry(header, textvariable=self.name_var, width=30).grid(row=0, column=1, sticky="ew", padx=(12, 9))
        ttk.Button(header, text="Abrir pendiente", command=lambda *a, _fn=self.open_pending: _fn(*a)).grid(row=0, column=2, sticky="e")
        self.auto_strips_button = ttk.Button(header, text="Crear tiras automáticas", command=self.create_automatic_strips)
        self.auto_strips_button.grid(row=0, column=3, sticky="e", padx=(0, 9))
        if self.open_print_queue:
            ttk.Button(
                header, text="Abrir cola de impresión", command=self.open_print_queue,
            ).grid(row=0, column=4, sticky="e")

        profiles = tk.Frame(self, background=COLORS.background)
        profiles.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))
        self.profile_buttons: dict[str, ttk.Button] = {}
        for label, length in PRODUCTION_PROFILES.items():
            button = ttk.Button(
                profiles, text=f"{label}\n{length:g} cm", command=lambda value=label: self.set_profile(value),
            )
            button.pack(side="left", fill="x", expand=True, padx=(0, 6))
            self.profile_buttons[label] = button
        ttk.Button(profiles, text="Personalizado\nhasta 118,8 cm", command=lambda *a, _fn=self.set_custom_profile: _fn(*a)).pack(
            side="left", fill="x", expand=True
        )

        body = tk.Frame(self, background=COLORS.background)
        body.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 12))
        body.columnconfigure(0, minsize=315)
        body.columnconfigure(1, weight=1, minsize=290)
        body.columnconfigure(2, weight=1, minsize=290)
        body.rowconfigure(0, weight=1)

        source = tk.Frame(body, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        source.grid(row=0, column=0, sticky="nsew")
        tk.Label(source, text="PLANCHAS TERMINADAS", background=COLORS.panel, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 12, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
        tk.Label(source, text="Arrastrá una plancha hacia Secciones de la tira. Solo se muestran planchas guardadas con PNG final.", background=COLORS.panel, foreground=COLORS.muted, justify="left", wraplength=265, font=(UI_FONT, 10)).pack(anchor="w", padx=12, pady=(0, 8))
        available_holder = tk.Frame(source, background=COLORS.panel)
        available_holder.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.available_tree = ttk.Treeview(available_holder, columns=("name", "client", "stickers"), show="headings", selectmode="browse", height=17)
        for key, label, width in (("name", "Plancha", 134), ("client", "Cliente", 90), ("stickers", "Stickers", 55)):
            self.available_tree.heading(key, text=label)
            self.available_tree.column(key, width=width, anchor="center" if key == "stickers" else "w")
        source_scroll = ttk.Scrollbar(available_holder, orient="vertical", command=lambda *a, _fn=self.available_tree.yview: _fn(*a))
        self.available_tree.configure(yscrollcommand=source_scroll.set)
        self.available_tree.tag_configure("photo-print", foreground="#c084fc")
        self.available_tree.pack(side="left", fill="both", expand=True)
        source_scroll.pack(side="right", fill="y")
        self.available_tree.bind("<ButtonPress-1>", self.start_plancha_drag, add="+")
        self.available_tree.bind("<B1-Motion>", self.move_plancha_drag, add="+")
        self.available_tree.bind("<ButtonRelease-1>", self.finish_plancha_drag, add="+")
        ttk.Button(source, text="Agregar a la tira  ›", command=lambda *a, _fn=self.add_selected: _fn(*a)).pack(fill="x", padx=10, pady=(0, 11))

        assembly = tk.Frame(body, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        assembly.grid(row=0, column=1, sticky="nsew", padx=10)
        tk.Label(assembly, text="SECCIONES DE LA TIRA", background=COLORS.panel, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 12, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
        tk.Label(assembly, text="El orden se respeta de arriba hacia abajo.", background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 10)).pack(anchor="w", padx=12, pady=(0, 8))
        section_holder = tk.Frame(assembly, background=COLORS.panel)
        section_holder.pack(fill="both", expand=True, padx=10)
        self.sections_tree = ttk.Treeview(section_holder, columns=("number", "name", "material", "stickers"), show="headings", selectmode="browse", height=17)
        for key, label, width in (("number", "#", 30), ("name", "Plancha", 120), ("material", "Material", 115), ("stickers", "Stickers", 55)):
            self.sections_tree.heading(key, text=label)
            self.sections_tree.column(key, width=width, anchor="center" if key in {"number", "stickers"} else "w")
        section_scroll = ttk.Scrollbar(section_holder, orient="vertical", command=lambda *a, _fn=self.sections_tree.yview: _fn(*a))
        self.sections_tree.configure(yscrollcommand=section_scroll.set)
        self.sections_tree.pack(side="left", fill="both", expand=True)
        section_scroll.pack(side="right", fill="y")
        self.sections_tree.bind("<Button-3>", self.show_section_context_menu)
        self.sections_tree.bind("<Delete>", lambda _event: self.remove_selected())
        section_actions = tk.Frame(assembly, background=COLORS.panel)
        section_actions.pack(fill="x", padx=10, pady=10)
        ttk.Button(section_actions, text="Subir", command=lambda: self.move_selected(-1)).pack(side="left", fill="x", expand=True)
        ttk.Button(section_actions, text="Bajar", command=lambda: self.move_selected(1)).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(section_actions, text="Quitar", command=lambda *a, _fn=self.remove_selected: _fn(*a)).pack(side="left", fill="x", expand=True)

        preview = tk.Frame(body, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        preview.grid(row=0, column=2, sticky="nsew")
        preview_top = tk.Frame(preview, background=COLORS.panel)
        preview_top.pack(fill="x", padx=12, pady=(12, 4))
        tk.Label(preview_top, text="VISTA PREVIA", background=COLORS.panel, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 12, "bold")).pack(side="left")
        ttk.Button(preview_top, text="−", width=3, command=lambda: self.change_zoom(-0.2)).pack(side="right")
        ttk.Button(preview_top, text="+", width=3, command=lambda: self.change_zoom(0.2)).pack(side="right", padx=(0, 4))
        self.preview_canvas = tk.Canvas(preview, background=COLORS.canvas, highlightthickness=0)
        preview_scroll = ttk.Scrollbar(preview, orient="vertical", command=lambda *a, _fn=self.preview_canvas.yview: _fn(*a))
        preview_scroll_x = ttk.Scrollbar(preview, orient="horizontal", command=lambda *a, _fn=self.preview_canvas.xview: _fn(*a))
        self.preview_canvas.configure(yscrollcommand=preview_scroll.set, xscrollcommand=preview_scroll_x.set)
        self.preview_canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(4, 0))
        preview_scroll.pack(side="right", fill="y", padx=(0, 10), pady=(4, 10))
        preview_scroll_x.pack(side="bottom", fill="x", padx=(10, 10), pady=(0, 10))

        footer = tk.Frame(self, background=COLORS.background)
        footer.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))
        footer.columnconfigure(0, weight=1)
        tk.Label(footer, textvariable=self.summary_var, background=COLORS.background, foreground=COLORS.text, justify="left", font=(UI_FONT, 10)).grid(row=0, column=0, sticky="w")
        actions = tk.Frame(footer, background=COLORS.background)
        actions.grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.printer_connection_var = tk.StringVar(value="Impresora: sin configurar")
        self.printer_connection_label = tk.Label(
            actions, textvariable=self.printer_connection_var, background=COLORS.background,
            foreground=COLORS.muted, font=(UI_FONT, 9), anchor="e",
        )
        self.printer_connection_label.pack(side="left", padx=(0, 10))
        self.save_button = ttk.Button(actions, text="Guardar pendiente", command=lambda *a, _fn=self.save_pending: _fn(*a), style="Plancha.Primary.TButton")
        self.save_button.pack(side="right")
        ttk.Button(actions, text="Volver a Planchas", command=self.close).pack(side="right", padx=(0, 7))
        self.printer_settings_button = ttk.Button(
            actions,
            text="Configurar impresora",
            command=lambda *a, _fn=self.open_print_panel: _fn(*a),
            style="Plancha.Secondary.TButton",
        )
        self.printer_settings_button.pack(side="right", padx=(0, 7))
        self.print_button = ttk.Button(actions, text="Imprimir tira", command=lambda *a, _fn=self.open_print_panel: _fn(*a), style="Plancha.Primary.TButton")
        self.print_button.pack(side="right", padx=(0, 7))
        self.experimental_print_button = ttk.Button(
            actions, text="Rollo experimental", command=lambda *a, _fn=self.print_experimental_roll_block: _fn(*a),
            style="Plancha.Secondary.TButton",
        )
        self.experimental_print_button.pack(side="right", padx=(0, 7))
        self.continuity_test_button = ttk.Button(
            actions, text="Prueba continuidad Epson", command=lambda *a, _fn=self.open_epson_continuity_test: _fn(*a),
            style="Plancha.Secondary.TButton",
        )
        self.continuity_test_button.pack(side="right", padx=(0, 7))

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

    def _set_title(self) -> None:
        """Actualiza el identificador de la tira dentro de la pestaña."""
        if hasattr(self, "production_id_var"):
            production_id = self.production.production_id
            self.production_id_var.set(f"Tira #{production_id}" if production_id else "Tira nueva")

    def close(self) -> None:
        """Vuelve al flujo de planchas sin cerrar ni crear ventanas."""
        if self.on_close:
            self.on_close()

    def _refresh_printer_connection(self) -> None:
        """Muestra el estado de la impresora activa sin abrir el diálogo del driver."""
        if not hasattr(self, "printer_connection_var"):
            return
        try:
            from app.printing.windows_print import default_printer, printer_status
            config = self._current_print_config()
            printer_name = (config.get("printer_name") or default_printer() or "").strip()
            profiles = config.get("printer_profiles") or {}
            profile_count = len(profiles) if isinstance(profiles, dict) else 0
            if not printer_name:
                self.printer_connection_var.set("Impresora: sin configurar")
                self.printer_connection_label.configure(foreground=COLORS.muted)
                return
            connected, detail = printer_status(printer_name)
            state = "Conectada" if connected else "No disponible"
            suffix = f" · {profile_count} perfil(es) guardado(s)" if profile_count else ""
            self.printer_connection_var.set(f"{state}: {printer_name}{suffix}")
            self.printer_connection_label.configure(foreground="#39d353" if connected else "#ff4d5a")
        except Exception:
            self.printer_connection_var.set("Estado de impresora no disponible")
            self.printer_connection_label.configure(foreground=COLORS.muted)

    def _on_resize(self, event):
        """Redibuja la tira cuando cambia el espacio útil de la vista previa."""
        if event.widget is self:
            if hasattr(self, "_resize_job"):
                self.after_cancel(self._resize_job)
            self._resize_job = self.after(100, self.render_preview)

    @staticmethod
    def _sticker_count(record: dict) -> int:
        try:
            data = json.loads(record.get("project_json") or "{}")
            return sum(max(1, int(item.get("quantity") or 1)) for item in data.get("items", []))
        except (TypeError, ValueError, AttributeError):
            return 0

    def refresh_available(self):
        self.available.clear()
        self.available_tree.delete(*self.available_tree.get_children())
        for record in self.database.available_planchas_for_continuous():
            plancha_id = int(record["id"])
            self.available[plancha_id] = record
            name = record.get("name") or f"Plancha {plancha_id}"
            client = record.get("order_client") or "-"
            tags = ("photo-print",) if self._is_photo_print(record) else ()
            self.available_tree.insert("", "end", iid=str(plancha_id), values=(name, client, self._sticker_count(record)), tags=tags)

    @staticmethod
    def _is_photo_print(record: dict) -> bool:
        """Da un color propio a las A4 de papel fotográfico en la tira."""
        values = (record.get("material"), record.get("order_material"), record.get("name"))
        text = " ".join(str(value or "") for value in values).lower()
        text = "".join(char for char in unicodedata.normalize("NFD", text)
                       if unicodedata.category(char) != "Mn")
        return "fotograf" in text or "papel foto" in text

    def refresh_sections(self):
        self.sections_tree.delete(*self.sections_tree.get_children())
        for index, section in enumerate(self.production.sections):
            material = section.material or "-"
            self.sections_tree.insert("", "end", iid=str(index), values=(index + 1, section.name, material, section.stickers))

    def refresh_summary(self):
        errors = self.production.validation_errors()
        material = self.production.material_label
        note = f"\nAviso: {errors[0]}" if errors else ""
        if self.batch_pending_count:
            note += f"\nLote: {self.batch_pending_count} plancha(s) más quedaron disponibles para la siguiente tira."
        self.summary_var.set(
            f"{self.production.mode} · {CONTINUOUS_WIDTH_CM:g} × {self.production.length_cm:g} cm\n"
            f"Secciones: {len(self.production.sections)} / {self.production.section_capacity} · "
            f"Stickers: {self.production.total_stickers} · Libre: {self.production.remaining_length_cm:g} cm\n"
            f"Material: {material}{note}"
        )

    def refresh_all(self):
        self.refresh_sections()
        self.refresh_summary()
        self.render_preview()
        enabled = "normal" if self.production.sections and not self.production.validation_errors() else "disabled"
        self.save_button.configure(state=enabled)
        self.print_button.configure(state=enabled)
        self.experimental_print_button.configure(state=enabled)
        self.continuity_test_button.configure(state="normal")
        self._refresh_printer_connection()

    def set_profile(self, mode: str):
        capacity = int((PRODUCTION_PROFILES[mode] + 0.001) // A4_HEIGHT_CM)
        if len(self.production.sections) > capacity:
            messagebox.showwarning(
                "Producción continua",
                f"El modo {mode} admite {capacity} sección(es). Quitá secciones antes de reducir el largo.",
                parent=self,
            )
            return
        self.production.set_profile(mode)
        self.refresh_all()

    def set_custom_profile(self):
        value = simpledialog.askfloat(
            "Largo personalizado", f"Largo de la tira en cm ({A4_HEIGHT_CM:g} a {MAX_CONTINUOUS_LENGTH_CM:g}):",
            initialvalue=self.production.length_cm, minvalue=A4_HEIGHT_CM, maxvalue=MAX_CONTINUOUS_LENGTH_CM, parent=self,
        )
        if value is None:
            return
        section_count = round(value / A4_HEIGHT_CM)
        normalized_length = round(section_count * A4_HEIGHT_CM, 1)
        if abs(value - normalized_length) > 0.05:
            messagebox.showwarning(
                "Largo personalizado",
                "La tira se arma con planchas A4 completas. Elegí un múltiplo de 29,7 cm.",
                parent=self,
            )
            return
        value = normalized_length
        capacity = int((value + 0.001) // A4_HEIGHT_CM)
        if len(self.production.sections) > capacity:
            messagebox.showwarning(
                "Producción continua",
                f"Ese largo admite {capacity} sección(es) A4. Quitá secciones antes de aplicarlo.",
                parent=self,
            )
            return
        self.production.set_profile("Personalizado", value)
        self.refresh_all()

    def add_selected(self):
        selected = self.available_tree.selection()
        if selected:
            self._add_plancha_id(int(selected[0]))

    # Arrastre interno ---------------------------------------------------
    def start_plancha_drag(self, event):
        """Prepara una plancha terminada para soltarla dentro de la tira."""
        row = self.available_tree.identify_row(event.y)
        self.dragged_plancha_id = int(row) if row and row.isdigit() else None
        self.drag_start = (event.x_root, event.y_root)
        self.drag_active = False

    def move_plancha_drag(self, event):
        if self.dragged_plancha_id is None or self.drag_start is None:
            return
        moved = abs(event.x_root - self.drag_start[0]) + abs(event.y_root - self.drag_start[1])
        if moved < 8:
            return
        self.drag_active = True
        if self.drag_indicator is None:
            record = self.available.get(self.dragged_plancha_id, {})
            name = record.get("name") or f"Plancha {self.dragged_plancha_id}"
            indicator = tk.Toplevel(self)
            indicator.overrideredirect(True)
            indicator.attributes("-topmost", True)
            indicator.configure(background=COLORS.wine, highlightthickness=1, highlightbackground=COLORS.wine_active)
            tk.Label(indicator, text=f"  {name}  ", background=COLORS.wine, foreground=COLORS.text,
                     font=(UI_FONT, 9, "bold"), padx=7, pady=4).pack()
            self.drag_indicator = indicator
        self.drag_indicator.geometry(f"+{event.x_root + 12}+{event.y_root + 12}")

    def finish_plancha_drag(self, event):
        plancha_id = self.dragged_plancha_id
        should_add = self.drag_active and plancha_id is not None and self._pointer_is_over_sections(event.x_root, event.y_root)
        self._clear_plancha_drag()
        if should_add:
            self._add_plancha_id(plancha_id)

    def _pointer_is_over_sections(self, x_root: int, y_root: int) -> bool:
        widget = self.winfo_containing(x_root, y_root)
        while widget is not None:
            if widget == self.sections_tree:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _clear_plancha_drag(self):
        self.dragged_plancha_id = None
        self.drag_start = None
        self.drag_active = False
        if self.drag_indicator is not None:
            self.drag_indicator.destroy()
            self.drag_indicator = None

    def _add_plancha_id(self, plancha_id: int, quiet: bool = False):
        record = self.available.get(plancha_id)
        if not record:
            if not quiet:
                messagebox.showinfo("Producción continua", "La plancha debe estar guardada y tener su PNG final para agregarla.", parent=self)
            return
        final_path = Path(record.get("final_png_path") or "")
        if not final_path.exists():
            if not quiet:
                messagebox.showerror("Producción continua", "No se encontró el PNG final de esa plancha.", parent=self)
            return
        material = (record.get("material") or record.get("order_material") or "").strip()
        section = ContinuousSection(
            plancha_id=plancha_id,
            name=record.get("name") or f"Plancha {plancha_id}",
            final_png_path=str(final_path), project_path=record.get("project_path") or "",
            order_id=record.get("order_id"), client=record.get("order_client") or "",
            material=material, stickers=self._sticker_count(record),
        )
        try:
            self.production.add_section(section)
        except ValueError as error:
            if not quiet:
                messagebox.showwarning("Producción continua", str(error), parent=self)
            return
        self.refresh_all()

    def _selected_section_index(self) -> int | None:
        selected = self.sections_tree.selection()
        return int(selected[0]) if selected else None

    def remove_selected(self):
        index = self._selected_section_index()
        if index is None:
            return
        removed = self.production.sections[index]
        self.production.remove_section(index)

        # Una tira ya guardada reserva sus planchas. Al quitar una sección la
        # liberamos en el acto y borramos su confirmación previa: vuelve a
        # Planchas para que el usuario pueda confirmarla otra vez.
        if removed.plancha_id in self._saved_section_ids:
            self.database.restore_plancha_status_after_continuous(removed.plancha_id)
            self._saved_section_ids.discard(removed.plancha_id)
            if self.production.sections:
                material = self.production.materials[0] if len(self.production.materials) == 1 else "Mixto"
                self.database.save_continuous_production(
                    self.production.name, self.production.mode,
                    self.production.width_cm, self.production.length_cm,
                    material, json.dumps(self.production.to_dict(), ensure_ascii=False),
                    self.production.production_id,
                )
            elif self.production.production_id:
                self.database.delete_continuous_production(self.production.production_id)
                self.production.production_id = None
                self._set_title()
        self.refresh_all()

    def show_section_context_menu(self, event):
        """Quitar de la tira nunca borra la plancha ni su archivo final."""
        row = self.sections_tree.identify_row(event.y)
        if not row:
            return
        self.sections_tree.selection_set(row)
        self.sections_tree.focus(row)
        menu = tk.Menu(self, tearoff=0)
        configure_menu(menu)
        menu.add_command(label="Quitar de la tira", command=lambda *a, _fn=self.remove_selected: _fn(*a))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def move_selected(self, direction: int):
        index = self._selected_section_index()
        if index is None:
            return
        self.production.move_section(index, direction)
        self.refresh_all()
        target = index + direction
        if 0 <= target < len(self.production.sections):
            self.sections_tree.selection_set(str(target))

    def change_zoom(self, delta: float):
        self.preview_zoom = min(1.8, max(0.5, round(self.preview_zoom + delta, 2)))
        self.render_preview()

    def render_preview(self):
        self.preview_canvas.delete("all")
        canvas_width = max(260, self.preview_canvas.winfo_width() - 16)
        if not self.production.sections:
            self.preview_canvas.create_text(155, 150, text="Agregá planchas terminadas\npara ver la tira.", fill="#e7d3c4", justify="center")
            self.preview_canvas.configure(scrollregion=(0, 0, 320, 340))
            return
        try:
            from PIL import Image, ImageDraw, ImageTk

            width = max(260, round(min(420, canvas_width) * self.preview_zoom))
            pixels_per_cm = width / CONTINUOUS_WIDTH_CM
            height = max(1, round(self.production.length_cm * pixels_per_cm))
            section_height = max(1, round(A4_HEIGHT_CM * pixels_per_cm))
            preview = Image.new("RGBA", (width, height), (248, 246, 240, 255))
            draw = ImageDraw.Draw(preview)
            for index, section in enumerate(self.production.sections):
                top = index * section_height
                with Image.open(section.final_png_path) as source:
                    image = source.convert("RGBA").resize((width, section_height), Image.Resampling.LANCZOS)
                preview.alpha_composite(image, (0, top))
                # Una Hoja es una plancha individual: no necesita una marca
                # de corte al final. Las tiras de varias secciones sí la usan
                # para identificar dónde termina cada plancha A4.
                if self.production.mode != "Hoja":
                    bottom = min(height - 1, top + section_height - 1)
                    draw.line((0, bottom, width, bottom), fill=(0, 0, 0, 255), width=max(1, round(2 * self.preview_zoom)))
            photo = ImageTk.PhotoImage(preview)
            self.preview_photo = photo
            self.preview_canvas.create_image(8, 8, image=photo, anchor="nw")
            self.preview_canvas.configure(scrollregion=(0, 0, width + 16, height + 16))
        except Exception as error:
            self.preview_canvas.create_text(160, 150, text=f"No se pudo mostrar la vista previa.\n{error}", fill="#f5b7b1", justify="center", width=280)
            self.preview_canvas.configure(scrollregion=(0, 0, 320, 340))

    def save_pending(self):
        self._save_pending(show_confirmation=True)

    def _save_pending(self, show_confirmation: bool) -> bool:
        if not self.production.sections:
            messagebox.showwarning("Producción continua", "Agregá al menos una plancha terminada.", parent=self)
            return False
        errors = self.production.validation_errors()
        if errors:
            messagebox.showerror("Producción continua", errors[0], parent=self)
            return False
        self.production.name = self.name_var.get().strip() or "Producción continua"
        material = self.production.materials[0] if len(self.production.materials) == 1 else "Mixto"
        current_section_ids = {section.plancha_id for section in self.production.sections}
        new_section_ids = current_section_ids - self._saved_section_ids
        for plancha_id in new_section_ids:
            project = self.database.plancha_project(plancha_id)
            if not project or project.get("production_status") == "usada_en_continua":
                messagebox.showwarning(
                    "Producción continua",
                    "Una de las planchas fue reservada en otra tira. Actualizá la lista y elegí otra.",
                    parent=self,
                )
                self.refresh_available()
                return False
        self.production.production_id = self.database.save_continuous_production(
            self.production.name, self.production.mode, self.production.width_cm, self.production.length_cm,
            material, json.dumps(self.production.to_dict(), ensure_ascii=False), self.production.production_id,
        )
        for plancha_id in self._saved_section_ids - current_section_ids:
            self.database.restore_plancha_status_after_continuous(plancha_id)
        for plancha_id in new_section_ids:
            self.database.save_plancha_status_before_continuous(plancha_id)
            self.database.update_plancha_production_status(plancha_id, "usada_en_continua")
        self._saved_section_ids = current_section_ids
        self._set_title()
        if show_confirmation:
            messagebox.showinfo("Producción guardada", "La tira quedó guardada como pendiente. Todavía no se generó ni imprimió ningún archivo.", parent=self)
        self.refresh_available()
        return True

    def open_pending(self):
        records = self.database.continuous_productions()
        if not records:
            messagebox.showinfo("Producciones pendientes", "Todavía no hay producciones continuas guardadas.", parent=self)
            return
        dialog = tk.Toplevel(self)
        dialog.title("Abrir producción pendiente")
        dialog.configure(background="#111314")
        dialog.transient(self)
        dialog.grab_set()
        tree = ttk.Treeview(dialog, columns=("name", "mode", "length", "updated"), show="headings", height=10)
        for key, label, width in (("name", "Producción", 240), ("mode", "Modo", 100), ("length", "Largo", 90), ("updated", "Actualizada", 160)):
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor="center" if key in {"mode", "length"} else "w")
        for record in records:
            tree.insert("", "end", iid=str(record["id"]), values=(record["name"], record["mode"], f"{float(record['length_cm']):g} cm", record["updated_at"].replace("T", " ")))
        tree.pack(fill="both", expand=True, padx=14, pady=14)

        def open_selected():
            selected = tree.selection()
            if not selected:
                return
            record = self.database.continuous_production(int(selected[0]))
            try:
                data = json.loads(record.get("production_json") or "{}")
                self.production = ContinuousProduction.from_dict(data, production_id=record["id"])
            except (TypeError, ValueError, AttributeError) as error:
                messagebox.showerror("Producción continua", f"No se pudo abrir la producción: {error}", parent=dialog)
                return
            self.name_var.set(self.production.name)
            self._saved_section_ids = {section.plancha_id for section in self.production.sections}
            dialog.destroy()
            self.refresh_available()
            self.refresh_all()

        ttk.Button(dialog, text="Abrir", command=open_selected, style="Plancha.Primary.TButton").pack(anchor="e", padx=14, pady=(0, 14))

    # ------------------------------------------------------------------
    # Generación e impresión de la tira continua
    # ------------------------------------------------------------------

    def generate_strip_png(self) -> str | None:
        """Renderiza todas las secciones en un único PNG a 300 DPI.

        Devuelve la ruta del archivo generado, o None si algo falló.
        Las secciones se apilan verticalmente en el mismo orden que la tira.
        """
        if not self.production.sections:
            messagebox.showwarning("Imprimir tira", "Agregá al menos una plancha a la tira.", parent=self)
            return None

        errors = self.production.validation_errors()
        if errors:
            messagebox.showerror("Producción continua", errors[0], parent=self)
            return None

        try:
            from PIL import Image, ImageDraw

            dpi = 300
            px_per_cm = dpi / 2.54
            strip_w = round(CONTINUOUS_WIDTH_CM * px_per_cm)   # 21 cm a 300 DPI
            section_h = round(A4_HEIGHT_CM * px_per_cm)        # 29.7 cm a 300 DPI
            total_h = section_h * len(self.production.sections)

            strip = Image.new("RGBA", (strip_w, total_h), (255, 255, 255, 255))
            draw = ImageDraw.Draw(strip)
            for index, section in enumerate(self.production.sections):
                with Image.open(section.final_png_path) as src:
                    page = src.convert("RGBA").resize(
                        (strip_w, section_h), Image.Resampling.LANCZOS
                    )
                strip.alpha_composite(page, (0, index * section_h))
                if self.production.mode != "Hoja":
                    bottom = min(total_h - 1, (index + 1) * section_h - 1)
                    draw.line((0, bottom, strip_w - 1, bottom), fill=(0, 0, 0, 255), width=3)

            # Guardar en la carpeta de salidas junto a las impresiones temporales.
            root = Path(__file__).resolve().parents[2]
            folder = root / "outputs" / "tiras_continuas"
            folder.mkdir(parents=True, exist_ok=True)
            import time, uuid
            stamp = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
            name = (self.production.name or "tira").replace(" ", "_")
            out_path = folder / f"{name}_{stamp}.png"

            # PIL guarda el DPI en los metadatos para que el driver lo lea.
            strip.save(str(out_path), "PNG", dpi=(dpi, dpi), compress_level=3)
            return str(out_path)

        except Exception as error:
            messagebox.showerror("Error al generar la tira", str(error), parent=self)
            return None

    def generate_experimental_roll_block_png(self, length_mm: int = 1188) -> str | None:
        """Genera un bloque aislado para pruebas con rollo, sin separadores."""
        if not self.production.sections:
            messagebox.showwarning("Rollo experimental", "Agregá al menos una plancha al bloque.", parent=self)
            return None
        try:
            block = ExperimentalRollBlock(
                tuple(section.final_png_path for section in self.production.sections), int(length_mm),
            )
            root = Path(__file__).resolve().parents[2]
            import time, uuid
            output = root / "outputs" / "bloques_rollo_experimental" / (
                f"bloque_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
            )
            return str(render_roll_block(block, output))
        except Exception as error:
            messagebox.showerror("Rollo experimental", str(error), parent=self)
            return None

    def print_experimental_roll_block(self) -> None:
        """Envía un bloque de prueba. No altera la impresión continua histórica."""
        if not self.production.sections:
            messagebox.showwarning("Rollo experimental", "Agregá al menos una plancha al bloque.", parent=self)
            return
        length_mm = simpledialog.askinteger(
            "Rollo experimental",
            "Largo del bloque en milímetros (1188 predeterminado; máximo 1200):",
            parent=self, initialvalue=1188, minvalue=1188, maxvalue=1200,
        )
        if length_mm is None:
            return
        if not messagebox.askyesno(
            "Rollo experimental",
            f"Se enviará un único bloque de 210 × {length_mm} mm sin separadores.\n\n"
            "La L3210 no tiene alimentación de rollo certificada; verificá la guía y el arrastre antes de imprimir.",
            parent=self,
        ):
            return
        from app.printing.windows_print import default_printer, print_png_strip, printer_status

        config = self._current_print_config()
        printer = (config.get("printer_name") or default_printer() or "").strip()
        available, message = printer_status(printer)
        if not available:
            messagebox.showerror("Rollo experimental", message, parent=self)
            return
        path = self.generate_experimental_roll_block_png(length_mm)
        if not path:
            return
        result = print_png_strip(
            printer, path, copies=1, document_name="Doccione · Bloque de rollo experimental",
            devmode_bytes=self._load_devmode(),
        )
        if result.success:
            self._print_spool_job_id = result.spool_job_id
            messagebox.showinfo("Rollo experimental", f"Bloque enviado. Trabajo en cola: {result.spool_job_id}", parent=self)
        else:
            messagebox.showerror("Rollo experimental", result.message, parent=self)

    def open_epson_continuity_test(self) -> None:
        """Abre la prueba A/B aislada; no reserva ni cambia planchas."""
        from app.printing.experimental_epson_continuity import (
            generate_continuity_patterns, latest_measurements, run_continuity_test, save_continuity_measurement,
        )
        from app.printing.windows_print import default_printer, list_printers, open_print_dialog, printer_status

        dialog = tk.Toplevel(self)
        dialog.title("Prueba continuidad Epson L3210 · experimental")
        dialog.configure(background=COLORS.background)
        dialog.geometry("570x620")
        dialog.transient(self)
        dialog.grab_set()
        patterns = list(generate_continuity_patterns())
        stop_event = threading.Event()
        running = {"value": False}
        config = self._current_print_config()
        printers = list_printers()
        saved = (config.get("printer_name") or default_printer() or "").strip()
        if saved and saved not in printers:
            printers.insert(0, saved)
        printer_var = tk.StringVar(value=saved)
        status_var = tk.StringVar(value="Patrones listos: dos bloques de 210 × 300 mm a 300 DPI.")
        tk.Label(dialog, text="PRUEBA CONTINUIDAD EPSON L3210", background=COLORS.background,
                 foreground=COLORS.text, font=(IDENTITY_FONT, 15, "bold")).pack(anchor="w", padx=18, pady=(18, 5))
        tk.Label(dialog, text="A compara dos StartDoc. B usa un StartDoc y dos StartPage. No hay compensación.",
                 background=COLORS.background, foreground=COLORS.muted, wraplength=530, justify="left").pack(anchor="w", padx=18)
        form = tk.Frame(dialog, background=COLORS.panel_elevated)
        form.pack(fill="x", padx=18, pady=16)
        tk.Label(form, text="IMPRESORA", background=COLORS.panel_elevated, foreground=COLORS.muted).pack(anchor="w", padx=12, pady=(12, 3))
        ttk.Combobox(form, textvariable=printer_var, values=printers, state="readonly", width=55).pack(fill="x", padx=12)

        def configure_driver():
            name = printer_var.get().strip()
            if not name:
                messagebox.showwarning("Prueba Epson", "Elegí una impresora.", parent=dialog)
                return
            devmode = open_print_dialog(name, parent_hwnd=0)
            if devmode is not None:
                self._save_devmode(devmode)
                status_var.set("DEVMODE guardado. Configurá en el driver papel personalizado 210 × 300 mm.")

        ttk.Button(form, text="Configurar driver (210 × 300 mm)", command=configure_driver,
                   style="Plancha.Secondary.TButton").pack(anchor="w", padx=12, pady=12)
        tk.Label(dialog, textvariable=status_var, background=COLORS.background, foreground=COLORS.text,
                 wraplength=530, justify="left").pack(anchor="w", padx=18)
        comparison_var = tk.StringVar(value="Aún no hay mediciones para comparar.")
        tk.Label(dialog, textvariable=comparison_var, background=COLORS.panel, foreground=COLORS.text,
                 wraplength=530, justify="left", padx=12, pady=12).pack(fill="x", padx=18, pady=12)

        def refresh_comparison():
            records = latest_measurements()
            if not {"A", "B"}.issubset(records):
                return
            a = records["A"].get("measurements", {}).get("separation_mm")
            b = records["B"].get("measurements", {}).get("separation_mm")
            try:
                comparison_var.set(
                    f"Método A — trabajos separados\nSeparación: {float(a):.1f} mm\n\n"
                    f"Método B — StartDoc único\nSeparación: {float(b):.1f} mm\n\n"
                    f"Diferencia:\n{float(a) - float(b):.1f} mm"
                )
            except (TypeError, ValueError):
                comparison_var.set("Hay resultados A y B, pero falta completar una separación numérica.")

        def collect_measurements(run, name):
            entry_dialog = tk.Toplevel(dialog)
            entry_dialog.title(f"Mediciones método {run.method}")
            entry_dialog.configure(background=COLORS.background)
            entry_dialog.transient(dialog)
            entry_dialog.grab_set()
            fields = (("separation_mm", "Separación entre bloques (mm)"), ("initial_margin_mm", "Margen inicial (mm)"),
                      ("final_margin_mm", "Margen final (mm)"), ("horizontal_deviation_mm", "Desviación horizontal (mm)"))
            values = {}
            for key, label in fields:
                tk.Label(entry_dialog, text=label, background=COLORS.background, foreground=COLORS.text).pack(anchor="w", padx=14, pady=(9, 1))
                values[key] = tk.StringVar()
                ttk.Entry(entry_dialog, textvariable=values[key]).pack(fill="x", padx=14)
            gripped, ejected = tk.BooleanVar(), tk.BooleanVar()
            ttk.Checkbutton(entry_dialog, text="El papel siguió agarrado por los rodillos", variable=gripped).pack(anchor="w", padx=14, pady=(9, 1))
            ttk.Checkbutton(entry_dialog, text="La impresora expulsó completamente el papel", variable=ejected).pack(anchor="w", padx=14)
            tk.Label(entry_dialog, text="Observaciones", background=COLORS.background, foreground=COLORS.text).pack(anchor="w", padx=14, pady=(9, 1))
            notes = tk.Text(entry_dialog, height=4, width=50)
            notes.pack(fill="x", padx=14)
            def save():
                measurements = {key: value.get().strip() for key, value in values.items()}
                measurements.update(paper_gripped=gripped.get(), paper_ejected=ejected.get(), observations=notes.get("1.0", "end").strip())
                location = save_continuity_measurement(run, name, bool(self._load_devmode()), measurements)
                entry_dialog.destroy()
                status_var.set(f"Resultado guardado en {location.name}")
                refresh_comparison()
            ttk.Button(entry_dialog, text="Guardar mediciones", command=save, style="Plancha.Primary.TButton").pack(pady=14)

        def launch(method):
            if running["value"]:
                return
            name = printer_var.get().strip()
            ok, message = printer_status(name)
            if not ok:
                messagebox.showerror("Prueba Epson", message, parent=dialog)
                return
            running["value"] = True
            stop_event.clear()
            status_var.set(f"Enviando método {method}…")
            devmode = self._load_devmode()
            def worker():
                run = run_continuity_test(name, patterns[0], patterns[1], method, devmode, stop_event)
                def done():
                    running["value"] = False
                    status_var.set(run.message + (f" Job ID: {', '.join(map(str, run.job_ids))}" if run.job_ids else ""))
                    if run.success:
                        collect_measurements(run, name)
                    else:
                        location = save_continuity_measurement(run, name, bool(devmode), {})
                        status_var.set(f"{run.message} Resultado técnico guardado en {location.name}")
                        messagebox.showerror("Prueba Epson", run.message, parent=dialog)
                self.after(0, done)
            threading.Thread(target=worker, daemon=True).start()

        actions = tk.Frame(dialog, background=COLORS.background)
        actions.pack(fill="x", padx=18, pady=(4, 12))
        ttk.Button(actions, text="Método A · dos trabajos", command=lambda: launch("A"), style="Plancha.Primary.TButton").pack(side="left", expand=True, fill="x")
        ttk.Button(actions, text="Método B · StartDoc único", command=lambda: launch("B"), style="Plancha.Primary.TButton").pack(side="left", expand=True, fill="x", padx=7)
        ttk.Button(dialog, text="DETENER PRUEBA", command=lambda: (stop_event.set(), status_var.set("Se detendrá antes del próximo bloque/página.")), style="Plancha.Danger.TButton").pack(fill="x", padx=18)
        ttk.Button(dialog, text="Cerrar", command=dialog.destroy, style="Plancha.Secondary.TButton").pack(pady=12)
        refresh_comparison()

    def _current_print_config(self) -> dict:
        if self.database:
            return self.database.printing_config()
        return {
            "printer_name": "", "paper": "A4", "orientation": "Vertical",
            "scale": 97.27, "quality": "Alta", "color": "Color", "copies": 1,
        }

    def _load_devmode(self) -> bytes | None:
        """Recupera el DEVMODE guardado en la sesión o en la base de datos."""
        if self._devmode_bytes:
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

    def _save_devmode(self, devmode: bytes) -> None:
        """Persiste el DEVMODE elegido en la sesión y en la base de datos."""
        self._devmode_bytes = devmode
        if self.database:
            encoded = base64.b64encode(devmode).decode()
            config = self._current_print_config()
            printer = config.get("printer_name") or ""
            copies = config.get("copies", 1)
            self.database.save_printing_config(printer, {"copies": copies, "devmode_b64": encoded})

    def print_strip_quickly(self) -> None:
        """Imprime con la impresora ya configurada, sin abrir pasos intermedios."""
        if not self.production.sections:
            messagebox.showwarning("Imprimir tira", "Agregá al menos una plancha a la tira.", parent=self)
            return
        errors = self.production.validation_errors()
        if errors:
            messagebox.showerror("Producción continua", errors[0], parent=self)
            return

        from app.printing.windows_print import default_printer, print_png_strip, printer_status

        config = self._current_print_config()
        printer_name = (config.get("printer_name") or default_printer() or "").strip()
        available, message = printer_status(printer_name)
        if not available:
            messagebox.showinfo(
                "Configurar impresora",
                "Elegí la impresora una sola vez para habilitar la impresión directa.\n\n" + message,
                parent=self,
            )
            self.open_print_panel()
            return

        self.update_idletasks()
        strip_path = self.generate_strip_png()
        if not strip_path:
            return
        if not self._save_pending(show_confirmation=False):
            return

        scale = epson_scale_for_sections(len(self.production.sections))
        copies = max(1, int(config.get("copies", 1) or 1))
        if self.database:
            self.database.save_printing_config(printer_name, {"copies": copies})
        result = print_png_strip(
            printer_name=printer_name,
            path=strip_path,
            copies=copies,
            document_name=self.production.name or "Producción continua",
            devmode_bytes=self._load_devmode(),
            scale_percent=scale,
        )
        if result.success:
            self._print_spool_job_id = result.spool_job_id
            self.database.mark_continuous_production_print_submitted(self.production.production_id)
            messagebox.showinfo(
                "Impresión enviada",
                f"{len(self.production.sections)} plancha(s) acoplada(s) · escala Epson {scale:.2f} %.\n{result.message}",
                parent=self,
            )
        else:
            messagebox.showerror("Error de impresión", result.message, parent=self)

    def open_print_panel(self) -> None:
        """Abre el panel de configuración e impresión de la tira continua."""

        panel = tk.Toplevel(self)
        panel.title("Configuración de impresora · Tira continua")
        panel.configure(background=COLORS.background)
        panel.geometry("480x610")
        panel.resizable(False, False)
        panel.transient(self)
        panel.grab_set()

        # ── Encabezado ───────────────────────────────────────────────────────
        header = tk.Frame(panel, background=COLORS.panel,
                          highlightthickness=1, highlightbackground=COLORS.border)
        header.pack(fill="x", padx=16, pady=(16, 10))
        tk.Label(header, text="IMPRIMIR TIRA", background=COLORS.panel,
                 foreground=COLORS.text, font=(IDENTITY_FONT, 16, "bold")).pack(
            anchor="w", padx=16, pady=(13, 2))
        if self.production.sections:
            info_text = (
                f"{len(self.production.sections)} sección(es) · "
                f"{self.production.length_cm:g} cm · "
                f"{self.production.total_stickers} stickers"
            )
        else:
            info_text = "Elegí la impresora y guardá su configuración para usarla al imprimir."
        tk.Label(header, text=info_text, background=COLORS.panel,
                 foreground=COLORS.muted, font=(UI_FONT, 10)).pack(
            anchor="w", padx=16, pady=(0, 13))

        # ── Configuración ────────────────────────────────────────────────────
        form = tk.Frame(panel, background=COLORS.panel_elevated,
                        highlightthickness=1, highlightbackground=COLORS.border)
        form.pack(fill="x", padx=16, pady=(0, 10))

        from app.printing.windows_print import (
            default_printer, list_printers, open_print_dialog, printer_status,
        )

        config = self._current_print_config()
        printers = list_printers()
        saved_printer = (config.get("printer_name") or "").strip()
        if saved_printer and saved_printer not in printers:
            printers = [saved_printer, *printers]

        printer_var = tk.StringVar(value=saved_printer or default_printer() or (printers[0] if printers else ""))
        copies_var = tk.IntVar(value=max(1, int(config.get("copies", 1) or 1)))

        tk.Label(form, text="IMPRESORA", background=COLORS.panel_elevated,
                 foreground=COLORS.muted, font=(IDENTITY_FONT, 9, "bold")).grid(
            row=0, column=0, sticky="w", padx=14, pady=(14, 4))
        printer_box = ttk.Combobox(form, textvariable=printer_var,
                                   values=printers, state="readonly", width=38)
        printer_box.grid(row=1, column=0, sticky="ew", padx=14)

        tk.Label(form, text="COPIAS", background=COLORS.panel_elevated,
                 foreground=COLORS.muted, font=(IDENTITY_FONT, 9, "bold")).grid(
            row=2, column=0, sticky="w", padx=14, pady=(14, 4))
        ttk.Spinbox(form, from_=1, to=99, textvariable=copies_var, width=8).grid(
            row=3, column=0, sticky="w", padx=14, pady=(0, 10))
        form.columnconfigure(0, weight=1)

        # Indicador de estado de la impresora
        printer_status_var = tk.StringVar(value="")
        printer_status_label = tk.Label(
            form, textvariable=printer_status_var,
            background=COLORS.panel_elevated, foreground=COLORS.muted,
            font=(UI_FONT, 9), anchor="w",
        )
        printer_status_label.grid(row=4, column=0, sticky="ew", padx=14, pady=(0, 6))

        def refresh_printer_status(*_args):
            name = printer_var.get().strip()
            if not name:
                printer_status_var.set("")
                return
            ok, msg = printer_status(name)
            printer_status_var.set(f"Estado: {msg}")
            printer_status_label.configure(foreground="#39d353" if ok else "#ff4d5a")

        printer_var.trace_add("write", refresh_printer_status)
        refresh_printer_status()

        # ── Botón «Configurar impresora» (abre diálogo nativo del driver) ────
        config_frame = tk.Frame(panel, background=COLORS.background)
        config_frame.pack(fill="x", padx=16, pady=(0, 4))

        devmode_status_var = tk.StringVar(value="Configuración por defecto del driver.")
        if self._load_devmode():
            devmode_status_var.set("Configuración personalizada guardada.")

        def configure_printer():
            name = printer_var.get().strip()
            if not name:
                messagebox.showwarning("Configurar impresora",
                                       "Elegí una impresora primero.", parent=panel)
                return
            # Obtener el HWND de la ventana del panel para centrar el diálogo.
            try:
                hwnd = int(panel.wm_frame(), 16)
            except Exception:
                hwnd = 0
            devmode = open_print_dialog(name, parent_hwnd=hwnd)
            if devmode is None:
                devmode_status_var.set("Configuración cancelada (sin cambios).")
                return
            self._save_devmode(devmode)
            # También guardar el nombre de impresora y copias elegidas.
            self.database and self.database.save_printing_config(
                name, {"copies": copies_var.get()}
            )
            devmode_status_var.set("✓ Configuración guardada para esta impresora.")
            self._refresh_printer_connection()

        ttk.Button(config_frame, text="Configurar impresora (abre cuadro de impresión)",
                   command=configure_printer,
                   style="Plancha.Secondary.TButton").pack(fill="x")
        tk.Label(config_frame, textvariable=devmode_status_var,
                 background=COLORS.background, foreground=COLORS.muted,
                 font=(UI_FONT, 9), anchor="w").pack(anchor="w", pady=(4, 0))

        # ── Estado e historial ───────────────────────────────────────────────
        status_frame = tk.Frame(panel, background=COLORS.panel_elevated,
                                highlightthickness=1, highlightbackground=COLORS.border)
        status_frame.pack(fill="x", padx=16, pady=(8, 0))
        tk.Label(status_frame, text="ESTADO", background=COLORS.panel_elevated,
                 foreground=COLORS.muted, font=(IDENTITY_FONT, 9, "bold")).pack(
            anchor="w", padx=14, pady=(10, 4))
        tk.Label(status_frame, textvariable=self._print_status_var,
                 background=COLORS.panel_elevated, foreground=COLORS.text,
                 font=(UI_FONT, 9), anchor="w", justify="left", wraplength=420).pack(
            anchor="w", padx=14, pady=(0, 10))

        # ── Botones de acción ────────────────────────────────────────────────
        actions = tk.Frame(panel, background=COLORS.background)
        actions.pack(fill="x", padx=16, pady=16)

        def do_print():
            """Genera la tira y la envía a la impresora seleccionada."""
            if not self.production.sections:
                messagebox.showwarning("Imprimir tira", "Agregá al menos una plancha a la tira.", parent=panel)
                return
            name = printer_var.get().strip()
            if not name:
                messagebox.showwarning("Imprimir", "Elegí una impresora.", parent=panel)
                return
            ok, msg = printer_status(name)
            if not ok:
                messagebox.showerror("Impresora no disponible", msg, parent=panel)
                return

            self._print_status_var.set("Generando tira PNG…")
            panel.update_idletasks()

            strip_path = self.generate_strip_png()
            if not strip_path:
                self._print_status_var.set("No se pudo generar la tira.")
                return
            if not self._save_pending(show_confirmation=False):
                self._print_status_var.set("No se pudo guardar la tira antes de imprimir.")
                return

            self._strip_png_path = strip_path
            self._print_status_var.set("Enviando a la impresora…")
            panel.update_idletasks()

            # Guardar la configuración elegida antes de imprimir.
            if self.database:
                self.database.save_printing_config(name, {"copies": copies_var.get()})
            self._refresh_printer_connection()

            from app.printing.windows_print import print_png_strip
            devmode = self._load_devmode()
            result = print_png_strip(
                printer_name=name,
                path=strip_path,
                copies=copies_var.get(),
                document_name=self.production.name or "Producción continua",
                devmode_bytes=devmode,
                scale_percent=epson_scale_for_sections(len(self.production.sections)),
            )
            self._print_spool_job_id = result.spool_job_id
            if result.success:
                self.database.mark_continuous_production_print_submitted(self.production.production_id)
                self._print_status_var.set(
                    f"✓ {result.message}\n"
                    f"Archivo: {Path(strip_path).name}\n"
                    f"Trabajo en cola: {result.spool_job_id}"
                )
            else:
                self._print_status_var.set(f"✗ {result.message}")
                messagebox.showerror("Error de impresión", result.message, parent=panel)

        def do_cancel():
            """Cancela el trabajo en la cola de Windows si todavía está pendiente."""
            name = printer_var.get().strip()
            if not name or not self._print_spool_job_id:
                messagebox.showinfo("Cancelar", "No hay ningún trabajo de impresión activo.", parent=panel)
                return
            from app.printing.windows_print import cancel_spool_job
            result = cancel_spool_job(name, self._print_spool_job_id)
            self._print_status_var.set(result.message)
            if result.success:
                self._print_spool_job_id = None

        dialog_print_button = ttk.Button(
            actions, text="Imprimir", command=do_print, style="Plancha.Primary.TButton",
        )
        dialog_print_button.pack(side="left", fill="x", expand=True)
        if not self.production.sections:
            dialog_print_button.configure(state="disabled")
        ttk.Button(actions, text="Cancelar impresión",
                   command=do_cancel,
                   style="Plancha.Danger.TButton").pack(side="left", fill="x", expand=True, padx=(8, 0))
        ttk.Button(actions, text="Cerrar",
                   command=panel.destroy,
                   style="Plancha.Secondary.TButton").pack(side="right")
