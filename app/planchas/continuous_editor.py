"""Interfaz de la etapa 1 para armar producciones continuas de planchas A4."""

from __future__ import annotations

import base64
import json
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from app.planchas.continuous_model import (
    A4_HEIGHT_CM,
    CONTINUOUS_WIDTH_CM,
    MAX_CONTINUOUS_LENGTH_CM,
    PRODUCTION_PROFILES,
    ContinuousProduction,
    ContinuousSection,
)
from app.ui.theme import COLORS, IDENTITY_FONT, UI_FONT, configure_menu, configure_plancha_styles


class ContinuousProductionEditor(tk.Toplevel):
    """Arma una tira visual sin imprimir ni alterar las planchas seleccionadas."""

    def __init__(self, master, database, initial_plancha_id: int | None = None):
        super().__init__(master)
        self.database = database
        self.title("Producción continua")
        self.configure(background=COLORS.background)
        self.geometry("1130x740")
        self.minsize(940, 610)
        self.transient(master)
        self.production = ContinuousProduction.new()
        self.initial_plancha_id = initial_plancha_id
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
        self._build()
        self.refresh_available()
        if initial_plancha_id:
            self.after_idle(lambda: self._add_plancha_id(initial_plancha_id, quiet=True))
        self.refresh_all()

    def _build(self):
        configure_plancha_styles(self)
        header = tk.Frame(self, background=COLORS.background)
        header.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(
            header, text="PRODUCCIÓN CONTINUA", background=COLORS.background, foreground=COLORS.text,
            font=(IDENTITY_FONT, 18, "bold"),
        ).pack(side="left")
        ttk.Button(header, text="Abrir pendiente", command=lambda *a, _fn=self.open_pending: _fn(*a)).pack(side="right")
        ttk.Entry(header, textvariable=self.name_var, width=34).pack(side="right", padx=(0, 9))

        profiles = tk.Frame(self, background=COLORS.background)
        profiles.pack(fill="x", padx=16, pady=(0, 10))
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
        body.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        source = tk.Frame(body, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border, width=295)
        source.pack(side="left", fill="y")
        source.pack_propagate(False)
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
        self.available_tree.pack(side="left", fill="both", expand=True)
        source_scroll.pack(side="right", fill="y")
        self.available_tree.bind("<ButtonPress-1>", self.start_plancha_drag, add="+")
        self.available_tree.bind("<B1-Motion>", self.move_plancha_drag, add="+")
        self.available_tree.bind("<ButtonRelease-1>", self.finish_plancha_drag, add="+")
        ttk.Button(source, text="Agregar a la tira  ›", command=lambda *a, _fn=self.add_selected: _fn(*a)).pack(fill="x", padx=10, pady=(0, 11))

        assembly = tk.Frame(body, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border, width=370)
        assembly.pack(side="left", fill="both", expand=True, padx=10)
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

        preview = tk.Frame(body, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border, width=370)
        preview.pack(side="right", fill="both", expand=True)
        preview_top = tk.Frame(preview, background=COLORS.panel)
        preview_top.pack(fill="x", padx=12, pady=(12, 4))
        tk.Label(preview_top, text="VISTA PREVIA", background=COLORS.panel, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 12, "bold")).pack(side="left")
        ttk.Button(preview_top, text="−", width=3, command=lambda: self.change_zoom(-0.2)).pack(side="right")
        ttk.Button(preview_top, text="+", width=3, command=lambda: self.change_zoom(0.2)).pack(side="right", padx=(0, 4))
        self.preview_canvas = tk.Canvas(preview, background=COLORS.canvas, highlightthickness=0)
        preview_scroll = ttk.Scrollbar(preview, orient="vertical", command=lambda *a, _fn=self.preview_canvas.yview: _fn(*a))
        self.preview_canvas.configure(yscrollcommand=preview_scroll.set)
        self.preview_canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(4, 10))
        preview_scroll.pack(side="right", fill="y", padx=(0, 10), pady=(4, 10))

        footer = tk.Frame(self, background=COLORS.background)
        footer.pack(fill="x", padx=16, pady=(0, 16))
        tk.Label(footer, textvariable=self.summary_var, background=COLORS.background, foreground=COLORS.text, justify="left", font=(UI_FONT, 10)).pack(side="left")
        ttk.Button(footer, text="Guardar pendiente", command=lambda *a, _fn=self.save_pending: _fn(*a), style="Plancha.Primary.TButton").pack(side="right")
        ttk.Button(footer, text="Cerrar", command=lambda *a, _fn=self.destroy: _fn(*a)).pack(side="right", padx=(0, 7))
        ttk.Button(footer, text="Imprimir tira", command=lambda *a, _fn=self.open_print_panel: _fn(*a), style="Plancha.Primary.TButton").pack(side="right", padx=(0, 7))

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
            self.available_tree.insert("", "end", iid=str(plancha_id), values=(name, client, self._sticker_count(record)))

    def refresh_sections(self):
        self.sections_tree.delete(*self.sections_tree.get_children())
        for index, section in enumerate(self.production.sections):
            material = section.material or "-"
            self.sections_tree.insert("", "end", iid=str(index), values=(index + 1, section.name, material, section.stickers))

    def refresh_summary(self):
        errors = self.production.validation_errors()
        material = self.production.material_label
        note = f"\nAviso: {errors[0]}" if errors else ""
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
        self.database.save_plancha_status_before_continuous(plancha_id)
        self.database.update_plancha_production_status(plancha_id, "usada_en_continua")
        self.refresh_all()

    def _selected_section_index(self) -> int | None:
        selected = self.sections_tree.selection()
        return int(selected[0]) if selected else None

    def remove_selected(self):
        index = self._selected_section_index()
        if index is None:
            return
        removed = self.production.sections[index]
        self.database.restore_plancha_status_after_continuous(removed.plancha_id)
        self.production.remove_section(index)
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
        if not self.production.sections:
            self.preview_canvas.create_text(155, 150, text="Agregá planchas terminadas\npara ver la tira.", fill="#e7d3c4", justify="center")
            self.preview_canvas.configure(scrollregion=(0, 0, 320, 340))
            return
        try:
            from PIL import Image, ImageDraw, ImageTk

            width = max(260, round(420 * self.preview_zoom))
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
                if index:
                    draw.line((0, top, width, top), fill=(215, 9, 22, 255), width=max(1, round(2 * self.preview_zoom)))
            photo = ImageTk.PhotoImage(preview)
            self.preview_photo = photo
            self.preview_canvas.create_image(8, 8, image=photo, anchor="nw")
            self.preview_canvas.configure(scrollregion=(0, 0, width + 16, height + 16))
        except Exception as error:
            self.preview_canvas.create_text(160, 150, text=f"No se pudo mostrar la vista previa.\n{error}", fill="#f5b7b1", justify="center", width=280)
            self.preview_canvas.configure(scrollregion=(0, 0, 320, 340))

    def save_pending(self):
        if not self.production.sections:
            messagebox.showwarning("Producción continua", "Agregá al menos una plancha terminada.", parent=self)
            return
        errors = self.production.validation_errors()
        if errors:
            messagebox.showerror("Producción continua", errors[0], parent=self)
            return
        self.production.name = self.name_var.get().strip() or "Producción continua"
        material = self.production.materials[0] if len(self.production.materials) == 1 else "Mixto"
        self.production.production_id = self.database.save_continuous_production(
            self.production.name, self.production.mode, self.production.width_cm, self.production.length_cm,
            material, json.dumps(self.production.to_dict(), ensure_ascii=False), self.production.production_id,
        )
        self.title(f"Producción continua · #{self.production.production_id}")
        messagebox.showinfo("Producción guardada", "La tira quedó guardada como pendiente. Todavía no se generó ni imprimió ningún archivo.", parent=self)

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
            dialog.destroy()
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
            from PIL import Image

            dpi = 300
            px_per_cm = dpi / 2.54
            strip_w = round(CONTINUOUS_WIDTH_CM * px_per_cm)   # 21 cm a 300 DPI
            section_h = round(A4_HEIGHT_CM * px_per_cm)        # 29.7 cm a 300 DPI
            total_h = section_h * len(self.production.sections)

            strip = Image.new("RGBA", (strip_w, total_h), (255, 255, 255, 255))
            for index, section in enumerate(self.production.sections):
                with Image.open(section.final_png_path) as src:
                    page = src.convert("RGBA").resize(
                        (strip_w, section_h), Image.Resampling.LANCZOS
                    )
                strip.alpha_composite(page, (0, index * section_h))

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

    def open_print_panel(self) -> None:
        """Abre el panel flotante de impresión de la tira continua."""
        if not self.production.sections:
            messagebox.showwarning("Imprimir tira", "Agregá al menos una plancha a la tira.", parent=self)
            return

        panel = tk.Toplevel(self)
        panel.title("Imprimir tira continua")
        panel.configure(background=COLORS.background)
        panel.geometry("480x560")
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
        info_text = (
            f"{len(self.production.sections)} sección(es) · "
            f"{self.production.length_cm:g} cm · "
            f"{self.production.total_stickers} stickers"
        )
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

            self._strip_png_path = strip_path
            self._print_status_var.set("Enviando a la impresora…")
            panel.update_idletasks()

            # Guardar la configuración elegida antes de imprimir.
            if self.database:
                self.database.save_printing_config(name, {"copies": copies_var.get()})

            from app.printing.windows_print import print_png_strip
            devmode = self._load_devmode()
            result = print_png_strip(
                printer_name=name,
                path=strip_path,
                copies=copies_var.get(),
                document_name=self.production.name or "Producción continua",
                devmode_bytes=devmode,
            )
            self._print_spool_job_id = result.spool_job_id
            if result.success:
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

        ttk.Button(actions, text="Imprimir",
                   command=do_print,
                   style="Plancha.Primary.TButton").pack(side="left", fill="x", expand=True)
        ttk.Button(actions, text="Cancelar impresión",
                   command=do_cancel,
                   style="Plancha.Danger.TButton").pack(side="left", fill="x", expand=True, padx=(8, 0))
        ttk.Button(actions, text="Cerrar",
                   command=panel.destroy,
                   style="Plancha.Secondary.TButton").pack(side="right")
