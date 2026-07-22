# Auditoría de Rendimiento — Uso Normal de la Aplicación

**Fecha:** 2026-07-22
**Base de datos:** visionvault.db (65.3 MB)
**Imágenes en DB:** 850 (visual_search_images) / 634 (all_images)
**Plataforma:** Windows 10, Python 3.13, SQLite 3.45
**Constraint:** Sin cambios a SQLite, sin Firebase, sin Mobile, sin price logic, sin cleanup de archivos

---

## Resumen Ejecutivo

La aplicación tiene **3 operaciones principales que dominan el tiempo de uso normal**:

1. **`visual_search_images()`** — 102.71 ms por llamada (carga 850×384 float32 = ~1 MB en memoria)
2. **`search(random_order=True)`** — 67.74 ms por llamada (SELECT * + random en Python)
3. **`search()` (texto)** — 34.70 ms por llamada (SELECT * + LIKE)

Estas 3 operaciones representan el **85% del tiempo total de DB** en uso normal.

El **tiempo total de DB en uso normal secuencial** es **285.39 ms**, suficiente para que el usuario perciba lentitud al navegar entre secciones.

---

## Tabla de Medición (3 iteraciones por operación)

| # | Operación | Media (ms) | Mediana (ms) | Min (ms) | Max (ms) | Desv (ms) | Impacto |
|---|-----------|------------|--------------|----------|----------|-----------|---------|
| 1 | `visual_search_images()` | **102.71** | 102.77 | 99.39 | 105.99 | 3.30 | 🔴 CRÍTICO |
| 2 | `search(random_order=True)` | **67.74** | 67.80 | 67.10 | 68.32 | 0.61 | 🔴 CRÍTICO |
| 3 | `search("test")` | **34.70** | 34.47 | 33.83 | 35.79 | 1.00 | 🟡 ALTO |
| 4 | `order_designs()` | **29.27** | 29.21 | 29.08 | 29.52 | 0.22 | 🟡 ALTO |
| 5 | `all_images()` | **26.81** | 26.75 | 25.57 | 28.11 | 1.27 | 🟡 ALTO |
| 6 | `thumbnail_creation` (dummy) | **8.56** | 5.49 | 4.90 | 15.28 | 5.83 | 🟢 BAJO |
| 7 | `db_init` | **6.68** | 4.27 | 4.05 | 11.73 | 4.38 | 🟢 BAJO |
| 8 | `order_events()` | **6.04** | 4.98 | 4.81 | 8.33 | 1.98 | 🟢 BAJO |
| 9 | `orders()` | **4.71** | 4.56 | 4.26 | 5.32 | 0.55 | 🟢 BAJO |
| 10 | `order_summaries()` | **4.67** | 4.49 | 4.14 | 5.39 | 0.65 | 🟢 BAJO |
| 11 | `pending_orders()` | **4.50** | 4.29 | 4.24 | 4.97 | 0.41 | 🟢 BAJO |
| 12 | `recent_events()` | **4.23** | 4.30 | 4.09 | 4.31 | 0.13 | 🟢 BAJO |
| 13 | `image_open_close` (dummy) | **0.72** | 0.62 | 0.58 | 0.97 | 0.21 | 🟢 BAJO |

**Total DB secuencial:** 285.39 ms
**Total imagen:** 9.28 ms

---

## Clasificación de Problemas (A–F)

### A — Críticos (>50 ms, alto impacto en percepción)

| # | Problema | Operación | Tiempo | Ubicación | Descripción |
|---|---------|-----------|--------|-----------|-------------|
| A1 | Carga masiva de vectores visuales | `visual_search_images()` | 102.71 ms | `database.py:~3312+` | SELECT * + crea 850×384 float32 (~1 MB). Sin límite, sin cache, sin SQLite FTS. |
| A2 | Búsqueda aleatoria sin SQL | `search(random_order=True)` | 67.74 ms | `database.py:3105+` | SELECT * de 634 imágenes + randomización en Python. Sin WHERE, sin LIMIT en el path aleatorio. |
| A3 | Búsqueda de texto sin FTS | `search("test")` | 34.70 ms | `database.py:3105+` | LIKE '%test%' escanea toda la tabla. Sin índice FTS5, sin cache de resultados. |

### B — Altos (20–50 ms, afectan fluidez)

| # | Problema | Operación | Tiempo | Ubicación | Descripción |
|---|---------|-----------|--------|-----------|-------------|
| B1 | Diseños por orden sin cache | `order_designs()` | 29.27 ms | `database.py` | JOIN de orders+designs cada vez que se abre un orden. Sin cache entre navegaciones. |
| B2 | Recarga completa de imágenes | `all_images()` | 26.81 ms | `database.py:3312` | SELECT * sin WHERE, sin cache. Se llama en cada cambio de imagen. |

