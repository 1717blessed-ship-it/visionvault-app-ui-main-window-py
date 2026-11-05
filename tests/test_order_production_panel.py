import tkinter as tk
from types import SimpleNamespace
import pytest

from app.database.database import ImageDatabase
from app.ui.order_production_panel import OrderProductionPanel


@pytest.mark.parametrize('size', ['1040x680', '1280x720', '1600x900', 'maximized'])
def test_panel_sizes_preserve_buttons_and_scroll(tmp_path, size):
    db = ImageDatabase(tmp_path / 'sizes.db')
    oid = db.create_order('Ficticio', quantity=100)
    root = tk.Tk()
    root.geometry(size if size != 'maximized' else '1040x680')
    if size == 'maximized':
        root.state('zoomed')
    panel = OrderProductionPanel(root, db, oid, prepare=lambda _: None, open_planchas=lambda _: None)
    panel.pack(fill='both', expand=True)
    try:
        root.update()
        assert panel.prepare_button.winfo_ismapped()
        assert panel.prepare_button.winfo_x() + panel.prepare_button.winfo_width() <= panel.winfo_width()
        assert panel.jobs_tree.cget('xscrollcommand')
        assert int(panel.detail_label.cget('wraplength')) <= panel.winfo_width()
    finally:
        root.destroy()
        db.close()


def test_timeline_delivery_action_explains_block_without_rewriting_history(tmp_path, monkeypatch):
    from app.ui.main_window import VisionVaultApp
    import app.ui.main_window as main_window
    db = ImageDatabase(tmp_path / 'timeline.db')
    oid = db.create_order('Ficticio', quantity=100)
    root = tk.Tk()
    frame = tk.Frame(root)
    frame.pack()
    notices = []
    monkeypatch.setattr(main_window.messagebox, 'showwarning', lambda title, message, **kw: notices.append(message))
    ui = SimpleNamespace(database=db)
    try:
        before = db.order_events(oid)
        VisionVaultApp._render_order_timeline(ui, frame, dict(db.order(oid)))
        delivery = next(stage for stage in frame.winfo_children()
                        if any(isinstance(w, tk.Label) and w.cget('text') == 'Entregado' for w in stage.winfo_children()))
        next(w for w in delivery.winfo_children() if isinstance(w, tk.Button)).invoke()
        assert notices and 'pendientes 100' in notices[0]
        assert db.order(oid)['status'] != 'Entregado'
        assert db.order_events(oid) == before
    finally:
        root.destroy()
        db.close()


def test_panel_reads_saved_data_updates_external_changes_and_contextual_actions(tmp_path):
    db = ImageDatabase(tmp_path / "panel.db")
    order = db.create_order_with_details("Cliente panel", jobs=[{
        "title": "Stickers", "quantity": 5, "unit_kind": "item", "subtotal": 100,
        "material": "Vinilo", "distribution_policy": "partial",
    }])
    job = db.order_jobs(order)[0]["id"]
    root = tk.Tk()
    root.geometry("1040x500")
    calls = []
    panel = OrderProductionPanel(root, db, order, prepare=lambda ids: calls.append(ids), open_planchas=lambda ids: None)
    panel.pack(fill="both", expand=True)
    try:
        root.update()
        assert panel.jobs_tree.item(str(job), "values")[2] == "5"
        assert str(panel.prepare_button["state"]) == "disabled"
        assert "Bloqueo" in panel.detail.get()
        revision = panel._revision
        external = ImageDatabase(tmp_path / "panel.db")
        external.connection.execute("UPDATE order_jobs SET quantity=7 WHERE id=?", (job,))
        external.connection.commit()
        assert panel._read_revision() != revision
        panel.refresh()
        assert panel.jobs_tree.item(str(job), "values")[2] == "7"
        assert not calls
        assert panel.winfo_width() > 500
        external.close()
    finally:
        root.destroy()
        db.close()
