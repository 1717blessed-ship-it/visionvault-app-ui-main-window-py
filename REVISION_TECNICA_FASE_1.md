# Revisión Técnica - Fase 1: API REST Móvil

**Fecha:** 2026-07-21  
**Rama:** `codex/mobile-api-v1`  
**Commits revisados:** `a469d77` a `3c09281`

---

## 🚨 HALLAZGOS CRÍTICOS

### 1. **VIOLACIÓN DE ARQUITECTURA: Rutas sin versionado /api/v1/**

**Severidad:** CRÍTICA ❌

Todos los endpoints nuevos fueron implementados bajo `/api/mobile/*` en lugar de `/api/v1/mobile/*` como establece la arquitectura aprobada.

**Rutas implementadas (INCORRECTAS):**
- ❌ `/api/mobile/reference/stages`
- ❌ `/api/mobile/reference/workflows`
- ❌ `/api/mobile/reference/materials`
- ❌ `/api/mobile/device/status`
- ❌ `/api/mobile/device/preferences`
- ❌ `/api/mobile/jobs/search`

**Rutas esperadas (CORRECTAS):**
- ✅ `/api/v1/mobile/reference/stages`
- ✅ `/api/v1/mobile/reference/workflows`
- ✅ `/api/v1/mobile/reference/materials`
- ✅ `/api/v1/mobile/device/status`
- ✅ `/api/v1/mobile/device/preferences`
- ✅ `/api/v1/mobile/jobs/search`

**Rutas legacy que deben permanecer:**
- `/api/mobile/jobs` (GET - lista)
- `/api/mobile/jobs/{id}` (GET - detalle)
- `/api/mobile/jobs/{id}/stage` (POST - cambio de etapa)

**Impacto:**
- Inconsistencia entre documentación y código
- Cliente móvil no podrá adoptar versionado limpio
- Mezcla de endpoints versionados y no versionados
- Dificulta la evolución futura de la API

---

### 2. **DUPLICACIÓN DE REGLAS DE NEGOCIO: Catálogos hardcodeados**

**Severidad:** ALTA ⚠️

**Problema:** Los métodos `_get_stages()`, `_get_workflows()` y `_get_materials()` contienen **copias manuales hardcodeadas** de reglas de negocio que ya existen en módulos oficiales.

#### 2.1 Etapas (`_get_stages`)

**Código implementado:** 12 etapas hardcodeadas en `mobile_jobs.py` líneas 398-489

```python
stages = [
    {"key": "Recibido", "label": "Recibido", ...},
    {"key": "Esperando archivos", ...},
    {"key": "Diseño", ...},
    # ... 9 más ...
]
```

**Fuente oficial:** `app/workflow/timeline.py` define:
- `GENERAL_WORKFLOW`: 12 etapas con nombres diferentes
- `VINYL_WORKFLOW`: 10 etapas específicas
- `TEXTILE_WORKFLOW`: 8 etapas específicas
- `FINISHING_WORKFLOW`: 8 etapas específicas

**Inconsistencias detectadas:**
- Mobile API usa "Diseño" → Timeline usa "Diseños confirmados"
- Mobile API usa "Impresión" → Timeline usa "Impresión" ✓ (coincide)
- Mobile API usa "Acabado" → Timeline usa "Corte" / "Terminación"
- Mobile API usa "RIP" → Timeline NO tiene esta etapa en GENERAL_WORKFLOW
- Mobile API usa "Laminado" → Timeline usa "Sublimado / Laminado"
- Mobile API usa "Control de calidad" → Timeline SÍ tiene esta etapa ✓

**Problema:** Existen 2 fuentes de verdad diferentes. Si se agrega una nueva etapa en `timeline.py`, NO se reflejará automáticamente en la API móvil.

#### 2.2 Workflows (`_get_workflows`)

**Código implementado:** 6 workflows hardcodeados en `mobile_jobs.py` líneas 494-561

