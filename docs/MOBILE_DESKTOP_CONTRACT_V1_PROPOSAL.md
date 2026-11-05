# Contrato de pedidos completos v1 — PROPUESTA, NO IMPLEMENTADO

Este documento es diseño previo de alcance, no anuncia endpoints disponibles. Mobile permanece local para los borradores completos. Ningún JSON de este contrato se envía a la API actual.

Actualización Sprint 2A: existe `app/services/mobile_order_contract.py` como preflight de solo lectura, **no coordinador transaccional**. Véase `MOBILE_SPRINT_2A_BACKEND_AUDIT.md` para los bloqueos de commits internos, revisión global y journal idempotente. No hay rutas nuevas habilitadas ni recibos de escritura implementados. Límites del preflight: 64 KiB, 30 trabajos y 100 diseños/trabajo; el parser HTTP antiguo conserva su límite distinto de 10 KB. Identidad Desktop es string decimal/null; unidades item/sheet. El catálogo real resuelve IDs opacos de diseño de 24 caracteres hexadecimales, no rutas del teléfono. `catalog_stale` es 422 en este preflight; el 409 mencionado en el diseño siguiente corresponde al futuro conflicto de catálogo en escritura y aún no está implementado.

## Inventario real

API HTTP en `app/api/mobile_jobs.py`, prefijo `/api/v1/mobile`: GET `/sync/pull` (snapshots orders/jobs/clients), GET `/jobs` y `/jobs/{id}`, `/catalog/products` y `/catalog/designs`; POST `/catalog/quote`, `/catalog/orders`, `/catalog/product-orders`, `/catalog/product-quote`, `/sticker-orders` y `/sticker-orders/quote` (alta sticker con client_request_id); PATCH `/orders/{id}/details`, `/orders/{id}/priority`, `/orders/{id}/status` y `/orders/{oid}/jobs/{jid}`; POST `/orders/{id}/payments` y `/orders/{id}/deliver`. Estos endpoints no conforman una API integral de edición del agregado pedido.

El snapshot no contiene un agregado editable con todas las líneas de demanda/reservas ni revisión monotónica. Los PATCH operativos no implementan compare-and-swap de versión. No hay HTTP de agregar/quitar trabajos completos ni de editar asociaciones modernas por trabajo. El catálogo HTTP contiene códigos/opciones, no se deben tratar como IDs de product_variants sin resolución de Studio. Presupuestos se calculan en Desktop; costos/históricos no son editables por Mobile.

Servicios internos: `ImageDatabase.replace_order_jobs`, `delete_order_job`, `mark_order_delivered`, demanda/asociaciones y `ProductionBatchService.configure_job_unit`/reservas. La unidad productiva real es `item` o `sheet`; el borrador legado `units`/`sheets` requiere conversión explícita. La eliminación de trabajo ya rechaza asignaciones con historial; se deben reutilizar guardas centralizadas, no reescribirlas en Flutter.

Riesgos actuales detectados por lectura: PATCH de cantidad/tamaño y POST deliver escriben SQL directamente; deliver no llama a `mark_order_delivered`. No afirmar que esos endpoints heredan todas las guardas modernas. El alta/agregado de productos no recibe una clave de idempotencia como stickers. Se requiere revisión y pruebas específicas antes de habilitar sincronización completa. No se modifican estos endpoints en esta entrega sin aprobar primero este alcance.

## Alcance backend propuesto para aprobación

Agregar lectura del agregado completo, operación atómica de cambios y consulta del resultado de operación; rutas nuevas por definir y negociar, no publicadas aquí como existentes. Persistir revisión monotónica y un registro de operaciones bajo scope de usuario/tenant/dispositivo. Revisión debe aumentar también ante mutaciones Desktop y endpoints antiguos; añadir solo un contador al endpoint nuevo sería insuficiente.

Entrada versionada: `contract_version: 1`, `operation_id` estable, `client_order_id` estable, `desktop_order_id` nullable solo en alta, `expected_revision` (0 alta, >=1 edición), y `jobs`. Cada trabajo tiene `client_job_id` estable, `desktop_job_id` opcional, product_code, variant_code, material/size resueltos de opción autorizada, quantity positiva y `unit_kind: item|sheet`; diseño con `association_id` estable, catalog_design_id autorizado y quantity positiva. Incluir cabecera cliente/contacto/observaciones/fecha solicitada, no estados comerciales/productivos como entrada.

