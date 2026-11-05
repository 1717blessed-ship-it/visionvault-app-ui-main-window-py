"""Ventana real de aceptación, siempre sobre copia SQLite aislada."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.ui.main_window import VisionVaultApp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--size', default='1040x680')
    args = parser.parse_args()
    folder = ROOT / 'artifacts' / 'acceptance-s31-20261023'
    folder.mkdir(exist_ok=True)
    target = folder / f'preview-{args.size}.db'
    if not target.exists():
        source = ROOT / 'artifacts' / 'acceptance-s3-20261023' / '04-remaining.db'
        with sqlite3.connect(f'{source.as_uri()}?mode=ro', uri=True) as src, sqlite3.connect(target) as dst:
            src.backup(dst)
    app = VisionVaultApp(database_path=target, isolated_database=True)
    def show():
        app.title(f'DOCCIONE — VALIDACIÓN AISLADA S3.1 VERIFICADO — {args.size}')
        app.minsize(780, 540)
        app.state('normal')
        if args.size == 'maximized':
            app.after(500, lambda: app.state('zoomed'))
        else:
            app.geometry(args.size + '+20+20')
        app.open_order_workspace(app.database.orders()[0]['id'])
        def show_production():
            tab = next(iter(app.order_tabs.values()))
            canvas = tab.order_scroll_canvas
            panel = tab.production_panel
            body = canvas.nametowidget(canvas.itemcget(canvas.find_all()[0], 'window'))
            y = panel.winfo_rooty() - body.winfo_rooty()
            canvas.yview_moveto(max(0, y - 8) / max(1, body.winfo_height()))
            (folder / f'layout-{args.size}.json').write_text(json.dumps({
                'requested': args.size, 'geometry': app.geometry(), 'state': app.state(),
                'screen': [app.winfo_screenwidth(), app.winfo_screenheight()],
                'tk_pixels_per_inch': app.winfo_fpixels('1i'),
                'tk_scaling': float(app.tk.call('tk', 'scaling')),
                'panel_width': panel.winfo_width(),
            }, indent=2), encoding='utf-8')
        app.after(1500, show_production)
    app.after(5000, show)
    app.mainloop()


if __name__ == '__main__':
    main()
