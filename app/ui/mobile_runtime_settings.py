"""Panel de Studio para administrar la configuración remota de la app móvil."""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk
from typing import Callable

from app.services.mobile_runtime_config_service import (
    DEFAULT_FEATURES,
    DEFAULT_MATERIALS,
    DEFAULT_ORDER_STATUSES,
    DEFAULT_PAYMENT_METHODS,
    DEFAULT_STICKER_MODES,
    RUNTIME_PREFIX,
)
from app.ui.theme import COLORS, IDENTITY_FONT, UI_FONT


class MobileRuntimeSettingsPanel(ttk.Frame):
    """Editor compacto de las opciones que Flutter consume desde capabilities."""

    def __init__(
        self,
        parent,
        *,
        database,
        status_callback: Callable[[str], None] | None = None,
    ):
        super().__init__(parent)
        self.database = database
        self.status_callback = status_callback or (lambda _message: None)
        self._features = {
            key: tk.BooleanVar(value=self._bool(f"feature.{key}", default))
            for key, default in DEFAULT_FEATURES.items()
        }
        self._announcement_enabled = tk.BooleanVar(
            value=self._bool("announcement.enabled", False)
        )
        self._maintenance_enabled = tk.BooleanVar(
            value=self._bool("maintenance.enabled", False)
        )
        self._announcement_title = tk.StringVar(
            value=self._get("announcement.title", "")
        )
        self._minimum_version = tk.StringVar(
            value=self._get("minimum_app_version", "1.0.0")
        )
        self._recommended_version = tk.StringVar(
            value=self._get("recommended_app_version", "1.0.2")
        )
        self._update_url = tk.StringVar(value=self._get("update_url", ""))
        self._catalog_page_size = tk.StringVar(
            value=self._get("catalog_page_size", "100")
        )
        self._notification_prefix = tk.StringVar(
            value=self._get("notification.title_prefix", "")
        )
        self._build()

    def _build(self) -> None:
        canvas = tk.Canvas(self, background=COLORS.panel, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, background=COLORS.panel)
        window = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        body.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(window, width=event.width),
        )
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        tk.Label(
            body,
            text="CONTROL REMOTO DE LA APP",
            background=COLORS.panel,
            foreground=COLORS.wine_active,
            font=(IDENTITY_FONT, 11, "bold"),
        ).pack(anchor="w", padx=16, pady=(16, 4))
        tk.Label(
            body,
            text=(
                "Los cambios se publican desde Studio. Las versiones nuevas los "
                "aplican al abrir; el APK actual conserva compatibilidad."
            ),
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 9),
            wraplength=650,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 12))

        self._section_label(body, "Funciones habilitadas")
        feature_labels = {
            "design_catalog": "Catálogo de diseños",
            "product_catalog": "Productos y precios",
            "sticker_orders": "Pedidos de stickers",
            "quick_edits": "Edición rápida de pedidos",
            "payments": "Registro de cobros",
            "push_notifications": "Notificaciones push",
        }
        feature_grid = tk.Frame(body, background=COLORS.panel)
        feature_grid.pack(fill="x", padx=16)
        for index, (key, label) in enumerate(feature_labels.items()):
            ttk.Checkbutton(
                feature_grid, text=label, variable=self._features[key]
            ).grid(row=index // 2, column=index % 2, sticky="w", padx=(0, 24), pady=3)

        self._section_label(body, "Avisos y mantenimiento")
        ttk.Checkbutton(
            body,
            text="Mostrar anuncio",
            variable=self._announcement_enabled,
        ).pack(anchor="w", padx=16)
        self._entry(body, "Título del anuncio", self._announcement_title)
        self._announcement_message = self._text(
            body,
            "Mensaje del anuncio",
            self._get("announcement.message", ""),
            height=3,
        )
        ttk.Checkbutton(
            body,
            text="Modo mantenimiento (conserva consultas y sincronización)",
            variable=self._maintenance_enabled,
        ).pack(anchor="w", padx=16, pady=(8, 0))
        self._maintenance_message = self._text(
            body,
            "Mensaje de mantenimiento",
            self._get(
                "maintenance.message",
                "Studio está en mantenimiento. Las operaciones pueden estar limitadas.",
            ),
            height=3,
        )

        self._section_label(body, "Compatibilidad")
        versions = tk.Frame(body, background=COLORS.panel)
        versions.pack(fill="x", padx=16)
        self._grid_entry(versions, 0, "Versión mínima", self._minimum_version)
        self._grid_entry(
            versions, 1, "Versión recomendada", self._recommended_version
        )
        self._entry(body, "URL de actualización", self._update_url)

        self._section_label(body, "Opciones comerciales")
        self._materials = self._text(
            body,
            "Materiales (uno por línea)",
            self._list_text("materials", DEFAULT_MATERIALS),
            height=4,
        )
        self._payment_methods = self._text(
            body,
            "Medios de pago (uno por línea)",
            self._list_text("payment_methods", DEFAULT_PAYMENT_METHODS),
            height=4,
        )
        self._sticker_modes = self._text(
            body,
            "Formatos de stickers (uno por línea)",
            self._list_text("sticker_modes", DEFAULT_STICKER_MODES),
            height=4,
        )
        self._order_statuses = self._text(
            body,
            "Estados editables (uno por línea)",
            self._list_text("order_statuses", DEFAULT_ORDER_STATUSES),
            height=4,
        )

        self._section_label(body, "Rendimiento y notificaciones")
        self._entry(
            body,
            "Diseños cargados por página (20–250)",
            self._catalog_page_size,
        )
        self._entry(
            body,
            "Prefijo opcional para títulos push",
            self._notification_prefix,
        )
        self._notification_suffix = self._text(
            body,
            "Pie opcional para mensajes push",
            self._get("notification.message_suffix", ""),
            height=2,
        )

        ttk.Button(
            body,
            text="Guardar y publicar configuración",
            command=self._save,
            style="Primary.TButton",
        ).pack(fill="x", padx=16, pady=18)

    def _save(self) -> None:
        try:
            page_size = min(500, max(20, int(self._catalog_page_size.get())))
        except ValueError:
            page_size = 100
            self._catalog_page_size.set("100")
        values = {
            **{
                f"feature.{key}": "true" if variable.get() else "false"
                for key, variable in self._features.items()
            },
            "announcement.enabled": self._boolean(self._announcement_enabled),
            "announcement.title": self._announcement_title.get().strip(),
            "announcement.message": self._content(self._announcement_message),
            "maintenance.enabled": self._boolean(self._maintenance_enabled),
            "maintenance.message": self._content(self._maintenance_message),
            "minimum_app_version": self._minimum_version.get().strip(),
            "recommended_app_version": self._recommended_version.get().strip(),
            "update_url": self._update_url.get().strip(),
            "catalog_page_size": str(page_size),
            "notification.title_prefix": self._notification_prefix.get().strip(),
            "notification.message_suffix": self._content(
                self._notification_suffix
            ),
            "materials": self._json_lines(self._materials),
            "payment_methods": self._json_lines(self._payment_methods),
            "sticker_modes": self._json_lines(self._sticker_modes),
            "order_statuses": self._json_lines(self._order_statuses),
        }
        for key, value in values.items():
            self.database.save_app_setting(f"{RUNTIME_PREFIX}{key}", value)
        self.status_callback("Configuración móvil publicada.")

    def _get(self, key: str, default: str) -> str:
        return self.database.app_setting(f"{RUNTIME_PREFIX}{key}", default)

    def _bool(self, key: str, default: bool) -> bool:
        raw = self._get(key, "true" if default else "false")
        return raw.strip().casefold() in {"1", "true", "yes", "si", "sí", "on"}

    def _list_text(self, key: str, default: tuple[str, ...]) -> str:
        raw = self._get(key, "")
        if not raw:
            return "\n".join(default)
        try:
            decoded = json.loads(raw)
            if isinstance(decoded, list):
                return "\n".join(str(item) for item in decoded)
        except json.JSONDecodeError:
            pass
        return raw

    @staticmethod
    def _section_label(parent, text: str) -> None:
        ttk.Separator(parent, orient="horizontal").pack(
            fill="x", padx=16, pady=(14, 10)
        )
        tk.Label(
            parent,
            text=text.upper(),
            background=COLORS.panel,
            foreground=COLORS.wine_active,
            font=(IDENTITY_FONT, 9, "bold"),
        ).pack(anchor="w", padx=16, pady=(0, 6))

    @staticmethod
    def _entry(parent, label: str, variable: tk.StringVar) -> None:
        frame = tk.Frame(parent, background=COLORS.panel)
        frame.pack(fill="x", padx=16, pady=4)
        tk.Label(
            frame,
            text=label,
            width=34,
            anchor="w",
            background=COLORS.panel,
            foreground=COLORS.text,
            font=(UI_FONT, 9),
        ).pack(side="left")
        ttk.Entry(frame, textvariable=variable).pack(
            side="left", fill="x", expand=True
        )

    @staticmethod
    def _grid_entry(
        parent, column: int, label: str, variable: tk.StringVar
    ) -> None:
        frame = tk.Frame(parent, background=COLORS.panel)
        frame.grid(row=0, column=column, sticky="ew", padx=(0, 12), pady=4)
        parent.grid_columnconfigure(column, weight=1)
        tk.Label(
            frame,
            text=label,
            background=COLORS.panel,
            foreground=COLORS.text,
            font=(UI_FONT, 9),
        ).pack(anchor="w")
        ttk.Entry(frame, textvariable=variable).pack(fill="x")

    @staticmethod
    def _text(parent, label: str, value: str, *, height: int) -> tk.Text:
        frame = tk.Frame(parent, background=COLORS.panel)
        frame.pack(fill="x", padx=16, pady=4)
        tk.Label(
            frame,
            text=label,
            background=COLORS.panel,
            foreground=COLORS.text,
            font=(UI_FONT, 9),
        ).pack(anchor="w", pady=(0, 3))
        widget = tk.Text(
            frame,
            height=height,
            wrap="word",
            background=COLORS.background_secondary,
            foreground=COLORS.text,
            insertbackground=COLORS.text,
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLORS.border,
        )
        widget.insert("1.0", value)
        widget.pack(fill="x")
        return widget

    @staticmethod
    def _content(widget: tk.Text) -> str:
        return widget.get("1.0", "end-1c").strip()

    @classmethod
    def _json_lines(cls, widget: tk.Text) -> str:
        values = []
        seen = set()
        for raw in cls._content(widget).splitlines():
            clean = raw.strip()
            folded = clean.casefold()
            if clean and folded not in seen:
                seen.add(folded)
                values.append(clean)
        return json.dumps(values, ensure_ascii=False)

    @staticmethod
    def _boolean(variable: tk.BooleanVar) -> str:
        return "true" if variable.get() else "false"
