import tkinter as tk
from tkinter import ttk


class SearchBar(ttk.Frame):
    """Búsqueda predictiva que no altera la consulta hasta confirmarla."""

    def __init__(self, master, on_search, on_suggest, on_random=None, on_recent=None,
                 on_predict=None, on_visual_search=None, on_create=None):
        super().__init__(master, padding=(0, 6), style="Panel.TFrame")
        self.on_search = on_search
        self.on_suggest = on_suggest
        self.on_random = on_random or (lambda: None)
        self.on_recent = on_recent or (lambda: None)
        self.on_predict = on_predict or (lambda _query: None)
        self.on_visual_search = on_visual_search or (lambda: None)
        self.on_create = on_create or (lambda: None)
        self.query = tk.StringVar()
        self.hint = tk.StringVar(value="")
        self.result_summary = tk.StringVar(value="")
        self.pending_prediction = None
        self.pending_suggestions = None
        # -1 significa que se conserva la consulta escrita. Down selecciona
        # recién entonces la primera sugerencia.
        self._suggestion_index = -1
        self._current_suggestions = []
        self._dropdown_open = False

        ttk.Label(self, text="BUSCAR STICKERS", style="Panel.TLabel").pack(side="left", padx=(0, 10))
        ttk.Button(self, text="Crear sticker", command=self.on_create, style="Primary.TButton").pack(side="right")
        ttk.Button(self, text="Buscar sticker", command=self.on_visual_search, style="Secondary.TButton").pack(side="right", padx=(0, 8))
        ttk.Button(self, text="Últimos procesados", command=self.on_recent, style="Secondary.TButton").pack(side="right", padx=(0, 8))
        ttk.Button(self, text="Aleatorios", command=self.on_random, style="Secondary.TButton").pack(side="right", padx=(0, 8))

        self.entry = ttk.Combobox(self, textvariable=self.query)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<KeyRelease>", self.on_key_release)
        self.entry.bind("<Up>", self.on_up_key)
        self.entry.bind("<Down>", self.on_down_key)
        self.entry.bind("<Return>", self.on_return_key)
        self.entry.bind("<Escape>", self.on_escape_key)
        self.entry.bind("<<ComboboxSelected>>", self.on_suggestion_selected)
        self.clear_button = ttk.Button(self, text="Limpiar", command=self.clear, style="Secondary.TButton")
        self.query.trace_add("write", self._update_clear_button)
        ttk.Label(self, textvariable=self.hint, style="PanelMuted.TLabel").pack(side="left", padx=(10, 0))
        ttk.Label(self, textvariable=self.result_summary, style="PanelMuted.TLabel").pack(side="left", padx=(10, 0))

    def set_result_summary(self, total: int, shown: int, query: str = ""):
        """Muestra resultados sin obligar a mirar la barra de estado."""
        if total:
            suffix = f" · mostrando {shown}" if shown < total else ""
            self.result_summary.set(f"{total} resultado(s){suffix}")
        elif query.strip():
            self.result_summary.set("Sin resultados")
        else:
            self.result_summary.set("")

    def on_key_release(self, event):
        if getattr(event, "keysym", "") in {"Up", "Down", "Return", "Escape"}:
            return
        query = self.query.get()
        # Las sugerencias consultan la base de datos. Se agrupan para no hacer
        # una consulta por cada letra escrita, especialmente en bancos grandes.
        if self.pending_suggestions is not None:
            self.after_cancel(self.pending_suggestions)
        self.pending_suggestions = self.after(
            110, lambda text=query: self._request_suggestions(text))
        if self.pending_prediction is not None:
            self.after_cancel(self.pending_prediction)
        self.pending_prediction = self.after(
            180, lambda text=query: self._request_prediction(text))

    def _request_prediction(self, query):
        self.pending_prediction = None
        if query == self.query.get():
            self.on_predict(query)

    def _request_suggestions(self, query):
        self.pending_suggestions = None
        # Si el usuario siguió escribiendo, el pedido quedó obsoleto.
        if query != self.query.get():
            return
        suggestions = self.on_suggest(query)
        self.entry["values"] = suggestions
        self._current_suggestions = suggestions
        self._suggestion_index = -1
        self.hint.set(
            f"{len(suggestions)} sugerencias · ↓ para elegir · Enter para buscar"
            if suggestions else "Enter para buscar · Esc para limpiar"
        )
        if suggestions and len(query.strip()) >= 2:
            self.entry.after_idle(self._show_suggestions)
        else:
            self._close_suggestions()

    def on_up_key(self, _event):
        if self._current_suggestions:
            self._suggestion_index = max(-1, self._suggestion_index - 1)
        return "break"

    def on_down_key(self, _event):
        if self._current_suggestions:
            self._suggestion_index = min(len(self._current_suggestions) - 1, self._suggestion_index + 1)
        return "break"

    def on_return_key(self, _event):
        if self._dropdown_open and self._current_suggestions and self._suggestion_index >= 0:
            self.query.set(self._clean_suggestion(self._current_suggestions[self._suggestion_index]))
        self._close_suggestions()
        self.on_search(self.query.get())
        return "break"

    def on_suggestion_selected(self, _event):
        self.query.set(self._clean_suggestion(self.query.get()))
        self._close_suggestions()
        self.on_search(self.query.get())

    def on_escape_key(self, _event):
        if self.query.get():
            self.clear()
        else:
            self._close_suggestions()
        return "break"

    def clear(self):
        if self.pending_prediction is not None:
            self.after_cancel(self.pending_prediction)
            self.pending_prediction = None
        if self.pending_suggestions is not None:
            self.after_cancel(self.pending_suggestions)
            self.pending_suggestions = None
        self.query.set("")
        self.entry["values"] = ()
        self.hint.set("")
        self._close_suggestions()
        self.on_search("")
        self.entry.focus_set()

    @staticmethod
    def _clean_suggestion(value: str) -> str:
        return value.split(":", 1)[1].strip() if ":" in value else value.strip()

    def _update_clear_button(self, *_args):
        if self.query.get().strip():
            if not self.clear_button.winfo_ismapped():
                self.clear_button.pack(side="left", padx=(8, 0))
        elif self.clear_button.winfo_ismapped():
            self.clear_button.pack_forget()

    def _close_suggestions(self):
        self._suggestion_index = -1
        self._current_suggestions = []
        self._dropdown_open = False
        try:
            self.tk.call("ttk::combobox::Unpost", str(self.entry))
        except tk.TclError:
            pass

    def _show_suggestions(self):
        try:
            self.tk.call("ttk::combobox::Post", str(self.entry))
            self._dropdown_open = True
        except tk.TclError:
            pass