```python
workflows = {
    "default": ["Recibido", "Diseño", "Aprobación cliente", "Impresión", "Acabado", "Finalizado"],
    "vinilo": ["Recibido", "Diseño", "Impresión", "Laminado", "Acabado", "Finalizado"],
    # ... 4 más ...
}
```

**Fuente oficial:** `app/workflow/timeline.py` define:
- `GENERAL_WORKFLOW` con nombres diferentes
- `VINYL_WORKFLOW` con nombres diferentes
- `TEXTILE_WORKFLOW` no contemplado en mobile API
- `FINISHING_WORKFLOW` no contemplado en mobile API

**Problema:** Los workflows de la API móvil NO coinciden con los workflows reales que usa el sistema desktop. Esto generará inconsistencias visuales entre ambas interfaces.

#### 2.3 Materiales (`_get_materials`)

**Estado:** ✅ CORRECTO (lee desde base de datos con fallback a lista predefinida)

**Código implementado (líneas 566-594):**
```python
rows = self.event_repo.conn.execute(
    """SELECT DISTINCT material FROM order_jobs WHERE material IS NOT NULL..."""
).fetchall()
materials = [row[0] for row in rows]
if not materials:
    materials = ["Vinilo", "Lona", "Banner", ...]  # Fallback
```

Este enfoque es correcto ya que:
- Lee datos reales de la DB
- Tiene fallback razonable para DB vacía
- Los materiales son datos dinámicos, no reglas de negocio fijas

---

### 3. **FALTA VALIDACIÓN DE WHITELIST: Preferencias sin restricción**

**Severidad:** MEDIA ⚠️

**Método:** `_update_device_preferences()` (líneas 599-635)

**Problema:** El endpoint acepta cualquier `event_type` sin validar contra una whitelist de eventos permitidos.

```python
for event_type, enabled in preferences.items():
    if not isinstance(enabled, bool):
        self._send_error(400, f"Preference value for '{event_type}' must be boolean")
        return
    self.event_repo.set_device_pref(device["id"], event_type, enabled)  # ❌ Sin validación
```

**Riesgo:**
- Cliente malicioso puede insertar event_types arbitrarios
- Contaminación de la tabla de preferencias
- Posibles inyecciones si event_type se usa en queries sin sanitizar

**Solución esperada:**
```python
ALLOWED_EVENT_TYPES = {
    "job_stage_changed",
    "job_created",
    "job_assigned",
    "order_updated",
    "urgent_job",
}

for event_type, enabled in preferences.items():
    if event_type not in ALLOWED_EVENT_TYPES:
        self._send_error(400, f"Unknown event type: '{event_type}'")
        return
    # ... continuar
```

---

### 4. **FALTA DE SANITIZACIÓN: SQL Injection en búsqueda**

**Severidad:** MEDIA ⚠️

**Método:** `_search_jobs()` (líneas 215-288)

**Estado:** ✅ PARCIALMENTE CORRECTO (usa parámetros preparados)

```python
search_pattern = f"%{query_text}%"  # ✅ Correcto: no inyecta directamente en query
query = """... WHERE o.is_archived = 0 AND (j.title LIKE ? OR o.client LIKE ? ...)"""
params_list = [search_pattern] * 6 + [limit, offset]
rows = self.event_repo.conn.execute(query, params_list).fetchall()  # ✅ Usa parámetros
```

**Análisis:**
- ✅ Usa prepared statements correctamente
- ✅ No inyecta `query_text` directamente en la query SQL
- ⚠️ No valida longitud de `query_text` (podría ser muy largo)
- ⚠️ No valida caracteres especiales de LIKE (`%`, `_`, `[`, `]`)

**Recomendación:** Agregar validación de longitud:
```python
if len(query_text) > 100:
    self._send_error(400, "Search query too long (max 100 characters)")
    return
```

---

