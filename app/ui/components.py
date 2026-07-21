"""Pequeños componentes visuales reutilizables de Doccione Studio."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.ui.theme import COLORS, IDENTITY_FONT, UI_FONT


def build_order_notification_payload(order: dict, priority_level: str, priority_score: int, priority_reason: str) -> dict | None:
    """Prepara los datos seguros para mostrar una notificación de pedido."""
    order_id = order.get("id")
    if order_id is None:
        return None

    client_name = order.get("client_name") or order.get("client") or "Sin nombre"
    client_name = str(client_name)
    if len(client_name) > 18:
        client_name = client_name[:15] + "..."

    reason = str(priority_reason or "Sin detalle").strip()
    if len(reason) > 30:
        reason = reason[:27] + "..."

    return {
        "order_id": order_id,
        "client_name": client_name,
        "priority_level": priority_level,
        "priority_score": priority_score,
        "reason": reason,
    }


def section_heading(parent, text: str, *, detail: str | None = None, padding=(14, 12, 14, 8)):
    """Encabezado compacto para paneles, tablas y barras contextuales."""
    holder = tk.Frame(parent, background=COLORS.panel)
    holder.pack(fill="x", padx=padding[0], pady=(padding[1], padding[3]))
    tk.Label(holder, text=text, background=COLORS.panel, foreground=COLORS.wine_active,
             font=(IDENTITY_FONT, 10, "bold")).pack(anchor="w")
    if detail:
        tk.Label(holder, text=detail, background=COLORS.panel, foreground=COLORS.muted,
                 font=(UI_FONT, 9), wraplength=220, justify="left").pack(anchor="w", pady=(3, 0))
    return holder


def navigation_button(parent, text: str, command):
    """Botón de navegación con estado activo gestionado por set_navigation_active."""
    button = tk.Button(
        parent, text=text, command=command, anchor="w", justify="left",
        background=COLORS.background_secondary, foreground=COLORS.muted,
        activebackground=COLORS.panel_elevated, activeforeground=COLORS.text,
        borderwidth=0, relief="flat", highlightthickness=0,
        padx=14, pady=9, font=(UI_FONT, 10, "bold"), cursor="hand2",
    )
    button.pack(fill="x", padx=8, pady=2)
    return button


def set_navigation_active(button, active: bool) -> None:
    button.configure(
        background=COLORS.wine if active else COLORS.background_secondary,
        foreground=COLORS.text if active else COLORS.muted,
        activebackground=COLORS.wine_active if active else COLORS.panel_elevated,
    )


def status_strip(parent, variable: tk.Variable):
    """Aviso visible y tranquilo para mensajes operativos no bloqueantes."""
    holder = tk.Frame(parent, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
    dot = tk.Label(holder, text="●", background=COLORS.panel, foreground=COLORS.success, font=(UI_FONT, 10))
    dot.pack(side="left", padx=(10, 7), pady=7)
    tk.Label(holder, textvariable=variable, background=COLORS.panel, foreground=COLORS.muted,
             font=(UI_FONT, 10), anchor="w").pack(side="left", fill="x", expand=True, padx=(0, 10), pady=7)
    return holder


class Toast:
    """Aviso breve no bloqueante, para operaciones que no requieren respuesta."""

    def __init__(self, parent, text: str, tone: str = "info", duration: int = 2600):
        colors = {"info": COLORS.info, "success": COLORS.success, "warning": COLORS.warning, "error": COLORS.error}
        self.window = tk.Toplevel(parent)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(background=COLORS.panel_elevated, highlightthickness=1,
                              highlightbackground=colors.get(tone, COLORS.info))
        tk.Label(self.window, text=text, background=COLORS.panel_elevated, foreground=COLORS.text,
                 font=(UI_FONT, 10), justify="left", wraplength=360, padx=14, pady=10).pack()
        self.window.update_idletasks()
        x = max(0, parent.winfo_rootx() + parent.winfo_width() - self.window.winfo_width() - 24)
        y = max(0, parent.winfo_rooty() + parent.winfo_height() - self.window.winfo_height() - 24)
        self.window.geometry(f"+{x}+{y}")
        self.window.after(duration, self.destroy)

    def destroy(self):
        if self.window.winfo_exists():
            self.window.destroy()


class Tooltip:
    """Ayuda breve para controles compactos, sin ocupar espacio fijo."""

    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.window = None
        self.after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._hide()
        self.after_id = self.widget.after(500, self._show)

    def _show(self):
        self.after_id = None
        if not self.widget.winfo_exists():
            return
        self.window = tk.Toplevel(self.widget)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border_strong)
        tk.Label(
            self.window, text=self.text, background=COLORS.panel_elevated,
            foreground=COLORS.text, font=(UI_FONT, 9), padx=9, pady=5,
        ).pack()
        self.window.update_idletasks()
        x = self.widget.winfo_rootx() + max(0, (self.widget.winfo_width() - self.window.winfo_width()) // 2)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.window.geometry(f"+{x}+{y}")

    def _hide(self, _event=None):
        if self.after_id is not None:
            self.widget.after_cancel(self.after_id)
            self.after_id = None
        if self.window is not None:
            self.window.destroy()
            self.window = None


def icon_button(parent, icon: str, description: str, command, *, tone: str = "secondary"):
    """Botón de barra de herramientas: símbolo lineal más ayuda al pasar el mouse."""
    style = {
        "primary": "Plancha.Icon.Primary.TButton",
        "danger": "Plancha.Icon.Danger.TButton",
    }.get(tone, "Plancha.Icon.Secondary.TButton")
    button = ttk.Button(parent, text=icon, command=command, style=style, width=3)
    Tooltip(button, description)
    return button
