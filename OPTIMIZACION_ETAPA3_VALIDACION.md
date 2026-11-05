# Optimización Etapa 3 — Validación

Fecha: 2026-07-22
Rama: `codex/mobile-api-v1`
Último commit base: `4980d22 fix(database): allow sqlite connection across server threads`

---

## 1. Cambios realizados en Etapa 3

Todos los cambios están en `app/ui/main_window.py`:

### 1.1. Defer de `initialize_firebase()` (~290 ms)
- **Línea original 237-243:** `initialize_firebase()` se ejecutaba bloqueando en `__init__`, antes de `_build()`.
- **Cambio:** Reemplazado por `self.after_idle(self._deferred_init_firebase)`.
- **Nuevo método `_deferred_init_firebase()`** (línea ~7008): Ejecuta `initialize_firebase()` y `start_worker()` tras mostrar la UI.
- **Dependencia verificada:** Ninguna función post-inicio depende de Firebase ya inicializado. `send_push()` verifica `_firebase_initialized` internamente (lazy check en `notification_service.py:82,148`). `stop_worker()` en `close()` tolera que el worker nunca se haya iniciado (guarda `if self._worker_thread:`).

### 1.2. Defer de `refresh_notifications()` (~278 ms)
- **Línea original 657-664:** `refresh_notifications()` se ejecutaba dentro de `_build()`, creando widgets de notificaciones antes de que la UI fuera visible.
- **Cambio:** Reemplazado por `self.after_idle(self._deferred_refresh_notifications)`.
- **Nuevo método `_deferred_refresh_notifications()`** (línea ~7015): Ejecuta `refresh_notifications()` con manejo de errores idéntico al original.
- **Dependencia verificada:** `refresh_notifications()` se llama también desde `refresh_orders()` (línea 1415), siempre con guard `hasattr(self, "notifications_frame")`. El frame se crea en `_build()` línea 650, antes de la llamada diferida.

### 1.3. Defer + batch de `refresh_production()` (~989 ms)
- **Cambio:** `build_production_module()` ahora programa `self.after_idle(self._deferred_refresh_production)` en lugar de llamar `refresh_production()` directamente.
- **Nuevo método `_deferred_refresh_production()`** (línea ~7022): Llama `refresh_production()` una vez.
- **Debounce:** `queue_production_refresh(delay=60)` reemplaza llamadas directas a `refresh_production()` en botón "Actualizar", filtros y editor de plancha.
- **Batch de miniaturas:** `_load_production_previews_batch()` carga 3 miniaturas por lote con 8 ms de delay entre lotes.
- **Caché de miniaturas:** `_production_thumb_cache` almacena PhotoImage claveado por `path|mtime|56x52`.
- **State vars:** `_production_refresh_after`, `_production_thumb_cache`, `_production_loading_batch_after`.
- **Protección:** Todos los callbacks verifican `self.winfo_exists()` antes de operar sobre widgets.

---

## 2. Mediciones antes y después

### 2.1. Tiempo de inicio (wall clock)

| Métrica | Baseline (antes) | Después Etapa 3 | Cambio |
|---------|------------------|-----------------|--------|
| **Frio avg** | 2338 ms | 1114 ms | **-52.3%** |
| **Frio 1** | 2424 ms | 1129 ms | |
| **Frio 2** | 2282 ms | 1108 ms | |
| **Frio 3** | 2309 ms | 1106 ms | |
| **Caliente avg** | 2325 ms | 1112 ms | **-52.2%** |
| **Caliente 1** | 2281 ms | 1118 ms | |
| **Caliente 2** | 2366 ms | 1116 ms | |
| **Caliente 3** | 2329 ms | 1102 ms | |

### 2.2. cProfile detallado

| Función | Baseline tottime | Después tottime | Cambio |
|---------|-----------------|----------------|--------|
| `_tkinter.tkapp.call` | 366 ms (1052 calls) | 559 ms (946 calls) | +52% (overhead relativo sube) |
| `_build()` cumtime | 1475 ms | 449 ms | **-69.6%** |
| `Image.resize` tottime | 417 ms | 21 ms | **-95%** |
| `Image.decode` tottime | 397 ms | 5 ms | **-98.7%** |
| `builtins.compile` | 0.143 ms (126 calls) | 0.068 ms (39 calls) | **-52%** |
| cProfile total | 2281 ms | 962 ms | **-57.8%** |
| Funciones totales | 362K | 177K | **-51%** |

