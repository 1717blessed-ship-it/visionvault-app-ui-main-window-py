"""Sistema visual compartido de Doccione Studio.

Este módulo concentra exclusivamente decisiones de presentación.  No conoce
pedidos, imágenes, planchas ni base de datos: los módulos de la aplicación lo
consumen para conservar una interfaz coherente sin alterar su comportamiento.
"""

from __future__ import annotations

from dataclasses import dataclass
from tkinter import ttk


@dataclass(frozen=True)
class Palette:
    background: str = "#0E0E0F"
    background_secondary: str = "#151517"
    panel: str = "#1B1B1E"
    panel_elevated: str = "#222226"
    field: str = "#121214"
    border: str = "#303036"
    border_strong: str = "#4A4A52"
    text: str = "#F2F2F2"
    muted: str = "#B5B5BA"
    disabled: str = "#73737A"
    wine: str = "#6E1730"
    wine_active: str = "#8A1F3D"
    wine_dark: str = "#42101F"
    wine_soft: str = "#2A121A"
    success: str = "#2D9B66"
    warning: str = "#C98A27"
    error: str = "#C94758"
    info: str = "#4E8AC7"
    canvas: str = "#26262A"
    paper: str = "#F6F3ED"


COLORS = Palette()
UI_FONT = "Segoe UI"
IDENTITY_FONT = "Bahnschrift SemiCondensed"


def format_currency(value: float | int | None) -> str:
    """Formatea dinero con formato consistente para toda la UI."""
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def normalize_order_style_key(value: str | None) -> str:
    """Normaliza texto de estado o prioridad para buscar un estilo reutilizable."""
    if value is None:
        return "default"
    text = str(value).strip().casefold()
    if not text:
        return "default"
    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ü": "u",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = text.replace("/", " ").replace("-", " ").replace("_", " ")
    text = " ".join(text.split())
    aliases = {
        "pendiente": "pendiente",
        "pendiente de pago": "pendiente",
        "diseño": "diseño",
        "diseno": "diseño",
        "en diseño": "diseño",
        "sin prisa": "sin prisa",
        "impresion": "impresion",
        "impresion en curso": "impresion",
        "impresion final": "impresion",
        "impresión": "impresion",
        "en impresion": "impresion",
        "sublimado": "sublimado",
        "laminado": "sublimado",
        "corte": "corte",
        "empaque": "empaque",
        "paquete": "empaque",
        "entregado": "entregado",
        "finalizado": "entregado",
        "atrasado": "atrasado",
        "urgente": "urgente",
        "alta": "alta",
        "media": "media",
        "baja": "baja",
    }
    if text in aliases:
        return aliases[text]
    return text if text in {"default", "pendiente", "diseño", "impresion", "sublimado", "corte", "empaque", "entregado", "atrasado", "sin prisa", "baja", "media", "alta", "urgente"} else "default"


ORDER_STATUS_STYLES = {
    "pendiente": {
        "bg": "#4A4A52",
        "fg": "#F2F2F2",
        "accent": COLORS.warning,
    },
    "diseño": {
        "bg": "#6D5B2C",
        "fg": "#F2F2F2",
        "accent": COLORS.warning,
    },
    "impresion": {
        "bg": "#7A4B1C",
        "fg": "#F2F2F2",
        "accent": COLORS.warning,
    },
    "sublimado": {
        "bg": "#6E1730",
        "fg": "#F2F2F2",
        "accent": COLORS.error,
    },
    "corte": {
        "bg": "#5C3C7A",
        "fg": "#F2F2F2",
        "accent": COLORS.info,
    },
    "empaque": {
        "bg": "#214B6E",
        "fg": "#F2F2F2",
        "accent": COLORS.info,
    },
    "entregado": {
        "bg": "#2D9B66",
        "fg": "#F2F2F2",
        "accent": COLORS.success,
    },
    "atrasado": {
        "bg": "#C94758",
        "fg": "#F2F2F2",
        "accent": COLORS.error,
    },
    "default": {
        "bg": "#303036",
        "fg": "#F2F2F2",
        "accent": COLORS.muted,
    },
}

