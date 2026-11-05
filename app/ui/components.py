"""Pequeños componentes visuales reutilizables de Doccione Studio."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.ui.theme import COLORS, IDENTITY_FONT, RADIUS, UI_FONT
from app.ui.rounded_components import RoundedNavigationButton


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


def navigation_button(parent, text: str, command, *, rounded: bool = False):
    """Botón de navegación con estado activo gestionado por set_navigation_active."""
    if rounded:
        button = RoundedNavigationButton(
            parent,
            text=text,
            command=command,
            radius_px=RADIUS.medium_px,
            padx=14,
            pady=9,
            cursor="hand2",
        )
        button.pack(fill="x", padx=8, pady=2)
        return button

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
    if isinstance(button, RoundedNavigationButton):
        button.set_active(active)
        return
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


class CustomerAutocomplete:
    """Autocompletado de clientes con búsqueda por nombre/teléfono, ID único y botón de creación."""
    
    def __init__(self, parent, database, on_customer_selected=None, on_new_customer=None):
        self.parent = parent
        self.database = database
        self.on_customer_selected = on_customer_selected
        self.on_new_customer = on_new_customer
        
        self.selected_customer_id = None
        self.selected_customer_name = None
        self.selected_customer_whatsapp = None
        self.selected_customer_type = None
        self.filtered_customers = []
        self.selected_index = -1
        self.dropdown_visible = False
        
        # Main container
        self.container = tk.Frame(parent, background=COLORS.background)
        
        # Search entry
        self.search_var = tk.StringVar()
        self.search_var.set("Buscar cliente...")
        self.search_entry = tk.Entry(
            self.container,
            textvariable=self.search_var,
            background=COLORS.field,
            foreground=COLORS.text,
            insertbackground=COLORS.text,
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLORS.border,
            highlightcolor=COLORS.wine_active,
            font=(UI_FONT, 11),
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        
        # New customer button
        self.new_btn = tk.Button(
            self.container,
            text="+ Nuevo",
            command=self.show_new_customer_dialog,
            background=COLORS.wine,
            foreground=COLORS.text,
            activebackground=COLORS.wine_active,
            activeforeground=COLORS.text,
            relief="flat",
            borderwidth=0,
            font=(UI_FONT, 10, "bold"),
            cursor="hand2",
            padx=12,
            pady=8,
        )
        self.new_btn.pack(side="right")
        
        # Dropdown listbox (hidden by default)
        self.dropdown = tk.Listbox(
            self.parent,
            background=COLORS.panel_elevated,
            foreground=COLORS.text,
            selectbackground=COLORS.wine_active,
            selectforeground=COLORS.text,
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLORS.border,
            highlightcolor=COLORS.wine_active,
            font=(UI_FONT, 11),
            height=8,
            borderwidth=0,
        )
        
        # Bindings
        self.search_entry.bind("<FocusIn>", self._on_focus_in)
        self.search_entry.bind("<FocusOut>", self._on_focus_out)
        self.search_entry.bind("<KeyRelease>", self._on_key_release)
        self.search_entry.bind("<Down>", self._on_down_arrow)
        self.search_entry.bind("<Up>", self._on_up_arrow)
        self.search_entry.bind("<Return>", self._on_enter)
        self.search_entry.bind("<Escape>", self._hide_dropdown)
        self.dropdown.bind("<<ListboxSelect>>", self._on_dropdown_select)
        self.dropdown.bind("<Return>", self._on_enter)
        self.dropdown.bind("<Escape>", self._hide_dropdown)
        
        # Load initial customers
        self._load_customers()
    
    def pack(self, **kwargs):
        """Pack the main container."""
        self.container.pack(**kwargs)
    
    def grid(self, **kwargs):
        """Grid the main container."""
        self.container.grid(**kwargs)
    
    def _on_focus_in(self, event):
        """Clear placeholder text on focus."""
        if self.search_var.get() == "Buscar cliente...":
            self.search_var.set("")
    
    def _on_focus_out(self, event):
        """Restore placeholder if empty and hide dropdown."""
        if not self.search_var.get().strip():
            self.search_var.set("Buscar cliente...")
        # Delay hiding to allow dropdown selection
        self.parent.after(100, self._hide_dropdown)
    
    def _load_customers(self):
        """Load all customers from database."""
        rows = self.database.connection.execute(
            "SELECT id, name, whatsapp, client_type FROM clients ORDER BY name COLLATE NOCASE"
        ).fetchall()
        self.all_customers = [
            {
                "id": row["id"], "name": row["name"],
                "whatsapp": row["whatsapp"] or "",
                "client_type": row["client_type"] or "Particular",
            }
            for row in rows
        ]
    
    def _filter_customers(self, query):
        """Filter customers by name or phone (case-insensitive)."""
        query = query.lower().strip()
        if not query or query == "buscar cliente...":
            self.filtered_customers = self.all_customers[:20]  # Show first 20
        else:
            self.filtered_customers = [
                c for c in self.all_customers
                if query in c["name"].lower() or (query in c["whatsapp"])
            ][:20]
        self.selected_index = -1
    
    def _update_dropdown(self):
        """Update dropdown with filtered customers."""
        self.dropdown.delete(0, tk.END)
        
        # Check for duplicate names
        name_counts = {}
        for customer in self.filtered_customers:
            name = customer["name"]
            name_counts[name] = name_counts.get(name, 0) + 1
        
        for customer in self.filtered_customers:
            name = customer["name"]
            whatsapp = customer["whatsapp"]
            
            # Show phone if duplicate name
            if name_counts[name] > 1 and whatsapp:
                display_text = f"{name} · {whatsapp}"
            else:
                display_text = name
            
            self.dropdown.insert(tk.END, display_text)
        
        # Position and show dropdown
        if self.filtered_customers and self.search_var.get().strip() and self.search_var.get() != "Buscar cliente...":
            x = self.search_entry.winfo_rootx()
            y = self.search_entry.winfo_rooty() + self.search_entry.winfo_height()
            self.dropdown.geometry(f"+{x}+{y}")
            self.dropdown.lift()
            self.dropdown.update_idletasks()
            self.dropdown.deiconify()
            self.dropdown_visible = True
        else:
            self._hide_dropdown()
    
    def _on_key_release(self, event):
        """Filter customers on key release."""
        query = self.search_var.get()
        self._filter_customers(query)
        self._update_dropdown()
    
    def _on_down_arrow(self, event):
        """Navigate down in dropdown."""
        if not self.dropdown_visible or not self.filtered_customers:
            return
        self.selected_index = min(self.selected_index + 1, len(self.filtered_customers) - 1)
        self.dropdown.selection_clear(0, tk.END)
        self.dropdown.selection_set(self.selected_index)
        self.dropdown.see(self.selected_index)
        return "break"
    
    def _on_up_arrow(self, event):
        """Navigate up in dropdown."""
        if not self.dropdown_visible or not self.filtered_customers:
            return
        self.selected_index = max(self.selected_index - 1, 0)
        self.dropdown.selection_clear(0, tk.END)
        self.dropdown.selection_set(self.selected_index)
        self.dropdown.see(self.selected_index)
        return "break"
    
    def _on_enter(self, event):
        """Select highlighted customer."""
        if self.dropdown_visible and self.selected_index >= 0:
            self._select_customer(self.selected_index)
        return "break"
    
    def _on_dropdown_select(self, event):
        """Handle dropdown selection."""
        selection = self.dropdown.curselection()
        if selection:
            self._select_customer(selection[0])
    
    def _select_customer(self, index):
        """Select a customer by index."""
        if 0 <= index < len(self.filtered_customers):
            customer = self.filtered_customers[index]
            self.selected_customer_id = customer["id"]
            self.selected_customer_name = customer["name"]
            self.selected_customer_whatsapp = customer["whatsapp"]
            self.selected_customer_type = customer.get("client_type") or "Particular"
            
            # Update search entry with customer name
            self.search_var.set(customer["name"])
            
            # Hide dropdown
            self._hide_dropdown()
            
            # Callback
            if self.on_customer_selected:
                self.on_customer_selected(customer)
    
    def _hide_dropdown(self, event=None):
        """Hide the dropdown."""
        self.dropdown.withdraw()
        self.dropdown_visible = False
    
    def show_new_customer_dialog(self):
        """Show dialog to create a new customer."""
        if self.on_new_customer:
            self.on_new_customer()
    
    def get_selected_customer(self):
        """Return selected customer info."""
        if self.selected_customer_id:
            return {
                "id": self.selected_customer_id,
                "name": self.selected_customer_name,
                "whatsapp": self.selected_customer_whatsapp,
                "client_type": getattr(self, "selected_customer_type", "Particular"),
            }
        return None
    
    def set_customer(self, customer_id: int, name: str, whatsapp: str = "", client_type: str = "Particular"):
        """Set a customer programmatically."""
        self.selected_customer_id = customer_id
        self.selected_customer_name = name
        self.selected_customer_whatsapp = whatsapp
        self.selected_customer_type = client_type
        self.search_var.set(name)
    
    def clear(self):
        """Clear selection."""
        self.selected_customer_id = None
        self.selected_customer_name = None
        self.selected_customer_whatsapp = None
        self.selected_customer_type = None
        self.search_var.set("Buscar cliente...")
    
    def refresh(self):
        """Reload customers from database."""
        self._load_customers()
        self._filter_customers(self.search_var.get())
