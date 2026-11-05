# Doccione Mobile — Sprint 1: avance y bloqueo de integración

Fecha: 2026-10-24. Rama independiente: `codex/mobile-s1-pedidos-subproductos`.

## Dictamen

Entrega parcial, no aprobación operativa ni Sprint 1 completo. Se habilitó un editor persistente de **borradores locales multi-trabajo**, sin simular sincronización. No se generó APK ni se publicó. Para cumplir el objetivo integral falta acordar y desarrollar el contrato de edición de pedidos completos con Desktop; no se improvisaron endpoints ni escrituras remotas SQLite.

## Auditoría previa y arquitectura encontrada

Flutter conserva su navegación y widgets actuales. `DatabaseHelper` usa sqflite, caché de pedidos/clientes/jobs y migraciones; `SyncService` y sus handlers descargan snapshots paginados. `OrdersRepository` contiene el caché remoto. `QuickEditApiClient` cambia detalles operativos online. `CatalogApiClient` consulta productos y diseños y crea ventas. `OfflineOrdersService` conserva una cola de altas, con dueño de sesión; no es un sistema general de edición bidireccional.

Había experiencias separadas: `sticker_order_screen`, `products_catalog_screen`, listado/detalle de pedidos y `unified_order_creation_screen`. Esta última era una referencia no conectada al listado: incluía productos ficticios permanentes (`prod_sticker_1`, etc.) y utilizaba `UnifiedOrdersManager`, que tenía TODO para guardar y recuperar items y para consultar variantes. No era un editor completo funcional. Ese manager antiguo sigue en el árbol para sus otros consumidores; no se declara reparado ni se usa en el nuevo editor.

Modelos actuales de transporte: `StudioProduct`/`StudioProductOption` contienen códigos, material y tamaño de opciones existentes. `OrderItem` no equivale automáticamente a `order_jobs` Desktop. Hay un catálogo incluido para trabajo offline; su disponibilidad no acredita vigencia de precios ni variantes configuradas actualmente en el servidor. No se agregaron variantes ficticias al catálogo.

## Contratos reales y brechas

| Contrato existente | Alcance observado | No garantiza |
|---|---|---|
| GET catálogo products/designs | Productos/opciones y diseños autorizados | Snapshot completo del catálogo interno ni reservas |
| POST catalog/quote y catalog/orders | Presupuesto y alta de diseños desde Studio | Edición multi-trabajo, conflictos y distribución por trabajo |
| POST venta de productos, target_order_id | Alta/agregado de líneas de producto al pedido | Vinculación de varios diseños al trabajo |
| PATCH orders/{id}/details y orders/{oid}/jobs/{jid} | Datos operativos y cantidad/tamaño | Edición integral con revisión optimista y protección de toda la demanda |
| Snapshot de orders/jobs/clients | Caché de lectura | Publicación de borradores ni confirmación de cambios locales |

La implementación actual de `catalog/orders` crea jobs y asociaciones legacy a nivel pedido; no debe asumirse que implementa el contrato moderno de demanda por trabajo. No se adaptó Desktop en este sprint parcial. La unidad del nuevo borrador es explícita (`units`/`sheets`), pero **no se afirma que sus JSON sean aceptados directamente por un endpoint existente**: requieren mapeo validado al contrato de Desktop. Tampoco se infieren IDs SQLite a partir de códigos HTTP.

«Vincular al pedido» en el checkout de productos admite un número y llama al alta de productos con `target_order_id`: no era un selector de trabajo ni un vínculo de diseño. Además, ese checkout captura cualquier error y encola una nueva solicitud; el alta de productos no comparte la idempotencia explícita del flujo sticker. Una respuesta perdida o reintentos pueden duplicar líneas. Sigue pendiente: no se atribuye una corrección de ese flujo al editor local nuevo.

## Cambios implementados

- Editor anterior de ejemplo reemplazado por borrador con varios trabajos, selección de productos/opciones reales recibidos del API o catálogo incluido etiquetado como vigencia no confirmada. Se accede desde Pedidos → icono «Borradores multi-trabajo».
- Cantidad positiva, unidad Unidades/Hojas, notas, material/tamaño provenientes de la opción y varios diseños del catálogo por trabajo. Permite editar cantidades, quitar vínculos **solo locales**, distribución parcial y bloquea sobreasignaciones/duplicados al conservar/guardar.
- Presupuesto siempre pendiente de Studio; no se crean precios ni costos con fórmulas móviles. El catálogo sin opciones no habilita inventar material/tamaño: completar esos atributos dinámicos queda pendiente del contrato correspondiente.
- Guardado de borradores incompletos, recuperación y revisión local optimista. IDs estables, transacciones, inmutabilidad de listas y rechazo de escrituras desde revisiones antiguas.
- Tabla separada `order_drafts`, esquema v18, clave por ID/vendedor. No se escribe en orders/jobs/pending_orders, no se envía por sync y no se borra con el caché al cerrar sesión; otro vendedor no los ve. El borrador no representa producción comprometida, por lo que quitar sus vínculos no toca reservas reales.
- Advertencia al salir/recuperar con cambios sin guardar; controles de cabecera deshabilitados durante guardado para no perder ediciones concurrentes.