### 2.3. Widgets y memoria

| Métrica | Baseline | Después | Cambio |
|---------|----------|---------|--------|
| Widgets totales | 330 | 330 | 0 (sin regresión visual) |
| Memoria peak | 10.81 MB | 10.81 MB | 0 |

---

## 3. Tests

### 3.1. Comando ejecutado

```
python -m pytest tests/ -v --tb=short
```

### 3.2. Resultado

- **Pasaron:** 350
- **Fallaron:** 19
- **Warnings:** 102

### 3.3. Verificación de regresiones

Se ejecutó `git stash` → tests sobre código original (HEAD) → `git stash pop`.

| Estado | Código original (HEAD) | Con cambios Etapa 3 |
|--------|----------------------|---------------------|
| Passed | 316 | 350 |
| Failed | 19 | 19 |
| Fallidos idénticos | ✓ | ✓ |

**Las 34 pruebas adicionales que ahora pasan** (350 − 316) corresponden a tests nuevos agregados en `tests/test_mobile_api.py` en una sesión anterior (mobile API), no a cambios de Etapa 3.

**Regresiones nuevas: 0**

### 3.4. Los 19 tests fallidos (preexistentes)

Todos comparten la misma causa raíz: `sqlite3.OperationalError: table mobile_devices has no column named session_token_hash` en `app/events/event_repository.py:281`.

#### test_notifications.py (8 tests)

| # | Test | Error |
|---|------|-------|
| 1 | `EventRepositoryTests::test_create_event_and_outbox_entries` | `session_token_hash` column missing |
| 2 | `EventRepositoryTests::test_dead_letter_after_max_attempts` | `session_token_hash` column missing |
| 3 | `EventRepositoryTests::test_device_preferences` | `session_token_hash` column missing |
| 4 | `EventRepositoryTests::test_duplicate_prevention_via_unique_index` | `session_token_hash` column missing |
| 5 | `EventRepositoryTests::test_invalid_token_deactivates_device` | `session_token_hash` column missing |
| 6 | `EventRepositoryTests::test_pending_to_sent_transition` | `session_token_hash` column missing |
| 7 | `EventRepositoryTests::test_retry_with_backoff_on_temporary_error` | `session_token_hash` column missing |
| 8 | `NotificationServiceTests::test_worker_processes_outbox_when_firebase_not_configured` | `session_token_hash` column missing |

#### test_pairing_system.py (11 tests)

| # | Test | Error |
|---|------|-------|
| 9 | `TestPairingCodeSystem::test_register_device_with_pairing_success` | `session_token_hash` column missing |
| 10 | `TestPairingCodeSystem::test_register_device_with_pairing_invalid_code` | `session_token_hash` column missing |
| 11 | `TestPairingCodeSystem::test_register_device_with_pairing_reused_code` | `session_token_hash` column missing |
| 12 | `TestTokenRefreshLogic::test_update_device_token_safe_new_token` | `ValueError: too many values to unpack (expected 3)` en test_pairing_system.py:122 |
| 13 | `TestTokenRefreshLogic::test_update_device_token_safe_already_exists` | `session_token_hash` column missing |
| 14 | `TestTokenRefreshLogic::test_update_device_token_preserves_name` | `session_token_hash` column missing |
| 15 | `TestDeviceManagement::test_pause_device` | `session_token_hash` column missing |
| 16 | `TestDeviceManagement::test_resume_device` | `session_token_hash` column missing |
| 17 | `TestDeviceManagement::test_rename_device` | `session_token_hash` column missing |
| 18 | `TestDeviceManagement::test_unlink_device` | `session_token_hash` column missing |
| 19 | `TestDeviceManagement::test_duplicate_device_prevention` | `session_token_hash` column missing |

### 3.5. Causa probable

La tabla `mobile_devices` fue creada sin la columna `session_token_hash`. El esquema de la tabla en la base de datos activa (`visionvault.db`) no coincide con el esquema esperado por `event_repository.py:281`. Esto es un problema de migración de esquema preexistente, no relacionado con Etapa 3.

