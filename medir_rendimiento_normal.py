"""Medición de rendimiento durante uso normal de la aplicación.

Ejecuta las operaciones clave identificadas en la auditoría y mide
tiempos de cada una. Correr 3 veces y guardar resultados.
"""
import sys
import os
import time
import statistics
import sqlite3
import cProfile
import pstats
import io

# Añadir el directorio del proyecto al path
sys.path.insert(0, os.path.dirname(__file__))

from app.database.database import ImageDatabase

# ── Configuración de mediciones ──────────────────────────────────────────────
NUM_ITERACIONES = 3
DB_PATH = os.path.join(os.path.dirname(__file__), "visionvault.db")
RESULTS_FILE = os.path.join(os.path.dirname(__file__), "RESULTADOS_RENDIMIENTO.md")

# ── Resultados ───────────────────────────────────────────────────────────────
resultados = {}


def medir(nombre, func, num_iter=NUM_ITERACIONES):
    """Mide una función num_iter veces, retorna stats."""
    tiempos = []
    for i in range(num_iter):
        t0 = time.perf_counter()
        resultado = func()
        t1 = time.perf_counter()
        tiempos.append((t1 - t0) * 1000)  # ms
    return {
        "media": statistics.mean(tiempos),
        "mediana": statistics.median(tiempos),
        "min": min(tiempos),
        "max": max(tiempos),
        "desv": statistics.stdev(tiempos) if len(tiempos) > 1 else 0,
        "iteraciones": tiempos,
    }


# ── Operaciones de base de datos ─────────────────────────────────────────────
def test_order_summaries():
    db = ImageDatabase()
    return db.order_summaries()

def test_orders():
    db = ImageDatabase()
    return db.orders()

def test_all_images():
    db = ImageDatabase()
    return db.all_images()

def test_search_visual():
    db = ImageDatabase()
    return db.search(query="", random_order=True, limit=50)

def test_search_text():
    db = ImageDatabase()
    return db.search(query="test")

def test_pending_orders():
    db = ImageDatabase()
    return db.pending_orders()

def test_order_events():
    db = ImageDatabase()
    ordenes = db.orders()
    if ordenes:
        return db.order_events(ordenes[0]["id"])
    return []

def test_recent_events():
    db = ImageDatabase()
    return db.event_repo.recent_events()

def test_order_designs():
    db = ImageDatabase()
    ordenes = db.orders()
    if ordenes:
        return db.order_designs(ordenes[0]["id"])
    return []

def test_visual_search_images():
    db = ImageDatabase()
    return db.visual_search_images()

# ── Operaciones de imagen/thumbnail ──────────────────────────────────────────
def test_thumbnail_creation():
    """Mide creación de thumbnail 56x52."""
    from PIL import Image
    import io
    # Crear imagen dummy de 200x200
    img = Image.new("RGB", (200, 200), color="red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    times = []
    for _ in range(10):
        t0 = time.perf_counter()
        with Image.open(buf) as thumbnail:
            thumbnail = thumbnail.copy()
            thumbnail.thumbnail((56, 52), Image.Resampling.LANCZOS)
        buf.seek(0)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)
    return statistics.mean(times)

def test_image_open_close():
    """Mide abrir y cerrar imagen 100x100."""
    from PIL import Image
    import io
    img = Image.new("RGB", (100, 100), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    times = []
    for _ in range(10):
        t0 = time.perf_counter()
        with Image.open(buf) as im:
            im.load()
        buf.seek(0)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)
    return statistics.mean(times)

# ── Operaciones de archivos ──────────────────────────────────────────────────
def test_folder_scan():
    """Mide escaneo de carpeta de imágenes."""
    import glob
    t0 = time.perf_counter()
    # Buscar imágenes en imágenes_generales
    base = os.path.join(os.path.dirname(__file__), "imágenes_generales")
    if os.path.exists(base):
        exts = ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.heic")
        files = []
        for ext in exts:
            files.extend(glob.glob(os.path.join(base, "**", ext), recursive=True))
        t1 = time.perf_counter()
        return {"count": len(files), "time_ms": (t1 - t0) * 1000}
    return {"count": 0, "time_ms": 0}

# ── Operaciones de imports ───────────────────────────────────────────────────
def test_import_tkinter():
    t0 = time.perf_counter()
    import tkinter
    t1 = time.perf_counter()
    return (t1 - t0) * 1000

