import importlib


def test_manual_smoke_module_imports_without_executing_gui():
    module = importlib.import_module("test_simple")
    assert module.__name__ == "test_simple"