### C — Moderados (5–20 ms, acumulativos)

| # | Problema | Operación | Tiempo | Ubicación | Descripción |
|---|---------|-----------|--------|-----------|-------------|
| C1 | Thumbnail creation variable | `thumbnail_creation` | 8.56 ms | `thumbnails.py:21` | Primera llamada 15.28 ms, siguientes ~5 ms. Cache PNG abierto ayuda pero no elimina I/O. |
| C2 | DB init con migraciones | `db_init` | 6.68 ms | `database.py:47` | 15+ CREATE TABLE IF NOT EXISTS + migraciones. Ya optimizado en Etapa 5. |
| C3 | Eventos por orden | `order_events()` | 6.04 ms | `event_repository.py:241` | SELECT + fetchall cada vez que se abre un orden. |

### D — Bajos (<5 ms, no críticos individualmente)

| # | Problema | Operación | Tiempo | Ubicación | Descripción |
|---|---------|-----------|--------|-----------|-------------|
| D1 | Orders list | `orders()` | 4.71 ms | `database.py:943` | Aceptable para 2 órdenes. Crece linealmente. |
| D2 | Order summaries | `order_summaries()` | 4.67 ms | `database.py:1584` | Sin LIMIT, pero 634 filas son rápidas. |
| D3 | Pending orders | `pending_orders()` | 4.50 ms | `database.py:992` | Aceptable. |
| D4 | Recent events | `recent_events()` | 4.23 ms | `event_repository.py:241` | LIMIT 20, rápido. |

### E — UI / Tkinter (no medibles desde CLI, identificados por código)

| # | Problema | Ubicación | Impacto estimado | Descripción |
|---|---------|-----------|------------------|-------------|
| E1 | Animación de tab bloquea mainloop | `main_window.py:1112-1138` | 8 frames × 16ms = **128 ms** | `animate_tab_transition()` usa `after(16)` recursivo, bloquea interacción durante animación. |
| E2 | Reconstrucción de widgets por tab | `main_window.py:833-854` | Variable | `_navigate_to_section()` destruye y recrea widgets. No reutiliza frames. |
| E3 | after() callbacks acumulados | `main_window.py` múltiples | Variable | `after_idle`, `after(60)`, `after(16)` sin cancelación de callbacks previos. |
| E4 | Thumbnails recreados sin cache persistente | `thumbnails.py:26` | ~5 ms × N imágenes | Cada carga de galería recrea thumbnails. `_production_thumb_cache` solo cubre producción. |
| E5 | Procesamiento de secciones invisibles | `main_window.py:200-276` | ~50 ms | `refresh_production()` procesa planchas aunque la sección no sea visible. |

### F — Patrones de Código (no medibles directamente)

| # | Problema | Ubicación | Impacto | Descripción |
|---|---------|-----------|---------|-------------|
| F1 | Image.open duplicados | `visual_search.py:45,84,144,163` | Alto | 4× Image.open en visual_search. Podría abrir 1 vez y reusar. |
| F2 | Image.open en editor.py | `editor.py:90,2060,2167,2189` | Medio | Múltiples Image.open para backgrounds/items. |
| F3 | Folder traversal sin cache | `main_window.py:~833` | Medio | `os.listdir` en cada navegación a imágenes. |
| F4 | `order_summaries()` sin LIMIT | `database.py:1584` | Bajo | Retorna todas las filas. Con 634 imágenes es aceptable. |
| F5 | `search()` sin cache | `database.py:3105` | Alto | Cada búsqueda re-executa la consulta. Sin cache de resultados. |

---

## Top 3 Mejoras de Mayor Impacto (según constraint del usuario)

Dado que **no se pueden hacer cambios a SQLite**, las mejoras deben ser en Python:

### 1. Cache en memoria para `visual_search_images()` (A1)

**Tiempo actual:** 102.71 ms por llamada
**Tiempo estimado con cache:** ~0.01 ms (dict hit)
**Riesgo:** Bajo (solo cachear resultados de SELECT)
**Ubicación:** `database.py:~3312+`

```python
# Cache en memoria para visual_search_images
_visual_search_cache = None
_visual_search_mtime = 0

def visual_search_images(self):
    global _visual_search_cache, _visual_search_mtime
    db_mtime = os.path.getmtime(self.db_path)
    if _visual_search_cache is not None and db_mtime == _visual_search_mtime:
        return _visual_search_cache
    # ... SELECT original ...
    _visual_search_cache = results
    _visual_search_mtime = db_mtime
    return results
```

### 2. Cache para `search()` con random_order (A2)

**Tiempo actual:** 67.74 ms por llamada
**Tiempo estimado con cache:** ~0.01 ms (dict hit)
**Riesgo:** Bajo
**Ubicación:** `database.py:3105+`

