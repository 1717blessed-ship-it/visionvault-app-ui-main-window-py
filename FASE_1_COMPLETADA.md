# Fase 1: API REST Móvil - Completada ✅

**Rama:** `codex/mobile-api-v1`  
**Base:** `baseline-mobile-v1` (commit `c845ba3`)  
**Commits:** 5 bloques implementados

## Resumen de Implementación

La Fase 1 se centró en expandir y robustecer la API REST móvil con nuevos endpoints y mejoras en validación/manejo de errores.

### Bloque 1: Endpoints de Referencia
**Commit:** `a469d77`

Nuevos endpoints agregados a `/api/mobile/reference/*`:

- **GET `/api/mobile/reference/stages`**
  - Retorna catálogo completo de etapas de producción
  - Incluye: key, label, category, description, color
  - Cache-Control: 1 hora

- **GET `/api/mobile/reference/workflows`**
  - Retorna flujos de trabajo por tipo de material
  - Workflows: default, vinilo, lona, banner, rígido, textil
  - Cada workflow incluye nombre y secuencia de etapas

- **GET `/api/mobile/reference/materials`**
  - Retorna lista de materiales disponibles
  - Fuente: base de datos (jobs existentes)
  - Fallback: lista predefinida si DB vacía

**Propósito:** Proveer información de referencia para que la app móvil construya su UI dinámicamente sin hardcodear datos.

---

### Bloque 2: Estado del Dispositivo
**Commit:** `3b7f95d`

- **GET `/api/mobile/device/status`**
  - Retorna información completa del dispositivo autenticado
  - Datos incluidos:
    - `device_id`, `device_name`, `platform`, `app_version`
    - `registered_at`, `last_seen`, `is_paused`
    - `notification_prefs`: preferencias de eventos
    - `stats.total_stage_changes`: total de cambios realizados
    - `server_version`: versión de la API

**Propósito:** Permitir al dispositivo móvil sincronizar su estado con el servidor y mostrar información relevante al operador.

---

### Bloque 3: Actualización de Preferencias
**Commit:** `ab43743`

- **POST `/api/mobile/device/preferences`**
  - Actualiza preferencias de notificaciones del dispositivo
  - Body JSON: `{ "preferences": { "event_type": true/false, ... } }`
  - Validación: cada valor debe ser booleano
  - Retorna preferencias actualizadas tras aplicar cambios

**Propósito:** Permitir al operador móvil personalizar qué notificaciones desea recibir desde la configuración de la app.

---

### Bloque 4: Búsqueda de Jobs
**Commit:** `7d6c9d9`

- **GET `/api/mobile/jobs/search?q=texto&limit=20&offset=0`**
  - Búsqueda en múltiples campos:
    - `j.title`, `o.client`, `j.material`, `j.notes`
    - `j.id`, `j.order_id` (búsqueda por ID numérico)
  - Paginación: `limit` (máx 50), `offset`
  - Retorna: `jobs`, `total`, `limit`, `offset`, `query`
  - Cada job incluye `progress`, `current_stage`, `workflow_stages`

**Propósito:** Permitir búsqueda rápida y flexible de trabajos desde la app móvil sin necesidad de descargar toda la lista.

---

### Bloque 5: Validación y Manejo de Errores
**Commit:** `3c09281`

Mejoras aplicadas a endpoints existentes:

#### `_list_jobs`:
- Validación de `filter` contra valores permitidos
- Validación de tipos para `limit` y `offset`
- Mensajes de error descriptivos (400)
- Retorna campo `filter` en respuesta para confirmar filtro aplicado

#### `_change_job_stage`:
- Validación de existencia del job antes de procesar body (404)
- Validación de tamaño del body (máx 10KB) → 413
- Validación de body vacío → 400
- Validación de longitud de campos:
  - `stage`: máx 100 caracteres
  - `notes`: máx 500 caracteres
  - `operator_name`: máx 100 caracteres
- Todos los campos se trimean para evitar espacios innecesarios

**Propósito:** Aumentar robustez, prevenir errores silenciosos y proveer feedback claro al cliente móvil.

---

## Endpoints Totales Disponibles

### Autenticación
- `POST /api/pair/validate` (pairing_server.py)
- `POST /api/device/update-token` (pairing_server.py)

### Jobs (v1)
- `GET /api/v1/mobile/jobs` (lista con filtros y paginación)
- `GET /api/v1/mobile/jobs/{id}` (detalle de un job)
- `GET /api/v1/mobile/jobs/search` (búsqueda por texto) ✨ NUEVO
- `POST /api/v1/mobile/jobs/{id}/stage` (cambiar etapa)

### Referencia (v1)
- `GET /api/v1/mobile/reference/stages` ✨ NUEVO
- `GET /api/v1/mobile/reference/workflows` ✨ NUEVO
- `GET /api/v1/mobile/reference/materials` ✨ NUEVO

### Dispositivo (v1)
- `GET /api/v1/mobile/device/status` ✨ NUEVO
- `POST /api/v1/mobile/device/preferences` ✨ NUEVO

**Total endpoints v1:** 9

---

## Próximos Pasos

**Fase 2:** Sincronización incremental de solo lectura (GET /api/v1/mobile/sync/pull)
**Fase 3:** Gestión de imágenes y multimedia
**Fase 4:** Reportes y estadísticas para operadores

---

## Notas Técnicas

- Todos los endpoints requieren autenticación con Bearer token (excepto pairing)
- Todos los endpoints retornan JSON con `Content-Type: application/json`
- Headers CORS configurados: `Access-Control-Allow-Origin: *`
- Logs consistentes vía `logger` (nivel INFO para requests, ERROR para excepciones)
- Cache-Control aplicado a endpoints de referencia (1 hora)

---

## Testing Recomendado

Para validar la implementación:

```bash
# 1. Iniciar servidor (modo desarrollo)
python main.py

# 2. Generar token de prueba (desde UI desktop o DB)

# 3. Probar endpoints
curl -H "Authorization: Bearer <token>" http://localhost:8766/api/mobile/reference/stages
curl -H "Authorization: Bearer <token>" http://localhost:8766/api/mobile/device/status
curl -H "Authorization: Bearer <token>" http://localhost:8766/api/mobile/jobs/search?q=vinilo
curl -X POST -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"preferences": {"job_stage_changed": true}}' \
  http://localhost:8766/api/mobile/device/preferences
```

---

**Estado:** ✅ Fase 1 completada sin errores  
**Último commit:** `e6c3f7c`  
**Rama activa:** `codex/mobile-api-v1`
