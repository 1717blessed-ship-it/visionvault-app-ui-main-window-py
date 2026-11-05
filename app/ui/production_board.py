"""Vista de tablero kanban para gestión visual de producción por etapas.

ProductionBoardView muestra pedidos agrupados por etapa en columnas verticales,
con métricas agregadas y tiles interactivos para cada pedido.
"""

from __future__ import annotations

import json
import sqlite3
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox
from typing import Callable

from app.database.database import ImageDatabase
from app.services.stage_service import StageService
from app.services.production_feedback_service import ProductionFeedbackService
from app.ui.production_order_tile import ProductionOrderTile
from app.ui.theme import COLORS, UI_FONT, IDENTITY_FONT
from app.ui.components import section_heading, Toast


class ProductionBoardView(tk.Frame):
    """Tablero visual de producción agrupado por etapas.

    Características:
    - Contenedor horizontal desplazable para columnas del tablero
    - Cada columna 250-290px, mismo ancho, altura adaptable
    - Scroll horizontal con barra inferior + Shift+rueda del mouse
    - Panel lateral derecho con filtros de producción
    - Persistencia de posición horizontal mientras la pestaña está abierta
    - Filtros: búsqueda + checkboxes + botón limpiar
    - Actualización que conserva filtros, scroll, selección, sin duplicados
    """

    # Ancho fijo para cada columna (250-290px)
    COLUMN_WIDTH = 270
    COLUMN_MIN_WIDTH = 250
    COLUMN_MAX_WIDTH = 290

    def __init__(
        self, parent, database: ImageDatabase, on_prepare_batch: Callable | None = None,
        on_open_print: Callable | None = None, on_open_finish: Callable | None = None,
        on_resolve_block: Callable | None = None,
    ):
        super().__init__(parent)

        self.database = database
        self.on_prepare_batch = on_prepare_batch
        self.on_open_print = on_open_print
        self.on_open_finish = on_open_finish
        self.on_resolve_block = on_resolve_block
        self.stage_service = StageService(database.connection)
        self.feedback_service = ProductionFeedbackService(database)
        self.selected_order_id: int | None = None

        # Variables de filtros
        self.filter_urgent = tk.BooleanVar(value=False)
        self.filter_overdue = tk.BooleanVar(value=False)
        self.filter_delivery_today = tk.BooleanVar(value=False)
        self.filter_delivery_week = tk.BooleanVar(value=False)
        self.filter_show_completed = tk.BooleanVar(value=False)  # Pedidos terminados
        self.filter_active_only = tk.BooleanVar(value=True)      # Solo activos
        self.filter_client = tk.StringVar(value="")
        self.filter_material = tk.StringVar(value="")
        self.filter_product = tk.StringVar(value="")
        self.filter_order_number = tk.StringVar(value="")
        self.filter_order_status = tk.StringVar(value="Todas las etapas")

        # Estado de scroll horizontal
        self._scroll_position = 0
        self._scroll_position_file = Path(__file__).parents[3] / "ui_settings_production_scroll.json"
        self._load_scroll_position()

        # Columnas de producción fijas (6 etapas)
        self.production_columns = [
            "Pendiente",
            "En diseño",
            "Listo para imprimir",
            "En proceso",
            "Listo",
            "Entregado",
        ]

        self.configure(background=COLORS.background)

        # Construir UI
        self._build_header()
        self._build_operational_summary()
        self._build_main_layout()

        # Cargar datos iniciales
        self.refresh()

    def _load_scroll_position(self):
        """Carga la posición de scroll guardada."""
        try:
            if self._scroll_position_file.exists():
                data = json.loads(self._scroll_position_file.read_text(encoding="utf-8"))
                self._scroll_position = data.get("scroll_x", 0)
        except Exception:
            self._scroll_position = 0

    def _save_scroll_position(self):
        """Guarda la posición de scroll actual."""
        try:
            data = {"scroll_x": self._scroll_position}
            self._scroll_position_file.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass

    def _build_header(self):
        """Construye el header con título y controles."""
        header_frame = tk.Frame(self, background=COLORS.background)
        header_frame.pack(fill="x", padx=20, pady=(15, 10))

        # Título
        title_frame = tk.Frame(header_frame, background=COLORS.background)
        title_frame.pack(side="left")

        tk.Label(
            title_frame,
            text="Tablero de Producción",
            background=COLORS.background,
            foreground=COLORS.text,
            font=(IDENTITY_FONT, 18, "bold"),
        ).pack(side="left")

        # Controles
        controls_frame = tk.Frame(header_frame, background=COLORS.background)
        controls_frame.pack(side="right")

        # Botón de refresh
        refresh_btn = tk.Button(
            controls_frame,
            text="↻ Actualizar",
            command=self.refresh,
            background=COLORS.panel,
            foreground=COLORS.text,
            activebackground=COLORS.panel_elevated,
            activeforeground=COLORS.text,
            font=(UI_FONT, 10),
            padx=14,
            pady=8,
            cursor="hand2",
            relief="flat",
            borderwidth=1,
        )
        refresh_btn.pack(side="right", padx=(10, 0))
        batch_btn = tk.Button(
            controls_frame, text="Preparar tanda", command=self._prepare_batch,
            background=COLORS.wine_active, foreground="white",
            activebackground=COLORS.wine_dark, activeforeground="white",
            font=(UI_FONT, 10, "bold"), padx=14, pady=8, cursor="hand2", relief="flat",
        )
        batch_btn.pack(side="right")

    def _prepare_batch(self):
        if self.on_prepare_batch:
            self.on_prepare_batch()

    def _build_operational_summary(self):
        """Amplía el tablero actual; no crea una vista paralela."""
        self.operational_summary = tk.Frame(self, background=COLORS.background)
        self.operational_summary.pack(fill="x", padx=20, pady=(0, 8))

    @staticmethod
    def _quantity_text(quantities: dict) -> str:
        parts = []
        units = int(quantities.get("units") or 0)
        sheets = int(quantities.get("sheets") or 0)
        if units:
            parts.append(f"{units} unidad{'es' if units != 1 else ''}")
        if sheets:
            parts.append(f"{sheets} hoja{'s' if sheets != 1 else ''}")
        return " · ".join(parts) or "0"

    def _refresh_operational_summary(self):
        for widget in self.operational_summary.winfo_children():
            widget.destroy()
        summary = self.feedback_service.summary()
        blocked = summary["blocked"]["items"]
        cards = (
            ("DISPONIBLES PARA PREPARAR", summary["available"], "Preparar", self._prepare_batch),
            ("PLANCHAS PENDIENTES DE IMPRESIÓN", summary["prepared"], "Imprimir", self.on_open_print),
            ("IMPRESAS PENDIENTES DE TERMINACIÓN", summary["printed"], "Terminar", self.on_open_finish),
            ("TRABAJOS BLOQUEADOS", summary["blocked"], "Resolver bloqueo",
             (lambda: self.on_resolve_block(blocked[0]["order_id"])) if blocked and self.on_resolve_block else None),
        )
        for column, (title, data, action_label, action) in enumerate(cards):
            card = tk.Frame(self.operational_summary, background=COLORS.panel,
                            highlightthickness=1, highlightbackground=COLORS.border)
            card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 4, 0))
            self.operational_summary.columnconfigure(column, weight=1, uniform="operational")
            tk.Label(card, text=title, background=COLORS.panel, foreground=COLORS.wine_active,
                     font=(IDENTITY_FONT, 9, "bold"), anchor="w").pack(fill="x", padx=10, pady=(9, 2))
            count_label = f"{data['work_count']} trabajo{'s' if data['work_count'] != 1 else ''}"
            if title in {"PLANCHAS PENDIENTES DE IMPRESIÓN", "IMPRESAS PENDIENTES DE TERMINACIÓN"}:
                count_label = f"{data['work_count']} plancha{'s' if data['work_count'] != 1 else ''}"
            tk.Label(card, text=f"{count_label} · {self._quantity_text(data['quantities'])}",
                     background=COLORS.panel, foreground=COLORS.text,
                     font=(UI_FONT, 10, "bold"), anchor="w").pack(fill="x", padx=10)
            details = []
            for item in data["items"][:2]:
                prefix = "⚠ " if int(item.get("urgency") or 0) else ""
                delivery = item.get("delivery_date") or "sin fecha"
                label = item.get("product") or item.get("name") or "Trabajo"
                if item.get("reason"):
                    label += f": {item['reason']}"
                details.append(f"{prefix}{label} · {delivery}")
            tk.Label(card, text="\n".join(details) or "Sin pendientes", background=COLORS.panel,
                     foreground=COLORS.muted, font=(UI_FONT, 8), justify="left", anchor="nw",
                     wraplength=235, height=2).pack(fill="x", padx=10, pady=(4, 5))
            button = tk.Button(card, text=action_label, command=action, state="normal" if action else "disabled",
                               background=COLORS.panel_elevated, foreground=COLORS.text,
                               activebackground=COLORS.wine_active, activeforeground="white",
                               relief="flat", cursor="hand2", font=(UI_FONT, 9))
            button.pack(anchor="w", padx=10, pady=(0, 9))

    def _build_main_layout(self):
        """Construye el layout principal: tablero (izquierda) + filtros (derecha)."""
        main_container = tk.Frame(self, background=COLORS.background)
        main_container.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # --- Panel izquierdo: Tablero con scroll horizontal ---
        self._build_board_panel(main_container)

        # --- Panel derecho: Filtros de Producción ---
        self._build_filters_panel(main_container)

    def _build_board_panel(self, parent):
        """Construye el panel del tablero con scroll horizontal."""
        # Frame contenedor del tablero (ocupa el espacio disponible menos el panel derecho)
        board_container = tk.Frame(parent, background=COLORS.background)
        board_container.pack(side="left", fill="both", expand=True)

        # Canvas para scroll horizontal
        self.board_canvas = tk.Canvas(
            board_container,
            background=COLORS.background,
            highlightthickness=0,
        )
        self.board_canvas.pack(side="top", fill="both", expand=True)

        # Scrollbar horizontal
        self.h_scrollbar = tk.Scrollbar(
            board_container,
            orient="horizontal",
            command=self.board_canvas.xview,
            background=COLORS.panel_elevated,
            troughcolor=COLORS.background_secondary,
            activebackground=COLORS.wine_active,
        )
        self.h_scrollbar.pack(side="bottom", fill="x")

        self.board_canvas.configure(xscrollcommand=self.h_scrollbar.set)

        # Frame interno que contiene las columnas
        self.board_frame = tk.Frame(self.board_canvas, background=COLORS.background)
        self.board_window = self.board_canvas.create_window(
            (0, 0), window=self.board_frame, anchor="nw"
        )

        # Bindings para scroll y redimensionamiento
        self.board_frame.bind("<Configure>", self._on_board_frame_configure)
        self.board_canvas.bind("<Configure>", self._on_canvas_configure)

        # Scroll con rueda del mouse (horizontal con Shift)
        self.board_canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.board_canvas.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)
        # Linux
        self.board_canvas.bind("<Button-4>", lambda e: self._on_mousewheel(e))
        self.board_canvas.bind("<Button-5>", lambda e: self._on_mousewheel(e))
        self.board_canvas.bind("<Shift-Button-4>", lambda e: self._on_shift_mousewheel(e))
        self.board_canvas.bind("<Shift-Button-5>", lambda e: self._on_shift_mousewheel(e))

        # Focus para recibir eventos de rueda
        self.board_canvas.bind("<Enter>", lambda e: self.board_canvas.focus_set())

    def _build_filters_panel(self, parent):
        """Construye el panel derecho de filtros de producción."""
        filters_frame = tk.Frame(
            parent,
            width=320,
            background=COLORS.panel,
            highlightthickness=1,
            highlightbackground=COLORS.border,
        )
        filters_frame.pack(side="right", fill="y", padx=(10, 0))
        filters_frame.pack_propagate(False)

        # Header del panel
        header = tk.Frame(filters_frame, background=COLORS.panel)
        header.pack(fill="x", padx=14, pady=(14, 10))

        tk.Label(
            header,
            text="FILTROS DE PRODUCCIÓN",
            background=COLORS.panel,
            foreground=COLORS.wine_active,
            font=(IDENTITY_FONT, 11, "bold"),
        ).pack(anchor="w")

        tk.Label(
            header,
            text="Filtros aplicados al tablero actual",
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 9),
        ).pack(anchor="w", pady=(2, 0))

        # Canvas con scroll para filtros (puede crecer)
        filters_canvas = tk.Canvas(
            filters_frame,
            background=COLORS.panel,
            highlightthickness=0,
            width=300,
        )
        filters_canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 10))

        filters_scrollbar = tk.Scrollbar(
            filters_frame,
            orient="vertical",
            command=filters_canvas.yview,
            background=COLORS.panel_elevated,
            troughcolor=COLORS.background_secondary,
        )
        filters_scrollbar.pack(side="right", fill="y", padx=(0, 10), pady=(0, 10))

        filters_canvas.configure(yscrollcommand=filters_scrollbar.set)

        # Frame interno para los filtros
        self.filters_inner = tk.Frame(filters_canvas, background=COLORS.panel)
        self.filters_window = filters_canvas.create_window(
            (0, 0), window=self.filters_inner, anchor="nw"
        )

        self.filters_inner.bind(
            "<Configure>",
            lambda e: filters_canvas.configure(scrollregion=filters_canvas.bbox("all"))
        )
        filters_canvas.bind(
            "<Configure>",
            lambda e: filters_canvas.itemconfig(self.filters_window, width=e.width)
        )

        # Scroll en filtros
        self.filters_inner.bind("<MouseWheel>", lambda e: self._scroll_filters(filters_canvas, e))
        filters_canvas.bind("<MouseWheel>", lambda e: self._scroll_filters(filters_canvas, e))

        # --- Construir secciones de filtros ---
        self._build_search_filters(self.filters_inner)
        self._build_quick_filters(self.filters_inner)
        self._build_stage_filter(self.filters_inner)
        self._build_material_filter(self.filters_inner)
        self._build_order_status_filter(self.filters_inner)
        self._build_clear_button(self.filters_inner)

    def _scroll_filters(self, canvas, event):
        """Scroll vertical para el panel de filtros."""
        if event.delta:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        elif event.num == 4:
            canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            canvas.yview_scroll(1, "units")

    def _build_search_filters(self, parent):
        """Filtros de búsqueda: número de pedido, cliente, producto/plancha."""
        section = tk.LabelFrame(
            parent,
            text="BUSCAR",
            background=COLORS.panel,
            foreground=COLORS.wine_active,
            font=(IDENTITY_FONT, 9, "bold"),
            borderwidth=1,
            relief="solid",
            highlightbackground=COLORS.border,
            highlightcolor=COLORS.wine_active,
        )
        section.pack(fill="x", pady=(0, 10), padx=4)

        inner = tk.Frame(section, background=COLORS.panel)
        inner.pack(fill="x", padx=10, pady=10)

        # Número de pedido
        tk.Label(inner, text="Número de pedido:", background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 9)).pack(anchor="w", pady=(0, 2))
        entry_order = tk.Entry(inner, textvariable=self.filter_order_number, font=(UI_FONT, 10))
        entry_order.pack(fill="x", pady=(0, 8))
        entry_order.bind("<KeyRelease>", lambda e: self.refresh())

        # Cliente
        tk.Label(inner, text="Cliente:", background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 9)).pack(anchor="w", pady=(0, 2))
        entry_client = tk.Entry(inner, textvariable=self.filter_client, font=(UI_FONT, 10))
        entry_client.pack(fill="x", pady=(0, 8))
        entry_client.bind("<KeyRelease>", lambda e: self.refresh())

        # Producto o plancha
        tk.Label(inner, text="Producto o plancha:", background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 9)).pack(anchor="w", pady=(0, 2))
        entry_product = tk.Entry(inner, textvariable=self.filter_product, font=(UI_FONT, 10))
        entry_product.pack(fill="x", pady=(0, 8))
        entry_product.bind("<KeyRelease>", lambda e: self.refresh())

    def _build_quick_filters(self, parent):
        """Filtros rápidos con checkboxes."""
        section = tk.LabelFrame(
            parent,
            text="FILTROS RÁPIDOS",
            background=COLORS.panel,
            foreground=COLORS.wine_active,
            font=(IDENTITY_FONT, 9, "bold"),
            borderwidth=1,
            relief="solid",
            highlightbackground=COLORS.border,
            highlightcolor=COLORS.wine_active,
        )
        section.pack(fill="x", pady=(0, 10), padx=4)

        inner = tk.Frame(section, background=COLORS.panel)
        inner.pack(fill="x", padx=10, pady=10)

        checkboxes = [
            ("Solo urgentes", self.filter_urgent),
            ("Solo vencidos", self.filter_overdue),
            ("Entrega hoy", self.filter_delivery_today),
            ("Entrega esta semana", self.filter_delivery_week),
            ("Solo activos", self.filter_active_only),
            ("Pedidos terminados", self.filter_show_completed),
        ]

        for text, var in checkboxes:
            cb = tk.Checkbutton(
                inner,
                text=text,
                variable=var,
                background=COLORS.panel,
                foreground=COLORS.text,
                activebackground=COLORS.panel,
                activeforeground=COLORS.text,
                selectcolor=COLORS.field,
                font=(UI_FONT, 10),
                command=self.refresh,
                anchor="w",
            )
            cb.pack(fill="x", pady=2)

        # Mutex: "Solo activos" y "Pedidos terminados" no pueden estar ambos activos
        self.filter_active_only.trace_add("write", self._on_active_only_change)
        self.filter_show_completed.trace_add("write", self._on_show_completed_change)

    def _on_active_only_change(self, *_):
        """Cuando se marca 'Solo activos', desmarcar 'Pedidos terminados'."""
        if self.filter_active_only.get():
            if self.filter_show_completed.get():
                self.filter_show_completed.set(False)
        self._schedule_refresh()

    def _on_show_completed_change(self, *_):
        """Cuando se marca 'Pedidos terminados', desmarcar 'Solo activos'."""
        if self.filter_show_completed.get():
            if self.filter_active_only.get():
                self.filter_active_only.set(False)
        self._schedule_refresh()

    def _build_stage_filter(self, parent):
        """Filtro por etapa (columna del tablero)."""
        section = tk.LabelFrame(
            parent,
            text="ETAPA",
            background=COLORS.panel,
            foreground=COLORS.wine_active,
            font=(IDENTITY_FONT, 9, "bold"),
            borderwidth=1,
            relief="solid",
            highlightbackground=COLORS.border,
            highlightcolor=COLORS.wine_active,
        )
        section.pack(fill="x", pady=(0, 10), padx=4)

        inner = tk.Frame(section, background=COLORS.panel)
        inner.pack(fill="x", padx=10, pady=10)

        stages = ["Todas las etapas"] + self.production_columns
        combo = tk.ttk.Combobox(
            inner,
            textvariable=self.filter_order_status,
            values=stages,
            state="readonly",
            font=(UI_FONT, 10),
        )
        combo.pack(fill="x")
        combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())

    def _build_material_filter(self, parent):
        """Filtro por material."""
        section = tk.LabelFrame(
            parent,
            text="MATERIAL",
            background=COLORS.panel,
            foreground=COLORS.wine_active,
            font=(IDENTITY_FONT, 9, "bold"),
            borderwidth=1,
            relief="solid",
            highlightbackground=COLORS.border,
            highlightcolor=COLORS.wine_active,
        )
        section.pack(fill="x", pady=(0, 10), padx=4)

        inner = tk.Frame(section, background=COLORS.panel)
        inner.pack(fill="x", padx=10, pady=10)

        entry = tk.Entry(inner, textvariable=self.filter_material, font=(UI_FONT, 10))
        entry.pack(fill="x")
        entry.bind("<KeyRelease>", lambda e: self.refresh())

    def _build_order_status_filter(self, parent):
        """Filtro por estado del pedido (desde BD)."""
        section = tk.LabelFrame(
            parent,
            text="ESTADO DEL PEDIDO",
            background=COLORS.panel,
            foreground=COLORS.wine_active,
            font=(IDENTITY_FONT, 9, "bold"),
            borderwidth=1,
            relief="solid",
            highlightbackground=COLORS.border,
            highlightcolor=COLORS.wine_active,
        )
        section.pack(fill="x", pady=(0, 10), padx=4)

        inner = tk.Frame(section, background=COLORS.panel)
        inner.pack(fill="x", padx=10, pady=10)

        # Obtener estados únicos de pedidos activos
        try:
            statuses = ["Todos los estados"]
            rows = self.database.connection.execute(
                """SELECT DISTINCT status FROM orders
                   WHERE COALESCE(is_archived, 0) = 0
                   ORDER BY status"""
            ).fetchall()
            statuses.extend([row["status"] for row in rows])

            combo = tk.ttk.Combobox(
                inner,
                textvariable=tk.StringVar(value="Todos los estados"),
                values=statuses,
                state="readonly",
                font=(UI_FONT, 10),
            )
            combo.pack(fill="x")
            combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())
            self._order_status_combo = combo
        except Exception:
            pass

    def _build_clear_button(self, parent):
        """Botón limpiar filtros."""
        btn_frame = tk.Frame(parent, background=COLORS.panel)
        btn_frame.pack(fill="x", pady=(10, 0), padx=10)

        tk.Button(
            btn_frame,
            text="Limpiar filtros",
            command=self._clear_all_filters,
            background=COLORS.panel_elevated,
            foreground=COLORS.text,
            activebackground=COLORS.border_strong,
            activeforeground=COLORS.text,
            font=(UI_FONT, 10, "bold"),
            padx=16,
            pady=10,
            cursor="hand2",
            relief="flat",
            borderwidth=1,
        ).pack(fill="x")

    def _clear_all_filters(self):
        """Limpia todos los filtros y refresca."""
        self.filter_urgent.set(False)
        self.filter_overdue.set(False)
        self.filter_delivery_today.set(False)
        self.filter_delivery_week.set(False)
        self.filter_show_completed.set(False)
        self.filter_active_only.set(True)
        self.filter_client.set("")
        self.filter_material.set("")
        self.filter_product.set("")
        self.filter_order_number.set("")
        self.filter_order_status.set("Todas las etapas")
        if hasattr(self, '_order_status_combo'):
            self._order_status_combo.set("Todos los estados")
        self.refresh()

    def _get_active_filters(self) -> dict:
        """Retorna los filtros activos actuales."""
        filters = {}

        if self.filter_urgent.get():
            filters["urgent_only"] = True

        if self.filter_overdue.get():
            filters["overdue_only"] = True

        if self.filter_delivery_today.get():
            today = datetime.now().strftime("%Y-%m-%d")
            filters["delivery_date_from"] = today
            filters["delivery_date_to"] = today

        if self.filter_delivery_week.get():
            today = datetime.now()
            week_end = today.replace(day=today.day + 7)
            filters["delivery_date_from"] = today.strftime("%Y-%m-%d")
            filters["delivery_date_to"] = week_end.strftime("%Y-%m-%d")

        # CONFLICT RESOLUTION: "Solo activos" y "Pedidos terminados" son mutuamente excluyentes
        # Si ambos están marcados, priorizar "Pedidos terminados" y desmarcar "Solo activos"
        show_completed = bool(self.filter_show_completed.get())
        active_only = bool(self.filter_active_only.get())

        if show_completed and active_only:
            self.filter_active_only.set(False)
            active_only = False

        if active_only:
            filters["exclude_completed"] = True

        if show_completed:
            filters["include_completed"] = True

        if self.filter_client.get().strip():
            filters["client"] = self.filter_client.get().strip()

        if self.filter_material.get().strip():
            filters["material"] = self.filter_material.get().strip()

        if self.filter_product.get().strip():
            filters["product"] = self.filter_product.get().strip()

        if self.filter_order_number.get().strip():
            filters["order_number"] = self.filter_order_number.get().strip()

        if self.filter_order_status.get() != "Todas las etapas":
            filters["production_column"] = self.filter_order_status.get()

        return filters

    # --- Scroll handling ---

    def _on_board_frame_configure(self, event=None):
        """Actualiza scrollregion cuando el frame interno cambia de tamaño."""
        self.board_canvas.configure(scrollregion=self.board_canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        """Ajusta el ancho del frame interno al canvas."""
        # Mantener altura del frame interno = altura del canvas
        self.board_canvas.itemconfig(self.board_window, height=event.height)

    def _on_mousewheel(self, event):
        """Scroll vertical (para contenido largo en columnas)."""
        if event.delta:
            self.board_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        elif event.num == 4:
            self.board_canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.board_canvas.yview_scroll(1, "units")

    def _on_shift_mousewheel(self, event):
        """Scroll horizontal con Shift + rueda."""
        if event.delta:
            self.board_canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
        elif event.num == 4:
            self.board_canvas.xview_scroll(-1, "units")
        elif event.num == 5:
            self.board_canvas.xview_scroll(1, "units")
        self._save_scroll_position()

    def _save_scroll_position(self):
        """Guarda la posición actual de scroll horizontal."""
        self._scroll_position = self.board_canvas.xview()[0]
        self._save_scroll_position_to_file()

    def _save_scroll_position_to_file(self):
        """Persiste scroll position a archivo."""
        try:
            data = {"scroll_x": self._scroll_position}
            self._scroll_position_file.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass

    def _restore_scroll_position(self):
        """Restaura la posición de scroll guardada."""
        if self._scroll_position > 0:
            self.board_canvas.xview_moveto(self._scroll_position)

    # --- Construcción de columnas ---

    def _schedule_refresh(self):
        """Programa una actualización diferida (evita refrescados múltiples)."""
        if hasattr(self, '_refresh_pending') and self._refresh_pending:
            return
        self._refresh_pending = True
        self.after(100, self._do_refresh_and_clear_flag)

    def _do_refresh_and_clear_flag(self):
        """Realiza la actualización diferida y limpia la bandera."""
        if hasattr(self, '_refresh_pending'):
            self._refresh_pending = False
        self.refresh()

    def refresh(self):
        """Recarga los datos y reconstruye el tablero conservando filtros, scroll y selección."""
        # Guardar selección actual
        prev_selected = self.selected_order_id
        # Guardar posición de scroll
        self._save_scroll_position()

        self._refresh_operational_summary()

        # Limpiar columnas existentes
        for widget in self.board_frame.winfo_children():
            widget.destroy()

        # Crear columna por cada etapa de producción
        columns_created = 0
        for column_name in self.production_columns:
            self._build_production_column(column_name)
            columns_created += 1

        # Verificar y generar notificaciones para urgentes/vencidos
        self._check_and_notify_urgent_overdue()

        # Restaurar posición de scroll
        self.after_idle(self._restore_scroll_position)

        # Restaurar selección si el pedido sigue existiendo
        if prev_selected:
            self._restore_selection(prev_selected)

        # Mostrar notificación
        Toast(self, "Tablero actualizado", tone="success", duration=1500)

        # Mensaje si no hay trabajos
        if columns_created == 0:
            empty_label = tk.Label(
                self.board_frame,
                text="No hay trabajos de producción para mostrar",
                background=COLORS.background,
                foreground=COLORS.muted,
                font=(UI_FONT, 12),
            )
            empty_label.pack(expand=True)

    def _restore_selection(self, order_id: int):
        """Intenta restaurar la selección visual del pedido."""
        # Buscar el tile en las columnas y resaltarlo
        for column_frame in self.board_frame.winfo_children():
            for widget in column_frame.winfo_children():
                if isinstance(widget, ProductionOrderTile) and widget.order_id == order_id:
                    widget.set_highlight(True)
                    self.selected_order_id = order_id
                    return

    def _build_production_column(self, column_name: str) -> int:
        """Construye una columna de producción con sus pedidos.

        Retorna la cantidad de tiles creados.
        """
        # Columna contenedor con ancho fijo
        column_frame = tk.Frame(
            self.board_frame,
            background=COLORS.background_secondary,
            highlightthickness=1,
            highlightbackground=COLORS.border,
            width=self.COLUMN_WIDTH,
        )
        column_frame.pack(side="left", fill="both", expand=False, padx=8, pady=8, ipadx=2, ipady=2)
        column_frame.pack_propagate(False)  # Mantener ancho fijo

        # Header de la columna
        self._build_production_column_header(column_frame, column_name)

        # Separador
        separator = tk.Frame(
            column_frame,
            background=COLORS.border,
            height=1,
        )
        separator.pack(fill="x", padx=10, pady=(0, 8))

        # Frame para los tiles (con scroll vertical interno)
        tiles_frame = tk.Frame(column_frame, background=COLORS.background_secondary)
        tiles_frame.pack(fill="both", expand=True, padx=10, pady=8)

        # Obtener pedidos de esta columna (aplicando filtros activos)
        tiles_created = 0
        try:
            filters = self._get_active_filters()
            orders = self.stage_service.get_orders_by_production_column(column_name, filters)
        except Exception as e:
            import traceback
            traceback.print_exc()
            error_label = tk.Label(
                tiles_frame,
                text=f"Error: {e}",
                background=COLORS.background_secondary,
                foreground=COLORS.error,
                font=(UI_FONT, 9),
            )
            error_label.pack(padx=10, pady=10)
            return 0

        # Crear tiles
        if not orders:
            empty_label = tk.Label(
                tiles_frame,
                text="Sin pedidos",
                background=COLORS.background_secondary,
                foreground=COLORS.muted,
                font=(UI_FONT, 10),
            )
            empty_label.pack(padx=10, pady=20)
        else:
            for order_summary in orders:
                tile = ProductionOrderTile(
                    tiles_frame,
                    order_id=order_summary.order_id,
                    client_name=order_summary.client_name,
                    material=order_summary.material,
                    quantity=order_summary.quantity,
                    jobs_count=order_summary.jobs_count,
                    age_days=order_summary.age_days,
                    priority=order_summary.priority,
                    is_urgent=order_summary.is_urgent,
                    delivery_date=order_summary.delivery_date,
                    on_click=self._on_order_click,
                    on_double_click=self._on_order_double_click,
                    on_context_menu=self._on_order_context_menu,
                )
                tile.pack(fill="x", padx=10, pady=(0, 8))
                tiles_created += 1

        return tiles_created

    def _build_production_column_header(self, parent, column_name: str):
        """Construye el header de una columna de producción con métricas."""
        header_frame = tk.Frame(parent, background=COLORS.background_secondary)
        header_frame.pack(fill="x", padx=10, pady=(10, 8))

        # Título de la columna
        title_label = tk.Label(
            header_frame,
            text=column_name,
            background=COLORS.background_secondary,
            foreground=COLORS.wine_active,
            font=(UI_FONT, 11, "bold"),
            anchor="w",
        )
        title_label.pack(fill="x")

        # Calcular métricas para esta columna
        try:
            filters = self._get_active_filters()
            orders = self.stage_service.get_orders_by_production_column(column_name, filters)

            if orders:
                total_orders = len(orders)
                total_jobs = sum(order.jobs_count for order in orders)
                urgent_count = sum(1 for order in orders if order.is_urgent)

                # Encontrar el más antiguo
                oldest_order = max(orders, key=lambda o: o.age_days)
                oldest_days = oldest_order.age_days

                # Mostrar métricas
                metrics_frame = tk.Frame(header_frame, background=COLORS.background_secondary)
                metrics_frame.pack(fill="x", pady=(6, 0))

                count_text = f"{total_orders} pedido{'s' if total_orders != 1 else ''}"
                if total_jobs > 0:
                    count_text += f" · {total_jobs} trabajo{'s' if total_jobs != 1 else ''}"

                count_label = tk.Label(
                    metrics_frame,
                    text=count_text,
                    background=COLORS.background_secondary,
                    foreground=COLORS.text,
                    font=(UI_FONT, 9),
                    anchor="w",
                )
                count_label.pack(fill="x")

                # Urgentes (si hay)
                if urgent_count > 0:
                    urgent_label = tk.Label(
                        metrics_frame,
                        text=f"⚠️ {urgent_count} urgente{'s' if urgent_count != 1 else ''}",
                        background=COLORS.background_secondary,
                        foreground=COLORS.warning,
                        font=(UI_FONT, 9, "bold"),
                        anchor="w",
                    )
                    urgent_label.pack(fill="x", pady=(2, 0))

                # Antigüedad del más antiguo
                if oldest_days > 0:
                    age_text = f"Más antiguo: {int(oldest_days)} día{'s' if oldest_days != 1 else ''}"

                    age_color = COLORS.muted
                    if oldest_days > 14:
                        age_color = COLORS.error
                    elif oldest_days > 7:
                        age_color = COLORS.warning

                    age_label = tk.Label(
                        metrics_frame,
                        text=age_text,
                        background=COLORS.background_secondary,
                        foreground=age_color,
                        font=(UI_FONT, 9),
                        anchor="w",
                    )
                    age_label.pack(fill="x", pady=(2, 0))
        except Exception as e:
            import traceback
            traceback.print_exc()

    # --- Event handlers ---

    def _on_order_click(self, order_id: int):
        """Maneja el click en un tile de pedido."""
        # Quitar highlight anterior
        for column_frame in self.board_frame.winfo_children():
            for widget in column_frame.winfo_children():
                if isinstance(widget, ProductionOrderTile):
                    widget.set_highlight(False)

        # Aplicar highlight al seleccionado
        for column_frame in self.board_frame.winfo_children():
            for widget in column_frame.winfo_children():
                if isinstance(widget, ProductionOrderTile) and widget.order_id == order_id:
                    widget.set_highlight(True)
                    break

        self.selected_order_id = order_id
        self.event_generate("<<OrderSelected>>", when="tail")

    def _on_order_double_click(self, order_id: int):
        """Maneja el doble click para abrir el pedido original."""
        self.selected_order_id = order_id
        self.event_generate("<<OrderOpenDetail>>", when="tail")

    def _on_order_context_menu(self, order_id: int, event: tk.Event):
        """Muestra menú contextual en la tarjeta."""
        menu = tk.Menu(self, tearoff=0)
        menu.configure(
            background=COLORS.panel_elevated,
            foreground=COLORS.text,
            activebackground=COLORS.wine_active,
            activeforeground=COLORS.text,
            borderwidth=1,
            relief="flat",
        )

        menu.add_command(
            label=f"Abrir pedido #{order_id}",
            command=lambda: self._open_order_workspace(order_id),
        )
        menu.add_separator()
        menu.add_command(
            label="Cambiar etapa...",
            command=lambda: self._change_order_stage(order_id),
        )
        menu.add_command(
            label="Entregar y terminar",
            command=lambda: self._deliver_and_complete(order_id),
        )
        menu.add_separator()
        menu.add_command(
            label="Marcar como urgente",
            command=lambda: self._mark_as_urgent(order_id, True),
        )
        menu.add_command(
            label="Quitar urgente",
            command=lambda: self._mark_as_urgent(order_id, False),
        )
        menu.add_command(
            label="Ver historial",
            command=lambda: self._view_order_history(order_id),
        )
        menu.add_separator()
        menu.add_command(
            label="Abrir plancha (si existe)",
            command=lambda: self._open_plancha(order_id),
        )

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _open_order_workspace(self, order_id: int):
        """Abre el workspace del pedido original (no una copia)."""
        # Seleccionar el pedido primero
        self.selected_order_id = order_id
        # Emitir evento para que main_window lo maneje
        self.event_generate("<<OpenOrderWorkspace>>", when="tail")

    def _change_order_stage(self, order_id: int):
        """Abre diálogo para cambiar la etapa del pedido (via job)."""
        # Obtener los jobs del pedido
        try:
            jobs = self.database.connection.execute(
                """SELECT id, title, material, size, quantity, status
                   FROM order_jobs WHERE order_id = ? ORDER BY sort_order, id""",
                (order_id,)
            ).fetchall()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar los trabajos:\n{e}", parent=self)
            return

        if not jobs:
            Toast(self, "El pedido no tiene trabajos", tone="warning")
            return

        # Si hay un solo job, usarlo directamente
        if len(jobs) == 1:
            self._show_stage_change_dialog(order_id, dict(jobs[0]))
        else:
            # Mostrar selector de job
            self._show_job_selector_for_stage_change(order_id, [dict(j) for j in jobs])

    def _show_job_selector_for_stage_change(self, order_id: int, jobs: list[dict]):
        """Muestra un diálogo para seleccionar qué job cambiar de etapa."""
        dialog = tk.Toplevel(self)
        dialog.title(f"Cambiar etapa - Pedido #{order_id}")
        dialog.geometry("500x400")
        dialog.configure(background=COLORS.background)
        dialog.transient(self)
        dialog.grab_set()

        tk.Label(
            dialog,
            text=f"Pedido #{order_id} - Seleccionar trabajo",
            background=COLORS.background,
            foreground=COLORS.text,
            font=(IDENTITY_FONT, 12, "bold"),
        ).pack(anchor="w", padx=20, pady=(20, 10))

        tk.Label(
            dialog,
            text="El pedido tiene múltiples trabajos. Elija cuál cambiar:",
            background=COLORS.background,
            foreground=COLORS.muted,
            font=(UI_FONT, 10),
        ).pack(anchor="w", padx=20, pady=(0, 10))

        # Lista de jobs
        list_frame = tk.Frame(dialog, background=COLORS.background)
        list_frame.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        selected_job = tk.StringVar()

        for job in jobs:
            job_text = f"Job #{job['id']} - {job['title']} - {job['material']} - {job['status']}"
            rb = tk.Radiobutton(
                list_frame,
                text=job_text,
                variable=selected_job,
                value=str(job['id']),
                background=COLORS.background,
                foreground=COLORS.text,
                activebackground=COLORS.background,
                activeforeground=COLORS.text,
                font=(UI_FONT, 10),
                anchor="w",
            )
            rb.pack(fill="x", pady=2)

        if jobs:
            selected_job.set(str(jobs[0]['id']))

        def on_confirm():
            job_id = int(selected_job.get())
            job = next(j for j in jobs if j['id'] == job_id)
            dialog.destroy()
            self._show_stage_change_dialog(order_id, job)

        btn_frame = tk.Frame(dialog, background=COLORS.background)
        btn_frame.pack(fill="x", padx=20, pady=(0, 20))

        tk.Button(
            btn_frame,
            text="Cancelar",
            command=dialog.destroy,
            background=COLORS.panel,
            foreground=COLORS.text,
            font=(UI_FONT, 10),
            padx=20,
            pady=8,
        ).pack(side="right", padx=(10, 0))

        tk.Button(
            btn_frame,
            text="Continuar",
            command=on_confirm,
            background=COLORS.wine_active,
            foreground=COLORS.text,
            font=(UI_FONT, 10, "bold"),
            padx=20,
            pady=8,
        ).pack(side="right")

    def _show_stage_change_dialog(self, order_id: int, job: dict):
        """Muestra diálogo para cambiar la etapa de un job específico."""
        from app.workflow.timeline import get_workflow

        # Obtener workflow del job
        workflow = get_workflow(job)
        stages = [stage for stage, _ in workflow]

        # Etapa actual normalizada
        from app.services.production_stage_service import LEGACY_STAGE_MAPPING
        current_stage = job.get("status", "Recibido")
        if current_stage in LEGACY_STAGE_MAPPING:
            current_stage = LEGACY_STAGE_MAPPING[current_stage]

        dialog = tk.Toplevel(self)
        dialog.title(f"Cambiar etapa - Job #{job['id']}")
        dialog.geometry("450x550")
        dialog.configure(background=COLORS.background)
        dialog.transient(self)
        dialog.grab_set()

        # Centrar
        dialog.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - (dialog.winfo_width() // 2)
        y = self.winfo_y() + (self.winfo_height() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")

        tk.Label(
            dialog,
            text=f"Job #{job['id']} - {job['title']}",
            background=COLORS.background,
            foreground=COLORS.text,
            font=(IDENTITY_FONT, 12, "bold"),
        ).pack(anchor="w", padx=20, pady=(20, 5))

        tk.Label(
            dialog,
            text=f"{job['material']} · {job.get('size', '')} · {job.get('quantity', 1)} un.",
            background=COLORS.background,
            foreground=COLORS.muted,
            font=(UI_FONT, 10),
        ).pack(anchor="w", padx=20, pady=(0, 10))

        # Etapa actual
        current_frame = tk.Frame(dialog, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        current_frame.pack(fill="x", padx=20, pady=(0, 15))

        tk.Label(
            current_frame,
            text="Etapa actual:",
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 9),
        ).pack(anchor="w", padx=15, pady=(10, 2))

        tk.Label(
            current_frame,
            text=current_stage,
            background=COLORS.panel,
            foreground=COLORS.wine_active,
            font=(UI_FONT, 12, "bold"),
        ).pack(anchor="w", padx=15, pady=(0, 10))

        # Selector de nueva etapa
        tk.Label(
            dialog,
            text="Nueva etapa:",
            background=COLORS.background,
            foreground=COLORS.text,
            font=(UI_FONT, 10, "bold"),
        ).pack(anchor="w", padx=20, pady=(0, 5))

        # Frame con scroll para etapas
        canvas = tk.Canvas(dialog, background=COLORS.background, highlightthickness=0)
        scrollbar = tk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
        stages_frame = tk.Frame(canvas, background=COLORS.background)

        stages_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=stages_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=(20, 0), pady=(0, 20))
        scrollbar.pack(side="right", fill="y", padx=(0, 20), pady=(0, 20))

        selected_stage = tk.StringVar(value=current_stage)

        for stage in stages:
            rb = tk.Radiobutton(
                stages_frame,
                text=stage,
                variable=selected_stage,
                value=stage,
                background=COLORS.background,
                foreground=COLORS.text,
                activebackground=COLORS.background,
                activeforeground=COLORS.text,
                selectcolor=COLORS.field,
                font=(UI_FONT, 10),
                anchor="w",
                indicatoron=0,
                width=35,
            )
            rb.pack(fill="x", pady=2)

            # Resaltar etapa actual
            if stage == current_stage:
                rb.configure(foreground=COLORS.wine_active, font=(UI_FONT, 10, "bold"))

        # Botones
        btn_frame = tk.Frame(dialog, background=COLORS.background)
        btn_frame.pack(fill="x", padx=20, pady=(0, 20))

        def on_confirm():
            new_stage = selected_stage.get()
            if new_stage == current_stage:
                Toast(self, "La etapa no ha cambiado", tone="info")
                dialog.destroy()
                return
            dialog.destroy()
            self._execute_stage_change(order_id, job['id'], new_stage)

        tk.Button(
            btn_frame,
            text="Cancelar",
            command=dialog.destroy,
            background=COLORS.panel,
            foreground=COLORS.text,
            font=(UI_FONT, 10),
            padx=20,
            pady=8,
        ).pack(side="right", padx=(10, 0))

        tk.Button(
            btn_frame,
            text="Cambiar etapa",
            command=on_confirm,
            background=COLORS.wine_active,
            foreground=COLORS.text,
            font=(UI_FONT, 10, "bold"),
            padx=20,
            pady=8,
        ).pack(side="right")

    def _execute_stage_change(self, order_id: int, job_id: int, new_stage: str):
        """Ejecuta el cambio de etapa usando ProductionStageService."""
        parent = self.winfo_toplevel()
        if not hasattr(parent, '_event_bus') or not hasattr(parent, 'database'):
            messagebox.showerror("Error", "Servicios no disponibles", parent=self)
            return

        try:
            from app.services.production_stage_service import ProductionStageService
            service = ProductionStageService(parent.database.connection, parent._event_bus)

            success, message, job_data = service.change_job_stage(
                job_id=job_id,
                new_stage=new_stage,
                device_id=1,  # Desktop
                device_name="Doccione Studio",
                operator_name="",
                source="desktop",
                notes=f"Cambio manual desde Tablero de Producción (Pedido #{order_id})"
            )

            if success:
                Toast(self, f"Etapa cambiada: {message}", tone="success")
                # El event bus ya notificará y refrescará el tablero
            else:
                messagebox.showerror("Error", f"No se pudo cambiar la etapa:\n{message}", parent=self)

        except Exception as e:
            import traceback
            traceback.print_exc()
            messagebox.showerror("Error", f"Error al cambiar etapa:\n{e}", parent=self)

    def _mark_as_urgent(self, order_id: int, urgent: bool):
        """Marca o desmarca un pedido como urgente."""
        try:
            priority = 4 if urgent else 0
            self.database.update_order_priority(order_id, priority)
            self.refresh()
            action = "marcado como urgente" if urgent else "quitado urgente"
            Toast(self, f"Pedido #{order_id} {action}", tone="success")
        except Exception as e:
            messagebox.showerror(
                "Error",
                f"Error al actualizar prioridad:\n{e}",
                parent=self,
            )

    def _view_order_history(self, order_id: int):
        """Muestra el historial del pedido."""
        parent = self.winfo_toplevel()
        if hasattr(parent, '_event_bus'):
            parent._event_bus.publish(
                event_type="production.view_history_requested",
                title="Ver historial",
                message=f"Pedido #{order_id}",
                priority="normal",
                entity_type="order",
                entity_id=order_id,
                payload={"order_id": order_id, "action": "view_history"},
            )
        Toast(self, "Historial solicitado", tone="info")

    def _open_plancha(self, order_id: int):
        """Abre la plancha asociada al pedido si existe."""
        parent = self.winfo_toplevel()
        if hasattr(parent, '_event_bus'):
            parent._event_bus.publish(
                event_type="production.open_plancha_requested",
                title="Abrir plancha",
                message=f"Pedido #{order_id}",
                priority="normal",
                entity_type="order",
                entity_id=order_id,
                payload={"order_id": order_id, "action": "open_plancha"},
            )
        Toast(self, "Abrir plancha solicitado", tone="info")

    def _deliver_and_complete(self, order_id: int):
        """Entrega todos los trabajos del pedido y lo marca como terminado."""

        confirmed = messagebox.askyesno(
            "Confirmar entrega",
            f"¿Confirmar la entrega y marcar el pedido #{order_id} como terminado?",
            parent=self,
        )
        if not confirmed:
            return

        try:
            from app.services.production_stage_service import ProductionStageService

            service = ProductionStageService(
                self.database.connection,
                self.event_bus,
            )

            success, message, order_data = service.finalize_order_delivery(
                order_id=order_id,
                device_id=1,
                device_name="Doccione Studio",
                operator_name="",
                source="desktop",
                notes=(
                    "Entrega confirmada desde Tablero de Producción "
                    f"(Pedido #{order_id})"
                ),
            )

            if not success:
                messagebox.showerror(
                    "Error",
                    message or f"No se pudo completar el pedido #{order_id}.",
                    parent=self,
                )
                return

            Toast(
                self,
                f"Pedido #{order_id} entregado y terminado",
                tone="success",
            )

            self.refresh()

        except Exception as exc:
            import traceback
            traceback.print_exc()
            messagebox.showerror(
                "Error",
                f"Error al entregar el pedido #{order_id}:\n{exc}",
                parent=self,
            )

    def _check_and_notify_urgent_overdue(self):
        """Verifica pedidos urgentes y vencidos y genera notificaciones."""
        try:
            now = datetime.now()

            all_orders = []
            for column in self.stage_service.get_production_board_columns():
                orders = self.stage_service.get_orders_by_production_column(column, {})
                all_orders.extend(orders)

            urgent_orders = [o for o in all_orders if o.is_urgent]
            overdue_orders = []

            for order in all_orders:
                if order.delivery_date:
                    try:
                        if "T" in order.delivery_date:
                            delivery_dt = datetime.fromisoformat(order.delivery_date.replace("Z", "+00:00"))
                        else:
                            delivery_dt = datetime.strptime(order.delivery_date[:10], "%Y-%m-%d")

                        if delivery_dt < now:
                            overdue_orders.append(order)
                    except (ValueError, TypeError):
                        pass

            if urgent_orders:
                self._generate_production_notification(
                    "urgent",
                    f"{len(urgent_orders)} pedido{'s' if len(urgent_orders) != 1 else ''} urgente{'s' if len(urgent_orders) != 1 else ''}",
                    urgent_orders[:5]
                )

            if overdue_orders:
                self._generate_production_notification(
                    "overdue",
                    f"{len(overdue_orders)} pedido{'s' if len(overdue_orders) != 1 else ''} vencido{'s' if len(overdue_orders) != 1 else ''}",
                    overdue_orders[:5]
                )

        except Exception as e:
            import traceback
            traceback.print_exc()

    def _generate_production_notification(self, notification_type: str, summary: str, orders: list):
        """Genera una notificación de producción usando el event bus."""
        try:
            parent = self.winfo_toplevel()
            if hasattr(parent, '_event_bus'):
                event_bus = parent._event_bus

                order_list = ", ".join([f"#{o.order_id}" for o in orders])
                message = f"{summary}: {order_list}"
                if len(orders) > 5:
                    message += f" y {len(orders) - 5} más"

                event_bus.publish(
                    event_type="production.alert",
                    title=f"⚠️ {summary}" if notification_type == "urgent" else f"📅 {summary}",
                    message=message,
                    priority="high" if notification_type == "urgent" else "normal",
                    entity_type="production",
                    entity_id=0,
                    payload={
                        "notification_type": notification_type,
                        "order_ids": [o.order_id for o in orders],
                        "count": len(orders),
                    },
                )

        except Exception as e:
            import traceback
            traceback.print_exc()

    def get_selected_order_id(self) -> int | None:
        """Retorna el ID del pedido seleccionado actualmente."""
        return self.selected_order_id