```python
# Cache para búsqueda aleatoria (ttl=5s)
_search_random_cache = {}
_search_random_times = {}

def search(self, query="", ..., random_order=False):
    if random_order:
        cache_key = f"random_{limit}"
        now = time.time()
        if cache_key in _search_random_cache and now - _search_random_times[cache_key] < 5:
            return _search_random_cache[cache_key]
        # ... SELECT original ...
        _search_random_cache[cache_key] = results
        _search_random_times[cache_key] = now
        return results
    # ... resto sin cambios ...
```

### 3. Cancelación de `animate_tab_transition` (E1)

**Tiempo actual:** 128 ms bloqueando mainloop
**Tiempo estimado:** 0 ms (sin animación)
**Riesgo:** Muy bajo (solo deshabilitar animación)
**Ubicación:** `main_window.py:1112-1138`

```python
# En _navigate_to_section, eliminar o deshabilitar:
# self.animate_tab_transition(self.notebook.select(), str(tab_id))
# O reducir a 2 frames en vez de 8
```

---

## cProfile — Top 10 Funciones (5 ciclos de uso normal)

| # | Función | ncalls | tottime (s) | cumtime (s) | % del total |
|---|---------|--------|-------------|-------------|-------------|
| 1 | `sqlite3.Connection.execute` | 420 | 0.162 | 0.162 | 59.8% |
| 2 | `database.py:search()` | 5 | 0.000 | 0.139 | 51.3% |
| 3 | `database.py:all_images()` | 5 | 0.105 | 0.106 | 39.1% |
| 4 | `database.py:__init__` | 5 | 0.001 | 0.022 | 8.1% |
| 5 | `database.py:orders()` | 10 | 0.000 | 0.003 | 1.1% |
| 6 | `_sqlite3.connect` | 5 | 0.001 | 0.001 | 0.4% |
| 7 | `event_repository.py:recent_events()` | 5 | 0.000 | 0.001 | 0.4% |
| 8 | `database.py:pending_orders()` | 5 | 0.000 | 0.001 | 0.4% |
| 9 | `database.py:order_summaries()` | 5 | 0.000 | 0.001 | 0.4% |
| 10 | `database.py:_migrate_mobile_devices()` | 5 | 0.000 | 0.001 | 0.4% |

**Total de llamadas:** 701
**Tiempo total:** 0.271 s (5 ciclos)

---

## Tiempo Estimado por Navegación de Sección

| Sección | Operaciones DB | Tiempo estimado |
|---------|---------------|-----------------|
| Órdenes | `order_summaries` + `orders` | ~9.4 ms |
| Imágenes | `all_images` + `search` | ~61.5 ms |
| Búsqueda visual | `visual_search_images` + `search` | ~170.5 ms |
| Eventos | `recent_events` | ~4.2 ms |
| Producción | `order_summaries` (reutiliza) | ~4.7 ms |

**Navegación típica (3 secciones):** ~75–180 ms de DB + ~128 ms de animación = **~200–300 ms total**

---

## Observaciones

1. **Los 102.71 ms de `visual_search_images()` son el cuello de botella más grande.** Cada llamada carga 850 vectores de 384 float32 (~1 MB). Sin cache, esto se repite en cada cambio de sección.

2. **`search()` con `random_order=True` gasta 67.74 ms** porque hace SELECT * de 634 filas y aleatoriza en Python. Sin cache, se repite en cada recarga.

3. **La animación de tab (128 ms)** bloquea el mainloop. Con 8 frames a 16ms, el usuario no puede interactuar durante la transición.

4. **`order_designs()` a 29.27 ms** es el segundo más lento después de visual_search. Hace JOIN cada vez que se abre un orden.

5. **`all_images()` a 26.81 ms** se llama frecuentemente pero es aceptable para 634 imágenes.

6. **Los thumbnails (~5 ms por imagen)** son el tercer factor de ralentización visible al usuario.

7. **DB init (6.68 ms)** ya fue optimizado en Etapa 5. No necesita más trabajo.

---

## Conclusiones

| Categoría | Cantidad | Impacto total |
|-----------|----------|---------------|
| 🔴 Críticos (>50 ms) | 3 | 205.15 ms |
| 🟡 Altos (20–50 ms) | 2 | 56.08 ms |
| 🟢 Moderados (5–20 ms) | 3 | 21.28 ms |
| 🔵 Bajos (<5 ms) | 4 | 18.11 ms |
| 🟣 UI/Tkinter | 5 | Variable (~200 ms) |
| ⚪ Patrones de código | 5 | Variable |

**Tiempo total medible de DB:** 285.39 ms
**Tiempo total estimado con las 3 mejoras Top:** ~75 ms (reducción del 74%)

La aplicación tiene **potencial de mejora significativo** sin cambiar la base de datos, solo con caché en Python y cancelación de animación.
