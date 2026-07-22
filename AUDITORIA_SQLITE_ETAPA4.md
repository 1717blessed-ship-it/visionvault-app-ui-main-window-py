# Auditoría SQLite — Etapa 4

Fecha: 2026-07-22
Base de datos: `visionvault.db` (65.3 MB, 36 tablas)
Total de consultas durante arranque: **105**
Tiempo total de arranque (wall clock): **1443.5 ms**
Tiempo total de ejecución SQL capturado: **~13.3 ms** (el resto: imports, tkinter, Pillow, deferred tasks)

---

## 1. Tabla de consultas del arranque

| # | Consulta / Función | Veces | Tiempo (ms) | Motivo | Optimización | Clase |
|---|---|---:|---:|---|---|---|
| 1 | `UPDATE plancha_projects SET production_status = CASE...` — `database.py:480(__init__)` | 1 | 2.45 | Full table scan (`SCAN plancha_projects`), sin índice en `production_status`. Evalúa CASE para cada fila cada vez que inicia. | Guard con `SELECT COUNT(*) > 0` antes del UPDATE, o agregar `WHERE production_status = 'borrador'` más específico; posiblemente migrar a migración one-shot. | **B** |
| 2 | `CREATE TABLE IF NOT EXISTS images` — `database.py:100(__init__)` | 1 | 1.33 | Primer CREATE TABLE del init. Tabla de 5058 filas. El engine verifica el esquema. | No se puede evitar: es la creación de la tabla principal. Conservar. | **F** |
| 3 | `SELECT orders.* ... FROM orders LEFT JOIN ...` (orders()) — `database.py:1063(orders)` | 1 | 0.71 | Query compleja con 3 subqueries correlacionadas (designs, planchas, clients). Ejecutada durante `build_orders_module()`. ORDER BY con temp B-tree. | Cachear resultado si se llama múltiples veces. La query es correcta; los subqueries usan índices (BLOOM FILTER). | **A** |
| 4 | `PRAGMA table_info(images)` — `database.py:106` | 1 | 0.12 | Verificación de columnas para migración. Solo 1 llamada. | Conservar: necesario para migraciones incrementales. | **F** |
| 5 | `SELECT orders.* ... WHERE order_jobs.id IS NULL` (_migrate_order_jobs) — `database.py:819` | 1 | 0.10 | Migración: busca pedidos sin jobs. Full scan en orders (2 filas). | Guard: solo ejecutar si es la primera vez (flag en app_settings). | **B** |
| 6 | `PRAGMA table_info(orders)` — `database.py:234` | 1 | 0.06 | Verificación de columnas para migración. | Conservar. | **F** |
| 7 | `SELECT id, client, whatsapp FROM orders WHERE client_id IS NULL` (_migrate_order_clients) — `database.py:917` | 1 | 0.06 | Migración: busca pedidos sin client_id. Solo 2 filas. | Guard: solo ejecutar si es la primera vez. | **B** |
| 8 | `SELECT setting_value FROM app_settings WHERE setting_key = ?` (app_setting) — `database.py:2923` | 1 | 0.03 | Lectura de configuración. 1 sola llamada durante init. | Conservar. Podría cachearse si se repite. | **F** |
| 9 | `CREATE TABLE IF NOT EXISTS app_events` — `database.py:611` | **2** | 0.09 | **DUPLICADO**: Creado en database.py __init__ y otra vez en event_repository.py create_tables(). 15 consultas duplicadas idénticas. | Eliminar las 15 CREATE TABLE/INDEX de `database.py:611-704`, ya que `EventRepository.create_tables()` las ejecuta inmediatamente después. | **B** |
| 10 | `CREATE INDEX IF NOT EXISTS idx_app_events_type` — `database.py:626` | **2** | 0.06 | DUPLICADO (ver #9). | Eliminar de database.py. | **B** |
| 11 | `CREATE INDEX IF NOT EXISTS idx_app_events_processed` — `database.py:627` | **2** | 0.06 | DUPLICADO (ver #9). | Eliminar de database.py. | **B** |
| 12 | `CREATE TABLE IF NOT EXISTS notification_outbox` — `database.py:628` | **2** | 0.05 | DUPLICADO (ver #9). | Eliminar de database.py. | **B** |
| 13 | `CREATE INDEX IF NOT EXISTS idx_outbox_status` — `database.py:643` | **2** | 0.05 | DUPLICADO (ver #9). | Eliminar de database.py. | **B** |
| 14 | `CREATE TABLE IF NOT EXISTS mobile_devices` — `database.py:644` | **2** | 0.05 | DUPLICADO (ver #9). | Eliminar de database.py. | **B** |
| 15 | `CREATE UNIQUE INDEX IF NOT EXISTS idx_mobile_devices_token` — `database.py:656` | **2** | 0.05 | DUPLICADO (ver #9). | Eliminar de database.py. | **B** |
| 16 | `CREATE TABLE IF NOT EXISTS device_notification_prefs` — `database.py:657` | **2** | 0.05 | DUPLICADO (ver #9). | Eliminar de database.py. | **B** |
| 17 | `CREATE TABLE IF NOT EXISTS pairing_codes` — `database.py:668` | **2** | 0.05 | DUPLICADO (ver #9). | Eliminar de database.py. | **B** |
| 18 | `CREATE TABLE IF NOT EXISTS production_stage_history` — `database.py:679` | **2** | 0.05 | DUPLICADO (ver #9). | Eliminar de database.py. | **B** |
| 19 | `CREATE INDEX IF NOT EXISTS idx_production_history_job` — `database.py:697` | **2** | 0.05 | DUPLICADO (ver #9). | Eliminar de database.py. | **B** |
| 20 | `CREATE INDEX IF NOT EXISTS idx_production_history_order` — `database.py:698` | **2** | 0.05 | DUPLICADO (ver #9). | Eliminar de database.py. | **B** |
| 21 | `CREATE INDEX IF NOT EXISTS idx_production_history_device` — `database.py:699` | **2** | 0.05 | DUPLICADO (ver #9). | Eliminar de database.py. | **B** |
| 22 | `CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_outbox_event_device` — `database.py:701` | **2** | 0.05 | DUPLICADO (ver #9). | Eliminar de database.py. | **B** |
| 23 | `PRAGMA table_info(plancha_projects)` — `database.py:452` | 1 | 0.05 | Verificación de columnas para migración. | Conservar. | **F** |
| 24 | `CREATE TABLE IF NOT EXISTS cost_rules` — `database.py:297` | 1 | 0.07 | Schema init. | Conservar. | **F** |
| 25 | `PRAGMA table_info(order_jobs)` — `database.py:286` | 1 | 0.05 | Verificación de columnas. | Conservar. | **F** |
| 26 | `PRAGMA table_info(price_rules)` — `database.py:419` | 1 | 0.05 | Verificación de columnas. | Conservar. | **F** |
| 27 | `PRAGMA table_info(cost_rules)` — `database.py:327` | 1 | 0.05 | Verificación de columnas. | Conservar. | **F** |
| 28 | `PRAGMA table_info(order_designs)` — `database.py:338` | 1 | 0.05 | Verificación de columnas. | Conservar. | **F** |
| 29 | `PRAGMA table_info(clients)` — `database.py:231` | 1 | 0.04 | Verificación de columnas. | Conservar. | **F** |
| 30 | `PRAGMA table_info(sticker_processing_jobs)` — `database.py:185` | 1 | 0.05 | Verificación de columnas. | Conservar. | **F** |
| 31-46 | Resto de CREATE TABLE/INDEX (schema init) — `database.py:139-607` | 1 c/u | 0.01-0.07 c/u | Creación de tablas e índices. Todas con IF NOT EXISTS. | Conservar todas. Son el esquema base. | **F** |
| 47-50 | Migraciones: `_migrate_mobile_devices` (PRAGMA + ALTER + CREATE INDEX) — `database.py:927-942` | 1 c/u | 0.01 c/u | Migración de columnas de session. | Guard: solo ejecutar si columnas faltan (ya lo hace con `if column not in`). | **F** |
| 51 | `_migrate_pairing_codes` (PRAGMA) — `database.py:947` | 1 | 0.01 | Verificación de migración de hash. | Conservar (ya tiene guard). | **F** |
| 52-54 | `_migrate_sync_indexes` (3 CREATE INDEX) — `database.py:981-987` | 1 c/u | 0.01 c/u | Índices de sincronización. IF NOT EXISTS. | Conservar. Ya son idempotentes. | **F** |
| 55-68 | Todas las CREATE TABLE/INDEX de `event_repository.py:26-134` | 1 c/u | 0.04-0.08 c/u | Creación de tablas del sistema de eventos. | Conservar en event_repository.py (eliminando duplicación de database.py). | **F** |

---

## 2. Resumen de duplicación

**15 consultas duplicadas** ejecutadas exactamente 2 veces cada una:

| Tabla / Índice | database.py líneas | event_repository.py líneas |
|---|---|---|
| `app_events` | 611-624 | 26-39 |
| `idx_app_events_type` | 626 | 41 |
| `idx_app_events_processed` | 627 | 44 |
| `notification_outbox` | 628-641 | 47-60 |
| `idx_outbox_status` | 643 | 62 |
| `idx_notification_outbox_event_device` | 701-703 | 66-68 |
| `mobile_devices` | 644-654 | 70-80 |
| `idx_mobile_devices_token` | 656 | 82 |
| `device_notification_prefs` | 657-665 | 86-94 |
| `pairing_codes` | 668-676 | 97-105 |
| `production_stage_history` | 679-695 | 108-124 |
| `idx_production_history_job` | 697 | 126 |
| `idx_production_history_order` | 698 | 129 |
| `idx_production_history_device` | 699 | 132 |

**Tiempo desperdiciado:** ~0.7 ms (15 queries × ~0.04 ms promedio)

**Causa:** `database.py.__init__` crea las tablas del sistema de eventos (líneas 611-704), y luego `main_window.py:221` llama `EventRepository.create_tables()` que crea las mismas tablas. El `CREATE TABLE IF NOT EXISTS` previene errores pero cada verificación cuesta tiempo.

---

## 3. EXPLAIN QUERY PLAN

### 3.1. `UPDATE plancha_projects` (2.45 ms)
```
SCAN plancha_projects
```
Sin índice en `production_status`. Full table scan sobre 8 filas. Evalúa CASE para cada fila. Con más planchas, el costo crece linealmente.

### 3.2. `orders()` query (0.71 ms)
```
MATERIALIZE metrics
  SCAN order_designs USING INDEX sqlite_autoindex_order_designs_1
MATERIALIZE plancha_counts
  SCAN plancha_projects                        ← FULL SCAN, sin índice
  USE TEMP B-TREE FOR GROUP BY
SCAN orders USING INDEX idx_orders_date
SEARCH clients USING INTEGER PRIMARY KEY LEFT-JOIN
BLOOM FILTER ON metrics (order_id=?)
SEARCH metrics USING AUTOMATIC COVERING INDEX LEFT-JOIN
BLOOM FILTER ON plancha_counts (order_id=?)
SEARCH plancha_counts USING AUTOMATIC COVERING INDEX LEFT-JOIN
USE TEMP B-TREE FOR LAST TERM OF ORDER BY
```
El cuello de botella es el subquery `plancha_counts`: full table scan + temp B-tree para GROUP BY.

### 3.3. `_migrate_order_jobs` (0.10 ms)
```
SCAN orders
SEARCH order_jobs USING COVERING INDEX idx_order_jobs_order LEFT-JOIN
```
Full scan sobre orders (2 filas). Con más pedidos, crece linealmente.

---

## 4. Clasificación de propuestas

### A. Reutilización de resultados en memoria
| Propuesta | Impacto | Riesgo |
|---|---|---|
| Cachear resultado de `orders()` si se llama múltiples veces durante init (se ejecuta al menos en `build_orders_module` y `refresh_notifications`). | Bajo | Bajo |

### B. Eliminación de consultas duplicadas
| Propuesta | Impacto | Riesgo |
|---|---|---|
| **Eliminar las 15 CREATE TABLE/INDEX de `database.py:611-704`** que duplican `EventRepository.create_tables()`. | Alto (15 queries eliminadas, ~0.7 ms + simplificación del código) | Bajo |
| **Eliminar `_migrate_order_jobs` y `_migrate_order_clients`** ejecutándose cada init. Agregar flag `migration_done` en `app_settings`. | Medio (2 queries + 1 lectura de settings eliminadas) | Medio (si se pierde el flag, la migración no se ejecuta) |
| **Eliminar el `UPDATE plancha_projects`** del init. Mover a migración one-shot con flag. | Alto (2.45 ms eliminadas) | Medio (si se pierde el flag, la migración no se ejecuta) |

### C. Agrupación de consultas
| Propuesta | Impacto | Riesgo |
|---|---|---|
| Combinar los 3 CREATE INDEX de `_migrate_sync_indexes` en un solo bloque ejecutado condicionalmente. | Bajo | Bajo |

### D. Índices potenciales
| Propuesta | Impacto | Riesgo |
|---|---|---|
| `CREATE INDEX IF NOT EXISTS idx_plancha_status ON plancha_projects(production_status)` — aceleraría el UPDATE y el subquery de `orders()`. | Medio (mejora performance del UPDATE y subquery) | Medio (requiere schema change, pero el usuario dijo no modificar esquema todavía) |

### E. Cambios que no conviene realizar
| Propuesta | Motivo |
|---|---|
| Eliminar los PRAGMA table_info | Necesarios para migraciones incrementales. Sin ellos, las ALTER TABLE se ejecutarían innecesariamente. |
| Eliminar las CREATE TABLE IF NOT EXISTS | Son el esquema base. Sin ellas la app no funciona. |
| Modificar el esquema de orders() | La query es correcta y bien optimizada (usa BLOOM FILTER, covering indexes). |
| Cachear PRAGMA table_info | El overhead de PRAGMA es mínimo (0.01-0.06 ms). |

### F. Consultas necesarias que deben conservarse
| Consulta | Motivo |
|---|---|
| Todas las CREATE TABLE IF NOT EXISTS (36 tablas) | Son el esquema base de la aplicación. |
| Todos los PRAGMA table_info (7 llamadas) | Necesarios para migraciones incrementales. |
| `_migrate_mobile_devices` (4 ALTER TABLE + 1 CREATE INDEX) | Migración de columnas de session. Ya tiene guards. |
| `_migrate_pairing_codes` (1 PRAGMA) | Verificación de migración. Ya tiene guard. |
| `_migrate_sync_indexes` (3 CREATE INDEX) | Índices de sincronización. IF NOT EXISTS. |
| `app_setting()` (1 SELECT) | Lectura de configuración. Necesaria. |

---

## 5. Top 3 optimizaciones SQLite de mayor impacto y menor riesgo

### 🥇 #1: Eliminar las 15 CREATE TABLE/INDEX duplicadas de event system

**Archivo:** `app/database/database.py:611-704`
**Consultas eliminadas:** 15
**Tiempo recuperado:** ~0.7 ms
**Riesgo:** Bajo

**Qué:** Eliminar las líneas 610-704 de `database.py.__init__` que crean `app_events`, `notification_outbox`, `mobile_devices`, `device_notification_prefs`, `pairing_codes`, `production_stage_history` y sus 9 índices. Estas tablas ya son creadas por `EventRepository.create_tables()` que se ejecuta inmediatamente después en `main_window.py:221`.

**Por qué es seguro:** `EventRepository.create_tables()` ejecuta las mismas 15 operaciones con `CREATE TABLE/INDEX IF NOT EXISTS`. La duplicación es un error de diseño donde database.py absorbió el esquema de event_repository pero no eliminó la llamada original.

### 🥈 #2: Migrar UPDATE plancha_projects a migración one-shot

**Archivo:** `app/database/database.py:480-488`
**Tiempo recuperado:** ~2.45 ms
**Riesgo:** Bajo-Medio

**Qué:** El `UPDATE plancha_projects SET production_status = CASE...` se ejecuta cada init y hace full table scan. Moverlo a una migración con flag en `app_settings` (`plancha_status_migration_done`). Solo se ejecuta la primera vez o después de una actualización de esquema.

**Por qué es seguro:** El UPDATE solo afecta filas con `production_status = 'borrador' o NULL`. Una vez ejecutado, no tiene efecto en siguientes init. El flag previene re-ejecución.

### 🥉 #3: Agregar índice en `plancha_projects(production_status)`

**Archivo:** `app/database/database.py` (nuevo CREATE INDEX)
**Tiempo recuperado:** Variable (mejora el UPDATE y el subquery de orders())
**Riesgo:** Medio (requiere schema change, pero con IF NOT EXISTS es seguro)

**Qué:** Agregar `CREATE INDEX IF NOT EXISTS idx_plancha_status ON plancha_projects(production_status)` después de la tabla. Esto elimina el full scan del UPDATE y acelera el subquery `plancha_counts` en `orders()`.

**Restricción del usuario:** "No crear índices todavía". Esta propuesta se queda registrada para cuando se levante esa restricción.

---

## 6. Resumen cuantitativo

| Categoría | Queries | Tiempo (ms) | % del SQL total |
|---|---:|---:|---:|
| Schema init (necesarias) | 68 | ~5.0 | 37.6% |
| Migraciones (necesarias) | 14 | ~0.3 | 2.3% |
| **Duplicadas (event system)** | **15** | **~0.7** | **5.3%** |
| **UPDATE plancha_projects** | **1** | **~2.45** | **18.4%** |
| Migraciones one-shot ejecutándose cada init | 2 | ~0.16 | 1.2% |
| orders() + app_setting() | 2 | ~0.74 | 5.6% |
| **Total** | **105** | **~13.3** | **100%** |

**SQL total = 13.3 ms de 1443.5 ms de arranque (0.9%)**

Las consultas SQL no son el cuello de botella del arranque. El mayor impacto viene de las imágenes (Pillow resize/decode ~30 ms), imports (~250 ms), y tkinter widget creation (~400 ms). Sin embargo, las optimizaciones SQL propuestas son de bajo riesgo y eliminan código muerto/duplicado.
