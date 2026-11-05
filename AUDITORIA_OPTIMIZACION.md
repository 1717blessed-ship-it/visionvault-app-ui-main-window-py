# INFORME DE AUDITORÍA — Doccione Studio
**Proyecto:** `visionvault-app-ui-main-window-py`  
**Fecha:** 2026-07-21

---

## 1. PROBLEMAS CRÍTICOS

### 1.1 Seguridad: `eval()` con datos del usuario
- **Archivo:** `app/database/database.py:1374`
- `eval(condition, {"__builtins__": {}}, ctx)` evalúa condiciones de reglas de costo desde la BD. Aunque restringe builtins, es escapable.

### 1.2 `except:` sin tipo (3 instancias)
- `app/ui/main_window.py:8358` — Además usa variable `e` de un bloque anterior, causaría `NameError` si se ejecuta primero.
- `app/stickers/editor.py:1657` y `:1732`

### 1.3 Métodos duplicados en la misma clase (silenciosamente sobrescritos)
| Método | 1ª definición (muerta) | 2ª definición (activa) |
|--------|----------------------|----------------------|
| `open_order_workspace` | `:1253` | `:3332` |
| `refresh_order_workspace` | `:1259` | `:6383` |
| `link_selection_to_order` | `:1276` | `:6390` |
| `_add_component` | `:5319` | `:5957` |
| `cost_rule_domain` | `:2218` | `:2279` |
| `save_cost_rule_domain` | `:2242` | `:2304` |

### 1.4 Lógica incompleta
- `app/ui/main_window.py:5151-5152` — `if mode == "percentage": pass` — El modo porcentaje está sin implementar, calcula cero silenciosamente.

### 1.5 Bloque muerto `try: pass except: pass`
- `app/ui/main_window.py:1098-1102` — Inútil y confuso.

---

## 2. RIESGOS DE RENDIMIENTO

### 2.1 Constructor gigante de BD al inicio
- `app/database/database.py:46-713` — **712 líneas** que crean 35+ tablas, 30+ índices, 6 migraciones e instalan catálogo de precios. Todo síncrono en el hilo principal.

### 2.2 Patrón N+1 en consultas (11 instancias)
| Ubicación | Descripción |
|-----------|-------------|
| `database.py:824-836` | `_migrate_order_jobs()` — DELETE + INSERT por cada fila |
| `database.py:920-922` | `_migrate_order_clients()` — SELECT + UPDATE por fila |
| `database.py:1628-1684` | `price_rule_presentations()` — SELECT por cada regla |
| `database.py:2022-2035` | `install_doccione_price_catalog()` — SELECT + INSERT por entrada del catálogo (~50+) |
| `database.py:3294-3295` | `approve_processed_sticker()` — `add_tag()` por cada tag |
| `database.py:3635-3637` | `remove_missing()` — SELECT all + DELETE + stat por imagen |
| `event_repository.py:164-180` | `publish_event()` — SELECT + INSERT por cada dispositivo |
| `database.py:766-780` | `_write_order_jobs()` — Sin `executemany()` |
| `database.py:3256-3260` | `save_sticker_processing()` — Sin `executemany()` |

### 2.3 Sin transacciones en operaciones multi-statement
- `delete_image()` (`:3620`) — 9 DELETEs sin transacción
- `create_print_job()` (`:4050-4087`) — 2 commits separados
- `register_order_payment()` (`:1529`) — UPDATE fuera del context manager

### 2.4 Imágenes sin caché
- **30+ llamadas** `Image.open()` sin caché en `main_window.py` y `stickers/editor.py`
- **15+ recreaciones** de `PhotoImage` sin reutilización

### 2.5 `.after()` callbacks sin cancelación
- **59 llamadas** `.after()` vs solo **10** `after_cancel()`
- `main_window.py:2830` — Autocomplete de cliente dispara query de BD sin debounce

### 2.6 `SELECT *` en tablas anchas
- **36 instancias** de `SELECT *`. Las más costosas:
  - Línea 3105: `images.*` (20+ columnas) en cada resultado de búsqueda
  - Línea 3722: `plancha_projects.*` incluye `project_json` enorme
  - Línea 1621: `price_rules.*` (15+ columnas)

### 2.7 Sin `VACUUM`/`ANALYZE`
- Ninguna optimización periódica de SQLite. La BD crecerá indefinidamente.

