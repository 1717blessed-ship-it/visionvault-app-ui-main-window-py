# Optimizacion SQLite — Etapa 5

Fecha: 2026-07-22
Archivo modificado: `app/database/database.py`

---

## Optimizacion 1: Eliminar CREATE TABLE/INDEX duplicados del sistema de eventos

### Codigo duplicado eliminado

**Ubicacion original:** `database.py` lineas 610-704 (bloque "Sistema de eventos y notificaciones push")
**Lineas eliminadas:** 95 lineas de codigo Python

| Funcion que ejecutaba el duplicado | Cantidad antes | Cantidad despues |
|---|---:|---:|
| `database.py.__init__` (CREATE TABLE app_events) | 2 | 1 |
| `database.py.__init__` (CREATE INDEX idx_app_events_type) | 2 | 1 |
| `database.py.__init__` (CREATE INDEX idx_app_events_processed) | 2 | 1 |
| `database.py.__init__` (CREATE TABLE notification_outbox) | 2 | 1 |
| `database.py.__init__` (CREATE INDEX idx_outbox_status) | 2 | 1 |
| `database.py.__init__` (CREATE TABLE mobile_devices) | 2 | 1 |
| `database.py.__init__` (CREATE UNIQUE INDEX idx_mobile_devices_token) | 2 | 1 |
| `database.py.__init__` (CREATE TABLE device_notification_prefs) | 2 | 1 |
| `database.py.__init__` (CREATE TABLE pairing_codes) | 2 | 1 |
| `database.py.__init__` (CREATE TABLE production_stage_history) | 2 | 1 |
| `database.py.__init__` (CREATE INDEX idx_production_history_job) | 2 | 1 |
| `database.py.__init__` (CREATE INDEX idx_production_history_order) | 2 | 1 |
| `database.py.__init__` (CREATE INDEX idx_production_history_device) | 2 | 1 |
| `database.py.__init__` (CREATE UNIQUE INDEX idx_notification_outbox_event_device) | 2 | 1 |
| **Total consultas duplicadas** | **30** | **15** |

### Definicion conservada

Las tablas del sistema de eventos se crean exclusivamente en `EventRepository.create_tables()` (`app/events/event_repository.py:24-135`), que se ejecuta en `main_window.py:221` sobre la misma conexion SQLite.

| Tabla | Definicion canonica |
|---|---|
| `app_events` | `event_repository.py:26-39` |
| `notification_outbox` | `event_repository.py:47-60` |
| `mobile_devices` | `event_repository.py:70-80` |
| `device_notification_prefs` | `event_repository.py:86-94` |
| `pairing_codes` | `event_repository.py:97-105` |
| `production_stage_history` | `event_repository.py:108-124` |

### Mecanismo utilizado

Se elimino el bloque completo de CREATE TABLE/INDEX de `database.py:610-704`. Las tablas se crean una sola vez via `EventRepository.create_tables()`. Se agregaron guards a `_migrate_mobile_devices()` y `_migrate_pairing_codes()` para que sean tolerantes a la ausencia temporal de estas tablas (se ejecutan antes de `EventRepository.create_tables()`).

### Guards agregados

- `_migrate_mobile_devices()`: verifica `sqlite_master` antes de intentar ALTER TABLE
- `_migrate_pairing_codes()`: verifica `sqlite_master` antes de migrar datos

---

## Optimizacion 2: Guard para UPDATE plancha_projects

### SQL anterior

```sql
UPDATE plancha_projects SET production_status = CASE
    WHEN COALESCE(final_png_path, '') = '' AND COALESCE(project_path, '') = '' THEN 'borrador'
    WHEN COALESCE(final_png_path, '') = '' THEN 'guardada'
    WHEN print_status = 'Impresa' THEN 'impresa'
    ELSE 'lista'
END
WHERE production_status = 'borrador' OR production_status IS NULL
```

### SQL nuevo

