from app.stickers.editor import StickerStudio


class DummyWidget:
    def __init__(self, name, master=None):
        self.name = name
        self.master = master
        self.scroll_calls = []

    def yview_scroll(self, *args):
        self.scroll_calls.append(args)


class DummyBindingWidget:
    def __init__(self):
        self.bindings = []

    def bind(self, sequence, handler, add=""):
        self.bindings.append((sequence, handler, add))
        return sequence

    def winfo_children(self):
        return []

    def yview_scroll(self, *args):
        self.scroll_calls.append(args)


class DummyScrollWidget(DummyWidget):
    def __init__(self, name, master=None):
        super().__init__(name, master)
        self.scroll_calls = []


def test_mousewheel_scrolls_queue_when_cursor_is_over_treeview():
    studio = StickerStudio.__new__(StickerStudio)
    studio.winfo_exists = lambda: True
    studio.winfo_containing = lambda *_args: queue_widget
    studio.winfo_pointerx = lambda: 0
    studio.winfo_pointery = lambda: 0
    studio._widget_is_inside = StickerStudio._widget_is_inside.__get__(studio, StickerStudio)

    panel_widget = DummyScrollWidget("panel")
    queue_widget = DummyScrollWidget("queue", master=panel_widget)
    studio.queue_panel = panel_widget
    studio.queue = queue_widget

    event = type("Event", (), {"delta": 120})()
    result = studio._on_studio_mousewheel(event)

    assert result == "break"
    assert queue_widget.scroll_calls == [(-1, "units")]


def test_bind_studio_mousewheel_registers_queue_handlers():
    studio = StickerStudio.__new__(StickerStudio)
    studio.bind_all = lambda *args, **kwargs: None
    studio.queue_panel = DummyBindingWidget()
    studio.queue = DummyBindingWidget()

    studio._bind_studio_mousewheel()

    assert any(binding[0] == "<MouseWheel>" for binding in studio.queue_panel.bindings)
    assert any(binding[0] == "<Button-4>" for binding in studio.queue_panel.bindings)
    assert any(binding[0] == "<Button-5>" for binding in studio.queue_panel.bindings)