### 2.8 Sin PRAGMAs de SQLite
- Sin WAL, sin `synchronous=NORMAL`, sin `cache_size`. Todo con valores por defecto.

---

## 3. CÓDIGO POSIBLEMENTE SIN USO

### 3.1 Archivos muertos en `app/`
| Archivo | Motivo |
|---------|--------|
| `app/stickers/pipeline_fix.py` | Duplica funciones de `pipeline.py`, no funciona como módulo independiente |
| `app/ui/Stick new.code-workspace` | Archivo de VSCode, no se carga por Python |
| `app/stickers/INSTRUCCIONES_CORRECCION_BORDE_BLANCO.md` | Documentación de debug |
| `app/assets/doccione_studio.ico.backup` | Backup del icono |
| `app/assets/icons/generate_pngs.py` | Script de generación, no parte de la app |
| `app/assets/icons/generate_pngs_pillow.py` | Script de generación, no parte de la app |
| `app/google-services.json` | Firebase config misplaced (pertenece al proyecto Flutter) |
| `app/scripts/convert_icon.py` | Script de conversión, no se importa |

### 3.2 Código muerto en `app/ui/main_window.py`
- Línea 1253-1276: 3 stubs legacy sobrescritos
- Línea 1098-1102: `try: pass except: pass`
- Import duplicado: `from pathlib import Path` (líneas 15 y 17)
- Import potencialmente no usado: `import tempfile` (línea 13)

### 3.3 Código muerto en `app/database/database.py`
- Líneas 62-77: Bloque de prints comentados (debug temporal)
- Líneas 2218-2339: Métodos `cost_rule_domain` y `save_cost_rule_domain` definidos dos veces
- `EventRepository.create_tables()` — Nunca se llama, las tablas ya existen

### 3.4 Archivos duplicados en root
| Archivo | Cantidad |
|---------|----------|
| Archivos de diagnóstico (`inspect_*.py`, `diagnose_*.py`, `debug_*.py`) | 20 |
| Tests dispersos en root (no en `tests/`) | 9 |
| Scripts temporales (`tmp_*.py`, `_fix_*.py`, etc.) | 5 |

### 3.5 Vendor duplicado
| Ubicación | Contenido | Usado |
|-----------|-----------|-------|
| `runtime_deps/` | PIL + tkinterdnd2 (~16 MB) | SÍ |
| `app/vendor/` | PIL + tkinterdnd2 (~16 MB) | NO — Copia redundante |
| `third_party/` | PIL (~19 MB) | NO — Copia redundante |

---

## 4. ARCHIVOS POSIBLEMENTE ELIMINABLES

### 4.1 Backups de BD (~137.6 MB)
| Archivo | Referencias | Seguridad | Recomendación |
|---------|-------------|-----------|---------------|
| `visionvault_antes_renombrar_20260719_143444.db` | Ninguna | ALTO | Archivar |
| `visionvault_antes_renombrar_20260719_143753.db` | Ninguna | ALTO | Archivar |
| `visionvault_antes_renombrar_20260719_143951.db` | Ninguna | ALTO | Archivar |
| `visionvault_backup_20260719_144406.db` | Ninguna | ALTO | Archivar |
| `visionvault_backup_20260719_144417.db` | Ninguna | ALTO | Archivar |
| `visionvault_backup_limpiar_20260719_145924.db` | Ninguna | ALTO | Archivar |
| `visionvault_backup_movepath_20260719_145242.db` | Ninguna | ALTO | Archivar |
| `visionvault_backup_mover_20260719_145448.db` | Ninguna | ALTO | Archivar |
| `visionvault_backup_reindex_20260719_144905.db` | Ninguna | ALTO | Archivar |

### 4.2 Archivos temporales/diagnóstico (55 archivos)
| Tipo | Cantidad | Seguridad |
|------|----------|-----------|
| `.log` | 5 | ALTO |
| `.txt` de debug | 4 | ALTO |
| `.csv` de mapeo | 5 | ALTO |
| `.json` de dump | 1 | ALTO |
| `.py` de debug/inspección | 20 | ALTO |
| `.py` test en root | 9 | MEDIO |
| `.md` temporales | 22 | ALTO |
| `.png` test output | 1 | ALTO |
| `.bat` duplicados | 2 | ALTO |

### 4.3 Vendor duplicado (~35 MB)
| Ubicación | Seguridad | Recomendación |
|-----------|-----------|---------------|
| `app/vendor/` | ALTO | Eliminar (redundante con `runtime_deps/`) |
| `third_party/` | ALTO | Eliminar (redundante con `runtime_deps/`) |

