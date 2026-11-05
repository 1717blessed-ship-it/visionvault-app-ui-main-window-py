# Sprint 2A — auditoría y preflight; escritura BLOQUEADA

Fecha: 2026-10-24. Rama actual: codex/mobile-s1-pedidos-subproductos. Esta es una entrega **parcial**, no el backend transaccional listo para conectar Mobile. No hay ruta nueva de escritura, sincronización automática ni APK.

## Contraste con servicios reales

Se leyó íntegramente MOBILE_DESKTOP_CONTRACT_V1_PROPOSAL.md y se inspeccionaron el router móvil, autenticación, catálogo, ImageDatabase y servicios productivos. Las operaciones internas reutilizables son create_order_with_details, save_order_snapshot, _write_order_jobs, delete_order_job, snapshot productivo, guardas de demanda/reservas y delivery_readiness. No se creó un segundo motor de pedidos ni un cálculo comercial nuevo.

| Operación | Existente | Brecha para agregado remoto seguro |
|---|---|---|
| Crear pedido/trabajos/demanda | create_order_with_details | Alta y guardado poseen commits internos; no incluye recibo idempotente |
| Consultar | Snapshot sync/pull y consulta de jobs | No snapshot editable completo con revisión monotónica |
| Editar/agregar/quitar trabajos | save_order_snapshot / replace_order_jobs / delete_order_job | API antigua no usa siempre las guardas; identidad cliente-servidor pendiente |
| Productos/variantes | products/product_variants activos y catálogo HTTP | Resolver código/opción y cotización oficial dentro de transacción |
| Diseños y distribución | demanda por design_line_id y trabajo, completa/parcial | Resolver catálogo autorizado, asociar identidad estable sin paths del teléfono |
| Unidades/hojas | item/sheet en producción | Adaptación explícita desde units/sheets local; nunca sumar mezclas |
| Precios/snapshots | _write_order_jobs y snapshots comerciales Desktop | No se admite precio móvil; preservar histórico y pedir recotización explícita |
| Reservas y producción | Guardas existentes de job/demanda | Reutilización atómica; no basta el PATCH SQL antiguo |
| Entrega | mark_order_delivered / delivery_readiness | Ruta antigua deliver escribe SQL directo |
| Revisión e idempotencia | request_id en alta sticker; pago idempotente | No hay revisión global del agregado ni journal de operaciones completas |

## Bloqueos concretos de la transacción

`save_order_snapshot` abre `with self.connection`, después vuelve a actualizar finanzas y llama a `connection.commit()`. `create_order_with_details` llama a create_order y luego al guardado de snapshot. Un BEGIN/SAVEPOINT externo no impide que esos commits internos confirmen antes del recibo. Si falla la última fase podría existir un pedido sin operación confirmada. No se hizo un wrapper que prometa un rollback falso.

La revisión no puede ser solo un contador dentro de una ruta móvil nueva: las modificaciones hechas por UI, demanda, pagos, producción y PATCH antiguos deben invalidar la base sobre la que editó Mobile. updated_at no garantiza una revisión monotónica ni captura todas las mutaciones con igual precisión. Tampoco basta un hash calculado fuera del bloqueo de escritura.

Por eso el coordinador de escritura no se implementó en este avance. Se requiere adaptar las fronteras transaccionales de los servicios compartidos, definir qué cambios invalidan revisión, instrumentar esas escrituras y persistir recibos/mapeos con unicidad. Son cambios centrales con impacto que debe cubrirse, no una migración cosmética. No se declaran pruebas de concurrencia, rollback integral o idempotencia remota de un servicio inexistente.

## Implementado y límites exactos

`app/services/mobile_order_contract.py`: preflight V1 puro/SELECT, no registrado en HTTP. Allowlist estricta de campos, versión entera, límites de payload 64 KiB/30 trabajos/100 diseños por trabajo, enteros positivos sin convertir bool/float/string, revisión esperada estructural, identidades estables, duplicados y distribución parcial/completa. Rechaza precios, pagos y estados administrativos extra. Genera huella SHA-256 canónica independiente del orden de claves. **Huella no es registro idempotente ni prueba de commit**.

check_catalog consulta productos activos y variantes activas del producto correcto, contrasta material/tamaño configurados y utiliza un resolver de diseños autorizado suministrado por el catálogo existente. No acepta rutas. No consulta ni modifica reservas; las guardas productivas siguen en los servicios existentes. No hace cotización comercial ni adjudica autorización. Debe repetirse dentro de la futura transacción; el preflight por sí solo tiene TOCTOU y no habilita escrituras.

No hay persistencia nueva, migraciones, credenciales ni modificaciones Flutter. El contrato generado por OrderSyncProposal es compatible estructuralmente: IDs remotos string decimal/null, unidades item/sheet y association_id opaco. Falta un intercambio automatizado Dart→Python ejecutado en un mismo harness; la prueba Python usa las mismas claves y codificación de tupla, no se presenta como E2E Flutter/Desktop.

## Seguridad del servidor existente