PRIORITY_STYLES = {
    "sin prisa": {
        "bg": "#1B1B1E",
        "fg": "#00BCD4",
        "accent": "#00BCD4",
    },
    "urgente": {
        "bg": "#2A121A",
        "fg": "#d60916",
        "accent": "#d60916",
    },
    "alta": {
        "bg": "#2A1E0E",
        "fg": "#ff6b35",
        "accent": "#ff6b35",
    },
    "media": {
        "bg": "#1E2A38",
        "fg": "#f5a623",
        "accent": "#f5a623",
    },
    "baja": {
        "bg": "#1B1B1E",
        "fg": "#39d353",
        "accent": "#39d353",
    },
    "default": {
        "bg": "#1B1B1E",
        "fg": COLORS.muted,
        "accent": COLORS.muted,
    },
}


def apply_ttk_theme(root) -> ttk.Style:
    """Instala los estilos reutilizables de toda la interfaz."""
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", background=COLORS.background, foreground=COLORS.text, font=(UI_FONT, 10))
    style.configure("TFrame", background=COLORS.background)
    style.configure("TLabel", background=COLORS.background, foreground=COLORS.text)
    style.configure("Title.TLabel", background=COLORS.background, foreground=COLORS.text, font=(IDENTITY_FONT, 30, "bold"))
    style.configure("Module.TLabel", background=COLORS.background, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 10, "bold"))
    style.configure("Tag.TLabel", background=COLORS.background, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 10, "bold"))
    style.configure("Muted.TLabel", background=COLORS.background, foreground=COLORS.muted)
    style.configure("Panel.TFrame", background=COLORS.panel)
    style.configure("Panel.TLabel", background=COLORS.panel, foreground=COLORS.text)
    style.configure("PanelMuted.TLabel", background=COLORS.panel, foreground=COLORS.muted)
    style.configure("Elevated.TFrame", background=COLORS.panel_elevated)
    style.configure("Card.TFrame", background=COLORS.panel, relief="flat", borderwidth=0)
    style.configure("Card.TLabel", background=COLORS.panel, foreground=COLORS.text)

    style.configure("TButton", background=COLORS.panel_elevated, foreground=COLORS.text, bordercolor=COLORS.border,
                    relief="flat", borderwidth=0, padding=(12, 7), font=(UI_FONT, 10, "bold"))
    style.map("TButton", background=[("active", COLORS.border_strong), ("pressed", COLORS.background_secondary)],
              foreground=[("disabled", COLORS.disabled)])
    style.configure("Primary.TButton", background=COLORS.wine, foreground=COLORS.text, bordercolor=COLORS.wine,
                    padding=(13, 7), font=(UI_FONT, 10, "bold"))
    style.map("Primary.TButton", background=[("active", COLORS.wine_active), ("pressed", COLORS.wine_dark)])
    style.configure("Secondary.TButton", background=COLORS.panel_elevated, foreground=COLORS.text, bordercolor=COLORS.border,
                    padding=(12, 7), font=(UI_FONT, 10, "bold"))
    style.map("Secondary.TButton", background=[("active", COLORS.border_strong), ("pressed", COLORS.background_secondary)])
    style.configure("Danger.TButton", background=COLORS.wine_dark, foreground=COLORS.text, bordercolor=COLORS.wine,
                    padding=(12, 7), font=(UI_FONT, 10, "bold"))
    style.map("Danger.TButton", background=[("active", COLORS.wine), ("pressed", "#2B0A14")])

    style.configure("TEntry", fieldbackground=COLORS.field, foreground=COLORS.text, insertcolor=COLORS.text,
                    bordercolor=COLORS.border, lightcolor=COLORS.wine_active, darkcolor=COLORS.border,
                    padding=(8, 6))
    style.map("TEntry", bordercolor=[("focus", COLORS.wine_active)])
    style.configure("TCombobox", fieldbackground=COLORS.field, foreground=COLORS.text, selectforeground=COLORS.text,
                    selectbackground=COLORS.wine_dark, arrowcolor=COLORS.text, bordercolor=COLORS.border,
                    padding=(7, 5))
    style.map("TCombobox", fieldbackground=[("readonly", COLORS.field)], bordercolor=[("focus", COLORS.wine_active)])
    style.configure("TSpinbox", fieldbackground=COLORS.field, foreground=COLORS.text, insertcolor=COLORS.text,
                    arrowcolor=COLORS.text, bordercolor=COLORS.border, padding=(7, 5))

    style.configure("TScrollbar", background=COLORS.panel_elevated, troughcolor=COLORS.background_secondary,
                    arrowcolor=COLORS.muted, bordercolor=COLORS.border)
    style.configure("TNotebook", background=COLORS.background, borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure("TNotebook.Tab", background=COLORS.panel, foreground=COLORS.muted, padding=(14, 8),
                    font=(UI_FONT, 10, "bold"))
    style.map("TNotebook.Tab", background=[("selected", COLORS.wine)], foreground=[("selected", COLORS.text)],
              expand=[("selected", (0, 0, 0, 1))])
    # El navegador lateral es la navegación principal. Este cuaderno conserva
    # la gestión de vistas de Tk sin duplicar pestañas arriba del contenido.
    style.configure("Main.TNotebook", background=COLORS.background, borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.layout("Main.TNotebook.Tab", [])
    style.configure("TSeparator", background=COLORS.border)
    style.configure("TCheckbutton", background=COLORS.panel, foreground=COLORS.text, font=(UI_FONT, 10))

    style.configure("Treeview", background=COLORS.panel, fieldbackground=COLORS.panel, foreground=COLORS.text,
                    rowheight=30, bordercolor=COLORS.border, font=(UI_FONT, 10))
    style.map("Treeview", background=[("selected", COLORS.wine)], foreground=[("selected", COLORS.text)])
    style.configure("Treeview.Heading", background=COLORS.panel_elevated, foreground=COLORS.text,
                    relief="flat", padding=(8, 8), font=(UI_FONT, 10, "bold"))
    style.map("Treeview.Heading", background=[("active", COLORS.border_strong)])
    style.configure("Horizontal.TProgressbar", background=COLORS.wine_active, troughcolor=COLORS.panel_elevated,
                    bordercolor=COLORS.border, lightcolor=COLORS.wine_active, darkcolor=COLORS.wine)
    return style


def configure_window(widget, *, dialog: bool = False) -> None:
    """Da el fondo correcto a ventanas principales y modales Tk puros."""
    widget.configure(background=COLORS.panel if dialog else COLORS.background)


def configure_menu(menu) -> None:
    menu.configure(
        background=COLORS.panel_elevated,
        foreground=COLORS.text,
        activebackground=COLORS.wine,
        activeforeground=COLORS.text,
        borderwidth=1,
        relief="flat",
    )


def configure_plancha_styles(root) -> None:
    """Alias semánticos para que los editores de planchas compartan el tema."""
    style = ttk.Style(root)
    for local, shared in (
        ("Plancha.Primary.TButton", "Primary.TButton"),
        ("Plancha.Secondary.TButton", "Secondary.TButton"),
        ("Plancha.Danger.TButton", "Danger.TButton"),
        ("Template.Primary.TButton", "Primary.TButton"),
        ("Template.Secondary.TButton", "Secondary.TButton"),
    ):
        # ttk no permite herencia explícita entre estilos; se replican solo
        # los valores visuales centrales sin involucrar lógica del editor.
        if shared == "Primary.TButton":
            style.configure(local, background=COLORS.wine, foreground=COLORS.text, bordercolor=COLORS.wine,
                            padding=(12, 7), font=(UI_FONT, 10, "bold"))
            style.map(local, background=[("active", COLORS.wine_active), ("pressed", COLORS.wine_dark)])
        elif shared == "Danger.TButton":
            style.configure(local, background=COLORS.wine_dark, foreground=COLORS.text, bordercolor=COLORS.wine,
                            padding=(11, 7), font=(UI_FONT, 10, "bold"))
            style.map(local, background=[("active", COLORS.wine), ("pressed", "#2B0A14")])
        else:
            style.configure(local, background=COLORS.panel_elevated, foreground=COLORS.text, bordercolor=COLORS.border,
                            padding=(11, 7), font=(UI_FONT, 10, "bold"))
            style.map(local, background=[("active", COLORS.border_strong), ("pressed", COLORS.background_secondary)])

    # Símbolos compactos para las barras de herramientas. El significado se
    # explica con ayuda emergente y no compite visualmente con la plancha.
    for local, background, active, pressed in (
        ("Plancha.Icon.Primary.TButton", COLORS.wine, COLORS.wine_active, COLORS.wine_dark),
        ("Plancha.Icon.Secondary.TButton", COLORS.panel_elevated, COLORS.border_strong, COLORS.background_secondary),
        ("Plancha.Icon.Danger.TButton", COLORS.wine_dark, COLORS.wine, "#2B0A14"),
    ):
        style.configure(local, background=background, foreground=COLORS.text, bordercolor=COLORS.border,
                        padding=(7, 5), font=("Segoe UI Symbol", 12, "bold"))
        style.map(local, background=[("active", active), ("pressed", pressed)], foreground=[("disabled", COLORS.disabled)])