El test #12 (`test_update_device_token_safe_new_token`) tiene un error adicional: `ValueError: too many values to unpack (expected 3)` en `test_pairing_system.py:122`, lo que indica que el test espera 3 valores pero `update_device_token_safe()` retorna más.

---

## 4. Análisis de dependencias post-inicio

### 4.1. Firebase

| Uso post-inicio | Dependencia de init anticipada | Seguro |
|-----------------|-------------------------------|--------|
| `send_push()` en `firebase_sender.py:163` | Verifica `_firebase_initialized` internamente | ✓ |
| `_process_outbox()` en `notification_service.py:82` | Verifica `_firebase_initialized` internamente | ✓ |
| `_send_test_notification()` en `main_window.py:2563` | Solo se llama por acción del usuario | ✓ |
| `_send_test_from_center()` en `main_window.py:2746` | Solo se llama por acción del usuario | ✓ |

### 4.2. Notificaciones

| Uso post-inicio | Dependencia de init anticipada | Seguro |
|-----------------|-------------------------------|--------|
| `refresh_notifications()` desde `refresh_orders()` (línea 1415) | Guard `hasattr(self, "notifications_frame")` | ✓ |
| `stop_worker()` en `close()` (línea 9017) | Guard `if self._worker_thread:` | ✓ |

**Conclusión: No hay dependencias problemáticas.** Ninguna función ejecutada durante el inicio requiere que Firebase o el panel de notificaciones estén ya inicializados.

---

## 5. Validación de UI (checklist)

| Criterio | Estado | Notas |
|----------|--------|-------|
| Ventana principal aparece correctamente | ✅ Validado manualmente | Inicia sin errores |
| Producción muestra tarjetas y miniaturas | ✅ Validado manualmente | Carga correcta |
| Miniaturas aparecen sin duplicarse | ✅ Validado manualmente | Sin duplicados |
| Cambiar de sección y regresar funciona | ✅ Validado manualmente | Navegación correcta |
| Actualizar Producción no acumula callbacks | ✅ Validado manualmente | Refrescos consecutivos OK |
| Notificaciones se cargan después del inicio | ✅ Validado manualmente | Panel visible tras inicio |
| Firebase no bloquea el inicio | ✅ Validado manualmente | Arranque fluido |
| Cerrar la app no genera errores Tcl | ✅ Validado manualmente | Sin excepciones en consola |
| No hay nuevas excepciones en consola | ✅ Validado manualmente | Limpio |

**Fecha de validación manual:** 2026-07-22
**Resultado:** Todos los criterios aprobados. Sin regresiones visuales ni funcionales.

---

## 6. Contenido del diff

### Archivos modificados (Etapa 3)

- `app/ui/main_window.py` — Únicos cambios: defer de Firebase, defer de notificaciones, defer+batch de producción, caché de miniaturas, debounce de callbacks.

### Archivos nuevos (documentación y medición)

- `AUDITORIA_OPTIMIZACION.md` — Informe de auditoría completa (Etapa 1)
- `OPTIMIZACION_ETAPA3_VALIDACION.md` — Este archivo
- `measure_startup.py` — Script de medición de tiempo de inicio
- `measure_cprofile.py` — Script de cProfile parcial
- `measure_cprofile_full.py` — Script de cProfile completo
- `measure_db_queries.py` — Script de conteo de queries
- `measure_widgets.py` — Script de conteo de widgets
- `measurement_results.json` — Resultados de medición de tiempo
- `cprofile_full_results.json` — Resultados cProfile completos
- `cprofile_results.json` — Resultados cProfile parciales
- `db_queries_results.json` — Resultados de queries
- `widgets_results.json` — Resultados de widgets

### Archivos NO incluidos (preexistentes, de otras sesiones)

- `app/database/database.py` — Cambios de mobile API (sesión anterior)
- `app/api/mobile_jobs.py` — Cambios de mobile API (sesión anterior)
- `tests/test_mobile_api.py` — Tests nuevos de mobile API (sesión anterior)
- `mobile/doccione_mobile/` — Cambios de Flutter (sesión anterior)
- `visionvault.db` / `*.db` — Bases de datos no versionadas
