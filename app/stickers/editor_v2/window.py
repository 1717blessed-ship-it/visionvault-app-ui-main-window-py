"""Ventana Sticker Studio 2.0 con compatibilidad reversible."""

from __future__ import annotations

import tkinter as tk
import json
import copy
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from PIL import Image

from app.stickers.editor import StickerStudio
from app.ui.theme import COLORS, IDENTITY_FONT, UI_FONT
from .canvas import StickerCanvas
from .components import Inspector, ThumbnailTray, ToolRail, add_tooltip
from .adapter import PipelineViewAdapter
from .state import CanvasState, StudioSessionState, VIEW_MODES
from .session import REMOVABLE_CLEAN_STATES, SessionStore, TraySelection, remove_from_session
from .review import (
    invalidate_review, mark_reviewed, mark_sent, master_path,
    record_export, review_is_current,
)
from app.stickers.pipeline import ProcessingResult
from app.stickers.mask_editing import (
    MaskEditDocument, MaskStroke, compare_masks, save_approved_reference,
)


class StickerStudioV2(StickerStudio):
    """Presentación moderna que delega todos los comandos al editor existente."""

    def __init__(self, *args, **kwargs):
        self._v2_ready = False
        super().__init__(*args, **kwargs)
        self.title("Creador de stickers 2.0")
        self.minsize(1040, 680)
        for child in self.winfo_children():
            child.pack_forget()
        self._v2_state = StudioSessionState()
        self._v2_border_mm = tk.DoubleVar(value=self.profile.final_white_px / self.profile.dpi * 25.4)
        self._v2_quality = tk.StringVar(value=self.profile.quality)
        self._v2_border_treatment = tk.StringVar(value="Automático")
        self._v2_contraction_mm = tk.DoubleVar(value=0.0)
        self._v2_expansion_mm = tk.DoubleVar(value=0.0)
        self._v2_smoothing_mm = tk.DoubleVar(value=0.08)
        self._v2_brush_size = tk.DoubleVar(value=24.0)
        self._v2_brush_hardness = tk.DoubleVar(value=.8)
        self._v2_brush_opacity = tk.DoubleVar(value=1.0)
        self._v2_selection_view = tk.StringVar(value="Ambas")
        self._v2_selection = TraySelection()
        self._v2_batch_filter = None
        self._v2_dirty = False
        self._v2_store = SessionStore(Path("work/stickers/studio_v2_session.json"))
        self._v2_preview_after = None
        self._v2_commit_after = None
        self._v2_preview_generation = 0
        self._v2_preview_future = None
        self._v2_preview_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sticker-preview")
        self._v2_geometry_cache = OrderedDict()
        self._v2_geometry_cache_bytes = 0
        self._v2_geometry_cache_limit = 64 * 1024 * 1024
        self._v2_editor_state = tk.StringVar(value="Guardado")
        self._v2_mode = tk.StringVar(value="Final")
        self._v2_cut = tk.BooleanVar(value=False)
        self._v2_compare = tk.BooleanVar(value=False)
        self._v2_background = tk.StringVar(value="Damero")
        self._v2_compare_split = tk.DoubleVar(value=50.0)
        self._v2_zoom_percent = tk.DoubleVar(value=100.0)
        self._build_v2()
        self._v2_border_mm.trace_add("write", lambda *_: self._preview_changed())
        for variable in (self._v2_contraction_mm, self._v2_expansion_mm,
                         self._v2_smoothing_mm, self._v2_brush_size,
                         self._v2_brush_hardness, self._v2_brush_opacity):
            variable.trace_add("write", lambda *_: self._mark_v2_dirty())
        self._v2_ready = True
        self._restore_v2_session()
        self._v2_sync(force=True)
        self._v2_dirty = False
        self.bind("<Control-Key-0>", lambda _e: self._fit_canvas())
        self.bind("<Control-Key-1>", lambda _e: self._actual_size())
        self.bind("<Control-z>", lambda _e: self._undo_edit())
        self.bind("<Control-y>", lambda _e: self._redo_edit())
        self.bind("<Delete>", lambda _e: self._remove_selected())
        self.bind("<Escape>", lambda _e: self._cancel_jobs())
        self.bind("<Control-s>", lambda _e: self._save_v2_session(notify=True))
        self.after(250, self._v2_poll)

    def _build_v2(self):
        root = tk.Frame(self, background=COLORS.background)
        root.pack(fill="both", expand=True)
        top = tk.Frame(root, background=COLORS.panel, height=58,
                       highlightthickness=1, highlightbackground=COLORS.border)
        top.pack(fill="x", padx=10, pady=(10, 6))
        top.pack_propagate(False)
        tk.Label(top, text="STICKER STUDIO 2.0", background=COLORS.panel,
                 foreground=COLORS.text, font=(IDENTITY_FONT, 16, "bold")).pack(side="left", padx=14)
        actions = tk.Frame(top, background=COLORS.panel)
        actions.pack(side="right", padx=10, pady=9)
        specs = (
            ("Importar", self.choose_files, True), ("Pegar", self.paste_image, True),
            ("Carpeta", self.choose_folder, True), ("Deshacer", self._undo_edit, True),
            ("Rehacer", self._redo_edit, True),
            ("Guardar proyecto", lambda: self._save_v2_session(notify=True), True),
            ("Exportar final", self._export_final, True),
        )
        for label, command, enabled in specs:
            button = ttk.Button(actions, text=label, command=command,
                                style="Primary.TButton" if label in {"Procesar", "Exportar final"} else "Secondary.TButton")
            button.pack(side="left", padx=2)
            if not enabled:
                button.state(["disabled"])
            add_tooltip(button, label if enabled else f"{label}: todavía no disponible")

        status = tk.Frame(root, background=COLORS.panel_elevated)
        status.pack(fill="x", padx=10, pady=(0, 6))
        tk.Label(status, textvariable=self.status, background=COLORS.panel_elevated,
                 foreground=COLORS.text, anchor="w", font=(UI_FONT, 9)).pack(side="left", fill="x", expand=True, padx=10, pady=5)
        tk.Label(status, textvariable=self._v2_editor_state, background=COLORS.panel_elevated,
                 foreground=COLORS.warning, font=(UI_FONT, 9, "bold")).pack(side="right", padx=8)
        ttk.Progressbar(status, variable=self.progress_value, maximum=100, length=190).pack(side="right", padx=10)

        queuebar = tk.Frame(root, background=COLORS.panel)
        queuebar.pack(fill="x", padx=10, pady=(0, 6))
        queuebar_top = tk.Frame(queuebar, background=COLORS.panel)
        queuebar_top.pack(fill="x")
        queuebar_more = tk.Frame(queuebar, background=COLORS.panel)
        queuebar_more.pack(fill="x")
        self._v2_action_buttons = {}
        queue_actions = (
            ("Procesar pendientes", self._process_pending, "Procesa sólo trabajos pendientes o reprocesables."),
            ("Procesar seleccionados", self._process_selected, "Procesa la selección de la bandeja."),
            ("Cancelar", self._cancel_jobs, "Cancela el trabajo activo y los seleccionados pendientes."),
            ("Reintentar errores", self._retry_errors, "Reintenta exclusivamente trabajos con Error."),
            ("Quitar seleccionados", self._remove_selected, "Quita de la sesión; nunca borra originales."),
            ("Limpiar finalizados", self._clean_finished, "Quita filas terminadas, canceladas o fallidas."),
            ("Exportar seleccionados", self._export_selected, "Exporta masters reales aprobados o revisados."),
        )
        for position, (label, command, tip) in enumerate(queue_actions):
            parent = queuebar_top if position < 4 else queuebar_more
            button = ttk.Button(parent, text=label, command=command, style="Secondary.TButton")
            button.pack(side="left", padx=2, pady=3)
            self._v2_action_buttons[label] = button
            add_tooltip(button, tip)

        workspace = tk.PanedWindow(root, orient="horizontal", background=COLORS.background,
                                   sashwidth=6, sashrelief="flat", bd=0)
        workspace.pack(fill="both", expand=True, padx=10)
        self._v2_tools = ToolRail(workspace, self._tool_action)
        workspace.add(self._v2_tools, minsize=176, width=184, stretch="never")
        center = tk.Frame(workspace, background=COLORS.background)
        workspace.add(center, minsize=420, stretch="always", padx=7)
        viewbar = tk.Frame(center, background=COLORS.panel)
        viewbar.pack(fill="x", pady=(0, 5))
        tk.Label(viewbar, text="Vista", background=COLORS.panel, foreground=COLORS.muted,
                 font=(UI_FONT, 9)).pack(side="left", padx=(10, 4), pady=6)
        modes = ttk.Combobox(viewbar, textvariable=self._v2_mode, values=VIEW_MODES,
                             state="readonly", width=12)
        modes.pack(side="left", pady=5)
        modes.bind("<<ComboboxSelected>>", lambda _e: self._set_view_mode())
        backgrounds = ttk.Combobox(viewbar, textvariable=self._v2_background,
                                   values=("Damero", "Blanco", "Negro", "Gris", "Magenta"),
                                   state="readonly", width=9)
        backgrounds.pack(side="left", padx=(8, 0), pady=5)
        backgrounds.bind("<<ComboboxSelected>>", lambda _e: self._v2_canvas.set_background(self._v2_background.get()))
        ttk.Checkbutton(viewbar, text="Contorno de corte", variable=self._v2_cut,
                        command=lambda: self._v2_canvas.toggle_cut(self._v2_cut.get())).pack(side="left", padx=10)
        compare_button = ttk.Button(viewbar, text="Comparar", command=self._toggle_compare, style="Secondary.TButton")
        compare_button.pack(side="left", padx=2, pady=4)
        compare_scale = ttk.Scale(viewbar, from_=0, to=100, variable=self._v2_compare_split,
                                  command=lambda value: self._v2_canvas.set_compare_split(float(value)))
        compare_scale.pack(side="left", padx=4, pady=4)
        fit_button = ttk.Button(viewbar, text="Ajustar", command=self._fit_canvas, style="Secondary.TButton")
        fit_button.pack(side="right", padx=7, pady=4)
        actual_button = ttk.Button(viewbar, text="100 %", command=self._actual_size, style="Secondary.TButton")
        actual_button.pack(side="right", padx=2, pady=4)
        center_button = ttk.Button(viewbar, text="Centro", command=self._center_canvas, style="Secondary.TButton")
        center_button.pack(side="right", padx=2, pady=4)
        zoom_entry = ttk.Spinbox(viewbar, from_=5, to=1600, increment=5,
                                 textvariable=self._v2_zoom_percent, width=6,
                                 command=self._set_numeric_zoom)
        zoom_entry.pack(side="right", padx=2, pady=4)
        zoom_entry.bind("<Return>", lambda _e: self._set_numeric_zoom())
        for button, tip in ((compare_button, "Alterna original y resultado."),
                            (fit_button, "Ajusta la imagen al espacio disponible (Ctrl+0)."),
                            (actual_button, "Vuelve al zoom 100 % (Ctrl+1)."),
                            (center_button, "Centra la imagen sin cambiar el zoom.")):
            add_tooltip(button, tip)
        self._v2_canvas = StickerCanvas(
            center, on_stroke=self._mask_stroke,
            brush_provider=self._brush_settings)
        self._v2_canvas.pack(fill="both", expand=True)
        self._v2_inspector = Inspector(
            workspace, self, self._apply_inspector, self._schedule_contraction_preview,
            self._interactive_parameter_changed,
            self._commit_interactive_preview,
            self._undo_edit, self._redo_edit, self._reset_edit,
            self._approve_mask_reference, self._review_current, self._send_to_processed)
        workspace.add(self._v2_inspector, minsize=260, width=280, stretch="never")
        self._v2_tray = ThumbnailTray(root, self._select_v2_job,
                                      self._remove_selected, self._process_selected)
        self._v2_tray.pack(fill="x", padx=10, pady=(6, 10))
        self.bind("<KeyPress-space>", self._global_space_down, add="+")
        self.bind("<KeyRelease-space>", self._global_space_up, add="+")

    def _tool_action(self, action):
        edit_tools = {"mask": "restore", "erase": "erase", "protect": "protect",
                      "refine": "refine"}
        if action in edit_tools:
            self._v2_tools.set_active(action)
            self._v2_canvas.set_edit_tool(edit_tools[action])
            labels = {"restore": "Pincel restaurar", "erase": "Borrador",
                      "protect": "Protección", "refine": "Refinamiento local"}
            self.status.set(f"{labels[edit_tools[action]]}: dibujá directamente sobre el sticker.")
            return
        self._v2_canvas.set_edit_tool(None)
        self._v2_tools.set_active(action if action == "zoom" else None)
        commands = {
            "select": self.open_area_selection,
            "auto": self._process_current,
            "background": self.reprocess_current,
            "objects": self.create_individual_objects,
            "cut": self.open_cut_editor,
            "zoom": self._fit_canvas,
        }
        command = commands.get(action)
        if command:
            command()

    def _process_current(self):
        if self.current_index is not None:
            self._start_filtered_batch([self.current_index])

    def _process_index(self, index):
        if 0 <= index < len(self.jobs):
            self.jobs[index]["v2_running_parameter_state"] = self._current_parameter_state(
                self.jobs[index])
        super()._process_index(index)

    def _set_numeric_zoom(self):
        try:
            self._v2_canvas._state.set_zoom(float(self._v2_zoom_percent.get()) / 100.0)
        except (TypeError, ValueError, tk.TclError):
            return
        self._v2_canvas.render()

    def _global_space_down(self, event):
        focus = self.focus_get()
        if focus and focus.winfo_class() in {"Entry", "TEntry", "Text", "TCombobox", "TSpinbox"}:
            return None
        return self._v2_canvas._space_down(event)

    def _global_space_up(self, event):
        return self._v2_canvas._space_up(event)

    def _select_v2_job(self, index, event=None, context=False):
        if not (0 <= index < len(self.jobs)):
            return
        ctrl = bool(event and event.state & 0x0004)
        shift = bool(event and event.state & 0x0001)
        if context and index in self._v2_selection.indices:
            pass
        else:
            self._v2_selection.click(index, ctrl=ctrl, shift=shift, count=len(self.jobs))
        if not self._v2_selection.indices:
            self._v2_selection.click(index, count=len(self.jobs))
        self.current_index = index
        # El Treeview legacy conserva la lógica de guardado por trabajo.
        self.queue.selection_set(str(index))
        self.queue.focus(str(index))
        self.select_job()
        self._v2_sync(force=True)

    def _set_view_mode(self):
        state = self._v2_state.current()
        state.mode = self._v2_mode.get()
        self._v2_canvas.set_mode(state.mode)

    def _fit_canvas(self):
        self._v2_canvas.fit()

    def _actual_size(self):
        self._v2_canvas.actual_size()

    def _center_canvas(self):
        self._v2_canvas.center()

    def _toggle_compare(self):
        self._v2_compare.set(not self._v2_compare.get())
        self._v2_state.current().compare = self._v2_compare.get()
        self._v2_canvas.toggle_compare(self._v2_compare.get())

    def _preview_changed(self):
        self._mark_v2_dirty()
        self._schedule_contraction_preview()

    def _mark_v2_dirty(self):
        if self._v2_ready and not getattr(self, "_v2_syncing", False):
            self._v2_dirty = True
            self._v2_editor_state.set("Cambios pendientes")

    @staticmethod
    def _parameter_state(job, border_mm, quality, treatment, contraction, expansion, smoothing):
        return {
            "border_mm": round(float(border_mm), 2), "quality": str(quality),
            "border_treatment": str(treatment),
            "contraction_mm": round(float(contraction), 2),
            "expansion_mm": round(float(expansion), 2),
            "smoothing_mm": round(float(smoothing), 2),
        }

    def _current_parameter_state(self, job):
        return self._parameter_state(
            job, job.get("v2_border_mm", self.profile.final_white_px / self.profile.dpi * 25.4),
            job.get("v2_quality", self.profile.quality), job.get("border_treatment") or "Automático",
            job.get("selection_contraction_mm", 0.0), job.get("selection_expansion_mm", 0.0),
            job.get("selection_smoothing_mm", 0.08))

    def _visible_parameter_state(self, job):
        return self._parameter_state(
            job, self._v2_border_mm.get(), self._v2_quality.get(), self._v2_border_treatment.get(),
            self._v2_contraction_mm.get(), self._v2_expansion_mm.get(), self._v2_smoothing_mm.get())

    @staticmethod
    def _record_operation(job, operation):
        history = job.setdefault("v2_operation_undo", [])
        history.append(operation)
        del history[:-100]
        job["v2_operation_redo"] = []

    def _restore_parameter_state(self, job, state):
        self._v2_border_mm.set(state["border_mm"])
        self._v2_quality.set(state["quality"])
        self._v2_border_treatment.set(state["border_treatment"])
        self._v2_contraction_mm.set(state["contraction_mm"])
        self._v2_expansion_mm.set(state["expansion_mm"])
        self._v2_smoothing_mm.set(state["smoothing_mm"])
        job.update(v2_border_mm=state["border_mm"], v2_quality=state["quality"],
                   border_treatment=None if state["border_treatment"] == "Automático" else state["border_treatment"],
                   selection_contraction_mm=state["contraction_mm"],
                   selection_expansion_mm=state["expansion_mm"],
                   selection_smoothing_mm=state["smoothing_mm"])

    def _export_final(self):
        """Exporta exactamente el master mostrado, sin recomponer ni reescalar."""
        job = self.current_job()
        result = job.get("result") if job else None
        if job and self._job_has_pending_parameters(job):
            messagebox.showwarning(
                "Cálculo pendiente",
                "Esperá a que termine el master definitivo del ajuste actual antes de exportar.",
                parent=self)
            return
        if not job or not review_is_current(job):
            messagebox.showwarning(
                "Falta revisión",
                "Revisá el master actual antes de exportarlo. Si el resultado cambió, necesita una revisión nueva.",
                parent=self,
            )
            return
        source = str(master_path(job) or "")
        if not source or not Path(source).is_file():
            messagebox.showwarning("Sin resultado", "Procesá el sticker antes de exportarlo.", parent=self)
            return
        destination = filedialog.asksaveasfilename(
            parent=self, defaultextension=".png",
            initialfile=f"{Path(job['source_path']).stem}_sticker.png",
            filetypes=[("PNG transparente", "*.png")])
        if not destination:
            return
        PipelineViewAdapter.export_final(source, destination)
        record_export(job, destination)
        self._save_v2_session()
        self.status.set(f"PNG exportado sin recomposición: {Path(destination).name}")

    def _selected_indices(self):
        if self._v2_selection.indices:
            return sorted(i for i in self._v2_selection.indices if i < len(self.jobs))
        return [] if self.current_index is None else [self.current_index]

    def _job_has_pending_parameters(self, job):
        if job is self.current_job():
            return self._current_parameter_state(job) != self._visible_parameter_state(job)
        return bool(job.get("v2_preview_active") or job.get("v2_pending_definitive"))

    def _start_filtered_batch(self, indices):
        eligible = [i for i in sorted(set(indices)) if 0 <= i < len(self.jobs)
                    and self.jobs[i].get("status") in {"Pendiente", "Reprocesar", "Cancelado", "Error"}]
        if not eligible:
            self.status.set("La selección no contiene trabajos procesables.")
            return
        if self.worker and self.worker.is_alive():
            self.status.set("Ya hay un procesamiento activo; no se inició otro.")
            return
        for index in eligible:
            self.jobs[index]["status"] = "Pendiente"
            self.jobs[index].pop("error", None)
        self._v2_batch_filter = set(eligible)
        self.cancel_event.clear()
        self._process_index(eligible[0])
        self._save_v2_session()

    def _process_selected(self):
        self._start_filtered_batch(self._selected_indices())

    def _process_pending(self):
        self._start_filtered_batch(i for i, job in enumerate(self.jobs)
                                   if job.get("status") in {"Pendiente", "Reprocesar"})

    def _retry_errors(self):
        self._start_filtered_batch(i for i, job in enumerate(self.jobs)
                                   if job.get("status") == "Error")

    def _cancel_jobs(self):
        selected = set(self._selected_indices())
        changed = 0
        for index, job in enumerate(self.jobs):
            if index in selected and job.get("status") in {"Pendiente", "Reprocesar"}:
                job["status"] = "Cancelado"; changed += 1
        active = next((i for i, job in enumerate(self.jobs) if job.get("status") == "Procesando"), None)
        if active is not None and (not selected or active in selected):
            self.cancel_processing(); changed += 1
        if not changed:
            self.status.set("No hay trabajos seleccionados que puedan cancelarse.")
        self.refresh_queue(); self._save_v2_session()

    def _remove_selected(self):
        indices = self._selected_indices()
        if not indices:
            return
        if any(self.jobs[i].get("status") == "Procesando" for i in indices):
            messagebox.showwarning("Trabajo activo", "Cancelá o esperá el trabajo activo antes de quitarlo.", parent=self)
            return
        names = [Path(self.jobs[i]["source_path"]).name for i in indices]
        preview = "\n".join(f"• {name}" for name in names[:6])
        if len(names) > 6:
            preview += f"\n• y {len(names)-6} más"
        if not messagebox.askyesno(
                "Quitar de esta sesión",
                f"¿Querés eliminar estos {len(names)} sticker(s) del editor?\n\n{preview}\n\n"
                "Se quitarán únicamente de esta sesión. Los archivos originales, pedidos y diseños guardados no serán eliminados.",
                parent=self):
            return
        old_count = len(self.jobs)
        removed_set = set(indices)
        remove_from_session(self.jobs, indices,
                            discard_result=getattr(self.database, "discard_processed_sticker", None))
        self._v2_selection.normalize_after_removal(removed_set, old_count)
        if self.jobs:
            self.current_index = min(indices[0], len(self.jobs)-1)
            self._v2_selection.click(self.current_index, count=len(self.jobs))
            self.queue.selection_set(str(self.current_index))
        else:
            self.current_index = None
        self._v2_state.discard_missing(self.jobs)
        self.refresh_queue(); self._save_v2_session()
        self.status.set(f"Se quitaron {len(indices)} sticker(s) de esta sesión. Los originales se conservaron.")

    def _clean_finished(self):
        indices = [i for i, job in enumerate(self.jobs) if job.get("status") in REMOVABLE_CLEAN_STATES]
        if not indices:
            self.status.set("No hay trabajos terminados o fallidos para limpiar.")
            return
        self._v2_selection.indices = set(indices)
        self._remove_selected()

    def _export_selected(self):
        indices = self._selected_indices()
        exportable = [i for i in indices if review_is_current(self.jobs[i])
                      and not self._job_has_pending_parameters(self.jobs[i])]
        if not exportable:
            messagebox.showwarning("Sin resultados", "La selección no contiene PNG finales exportables.", parent=self)
            return
        if len(exportable) == 1:
            self.current_index = exportable[0]
            return self._export_final()
        folder = filedialog.askdirectory(parent=self, title="Carpeta para exportar stickers")
        if not folder:
            return
        used = set()
        for index in exportable:
            job = self.jobs[index]
            stem = Path(job["source_path"]).stem
            name = f"{stem}_sticker.png"; suffix = 2
            while name.lower() in used or (Path(folder) / name).exists():
                name = f"{stem}_sticker_{suffix}.png"; suffix += 1
            used.add(name.lower())
            PipelineViewAdapter.export_final(job["result"].artifacts["master"], Path(folder) / name)
            record_export(job, Path(folder) / name)
        self.refresh_queue(); self._save_v2_session()
        self.status.set(f"Se exportaron {len(exportable)} PNG sin recomposición.")

    def _apply_inspector(self):
        try:
            border_mm = max(0.0, float(self._v2_border_mm.get()))
        except (TypeError, ValueError, tk.TclError):
            self.status.set("El grosor del borde debe ser un número válido.")
            return
        self.profile.final_white_px = round(border_mm / 25.4 * self.profile.dpi)
        self.profile.quality = self._v2_quality.get()
        job = self.current_job()
        if job is not None:
            before = self._current_parameter_state(job)
            after = self._visible_parameter_state(job)
            if before != after:
                self._record_operation(job, {"kind": "parameters", "before": before, "after": after})
            invalidate_review(job, "parameters_changed")
            # La preferencia acompaña al trabajo durante la sesión. El editor
            # legacy sigue siendo quien materializa el perfil al reprocesar.
            job["v2_border_mm"] = border_mm
            job["v2_quality"] = self.profile.quality
            requested_border = self._v2_border_treatment.get()
            job["border_treatment"] = (
                None if requested_border == "Automático" else requested_border)
            job["selection_contraction_mm"] = round(float(self._v2_contraction_mm.get()), 2)
            job["selection_expansion_mm"] = round(float(self._v2_expansion_mm.get()), 2)
            job["selection_smoothing_mm"] = round(float(self._v2_smoothing_mm.get()), 2)
            self._materialize_manual_mask(job)
            job.pop("v2_preview_active", None)
            self._save_v2_session()
            if job.get("status") == "Procesando":
                job["v2_pending_definitive"] = True
                self.cancel_event.set()
                self.status.set("Descartando cálculo anterior; se aplicará el ajuste más reciente…")
                return
        self.reprocess_current()

    def _interactive_parameter_changed(self):
        """Respuesta rápida mientras se mueve; consolida tras una pausa real."""
        self._schedule_contraction_preview()
        if self._v2_commit_after is not None:
            try:
                self.after_cancel(self._v2_commit_after)
            except tk.TclError:
                pass
        self._v2_commit_after = self.after(650, self._commit_interactive_preview)

    def _commit_interactive_preview(self):
        """Materializa sólo si el control visible difiere del master vigente."""
        if self._v2_commit_after is not None:
            try:
                self.after_cancel(self._v2_commit_after)
            except tk.TclError:
                pass
            self._v2_commit_after = None
        job = self.current_job()
        if job is None or self._current_parameter_state(job) == self._visible_parameter_state(job):
            return
        self._cancel_v2_preview()
        self._v2_editor_state.set("Generando master definitivo…")
        self._apply_inspector()

    def _cancel_v2_preview(self):
        self._v2_preview_generation += 1
        if self._v2_preview_after is not None:
            try:
                self.after_cancel(self._v2_preview_after)
            except tk.TclError:
                pass
            self._v2_preview_after = None
        if self._v2_preview_future is not None and not self._v2_preview_future.done():
            self._v2_preview_future.cancel()
        job = self.current_job()
        if job is not None:
            job.pop("v2_preview_active", None)

    def _schedule_contraction_preview(self):
        if not hasattr(self, "_v2_canvas"):
            return
        self._v2_preview_generation += 1
        if self._v2_preview_future is not None and not self._v2_preview_future.done():
            self._v2_preview_future.cancel()
        if self._v2_preview_after:
            self.after_cancel(self._v2_preview_after)
        self._v2_preview_after = self.after(140, self._update_contraction_preview)

    def _update_contraction_preview(self):
        self._v2_preview_after = None
        job = self.current_job()
        if not job:
            return
        job["v2_preview_active"] = True
        job["v2_preview_contraction_mm"] = round(float(self._v2_contraction_mm.get()), 2)
        job["v2_preview_expansion_mm"] = round(float(self._v2_expansion_mm.get()), 2)
        job["v2_preview_smoothing_mm"] = round(float(self._v2_smoothing_mm.get()), 2)
        job["v2_preview_border_mm"] = max(0.0, float(self._v2_border_mm.get()))
        job["v2_selection_view"] = self._v2_selection_view.get()
        document = self._mask_document(job)
        base_path = job.get("v2_mask_base_path")
        if not document or not base_path or not Path(base_path).is_file():
            self._v2_canvas.render()
            return
        generation = self._v2_preview_generation
        job["v2_preview_requested_generation"] = generation
        self._v2_editor_state.set("Calculando vista previa…")
        with Image.open(base_path) as image:
            base = image.convert("L").copy()
        result = job.get("result")
        dpi = float(getattr(result, "analysis", {}).get("source_processing_dpi") or 300)
        offset = job["v2_preview_contraction_mm"] - job["v2_preview_expansion_mm"]
        smoothing = job["v2_preview_smoothing_mm"]
        snapshot = copy.deepcopy(document)
        future = self._v2_preview_executor.submit(
            self._render_geometry_preview, snapshot, base, offset, dpi, smoothing)
        self._v2_preview_future = future
        self.after(20, lambda j=job, g=generation, f=future: self._poll_async_preview(j, g, f))

    def _render_geometry_preview(self, document, base, offset, dpi, smoothing):
        operations = tuple(
            (stroke.tool, stroke.points, stroke.size_px, stroke.hardness, stroke.opacity)
            for stroke in document.operations)
        key = (document.base_sha256, document.width, document.height, operations,
               float(offset), float(dpi), float(smoothing))
        cached = self._v2_geometry_cache.get(key)
        if cached is not None:
            self._v2_geometry_cache.move_to_end(key)
            mask, protection, report, _size = cached
            return mask.copy(), protection.copy(), report
        mask, protection, report = document.render(base, offset, dpi, smoothing)
        size = mask.width * mask.height + protection.width * protection.height
        self._v2_geometry_cache[key] = (mask.copy(), protection.copy(), report, size)
        self._v2_geometry_cache_bytes = getattr(self, "_v2_geometry_cache_bytes", 0) + size
        self._v2_geometry_cache.move_to_end(key)
        limit = getattr(self, "_v2_geometry_cache_limit", 64 * 1024 * 1024)
        while self._v2_geometry_cache_bytes > limit and len(self._v2_geometry_cache) > 1:
            _old_key, (_mask, _protection, _report, old_size) = self._v2_geometry_cache.popitem(last=False)
            self._v2_geometry_cache_bytes -= old_size
        return mask, protection, report

    def _poll_async_preview(self, job, generation, future):
        """Consulta el worker desde Tk; ningún hilo secundario toca widgets."""
        if generation != self._v2_preview_generation or not self.winfo_exists():
            return
        if not future.done():
            self.after(20, lambda: self._poll_async_preview(job, generation, future))
            return
        self._finish_async_preview(job, generation, future)

    def _finish_async_preview(self, job, generation, future):
        if generation != self._v2_preview_generation or job is not self.current_job():
            return
        try:
            mask, protection, report = future.result()
        except Exception as error:
            self._v2_editor_state.set("Error de vista previa")
            self.status.set(f"No se pudo calcular la vista previa: {error}")
            return
        job["v2_preview_mask_image"] = mask
        job["v2_preview_protection_image"] = protection
        job["v2_preview_contraction_report"] = report.to_dict()
        job["v2_preview_ready_generation"] = generation
        self._v2_canvas.render()
        self._v2_editor_state.set("Vista previa sin aplicar")
        report = job.get("v2_preview_contraction_report", {})
        if report.get("requires_review"):
            self.status.set("Advertencia de contracción: " + " ".join(report.get("warnings", [])))
        else:
            self.status.set(
                f"Vista previa: contraer {job['v2_preview_contraction_mm']:.1f} mm · "
                f"expandir {job['v2_preview_expansion_mm']:.1f} mm · "
                "cian original / magenta contraída.")

    def _undo_edit(self):
        job = self.current_job()
        history = job.get("v2_operation_undo", []) if job else []
        if not history:
            document = self._mask_document(job) if job else None
            if document and document.undo():
                self._save_mask_document(job, document)
                self._schedule_contraction_preview(); self._save_v2_session()
                self.status.set("Trazo anterior deshecho.")
                return
            self.status.set("No hay operaciones para deshacer.")
            return
        operation = history.pop()
        document = self._mask_document(job)
        if operation["kind"] == "mask" and document:
            document.undo(); self._save_mask_document(job, document)
        elif operation["kind"] == "mask_reset" and document:
            document.operations = [MaskStroke.from_dict(value) for value in operation["operations"]]
            document.redo_operations = []
            self._save_mask_document(job, document)
        elif operation["kind"] == "parameters":
            self._restore_parameter_state(job, operation["before"])
        job.setdefault("v2_operation_redo", []).append(operation)
        invalidate_review(job, "undo")
        self._schedule_contraction_preview()
        self._save_v2_session()
        self.status.set("Operación deshecha.")

    def _redo_edit(self):
        job = self.current_job()
        history = job.get("v2_operation_redo", []) if job else []
        if not history:
            document = self._mask_document(job) if job else None
            if document and document.redo():
                self._save_mask_document(job, document)
                self._schedule_contraction_preview(); self._save_v2_session()
                self.status.set("Trazo anterior rehecho.")
                return
            self.status.set("No hay operaciones para rehacer.")
            return
        operation = history.pop()
        document = self._mask_document(job)
        if operation["kind"] == "mask" and document:
            document.redo(); self._save_mask_document(job, document)
        elif operation["kind"] == "mask_reset" and document:
            document.reset(); self._save_mask_document(job, document)
        elif operation["kind"] == "parameters":
            self._restore_parameter_state(job, operation["after"])
        job.setdefault("v2_operation_undo", []).append(operation)
        invalidate_review(job, "redo")
        self._schedule_contraction_preview()
        self._save_v2_session()
        self.status.set("Operación rehecha.")

    def _reset_edit(self):
        job = self.current_job()
        if job:
            before = self._current_parameter_state(job)
            document = self._mask_document(job)
            if document:
                if document.operations:
                    serialized = [{"tool": stroke.tool, "points": stroke.points,
                                   "size_px": stroke.size_px, "hardness": stroke.hardness,
                                   "opacity": stroke.opacity} for stroke in document.operations]
                    self._record_operation(job, {"kind": "mask_reset", "operations": serialized})
                document.reset()
                self._save_mask_document(job, document)
            job["selection_contraction_mm"] = 0.0
            job["selection_expansion_mm"] = 0.0
            job["selection_smoothing_mm"] = 0.08
        self._v2_contraction_mm.set(0.0)
        self._v2_expansion_mm.set(0.0)
        self._v2_smoothing_mm.set(0.08)
        if job:
            after = self._visible_parameter_state(job)
            if before != after:
                self._record_operation(job, {"kind": "parameters", "before": before, "after": after})
            invalidate_review(job, "reset")
        self._schedule_contraction_preview()
        self._save_v2_session()

    def _v2_sync(self, force=False):
        if not self._v2_ready:
            return
        self._v2_syncing = True
        job = self.current_job()
        state = self._v2_state.select(job, self.current_index or 0) if job else self._v2_state.current()
        if force or getattr(self, "_v2_last_job", None) is not job:
            self._v2_last_job = job
            if job:
                border_mm = job.get(
                    "v2_border_mm", self.profile.final_white_px / self.profile.dpi * 25.4)
                quality = job.get("v2_quality", self.profile.quality)
                self._v2_border_mm.set(border_mm)
                self._v2_quality.set(quality)
                self._v2_border_treatment.set(job.get(
                    "border_treatment") or "Automático")
                self._v2_contraction_mm.set(job.get("selection_contraction_mm", 0.0))
                self._v2_expansion_mm.set(job.get("selection_expansion_mm", 0.0))
                self._v2_smoothing_mm.set(job.get("selection_smoothing_mm", 0.08))
                self._mask_document(job)
                self.profile.final_white_px = round(float(border_mm) / 25.4 * self.profile.dpi)
                self.profile.quality = quality
            self._v2_mode.set(state.mode)
            self._v2_cut.set(state.show_cut)
            self._v2_compare.set(state.compare)
            self._v2_canvas.show_job(job, state)
            self._v2_inspector.update_job(job)
        selected = self._v2_selection.indices or (
            set() if self.current_index is None else {self.current_index})
        self._v2_tray.refresh(self.jobs, selected)
        self._v2_syncing = False

    def _v2_poll(self):
        if not self.winfo_exists():
            return
        self._v2_sync()
        self._update_action_states()
        if hasattr(self, "_v2_canvas"):
            self._v2_zoom_percent.set(round(self._v2_canvas._state.zoom * 100, 1))
        self.after(250, self._v2_poll)

    def _update_action_states(self):
        if not hasattr(self, "_v2_action_buttons"):
            return
        busy = bool(self.worker and self.worker.is_alive())
        for label in ("Procesar pendientes", "Procesar seleccionados", "Reintentar errores",
                      "Quitar seleccionados", "Limpiar finalizados"):
            self._v2_action_buttons[label].state(["disabled"] if busy else ["!disabled"])
        self._v2_action_buttons["Cancelar"].state(["!disabled"] if busy or self.jobs else ["disabled"])

    def _continue_queue(self):
        if self.cancel_event.is_set():
            self._v2_batch_filter = None
            return
        if self._v2_batch_filter is not None:
            pending = next((i for i in sorted(self._v2_batch_filter)
                            if i < len(self.jobs) and self.jobs[i].get("status") in {"Pendiente", "Reprocesar"}), None)
            if pending is None:
                self._v2_batch_filter = None
                self.status.set("Lote seleccionado finalizado. Los resultados requieren revisión.")
                self._save_v2_session()
                return
            self.after(80, lambda: self._process_index(pending))
            return
        super()._continue_queue()

    def _finish_result(self, index, result):
        if 0 <= index < len(self.jobs):
            job = self.jobs[index]
            running = job.pop("v2_running_parameter_state", None)
            if running is not None and running != self._current_parameter_state(job):
                job["status"] = "Reprocesar"
                job.pop("v2_pending_definitive", None)
                self.cancel_event.clear()
                self.status.set("Resultado obsoleto descartado; generando el master vigente…")
                self.after(80, self.reprocess_current)
                return
        viewed = self.current_index
        super()._finish_result(index, result)
        if 0 <= index < len(self.jobs):
            invalidate_review(self.jobs[index], "master_reprocessed")
        if viewed is not None and viewed != index and viewed < len(self.jobs):
            self.current_index = viewed
            self.queue.selection_set(str(viewed))
        self._save_v2_session()
        self._v2_sync(force=True)

    def _finish_error(self, index, error):
        super()._finish_error(index, error)
        self._save_v2_session()

    def _finish_cancelled(self, index):
        pending = (0 <= index < len(self.jobs)
                   and self.jobs[index].pop("v2_pending_definitive", False))
        if 0 <= index < len(self.jobs):
            self.jobs[index].pop("v2_running_parameter_state", None)
        super()._finish_cancelled(index)
        self._v2_batch_filter = None
        if pending:
            self.cancel_event.clear()
            self.jobs[index]["status"] = "Reprocesar"
            self.after(80, self.reprocess_current)
            self.status.set("Generando el master definitivo del ajuste más reciente…")
        self._save_v2_session()

    def add_paths(self, paths, run_queue: bool = True):
        before = len(self.jobs)
        # V2 deja decidir qué procesar; importar no dispara trabajo pesado.
        super().add_paths(paths, run_queue=False)
        if len(self.jobs) > before:
            self._v2_selection.click(before, count=len(self.jobs))
            self.current_index = before
            self._save_v2_session()
            self._v2_sync(force=True)

    def _serialize_views(self):
        return {key: {"mode": value.mode, "zoom": value.zoom,
                      "pan_x": value.pan_x, "pan_y": value.pan_y,
                      "fitted": value.fitted, "show_cut": value.show_cut,
                      "compare": value.compare}
                for key, value in self._v2_state.views.items()}

    def _save_v2_session(self, notify=False):
        self._v2_editor_state.set("Guardando…")
        self._v2_store.save(self.jobs, self._serialize_views())
        self._v2_dirty = False
        self._v2_editor_state.set("Guardado")
        if notify:
            self.status.set("Proyecto de sesión guardado.")

    def _restore_v2_session(self):
        payload = self._v2_store.load()
        known = {job.get("source_path") for job in self.jobs}
        for row in payload.get("jobs", []):
            if row.get("source_path") in known:
                continue
            result = None
            metadata = row.pop("result_metadata", None)
            if metadata and Path(metadata).is_file():
                try:
                    result = ProcessingResult.from_metadata(metadata)
                except (OSError, ValueError, KeyError, TypeError):
                    result = None
            status = row.get("status", "Pendiente")
            if status == "Procesando":
                status = "Cancelado"
            if result is None and status in {"Procesado", "Confirmado", "Exportado"}:
                status = "Pendiente"
            job = dict(row, status=status, result=result, force=False,
                       is_png=Path(row["source_path"]).suffix.lower() == ".png",
                       protection_zones=[])
            self.jobs.append(job); known.add(row["source_path"])
        for key, raw in payload.get("views", {}).items():
            try:
                self._v2_state.views[key] = CanvasState(**raw)
            except (TypeError, ValueError):
                continue
        if self.jobs and self.current_index is None:
            self.current_index = 0
        if self.jobs:
            self._v2_selection.click(self.current_index or 0, count=len(self.jobs))

    def close(self):
        if self._v2_dirty:
            decision = messagebox.askyesnocancel(
                "Cambios sin guardar",
                "Hay ajustes de esta sesión todavía no guardados. ¿Querés guardarlos antes de cerrar?",
                parent=self)
            if decision is None:
                return
            if decision:
                self._save_v2_session()
        else:
            self._save_v2_session()
        self._v2_preview_generation += 1
        self._v2_preview_executor.shutdown(wait=False, cancel_futures=True)
        super().close()

    def refresh_queue(self, scroll_to=None):
        super().refresh_queue(scroll_to)
        if getattr(self, "_v2_ready", False):
            self._v2_sync(force=True)

    def render_current(self):
        super().render_current()
        if getattr(self, "_v2_ready", False):
            self._v2_sync(force=True)

    def _brush_settings(self):
        return {"size_px": float(self._v2_brush_size.get()),
                "hardness": float(self._v2_brush_hardness.get()),
                "opacity": float(self._v2_brush_opacity.get())}

    def _mask_storage(self, job):
        source = Path(job["source_path"])
        key = sha256(str(source.resolve()).encode("utf-8")).hexdigest()[:16]
        return Path("artifacts/sticker-mask-edits") / key

    def _mask_document(self, job):
        if not job or not job.get("result"):
            return None
        if job.get("v2_mask_document") is not None:
            return job["v2_mask_document"]
        artifacts = PipelineViewAdapter.artifacts(job)
        mask_path = artifacts.get("selection_alpha_original") or artifacts.get("mask_editable")
        if not mask_path or not Path(mask_path).is_file():
            return None
        storage = self._mask_storage(job)
        storage.mkdir(parents=True, exist_ok=True)
        base_path = storage / "base_alpha.png"
        if not base_path.exists():
            with Image.open(mask_path) as image:
                image.convert("L").save(base_path)
        with Image.open(base_path) as image:
            base = image.convert("L").copy()
        document_path = storage / "edits.json"
        try:
            document = MaskEditDocument.load(document_path) if document_path.exists() else MaskEditDocument.for_base(base)
            if not document.compatible(base):
                raise ValueError("La máscara base no coincide con el historial.")
        except (ValueError, OSError, KeyError, TypeError):
            document = MaskEditDocument.for_base(base)
            self.status.set("La base cambió: se inició una edición nueva sin reutilizar trazos incompatibles.")
        job["v2_mask_document"] = document
        job["v2_mask_base_path"] = str(base_path)
        job["v2_mask_document_path"] = str(document_path)
        job["v2_preview_active"] = True
        return document

    def _save_mask_document(self, job, document):
        document.save(job["v2_mask_document_path"])
        job["v2_mask_document"] = document
        job["v2_preview_active"] = True

    def _mask_stroke(self, tool, points, settings):
        job = self.current_job()
        document = self._mask_document(job) if job else None
        if document is None:
            self.status.set("Procesá el sticker antes de editar su máscara.")
            return
        invalidate_review(job, "mask_edited")
        document.add(MaskStroke(tool, points, **settings))
        self._record_operation(job, {"kind": "mask"})
        self._save_mask_document(job, document)
        self._schedule_contraction_preview()
        self._save_v2_session()
        self.status.set(f"Operación de máscara registrada: {tool}.")

    def _materialize_manual_mask(self, job):
        document = self._mask_document(job)
        if document is None:
            return
        with Image.open(job["v2_mask_base_path"]) as image:
            base = image.convert("L").copy()
        manual, protection = document.render_manual(base)
        storage = self._mask_storage(job)
        manual_path, protection_path = storage / "manual_mask.png", storage / "protection_mask.png"
        manual.save(manual_path)
        protection.save(protection_path)
        job["mask_override"] = str(manual_path)
        job["selection_protection_mask"] = str(protection_path)

    def _approve_mask_reference(self):
        job = self.current_job()
        document = self._mask_document(job) if job else None
        if document is None:
            messagebox.showwarning("Sin máscara", "Procesá y revisá una máscara antes de aprobarla.", parent=self)
            return
        if not messagebox.askyesno(
                "Aprobar referencia humana",
                "¿Confirmás visualmente esta máscara como referencia? Esta decisión no la toma el algoritmo.",
                parent=self):
            return
        with Image.open(job["v2_mask_base_path"]) as image:
            base = image.convert("L").copy()
        dpi = float(getattr(job.get("result"), "analysis", {}).get("source_processing_dpi") or 300)
        mask, _protection, _report = document.render(
            base, float(self._v2_contraction_mm.get())-float(self._v2_expansion_mm.get()),
            dpi, float(self._v2_smoothing_mm.get()))
        destination = self._mask_storage(job) / "approved_reference.png"
        manifest = save_approved_reference(mask, job["source_path"], destination)
        with Image.open(job["v2_mask_base_path"]) as automatic_source:
            comparison = compare_masks(
                automatic_source.convert("L"), mask,
                self._mask_storage(job) / "automatic_vs_approved.png")
        manifest["comparison"] = comparison
        import json
        Path(manifest["manifest_path"]).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        job["approved_mask_reference"] = manifest
        self._save_v2_session()
        self.status.set(f"Referencia aprobada por el usuario: {destination.name}")

    def _review_current(self):
        job = self.current_job()
        result = job.get("result") if job else None
        if job and self._job_has_pending_parameters(job):
            messagebox.showwarning(
                "Cálculo pendiente",
                "Esperá a que termine el master definitivo antes de revisarlo.", parent=self)
            return False
        if not job or not result:
            messagebox.showwarning("Sin resultado", "Procesá el sticker antes de revisarlo.", parent=self)
            return False
        errors = getattr(result, "analysis", {}).get("quality_report", {}).get("errors", [])
        if errors:
            messagebox.showerror("Resultado inválido", "Corregí los errores técnicos antes de revisar el master.", parent=self)
            return False
        mark_reviewed(job)
        self._save_v2_session()
        self._v2_sync(force=True)
        self.status.set("Master revisado. Ya puede exportarse o enviarse a Últimos Procesados.")
        return True

    def _send_to_processed(self):
        job = self.current_job()
        if job and self._job_has_pending_parameters(job):
            messagebox.showwarning(
                "Cálculo pendiente",
                "Esperá a que termine el master definitivo antes de enviarlo.", parent=self)
            return False
        if not job or not review_is_current(job):
            messagebox.showwarning("Falta revisión", "Revisá el master actual antes de enviarlo.", parent=self)
            return False
        if job.get("sent_to_processed"):
            self.status.set("Este master ya fue enviado a Últimos Procesados; no se creó un duplicado.")
            return True
        if not super().approve_current(keep_in_session=True):
            return False
        mark_sent(job)
        self._save_v2_session()
        self._v2_sync(force=True)
        return True

    def approve_current(self):
        """Compatibilidad: en V2 aprobar significa revisar, no publicar."""
        return self._review_current()