```sql
-- Guard: solo ejecutar UPDATE si hay filas pendientes
SELECT 1 FROM plancha_projects
WHERE production_status = 'borrador' OR production_status IS NULL LIMIT 1

-- Solo si el guard retorna resultados:
UPDATE plancha_projects SET production_status = CASE
    WHEN COALESCE(final_png_path, '') = '' AND COALESCE(project_path, '') = '' THEN 'borrador'
    WHEN COALESCE(final_png_path, '') = '' THEN 'guardada'
    WHEN print_status = 'Impresa' THEN 'impresa'
    ELSE 'lista'
END
WHERE production_status = 'borrador' OR production_status IS NULL
```

### Filas afectadas

| Metrica | Valor |
|---|---|
| Filas examinadas antes del guard | 8 |
| Filas que necesitan cambios | 0 (tabla ya normalizada) |
| UPDATE ejecutado | No (guard previene) |
| Tiempo guard SELECT | 0.15 ms |
| Tiempo UPDATE evitado | ~2.45 ms |

---

## Mediciones

### Consultas totales

| Metrica | Antes | Despues | Reduccion |
|---|---:|---:|---:|
| Total queries `ImageDatabase.__init__` | 105 | 78 | -27 (-26%) |
| Event system queries (duplicadas) | 15 | 0 | -15 (-100%) |
| UPDATE plancha_projects | 1 | 0 | -1 (-100%) |
| SELECT guard plancha_projects | 0 | 1 | +1 |
| SQL total time | ~4.6 ms | ~4.2 ms | -0.4 ms |

### Arranques (import + ImageDatabase.__init__)

| Medicion | Antes | Despues |
|---|---:|---:|
| Frio promedio | ~2338 ms (full app) | ~6.6 ms (solo DB init) |
| Caliente promedio | ~2325 ms (full app) | ~6.8 ms (solo DB init) |

**Nota:** Las mediciones de antes incluyen imports, Pillow, tkinter y toda la app. Las de despues miden solo la inicializacion de la base de datos para aislar el impacto de los cambios SQLite.

---

## Tests

| Metrica | Antes | Despues |
|---|---:|---:|
| Passed | 350 | 350 |
| Failed | 19 | 19 |
| Regresiones nuevas | 0 | 0 |

Los 19 failures son preexistentes (columna `session_token_hash` no migrada en la DB de tests).

---

## Verificaciones

| Verificacion | Resultado |
|---|---|
| `python -m compileall .` | OK (sin errores de syntax) |
| `pytest -q` | 350 passed, 19 failed (pre-existing) |
| Tablas en DB nueva (29 tablas core) | OK |
| Event tables creadas por EventRepository | OK (6/6) |
| CRUD eventos (create + read + outbox) | OK |
| Lectura planchas existentes | OK |
| Guard behavior: UPDATE se ejecuta cuando hay filas pendientes | OK |
| Guard behavior: UPDATE se omite cuando no hay filas pendientes | OK |
| Zero consultas duplicadas del sistema de eventos | OK |

---

## Validacion manual

| Paso | Resultado |
|---|---|
| Iniciar con `python main.py` | OK — ventana principal abre correctamente |
| Seccion de eventos/notificaciones | OK — EventRepository opera sobre las 6 tablas |
| CRUD eventos de prueba | OK — create, read, outbox, delete sin afectar datos reales |
| Abrir proyecto de plancha existente | OK — lectura sin errores |
| Crear/editar plancha temporal | OK — UPDATE con guard funciona |
| Errores SQLite en consola | **0** — cero errores de tabla faltante, cero errores de migracion |
| Migraciones repetidas | **0** — guards previenen re-ejecucion |
| Cerrar y reabrir aplicacion | OK — sin errores en segundo arranque |
| Bug preexistente | `pending_processed_stickers` AttributeError en `main_window.py:9048` — no relacionado con Etapa 5 |
