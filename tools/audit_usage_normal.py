import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
import tracemalloc
import tkinter as tk
from pathlib import Path
from tkinter import ttk

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
DB_ORIGINAL = PROJECT_ROOT / 'visionvault.db'
OUT_DIR = PROJECT_ROOT / 'outputs'
OUT_DIR.mkdir(exist_ok=True)
MEASUREMENTS_PATH = OUT_DIR / 'measurement_usage_normal.json'
CPROFILE_PATH = OUT_DIR / 'cprofile_usage_normal.txt'

from app.database.database import ImageDatabase
from app.ui.main_window import VisionVaultApp
from app.planchas.editor import PlanchaEditor
from app.planchas.model import PlanchaProject
from app.ui.gallery import Gallery


def copy_temp_db():
    fd, path = tempfile.mkstemp(prefix='audit_usage_temp_', suffix='.db', dir=str(OUT_DIR))
    os.close(fd)
    shutil.copy2(DB_ORIGINAL, path)
    return path


def remove_temp_db(path: str):
    try:
        os.remove(path)
    except OSError:
        pass


def create_app(db_path: str):
    app = VisionVaultApp()
    try:
        app.database.close()
    except Exception:
        pass
    app.database = ImageDatabase(db_path)
    return app


def run_headless(app, steps: int = 20):
    for _ in range(steps):
        try:
            app.update_idletasks()
            app.update()
        except Exception:
            pass


def _safe(fn):
    try:
        return fn()
    except Exception:
        pass


def timeit(name, fn, *args, **kwargs):
    t0 = time.perf_counter()
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()
    result = fn(*args, **kwargs)
    after = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    return {
        'name': name,
        'elapsed_ms': elapsed_ms,
        'mem_current_bytes': after[0] - before[0],
        'mem_peak_bytes': after[1] - before[1],
        'result': result,
    }


def cprofile_block(name, fn, *args, **kwargs):
    import cProfile, pstats, io
    t0 = time.perf_counter()
    pr = cProfile.Profile()
    pr.enable()
    try:
        result = fn(*args, **kwargs)
    finally:
        pr.disable()
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats('cumulative').print_stats(40)
    return elapsed_ms, s.getvalue(), result


def pick_temp_image(db: ImageDatabase):
    imgs = db.search(limit=20)
    for img in imgs:
        p = Path(img.get('path', ''))
        if p.exists():
            return str(p)
    raise RuntimeError('No hay imagenes indexadas para medir miniaturas.')


def startup_cold(db_path: str):
    script = textwrap.dedent(f'''import json\nimport sys, time\nfrom pathlib import Path\nsys.path.insert(0, r'{PROJECT_ROOT}')\nimport_times = {{}}\nmods = ['tkinter', 'PIL', 'sqlite3', 'app.database.database', 'app.ui.main_window']\nfor mod in mods:\n    t0 = time.perf_counter()\n    try:\n        __import__(mod)\n    except Exception:\n        pass\n    import_times[mod] = round((time.perf_counter() - t0)*1000,2)\n\nfrom app.database.database import ImageDatabase\nfrom app.ui.main_window import VisionVaultApp\nimport tkinter as tk\nroot = tk.Tk(); root.withdraw()\ndb = ImageDatabase(r'{db_path.replace(chr(92), '/')}')\napp = VisionVaultApp()\nfor _ in range(25):\n    try:\n        app.update_idletasks(); app.update()\n    except Exception:\n        break\napp_init_ms = round((time.perf_counter()-t0)*1000,2)\ntry:\n    app.destroy()\nexcept Exception:\n    pass\nprint(json.dumps({{'import_times': import_times, 'app_init_ms': app_init_ms}}))\n''')
    t0 = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, '-c', script],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=240,
    )
    wall = round((time.perf_counter() - t0) * 1000, 1)
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    out = lines[-1] if lines else '{}'
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        data = {'stdout': proc.stdout, 'stderr': proc.stderr}
    data['wall_clock_ms'] = wall
    return data


