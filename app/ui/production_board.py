"""Vista de tablero kanban para gestión visual de producción por etapas.

ProductionBoardView muestra pedidos agrupados por etapa en columnas verticales,
con métricas agregadas y tiles interactivos para cada pedido.
"""

from __future__ import annotations

import sqlite3
import tkinter as tk
from tkinter import messagebox

from app.database.database import ImageDatabase
from app.services.stage_service import StageService
from app.ui.production_order_tile import ProductionOrderTile
from app.ui.theme import COLORS, UI_FONT, IDENTITY_FONT
from app.ui.components import section_heading, Toast


class ProductionBoardView(tk.Frame):
    """Tablero visual de producción agrupado por etapas.
    
    Características:
    - Columnas verticales por etapa de producción
    - Métricas agregadas en header de cada columna
    - Tiles interactivos para cada pedido
    - Scroll horizontal para múltiples columnas
    - Actualización manual con botón de refresh
    
    Diseñado para visualización en pantalla completa o embebido en tabs.
    """
    
    def __init__(self, parent, database: ImageDatabase):
        super().__init__(parent)
        
        self.database = database
        self.stage_service = StageService(database.connection)
        self.selected_order_id: int | None = None
        
        self.configure(background=COLORS.background)
        
        # Header con título y controles
        self._build_header()
        
        # Contenedor principal con scroll horizontal
        self.canvas_container = tk.Frame(self, background=COLORS.background)
        self.canvas_container.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        # Canvas para scroll horizontal
        self.canvas = tk.Canvas(
            self.canvas_container,
            background=COLORS.background,
            highlightthickness=0,
        )
        self.scrollbar = tk.Scrollbar(
            self.canvas_container,
            orient="horizontal",
            command=self.canvas.xview,
        )
        
        self.canvas.configure(xscrollcommand=self.scrollbar.set)
        
        self.scrollbar.pack(side="bottom", fill="x")
        self.canvas.pack(side="top", fill="both", expand=True)
        
        # Frame interno del canvas que contendrá las columnas
        self.board_frame = tk.Frame(self.canvas, background=COLORS.background)
        self.canvas_window = self.canvas.create_window(
            (0, 0),
            window=self.board_frame,
            anchor="nw",
        )
        
        # Bind para actualizar scroll region
        self.board_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        
        # Scroll con mouse wheel
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        
        # Cargar datos iniciales
        self.refresh()
    
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
        
        # Botón de filtros (placeholder para futuras versiones)
        filter_btn = tk.Button(
            controls_frame,
            text="⚙ Filtros",
            command=self._show_filters,
            background=COLORS.panel,
            foreground=COLORS.muted,
            activebackground=COLORS.panel_elevated,
            activeforeground=COLORS.text,
            font=(UI_FONT, 10),
            padx=14,
            pady=8,
            cursor="hand2",
            relief="flat",
            borderwidth=1,
        )
        filter_btn.pack(side="right")
    
    def _on_frame_configure(self, event=None):
        """Actualiza la región de scroll cuando cambia el tamaño del frame."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
    
    def _on_canvas_configure(self, event):
        """Ajusta el ancho del frame interno al canvas si es necesario."""
        canvas_width = event.width
        frame_width = self.board_frame.winfo_reqwidth()
        
        if frame_width < canvas_width:
            self.canvas.itemconfig(self.canvas_window, width=canvas_width)
    
    def _on_mousewheel(self, event):
        """Scroll horizontal con mouse wheel (+ Shift)."""
        if event.state & 0x1:  # Shift presionado
            self.canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
    
    def refresh(self):
        """Recarga los datos y reconstruye el tablero."""
        # Limpiar columnas existentes
        for widget in self.board_frame.winfo_children():
            widget.destroy()
        
        # Obtener etapas con métricas
        try:
            stages_with_metrics = self.stage_service.get_all_stages_with_metrics()
        except Exception as e:
            messagebox.showerror(
                "Error",
                f"Error al cargar datos del tablero:\n{e}",
                parent=self,
            )
            return
        
        # Crear columna por cada etapa
        for stage_name, metrics in stages_with_metrics:
            self._build_stage_column(stage_name, metrics)
        
        # Actualizar scroll region
        self.board_frame.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        
        # Mostrar notificación
        Toast(self, "Tablero actualizado", tone="success", duration=1500)
    
    def _build_stage_column(self, stage_name: str, metrics):
        """Construye una columna de etapa con sus pedidos."""
        # Columna contenedor
        column_frame = tk.Frame(
            self.board_frame,
            background=COLORS.background_secondary,
            highlightthickness=1,
            highlightbackground=COLORS.border,
        )
        column_frame.pack(side="left", fill="both", padx=8, pady=8, ipadx=2, ipady=2)
        
        # Ancho fijo para las columnas
        column_frame.configure(width=320)
        column_frame.pack_propagate(False)
        
        # Header de la columna con métricas
        self._build_column_header(column_frame, stage_name, metrics)
        
        # Separador
        separator = tk.Frame(
            column_frame,
            background=COLORS.border,
            height=1,
        )
        separator.pack(fill="x", padx=10, pady=(0, 8))
        
        # Scroll para los pedidos de esta columna
        column_canvas = tk.Canvas(
            column_frame,
            background=COLORS.background_secondary,
            highlightthickness=0,
        )
        column_scrollbar = tk.Scrollbar(
            column_frame,
            orient="vertical",
            command=column_canvas.yview,
        )
        
        column_canvas.configure(yscrollcommand=column_scrollbar.set)
        
        column_scrollbar.pack(side="right", fill="y")
        column_canvas.pack(side="left", fill="both", expand=True)
        
        # Frame interno para los tiles
        tiles_frame = tk.Frame(column_canvas, background=COLORS.background_secondary)
        column_canvas.create_window((0, 0), window=tiles_frame, anchor="nw")
        
        # Obtener pedidos de esta etapa
        try:
            orders = self.stage_service.get_orders_by_stage(stage_name)
        except Exception as e:
            error_label = tk.Label(
                tiles_frame,
                text=f"Error: {e}",
                background=COLORS.background_secondary,
                foreground=COLORS.error,
                font=(UI_FONT, 9),
            )
            error_label.pack(padx=10, pady=10)
            return
        
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
                    on_context_menu=self._on_order_context_menu,
                )
                tile.pack(fill="x", padx=10, pady=(0, 8))
        
        # Actualizar scroll region
        tiles_frame.update_idletasks()
        column_canvas.configure(scrollregion=column_canvas.bbox("all"))
        
        # Bind scroll con mouse wheel
        def _on_column_mousewheel(event):
            column_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
        column_canvas.bind_all("<MouseWheel>", _on_column_mousewheel)
    
    def _build_column_header(self, parent, stage_name: str, metrics):
        """Construye el header de una columna con métricas."""
        header_frame = tk.Frame(parent, background=COLORS.background_secondary)
        header_frame.pack(fill="x", padx=10, pady=(10, 8))
        
        # Título de la etapa
        title_label = tk.Label(
            header_frame,
            text=stage_name,
            background=COLORS.background_secondary,
            foreground=COLORS.wine_active,
            font=(UI_FONT, 11, "bold"),
            anchor="w",
        )
        title_label.pack(fill="x")
        
        # Métricas
        metrics_frame = tk.Frame(header_frame, background=COLORS.background_secondary)
        metrics_frame.pack(fill="x", pady=(6, 0))
        
        # Total de pedidos y trabajos
        count_text = f"{metrics.total_orders} pedido{'s' if metrics.total_orders != 1 else ''}"
        if metrics.total_jobs > 0:
            count_text += f" · {metrics.total_jobs} trabajo{'s' if metrics.total_jobs != 1 else ''}"
        
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
        if metrics.urgent_count > 0:
            urgent_label = tk.Label(
                metrics_frame,
                text=f"⚠️ {metrics.urgent_count} urgente{'s' if metrics.urgent_count != 1 else ''}",
                background=COLORS.background_secondary,
                foreground=COLORS.warning,
                font=(UI_FONT, 9, "bold"),
                anchor="w",
            )
            urgent_label.pack(fill="x", pady=(2, 0))
        
        # Antigüedad del más antiguo
        if metrics.oldest_order_days is not None and metrics.oldest_order_days > 0:
            age_text = f"Más antiguo: {int(metrics.oldest_order_days)} día{'s' if metrics.oldest_order_days != 1 else ''}"
            
            age_color = COLORS.muted
            if metrics.oldest_order_days > 14:
                age_color = COLORS.error
            elif metrics.oldest_order_days > 7:
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
    
    def _on_order_click(self, order_id: int):
        """Maneja el click en un tile de pedido."""
        self.selected_order_id = order_id
        
        # TODO: Abrir detalle del pedido o navegar a vista de pedidos
        # Por ahora, mostrar toast con ID
        Toast(self, f"Pedido #{order_id} seleccionado", tone="info", duration=1500)
        
        # Emitir evento personalizado para que el parent lo maneje
        self.event_generate("<<OrderSelected>>", when="tail")
    
    def _on_order_context_menu(self, order_id: int, event: tk.Event):
        """Maneja el menú contextual de un tile."""
        menu = tk.Menu(self, tearoff=0)
        
        menu.add_command(
            label=f"Ver pedido #{order_id}",
            command=lambda: self._view_order_details(order_id),
        )
        menu.add_separator()
        menu.add_command(
            label="Cambiar etapa...",
            command=lambda: self._change_order_stage(order_id),
        )
        menu.add_command(
            label="Marcar como urgente",
            command=lambda: self._mark_as_urgent(order_id),
        )
        menu.add_separator()
        menu.add_command(
            label="Actualizar tablero",
            command=self.refresh,
        )
        
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
    
    def _view_order_details(self, order_id: int):
        """Abre la vista de detalles del pedido."""
        # TODO: Implementar navegación a vista de detalle
        Toast(self, f"Vista de detalle para pedido #{order_id}", tone="info")
    
    def _change_order_stage(self, order_id: int):
        """Abre diálogo para cambiar la etapa del pedido."""
        # TODO: Implementar diálogo de cambio de etapa
        Toast(self, "Cambio de etapa en desarrollo", tone="warning")
    
    def _mark_as_urgent(self, order_id: int):
        """Marca un pedido como urgente."""
        try:
            self.database.update_order_priority(order_id, 4)
            self.refresh()
            Toast(self, f"Pedido #{order_id} marcado como urgente", tone="success")
        except Exception as e:
            messagebox.showerror(
                "Error",
                f"Error al actualizar prioridad:\n{e}",
                parent=self,
            )
    
    def _show_filters(self):
        """Muestra diálogo de filtros (placeholder)."""
        Toast(self, "Filtros en desarrollo", tone="info")
    
    def get_selected_order_id(self) -> int | None:
        """Retorna el ID del pedido seleccionado actualmente."""
        return self.selected_order_id
