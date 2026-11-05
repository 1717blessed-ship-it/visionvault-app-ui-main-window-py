"""
Panel "Necesitan atención hoy" - Dashboard inteligente.
Muestra los pedidos que requieren acción inmediata.
"""

import tkinter as tk
from tkinter import ttk
from typing import Callable

from app.workflow.priority import calculate_priority, get_priority_emoji, get_priority_color
from app.workflow.timeline import get_next_action, get_current_stage
from app.workflow.estimator import estimate_remaining_work, format_time_remaining, format_work_time


COLORS = type("COLORS", (), {
    "background": "#111314",
    "panel": "#1b1e1f",
    "panel_elevated": "#252829",
    "text": "#f3e0d2",
    "muted": "#b9a79b",
    "wine": "#d60916",
    "wine_active": "#ff2937",
    "border": "#2d3132",
})()

UI_FONT = "Segoe UI"
IDENTITY_FONT = "Bahnschrift SemiCondensed"


class AttentionDashboard(tk.Toplevel):
    """Panel que muestra pedidos que necesitan atención inmediata."""
    
    def __init__(
        self,
        parent,
        orders: list[dict],
        on_open_order: Callable[[int], None],
    ):
        super().__init__(parent)
        self.orders = orders
        self.on_open_order = on_open_order
        
        self.title("Necesitan atención hoy")
        self.configure(background=COLORS.background)
        self.transient(parent)
        self.geometry("950x680")
        self.minsize(850, 600)
        
        self._build_ui()
        self._render_orders()
        
        # Centrar en pantalla
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (self.winfo_width() // 2)
        y = (self.winfo_screenheight() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{x}+{y}")
    
    def _build_ui(self):
        """Construye la interfaz del dashboard."""
        # Header
        header = tk.Frame(
            self,
            background=COLORS.panel,
            highlightthickness=1,
            highlightbackground=COLORS.border
        )
        header.pack(fill="x", padx=20, pady=(20, 12))
        
        tk.Label(
            header,
            text="⚠ NECESITAN ATENCIÓN HOY",
            background=COLORS.panel,
            foreground=COLORS.wine_active,
            font=(IDENTITY_FONT, 20, "bold")
        ).pack(anchor="w", padx=18, pady=(16, 4))
        
        tk.Label(
            header,
            text="Pedidos ordenados por urgencia. Trabajá de arriba hacia abajo.",
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 11)
        ).pack(anchor="w", padx=18, pady=(0, 16))
        
        # Scrollable container
        container = tk.Frame(self, background=COLORS.background)
        container.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        
        canvas = tk.Canvas(
            container,
            background=COLORS.background,
            highlightthickness=0,
            borderwidth=0
        )
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        
        self.scrollable_frame = tk.Frame(canvas, background=COLORS.background)
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Bind mouse wheel
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
        canvas.bind_all("<MouseWheel>", on_mousewheel)
    
    def _render_orders(self):
        """Renderiza las tarjetas de pedidos urgentes."""
        from app.workflow.priority import sort_orders_by_priority
        
        # Filtrar pedidos que necesitan atención
        urgent_orders = []
        for order in self.orders:
            # Excluir pedidos cerrados; la entrega se persiste como Terminado
            # en el cierre transaccional del tablero de producción.
            status = str(order.get("status", ""))
            if status in ("Archivado", "Finalizado", "Entregado", "Terminado", "Cancelado"):
                continue
            
            # Calcular prioridad
            estimated_minutes = estimate_remaining_work(order)
            level, score, reason = calculate_priority(order, estimated_minutes)
            
            # Incluir si tiene prioridad Media o superior.
            if level in ("Media", "Alta", "Urgente"):
                urgent_orders.append({
                    **order,
                    "_priority_level": level,
                    "_priority_score": score,
                    "_priority_reason": reason,
                    "_estimated_work_minutes": estimated_minutes,
                })
        
        # Ordenar por urgencia
        urgent_orders.sort(key=lambda o: o["_priority_score"], reverse=True)
        
        if not urgent_orders:
            tk.Label(
                self.scrollable_frame,
                text="✓ No hay pedidos urgentes en este momento.",
                background=COLORS.background,
                foreground=COLORS.muted,
                font=(UI_FONT, 13)
            ).pack(pady=50)
            return
        
        # Renderizar cada pedido como tarjeta
        for order in urgent_orders:
            self._render_order_card(order)
    
    def _render_order_card(self, order: dict):
        """Renderiza una tarjeta individual de pedido."""
        order_id = order["id"]
        client = order.get("client_name") or order.get("client", "Sin cliente")
        priority_level = order["_priority_level"]
        priority_reason = order["_priority_reason"]
        estimated_minutes = order["_estimated_work_minutes"]
        
        # Próxima acción
        action_key, action_desc, action_time = get_next_action(order)
        
        # Tiempo restante
        time_remaining = format_time_remaining(order)
        work_time = format_work_time(estimated_minutes)
        
        # Color de prioridad
        priority_color = get_priority_color(priority_level)
        emoji = get_priority_emoji(priority_level)
        
        # Card container
        card = tk.Frame(
            self.scrollable_frame,
            background=COLORS.panel,
            highlightthickness=2,
            highlightbackground=priority_color,
            cursor="hand2"
        )
        card.pack(fill="x", pady=(0, 12))
        
        # Click para abrir pedido
        def open_order(event=None):
            self.on_open_order(order_id)
            self.destroy()
        
        card.bind("<Button-1>", open_order)
        
        # Header de la card
        card_header = tk.Frame(card, background=COLORS.panel)
        card_header.pack(fill="x", padx=16, pady=(14, 8))
        
        # Prioridad y número
        tk.Label(
            card_header,
            text=f"{emoji} Pedido #{order_id}",
            background=COLORS.panel,
            foreground=COLORS.text,
            font=(IDENTITY_FONT, 15, "bold"),
            cursor="hand2"
        ).pack(side="left")
        card_header.children[list(card_header.children.keys())[-1]].bind("<Button-1>", open_order)
        
        tk.Label(
            card_header,
            text=f"  ·  {client}",
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 12),
            cursor="hand2"
        ).pack(side="left")
        card_header.children[list(card_header.children.keys())[-1]].bind("<Button-1>", open_order)
        
        # Prioridad badge
        priority_badge = tk.Label(
            card_header,
            text=f" {priority_level} ",
            background=priority_color,
            foreground="#FFFFFF",
            font=(UI_FONT, 10, "bold"),
            padx=8,
            pady=2,
            cursor="hand2"
        )
        priority_badge.pack(side="right")
        priority_badge.bind("<Button-1>", open_order)
        
        # Razón principal
        tk.Label(
            card,
            text=priority_reason,
            background=COLORS.panel,
            foreground=COLORS.wine_active if priority_level == "Urgente" else COLORS.text,
            font=(UI_FONT, 11, "bold"),
            cursor="hand2"
        ).pack(anchor="w", padx=16, pady=(0, 10))
        
        # Info row
        info_row = tk.Frame(card, background=COLORS.panel)
        info_row.pack(fill="x", padx=16, pady=(0, 8))
        
        # Columna izquierda: Tiempo
        left_col = tk.Frame(info_row, background=COLORS.panel)
        left_col.pack(side="left", fill="x", expand=True)
        
        tk.Label(
            left_col,
            text=f"Entrega: {time_remaining}",
            background=COLORS.panel,
            foreground=COLORS.text,
            font=(UI_FONT, 10),
            cursor="hand2"
        ).pack(anchor="w")
        left_col.children[list(left_col.children.keys())[-1]].bind("<Button-1>", open_order)
        
        tk.Label(
            left_col,
            text=f"Trabajo estimado: {work_time}",
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 10),
            cursor="hand2"
        ).pack(anchor="w")
        left_col.children[list(left_col.children.keys())[-1]].bind("<Button-1>", open_order)
        
        # Separador
        tk.Frame(card, background=COLORS.border, height=1).pack(fill="x", padx=16, pady=10)
        
        # Acción recomendada
        action_frame = tk.Frame(card, background=COLORS.panel)
        action_frame.pack(fill="x", padx=16, pady=(0, 14))
        
        tk.Label(
            action_frame,
            text="✓ Siguiente acción:",
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 10),
            cursor="hand2"
        ).pack(side="left")
        action_frame.children[list(action_frame.children.keys())[-1]].bind("<Button-1>", open_order)
        
        tk.Label(
            action_frame,
            text=f"  {action_desc}",
            background=COLORS.panel,
            foreground=COLORS.text,
            font=(UI_FONT, 11, "bold"),
            cursor="hand2"
        ).pack(side="left")
        action_frame.children[list(action_frame.children.keys())[-1]].bind("<Button-1>", open_order)
        
        tk.Label(
            action_frame,
            text=f"  ({format_work_time(action_time)})",
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 10),
            cursor="hand2"
        ).pack(side="left")
        action_frame.children[list(action_frame.children.keys())[-1]].bind("<Button-1>", open_order)
        
        # Botón principal
        button = ttk.Button(
            card,
            text="Ir al pedido",
            command=lambda: open_order(),
            style="Primary.TButton"
        )
        button.pack(anchor="e", padx=16, pady=(0, 14))


def show_attention_dashboard(parent, database, on_open_order: Callable[[int], None]):
    """
    Muestra el panel de pedidos que necesitan atención.
    
    Args:
        parent: Ventana padre
        database: Instancia de Database
        on_open_order: Callback para abrir un pedido
    """
    orders = database.orders()
    dashboard = AttentionDashboard(parent, orders, on_open_order)
    dashboard.grab_set()
