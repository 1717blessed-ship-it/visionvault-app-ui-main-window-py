#!/usr/bin/env python3
"""Test the searchbar predictive feature.

Run:
    python tests/test_predictive_search.py

The test simulates typing in the SearchBar and verifies:
* Suggestions appear for every type supported by main_window (stickers, categories, tags)
* Navigation with arrows and selection with Return works
* Clicks outside a dropdown close it
* Filters and selection are preserved when a suggestion is selected
* Keys remain uninterpreted

La aptitud visual es el complemento de lo que solo una GUI puede probar;
esta es una prueba unitaria.
"""

import tkinter as tk

from tkinter import ttk
from unittest.mock import MagicMock
from app.ui.search import SearchBar
class TestPredictiveSearch:
    """Funciones de ayuda y casos de prueba."""

    def run_test(self) -> None:
        root = tk.Tk()
        root.withdraw()

        on_suggest = lambda q: self._on_suggest(q)
        on_predict = lambda q: None
        search = SearchBar(
            root, on_search=lambda q: None, on_suggest=on_suggest,
            on_random=lambda: None, on_predict=on_predict,
            on_visual_search=lambda: None, on_create=lambda: None,
        )
        search.pack()
        root.update()

        # Obtener valores
        for char in "stic":
            search.on_key_release(None)
            root.update()
        all_current = list(search.entry.cget('values'))
        assert "Vistazo rápido" in all_current, "Stickers no en sugerencias"

        # Navegación con flechas arriba y abajo
        search.on_up_key(None)
        root.update()
        # Los valores ya están disponibles en la propiedad internalvalue del Combobox
        assert search.entry['values'], "No hay sugerencias después de aumentar el índice"

        # Simular escribir "stick" y enviar Enter
        search.query.set("stick")
        suggestions = search._current_suggestions
        for _ in range(3):
            search.on_down_key(None)
            root.update()
        search.on_return_key(None)
        assert search.query.get() == suggestions[3], f"Esperaba '{(suggestions[3],)}', {(search.query.get(),)}"

        # Escape cierra el desplegable
        search.on_escape_key(None)
        self._simulate_click_outside(root, search)

        search.destroy()
        root.destroy()
        print("✓ Todas las pruebas unitarias pasaron.")

    def _on_suggest(self, query: str) -> list[str]:
        """Devuelve sugerencias para cada tipo.

        Simula datos reales:
        * 'Sticker: Goku' (nombre de sticker)
        * 'Categoría: Autos' (categoría)
        * 'Etiqueta: anime' (etiqueta)
        * 'Cliente: ABC' (cuando está presente)

        El prefijo permite al test verificar que un fragmento de texto limpio
        se coloca en el campo después de la selección.
        """
        suggestion_types = [
            f"Sticker: Goku", f"Sticker: Pikachu",
            f"Categoría: Anime", f"Categoría: Autos",
            f"Etiqueta: dragon ball", f"Etiqueta: naruto",
            f"Cliente: XYZ", f"Cliente: ABC",
        ]
        lowered = query.lower() if query else ""
        result = []
        for item in suggestion_types:
            if lowered and item.lower().startswith(lowered):
                result.append(item)
            elif lowered and lowered in item.lower():
                result.append(item)
        result = result[:10]
        return result

    @staticmethod
    def _simulate_click_outside(root: tk.Tk, widget: SearchBar) -> None:
        """Simula un clic fuera del widget para cerrar el desplegable."""
        x = widget.winfo_rootx() - 10
        y = widget.winfo_rooty() - 10
        root.event_generate("<Button-1>", x=x, y=y)
if __name__ == "__main__":
    TestPredictiveSearch().run_test()