def test_import_pillow():
    t0 = time.perf_counter()
    from PIL import Image, ImageTk
    t1 = time.perf_counter()
    return (t1 - t0) * 1000

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("MEDICIÓN DE RENDIMIENTO - USO NORMAL")
    print("=" * 60)

    # 1. Imports
    print("\n[1/15] Imports...")
    resultados["import_tkinter"] = medir("import_tkinter", test_import_tkinter)
    resultados["import_pillow"] = medir("import_pillow", test_import_pillow)

    # 2. Inicialización de base de datos
    print("[2/15] DB init...")
    resultados["db_init"] = medir("db_init", lambda: ImageDatabase())

    # 3. Operaciones de BD
    print("[3/15] order_summaries()...")
    resultados["order_summaries"] = medir("order_summaries", test_order_summaries)

    print("[4/15] orders()...")
    resultados["orders"] = medir("orders", test_orders)

    print("[5/15] all_images()...")
    resultados["all_images"] = medir("all_images", test_all_images)

    print("[6/15] search(visual)...")
    resultados["search_visual"] = medir("search_visual", test_search_visual)

    print("[7/15] search(text)...")
    resultados["search_text"] = medir("search_text", test_search_text)

    print("[8/15] pending_orders()...")
    resultados["pending_orders"] = medir("pending_orders", test_pending_orders)

    # 4. Operaciones de eventos
    print("[9/15] order_events()...")
    resultados["order_events"] = medir("order_events", test_order_events)

    print("[10/15] recent_events()...")
    resultados["recent_events"] = medir("recent_events", test_recent_events)

    print("[11/15] order_designs()...")
    resultados["order_designs"] = medir("order_designs", test_order_designs)

    print("[12/15] visual_search_images()...")
    resultados["visual_search_images"] = medir("visual_search_images", test_visual_search_images)

    # 5. Operaciones de imagen
    print("[13/15] Thumbnail creation...")
    resultados["thumbnail_creation"] = medir("thumbnail_creation", test_thumbnail_creation)

    print("[14/15] Image open/close...")
    resultados["image_open_close"] = medir("image_open_close", test_image_open_close)

    # 6. Escaneo de archivos
    print("[15/15] Folder scan...")
    scan = test_folder_scan()
    resultados["folder_scan"] = {"media": scan["time_ms"], "count": scan["count"]}

    # Generar reporte
    print("\n" + "=" * 60)
    print("GENERANDO REPORTE...")
    print("=" * 60)

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        f.write("# Resultados de Medición - Rendimiento en Uso Normal\n\n")
        f.write(f"Fecha: {time.strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"Iteraciones por operación: {NUM_ITERACIONES}\n\n")

        f.write("## Tabla de Resultados\n\n")
        f.write("| Operación | Media (ms) | Mediana (ms) | Min (ms) | Max (ms) | Desv (ms) |\n")
        f.write("|-----------|------------|--------------|----------|----------|----------|\n")

        for nombre, stats in resultados.items():
            if "iteraciones" in stats:
                f.write(f"| {nombre} | {stats['media']:.2f} | {stats['mediana']:.2f} | {stats['min']:.2f} | {stats['max']:.2f} | {stats['desv']:.2f} |\n")
            else:
                f.write(f"| {nombre} | {stats['media']:.2f} | - | - | - | - |\n")

        f.write("\n## Detalle por Iteración\n\n")
        for nombre, stats in resultados.items():
            if "iteraciones" in stats:
                f.write(f"### {nombre}\n")
                for i, t in enumerate(stats["iteraciones"]):
                    f.write(f"- Iteración {i+1}: {t:.2f} ms\n")
                f.write("\n")

        # Resumen
        total_db = sum(resultados[k]["media"] for k in ["order_summaries", "orders", "all_images", "search_visual", "search_text", "pending_orders", "order_events", "recent_events", "order_designs", "visual_search_images"])
        total_image = resultados["thumbnail_creation"]["media"] + resultados["image_open_close"]["media"]

        f.write("## Resumen\n\n")
        f.write(f"- **Tiempo total DB (medición secuencial):** {total_db:.2f} ms\n")
        f.write(f"- **Tiempo total imagen:** {total_image:.2f} ms\n")
        f.write(f"- **DB init:** {resultados['db_init']['media']:.2f} ms\n")
        f.write(f"- **Folder scan:** {resultados['folder_scan']['media']:.2f} ms ({resultados['folder_scan']['count']} archivos)\n")

    print(f"\nResultados guardados en: {RESULTS_FILE}")

    # También ejecutar profiling
    print("\nEjecutando cProfile de uso normal...")
    pr = cProfile.Profile()
    pr.enable()

    # Ejecutar operaciones típicas de uso normal
    for _ in range(5):
        db = ImageDatabase()
        db.order_summaries()
        db.orders()
        db.pending_orders()
        db.all_images()
        db.search(query="test")
        db.event_repo.recent_events()

    pr.disable()
    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
    ps.print_stats(30)
    print(s.getvalue())

    # Guardar perfil
    with open("PROFILE_USO_NORMAL.txt", "w", encoding="utf-8") as f:
        ps = pstats.Stats(pr, stream=f).sort_stats("cumulative")
        ps.print_stats(50)

    print("\n¡Medición completada!")


if __name__ == "__main__":
    main()
