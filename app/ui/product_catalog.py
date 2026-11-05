"""Catálogo visual y editable de productos de Doccione Studio."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app.ui.theme import COLORS, IDENTITY_FONT, UI_FONT, format_currency

try:
    from PIL import Image, ImageOps, ImageTk

    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False


def parse_price(value: str) -> float:
    """Acepta importes escritos con separadores argentinos o internacionales."""
    cleaned = str(value or "").strip().replace("$", "").replace(" ", "")
    if not cleaned:
        raise ValueError("Ingresá un precio.")
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    amount = float(cleaned)
    if amount < 0:
        raise ValueError("El precio no puede ser negativo.")
    return amount


class ProductCatalog(tk.Frame):
    """Vista de fichas de producto con alta, edición y archivado."""

    CARD_WIDTH = 260
    CARD_HEIGHT = 384
    CARD_GAP = 12

    def __init__(self, parent, database, *, on_status=None):
        super().__init__(parent, background=COLORS.background)
        self.database = database
        self.on_status = on_status
        self.search_var = tk.StringVar()
        self.include_archived_var = tk.BooleanVar(value=False)
        self.count_var = tk.StringVar()
        self._photos: list[object] = []
        self._products: list[dict] = []
        self._column_count = 0
        self._refresh_after = None
        self._editor = None
        self._build()
        self.refresh()

    def _build(self) -> None:
        header = tk.Frame(
            self,
            background=COLORS.panel,
            highlightthickness=1,
            highlightbackground=COLORS.border,
        )
        header.pack(fill="x", padx=10, pady=(10, 10))

        heading = tk.Frame(header, background=COLORS.panel)
        heading.pack(side="left", fill="x", expand=True, padx=16, pady=13)
        tk.Label(
            heading,
            text="PRODUCTOS",
            background=COLORS.panel,
            foreground=COLORS.text,
            font=(IDENTITY_FONT, 21, "bold"),
        ).pack(anchor="w")
        tk.Label(
            heading,
            text="Información, precios e imágenes en un catálogo listo para consultar.",
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 10),
        ).pack(anchor="w", pady=(2, 0))

        ttk.Button(
            header,
            text="+ Nuevo producto",
            style="Primary.TButton",
            command=self.open_editor,
        ).pack(side="right", padx=16, pady=16)

        tools = tk.Frame(self, background=COLORS.background)
        tools.pack(fill="x", padx=10, pady=(0, 10))
        search_holder = tk.Frame(
            tools,
            background=COLORS.panel,
            highlightthickness=1,
            highlightbackground=COLORS.border,
        )
        search_holder.pack(side="left", fill="x", expand=True)
        tk.Label(
            search_holder,
            text="Buscar",
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 9, "bold"),
        ).pack(side="left", padx=(12, 8), pady=9)
        search_entry = ttk.Entry(search_holder, textvariable=self.search_var)
        search_entry.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=7)
        self.search_var.trace_add("write", self._schedule_refresh)

        ttk.Checkbutton(
            tools,
            text="Mostrar archivados",
            variable=self.include_archived_var,
            command=self.refresh,
        ).pack(side="left", padx=(14, 0))
        tk.Label(
            tools,
            textvariable=self.count_var,
            background=COLORS.background,
            foreground=COLORS.muted,
            font=(UI_FONT, 9),
        ).pack(side="right", padx=(14, 4))

        catalog_holder = tk.Frame(
            self,
            background=COLORS.panel,
            highlightthickness=1,
            highlightbackground=COLORS.border,
        )
        catalog_holder.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.canvas = tk.Canvas(
            catalog_holder,
            background=COLORS.background,
            borderwidth=0,
            highlightthickness=0,
        )
        scrollbar = ttk.Scrollbar(catalog_holder, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.cards = tk.Frame(self.canvas, background=COLORS.background)
        self.cards_window = self.canvas.create_window((0, 0), window=self.cards, anchor="nw")
        self.cards.bind(
            "<Configure>",
            lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._bind_mousewheel(self.canvas)
        self._bind_mousewheel(self.cards)

    def _schedule_refresh(self, *_args) -> None:
        if self._refresh_after:
            self.after_cancel(self._refresh_after)
        self._refresh_after = self.after(160, self.refresh)

    def _on_canvas_resize(self, event) -> None:
        width = max(1, int(event.width))
        self.canvas.itemconfigure(self.cards_window, width=width)
        columns = max(1, width // (self.CARD_WIDTH + self.CARD_GAP))
        if columns != self._column_count:
            self._column_count = columns
            self._render_cards()

    def _bind_mousewheel(self, widget) -> None:
        widget.bind(
            "<MouseWheel>",
            lambda event: self.canvas.yview_scroll(int(-event.delta / 120), "units"),
            add="+",
        )

    def refresh(self) -> None:
        self._refresh_after = None
        self._products = self.database.catalog_products(
            self.search_var.get(),
            include_inactive=self.include_archived_var.get(),
        )
        active_count = sum(bool(item.get("active", 1)) for item in self._products)
        suffix = "producto" if len(self._products) == 1 else "productos"
        if self.include_archived_var.get() and active_count != len(self._products):
            archived = len(self._products) - active_count
            self.count_var.set(f"{len(self._products)} {suffix} · {archived} archivados")
        else:
            self.count_var.set(f"{len(self._products)} {suffix}")
        self._render_cards()

    def _render_cards(self) -> None:
        for child in self.cards.winfo_children():
            child.destroy()
        self._photos.clear()
        if not self._products:
            self._render_empty_state()
            return
        columns = max(1, self._column_count)
        for column in range(columns):
            self.cards.grid_columnconfigure(column, weight=1, uniform="products")
        for index, product in enumerate(self._products):
            card = self._build_card(product)
            card.grid(
                row=index // columns,
                column=index % columns,
                sticky="nsew",
                padx=self.CARD_GAP // 2,
                pady=self.CARD_GAP // 2,
            )

    def _render_empty_state(self) -> None:
        empty = tk.Frame(self.cards, background=COLORS.background)
        empty.pack(fill="both", expand=True, padx=30, pady=80)
        title = "No encontramos productos" if self.search_var.get().strip() else "Tu catálogo está listo para empezar"
        detail = (
            "Probá con otra palabra o activá “Mostrar archivados”."
            if self.search_var.get().strip()
            else "Creá la primera ficha con una imagen, información y precio."
        )
        tk.Label(
            empty,
            text=title,
            background=COLORS.background,
            foreground=COLORS.text,
            font=(IDENTITY_FONT, 17, "bold"),
        ).pack()
        tk.Label(
            empty,
            text=detail,
            background=COLORS.background,
            foreground=COLORS.muted,
            font=(UI_FONT, 10),
        ).pack(pady=(6, 14))
        if not self.search_var.get().strip():
            ttk.Button(
                empty,
                text="+ Nuevo producto",
                command=self.open_editor,
                style="Primary.TButton",
            ).pack()

    def _build_card(self, product: dict) -> tk.Frame:
        is_active = bool(product.get("active", 1))
        card = tk.Frame(
            self.cards,
            width=self.CARD_WIDTH,
            height=self.CARD_HEIGHT,
            background=COLORS.panel,
            highlightthickness=1,
            highlightbackground=COLORS.border if is_active else COLORS.wine_dark,
        )
        card.grid_propagate(False)
        card.grid_columnconfigure(0, weight=1)

        image_holder = tk.Frame(
            card,
            height=142,
            background=COLORS.panel_elevated,
        )
        image_holder.grid(row=0, column=0, sticky="ew")
        image_holder.grid_propagate(False)
        # La foto ocupa todo el ancho de la ficha.  El recorte central evita
        # márgenes y mantiene la altura uniforme de todas las tarjetas.
        image_path = product.get("image_path")
        preview = self._load_photo(image_path, (self.CARD_WIDTH, 142), cover=True)
        if preview is not None:
            image_label = tk.Label(
                image_holder,
                image=preview,
                background=COLORS.panel_elevated,
                borderwidth=0,
            )
            self._photos.append(preview)

            def resize_preview(event) -> None:
                """Ajusta la foto al ancho real asignado por la grilla."""
                size = (event.width, event.height)
                if getattr(image_label, "_preview_size", None) == size:
                    return
                resized = self._load_photo(image_path, size, cover=True)
                if resized is not None:
                    image_label.configure(image=resized)
                    image_label.image = resized
                    image_label._preview_size = size

            image_label.bind("<Configure>", resize_preview)
        else:
            image_label = tk.Label(
                image_holder,
                text="IMAGEN\nDEL PRODUCTO",
                background=COLORS.panel_elevated,
                foreground=COLORS.disabled,
                font=(IDENTITY_FONT, 11, "bold"),
                justify="center",
            )
        image_label.pack(fill="both", expand=True)

        body = tk.Frame(card, background=COLORS.panel)
        body.grid(row=1, column=0, sticky="nsew", padx=13, pady=(11, 8))
        body.grid_columnconfigure(0, weight=1)

        category = str(product.get("category") or "SIN CATEGORÍA").upper()
        state_text = "" if is_active else " · ARCHIVADO"
        tk.Label(
            body,
            text=category + state_text,
            background=COLORS.panel,
            foreground=COLORS.wine_active if is_active else COLORS.warning,
            font=(UI_FONT, 8, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        tk.Label(
            body,
            text=str(product.get("name") or "Producto"),
            background=COLORS.panel,
            foreground=COLORS.text,
            font=(IDENTITY_FONT, 14, "bold"),
            anchor="w",
            justify="left",
            wraplength=226,
        ).grid(row=1, column=0, sticky="ew", pady=(4, 2))
        description = str(product.get("description") or "Sin descripción. Podés agregar detalles al editar.")
        tk.Label(
            body,
            text=description,
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 9),
            anchor="nw",
            justify="left",
            wraplength=226,
            height=3,
        ).grid(row=2, column=0, sticky="ew")

        price_row = tk.Frame(body, background=COLORS.panel)
        price_row.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        rule_count = int(product.get("price_rule_count") or 0)
        min_price = product.get("min_price")
        max_price = product.get("max_price")
        if rule_count > 1 and min_price is not None and max_price is not None:
            price_text = (
                f"Desde {format_currency(min_price)}"
                if float(min_price) == float(max_price)
                else f"{format_currency(min_price)} a {format_currency(max_price)}"
            )
        else:
            price_text = format_currency(product.get("price"))
        tk.Label(
            price_row,
            text=price_text,
            background=COLORS.panel,
            foreground=COLORS.text,
            font=(IDENTITY_FONT, 14, "bold"),
        ).pack(side="left")
        if rule_count > 1:
            tk.Label(
                price_row,
                text=f"{rule_count} variantes",
                background=COLORS.panel,
                foreground=COLORS.muted,
                font=(UI_FONT, 8),
            ).pack(side="right", pady=(5, 0))

        # Una ficha representa el producto principal; las reglas de precio son
        # sus variantes (por ejemplo, tamaños). Se resumen acá para que no
        # parezcan productos independientes ni obliguen a abrir la ficha.
        sizes = [size.strip() for size in str(product.get("available_sizes") or "").split(",") if size.strip()]
        variants = tk.Frame(body, background=COLORS.panel_elevated)
        variants.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        variants.grid_columnconfigure(1, weight=1)
        tk.Label(
            variants,
            text="VARIANTES",
            background=COLORS.panel_elevated,
            foreground=COLORS.wine_active,
            font=(UI_FONT, 8, "bold"),
        ).grid(row=0, column=0, sticky="nw", padx=(8, 6), pady=6)
        if sizes:
            shown = sizes[:4]
            extra = f" +{len(sizes) - len(shown)}" if len(sizes) > len(shown) else ""
            variant_text = " · ".join(shown) + extra
        elif rule_count > 1:
            variant_text = "Ver materiales, cantidades y precios"
        else:
            variant_text = "Precio general"
        tk.Label(
            variants,
            text=variant_text,
            background=COLORS.panel_elevated,
            foreground=COLORS.text,
            font=(UI_FONT, 8),
            justify="left",
            anchor="w",
            wraplength=172,
        ).grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=6)

        actions = tk.Frame(card, background=COLORS.panel)
        actions.grid(row=2, column=0, sticky="ew", padx=13, pady=(0, 12))
        actions.grid_columnconfigure(0, weight=1)
        ttk.Button(
            actions,
            text="Ver variantes",
            command=lambda current=product: self.open_price_sheet(current),
            style="Secondary.TButton",
        ).grid(row=0, column=0, sticky="ew")
        ttk.Button(
            actions,
            text="Editar",
            command=lambda current=product: self.open_editor(current),
            style="Secondary.TButton",
        ).grid(row=0, column=1, padx=(7, 0))
        if is_active:
            ttk.Button(
                actions,
                text="Archivar",
                command=lambda current=product: self._archive(current),
                style="Danger.TButton",
                width=8,
            ).grid(row=0, column=2, padx=(7, 0))
        else:
            ttk.Button(
                actions,
                text="Restaurar",
                command=lambda current=product: self._restore(current),
                style="Primary.TButton",
                width=8,
            ).grid(row=0, column=2, padx=(7, 0))

        for widget in (card, image_holder, image_label, body, price_row, actions):
            self._bind_mousewheel(widget)

        # Bind right-click context menu to card
        card.bind("<Button-3>", lambda event, current=product: self._show_context_menu(event, current))
        image_label.bind("<Button-3>", lambda event, current=product: self._show_context_menu(event, current))

        return card

    def _load_photo(self, image_path, size: tuple[int, int], *, cover: bool = False):
        path = Path(str(image_path or ""))
        if not PIL_AVAILABLE or not path.is_file():
            return None
        try:
            with Image.open(path) as source:
                image = source.convert("RGBA")
                if cover:
                    image = ImageOps.fit(
                        image,
                        size,
                        method=Image.Resampling.LANCZOS,
                        centering=(0.5, 0.5),
                    )
                else:
                    image.thumbnail(size, Image.Resampling.LANCZOS)
                return ImageTk.PhotoImage(image)
        except Exception:
            return None

    def open_price_sheet(self, product: dict) -> None:
        """Muestra una ficha comercial con todas las variantes del producto."""
        product_id = int(product["id"])
        sheet = tk.Toplevel(self)
        sheet.title(f"Ficha de precios · {product.get('name') or 'Producto'}")
        sheet.geometry("820x520")
        sheet.minsize(700, 420)
        sheet.configure(background=COLORS.background)
        sheet.transient(self.winfo_toplevel())

        header = tk.Frame(sheet, background=COLORS.panel)
        header.pack(fill="x")
        tk.Label(
            header, text=str(product.get("name") or "Producto").upper(),
            background=COLORS.panel, foreground=COLORS.text,
            font=(IDENTITY_FONT, 18, "bold"),
        ).pack(anchor="w", padx=20, pady=(16, 2))
        description = str(product.get("description") or "Tamaños, cantidades y precios vigentes.")
        tk.Label(
            header, text=description, background=COLORS.panel,
            foreground=COLORS.muted, font=(UI_FONT, 10), wraplength=760,
            justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 16))

        holder = tk.Frame(sheet, background=COLORS.background)
        holder.pack(fill="both", expand=True, padx=18, pady=18)
        columns = ("list", "material", "size", "quantity", "mode", "price")
        tree = ttk.Treeview(holder, columns=columns, show="headings", selectmode="browse")
        for key, title, width, anchor in (
            ("list", "Lista", 155, "w"), ("material", "Material", 190, "w"),
            ("size", "Tamaño", 85, "center"), ("quantity", "Cantidad", 125, "center"),
            ("mode", "Cálculo", 100, "center"), ("price", "Precio", 115, "e"),
        ):
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=70, anchor=anchor)
        scrollbar = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def refresh_prices() -> None:
            tree.delete(*tree.get_children())
            prices = self.database.catalog_product_prices(product_id)
            for rule in prices:
                minimum = max(1, int(rule.get("min_quantity") or 1))
                maximum = rule.get("max_quantity")
                if maximum is None:
                    quantity = f"Desde {minimum}" if minimum > 1 else "1 unidad"
                elif int(maximum) == minimum:
                    quantity = f"{minimum} unidades"
                else:
                    quantity = f"{minimum} a {maximum} unidades"
                mode = {"unitario": "Por unidad", "pack": "Por pack", "fijo": "Precio fijo"}.get(
                    str(rule.get("price_mode") or "fijo").casefold(), "Precio fijo"
                )
                tree.insert("", "end", iid=str(rule["id"]), values=(
                    rule.get("price_list_name") or "Precios generales",
                rule.get("material") or "—", rule.get("size") or "—", quantity,
                    mode, format_currency(rule.get("price")),
                ))
            if not prices:
                tree.insert("", "end", iid="empty", values=("", "Sin precios configurados", "", "", "", ""))

        def get_selected_rule() -> dict | None:
            selected = tree.selection()
            if not selected or selected[0] == "empty":
                return None
            return self.database.price_rule(int(selected[0]))

        def modify_selected_rule() -> None:
            rule = get_selected_rule()
            if not rule:
                return
            editor = tk.Toplevel(sheet)
            editor.title("Modificar precio")
            editor.configure(background=COLORS.background)
            editor.transient(sheet)
            editor.grab_set()
            form = tk.Frame(editor, background=COLORS.background)
            form.pack(fill="both", expand=True, padx=20, pady=20)
            form.columnconfigure(1, weight=1)
            values = {
                "Material": tk.StringVar(value=str(rule.get("material") or "")),
                "Tamano": tk.StringVar(value=str(rule.get("size") or "")),
                "Cantidad minima": tk.StringVar(value=str(max(1, int(rule.get("min_quantity") or 1)))),
                "Precio": tk.StringVar(value=f"{float(rule.get('price') or 0):g}"),
            }
            for row, (label, variable) in enumerate(values.items()):
                tk.Label(form, text=f"{label}:", background=COLORS.background,
                         foreground=COLORS.text, font=(UI_FONT, 10)).grid(row=row, column=0, sticky="w", pady=5)
                ttk.Entry(form, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=5)

            def save() -> None:
                try:
                    minimum = max(1, int(values["Cantidad minima"].get().strip()))
                    price = parse_price(values["Precio"].get())
                except ValueError as exc:
                    messagebox.showerror("Precio", str(exc), parent=editor)
                    return
                self.database.update_price_rule(
                    int(rule["id"]), values["Material"].get(), values["Tamano"].get(), minimum, price,
                    extra_service=str(rule.get("extra_service") or ""),
                    discount_percent=float(rule.get("discount_percent") or 0),
                    price_mode=str(rule.get("price_mode") or "fijo"),
                    pack_quantity=int(rule.get("pack_quantity") or 1),
                    variable_cost_model_id=rule.get("variable_cost_model_id"),
                    image_path=str(rule.get("image_path") or ""), product_id=product_id,
                    price_list_id=rule.get("price_list_id"),
                )
                editor.destroy()
                refresh_prices()
                self.refresh()

            actions = tk.Frame(form, background=COLORS.background)
            actions.grid(row=len(values), column=0, columnspan=2, sticky="e", pady=(16, 0))
            ttk.Button(actions, text="Cancelar", command=editor.destroy, style="Secondary.TButton").pack(side="right")
            ttk.Button(actions, text="Guardar", command=save, style="Primary.TButton").pack(side="right", padx=(0, 7))

        def delete_selected_rule() -> None:
            rule = get_selected_rule()
            if rule and messagebox.askyesno("Eliminar precio", "Eliminar esta regla de precios?", parent=sheet):
                self.database.remove_price_rule(int(rule["id"]))
                refresh_prices()
                self.refresh()

        menu = tk.Menu(sheet, tearoff=False)
        menu.add_command(label="Modificar", command=modify_selected_rule)
        menu.add_command(label="Eliminar", command=delete_selected_rule)

        def show_context_menu(event) -> None:
            row_id = tree.identify_row(event.y)
            if row_id and row_id != "empty":
                tree.selection_set(row_id)
                tree.focus(row_id)
                menu.tk_popup(event.x_root, event.y_root)

        tree.bind("<Button-3>", show_context_menu)
        tree.bind("<Double-1>", lambda _event: modify_selected_rule())
        refresh_prices()

        footer = tk.Frame(sheet, background=COLORS.background)
        footer.pack(fill="x", padx=18, pady=(0, 18))
        ttk.Button(footer, text="Cerrar", command=sheet.destroy, style="Secondary.TButton").pack(side="right")

    def open_editor(self, product: dict | None = None) -> None:
        if self._editor is not None and self._editor.winfo_exists():
            self._editor.lift()
            self._editor.focus_force()
            return
        editor = tk.Toplevel(self)
        self._editor = editor
        editor.title("Nuevo producto" if product is None else f"Editar {product.get('name', 'producto')}")
        editor.configure(background=COLORS.background)
        editor.geometry("760x560")
        editor.minsize(680, 520)
        editor.transient(self.winfo_toplevel())
        editor.grab_set()
        editor.protocol("WM_DELETE_WINDOW", self._close_editor)

        name_var = tk.StringVar(value=str(product.get("name") or "") if product else "")
        category_var = tk.StringVar(value=str(product.get("category") or "") if product else "")
        price_value = product.get("base_price") if product and product.get("base_price") is not None else product.get("price") if product else ""
        price_var = tk.StringVar(value=f"{float(price_value):g}" if price_value not in {"", None} else "")
        image_var = tk.StringVar(value=str(product.get("image_path") or "") if product else "")

        header = tk.Frame(editor, background=COLORS.panel)
        header.pack(fill="x")
        tk.Label(
            header,
            text="NUEVO PRODUCTO" if product is None else "EDITAR PRODUCTO",
            background=COLORS.panel,
            foreground=COLORS.text,
            font=(IDENTITY_FONT, 18, "bold"),
        ).pack(anchor="w", padx=20, pady=(16, 2))
        tk.Label(
            header,
            text="Completá la información que querés mostrar en la ficha.",
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 9),
        ).pack(anchor="w", padx=20, pady=(0, 15))

        content = tk.Frame(editor, background=COLORS.background)
        content.pack(fill="both", expand=True, padx=20, pady=18)
        content.grid_columnconfigure(1, weight=1)
        content.grid_rowconfigure(0, weight=1)

        image_column = tk.Frame(content, width=245, background=COLORS.panel)
        image_column.grid(row=0, column=0, sticky="ns", padx=(0, 18))
        image_column.grid_propagate(False)
        tk.Label(
            image_column,
            text="IMAGEN",
            background=COLORS.panel,
            foreground=COLORS.wine_active,
            font=(UI_FONT, 9, "bold"),
        ).pack(anchor="w", padx=12, pady=(13, 7))
        preview_holder = tk.Frame(
            image_column,
            width=221,
            height=210,
            background=COLORS.panel_elevated,
        )
        preview_holder.pack(padx=12)
        preview_holder.pack_propagate(False)
        preview_label = tk.Label(
            preview_holder,
            text="Elegí una foto\npara la ficha",
            background=COLORS.panel_elevated,
            foreground=COLORS.disabled,
            font=(UI_FONT, 10),
            justify="center",
        )
        preview_label.pack(fill="both", expand=True)

        def refresh_preview(*_args) -> None:
            photo = self._load_photo(image_var.get(), (211, 200))
            if photo is None:
                preview_label.configure(image="", text="Elegí una foto\npara la ficha")
                preview_label.image = None
            else:
                preview_label.configure(image=photo, text="")
                preview_label.image = photo

        def choose_image() -> None:
            selected = filedialog.askopenfilename(
                parent=editor,
                title="Elegir imagen del producto",
                filetypes=[
                    ("Imágenes", "*.png *.jpg *.jpeg *.webp *.gif *.bmp"),
                    ("Todos los archivos", "*.*"),
                ],
            )
            if selected:
                image_var.set(selected)

        ttk.Button(
            image_column,
            text="Elegir imagen",
            command=choose_image,
            style="Secondary.TButton",
        ).pack(fill="x", padx=12, pady=(12, 6))
        ttk.Button(
            image_column,
            text="Quitar imagen",
            command=lambda: image_var.set(""),
            style="Secondary.TButton",
        ).pack(fill="x", padx=12)
        tk.Label(
            image_column,
            textvariable=image_var,
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 8),
            wraplength=210,
            justify="left",
        ).pack(anchor="w", padx=12, pady=(12, 0))
        image_var.trace_add("write", refresh_preview)

        form = tk.Frame(content, background=COLORS.background)
        form.grid(row=0, column=1, sticky="nsew")
        form.grid_columnconfigure(0, weight=1)

        def field_label(text: str, row: int) -> None:
            tk.Label(
                form,
                text=text,
                background=COLORS.background,
                foreground=COLORS.text,
                font=(UI_FONT, 9, "bold"),
            ).grid(row=row, column=0, sticky="w", pady=(0 if row == 0 else 10, 4))

        field_label("Nombre del producto *", 0)
        name_entry = ttk.Entry(form, textvariable=name_var)
        name_entry.grid(row=1, column=0, sticky="ew")
        field_label("Categoría", 2)
        ttk.Entry(form, textvariable=category_var).grid(row=3, column=0, sticky="ew")
        field_label("Precio de venta *", 4)
        price_holder = tk.Frame(form, background=COLORS.background)
        price_holder.grid(row=5, column=0, sticky="ew")
        tk.Label(
            price_holder,
            text="$",
            background=COLORS.field,
            foreground=COLORS.muted,
            font=(UI_FONT, 11, "bold"),
            padx=9,
            pady=5,
        ).pack(side="left")
        ttk.Entry(price_holder, textvariable=price_var).pack(side="left", fill="x", expand=True)
        field_label("Descripción", 6)
        description_text = tk.Text(
            form,
            height=7,
            background=COLORS.field,
            foreground=COLORS.text,
            insertbackground=COLORS.text,
            selectbackground=COLORS.wine,
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLORS.border,
            highlightcolor=COLORS.wine_active,
            wrap="word",
            font=(UI_FONT, 10),
            padx=8,
            pady=7,
        )
        description_text.grid(row=7, column=0, sticky="nsew")
        description_text.insert("1.0", str(product.get("description") or "") if product else "")

        footer = tk.Frame(editor, background=COLORS.panel)
        footer.pack(fill="x")

        def save() -> None:
            try:
                name = name_var.get().strip()
                if not name:
                    raise ValueError("Ingresá el nombre del producto.")
                price = parse_price(price_var.get())
                image_path = image_var.get().strip()
                if image_path and not Path(image_path).is_file():
                    raise ValueError("La imagen elegida ya no está disponible.")
                payload = {
                    "name": name,
                    "price": price,
                    "description": description_text.get("1.0", "end-1c").strip(),
                    "category": category_var.get().strip(),
                    "image_path": image_path,
                }
                if product is None:
                    self.database.save_catalog_product(**payload)
                    message = f"Producto “{name}” agregado."
                else:
                    if not self.database.update_catalog_product(int(product["id"]), **payload):
                        raise ValueError("El producto ya no existe.")
                    message = f"Producto “{name}” actualizado."
            except (TypeError, ValueError) as error:
                messagebox.showerror("Revisá la ficha", str(error), parent=editor)
                return
            except Exception as error:
                messagebox.showerror(
                    "No se pudo guardar",
                    f"Ocurrió un problema al guardar el producto:\n{error}",
                    parent=editor,
                )
                return
            self._close_editor()
            self.refresh()
            self._set_status(message)

        ttk.Button(
            footer,
            text="Cancelar",
            command=self._close_editor,
            style="Secondary.TButton",
        ).pack(side="right", padx=(8, 20), pady=13)
        ttk.Button(
            footer,
            text="Guardar producto",
            command=save,
            style="Primary.TButton",
        ).pack(side="right", pady=13)
        editor.bind("<Control-Return>", lambda _event: save())
        refresh_preview()
        name_entry.focus_set()

    def _close_editor(self) -> None:
        if self._editor is not None and self._editor.winfo_exists():
            self._editor.grab_release()
            self._editor.destroy()
        self._editor = None

    def _archive(self, product: dict) -> None:
        if not messagebox.askyesno(
            "Archivar producto",
            f"¿Archivar “{product.get('name', 'este producto')}”?\n\n"
            "No se borrarán sus precios ni el historial de pedidos.",
            parent=self.winfo_toplevel(),
        ):
            return
        self.database.set_catalog_product_active(int(product["id"]), False)
        self.refresh()
        self._set_status(f"Producto “{product.get('name', '')}” archivado.")

    def _restore(self, product: dict) -> None:
        self.database.set_catalog_product_active(int(product["id"]), True)
        self.refresh()
        self._set_status(f"Producto “{product.get('name', '')}” restaurado.")

    def _show_context_menu(self, event, product: dict) -> None:
        """Muestra un menú contextual al hacer clic derecho en un producto."""
        is_active = bool(product.get("active", 1))

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label="Editar",
            command=lambda: self.open_editor(product)
        )

        if is_active:
            menu.add_command(
                label="Archivar",
                command=lambda: self._archive(product)
            )
        else:
            menu.add_command(
                label="Restaurar",
                command=lambda: self._restore(product)
            )

        menu.add_separator()
        menu.add_command(
            label="Eliminar permanentemente",
            command=lambda: self._delete_product(product)
        )

        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()

    def _delete_product(self, product: dict) -> None:
        """Elimina permanentemente un producto después de confirmación."""
        if not messagebox.askyesno(
            "Eliminar producto",
            f"¿Eliminar permanentemente \"{product.get('name', 'este producto')}\"?\n\n"
            "Esta acción no se puede deshacer. Se borrarán todos los precios asociados.",
            parent=self.winfo_toplevel(),
            icon="warning",
        ):
            return

        try:
            if not self.database.delete_catalog_product(int(product["id"])):
                raise ValueError("El producto ya no existe.")
            self.refresh()
            self._set_status(f"Producto \"{product.get('name', '')}\" eliminado.")
        except Exception as error:
            messagebox.showerror(
                "Error al eliminar",
                f"No se pudo eliminar el producto:\n{error}",
                parent=self.winfo_toplevel(),
            )

    def _set_status(self, message: str) -> None:
        if callable(self.on_status):
            self.on_status(message)