### 5. **EXPOSICIÓN DE DATOS SENSIBLES: Estado del dispositivo**

**Severidad:** BAJA ℹ️

**Método:** `_get_device_status()` (líneas 640-692)

**Estado:** ✅ CORRECTO (no expone tokens ni hashes)

```python
device_status = {
    "device_id": device["id"],
    "device_name": device["device_name"],
    "platform": device["platform"],
    "app_version": device.get("app_version", ""),
    "registered_at": device["registered_at"],
    "last_seen": last_seen,
    "is_paused": device.get("is_paused", 0) == 1,
    "notification_prefs": prefs,
    "stats": {"total_stage_changes": total_changes},
    "server_version": "1.0.0",
}
```

**Análisis:**
- ✅ NO expone `push_token` (FCM)
- ✅ NO expone `session_token` o `session_token_hash`
- ✅ NO expone información de otros dispositivos
- ✅ Solo muestra datos del dispositivo autenticado

---

### 6. **CÓDIGOS HTTP: Validación de respuestas**

**Estado:** ✅ MAYORMENTE CORRECTO

| Endpoint | 200 | 400 | 401 | 404 | 413 | 500 |
|----------|-----|-----|-----|-----|-----|-----|
| GET /jobs | ✅ | ✅ | ✅ | - | - | ✅ |
| GET /jobs/search | ✅ | ✅ | ✅ | - | - | ✅ |
| GET /jobs/{id} | ✅ | ✅ | ✅ | ✅ | - | ✅ |
| POST /jobs/{id}/stage | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| GET /reference/* | ✅ | - | ✅ | - | - | ✅ |
| GET /device/status | ✅ | - | ✅ | - | - | ✅ |
| POST /device/preferences | ✅ | ✅ | ✅ | - | - | ✅ |

**Faltantes:**
- ❌ **409 Conflict:** No se usa, pero podría ser útil para conflictos de concurrencia en cambio de etapa

---

### 7. **VALIDACIÓN DE ENTRADA: Mejoras implementadas**

**Estado:** ✅ CORRECTO

Las mejoras del commit `3c09281` agregaron validaciones robustas:

#### `_list_jobs`:
- ✅ Valida `filter` contra whitelist `["", "pending", "production", "ready"]`
- ✅ Valida tipo de `limit` y `offset` (ValueError capturado)
- ✅ Límites seguros: `limit` máx 100, `offset` mín 0

#### `_change_job_stage`:
- ✅ Valida existencia del job antes de procesar body (404)
- ✅ Valida body no vacío (400)
- ✅ Valida tamaño máximo de body: 10KB (413)
- ✅ Valida longitudes:
  - `stage`: máx 100 caracteres
  - `notes`: máx 500 caracteres
  - `operator_name`: máx 100 caracteres
- ✅ Trim automático de campos (`strip()`)

---

### 8. **BÚSQUEDA: Límites de seguridad**

**Estado:** ✅ CORRECTO

```python
limit = min(50, max(1, int(params.get("limit", "20"))))  # Máx 50 (más estricto que list_jobs)
offset = max(0, int(params.get("offset", "0")))
```

**Análisis:**
- ✅ Límite máximo: 50 resultados (razonable para búsqueda)
- ✅ Default: 20 resultados
- ⚠️ Inconsistencia: `list_jobs` permite hasta 100, `search_jobs` solo 50

**Recomendación:** Unificar límite máximo a 50 en ambos endpoints para consistencia.

---

### 9. **LÓGICA DE NEGOCIO ACOPLADA**

**Severidad:** MEDIA ⚠️

**Problema:** Se agregaron 300 líneas de lógica en `mobile_jobs.py` que debería vivir en servicios independientes.

**Métodos problemáticos:**
- `_get_stages()` → Debería llamar a `StageService.get_all_stages()`
- `_get_workflows()` → Debería llamar a `WorkflowService.get_workflows()`
- `_update_device_preferences()` → Ya usa correctamente `event_repo.set_device_pref()` ✅

**Arquitectura actual:**
```
mobile_jobs.py (694 líneas)
├── Handlers HTTP
├── Validación de entrada
├── Autenticación
└── ❌ LÓGICA DE NEGOCIO (stages, workflows)  # ACOPLAMIENTO
```

**Arquitectura esperada:**
```
mobile_jobs.py
├── Handlers HTTP
├── Validación de entrada
├── Autenticación
└── Delega a servicios ✅
    ├── StageService.get_all_stages()
    ├── WorkflowService.get_workflows()
    └── MaterialService.get_materials()
```

---

### 10. **TESTS EXISTENTES: Cobertura actual**

**Archivo:** `tests/test_mobile_api.py`

**Cobertura:** ✅ BUENA (endpoints legacy)

| Clase de Test | Endpoints cubiertos | Estado |
|---------------|---------------------|--------|
| `TestAuthentication` | Bearer token validation | ✅ |
| `TestListJobsEndpoint` | GET /jobs (legacy) | ✅ |
| `TestGetJobDetailEndpoint` | GET /jobs/{id} (legacy) | ✅ |
| `TestChangeJobStageEndpoint` | POST /jobs/{id}/stage (legacy) | ✅ |
| `TestFCMTokenRenewalIndependence` | Session preservation | ✅ |

**Endpoints SIN tests:**
- ❌ GET /reference/stages
- ❌ GET /reference/workflows
- ❌ GET /reference/materials
- ❌ GET /device/status
- ❌ POST /device/preferences
- ❌ GET /jobs/search

**Tests no ejecutados:** pytest parece colgar durante la recolección. Posible conflicto con fixtures o importaciones lentas.

---

## 📋 RESUMEN DE RIESGOS

| # | Riesgo | Severidad | Estado |
|---|--------|-----------|--------|
| 1 | Rutas sin versionado /api/v1/ | 🔴 CRÍTICA | Requiere corrección |
| 2 | Duplicación de reglas de negocio (stages/workflows) | 🟡 ALTA | Requiere corrección |
| 3 | Preferencias sin whitelist | 🟡 MEDIA | Requiere corrección |
| 4 | Búsqueda sin límite de longitud | 🟡 MEDIA | Recomendado |
| 5 | Exposición de datos sensibles | 🟢 BAJA | OK |
| 6 | Códigos HTTP | 🟢 OK | OK |
| 7 | Validación de entrada | 🟢 OK | OK |
| 8 | Límites de búsqueda | 🟢 OK | OK (minor inconsistencia) |
| 9 | Lógica acoplada en handlers | 🟡 MEDIA | Recomendado desacoplar |
| 10 | Tests incompletos | 🟡 MEDIA | Agregar tests para nuevos endpoints |

---

## 🛠️ CAMBIOS NECESARIOS PARA CORREGIR FASE 1

### Cambio 1: Mover endpoints nuevos a /api/v1/mobile/*

**Prioridad:** 🔴 CRÍTICA

**Archivos afectados:**
- `app/api/mobile_jobs.py`

**Acción:**
1. Mantener rutas legacy `/api/mobile/*` para:
   - GET `/api/mobile/jobs`
   - GET `/api/mobile/jobs/{id}`
   - POST `/api/mobile/jobs/{id}/stage`

2. Implementar rutas nuevas bajo `/api/v1/mobile/*`:
   - GET `/api/v1/mobile/reference/stages`
   - GET `/api/v1/mobile/reference/workflows`
   - GET `/api/v1/mobile/reference/materials`
   - GET `/api/v1/mobile/device/status`
   - POST `/api/v1/mobile/device/preferences`
   - GET `/api/v1/mobile/jobs/search`

3. Opcional: Crear adaptadores de compatibilidad si se desea:
   ```python
   elif parsed.path == "/api/mobile/reference/stages":
       # Redirect legacy to v1
       return self._get_stages_v1()
   ```

---

### Cambio 2: Extraer etapas y workflows a servicios

**Prioridad:** 🟡 ALTA

**Archivos afectados:**
- `app/api/mobile_jobs.py`
- `app/workflow/timeline.py` (fuente de verdad)
- Nuevo: `app/services/stage_catalog_service.py`

**Acción:**
1. Crear `StageCatalogService` que:
   - Lea etapas desde `timeline.py` (GENERAL_WORKFLOW, VINYL_WORKFLOW, etc.)
   - Genere representaciones JSON para la API móvil
   - Incluya metadatos (colores, descripciones) desde una constante centralizada

2. Modificar `_get_stages()` para delegar:
   ```python
   def _get_stages(self) -> None:
       try:
           stages = StageCatalogService.get_all_stages_for_mobile()
           self._send_json_response(200, {"stages": stages})
       except Exception as e:
           logger.error("Error getting stages: %s", e)
           self._send_error(500, f"Error getting stages: {e}")
   ```

3. Modificar `_get_workflows()` para delegar:
   ```python
   def _get_workflows(self) -> None:
       try:
           workflows = StageCatalogService.get_workflows_for_mobile()
           self._send_json_response(200, {"workflows": workflows})
       except Exception as e:
           logger.error("Error getting workflows: %s", e)
           self._send_error(500, f"Error getting workflows: {e}")
   ```

---

### Cambio 3: Agregar whitelist de event_types

**Prioridad:** 🟡 MEDIA

**Archivos afectados:**
- `app/api/mobile_jobs.py`

**Acción:**
```python
# Agregar constante al inicio del archivo
ALLOWED_NOTIFICATION_EVENT_TYPES = {
    "job_stage_changed",
    "job_created",
    "job_assigned",
    "order_updated",
    "order_priority_changed",
    "urgent_notification",
}

def _update_device_preferences(self, device: dict[str, Any]) -> None:
    """Actualiza las preferencias de notificaciones del dispositivo."""
    try:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        data = json.loads(body.decode("utf-8"))

        preferences = data.get("preferences")
        if not isinstance(preferences, dict):
            self._send_error(400, "preferences field must be a dictionary")
            return

        # Validar event_types contra whitelist
        for event_type in preferences.keys():
            if event_type not in ALLOWED_NOTIFICATION_EVENT_TYPES:
                self._send_error(400, f"Unknown event type: '{event_type}'")
                return

        # Actualizar cada preferencia
        updated_count = 0
        for event_type, enabled in preferences.items():
            if not isinstance(enabled, bool):
                self._send_error(400, f"Preference value for '{event_type}' must be boolean")
                return

            self.event_repo.set_device_pref(device["id"], event_type, enabled)
            updated_count += 1

        # ... resto del método
```

---

### Cambio 4: Agregar validación de longitud en búsqueda

**Prioridad:** 🟢 BAJA (nice to have)

**Archivos afectados:**
- `app/api/mobile_jobs.py`

**Acción:**
```python
def _search_jobs(self, device: dict[str, Any]) -> None:
    """Busca jobs por texto en título, cliente, material, notas."""
    params = self._parse_url_params()

    query_text = params.get("q", "").strip()
    if not query_text:
        self._send_error(400, "Query parameter 'q' is required")
        return

    # NUEVO: Validar longitud
    if len(query_text) > 100:
        self._send_error(400, "Search query too long (max 100 characters)")
        return

    # ... resto del método
```

---

### Cambio 5: Agregar tests para nuevos endpoints

**Prioridad:** 🟡 MEDIA

**Archivos afectados:**
- `tests/test_mobile_api.py`

**Acción:** Agregar clases de test:
```python
class TestReferenceEndpoints:
    def test_get_stages(self, ...): ...
    def test_get_workflows(self, ...): ...
    def test_get_materials(self, ...): ...

class TestDeviceEndpoints:
    def test_get_device_status(self, ...): ...
    def test_update_preferences_success(self, ...): ...
    def test_update_preferences_invalid_event_type(self, ...): ...

class TestSearchEndpoint:
    def test_search_jobs_by_title(self, ...): ...
    def test_search_jobs_by_client(self, ...): ...
    def test_search_jobs_too_long_query(self, ...): ...
```

---

## 🎯 RUTAS FINALES ESPERADAS

### API v1 (nuevos endpoints)
```
GET  /api/v1/mobile/reference/stages       → Catálogo de etapas
GET  /api/v1/mobile/reference/workflows    → Flujos por material
GET  /api/v1/mobile/reference/materials    → Materiales disponibles
GET  /api/v1/mobile/device/status          → Estado del dispositivo
POST /api/v1/mobile/device/preferences     → Actualizar preferencias
GET  /api/v1/mobile/jobs/search?q=...      → Búsqueda de jobs
```

### API Legacy (mantener sin cambios)
```
GET  /api/mobile/jobs                       → Lista de jobs
GET  /api/mobile/jobs/{id}                  → Detalle de job
POST /api/mobile/jobs/{id}/stage            → Cambiar etapa
```

### API Pairing (sin cambios)
```
POST /api/pair/validate                     → Vincular dispositivo
POST /api/device/update-token               → Actualizar FCM token
```

---

## 📊 RESULTADOS DE COMPILACIÓN

```bash
python -m compileall app
```

**Resultado:** ✅ Sin errores de sintaxis

**Warnings:** Permisos denegados en directorios vendor (ignorables)

---

## 📊 RESULTADOS DE TESTS

**Comando intentado:**
```bash
python -m pytest tests/test_mobile_api.py -v
```

**Resultado:** ⏸️ COLGADO durante recolección de tests

**Causa probable:**
- Importación lenta de dependencias (Tkinter, PIL, etc.)
- Fixtures complejas con DB temporal
- Posible deadlock en inicialización de EventBus

**Tests existentes (basado en código fuente):**
- ✅ 4 tests de autenticación
- ✅ 5 tests de lista de jobs
- ✅ 2 tests de detalle de job
- ✅ 3 tests de cambio de etapa
- ✅ 2 tests de renovación FCM

**Total:** 16 tests para endpoints legacy

**Faltantes:** 0 tests para 6 endpoints nuevos

---

## ✅ CHECKLIST DE CORRECCIONES

- [ ] **Crítico:** Mover endpoints a /api/v1/mobile/*
- [ ] **Alto:** Extraer stages/workflows a servicios
- [ ] **Medio:** Agregar whitelist de event_types
- [ ] **Bajo:** Validar longitud de query de búsqueda
- [ ] **Medio:** Agregar tests para nuevos endpoints
- [ ] **Bajo:** Unificar límite máximo de paginación (50)
- [ ] **Documentación:** Actualizar FASE_1_COMPLETADA.md con rutas v1

---

## 🎯 RECOMENDACIÓN FINAL

**Estado actual:** ⚠️ FASE 1 FUNCIONALMENTE COMPLETA pero con VIOLACIONES ARQUITECTURALES

**Acción inmediata recomendada:**

1. **OBLIGATORIO:** Corregir rutas a /api/v1/mobile/* antes de continuar con Fase 2
2. **OBLIGATORIO:** Extraer stages/workflows a servicios para eliminar duplicación
3. **RECOMENDADO:** Agregar whitelist de event_types
4. **OPCIONAL:** Agregar tests para nuevos endpoints
5. **OPCIONAL:** Validación de longitud en búsqueda

**No continuar con Fase 2** hasta completar al menos los 2 cambios obligatorios para evitar propagación de deuda técnica.

---

**Firma de revisión:** Kiro AI  
**Commits revisados:** baseline-mobile-v1 (c845ba3) → HEAD (3c09281)
