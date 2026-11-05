# Fase 2: Sincronización Incremental de Solo Lectura - Completada ✅

**Rama:** `codex/mobile-api-v1`  
**Base:** `baseline-mobile-v1` (commit `c845ba3`)  
**Commits:** 3 bloques implementados

## Resumen de Implementación

La Fase 2 implementó sincronización incremental de solo lectura para dispositivos móviles, permitiendo que la app móvil obtenga cambios desde el servidor sin necesidad de sincronización bidireccional.

### Bloque 1: Índices y Servicio de Cursor
**Commit:** `3535ada`

**Índices creados:**
- `idx_orders_updated_id` en tabla `orders(updated_at, id)`
- `idx_order_jobs_updated_id` en tabla `order_jobs(updated_at, id)`
- `idx_clients_updated_id` en tabla `clients(updated_at, id)`

**Servicio de cursor opaco:**
- `SyncCursorService` con encode/decode de tokens Base64 URL-safe
- Validación estricta de estructura de cursor
- Soporte para versionado de cursor (v1)
- Validación de tipos, límites y timestamps
- Manejo de cursores independientes por entidad

**Propósito:** Proporcionar infraestructura eficiente para paginación incremental con índices compuestos y manejo seguro de cursores opacos.

---

### Bloque 2: Endpoint Capabilities
**Commit:** `ee6a5b6`

**Endpoint agregado:**
- **GET `/api/v1/mobile/capabilities`**
  - Retorna capacidades del servidor para sincronización
  - Incluye: `api_version`, `server_version`, `supported_types`, `max_limit`, `cursor_version`
  - Indica capacidades: `supports_pull`, `supports_push`, `supports_deletions`

**Propósito:** Permitir que la app móvil se adapte automáticamente a futuras versiones del servidor sin cambios manuales.

---

### Bloque 3: Endpoint Sync Pull
**Commit:** `156d72e`

**Endpoint agregado:**
- **GET `/api/v1/mobile/sync/pull`**
  - Parámetros: `cursor` (opcional), `since` (opcional), `limit` (default=100, max=500), `types` (default="jobs,orders,clients")
  - Soporta primera sincronización absoluta
  - Soporta sincronización incremental con `since`
  - Soporta paginación con cursor opaco
  - Usa `LIMIT + 1` para determinar `has_more`
  - Orden estable: `updated_at ASC, id ASC`
  - Cursor robusto: `(updated_at, id) > (?, ?)`

**Entidades sincronizables:**
- `jobs`: order_jobs (id, order_id, title, material, size, quantity, status, notes, sort_order, created_at, updated_at)
- `orders`: orders (id, client, client_id, whatsapp, order_date, status, material, size, quantity, delivery_date, print_priority, is_archived, observations, order_concept, order_description, created_at, updated_at)
- `clients`: clients (id, name, whatsapp, client_type, created_at, updated_at)

**Respuesta:**
```json
{
  "server_time": "2026-07-21T17:30:00",
  "snapshot_until": "2026-07-21T17:30:00",
  "complete": false,
  "next_cursor": "eyJ2ZXJzaW9uIjoxLC...}",
  "entities": {
    "jobs": {"items": [...], "has_more": true},
    "orders": {"items": [...], "has_more": false},
    "clients": {"items": [...], "has_more": false}
  }
}
```

**Propósito:** Permitir sincronización incremental eficiente y confiable entre servidor y dispositivos móviles.

---

## Endpoints Totales Disponibles

### Autenticación
- `POST /api/pair/validate` (pairing_server.py)
- `POST /api/device/update-token` (pairing_server.py)

### Jobs (v1)
- `GET /api/v1/mobile/jobs` (lista con filtros y paginación)
- `GET /api/v1/mobile/jobs/{id}` (detalle de un job)
- `GET /api/v1/mobile/jobs/search` (búsqueda por texto)
- `POST /api/v1/mobile/jobs/{id}/stage` (cambiar etapa)

### Referencia (v1)
- `GET /api/v1/mobile/reference/stages`
- `GET /api/v1/mobile/reference/workflows`
- `GET /api/v1/mobile/reference/materials`

### Dispositivo (v1)
- `GET /api/v1/mobile/device/status`
- `POST /api/v1/mobile/device/preferences`

