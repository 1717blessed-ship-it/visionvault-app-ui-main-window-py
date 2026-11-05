import pytest

from app.ui.module_registry import ModuleRegistry


def test_module_is_loaded_only_once_and_reports_duration():
    calls = []
    metrics = []
    registry = ModuleRegistry(on_loaded=lambda name, elapsed: metrics.append((name, elapsed)))
    registry.register("ventas", lambda: calls.append("loaded") or {"ready": True})

    assert not registry.is_loaded("ventas")
    assert registry.ensure("ventas") == {"ready": True}
    assert registry.ensure("ventas") == {"ready": True}
    assert calls == ["loaded"]
    assert registry.is_loaded("ventas")
    assert metrics[0][0] == "ventas"
    assert registry.metrics()["ventas"] >= 0


def test_failed_module_can_be_retried():
    attempts = []
    registry = ModuleRegistry()

    def factory():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("temporal")
        return "ok"

    registry.register("chat", factory)
    with pytest.raises(RuntimeError, match="temporal"):
        registry.ensure("chat")
    assert not registry.is_loaded("chat")
    assert registry.ensure("chat") == "ok"
