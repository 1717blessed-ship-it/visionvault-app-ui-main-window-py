# Versión mejorada del formulario de nuevo pedido
# Para integrar en app/ui/main_window.py reemplazando el método new_order_dialog

def new_order_dialog(self):
    """Formulario mejorado con fecha de pedido, concepto, descripción y fecha/hora de entrega."""
    dialog = tk.Toplevel(self)
    dialog.title("Nuevo pedido")
    dialog.configure(background=COLORS.background)
    dialog.transient(self)
    dialog.grab_set()
    dialog.geometry("1100x820")
    dialog.minsize(950, 720)

    from datetime import datetime
    
    style = ttk.Style(dialog)
    style.configure("Order.TCombobox", fieldbackground=COLORS.field, background=COLORS.panel_elevated,
                    foreground=COLORS.text, arrowcolor=COLORS.text, padding=(7, 5))
    
    # Variables del formulario
    values = {
        name: tk.StringVar() 
        for name in ("client", "whatsapp", "assigned_to", "delivery_date", "delivery_time", 
                    "print_priority", "pending_reason", "order_concept", "order_description")
    }
    values["print_priority"].set("0")
    values["delivery_time"].set("18:00")  # Hora por defecto
    
    # Fecha de pedido (hoy)
    order_date = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
    
    # Mapeo de estados a etapas de la línea de tiempo
    # IMPORTANTE: Los estados ahora SON las etapas (1:1)
    STATUS_TO_STAGE = {
        # Estados principales del workflow (coinciden con las etapas)
        "Recibido": "Recibido",
        "Esperando archivos": "Esperando archivos",
        "Diseños confirmados": "Diseños confirmados",
        "Listo para Armado de Planchas": "Listo para Armado de Planchas",
        "En Armado de Planchas": "En Armado de Planchas",
        "Listo para imprimir": "Listo para imprimir",
        "Impreso": "Impreso",
        "Finalizado": "Finalizado",
        "Entregado": "Entregado",
        # Estados especiales (no son etapas, pero se mapean)
        "Esperando aprobación": "Esperando archivos",
        "Esperando pago": "Recibido",
        "Pendiente": "Recibido",
        "Bloqueado": "Recibido",
        # Compatibilidad con estados antiguos
        "Nuevo": "Recibido",
        "En revisión": "Esperando archivos",
        "En diseño": "Esperando archivos",
        "Listo para plancha": "Listo para Armado de Planchas",
        "En producción": "En Armado de Planchas",
    }
    
    status = tk.StringVar(value="Recibido")
    current_stage = tk.StringVar(value="Recibido")
    
    # Callback para sincronizar estado con línea de tiempo
    def sync_status_to_stage(*args):
        selected_status = status.get()
        stage = STATUS_TO_STAGE.get(selected_status, "Recibido")
        current_stage.set(stage)
        
        # Advertencia visual si está bloqueado
        if selected_status in ("Esperando aprobación", "Esperando pago", "Pendiente", "Bloqueado"):
            if hasattr(dialog, 'pending_reason_entry'):
                dialog.pending_reason_entry.configure(highlightcolor="#ff6b35", highlightbackground="#ff6b35")
    
    status.trace_add("write", sync_status_to_stage)
    
    jobs: list[dict] = [{"title": "Trabajo 1", "material": "", "size": "", "quantity": 1, "subtotal": 0, "discount_percent": 0, "status": "Pendiente"}]

    # Header
    header = tk.Frame(dialog, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
    header.pack(fill="x", padx=18, pady=(18, 12))
    tk.Label(
        header, 
        text="NUEVO PEDIDO", 
        background=COLORS.panel, 
        foreground=COLORS.text,
        font=(IDENTITY_FONT, 19, "bold")
    ).pack(anchor="w", padx=18, pady=(15, 3))
    tk.Label(
        header, 
        text="Registrá la información del cliente, fecha de entrega y los trabajos que incluye el pedido.",
        background=COLORS.panel, 
        foreground=COLORS.muted, 
        font=(UI_FONT, 10)
    ).pack(anchor="w", padx=18, pady=(0, 3))
    
    # Indicador de etapa actual de la línea de tiempo
    stage_frame = tk.Frame(header, background=COLORS.panel)
    stage_frame.pack(anchor="w", padx=18, pady=(0, 12))
    
    tk.Label(
        stage_frame,
        text="📍 Etapa en línea de tiempo:",
        background=COLORS.panel,
        foreground=COLORS.muted,
        font=(UI_FONT, 9)
    ).pack(side="left", padx=(0, 4))
    
    tk.Label(
        stage_frame,
        textvariable=current_stage,
        background=COLORS.panel,
        foreground=COLORS.wine_active,
        font=(UI_FONT, 10, "bold")
    ).pack(side="left")

    # Body con scroll
    body_container = tk.Frame(dialog, background=COLORS.background)
    body_container.pack(fill="both", expand=True, padx=18, pady=(0, 12))
    
    # Canvas para scroll
    canvas = tk.Canvas(body_container, background=COLORS.background, highlightthickness=0, borderwidth=0)
    scrollbar = ttk.Scrollbar(body_container, orient="vertical", command=canvas.yview)
    
    body = tk.Frame(canvas, background=COLORS.background)
    body.columnconfigure(0, weight=1)
    body.columnconfigure(1, weight=1)
    
    # Configurar scroll
    body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=body, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    
    # Habilitar scroll con rueda del mouse
    def on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    
    canvas.bind_all("<MouseWheel>", on_mousewheel)
    
    # Limpiar binding al cerrar
    def on_close():
        canvas.unbind_all("<MouseWheel>")
        dialog.destroy()
    
    dialog.protocol("WM_DELETE_WINDOW", on_close)

    # === PANEL IZQUIERDO: INFORMACIÓN DEL PEDIDO ===
    left_panel = tk.Frame(body, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
    left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
    
    tk.Label(
        left_panel, 
        text="INFORMACIÓN DEL PEDIDO", 
        background=COLORS.panel_elevated, 
        foreground=COLORS.wine_active,
        font=(IDENTITY_FONT, 11, "bold")
    ).pack(anchor="w", padx=16, pady=(14, 8))
    
    info_form = tk.Frame(left_panel, background=COLORS.panel_elevated)
    info_form.pack(fill="both", expand=True, padx=16, pady=(0, 16))
    info_form.columnconfigure(1, weight=1)

    def dark_entry(parent, variable, width=None):
        entry = tk.Entry(
            parent, 
            textvariable=variable, 
            background=COLORS.field, 
            foreground=COLORS.text,
            insertbackground=COLORS.text, 
            relief="flat", 
            highlightthickness=1,
            highlightbackground=COLORS.border, 
            highlightcolor=COLORS.wine_active, 
            font=(UI_FONT, 11)
        )
        if width:
            entry.configure(width=width)
        return entry

    def add_info_field(row, label, key, widget_type="entry", values_list=None, width=None):
        tk.Label(
            info_form, 
            text=label, 
            background=COLORS.panel_elevated, 
            foreground=COLORS.text,
            font=(UI_FONT, 10, "bold")
        ).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=7)
        
        if widget_type == "combo":
            widget = ttk.Combobox(
                info_form, 
                textvariable=values[key] if key in values else (status if key == "status" else order_date),
                values=values_list or [], 
                state="readonly", 
                style="Order.TCombobox"
            )
        elif widget_type == "text":
            widget = tk.Text(
                info_form,
                height=3,
                background=COLORS.field,
                foreground=COLORS.text,
                insertbackground=COLORS.text,
                relief="flat",
                highlightthickness=1,
                highlightbackground=COLORS.border,
                highlightcolor=COLORS.wine_active,
                font=(UI_FONT, 10),
                wrap="word"
            )
        else:
            widget = dark_entry(info_form, values[key] if key in values else order_date, width)
        
        widget.grid(row=row, column=1, sticky="ew", pady=7)
        return widget

    # Campos de información del pedido
    row = 0
    add_info_field(row, "📅 Fecha de pedido", "order_date", "entry")
    row += 1
    
    concept_widget = add_info_field(row, "📝 Concepto", "order_concept", "text")
    row += 1
    
    desc_widget = add_info_field(row, "📄 Descripción", "order_description", "text")
    row += 1
    
    tk.Frame(info_form, background=COLORS.border, height=1).grid(
        row=row, column=0, columnspan=2, sticky="ew", pady=12
    )
    row += 1
    
    tk.Label(
        info_form,
        text="CLIENTE",
        background=COLORS.panel_elevated,
        foreground=COLORS.wine_active,
        font=(IDENTITY_FONT, 10, "bold")
    ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
    row += 1
    
    client_entry = add_info_field(row, "👤 Nombre", "client", "entry")
    row += 1
    
    add_info_field(row, "📱 WhatsApp", "whatsapp", "entry")
    row += 1
    
    tk.Frame(info_form, background=COLORS.border, height=1).grid(
        row=row, column=0, columnspan=2, sticky="ew", pady=12
    )
    row += 1
    
    tk.Label(
        info_form,
        text="ENTREGA Y SEGUIMIENTO",
        background=COLORS.panel_elevated,
        foreground=COLORS.wine_active,
        font=(IDENTITY_FONT, 10, "bold")
    ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
    row += 1
    
    delivery_row = tk.Frame(info_form, background=COLORS.panel_elevated)
    delivery_row.grid(row=row, column=1, sticky="ew", pady=7)
    delivery_row.columnconfigure(0, weight=1)
    
    tk.Label(
        info_form,
        text="📆 Fecha de entrega",
        background=COLORS.panel_elevated,
        foreground=COLORS.text,
        font=(UI_FONT, 10, "bold")
    ).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=7)
    
    dark_entry(delivery_row, values["delivery_date"]).pack(side="left", fill="x", expand=True, padx=(0, 8))
    
    tk.Label(
        delivery_row,
        text="🕐 Hora:",
        background=COLORS.panel_elevated,
        foreground=COLORS.text,
        font=(UI_FONT, 9)
    ).pack(side="left", padx=(0, 4))
    
    dark_entry(delivery_row, values["delivery_time"], width=8).pack(side="left")
    row += 1
    
    add_info_field(row, "👨‍💼 Asignado a", "assigned_to", "entry")
    row += 1
    
    add_info_field(row, "⚡ Prioridad manual", "print_priority", "entry")
    row += 1
    
    add_info_field(row, "📌 Estado", "status", "combo", self.ORDER_STATUSES)
    row += 1
    
    tk.Label(
        info_form,
        text="💡 El estado define la etapa en la línea de tiempo",
        background=COLORS.panel_elevated,
        foreground=COLORS.muted,
        font=(UI_FONT, 8),
        wraplength=280,
        justify="left"
    ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
    row += 1
    
    dialog.pending_reason_entry = add_info_field(row, "⚠️ Razón si está bloqueado", "pending_reason", "entry")

    # === PANEL DERECHO: TRABAJOS DEL PEDIDO ===
    right_panel = tk.Frame(body, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
    right_panel.grid(row=0, column=1, sticky="nsew", pady=(0, 8))
    
    jobs_header = tk.Frame(right_panel, background=COLORS.panel_elevated)
    jobs_header.pack(fill="x", padx=14, pady=(13, 8))
    tk.Label(jobs_header, text="TRABAJOS DEL PEDIDO", background=COLORS.panel_elevated, foreground=COLORS.wine_active,
             font=(IDENTITY_FONT, 10, "bold")).pack(side="left")
    jobs_summary = tk.StringVar()
    tk.Label(jobs_header, textvariable=jobs_summary, background=COLORS.panel_elevated, foreground=COLORS.muted,
             font=(UI_FONT, 9)).pack(side="left", padx=11)
    job_actions = tk.Frame(jobs_header, background=COLORS.panel_elevated)
    job_actions.pack(side="right")
    
    table = tk.Frame(right_panel, background=COLORS.panel)
    table.pack(fill="both", expand=True, padx=14)
    # Columna "discount" y "total" removidas - descuentos se aplican al pedido, no por trabajo
    columns = ("title", "material", "size", "quantity", "subtotal", "status")
    job_tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse", height=13)
    labels = {"title": ("Trabajo", 170), "material": ("Material", 160), "size": ("Tamaño", 75),
              "quantity": ("Cant.", 60), "subtotal": ("Total", 110), "status": ("Estado", 100)}
    for key in columns:
        label, width = labels[key]
        job_tree.heading(key, text=label)
        job_tree.column(key, width=width, anchor="center" if key not in {"title", "material"} else "w")
    job_scroll = ttk.Scrollbar(table, orient="vertical", command=job_tree.yview)
    job_tree.configure(yscrollcommand=job_scroll.set)
    job_tree.pack(side="left", fill="both", expand=True)
    job_scroll.pack(side="right", fill="y")

    def total_for(job):
        # Los descuentos individuales ya no se usan; siempre devuelve el subtotal
        return float(job.get("subtotal", 0) or 0)

    def render_jobs():
        job_tree.delete(*job_tree.get_children())
        total = 0.0
        for index, job in enumerate(jobs):
            total += total_for(job)
            job_tree.insert("", "end", iid=str(index), values=(
                job.get("title") or f"Trabajo {index + 1}", job.get("material") or "Sin material",
                job.get("size") or "-", job.get("quantity") or 1,
                f"${float(job.get('subtotal', 0) or 0):,.0f}", job.get("status") or "Pendiente",
            ))
        jobs_summary.set(f"{len(jobs)} trabajo(s) · Total propuesto: ${total:,.0f}")

    def selected_index():
        selected = job_tree.selection()
        return int(selected[0]) if selected else None

    def add_job():
        self.edit_order_job_dialog(dialog, None, lambda saved: (jobs.append(saved), render_jobs()))

    def edit_job():
        index = selected_index()
        if index is None:
            messagebox.showinfo("Trabajos", "Elegí un trabajo para editar.", parent=dialog)
            return
        self.edit_order_job_dialog(dialog, jobs[index], lambda saved, current=index: (jobs.__setitem__(current, saved), render_jobs()))

    def remove_job():
        index = selected_index()
        if index is None:
            messagebox.showinfo("Trabajos", "Elegí un trabajo para quitar.", parent=dialog)
            return
        if len(jobs) == 1:
            messagebox.showwarning("Trabajos", "El pedido necesita al menos un trabajo.", parent=dialog)
            return
        jobs.pop(index)
        render_jobs()

    ttk.Button(job_actions, text="+ Trabajo", command=add_job, style="Primary.TButton").pack(side="left")
    ttk.Button(job_actions, text="Editar", command=edit_job, style="Secondary.TButton").pack(side="left", padx=6)
    ttk.Button(job_actions, text="Quitar", command=remove_job, style="Secondary.TButton").pack(side="left")
    job_tree.bind("<Double-1>", lambda _event: edit_job())
    tk.Label(right_panel, text="Cada trabajo mantiene su propio presupuesto. El total se calcula automáticamente.",
             background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 9)).pack(anchor="w", padx=14, pady=12)
    render_jobs()

    def create():
        client = values["client"].get().strip()
        if not client:
            messagebox.showwarning("Nuevo pedido", "Indicá el cliente.", parent=dialog)
            client_entry.focus_set()
            return
        
        # Combinar fecha y hora de entrega
        delivery_datetime = ""
        if values["delivery_date"].get().strip():
            delivery_datetime = f"{values['delivery_date'].get().strip()} {values['delivery_time'].get().strip()}"
        
        try:
            order_id = self.database.create_order(
                client, 
                values["whatsapp"].get(), 
                order_date=order_date.get(),
                status=status.get(), 
                jobs=jobs,
                assigned_to=values["assigned_to"].get(), 
                observations=(
                    f"CONCEPTO: {concept_widget.get('1.0', 'end').strip()}\n\n"
                    f"DESCRIPCIÓN: {desc_widget.get('1.0', 'end').strip()}"
                ).strip(),
                pending_reason=values["pending_reason"].get(), 
                delivery_date=delivery_datetime,
                print_priority=values["print_priority"].get(),
            )
        except ValueError:
            messagebox.showwarning("Nuevo pedido", "Revisá los datos de los trabajos y la prioridad.", parent=dialog)
            return
        dialog.destroy()
        self.refresh_orders()
        self.open_order_workspace(order_id)

    actions = tk.Frame(dialog, background=COLORS.background)
    actions.pack(fill="x", padx=18, pady=(10, 18))
    ttk.Button(actions, text="Cancelar", command=on_close, style="Secondary.TButton").pack(side="right")
    ttk.Button(actions, text="Crear pedido", command=create, style="Primary.TButton").pack(side="right", padx=(0, 8))
    dialog.bind("<Escape>", lambda _event: on_close())
    self.center_window(dialog)
    client_entry.focus_set()