_validate_auth verifica bearer contra sesión de dispositivo. _authorize_network_request aplica whitelist y rate limiting. Hay feature gates y modo mantenimiento. Login/enlace bloquean credenciales públicas por HTTP; esto no demuestra que toda escritura remota herede TLS/permisos completos. La futura operación deberá validar scope usuario/dispositivo y propiedad del pedido, token revocado, permisos y transporte por sí misma. No se abre ni publica un servicio en Internet.

_read_json_body actualmente limita a 10000 bytes; el máximo de 64 KiB del preflight NO cambia ese límite ni habilita una ruta de ese tamaño. Falta tratamiento común de Content-Length negativo/no numérico, Unicode inválido y raíz JSON incorrecta en rutas antiguas. El preflight no corrige el framing HTTP. No devolver SQL, excepciones internas o rutas en errores nuevos. Las rutas antiguas contienen mensajes con excepciones: riesgo pendiente, no afirmación de seguridad integral.

## Matriz de respuestas del contrato ajustado

| Caso | Estado previsto de futura escritura | Implementación hoy |
|---|---|---|
| Alta / actualización | 201 / 200, persisted=true + recibo tras commit | No disponible |
| Reintento idéntico | Recibo original, sin nueva mutación | No disponible; solo fingerprint probado |
| Revisión antigua | 409 revision_conflict | Solo validez estructural; no compara revisión vigente |
| Mismo operation_id, contenido diferente | 409 operation_mismatch | No journal ni endpoint disponible |
| Producto/variante inválidos | 422 product_invalid / variant_invalid | Preflight SELECT implementado |
| Opción cambiada | 422 catalog_stale en preflight | Implementado; propuesta anterior lo listaba como 409 |
| Cantidad estructural inválida/distribución excesiva | 422 validation_failed | Implementado |
| Cantidad incompatible con producción | 409 production_committed | Guardas internas existentes, no adapter nuevo |
| Diseño no disponible | 422 design_not_found | Resolver en preflight; sin exposición de path |
| No autorizado / error interno | 401/403 / 500 genérico | Contrato futuro; controles antiguos no prueban la ruta nueva |
| Payload excesivo | 413 payload_too_large | Preflight implementado, límite HTTP antiguo distinto |

Todo error nuevo incluye contract_version=1, persisted=false y error.code/field/message. El preflight devuelve datos validados, no recibo ni estado confirmado. Mobile debe conservar su borrador. No hay eliminación de pendientes por estas validaciones.

## Pruebas y evidencia

65 pruebas focalizadas aprobadas, cero fallos, 15,55 s: tests/test_mobile_order_contract.py, test_order_sprint1_integrity.py, test_delivery_readiness.py, test_order_workflow_service.py, test_order_production_service.py. Reporte artifacts/mobile-s2a-focus.xml. Se usaron exclusivamente bases temporales. El nuevo preflight confirma cero escrituras por total_changes, ausencia de pedidos creados, rollback no aplicable por diseño. Las otras suites verifican guardas y comportamiento existente, no una operación remota nueva.

Validación final del módulo: **36 aprobadas, cero fallos**, 5,25 s, artifacts/mobile-s2a-contract-final.xml. Incluye una prueba diagnóstica adicional en base aislada que abre SAVEPOINT externo y verifica que save_order_snapshot lo elimina al confirmar: ROLLBACK TO falla por ausencia del savepoint y la edición ya persiste. Esto demuestra el bloqueo transaccional; no es una aprobación del comportamiento para uso remoto. La suite general iniciada antes de añadir ese diagnóstico no lo incluye; se informa por separado.

Suite general Desktop: **1354 aprobadas, 1 omitida, cero fallos; 5 subtests aprobados, 249 advertencias**, 283,59 s. Comando `python -m pytest tests -q`, carpetas artifacts/mobile-s2a-full-tmp/cache y reportes mobile-s2a-full.xml/log. El diagnóstico transaccional añadido después de iniciar la colección se verificó aparte como se indica arriba. No se reejecutó Flutter porque no se modificó su código; su resultado previo 313/313 no es una ejecución nueva de Sprint 2A.

## Recomendación y siguiente alcance necesario

No conectar envío de Mobile ni declarar Sprint 2A aceptado. Antes de Sprint 2B: completar el coordinador con frontera transaccional única, revisiones compartidas, journal de idempotencia bajo scope, mapping estable y recibos; adapter de cotización oficial; adapter HTTP autenticado y autorizado con framing/límites seguros. Cubrir las 16 operaciones pedidas en integración de una base aislada, especialmente dos conexiones concurrentes, respuesta perdida, fallo final, histórico de precios/pagos y producción comprometida. Hoy no están verificadas las operaciones nuevas de alta/edición/retry/concurrencia porque no existe el servicio seguro; este es el bloqueo, no pruebas omitidas presentadas como éxito.

Archivos nuevos: app/services/mobile_order_contract.py, tests/test_mobile_order_contract.py, este informe. El documento de propuesta previo se conserva como antecedente; este informe precisa diferencias y estado real. No hubo cambios de esquema ni rutas activadas.