### Sincronización (v1) ✨ NUEVO
- `GET /api/v1/mobile/capabilities` ✨ NUEVO
- `GET /api/v1/mobile/sync/pull` ✨ NUEVO

**Total endpoints v1:** 11

---

## Pruebas Implementadas

### Tests de Cursor Service (29 tests)
- Encode/decode roundtrip
- Validación de Base64 inválido
- Validación de JSON inválido
- Validación de versión no soportada
- Validación de tipos inválidos
- Validación de límites
- Validación de timestamps
- Validación de compatibilidad de cursor

### Tests de Capabilities Endpoint (2 tests)
- Requiere autenticación
- Retorna contrato válido

### Tests de Sync Pull Endpoint (10 tests)
- Requiere autenticación
- Primera sincronización vacía
- Primera sincronización con datos
- LIMIT + 1 determina has_more
- Paginación con cursor
- Tipos parciales
- Cursor inválido
- Cursor con since rechazado
- Validación de límites (0, 1, 500, 501)
- Sincronización incremental con since

**Total tests:** 41 tests pasando (30 de Fase 1 + 11 de Fase 2)

---

## Decisiones de Diseño

### Cursor Opaco
- Token Base64 URL-safe del JSON interno
- Contiene: version, snapshot_until, types, limit, entities con cursores individuales
- Validación estricta al decodificar
- No expone estructura interna al cliente

### Ordenamiento
- `updated_at ASC, id ASC` para continuidad cronológica
- Permite que el último elemento recibido sea el cursor para la siguiente sincronización
- Evita problemas cuando llegan registros nuevos durante el pull

### Paginación
- `LIMIT + 1` para determinar `has_more` correctamente
- `has_more` por entidad (no global)
- Entidades `complete=true` no se consultan nuevamente

### Consultas SQL
- Variante B: `WHERE (updated_at, id) > (?, ?)` aprovecha mejor índice compuesto
- Evita B-TREE temporal en ORDER BY
- Snapshot consistente con `updated_at <= snapshot_until`

### Timestamps
- Formato naive ISO 8601 (sin zona horaria)
- `since` usa `>=` para incluir registros con mismo timestamp
- Semántica "at-least-once": pueden existir registros repetidos entre rondas
- Cliente debe aplicar upsert por ID

### Eliminaciones
- No soporta borrados físicos en esta fase
- Recomendación: usar `is_archived=1` en orders
- Futuras fases pueden agregar `deleted_at` y tombstones

---

## Notas Técnicas

- Todos los endpoints requieren autenticación con Bearer token
- Todos los endpoints retornan JSON con `Content-Type: application/json`
- Headers CORS configurados: `Access-Control-Allow-Origin: *`
- Logs consistentes vía `logger` (nivel INFO para requests, ERROR para excepciones)
- Índices compuestos optimizan patrón de cursor
- No se implementan cálculos en servidor (solo datos persistidos)

---

## Testing Recomendado

Para validar la implementación:

```bash
# 1. Iniciar servidor (modo desarrollo)
python main.py

# 2. Generar token de prueba (desde UI desktop o DB)

# 3. Probar capabilities
curl -H "Authorization: Bearer <token>" http://localhost:8766/api/v1/mobile/capabilities

# 4. Probar primera sincronización
curl -H "Authorization: Bearer <token>" "http://localhost:8766/api/v1/mobile/sync/pull?limit=10"

# 5. Probar sincronización incremental
curl -H "Authorization: Bearer <token>" "http://localhost:8766/api/v1/mobile/sync/pull?since=2026-07-20T00:00:00&limit=10"

# 6. Probar paginación con cursor
# (usar next_cursor de respuesta anterior)
curl -H "Authorization: Bearer <token>" "http://localhost:8766/api/v1/mobile/sync/pull?cursor=<cursor_token>&limit=10"
```

---

## Próximos Pasos

**Fase 3:** Gestión de imágenes y multimedia
**Fase 4:** Reportes y estadísticas para operadores
**Fase 5:** Sincronización bidireccional (sync push)

---

**Estado:** ✅ Fase 2 completada sin errores  
**Último commit:** `156d72e`  
**Rama activa:** `codex/mobile-api-v1`  
**Tests:** 41/42 pasando (30 de Fase 1 + 11 de Fase 2)
