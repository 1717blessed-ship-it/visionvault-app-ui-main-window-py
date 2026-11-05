"""UI forms for Fotocopias y terminaciones in order editor."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from app.ui.theme import COLORS, UI_FONT
from app.services.fotocopia_pricing_service import FotocopiaPricingService, FotocopiaPriceCalculation


def create_fotocopia_form(
    parent: tk.Widget,
    pricing_service: FotocopiaPricingService,
    on_calculation_change: Callable[[FotocopiaPriceCalculation], None],
    initial_data: dict[str, Any] | None = None,
) -> dict[str, tk.Variable]:
    """Create form for photocopies (fotocopias).

    Returns dictionary of form variables.
    """
    initial_data = initial_data or {}

    # Form variables
    vars = {
        "color_mode": tk.StringVar(value=initial_data.get("color_mode", "Blanco y negro")),
        "sides": tk.StringVar(value=initial_data.get("sides", "Simple")),
        "physical_sheets": tk.StringVar(value=str(initial_data.get("physical_sheets", 1))),
        "copies": tk.StringVar(value=str(initial_data.get("copies", 1))),
        "is_urgent": tk.BooleanVar(value=initial_data.get("is_urgent", False)),
        "manual_price": tk.StringVar(value=str(initial_data.get("manual_price", ""))),
    }

    frame = tk.Frame(parent, background=COLORS.panel_elevated)
    frame.pack(fill="x", padx=16, pady=8)

    # Color mode
    tk.Label(frame, text="Tipo", background=COLORS.panel_elevated, foreground=COLORS.text,
             font=(UI_FONT, 10, "bold")).grid(row=0, column=0, sticky="w", pady=4)
    color_combo = ttk.Combobox(
        frame, textvariable=vars["color_mode"],
        values=("Blanco y negro", "Color"),
        state="readonly",
    )
    color_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=4)

    # Sides
    tk.Label(frame, text="Caras", background=COLORS.panel_elevated, foreground=COLORS.text,
             font=(UI_FONT, 10, "bold")).grid(row=1, column=0, sticky="w", pady=4)
    sides_combo = ttk.Combobox(
        frame, textvariable=vars["sides"],
        values=("Simple", "Doble faz"),
        state="readonly",
    )
    sides_combo.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=4)

    # Physical sheets
    tk.Label(frame, text="Hojas físicas", background=COLORS.panel_elevated, foreground=COLORS.text,
             font=(UI_FONT, 10, "bold")).grid(row=2, column=0, sticky="w", pady=4)
    sheets_entry = ttk.Entry(frame, textvariable=vars["physical_sheets"])
    sheets_entry.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=4)

    # Copies
    tk.Label(frame, text="Juegos/copias", background=COLORS.panel_elevated, foreground=COLORS.text,
             font=(UI_FONT, 10, "bold")).grid(row=3, column=0, sticky="w", pady=4)
    copies_entry = ttk.Entry(frame, textvariable=vars["copies"])
    copies_entry.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=4)

    # Urgent checkbox
    urgent_check = tk.Checkbutton(
        frame, text="Trabajo urgente (+30%)",
        variable=vars["is_urgent"],
        background=COLORS.panel_elevated,
        foreground=COLORS.text,
        font=(UI_FONT, 10),
    )
    urgent_check.grid(row=4, column=0, columnspan=2, sticky="w", pady=8)

    # Manual price
    tk.Label(frame, text="Precio manual (opcional)", background=COLORS.panel_elevated, foreground=COLORS.text,
             font=(UI_FONT, 10, "bold")).grid(row=5, column=0, sticky="w", pady=4)
    manual_entry = ttk.Entry(frame, textvariable=vars["manual_price"])
    manual_entry.grid(row=5, column=1, sticky="ew", padx=(8, 0), pady=4)

    frame.columnconfigure(1, weight=1)

    def calculate():
        """Calculate price based on form values."""
        # Determine product type
        color_mode = vars["color_mode"].get()
        sides = vars["sides"].get()

        if color_mode == "Blanco y negro":
            if sides == "Simple":
                product_type = "fotocopia_bn_simple"
            else:
                product_type = "fotocopia_bn_doble"
        else:
            if sides == "Simple":
                product_type = "fotocopia_color_simple"
            else:
                product_type = "fotocopia_color_doble"

        try:
            physical_sheets = max(1, int(vars["physical_sheets"].get() or 1))
        except (ValueError, TypeError):
            physical_sheets = 1

        try:
            copies = max(1, int(vars["copies"].get() or 1))
        except (ValueError, TypeError):
            copies = 1

        is_urgent = vars["is_urgent"].get()

        try:
            manual_price = float(vars["manual_price"].get() or 0) if vars["manual_price"].get() else None
        except (ValueError, TypeError):
            manual_price = None

        calculation = pricing_service.calculate_for_product(
            product_type,
            physical_sheets=physical_sheets,
            copies=copies,
            is_urgent=is_urgent,
            manual_price=manual_price,
        )

        on_calculation_change(calculation)

    # Bind calculation to all inputs
    color_combo.bind("<<ComboboxSelected>>", lambda e: calculate())
    sides_combo.bind("<<ComboboxSelected>>", lambda e: calculate())
    sheets_entry.bind("<KeyRelease>", lambda e: calculate())
    copies_entry.bind("<KeyRelease>", lambda e: calculate())
    urgent_check.bind("<Button-1>", lambda e: calculate())
    manual_entry.bind("<KeyRelease>", lambda e: calculate())

    # Initial calculation
    calculate()

    return vars


def create_anillado_form(
    parent: tk.Widget,
    pricing_service: FotocopiaPricingService,
    on_calculation_change: Callable[[FotocopiaPriceCalculation], None],
    on_size_warning: Callable[[bool, str], None] | None = None,
    initial_data: dict[str, Any] | None = None,
) -> dict[str, tk.Variable]:
    """Create form for binding (anillado).

    Returns dictionary of form variables.
    """
    initial_data = initial_data or {}

    # Form variables
    vars = {
        "sheets": tk.StringVar(value=str(initial_data.get("sheets", 1))),
        "quantity": tk.StringVar(value=str(initial_data.get("quantity", 1))),
        "is_urgent": tk.BooleanVar(value=initial_data.get("is_urgent", False)),
        "manual_price": tk.StringVar(value=str(initial_data.get("manual_price", ""))),
        "size_display": tk.StringVar(value=""),
    }

    frame = tk.Frame(parent, background=COLORS.panel_elevated)
    frame.pack(fill="x", padx=16, pady=8)

    # Sheets
    tk.Label(frame, text="Cantidad de hojas", background=COLORS.panel_elevated, foreground=COLORS.text,
             font=(UI_FONT, 10, "bold")).grid(row=0, column=0, sticky="w", pady=4)
    sheets_entry = ttk.Entry(frame, textvariable=vars["sheets"])
    sheets_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=4)

    # Size display (auto-calculated)
    tk.Label(frame, text="Tamaño (automático)", background=COLORS.panel_elevated, foreground=COLORS.text,
             font=(UI_FONT, 10, "bold")).grid(row=1, column=0, sticky="w", pady=4)
    size_label = tk.Label(frame, textvariable=vars["size_display"], background=COLORS.panel_elevated,
                          foreground=COLORS.text, font=(UI_FONT, 10))
    size_label.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=4)

    # Quantity
    tk.Label(frame, text="Cantidad de anillados", background=COLORS.panel_elevated, foreground=COLORS.text,
             font=(UI_FONT, 10, "bold")).grid(row=2, column=0, sticky="w", pady=4)
    quantity_entry = ttk.Entry(frame, textvariable=vars["quantity"])
    quantity_entry.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=4)

    # Info about covers
    info_label = tk.Label(frame, text="✓ Incluye tapas de cuadernillo",
                         background=COLORS.panel_elevated, foreground=COLORS.muted,
                         font=(UI_FONT, 9))
    info_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=4)

    # Urgent checkbox
    urgent_check = tk.Checkbutton(
        frame, text="Trabajo urgente (+30%)",
        variable=vars["is_urgent"],
        background=COLORS.panel_elevated,
        foreground=COLORS.text,
        font=(UI_FONT, 10),
    )
    urgent_check.grid(row=4, column=0, columnspan=2, sticky="w", pady=8)

    # Manual price
    tk.Label(frame, text="Precio manual (opcional)", background=COLORS.panel_elevated, foreground=COLORS.text,
             font=(UI_FONT, 10, "bold")).grid(row=5, column=0, sticky="w", pady=4)
    manual_entry = ttk.Entry(frame, textvariable=vars["manual_price"])
    manual_entry.grid(row=5, column=1, sticky="ew", padx=(8, 0), pady=4)

    frame.columnconfigure(1, weight=1)

    def calculate():
        """Calculate price based on form values."""
        try:
            sheets = max(1, int(vars["sheets"].get() or 1))
        except (ValueError, TypeError):
            sheets = 1

        try:
            quantity = max(1, int(vars["quantity"].get() or 1))
        except (ValueError, TypeError):
            quantity = 1

        # Determine size and show warning if beyond limit
        if sheets <= 50:
            size_text = "Chico (1-50 hojas)"
            size_warning = False
        elif sheets <= 150:
            size_text = "Mediano (51-150 hojas)"
            size_warning = False
        elif sheets <= 300:
            size_text = "Grande (151-300 hojas)"
            size_warning = False
        else:
            size_text = "⚠ Supera las 300 hojas (usará precio Grande)"
            size_warning = True

        vars["size_display"].set(size_text)

        if on_size_warning:
            on_size_warning(size_warning, size_text)

        is_urgent = vars["is_urgent"].get()

        try:
            manual_price = float(vars["manual_price"].get() or 0) if vars["manual_price"].get() else None
        except (ValueError, TypeError):
            manual_price = None

        calculation = pricing_service.calculate_anillado(
            sheets=sheets,
            quantity=quantity,
            is_urgent=is_urgent,
            manual_price=manual_price,
        )

        on_calculation_change(calculation)

    # Bind calculation to all inputs
    sheets_entry.bind("<KeyRelease>", lambda e: calculate())
    quantity_entry.bind("<KeyRelease>", lambda e: calculate())
    urgent_check.bind("<Button-1>", lambda e: calculate())
    manual_entry.bind("<KeyRelease>", lambda e: calculate())

    # Initial calculation
    calculate()

    return vars


def create_plastificado_form(
    parent: tk.Widget,
    pricing_service: FotocopiaPricingService,
    on_calculation_change: Callable[[FotocopiaPriceCalculation], None],
    initial_data: dict[str, Any] | None = None,
) -> dict[str, tk.Variable]:
    """Create form for laminating (plastificado).

    Returns dictionary of form variables.
    """
    initial_data = initial_data or {}

    # Form variables
    vars = {
        "quantity": tk.StringVar(value=str(initial_data.get("quantity", 1))),
        "is_urgent": tk.BooleanVar(value=initial_data.get("is_urgent", False)),
        "manual_price": tk.StringVar(value=str(initial_data.get("manual_price", ""))),
    }

    frame = tk.Frame(parent, background=COLORS.panel_elevated)
    frame.pack(fill="x", padx=16, pady=8)

    # Size (fixed A4)
    tk.Label(frame, text="Tamaño", background=COLORS.panel_elevated, foreground=COLORS.text,
             font=(UI_FONT, 10, "bold")).grid(row=0, column=0, sticky="w", pady=4)
    size_label = tk.Label(frame, text="A4", background=COLORS.panel_elevated,
                          foreground=COLORS.text, font=(UI_FONT, 10))
    size_label.grid(row=0, column=1, sticky="w", padx=(8, 0), pady=4)

    # Quantity
    tk.Label(frame, text="Cantidad de unidades", background=COLORS.panel_elevated, foreground=COLORS.text,
             font=(UI_FONT, 10, "bold")).grid(row=1, column=0, sticky="w", pady=4)
    quantity_entry = ttk.Entry(frame, textvariable=vars["quantity"])
    quantity_entry.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=4)

    # Urgent checkbox
    urgent_check = tk.Checkbutton(
        frame, text="Trabajo urgente (+30%)",
        variable=vars["is_urgent"],
        background=COLORS.panel_elevated,
        foreground=COLORS.text,
        font=(UI_FONT, 10),
    )
    urgent_check.grid(row=2, column=0, columnspan=2, sticky="w", pady=8)

    # Manual price
    tk.Label(frame, text="Precio manual (opcional)", background=COLORS.panel_elevated, foreground=COLORS.text,
             font=(UI_FONT, 10, "bold")).grid(row=3, column=0, sticky="w", pady=4)
    manual_entry = ttk.Entry(frame, textvariable=vars["manual_price"])
    manual_entry.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=4)

    frame.columnconfigure(1, weight=1)

    def calculate():
        """Calculate price based on form values."""
        try:
            quantity = max(1, int(vars["quantity"].get() or 1))
        except (ValueError, TypeError):
            quantity = 1

        is_urgent = vars["is_urgent"].get()

        try:
            manual_price = float(vars["manual_price"].get() or 0) if vars["manual_price"].get() else None
        except (ValueError, TypeError):
            manual_price = None

        calculation = pricing_service.calculate_plastificado(
            quantity=quantity,
            is_urgent=is_urgent,
            manual_price=manual_price,
        )

        on_calculation_change(calculation)

    # Bind calculation to all inputs
    quantity_entry.bind("<KeyRelease>", lambda e: calculate())
    urgent_check.bind("<Button-1>", lambda e: calculate())
    manual_entry.bind("<KeyRelease>", lambda e: calculate())

    # Initial calculation
    calculate()

    return vars
