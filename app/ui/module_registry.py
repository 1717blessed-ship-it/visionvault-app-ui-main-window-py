"""Carga bajo demanda de módulos de interfaz independientes."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable


Factory = Callable[[], Any]


@dataclass
class ModuleEntry:
    name: str
    factory: Factory
    loaded: bool = False
    loading: bool = False
    instance: Any = None
    load_ms: float = 0.0
    error: Exception | None = None


class ModuleRegistry:
    """Evita construir pestañas pesadas hasta que realmente se utilizan."""

    def __init__(self, *, on_loaded: Callable[[str, float], None] | None = None):
        self._entries: dict[str, ModuleEntry] = {}
        self.on_loaded = on_loaded

    def register(self, name: str, factory: Factory) -> None:
        if name in self._entries:
            raise ValueError(f"El módulo '{name}' ya está registrado.")
        self._entries[name] = ModuleEntry(name=name, factory=factory)

    def ensure(self, name: str) -> Any:
        entry = self._entries.get(name)
        if not entry:
            raise KeyError(f"Módulo no registrado: {name}")
        if entry.loaded:
            return entry.instance
        if entry.loading:
            return entry.instance
        entry.loading = True
        started = perf_counter()
        try:
            entry.instance = entry.factory()
            entry.loaded = True
            entry.error = None
            return entry.instance
        except Exception as error:
            entry.error = error
            raise
        finally:
            entry.loading = False
            entry.load_ms = (perf_counter() - started) * 1000
            if entry.loaded and self.on_loaded:
                self.on_loaded(name, entry.load_ms)

    def is_loaded(self, name: str) -> bool:
        entry = self._entries.get(name)
        return bool(entry and entry.loaded)

    def statuses(self) -> dict[str, dict[str, Any]]:
        """Estado auditable de cada conexión de interfaz registrada."""
        return {
            name: {
                "loaded": entry.loaded,
                "loading": entry.loading,
                "load_ms": entry.load_ms,
                "error": str(entry.error) if entry.error is not None else "",
            }
            for name, entry in self._entries.items()
        }

    def metrics(self) -> dict[str, float]:
        return {name: entry.load_ms for name, entry in self._entries.items() if entry.loaded}