---

## 5. CADENAS O TEXTOS INCOMPLETOS

### 5.1 Corrupción de encoding (Mojibake) — 10 instancias
| Archivo | Línea | Texto corrupto |
|---------|-------|----------------|
| `app/database/database.py` | 1103 | `recuperaciÃ³n` → recuperación |
| `app/database/database.py` | 1137 | `diseÃ±os`, `operaciÃ³n` → diseños, operación |
| `app/database/database.py` | 1143 | `IndicÃ¡` → Indicá |
| `app/planchas/model.py` | 160 | `posiciÃ³n` → posición |
| `app/planchas/model.py` | 170 | `ImplementaciÃ³n` → Implementación |
| `app/planchas/model.py` | 434 | `producciÃ³n` → producción |
| `app/planchas/model.py` | 436 | `diseÃ±os`, `tamaÃ±o` → diseños, tamaño |
| `app/planchas/model.py` | 438-439 | `autorizÃ³`, `rotaciÃ³n`, `asÃ­` → autorizó, rotación, así |
| `app/stickers/pipeline.py` | 2922 | `diseÃ±o` → diseño |
| `app/stickers/pipeline.py` | 2923 | `despuÃ©s` → después |

### 5.2 Texto temporal visible al usuario
- `app/ui/main_window.py:1091` — `"Panel de producción (temporal)"` — Placeholder visible en la UI

### 5.3 `print()` en código de producción (12 instancias)
- 6 en `main_window.py` (errores de icono + simulador de costos)
- 6 en `stickers/editor.py` (archivos no encontrados, errores de carga)

---

## 6. MEJORAS SEGURAS

| # | Cambio | Riesgo |
|---|--------|--------|
| 1 | Eliminar imports no usados (`tempfile`, Path duplicado) | BAJO |
| 2 | Eliminar los 3 stubs legacy en `main_window.py` | BAJO |
| 3 | Eliminar `pipeline_fix.py` y código muerto en `database.py` | BAJO |
| 4 | Mover tests del root a `tests/` | BAJO |
| 5 | Agregar PRAGMA `journal_mode=WAL` y `cache_size` | BAJO |
| 6 | Reemplazar `executemany()` en batch inserts | BAJO |
| 7 | Corregir mojibake en docstrings | BAJO |
| 8 | Eliminar `print()` debug → `logging` | BAJO |
| 9 | Agregar `with` context manager a `Image.open()` | BAJO |
| 10 | Eliminar vendor duplicado (`app/vendor/`, `third_party/`) | MEDIO |
| 11 | Mover archivos temporales a `archive_cleanup_review/` | BAJO |

---

## 7. CAMBIOS QUE REQUIEREN REVISIÓN MANUAL

| # | Cambio | Riesgo | Motivo |
|---|--------|--------|--------|
| 1 | Eliminar `eval()` de costos | ALTO | Requiere reemplazar con AST eval o similar |
| 2 | Eliminar `except Exception: pass` en BD | MEDIO | Algunos son intencionales (fallback silencioso) |
| 3 | Refactorizar constructor de BD (712 líneas) | MEDIO | Migraciones pesadas podrían romper inicio |
| 4 | Mover N+1 queries a batch | MEDIO | Puede afectar lógica de eventos |
| 5 | Corregir `if mode == "percentage": pass` | MEDIO | Requiere implementar la lógica faltante |
| 6 | Eliminar prints de `main_window.py` | BAJO | Solo si se agrega logging |
| 7 | Mover backups a `archive_cleanup_review/` | BAJO | Verificar que no se usan para recovery |
| 8 | Agregar cancelación de `.after()` callbacks | MEDIO | Puede afectar flujo de debounce |
| 9 | Mover `main.py` imports pesados a lazy loading | MEDIO | Requiere verificar orden de init |
| 10 | Unificar `cost_rule_domain()` duplicado | BAJO | Verificar cuál es la versión correcta |

---

## Resumen de Impacto

| Categoría | Archivos | Espacio |
|-----------|----------|---------|
| Backups de BD archivables | 9 | ~137.6 MB |
| Vendor duplicado eliminable | ~564 | ~35 MB |
| Archivos temporales/diagnóstico | ~68 | ~small |
| **Total recuperable** | **~641 archivos** | **~173 MB** |
