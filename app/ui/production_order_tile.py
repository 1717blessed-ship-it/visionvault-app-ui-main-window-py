"""Componente reutilizable para visualización de pedidos en vistas de producción.

ProductionOrderTile es un tile configurable para mostrar información de pedidos
de forma compacta y visual. Diseñado para ser usado en múltiples contextos:
- Tableros kanban por etapa
- Listas de producción
- Vistas de tracking
- Dashboards de monitoreo

El componente es desacoplado y usa callbacks para todas las interacciones,
evitando dependencias con vistas específicas.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from app.ui.theme import COLORS, UI_FONT


class ProductionOrderTile(tk.Frame):
    """Tile compacto para visualizar un pedido en vistas de producción.
    
    Características:
    - Muestra información clave: cliente, material, cantidad, antigüedad
    - Indicador visual de prioridad (color lateral)
    - Badges para urgente y días de antigüedad
    - Callbacks configurables para click y hover
    - Estilo consistente con el sistema de diseño
    
    Configuración mediante callbacks:
    - on_click: se ejecuta al hacer click en el tile
    - on_hover: se ejecuta al pasar el mouse (opcional)
    - on_context_menu: menú contextual (opcional)
    """
    
    def __init__(
        self,
        parent,
        order_id: int,
        client_name: str,
        material: str,
        quantity: int,
        jobs_count: int,
        age_days: float,
        priority: int = 0,
        is_urgent: bool = False,
        delivery_date: str = "",
        on_click: Callable[[int], None] | None = None,
        on_hover: Callable[[int], None] | None = None,
        on_context_menu: Callable[[int, tk.Event], None] | None = None,
        **kwargs,
    ):
        """Crea un tile de pedido con la información especificada.
        
        Args:
            parent: Widget padre
            order_id: ID del pedido
            client_name: Nombre del cliente
            material: Material o descripción del trabajo
            quantity: Cantidad de unidades
            jobs_count: Cantidad de trabajos en el pedido
            age_days: Días desde la creación del pedido
            priority: Nivel de prioridad (0-4)
            is_urgent: Si el pedido es urgente
            delivery_date: Fecha de entrega (opcional)
            on_click: Callback al hacer click (recibe order_id)
            on_hover: Callback al pasar el mouse (recibe order_id)
            on_context_menu: Callback para menú contextual (recibe order_id, event)
        """
        super().__init__(parent, **kwargs)
        
        self.order_id = order_id
        self._on_click = on_click
        self._on_hover = on_hover
        self._on_context_menu = on_context_menu
        
        # Configuración del contenedor principal
        self.configure(
            background=COLORS.panel,
            highlightthickness=1,
            highlightbackground=COLORS.border,
            cursor="hand2",
        )
        
        # Color del borde lateral según prioridad
        priority_color = self._get_priority_color(priority)
        
        # Borde lateral de prioridad
        priority_bar = tk.Frame(
            self,
            background=priority_color,
            width=4,
        )
        priority_bar.pack(side="left", fill="y")
        
        # Contenedor de contenido
        content_frame = tk.Frame(self, background=COLORS.panel)
        content_frame.pack(side="left", fill="both", expand=True, padx=(8, 10), pady=8)
        
        # Header: ID + Badges
        header_frame = tk.Frame(content_frame, background=COLORS.panel)
        header_frame.pack(fill="x", pady=(0, 6))
        
        # ID del pedido
        id_label = tk.Label(
            header_frame,
            text=f"#{order_id}",
            background=COLORS.panel,
            foreground=COLORS.wine_active,
            font=(UI_FONT, 10, "bold"),
        )
        id_label.pack(side="left")
        
        # Badge de urgente
        if is_urgent:
            urgent_badge = tk.Label(
                header_frame,
                text="URGENTE",
                background=COLORS.error,
                foreground=COLORS.text,
                font=(UI_FONT, 8, "bold"),
                padx=6,
                pady=2,
            )
            urgent_badge.pack(side="left", padx=(6, 0))
        
        # Badge de antigüedad (si es > 3 días)
        if age_days > 3:
            age_color = self._get_age_color(age_days)
            age_text = f"{int(age_days)}d" if age_days < 30 else f"{int(age_days/30)}m"
            age_badge = tk.Label(
                header_frame,
                text=age_text,
                background=age_color,
                foreground=COLORS.text,
                font=(UI_FONT, 8, "bold"),
                padx=6,
                pady=2,
            )
            age_badge.pack(side="right")
        
        # Cliente
        client_display = client_name[:25] + "..." if len(client_name) > 25 else client_name
        client_label = tk.Label(
            content_frame,
            text=client_display,
            background=COLORS.panel,
            foreground=COLORS.text,
            font=(UI_FONT, 10),
            anchor="w",
        )
        client_label.pack(fill="x", pady=(0, 4))
        
        # Material y cantidad
        material_display = material[:30] + "..." if len(material) > 30 else material
        material_text = f"{material_display}"
        
        if quantity > 0:
            material_text += f" · {quantity} un."
        
        if jobs_count > 1:
            material_text += f" · {jobs_count} trabajos"
        
        material_label = tk.Label(
            content_frame,
            text=material_text,
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 9),
            anchor="w",
        )
        material_label.pack(fill="x")
        
        # Fecha de entrega (opcional)
        if delivery_date:
            delivery_frame = tk.Frame(content_frame, background=COLORS.panel)
            delivery_frame.pack(fill="x", pady=(4, 0))
            
            tk.Label(
                delivery_frame,
                text="📅",
                background=COLORS.panel,
                foreground=COLORS.muted,
                font=(UI_FONT, 9),
            ).pack(side="left")
            
            delivery_display = self._format_delivery_date(delivery_date)
            tk.Label(
                delivery_frame,
                text=delivery_display,
                background=COLORS.panel,
                foreground=COLORS.muted,
                font=(UI_FONT, 9),
            ).pack(side="left", padx=(4, 0))
        
        # Bindings de eventos
        self._bind_events(self)
        self._bind_events(content_frame)
        self._bind_events(header_frame)
        self._bind_events(client_label)
        self._bind_events(material_label)
    
    def _bind_events(self, widget):
        """Aplica los eventos al widget y sus hijos."""
        if self._on_click:
            widget.bind("<Button-1>", lambda e: self._on_click(self.order_id))
        
        if self._on_hover:
            widget.bind("<Enter>", lambda e: self._handle_hover())
        
        if self._on_context_menu:
            widget.bind("<Button-3>", lambda e: self._on_context_menu(self.order_id, e))
        
        # Aplicar también a hijos
        for child in widget.winfo_children():
            self._bind_events(child)
    
    def _handle_hover(self):
        """Maneja el efecto hover."""
        self.configure(highlightbackground=COLORS.border_strong)
        if self._on_hover:
            self._on_hover(self.order_id)
    
    def _handle_hover_leave(self):
        """Restaura el borde al salir del hover."""
        self.configure(highlightbackground=COLORS.border)
    
    def _get_priority_color(self, priority: int) -> str:
        """Retorna el color del borde según la prioridad."""
        if priority >= 4:
            return COLORS.error
        elif priority >= 3:
            return COLORS.warning
        elif priority >= 2:
            return COLORS.info
        else:
            return COLORS.border
    
    def _get_age_color(self, age_days: float) -> str:
        """Retorna el color del badge de antigüedad."""
        if age_days > 14:
            return COLORS.error
        elif age_days > 7:
            return COLORS.warning
        else:
            return COLORS.info
    
    def _format_delivery_date(self, date_str: str) -> str:
        """Formatea la fecha de entrega para visualización."""
        if not date_str:
            return ""
        
        try:
            from datetime import datetime
            
            # Intentar parsear diferentes formatos
            if "T" in date_str:
                date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            else:
                date = datetime.strptime(date_str[:10], "%Y-%m-%d")
            
            # Formato compacto
            return date.strftime("%d/%m")
        except (ValueError, TypeError):
            return date_str[:10] if len(date_str) >= 10 else date_str
    
    def set_highlight(self, highlighted: bool):
        """Activa o desactiva el resaltado del tile (para selección)."""
        if highlighted:
            self.configure(
                highlightbackground=COLORS.wine_active,
                highlightthickness=2,
            )
        else:
            self.configure(
                highlightbackground=COLORS.border,
                highlightthickness=1,
            )


class ProductionOrderTileCompact(tk.Frame):
    """Versión compacta del tile para vistas densas.
    
    Muestra solo la información esencial en una sola línea:
    - ID + Cliente + Indicador de urgencia
    - Material resumido
    """
    
    def __init__(
        self,
        parent,
        order_id: int,
        client_name: str,
        material: str,
        is_urgent: bool = False,
        on_click: Callable[[int], None] | None = None,
        **kwargs,
    ):
        super().__init__(parent, **kwargs)
        
        self.order_id = order_id
        self._on_click = on_click
        
        self.configure(
            background=COLORS.panel,
            highlightthickness=1,
            highlightbackground=COLORS.border,
            cursor="hand2",
        )
        
        content_frame = tk.Frame(self, background=COLORS.panel)
        content_frame.pack(fill="both", expand=True, padx=8, pady=6)
        
        # ID
        id_text = f"#{order_id}"
        if is_urgent:
            id_text += " ⚠️"
        
        id_label = tk.Label(
            content_frame,
            text=id_text,
            background=COLORS.panel,
            foreground=COLORS.wine_active if is_urgent else COLORS.text,
            font=(UI_FONT, 9, "bold"),
        )
        id_label.pack(side="left")
        
        # Cliente
        client_display = client_name[:15] + "..." if len(client_name) > 15 else client_name
        client_label = tk.Label(
            content_frame,
            text=client_display,
            background=COLORS.panel,
            foreground=COLORS.text,
            font=(UI_FONT, 9),
        )
        client_label.pack(side="left", padx=(8, 0))
        
        # Material
        material_display = material[:20] + "..." if len(material) > 20 else material
        material_label = tk.Label(
            content_frame,
            text=material_display,
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 9),
        )
        material_label.pack(side="right")
        
        # Binding de click
        if on_click:
            self.bind("<Button-1>", lambda e: on_click(order_id))
            content_frame.bind("<Button-1>", lambda e: on_click(order_id))