Asociaciones se identifican por línea de demanda, no solo por path ni posición de la lista. Una misma imagen en trabajos diferentes tiene asociaciones diferentes. Los IDs de catálogo son opacos; jamás aceptar una ruta local arbitraria enviada por teléfono. No interpretar cantidades de hojas como cantidad de stickers ni sumarlas para producir un total global engañoso.

Mobile puede proponer cliente/contacto, notas/fecha, selección de catálogo, trabajos y distribución. Studio administra IDs persistidos, precios/costos históricos, autorización, stock/reservas, etapas/entrega, revisiones y validación definitiva. Cantidades de diseños pueden ser parciales, nunca mayores al trabajo. No ajustar precios pasados al cambiar silenciosamente catálogo: recalcular presupuesto explícito y confirmarlo en una operación distinta autorizada.

## Transacción e idempotencia obligatorias

1. Autenticar token vigente, alcance vendedor/pedido y permiso de edición. HTTPS fuera de LAN/VPN según validaciones vigentes; límites de tamaño, tipos y allowlist de campos. Rechazar campos administrativos desconocidos.
2. Resolver operation_id bajo el mismo scope: mismo hash canónico devuelve el recibo original; mismo ID y payload diferente rechaza `operation_mismatch`. El chequeo y resultado deben estar en la misma transacción que los cambios, con índice único y control de concurrencia.
3. Comparar revisión esperada; conflicto 409 con revisión actual y snapshot autorizado, sin sobrescribir ni consumir la operación como exitosa.
4. Resolver catálogo autorizado y pasar todas las mutaciones por las guardas de Pedidos 2.0. No eliminar trabajo/demanda con reservas o historia; no reducir por debajo de comprometido, impreso, terminado o entregado. Rechazar todo el agregado si una parte falla. No cambiar etapas/entrega ni precios históricos por esta operación.
5. Confirmar commit antes de responder. Recibo: contract_version, operation_id, payload_hash, desktop_order_id, revision, persisted=true, committed_at, mapeos client_job_id→desktop_job_id y association_id→demand_line_id, snapshot oficial y validaciones. Un HTTP 200 vacío no prueba persistencia.
6. Publicar eventos solo después del commit. Fallo de evento no debe inducir una segunda venta. Ante respuesta perdida consultar recibo o repetir exactamente la misma operación, no generar otro ID.

Errores estructurados: validation_failed (422, campos), forbidden (403), not_found autorizado (404), revision_conflict (409), production_committed (409), operation_mismatch (409), catalog_stale (409), transient (503). No devolver rutas internas ni SQL. Sin cambios parciales incluso si falla el último diseño. Operaciones rechazadas deben conservar diagnóstico y no presentarse como confirmadas.

## Estados y trabajo offline

Guardado local → pendiente de sincronización (solo cuando exista adapter negociado) → sincronizando → sincronizado y confirmado (solo recibo válido y correspondiente al payload). Conflicto conserva ambas versiones; error conserva la operación y texto de validación. Respuesta perdida conserva ID y payload; no vuelve a generar una venta.

Hoy solo está habilitado **guardado local** y conflicto local. No se habilitan estados de envío ni sincronización por temporizadores. No borrar borradores por ausencia en snapshot, timeout, logout ni refresh. Un recibo de una revisión anterior no confirma ediciones locales posteriores. Para resolver conflicto debe mantenerse copia de la versión local y una base remota; no automezclar cantidades ni asociaciones comprometidas.

## Puerta de aceptación backend y Sprint 2

Antes de conectar: pruebas E2E en base aislada para alta completa, rollback de último trabajo, edición concurrente Mobile/Desktop, retry/respuesta perdida, dos dispositivos con mismo operation_id, replay con payload distinto, autorización cruzada, token revocado, transporte inválido, datos antiguos, cotización desactualizada, unidades mezcladas, reservas activas e historia liberada, entrega bloqueada y fallo de evento postcommit. Aprobar alcance backend antes de crear endpoints. No se toca SQLite operativa ni se genera APK con bloqueos críticos.
