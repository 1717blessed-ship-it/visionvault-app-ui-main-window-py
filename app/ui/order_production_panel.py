"""Seguimiento persistido, compacto y sin edición de estados inferidos."""
import tkinter as tk
from tkinter import ttk

from app.services.order_production_service import OrderProductionService


class OrderProductionPanel(ttk.LabelFrame):
    def __init__(self, parent, database, order_id, *, prepare, open_planchas):
        super().__init__(parent, text="PRODUCCIÓN DEL PEDIDO", padding=8)
        self.service = OrderProductionService(database)
        self.order_id = order_id
        self.prepare = prepare
        self.open_planchas = open_planchas
        self.snapshot = None
        self._revision = None
        self._timer = None
        actions = ttk.Frame(self)
        actions.pack(fill="x")
        ttk.Button(actions, text="Actualizar", command=self.refresh).pack(side="right")
        self.prepare_button = ttk.Button(actions, text="Preparar seleccionados", command=self._prepare,
                                         style="Primary.TButton", state="disabled")
        self.prepare_button.pack(side="left")
        ttk.Label(self, text="Avance físico persistido · Seleccioná trabajos", style="Muted.TLabel").pack(anchor="w")
        notebook = ttk.Notebook(self)
        notebook.pack(fill="x", pady=6)
        work = ttk.Frame(notebook)
        batches = ttk.Frame(notebook)
        notebook.add(work, text="Avance por trabajo")
        notebook.add(batches, text="Tandas relacionadas")
        columns = ("product", "unit", "requested", "distributed", "available", "finished", "pending")
        self.jobs_tree = ttk.Treeview(work, columns=columns, show="headings", height=4, selectmode="extended")
        for key, label, width in (
            ("product", "Producto / variante · material", 220), ("unit", "Unidad", 65),
            ("requested", "Solicitado", 95), ("distributed", "Distribuido", 110),
            ("available", "Preparable", 105), ("finished", "Terminado", 100), ("pending", "Falta terminar", 130),
        ):
            self.jobs_tree.heading(key, text=label)
            self.jobs_tree.column(key, width=width, minwidth=width, stretch=False, anchor="w" if key == "product" else "center")
        self.jobs_tree.pack(fill="x")
        horizontal = ttk.Scrollbar(work, orient="horizontal", command=self.jobs_tree.xview)
        horizontal.pack(fill="x")
        self.jobs_tree.configure(xscrollcommand=horizontal.set)
        self.detail = tk.StringVar(value="")
        self.detail_label = ttk.Label(work, textvariable=self.detail, wraplength=400, justify="left")
        self.detail_label.pack(fill="x", pady=5)
        self.jobs_tree.bind("<<TreeviewSelect>>", self._selection)
        self.batches_tree = ttk.Treeview(batches, columns=("name", "status", "planchas"), show="headings", height=4)
        for key, title in (("name", "Tanda"), ("status", "Estado"), ("planchas", "Planchas del pedido")):
            self.batches_tree.heading(key, text=title)
        self.batches_tree.pack(fill="x")
        batch_scroll = ttk.Scrollbar(batches, orient="horizontal", command=self.batches_tree.xview)
        batch_scroll.pack(fill="x")
        self.batches_tree.configure(xscrollcommand=batch_scroll.set)
        self.open_button = ttk.Button(batches, text="Consultar planchas", command=self._open_batch, state="disabled")
        self.open_button.pack(anchor="e", pady=4)
        self.batches_tree.bind("<<TreeviewSelect>>", lambda _e: self.open_button.configure(
            state="normal" if self.batches_tree.selection() else "disabled"))
        self.notice = tk.StringVar(value="")
        self.notice_label = ttk.Label(self, textvariable=self.notice, style="Muted.TLabel", wraplength=400)
        self.notice_label.pack(fill="x")
        self.bind("<Configure>", self._resize, add="+")
        self.bind("<Destroy>", self._destroyed, add="+")
        self.refresh()
        self._timer = self.after(2000, self._poll)

    def refresh(self):
        try:
            data = self.service.snapshot(self.order_id)
        except ValueError as error:
            self.notice.set(str(error))
            self.prepare_button.configure(state="disabled")
            return
        self.snapshot = data
        selected = self.jobs_tree.selection()
        self.jobs_tree.delete(*self.jobs_tree.get_children())
        for job in data["jobs"]:
            unit = {"item": "Unidades", "sheet": "Hojas"}.get(job["unit_kind"], "Sin definir")
            title = " · ".join(str(v) for v in (job["product"], job["variant"], job["material"]) if v)
            self.jobs_tree.insert("", "end", iid=str(job["order_job_id"]), values=(
                title, unit, f"{job['requested']:g}", f"{job['distributed']:g}",
                f"{job['available']:g}", f"{job['finished']:g}", f"{job['pending_finish']:g}"))
        restored = [key for key in selected if self.jobs_tree.exists(key)]
        if restored:
            self.jobs_tree.selection_set(restored)
        elif data["jobs"]:
            self.jobs_tree.selection_set(str(data["jobs"][0]["order_job_id"]))
        self.batches_tree.delete(*self.batches_tree.get_children())
        self.open_button.configure(state="disabled")
        for batch in data["batches"]:
            self.batches_tree.insert("", "end", iid=str(batch["id"]), values=(
                f"#{batch['id']} · {batch['name']}", {"prepared": "Preparada", "cancelled": "Cancelada"}.get(batch["status"], batch["status"]), batch["plancha_ids"]))
        self.notice.set(f"Entrega: {data['delivery_status']}. {data['delivery_note']} "
                        "Liberada = reserva cancelada, no entrega. Los acumulados incluyen las etapas posteriores."
                        + ("\n" + "\n".join(data.get("anomalies", [])) if data.get("anomalies") else ""))
        self._selection()
        self._revision = self._read_revision()

    def _selection(self, _event=None):
        if not self.snapshot:
            return
        selected = set(self.jobs_tree.selection())
        jobs = [j for j in self.snapshot["jobs"] if str(j["order_job_id"]) in selected]
        enabled = bool(jobs) and all(j["available"] > 0 and not j["blocked_reason"] for j in jobs)
        self.prepare_button.configure(state="normal" if enabled else "disabled")
        if not jobs:
            self.detail.set("Seleccioná un trabajo para consultar sus saldos y bloqueos.")
            return
        j = jobs[0]
        self.detail.set(
            f"{j['product']} · {j['variant']} · {j['material']}\nSolicitado {j['requested']:g} · Falta terminar {j['pending_finish']:g}\n{j['design_count']} diseño(s) · Sin distribuir {j['undistributed']:g} · "
            f"Asignado sin preparar {j['assigned_unprepared']:g}\n"
            f"Ahora: preparada sin imprimir {j['prepared_current']:g} · Impresa sin terminar {j['printed_current']:g} · "
            f"Terminada {j['finished']:g} · Reservas liberadas registradas {j['released']:g}\n"
            f"Acumulado activo: preparado {j['prepared_accumulated']:g} · Impreso {j['printed_accumulated']:g} · "
            f"Pendiente de imprimir {j['pending_print']:g}"
            + (f"\nBloqueo: {j['blocked_reason']}" if j["blocked_reason"] else "")
            + (f"\n{len(jobs)} trabajos seleccionados; el detalle corresponde al primero." if len(jobs) > 1 else ""))

    def _resize(self, event):
        if event.widget is self:
            width = max(180, event.width-24)
            self.detail_label.configure(wraplength=width)
            self.notice_label.configure(wraplength=width)

    def _prepare(self):
        self.prepare([int(key) for key in self.jobs_tree.selection()])

    def _open_batch(self):
        selected = self.batches_tree.selection()
        if selected:
            batch = next(b for b in self.snapshot["batches"] if str(b["id"]) == selected[0])
            self.open_planchas([int(v) for v in batch["plancha_ids"].split(",")])

    def _read_revision(self):
        connection = self.service.connection
        return connection.execute("PRAGMA data_version").fetchone()[0], connection.total_changes

    def _poll(self):
        self._timer = None
        if self.winfo_ismapped() and self._read_revision() != self._revision:
            self.refresh()
        self._timer = self.after(2000, self._poll)

    def _destroyed(self, event):
        if event.widget is self and self._timer:
            self.after_cancel(self._timer)
            self._timer = None
