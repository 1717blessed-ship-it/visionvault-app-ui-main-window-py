"""Centro de ventas: CRM, cotizaciones, cobranzas y posventa."""

from __future__ import annotations

import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from app.sales.repository import DELIVERY_STATUSES, LEAD_STAGES, QUOTE_STATUSES, SellerRepository
from app.ui.theme import COLORS, IDENTITY_FONT, UI_FONT, format_currency


class SellerCenter(tk.Frame):
    """Área de trabajo integral para quien vende y hace seguimiento."""

    def __init__(
        self, parent: tk.Widget, database, *, on_open_order: Callable[[int], None] | None = None,
        on_register_payment: Callable[[int], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ):
        super().__init__(parent, background=COLORS.background)
        self.database = database
        self.repository = SellerRepository(database.connection)
        self.on_open_order = on_open_order or (lambda _order_id: None)
        self.on_register_payment = on_register_payment or (lambda _order_id: None)
        self.on_status = on_status or (lambda _message: None)
        self._build()
        self.refresh_all()

    # ---------------------------------------------------------------- Layout
    def _build(self) -> None:
        header = tk.Frame(self, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        header.pack(fill="x", padx=10, pady=(10, 0))
        copy = tk.Frame(header, background=COLORS.panel)
        copy.pack(side="left", fill="x", expand=True, padx=16, pady=12)
        tk.Label(copy, text="CENTRO DE VENTAS", background=COLORS.panel, foreground=COLORS.text,
                 font=(IDENTITY_FONT, 20, "bold")).pack(anchor="w")
        tk.Label(copy, text="Consultas, presupuestos, cobros, entregas y clientes en un solo recorrido.",
                 background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 10)).pack(anchor="w", pady=(2, 0))
        ttk.Button(header, text="Actualizar", command=self.refresh_all, style="Secondary.TButton").pack(side="right", padx=16, pady=14)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)
        self.dashboard_tab = ttk.Frame(self.notebook)
        self.pipeline_tab = ttk.Frame(self.notebook)
        self.quotes_tab = ttk.Frame(self.notebook)
        self.receivables_tab = ttk.Frame(self.notebook)
        self.deliveries_tab = ttk.Frame(self.notebook)
        self.customers_tab = ttk.Frame(self.notebook)
        self.catalog_tab = ttk.Frame(self.notebook)
        self.policies_tab = ttk.Frame(self.notebook)
        for tab, label in (
            (self.dashboard_tab, "Panel"), (self.pipeline_tab, "Oportunidades"),
            (self.quotes_tab, "Presupuestos"), (self.receivables_tab, "Cobranzas"),
            (self.deliveries_tab, "Entregas"), (self.customers_tab, "Fidelización"),
            (self.catalog_tab, "Catálogo compartible"), (self.policies_tab, "Reglas comerciales"),
        ):
            self.notebook.add(tab, text=f"  {label}  ")
        self._build_dashboard()
        self._build_pipeline()
        self._build_quotes()
        self._build_receivables()
        self._build_deliveries()
        self._build_customers()
        self._build_catalog()
        self._build_policies()
        self.notebook.bind("<<NotebookTabChanged>>", lambda _event: self.refresh_current())

    def _section_header(self, parent: tk.Widget, title: str, subtitle: str) -> tk.Frame:
        frame = tk.Frame(parent, background=COLORS.panel)
        frame.pack(fill="x", padx=14, pady=(14, 8))
        left = tk.Frame(frame, background=COLORS.panel)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=title, background=COLORS.panel, foreground=COLORS.text,
                 font=(IDENTITY_FONT, 16, "bold")).pack(anchor="w")
        tk.Label(left, text=subtitle, background=COLORS.panel, foreground=COLORS.muted,
                 font=(UI_FONT, 9)).pack(anchor="w", pady=(2, 0))
        return frame

    @staticmethod
    def _tree(parent: tk.Widget, columns: tuple[tuple[str, str, int, str], ...], *, height: int = 14) -> ttk.Treeview:
        holder = ttk.Frame(parent)
        holder.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        tree = ttk.Treeview(holder, columns=[item[0] for item in columns], show="headings", height=height, selectmode="browse")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        for key, label, width, anchor in columns:
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor=anchor, stretch=key not in {"id", "status", "quantity"})
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return tree

    @staticmethod
    def _selected_id(tree: ttk.Treeview) -> int | None:
        selected = tree.selection()
        if not selected:
            return None
        try:
            return int(tree.item(selected[0], "values")[0])
        except (TypeError, ValueError, IndexError):
            return None

    def _copy(self, text: str, message: str = "Texto copiado para WhatsApp.") -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        self.on_status(message)

    def _money(self, value: Any) -> str:
        return format_currency(float(value or 0))

    # --------------------------------------------------------------- Panel
    def _build_dashboard(self) -> None:
        header = self._section_header(self.dashboard_tab, "PANEL COMERCIAL", "La situación de ventas y las próximas acciones, sin mezclarla con producción.")
        ttk.Button(header, text="+ Nueva oportunidad", command=self.open_lead_editor, style="Primary.TButton").pack(side="right")
        cards = tk.Frame(self.dashboard_tab, background=COLORS.panel)
        cards.pack(fill="x", padx=14, pady=(0, 10))
        self.metric_vars: dict[str, tk.StringVar] = {}
        specs = (
            ("Ventas", "sales", COLORS.success), ("Cobrado", "collected", COLORS.info),
            ("A cobrar", "outstanding", COLORS.warning), ("Ticket promedio", "average_ticket", COLORS.text),
            ("Conversión oportunidades", "lead_conversion", COLORS.wine_active),
            ("Conversión presupuestos", "quote_conversion", COLORS.wine_active),
            ("Tareas vencidas/hoy", "tasks_due", COLORS.error), ("Clientes recurrentes", "repeat_customers", COLORS.text),
        )
        for column in range(4): cards.grid_columnconfigure(column, weight=1)
        for index, (label, key, color) in enumerate(specs):
            card = tk.Frame(cards, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
            card.grid(row=index // 4, column=index % 4, sticky="nsew", padx=4, pady=4)
            tk.Label(card, text=label.upper(), background=COLORS.panel_elevated, foreground=COLORS.muted,
                     font=(UI_FONT, 8, "bold")).pack(anchor="w", padx=12, pady=(10, 3))
            var = tk.StringVar(value="—")
            self.metric_vars[key] = var
            tk.Label(card, textvariable=var, background=COLORS.panel_elevated, foreground=color,
                     font=(IDENTITY_FONT, 15, "bold")).pack(anchor="w", padx=12, pady=(0, 10))

        body = tk.PanedWindow(self.dashboard_tab, orient="horizontal", background=COLORS.panel, sashwidth=5)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        tasks = tk.Frame(body, background=COLORS.panel_elevated)
        products = tk.Frame(body, background=COLORS.panel_elevated)
        body.add(tasks, minsize=520, stretch="always"); body.add(products, minsize=330, stretch="always")
        tk.Label(tasks, text="PRÓXIMAS ACCIONES", background=COLORS.panel_elevated, foreground=COLORS.text,
                 font=(IDENTITY_FONT, 12, "bold")).pack(anchor="w", padx=12, pady=(10, 6))
        self.tasks_tree = self._tree(tasks, (
            ("id", "ID", 45, "center"), ("due", "Cuándo", 130, "center"),
            ("client", "Cliente", 150, "w"), ("kind", "Tipo", 95, "center"), ("title", "Acción", 230, "w"),
        ), height=8)
        actions = ttk.Frame(tasks); actions.pack(fill="x", padx=12, pady=(0, 10))
        ttk.Button(actions, text="Completar", command=self.complete_selected_task, style="Primary.TButton").pack(side="left")
        ttk.Button(actions, text="Copiar mensaje", command=self.copy_selected_task_message).pack(side="left", padx=7)
        tk.Label(products, text="PRODUCTOS MÁS VENDIDOS", background=COLORS.panel_elevated, foreground=COLORS.text,
                 font=(IDENTITY_FONT, 12, "bold")).pack(anchor="w", padx=12, pady=(10, 6))
        self.top_products_tree = self._tree(products, (
            ("product", "Producto", 200, "w"), ("quantity", "Unidades", 80, "center"), ("sales", "Ventas", 110, "e"),
        ), height=8)

    def refresh_dashboard(self) -> None:
        metrics = self.repository.dashboard_metrics()
        for key, var in self.metric_vars.items():
            value = metrics.get(key, 0)
            var.set(f"{value:.1f}%" if key.endswith("conversion") else (self._money(value) if key in {"sales", "collected", "outstanding", "average_ticket"} else str(value)))
        self.tasks_tree.delete(*self.tasks_tree.get_children())
        for task in self.repository.tasks(limit=50):
            self.tasks_tree.insert("", "end", iid=str(task["id"]), values=(task["id"], str(task["due_at"]).replace("T", " ")[:16], task["client_name"], task["kind"], task["title"]))
        self.top_products_tree.delete(*self.top_products_tree.get_children())
        for item in self.repository.top_products():
            self.top_products_tree.insert("", "end", values=(item["product"], item["quantity"], self._money(item["sales"])))

    def complete_selected_task(self) -> None:
        task_id = self._selected_id(self.tasks_tree)
        if task_id:
            self.repository.complete_task(task_id); self.refresh_dashboard(); self.on_status("Seguimiento completado.")

    def copy_selected_task_message(self) -> None:
        task_id = self._selected_id(self.tasks_tree)
        task = next((item for item in self.repository.tasks(limit=500) if int(item["id"]) == task_id), None)
        if task:
            self._copy(task.get("message_template") or task["title"])

    # --------------------------------------------------------- Oportunidades
    def _build_pipeline(self) -> None:
        header = self._section_header(self.pipeline_tab, "OPORTUNIDADES", "Registrá cada consulta antes de que sea pedido y definí siempre el próximo paso.")
        ttk.Button(header, text="+ Nueva oportunidad", command=self.open_lead_editor, style="Primary.TButton").pack(side="right")
        filters = ttk.Frame(self.pipeline_tab); filters.pack(fill="x", padx=14, pady=(0, 8))
        self.lead_stage_var = tk.StringVar(value="Todas")
        self.lead_query_var = tk.StringVar()
        ttk.Label(filters, text="Estado").pack(side="left")
        combo = ttk.Combobox(filters, textvariable=self.lead_stage_var, values=("Todas",) + LEAD_STAGES, state="readonly", width=16)
        combo.pack(side="left", padx=(6, 14)); combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_leads())
        ttk.Entry(filters, textvariable=self.lead_query_var, width=32).pack(side="left")
        ttk.Button(filters, text="Buscar", command=self.refresh_leads).pack(side="left", padx=6)
        self.leads_tree = self._tree(self.pipeline_tab, (
            ("id", "ID", 45, "center"), ("client", "Contacto", 180, "w"), ("whatsapp", "WhatsApp", 120, "w"),
            ("source", "Origen", 100, "center"), ("stage", "Estado", 115, "center"), ("probability", "Prob.", 65, "center"),
            ("value", "Valor estimado", 110, "e"), ("next", "Próxima acción", 230, "w"), ("when", "Fecha", 130, "center"),
        ))
        self.leads_tree.bind("<Double-1>", lambda _event: self.edit_selected_lead())
        actions = ttk.Frame(self.pipeline_tab); actions.pack(fill="x", padx=14, pady=(0, 14))
        ttk.Button(actions, text="Editar", command=self.edit_selected_lead).pack(side="left")
        ttk.Button(actions, text="Crear presupuesto", command=self.create_quote_from_selected_lead, style="Primary.TButton").pack(side="left", padx=7)
        ttk.Button(actions, text="Copiar seguimiento", command=self.copy_lead_followup).pack(side="left")

    def refresh_leads(self) -> None:
        self.leads_tree.delete(*self.leads_tree.get_children())
        for lead in self.repository.leads(stage=self.lead_stage_var.get(), query=self.lead_query_var.get()):
            self.leads_tree.insert("", "end", iid=str(lead["id"]), values=(
                lead["id"], lead["client_name"], lead["whatsapp"], lead["source"], lead["stage"], f"{lead['probability']}%",
                self._money(lead["expected_value"]), lead["next_action"], str(lead["next_action_at"]).replace("T", " ")[:16],
            ))

    def open_lead_editor(self, lead_id: int | None = None) -> None:
        lead = self.repository.lead(lead_id) if lead_id else {}
        dialog = tk.Toplevel(self); dialog.title("Editar oportunidad" if lead_id else "Nueva oportunidad")
        dialog.configure(background=COLORS.background); dialog.transient(self); dialog.grab_set(); dialog.resizable(False, False)
        form = ttk.Frame(dialog, padding=18); form.pack(fill="both", expand=True)
        values = {
            "client_name": tk.StringVar(value=lead.get("client_name", "")), "whatsapp": tk.StringVar(value=lead.get("whatsapp", "")),
            "source": tk.StringVar(value=lead.get("source", "WhatsApp")), "stage": tk.StringVar(value=lead.get("stage", "Nueva")),
            "probability": tk.StringVar(value=str(lead.get("probability", 20))), "expected_value": tk.StringVar(value=str(lead.get("expected_value", 0))),
            "assigned_to": tk.StringVar(value=lead.get("assigned_to", "")), "next_action": tk.StringVar(value=lead.get("next_action", "")),
            "next_action_at": tk.StringVar(value=str(lead.get("next_action_at", ""))), "notes": tk.StringVar(value=lead.get("notes", "")),
            "loss_reason": tk.StringVar(value=lead.get("loss_reason", "")),
        }
        fields = (
            ("Contacto *", "client_name"), ("WhatsApp", "whatsapp"), ("Origen", "source"), ("Estado", "stage"),
            ("Probabilidad %", "probability"), ("Valor estimado", "expected_value"), ("Vendedor", "assigned_to"),
            ("Próxima acción", "next_action"), ("Fecha y hora (AAAA-MM-DD HH:MM)", "next_action_at"),
            ("Notas", "notes"), ("Motivo de pérdida", "loss_reason"),
        )
        first = None
        for row, (label, key) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
            if key == "stage": widget = ttk.Combobox(form, textvariable=values[key], values=LEAD_STAGES, state="readonly", width=38)
            elif key == "source": widget = ttk.Combobox(form, textvariable=values[key], values=("WhatsApp", "Instagram", "Facebook", "Referido", "Local", "Web", "Otro"), width=38)
            else: widget = ttk.Entry(form, textvariable=values[key], width=41)
            widget.grid(row=row, column=1, sticky="ew", pady=5)
            first = first or widget
        def save() -> None:
            try:
                payload = {key: var.get() for key, var in values.items()}
                payload["probability"] = int(payload["probability"] or 0)
                payload["expected_value"] = float(str(payload["expected_value"] or 0).replace(",", "."))
                if lead_id: self.repository.update_lead(lead_id, **payload)
                else: self.repository.create_lead(**payload)
            except (ValueError, TypeError) as error:
                messagebox.showwarning("Oportunidad", str(error), parent=dialog); return
            dialog.destroy(); self.refresh_all(); self.on_status("Oportunidad guardada.")
        buttons = ttk.Frame(form); buttons.grid(row=len(fields), column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Cancelar", command=dialog.destroy).pack(side="left", padx=6)
        ttk.Button(buttons, text="Guardar", command=save, style="Primary.TButton").pack(side="left")
        dialog.bind("<Return>", lambda _event: save()); dialog.after_idle(first.focus_set)

    def edit_selected_lead(self) -> None:
        lead_id = self._selected_id(self.leads_tree)
        if lead_id: self.open_lead_editor(lead_id)

    def create_quote_from_selected_lead(self) -> None:
        lead_id = self._selected_id(self.leads_tree)
        if lead_id: self.open_quote_editor(lead_id=lead_id)

    def copy_lead_followup(self) -> None:
        lead = self.repository.lead(self._selected_id(self.leads_tree) or 0)
        if lead:
            self._copy(f"Hola {lead['client_name']}, te escribo para continuar con tu consulta. ¿Querés que avancemos con el presupuesto?")

    # --------------------------------------------------------- Presupuestos
    def _build_quotes(self) -> None:
        header = self._section_header(self.quotes_tab, "PRESUPUESTOS GUARDADOS", "Versionados, con vencimiento, aprobación de descuento y conversión directa en pedido.")
        ttk.Button(header, text="+ Nuevo presupuesto", command=self.open_quote_editor, style="Primary.TButton").pack(side="right")
        filters = ttk.Frame(self.quotes_tab); filters.pack(fill="x", padx=14, pady=(0, 8))
        self.quote_status_var = tk.StringVar(value="Todos"); self.quote_query_var = tk.StringVar()
        ttk.Label(filters, text="Estado").pack(side="left")
        combo = ttk.Combobox(filters, textvariable=self.quote_status_var, values=("Todos",) + QUOTE_STATUSES, state="readonly", width=15)
        combo.pack(side="left", padx=(6, 14)); combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_quotes())
        ttk.Entry(filters, textvariable=self.quote_query_var, width=30).pack(side="left")
        ttk.Button(filters, text="Buscar", command=self.refresh_quotes).pack(side="left", padx=6)
        self.quotes_tree = self._tree(self.quotes_tab, (
            ("id", "ID", 45, "center"), ("number", "Número", 115, "center"), ("client", "Cliente", 180, "w"),
            ("date", "Creado", 105, "center"), ("valid", "Vence", 105, "center"), ("items", "Ítems", 55, "center"),
            ("total", "Total", 110, "e"), ("status", "Estado", 95, "center"), ("approval", "Descuento", 105, "center"), ("order", "Pedido", 70, "center"),
        ))
        actions = ttk.Frame(self.quotes_tab); actions.pack(fill="x", padx=14, pady=(0, 14))
        ttk.Button(actions, text="Editar / nueva versión", command=self.edit_selected_quote).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Copiar para WhatsApp", command=self.copy_selected_quote, style="Primary.TButton").pack(side="left")
        ttk.Button(actions, text="Marcar enviado", command=lambda: self.change_selected_quote_status("Enviado")).pack(side="left", padx=6)
        ttk.Button(actions, text="Aceptar", command=lambda: self.change_selected_quote_status("Aceptado")).pack(side="left")
        ttk.Button(actions, text="Aprobar descuento", command=self.approve_selected_quote).pack(side="left", padx=6)
        ttk.Button(actions, text="Convertir en pedido", command=self.convert_selected_quote, style="Primary.TButton").pack(side="right")

    def refresh_quotes(self) -> None:
        self.quotes_tree.delete(*self.quotes_tree.get_children())
        for quote in self.repository.quotes(status=self.quote_status_var.get(), query=self.quote_query_var.get()):
            self.quotes_tree.insert("", "end", iid=str(quote["id"]), values=(
                quote["id"], f"{quote['quote_number']} · v{quote['version']}", quote["client_name"], str(quote["created_at"])[:10], quote["valid_until"],
                quote["item_count"], self._money(quote["total"]), quote["status"], quote["approval_status"], quote["converted_order_id"] or "—",
            ))

    def open_quote_editor(self, lead_id: int | None = None, quote_id: int | None = None) -> None:
        quote = self.repository.quote(quote_id) if quote_id else {}
        lead_id = lead_id or quote.get("lead_id")
        lead = self.repository.lead(lead_id) if lead_id else {}
        dialog = tk.Toplevel(self); dialog.title("Nueva versión del presupuesto" if quote_id else "Nuevo presupuesto"); dialog.configure(background=COLORS.background)
        dialog.geometry("900x690"); dialog.minsize(760, 590); dialog.transient(self); dialog.grab_set()
        root = ttk.Frame(dialog, padding=16); root.pack(fill="both", expand=True)
        customer = ttk.LabelFrame(root, text=" Cliente ", padding=10); customer.pack(fill="x")
        name_var = tk.StringVar(value=quote.get("client_name") or lead.get("client_name", "")); whatsapp_var = tk.StringVar(value=quote.get("whatsapp") or lead.get("whatsapp", ""))
        default_valid = (date.today() + timedelta(days=int(float(self.repository.setting("quote_valid_days", "7"))))).isoformat()
        valid_var = tk.StringVar(value=quote.get("valid_until") or default_valid)
        ttk.Label(customer, text="Nombre *").grid(row=0, column=0, sticky="w"); ttk.Entry(customer, textvariable=name_var, width=30).grid(row=0, column=1, padx=7)
        ttk.Label(customer, text="WhatsApp").grid(row=0, column=2, sticky="w"); ttk.Entry(customer, textvariable=whatsapp_var, width=20).grid(row=0, column=3, padx=7)
        ttk.Label(customer, text="Válido hasta").grid(row=0, column=4, sticky="w"); ttk.Entry(customer, textvariable=valid_var, width=12).grid(row=0, column=5, padx=7)

        products = self.database.catalog_products()
        product_by_name = {str(item["name"]): item for item in products}
        item_box = ttk.LabelFrame(root, text=" Producto ", padding=10); item_box.pack(fill="x", pady=10)
        product_var = tk.StringVar(value=next(iter(product_by_name), "")); material_var = tk.StringVar(); size_var = tk.StringVar()
        quantity_var = tk.StringVar(value="1"); price_var = tk.StringVar(value="0")
        ttk.Label(item_box, text="Producto").grid(row=0, column=0, sticky="w")
        product_combo = ttk.Combobox(item_box, textvariable=product_var, values=list(product_by_name), state="readonly", width=27)
        product_combo.grid(row=1, column=0, padx=(0, 8), sticky="ew")
        for column, (label, var, width) in enumerate((("Material", material_var, 20), ("Tamaño", size_var, 12), ("Cantidad", quantity_var, 8), ("Precio unitario", price_var, 13)), start=1):
            ttk.Label(item_box, text=label).grid(row=0, column=column, sticky="w")
            ttk.Entry(item_box, textvariable=var, width=width).grid(row=1, column=column, padx=(0, 8), sticky="ew")
        quote_items: list[dict[str, Any]] = self.repository.quote_items(quote_id) if quote_id else []
        items_tree = ttk.Treeview(root, columns=("product", "variant", "quantity", "unit", "subtotal"), show="headings", height=8)
        for key, label, width, anchor in (("product", "Producto", 260, "w"), ("variant", "Variante", 220, "w"), ("quantity", "Cant.", 65, "center"), ("unit", "Unitario", 100, "e"), ("subtotal", "Subtotal", 110, "e")):
            items_tree.heading(key, text=label); items_tree.column(key, width=width, anchor=anchor)
        items_tree.pack(fill="both", expand=True)
        def fill_price(*_args) -> None:
            product = product_by_name.get(product_var.get())
            if product: price_var.set(str(float(product.get("price") or product.get("base_price") or 0)))
        def refresh_items() -> None:
            items_tree.delete(*items_tree.get_children())
            for index, item in enumerate(quote_items):
                variant = " · ".join(part for part in (item["material"], item["size"]) if part) or "—"
                items_tree.insert("", "end", iid=str(index), values=(item["product_name"], variant, item["quantity"], self._money(item["unit_price"]), self._money(item["subtotal"])))
        def add_item() -> None:
            product = product_by_name.get(product_var.get())
            try:
                quantity = max(1, int(quantity_var.get())); price = max(0.0, float(price_var.get().replace(",", ".")))
            except ValueError:
                messagebox.showwarning("Producto", "Revisá cantidad y precio.", parent=dialog); return
            if not product:
                messagebox.showwarning("Producto", "Seleccioná un producto activo.", parent=dialog); return
            base_price = float(product.get("price") or product.get("base_price") or 0)
            calculation = self.database.resolve_commercial_price(
                product_id=int(product["id"]), material=material_var.get(), size=size_var.get(), quantity=quantity,
            )
            if calculation.get("matched") and abs(price - base_price) < 0.005:
                subtotal = float(calculation.get("subtotal") or 0)
                price = float(calculation.get("unit_price") or (subtotal / quantity))
            else:
                subtotal = price * quantity
            quote_items.append({"product_id": product["id"], "product_name": product["name"], "material": material_var.get(), "size": size_var.get(), "quantity": quantity, "unit_price": price, "subtotal": subtotal})
            refresh_items()
        def remove_item() -> None:
            selected = items_tree.selection()
            if selected: del quote_items[int(selected[0])]; refresh_items()
        product_combo.bind("<<ComboboxSelected>>", fill_price); fill_price(); refresh_items()
        ttk.Button(item_box, text="Agregar", command=add_item, style="Primary.TButton").grid(row=1, column=5)
        ttk.Button(root, text="Quitar seleccionado", command=remove_item).pack(anchor="e", pady=(5, 8))

        options = ttk.LabelFrame(root, text=" Condiciones ", padding=10); options.pack(fill="x")
        discount_var = tk.StringVar(value=str(quote.get("discount_percent", 0))); reason_var = tk.StringVar(value=quote.get("discount_reason", ""))
        payment_var = tk.StringVar(value=quote.get("payment_terms") or "Seña para confirmar; saldo antes de entregar")
        delivery_var = tk.StringVar(value=quote.get("delivery_terms") or "Plazo a confirmar al aceptar"); notes_var = tk.StringVar(value=quote.get("notes", ""))
        promotion_var = tk.StringVar(value=quote.get("promotion_code", ""))
        labels = (("Descuento %", discount_var, 8), ("Motivo", reason_var, 18), ("Promoción", promotion_var, 12), ("Pago", payment_var, 24), ("Entrega", delivery_var, 22), ("Notas", notes_var, 17))
        for column, (label, var, width) in enumerate(labels):
            ttk.Label(options, text=label).grid(row=0, column=column, sticky="w")
            ttk.Entry(options, textvariable=var, width=width).grid(row=1, column=column, padx=(0, 7), sticky="ew")
        def save() -> None:
            try:
                payload = dict(client_name=name_var.get(), whatsapp=whatsapp_var.get(), items=quote_items,
                    valid_until=valid_var.get(), discount_percent=float(discount_var.get().replace(",", ".") or 0),
                    discount_reason=reason_var.get(), notes=notes_var.get(), delivery_terms=delivery_var.get(),
                    payment_terms=payment_var.get(), promotion_code=promotion_var.get())
                if quote_id:
                    saved_quote_id = self.repository.revise_quote(quote_id, **payload)
                else:
                    saved_quote_id = self.repository.create_quote(lead_id=lead_id, **payload)
            except (ValueError, TypeError) as error:
                messagebox.showwarning("Presupuesto", str(error), parent=dialog); return
            dialog.destroy(); self.refresh_all(); self.notebook.select(self.quotes_tab); self.on_status(f"Presupuesto {self.repository.quote_label(saved_quote_id)} guardado.")
        footer = ttk.Frame(root); footer.pack(fill="x", pady=(12, 0))
        ttk.Button(footer, text="Cancelar", command=dialog.destroy).pack(side="right")
        ttk.Button(footer, text="Guardar presupuesto", command=save, style="Primary.TButton").pack(side="right", padx=7)

    def edit_selected_quote(self) -> None:
        quote_id = self._selected_id(self.quotes_tree)
        if quote_id:
            self.open_quote_editor(quote_id=quote_id)

    def copy_selected_quote(self) -> None:
        quote_id = self._selected_id(self.quotes_tree)
        if quote_id:
            self._copy(self.repository.quote_message(quote_id)); self.repository.set_quote_status(quote_id, "Enviado"); self.refresh_all()

    def change_selected_quote_status(self, status: str) -> None:
        quote_id = self._selected_id(self.quotes_tree)
        if quote_id:
            self.repository.set_quote_status(quote_id, status); self.refresh_all(); self.on_status(f"Presupuesto marcado como {status.lower()}.")

    def approve_selected_quote(self) -> None:
        quote_id = self._selected_id(self.quotes_tree)
        if not quote_id: return
        dialog = tk.Toplevel(self); dialog.title("Aprobar descuento"); dialog.transient(self); dialog.grab_set()
        frame = ttk.Frame(dialog, padding=18); frame.pack(fill="both", expand=True)
        name = tk.StringVar(); ttk.Label(frame, text="Responsable que aprueba").pack(anchor="w")
        entry = ttk.Entry(frame, textvariable=name, width=35); entry.pack(fill="x", pady=8)
        def approve() -> None:
            try: self.repository.approve_quote(quote_id, name.get())
            except ValueError as error: messagebox.showwarning("Aprobación", str(error), parent=dialog); return
            dialog.destroy(); self.refresh_all(); self.on_status("Descuento aprobado.")
        ttk.Button(frame, text="Aprobar", command=approve, style="Primary.TButton").pack(anchor="e"); entry.focus_set()

    def convert_selected_quote(self) -> None:
        quote_id = self._selected_id(self.quotes_tree)
        if not quote_id: return
        try: order_id = self.repository.convert_quote_to_order(quote_id, self.database.create_order)
        except (ValueError, TypeError) as error: messagebox.showwarning("Convertir presupuesto", str(error), parent=self); return
        self.refresh_all(); self.on_status(f"Pedido #{order_id} creado desde el presupuesto.")
        if messagebox.askyesno("Pedido creado", f"Se creó el pedido #{order_id}. ¿Querés abrirlo?", parent=self): self.on_open_order(order_id)

    # -------------------------------------------------------------- Cobros
    def _build_receivables(self) -> None:
        header = self._section_header(self.receivables_tab, "SALDOS A COBRAR", "Priorizá vencidos, registrá pagos y enviá recordatorios claros.")
        self.receivable_summary = tk.StringVar()
        ttk.Label(header, textvariable=self.receivable_summary, style="Muted.TLabel").pack(side="right")
        self.receivables_tree = self._tree(self.receivables_tab, (
            ("id", "Pedido", 65, "center"), ("client", "Cliente", 200, "w"), ("total", "Total", 110, "e"),
            ("paid", "Cobrado", 110, "e"), ("pending", "Pendiente", 110, "e"), ("due", "Vencimiento", 120, "center"),
            ("status", "Pedido", 110, "center"), ("alert", "Alerta", 85, "center"),
        ))
        actions = ttk.Frame(self.receivables_tab); actions.pack(fill="x", padx=14, pady=(0, 14))
        ttk.Button(actions, text="Registrar cobro", command=self.register_selected_receivable, style="Primary.TButton").pack(side="left")
        ttk.Button(actions, text="Copiar recordatorio", command=self.copy_receivable_reminder).pack(side="left", padx=7)
        ttk.Button(actions, text="Abrir pedido", command=self.open_selected_receivable_order).pack(side="left")

    def refresh_receivables(self) -> None:
        self.receivables_tree.delete(*self.receivables_tree.get_children())
        rows = self.repository.receivables(); pending = sum(float(item["pending"]) for item in rows)
        self.receivable_summary.set(f"{len(rows)} pedido(s) · {self._money(pending)} pendiente")
        for item in rows:
            self.receivables_tree.insert("", "end", iid=str(item["order_id"]), values=(item["order_id"], item["client_name"], self._money(item["total"]), self._money(item["paid"]), self._money(item["pending"]), str(item["due_at"])[:10], item["status"], "Vencido" if item["overdue"] else "Al día"))

    def register_selected_receivable(self) -> None:
        order_id = self._selected_id(self.receivables_tree)
        if order_id: self.on_register_payment(order_id); self.after(300, self.refresh_all)

    def copy_receivable_reminder(self) -> None:
        order_id = self._selected_id(self.receivables_tree)
        item = next((row for row in self.repository.receivables() if int(row["order_id"]) == order_id), None)
        if item: self._copy(item["message"])

    def open_selected_receivable_order(self) -> None:
        order_id = self._selected_id(self.receivables_tree)
        if order_id: self.on_open_order(order_id)

    # ------------------------------------------------------------ Entregas
    def _build_deliveries(self) -> None:
        header = self._section_header(self.deliveries_tab, "ENTREGAS Y RETIROS", "Dirección, costo, horario, seguimiento y confirmación de recepción.")
        ttk.Button(header, text="Coordinar seleccionado", command=self.edit_selected_delivery, style="Primary.TButton").pack(side="right")
        self.deliveries_tree = self._tree(self.deliveries_tab, (
            ("id", "Pedido", 65, "center"), ("client", "Cliente", 180, "w"), ("method", "Modalidad", 105, "center"),
            ("address", "Dirección", 230, "w"), ("scheduled", "Programada", 135, "center"), ("window", "Franja", 110, "center"),
            ("tracking", "Seguimiento", 120, "center"), ("status", "Estado", 125, "center"), ("cost", "Costo", 90, "e"),
        ))
        self.deliveries_tree.bind("<Double-1>", lambda _event: self.edit_selected_delivery())
        actions = ttk.Frame(self.deliveries_tab); actions.pack(fill="x", padx=14, pady=(0, 14))
        ttk.Button(actions, text="Editar coordinación", command=self.edit_selected_delivery).pack(side="left")
        ttk.Button(actions, text="Copiar confirmación", command=self.copy_delivery_message).pack(side="left", padx=7)
        ttk.Button(actions, text="Abrir pedido", command=lambda: self.on_open_order(self._selected_id(self.deliveries_tree) or 0)).pack(side="left")

    def refresh_deliveries(self) -> None:
        self.deliveries_tree.delete(*self.deliveries_tree.get_children())
        for item in self.repository.deliveries():
            self.deliveries_tree.insert("", "end", iid=str(item["order_id"]), values=(
                item["order_id"], item["client_name"], item.get("method") or "Retiro", item.get("address") or "—",
                str(item.get("scheduled_at") or item.get("delivery_date") or "")[:16].replace("T", " "), item.get("time_window") or "—",
                item.get("tracking_code") or "—", item.get("status") or "Sin coordinar", self._money(item.get("shipping_cost") or 0),
            ))

    def edit_selected_delivery(self) -> None:
        order_id = self._selected_id(self.deliveries_tree)
        if not order_id: return
        data = self.repository.delivery(order_id) or {}
        dialog = tk.Toplevel(self); dialog.title(f"Entrega · Pedido #{order_id}"); dialog.transient(self); dialog.grab_set(); dialog.resizable(False, False)
        form = ttk.Frame(dialog, padding=18); form.pack(fill="both", expand=True)
        values = {
            "method": tk.StringVar(value=data.get("method", "Retiro")), "address": tk.StringVar(value=data.get("address", "")),
            "city": tk.StringVar(value=data.get("city", "")), "shipping_cost": tk.StringVar(value=str(data.get("shipping_cost", 0))),
            "scheduled_at": tk.StringVar(value=data.get("scheduled_at", "")), "time_window": tk.StringVar(value=data.get("time_window", "")),
            "tracking_code": tk.StringVar(value=data.get("tracking_code", "")), "status": tk.StringVar(value=data.get("status", "Sin coordinar")),
            "notes": tk.StringVar(value=data.get("notes", "")),
        }
        fields = (("Modalidad", "method"), ("Dirección", "address"), ("Localidad", "city"), ("Costo de envío", "shipping_cost"),
                  ("Fecha y hora", "scheduled_at"), ("Franja horaria", "time_window"), ("Tracking / referencia", "tracking_code"),
                  ("Estado", "status"), ("Notas", "notes"))
        for row, (label, key) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
            if key == "method": widget = ttk.Combobox(form, textvariable=values[key], values=("Retiro", "Mensajería", "Correo", "Entrega propia"), state="readonly", width=36)
            elif key == "status": widget = ttk.Combobox(form, textvariable=values[key], values=DELIVERY_STATUSES, state="readonly", width=36)
            else: widget = ttk.Entry(form, textvariable=values[key], width=39)
            widget.grid(row=row, column=1, pady=5)
        def save() -> None:
            try:
                payload = {key: var.get() for key, var in values.items()}; payload["shipping_cost"] = float(payload["shipping_cost"].replace(",", ".") or 0)
                self.repository.upsert_delivery(order_id, **payload)
            except ValueError as error: messagebox.showwarning("Entrega", str(error), parent=dialog); return
            dialog.destroy(); self.refresh_all(); self.on_status("Coordinación de entrega guardada.")
        ttk.Button(form, text="Guardar", command=save, style="Primary.TButton").grid(row=len(fields), column=1, sticky="e", pady=(12, 0))

    def copy_delivery_message(self) -> None:
        order_id = self._selected_id(self.deliveries_tree)
        item = next((row for row in self.repository.deliveries() if int(row["order_id"]) == order_id), None)
        if item:
            scheduled = str(item.get("scheduled_at") or item.get("delivery_date") or "a coordinar").replace("T", " ")[:16]
            self._copy(f"Hola {item['client_name']}, te confirmo la {str(item.get('method') or 'entrega').lower()} del pedido #{order_id} para {scheduled}. Estado: {item.get('status') or 'Sin coordinar'}.")

    # ------------------------------------------------------ Fidelización
    def _build_customers(self) -> None:
        header = self._section_header(self.customers_tab, "FIDELIZACIÓN Y RECOMPRA", "Segmentos automáticos para volver a conversar con el cliente adecuado.")
        self.campaign_var = tk.StringVar(value="Reactivación")
        ttk.Combobox(header, textvariable=self.campaign_var, values=("Reactivación", "Recompra", "Fidelización"), state="readonly", width=18).pack(side="right")
        self.customers_tree = self._tree(self.customers_tab, (
            ("id", "ID", 45, "center"), ("client", "Cliente", 190, "w"), ("whatsapp", "WhatsApp", 120, "w"),
            ("segment", "Segmento", 100, "center"), ("orders", "Pedidos", 65, "center"), ("billed", "Facturación", 115, "e"),
            ("last", "Última compra", 110, "center"), ("type", "Tipo", 95, "center"), ("tags", "Etiquetas", 180, "w"),
        ))
        actions = ttk.Frame(self.customers_tab); actions.pack(fill="x", padx=14, pady=(0, 14))
        ttk.Button(actions, text="Copiar mensaje de campaña", command=self.copy_customer_campaign, style="Primary.TButton").pack(side="left")
        ttk.Button(actions, text="Editar perfil comercial", command=self.edit_customer_profile).pack(side="left", padx=7)

    def refresh_customers(self) -> None:
        self.customers_tree.delete(*self.customers_tree.get_children())
        for item in self.repository.customer_segments():
            self.customers_tree.insert("", "end", iid=str(item["id"]), values=(item["id"], item["name"], item["whatsapp"], item["segment"], item["order_count"], self._money(item["total_billed"]), str(item.get("last_order_at") or "")[:10] or "—", item.get("client_type") or "Particular", item.get("tags") or ""))

    def copy_customer_campaign(self) -> None:
        client_id = self._selected_id(self.customers_tree)
        item = next((row for row in self.repository.customer_segments() if int(row["id"]) == client_id), None)
        if item: self._copy(self.repository.campaign_message(item, self.campaign_var.get()))

    def edit_customer_profile(self) -> None:
        client_id = self._selected_id(self.customers_tree)
        if not client_id: return
        row = self.database.connection.execute("SELECT * FROM client_commercial_profiles WHERE client_id=?", (client_id,)).fetchone()
        data = dict(row) if row else {}
        dialog = tk.Toplevel(self); dialog.title("Perfil comercial del cliente"); dialog.transient(self); dialog.grab_set(); dialog.resizable(False, False)
        form = ttk.Frame(dialog, padding=18); form.pack(fill="both", expand=True)
        values = {key: tk.StringVar(value=data.get(key, "")) for key in ("email", "birthday", "tags", "notes", "last_contact_at")}
        values["preferred_channel"] = tk.StringVar(value=data.get("preferred_channel", "WhatsApp"))
        for row_index, (label, key) in enumerate((("Email", "email"), ("Cumpleaños (AAAA-MM-DD)", "birthday"), ("Canal preferido", "preferred_channel"), ("Etiquetas separadas por coma", "tags"), ("Último contacto", "last_contact_at"), ("Notas", "notes"))):
            ttk.Label(form, text=label).grid(row=row_index, column=0, sticky="w", padx=(0, 10), pady=5)
            widget = ttk.Combobox(form, textvariable=values[key], values=("WhatsApp", "Email", "Teléfono", "Instagram"), state="readonly", width=37) if key == "preferred_channel" else ttk.Entry(form, textvariable=values[key], width=40)
            widget.grid(row=row_index, column=1, pady=5)
        def save() -> None:
            self.repository.save_client_profile(client_id, **{key: var.get() for key, var in values.items()})
            dialog.destroy(); self.refresh_customers(); self.on_status("Perfil comercial actualizado.")
        ttk.Button(form, text="Guardar", command=save, style="Primary.TButton").grid(row=6, column=1, sticky="e", pady=(12, 0))

    # ---------------------------------------------------- Catálogo exportable
    def _build_catalog(self) -> None:
        header = self._section_header(self.catalog_tab, "CATÁLOGO COMPARTIBLE", "Generá un archivo HTML autocontenido con fotos, descripciones y precios de referencia.")
        content = tk.Frame(self.catalog_tab, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
        content.pack(fill="x", padx=14, pady=(10, 14))
        self.catalog_title_var = tk.StringVar(value="Catálogo Doccione")
        tk.Label(content, text="Título del catálogo", background=COLORS.panel_elevated, foreground=COLORS.text, font=(UI_FONT, 10, "bold")).pack(anchor="w", padx=18, pady=(18, 5))
        ttk.Entry(content, textvariable=self.catalog_title_var, width=52).pack(anchor="w", padx=18)
        tk.Label(content, text="Incluye únicamente productos activos. Las imágenes pequeñas quedan incrustadas para que el archivo pueda enviarse tal cual.",
                 background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 9), wraplength=680, justify="left").pack(anchor="w", padx=18, pady=(10, 14))
        buttons = ttk.Frame(content); buttons.pack(fill="x", padx=18, pady=(0, 18))
        ttk.Button(buttons, text="Generar catálogo", command=self.export_catalog, style="Primary.TButton").pack(side="left")
        self.catalog_last_path = tk.StringVar(value="Todavía no se generó un catálogo.")
        ttk.Label(buttons, textvariable=self.catalog_last_path, style="Muted.TLabel").pack(side="left", padx=12)

    def export_catalog(self) -> None:
        path = filedialog.asksaveasfilename(parent=self, title="Guardar catálogo", defaultextension=".html", filetypes=(("Catálogo web", "*.html"),), initialfile="catalogo_doccione.html")
        if not path: return
        result = self.repository.export_catalog_html(path, title=self.catalog_title_var.get().strip() or "Catálogo Doccione")
        self.catalog_last_path.set(str(result)); self.on_status(f"Catálogo creado: {result.name}")
        if messagebox.askyesno("Catálogo creado", "El catálogo quedó listo para compartir. ¿Querés abrirlo?", parent=self):
            webbrowser.open(result.resolve().as_uri())

    # ---------------------------------------------------- Reglas comerciales
    def _build_policies(self) -> None:
        header = self._section_header(self.policies_tab, "REGLAS COMERCIALES", "Límites de descuento, mayoristas, vencimientos y promociones trazables.")
        body = tk.PanedWindow(self.policies_tab, orient="horizontal", background=COLORS.panel, sashwidth=5)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        policy = ttk.LabelFrame(body, text=" Política general ", padding=14); promo = ttk.LabelFrame(body, text=" Promociones ", padding=14)
        body.add(policy, minsize=330); body.add(promo, minsize=520)
        self.setting_vars = {key: tk.StringVar() for key in (
            "max_discount_without_approval", "wholesale_min_quantity", "quote_valid_days", "followup_days", "dormant_customer_days", "business_whatsapp")}
        labels = (("Descuento máximo sin aprobación (%)", "max_discount_without_approval"), ("Cantidad mínima mayorista", "wholesale_min_quantity"),
                  ("Validez de presupuestos (días)", "quote_valid_days"), ("Seguimiento tras enviar (días)", "followup_days"),
                  ("Cliente inactivo después de (días)", "dormant_customer_days"), ("WhatsApp comercial", "business_whatsapp"))
        for row, (label, key) in enumerate(labels):
            ttk.Label(policy, text=label).grid(row=row, column=0, sticky="w", pady=6)
            ttk.Entry(policy, textvariable=self.setting_vars[key], width=16).grid(row=row, column=1, padx=(10, 0), pady=6)
        ttk.Button(policy, text="Guardar política", command=self.save_policy, style="Primary.TButton").grid(row=len(labels), column=0, columnspan=2, sticky="e", pady=(14, 0))
        self.promotions_tree = ttk.Treeview(promo, columns=("id", "code", "name", "discount", "audience", "period", "status"), show="headings", height=10)
        for key, label, width in (("id", "ID", 40), ("code", "Código", 80), ("name", "Promoción", 150), ("discount", "%", 50), ("audience", "Público", 90), ("period", "Vigencia", 170), ("status", "Estado", 70)):
            self.promotions_tree.heading(key, text=label); self.promotions_tree.column(key, width=width, anchor="center" if key != "name" else "w")
        self.promotions_tree.pack(fill="both", expand=True)
        ttk.Button(promo, text="+ Nueva promoción", command=self.open_promotion_editor, style="Primary.TButton").pack(anchor="e", pady=(10, 0))

    def save_policy(self) -> None:
        try:
            for key in ("max_discount_without_approval", "wholesale_min_quantity", "quote_valid_days", "followup_days", "dormant_customer_days"):
                if float(self.setting_vars[key].get()) < 0: raise ValueError("Los valores no pueden ser negativos.")
        except ValueError as error:
            messagebox.showwarning("Política comercial", str(error), parent=self); return
        self.repository.save_settings({key: var.get() for key, var in self.setting_vars.items()}); self.on_status("Política comercial guardada.")

    def open_promotion_editor(self) -> None:
        dialog = tk.Toplevel(self); dialog.title("Nueva promoción"); dialog.transient(self); dialog.grab_set(); dialog.resizable(False, False)
        form = ttk.Frame(dialog, padding=18); form.pack(fill="both", expand=True)
        values = {"code": tk.StringVar(), "name": tk.StringVar(), "description": tk.StringVar(), "discount_percent": tk.StringVar(value="10"),
                  "starts_at": tk.StringVar(value=date.today().isoformat()), "ends_at": tk.StringVar(value=(date.today()+timedelta(days=30)).isoformat()), "audience": tk.StringVar(value="Todos")}
        for row, (label, key) in enumerate((("Código *", "code"), ("Nombre *", "name"), ("Descripción", "description"), ("Descuento %", "discount_percent"), ("Desde", "starts_at"), ("Hasta", "ends_at"), ("Público", "audience"))):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
            widget = ttk.Combobox(form, textvariable=values[key], values=("Todos", "VIP", "Recurrente", "Inactivo", "Revendedor"), state="readonly", width=36) if key == "audience" else ttk.Entry(form, textvariable=values[key], width=39)
            widget.grid(row=row, column=1, pady=5)
        def save() -> None:
            try: self.repository.save_promotion(**{key: (float(var.get().replace(",", ".")) if key == "discount_percent" else var.get()) for key, var in values.items()})
            except (ValueError, TypeError) as error: messagebox.showwarning("Promoción", str(error), parent=dialog); return
            dialog.destroy(); self.refresh_policies(); self.on_status("Promoción guardada.")
        ttk.Button(form, text="Guardar", command=save, style="Primary.TButton").grid(row=7, column=1, sticky="e", pady=(12, 0))

    def refresh_policies(self) -> None:
        settings = self.repository.settings()
        for key, var in self.setting_vars.items(): var.set(settings.get(key, ""))
        self.promotions_tree.delete(*self.promotions_tree.get_children())
        for item in self.repository.promotions():
            period = f"{item['starts_at'] or '—'} → {item['ends_at'] or '—'}"
            self.promotions_tree.insert("", "end", values=(item["id"], item["code"], item["name"], f"{float(item['discount_percent']):g}%", item["audience"], period, "Activa" if item["active"] else "Pausada"))

    # --------------------------------------------------------------- Refresh
    def refresh_current(self) -> None:
        selected = self.notebook.nametowidget(self.notebook.select())
        callbacks = {self.dashboard_tab: self.refresh_dashboard, self.pipeline_tab: self.refresh_leads,
                     self.quotes_tab: self.refresh_quotes, self.receivables_tab: self.refresh_receivables,
                     self.deliveries_tab: self.refresh_deliveries, self.customers_tab: self.refresh_customers,
                     self.policies_tab: self.refresh_policies}
        callback = callbacks.get(selected)
        if callback: callback()

    def refresh_all(self) -> None:
        self.refresh_dashboard(); self.refresh_leads(); self.refresh_quotes(); self.refresh_receivables()
        self.refresh_deliveries(); self.refresh_customers(); self.refresh_policies()
