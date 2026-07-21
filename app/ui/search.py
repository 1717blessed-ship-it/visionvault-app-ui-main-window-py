import tkinter as tk
from tkinter import ttk


class SearchBar(ttk.Frame):
    def __init__(self, master, on_search, on_suggest, on_random, on_predict, on_visual_search, on_create):
        super().__init__(master, padding=(0, 6), style="Panel.TFrame")
        self.on_search = on_search
        self.on_suggest = on_suggest
        self.on_random = on_random
        self.on_predict = on_predict
        self.on_visual_search = on_visual_search
        self.on_create = on_create
        self.query = tk.StringVar()
        self.hint = tk.StringVar(value="")
        self.pending_search = None
        self.pending_prediction = None
        ttk.Label(self, text="BUSCAR STICKERS", style="Panel.TLabel").pack(side="left", padx=(0, 10))
        self.entry = ttk.Combobox(self, textvariable=self.query, width=32)
        self.entry.pack(side="left")
        self.entry.bind("<KeyRelease>", self.on_key_release)
        self.entry.bind("<<ComboboxSelected>>", lambda _event: self.on_predict(self.query.get()))
        ttk.Button(self, text="Aleatorios", command=lambda *a, _fn=self.on_random: _fn(*a), style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(self, text="Buscar sticker", command=lambda *a, _fn=self.on_visual_search: _fn(*a), style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(self, text="Crear sticker", command=lambda *a, _fn=self.on_create: _fn(*a), style="Primary.TButton").pack(side="left", padx=(8, 0))
        ttk.Label(self, textvariable=self.hint, style="PanelMuted.TLabel").pack(side="left", padx=(10, 0))

    def on_key_release(self, _event):
        suggestions = self.on_suggest(self.query.get())
        self.entry["values"] = suggestions
        self.hint.set(f"Etiqueta cercana: {suggestions[0]}" if suggestions else "")
        if self.pending_prediction is not None:
            self.after_cancel(self.pending_prediction)
        query = self.query.get()
        # Evita recargar cincuenta miniaturas por cada letra escrita.
        self.pending_prediction = self.after(180, lambda: self.on_predict(query))