Archivos intervenidos por esta entrega (no confundir con los numerosos cambios preexistentes):

- `lib/models/order_draft.dart` (nuevo).
- `lib/database/order_drafts_repository.dart` (nuevo).
- `lib/database/database_helper.dart` (v18 y tabla nueva).
- `lib/screens/unified_order_creation_screen.dart` (reemplazo del ejemplo).
- `lib/screens/orders_list_screen.dart` (acceso al editor).
- `test/order_drafts_test.dart`, `test/screens/order_draft_screen_test.dart` (nuevos).
- `test/database/database_helper_test.dart`, `test/integration/db_schema_integration_test.dart` (expectativas de versión actualizadas).

Se preservaron modificaciones anteriores sin reset, checkout destructivo ni commits ajenos. Resolver dependencias offline actualizó metadatos locales del SDK; no se solicitó actualización de paquetes. No se modificaron Sticker Studio, Creador de Planchas, calibraciones ni código productivo Desktop.

## Pruebas y limitaciones de evidencia

Primer intento: hook nativo falló por espacios en la ruta del SDK; segundo intento encontró referencias al alias G: inexistente. Se restauró ese alias al mismo SDK instalado y se resolvieron dependencias con `pub get --offline`. No eran fallos de negocio de la aplicación.

La primera ejecución completa utilizable se solapó con cambios de esta tarea: **no constituye una línea base limpia anterior a la modificación**. Reportó 279 aprobadas y 16 fallos (dos expectativas v16 y catorce tests de Configuración del servidor). La siguiente ejecución, con pruebas nuevas y una expectativa corregida, reportó 292 aprobadas y 15 fallos. Queda registro en `artifacts/mobile-s1-full-test.log`.

Validación focalizada final: **31 aprobadas, cero fallos**, incluyendo las 12 nuevas pruebas de modelo/repositorio, dos de widgets y regresiones de esquema/sync. Registro: `artifacts/mobile-s1-focused-test.log`. Se probaron recuperación tras cerrar base, asociaciones 40/35/25, parcialidad, cantidades inválidas, unidades distintas, aislamiento de vendedor, reintento local sin duplicados, conflicto, rollback y conservación al limpiar caché.

Suite general final: **295 aprobadas y 14 fallos**, todos en `server_config_screen_test.dart`; ninguna expectativa de esquema queda fallando. Registro completo: `artifacts/mobile-s1-full-final.log`. No se excluyeron ni silenciaron esos fallos para presentar una suite verde.

Análisis focalizado: **sin errores ni warnings; 14 observaciones de estilo** en `artifacts/mobile-s1-analyze.log`. Análisis general anterior: 54 observaciones, incluidas advertencias de código preexistente. No equivale a compilación Android verificada.

Los fallos de Configuración del servidor reportan «La configuración no terminó de cargar»: el helper de test bombea tiempo virtual mientras espera SQLite real. No se modificaron esa pantalla ni esos tests aquí; debe aislarse el problema de harness/carga antes de promover. No se afirma que el problema real sea exclusivamente del entorno sin una reproducción controlada.

No hay capturas reales de dispositivo, pruebas físicas Android ni prueba E2E con Studio conectado. Los widgets se renderizaron en tests, no se presentan sus resultados como capturas de un teléfono. No hay APK nuevo porque faltan regresiones generales satisfactorias y verificación de compilación.

## Bloqueo y propuesta de continuación

1. Definir/adaptar con pruebas el contrato integral Desktop: identidad de pedido y trabajo, código de variante, unidad, IDs de demanda/diseño, cantidades y revisión esperada. Debe aplicar reglas existentes de reservas y producción antes de admitir cambios o desvínculos.
2. Implementar idempotencia del alta/agregado de productos y estados diferenciados de rechazo, resultado incierto y confirmado; no reencolar errores comerciales como si fueran desconexión. Cotización oficial y caducidad explícitas.
3. Publicación de borradores y edición de pedidos existentes mediante ese contrato: conservar pendientes, resolver conflictos, no sobrescribir caché como si fuera escritura remota confirmada. Migrar las entradas de UI solo cuando tengan paridad; no ocultar los flujos actuales prematuramente.
4. Completar selectores de atributos y catálogo cacheado versionado, edición de cabecera, búsqueda/paginación de diseños y pruebas widget de todas las variantes/cambios. Los borradores permiten guardar incompleto pero no deben convertirse en venta definitiva sin estas validaciones.
5. Aislar fallos generales, establecer baseline reproducible, compilar Android, generar APK de prueba y obtener capturas y aceptación real antes de recomendar uso operativo.

Este es un bloqueo concreto para la unificación completa solicitada, no una declaración de sincronización terminada. No se publica ni inicia automáticamente un sprint adicional.