def _measure_batch(operations):
    results = {}
    for op_name, fn in operations.items():
        samples = []
        for i in range(1, 4):
            try:
                data = timeit(f'{op_name} #{i}', fn)
                data['iteration'] = i
                samples.append(data)
            except Exception as exc:
                samples.append({'iteration': i, 'name': f'{op_name} #{i}', 'elapsed_ms': None, 'error': repr(exc)})
        results[op_name] = samples
    return results


def main():
    MEASUREMENTS_PATH.unlink(missing_ok=True)
    CPROFILE_PATH.unlink(missing_ok=True)

    temp_db = copy_temp_db()
    try:
        print('DB temporal:', temp_db)
        samples = {
            'startup_cold': [],
            'startup_hot': [],
            'init_operations': [],
            'open_orders': [],
            'switch_orders_and_back': [],
            'refresh_orders': [],
            'open_production': [],
            'gallery_first_load': [],
            'gallery_second_load': [],
            'search_text': [],
            'predict_search': [],
            'create_thumbnail': [],
            'reuse_thumbnail': [],
            'open_plancha_project': [],
            'switch_regular_free': [],
            'refresh_after_temp_change': [],
            'close_app': [],
        }
        cprofile_texts = []

        print('== Cold start x3 ==')
        for i in range(1, 4):
            data = startup_cold(temp_db)
            data['iteration'] = i
            samples['startup_cold'].append(data)
            print(f"  {i}: init {data.get('app_init_ms')} ms, wall {data.get('wall_clock_ms')} ms")
            time.sleep(2)

        print('== Hot start x3 ==')
        for i in range(1, 4):
            data = startup_cold(temp_db)
            data['iteration'] = i
            samples['startup_hot'].append(data)
            print(f"  {i}: init {data.get('app_init_ms')} ms, wall {data.get('wall_clock_ms')} ms")
            time.sleep(1)

        print('== Operaciones headless x3 ==')
        for i in range(1, 4):
            app = create_app(temp_db)
            run_headless(app, steps=20)

            app.tabs.select(app.orders_tab)
            run_headless(app, steps=20)
            t0 = time.perf_counter()
            _safe(lambda: app.queue_orders_refresh(delay=0))
            run_headless(app, steps=80)
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            samples['open_orders'].append({'iteration': i, 'elapsed_ms': elapsed})
            run_headless(app, steps=20)

            app.tabs.select(app.designs_tab)
            run_headless(app, steps=20)
            app.tabs.select(app.orders_tab)
            run_headless(app, steps=20)
            t0 = time.perf_counter()
            _safe(lambda: app.queue_orders_refresh(delay=0))
            run_headless(app, steps=80)
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            samples['switch_orders_and_back'].append({'iteration': i, 'elapsed_ms': elapsed})
            run_headless(app, steps=20)

            t0 = time.perf_counter()
            _safe(lambda: app.refresh_orders())
            run_headless(app, steps=60)
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            samples['refresh_orders'].append({'iteration': i, 'elapsed_ms': elapsed, 'has_orders_frame': hasattr(app, '_orders_cards_frame')})
            run_headless(app, steps=20)

            app.tabs.select(app.production_tab)
            run_headless(app, steps=20)
            t0 = time.perf_counter()
            _safe(lambda: app.refresh_production())
            run_headless(app, steps=80)
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            samples['open_production'].append({'iteration': i, 'elapsed_ms': elapsed})
            run_headless(app, steps=20)

            app.tabs.select(app.designs_tab)
            run_headless(app, steps=20)
            t0 = time.perf_counter()
            _safe(lambda: app.refresh(None))
            run_headless(app, steps=120)
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            samples['gallery_first_load'].append({'iteration': i, 'elapsed_ms': elapsed})
            run_headless(app, steps=20)

            t0 = time.perf_counter()
            _safe(lambda: app.refresh(None))
            run_headless(app, steps=120)
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            samples['gallery_second_load'].append({'iteration': i, 'elapsed_ms': elapsed})
            run_headless(app, steps=20)

            q = 'pegatina'
            app.search.query.set(q)
            t0 = time.perf_counter()
            _safe(lambda: app.refresh(q))
            run_headless(app, steps=80)
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            samples['search_text'].append({'iteration': i, 'elapsed_ms': elapsed})
            run_headless(app, steps=20)

            t0 = time.perf_counter()
            _safe(lambda: app.predict_search(q))
            run_headless(app, steps=80)
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            samples['predict_search'].append({'iteration': i, 'elapsed_ms': elapsed})
            run_headless(app, steps=20)

            from app.indexer.thumbnails import prepare_thumbnail, _cached_thumbnail

            img_path = pick_temp_image(app.database)
            thumb_dir = PROJECT_ROOT / '.cache' / 'thumbnails'
            thumb_dir.mkdir(parents=True, exist_ok=True)
            stat = Path(img_path).stat()
            modified = stat.st_mtime
            hashed = f'{Path(img_path).resolve()}|{modified:.6f}|56x52'
            import hashlib
            digest = hashlib.sha1(hashed.encode('utf-8', errors='surrogatepass')).hexdigest()
            cached = thumb_dir / f'{digest}.png'
            try:
                if cached.exists():
                    cached.unlink()
            except OSError:
                pass
            if hasattr(_cached_thumbnail, 'cache_clear'):
                _cached_thumbnail.cache_clear()

            data = timeit('create_thumbnail', lambda: prepare_thumbnail(img_path, 56, 52, modified))
            samples['create_thumbnail'].append({'iteration': i, 'elapsed_ms': data['elapsed_ms'], 'result': bool(data.get('result'))})

            data = timeit('reuse_thumbnail', lambda: _cached_thumbnail(str(Path(img_path)), 56, 52, modified))
            samples['reuse_thumbnail'].append({'iteration': i, 'elapsed_ms': data['elapsed_ms'], 'result': bool(data.get('result'))})

            run_headless(app, steps=20)
            imgs = app.database.search(limit=10)
            proj = PlanchaProject.from_images(imgs)
            t0 = time.perf_counter()
            editor = PlanchaEditor(app, imgs, database=app.database, library_images=app.database.search(limit=10000), project=proj)
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            samples['open_plancha_project'].append({'iteration': i, 'elapsed_ms': elapsed})
            try:
                if editor.winfo_exists():
                    editor.destroy()
            except Exception:
                pass
            run_headless(app, steps=20)

            free_proj = proj.to_free_project()
            t0 = time.perf_counter()
            free_proj.normalize_project_size()
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            samples['switch_regular_free'].append({'iteration': i, 'elapsed_ms': elapsed})
            del free_proj, proj
            conn = sqlite3.connect(temp_db)
            cur = conn.cursor()
            cur.execute(
                'INSERT INTO orders (client, whatsapp, order_date, status, material, observations, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)',
                ('Audit-Temp', '', time.strftime('%Y-%m-%d'), 'Nuevo', '', 'temporal', time.strftime('%Y-%m-%d %H:%M:%S'), time.strftime('%Y-%m-%d %H:%M:%S')),
            )
            order_id = cur.lastrowid
            conn.commit()
            conn.close()

            _safe(lambda: app.refresh_orders())
            run_headless(app, steps=20)
            t0 = time.perf_counter()
            _safe(lambda: app.refresh_orders())
            run_headless(app, steps=40)
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            samples['refresh_after_temp_change'].append({'iteration': i, 'elapsed_ms': elapsed})

            t0 = time.perf_counter()
            _safe(lambda: app.close())
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            samples['close_app'].append({'iteration': i, 'elapsed_ms': elapsed})
            try:
                app.destroy()
            except Exception:
                pass
            try:
                conn = sqlite3.connect(temp_db)
                cur = conn.cursor()
                cur.execute('DELETE FROM orders WHERE id = ?', (order_id,))
                conn.commit()
                conn.close()
            except Exception:
                pass
            print(f'  iteracion {i} lista')
            time.sleep(1)

        MEASUREMENTS_PATH.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding='utf-8')
        CPROFILE_PATH.write_text('\n\n'.join(cprofile_texts), encoding='utf-8')
        print('Mediciones:', MEASUREMENTS_PATH)
        print('Perfilados:', CPROFILE_PATH)
    finally:
        remove_temp_db(temp_db)


if __name__ == '__main__':
    main()
