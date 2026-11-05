# Sprint 2A.2 — adaptador HTTP de integración aislada

Fecha: 2026-10-24. Rama: `codex/mobile-s2a2-api-aislada`.

## Estado y frontera de seguridad

Se implementó un adaptador HTTP real, probado en loopback con datos ficticios y bases temporales. **No está conectado a la aplicación operativa ni habilita sincronización Flutter.** No se generó APK ni se publicó el servidor. La aplicación móvil no recibió cambios productivos: solo pruebas contractuales.

El servidor operativo existente rechaza GET/POST del namespace nuevo con 503 `order_sync_disabled`, antes de interpretar parámetros de activación. Los endpoints legacy mantienen su comportamiento anterior: este sprint **no los certifica ni migra al coordinador nuevo**. En particular, las rutas antiguas de edición/entrega siguen requiriendo la revisión de seguridad ya documentada.

`OrderIntegrationEnvironment()` crea siempre su propio TemporaryDirectory y una base nueva `integration.db`; no recibe una ruta de SQLite, dirección de red ni base operativa. Escribe pedidos solo con `enable_writes=True` configurado por código de pruebas. Cada petición comprueba el archivo real de la conexión con PRAGMA database_list y su ubicación en el temporal propiedad del entorno. Un body/query `test_mode`, `enable_writes` o similar no cambia esa configuración. No se instala ninguna migración en producción.

`integration_server(environment)` solo escucha en 127.0.0.1 y puerto efímero; no hay CLI, autoinicio ni opción de bind público. HTTP sin TLS se permite exclusivamente en este entorno local descartable: **no es una configuración segura para Wi-Fi doméstico, LAN ni acceso remoto**. El despliegue real deberá definir TLS con verificación de certificado y autenticación operativa completa; no se confía en cabeceras de proxy para simular transporte seguro.

## Núcleo verificado y arquitectura

Antes del adaptador se ejecutaron 57 regresiones del núcleo transaccional y contrato, sin fallos. Se revisaron OrderConnection, triggers y OrderOperationService: BEGIN IMMEDIATE, commits internos diferidos, rollback integral, autorizar cada replay, comparación de revisión y journal dentro del mismo commit. Los eventos se almacenan en outbox usando la conexión del hilo; no se inicia ningún consumidor de notificaciones en el entorno HTTP.

Flujo del adaptador: framing/límite/rate limit → bearer revocable → scope de dispositivo → DTO V1 estricto → coordinador → revalidar token dentro del lock → catálogo/variantes/diseños y motor comercial Desktop → create_order_with_details/save_order_snapshot → identidades persistidas → snapshots comerciales/historial → snapshot del resultado → journal/commit → respuesta HTTP. No se envía a la API un callback ni SQL desde el cliente.

La ampliación interna `result_data` del coordinador captura el snapshot y los mapeos **dentro de la transacción**, sin permitir sobrescribir los campos del recibo. La revisión se vuelve a comprobar antes del commit. Así una respuesta y sus reintentos contienen el resultado original confirmado, no una mezcla con otra modificación concurrente. GET del pedido sirve el snapshot vigente; GET del resultado sirve el recibo histórico original.

## Rutas y métodos

Prefijo en la instancia aislada: `/api/v1/mobile/order-sync/`.

| Método/ruta | Resultado |
|---|---|
| POST pair | Consume código local de un solo uso; devuelve token de sesión una vez |
| GET capabilities | Versión, límites, integration_only y funciones habilitadas/restringidas |
| GET catalog | Catálogo de productos y opciones del handler Desktop existente |
| GET orders | Hasta 100 pedidos no archivados propiedad del dispositivo, con revisión |
| GET orders/{id} | Ficha, trabajos, asociaciones y revisión vigente, sin rutas locales |
| POST validate | Validación comercial/estructural y de revisión sin guardar el pedido |
| POST operations | Alta si desktop_order_id=null/revisión 0; edición con ID/revisión esperada |
| GET operations/{operation_id} | Recibo persistido del actor autorizado |

No hay DELETE, entrega, cambio de etapa, pagos, cancelación de tandas ni ejecución arbitraria. PATCH responde 405 en la instancia aislada. Todas las respuestas del adaptador llevan contract_version=1. La lista de pedidos está acotada a 100 y aún no tiene paginación; no debe interpretarse como exportación completa. La galería/preview de diseños no se publica desde este servidor descartable: se prueban IDs de diseños previamente publicados en el catálogo de la base aislada.

## Autenticación, autorización y errores

Se reutilizan EventRepository.register_device_with_pairing y validate_session_token: código creado localmente, consumo de un solo uso, token aleatorio, almacenamiento hash, expiración y revocación del dispositivo. No hay credenciales fijas. Las pruebas usan dispositivos del realm temporal; **no prueban la cadena de login de vendedor + enlace de la aplicación operativa**. Esa vinculación a cuentas/roles debe integrarse antes de un despliegue.

Todos los datos de pedido y recibos se restringen a creator_device_id; otro dispositivo recibe 403/404 y no ve recibos ajenos. La autorización se repite dentro del lock, incluyendo validez del token, para no aceptar revocaciones entre autenticación inicial y escritura. No existe un rol administrativo remoto en este adaptador. El actor se deriva del token, nunca del payload.

Límites: 64 KiB de body, 30 trabajos, 100 diseños/trabajo, 10000 unidades por cantidad y 120 peticiones/minuto por IP de loopback. Content-Length único, decimal no negativo, sin Transfer-Encoding; Content-Type JSON obligatorio; timeout de lectura de 3 s. Se rechazan JSON duplicado, raíz no objeto, Unicode inválido, valores no finitos y campos administrativos desconocidos. La validación de precio/medida también rechaza resultados comerciales negativos/no finitos y geometría no finita; no introduce una fórmula comercial alternativa.

Los rechazos se registran con código, fecha y dispositivo cuando se conoce, sin bearer, códigos de enlace ni payload/PII. Las respuestas no incluyen excepciones SQL, stack traces ni rutas internas. Los diagnósticos internos del servidor se registran localmente, no se devuelven al cliente. En Windows se corrigió el cierre de la conexión por request y se espera a los hilos antes de quitar el temporal. La conexión utilizada para restaurar el respaldo también se cierra explícitamente.

| Caso | HTTP / error.code |
|---|---|
| Alta / edición confirmada | 201 / 200 con persisted=true, ID, revisión, hash y snapshot |
| Reintento idéntico | Mismo recibo y código de su operación original; no nueva escritura de pedido |
| Revisión antigua | 409 revision_conflict |
| Clave reutilizada con otro contenido | 409 operation_mismatch |
| Otro create para identidad cliente ya usada | 409 client_identity_exists |
| Cambio de identidad local de pedido | 409 client_identity_mismatch |
| Producto/variante inválidos | 422 product_invalid / variant_invalid |
| Opción material/tamaño desactualizada | 422 catalog_stale |
| Sin cálculo comercial inequívoco | 422 commercial_validation_failed |
| Cambio comercial de trabajo existente | 409 commercial_change_requires_desktop |
| Historial/reservas productivas | 409 production_committed |
| Eliminación/importación de trabajos sin mapeo seguro | 409 job_removal_requires_desktop |
| Diseño no publicado o no disponible | 422 design_not_found |
| Diseño sin medida admisible | 422 design_size_unsupported |
| Cantidad, distribución o campos inválidos | 422 validation_failed |
| Token inválido/revocado / otro propietario | 401 unauthorized / 403 forbidden |
| Versión incompatible | 422 version_unsupported |
| Tamaño / framing / JSON / Content-Type / timeout | 413 / 400 / 400 / 415 / 408 |
| Abuso | 429 rate_limited |
| Escritura apagada / namespace operativo | 503 writes_disabled / order_sync_disabled |
| Error inesperado | 500 internal_error, sin detalles internos |

Errores: `{contract_version:1,persisted:false,error:{code:...}}`. Una validación positiva devuelve valid=true, persisted=false: no es confirmación de venta. La autenticación y la auditoría sí actualizan sus propios registros en la base temporal; «no guardar» se refiere a pedido, trabajos, demanda y precios. Mobile debe conservar borradores ante todo rechazo o resultado incierto.

## Integridad y alcance funcional admitido

Se reutiliza resolve_commercial_price y save_order_job_price_snapshot; no se copió el cálculo de precio del handler legacy ni se aceptaron importes del teléfono. Productos/variantes se revalidan dentro del lock, y el resultado de la regla debe corresponder a la variante seleccionada. El catálogo puede ofrecer opciones que el motor no resuelva inequívocamente por su firma: se rechazan, no se elige otra variante silenciosamente. Packs con confirmación comercial pendiente no se habilitan.

El catálogo de diseño se resuelve por el helper existente y además exige reusable=true, private=false y archivo fuente existente, aunque el modo legacy sea «all». No se acepta un path del teléfono ni se devuelve el path persistido. La demanda usa IDs deterministas por actor/pedido/asociación y mapping de trabajo estable. No hay conversión de hojas a stickers: el contrato usa item/sheet explícitos y conserva cantidades por trabajo.

En trabajos existentes se conservan los snapshots y precios. Por falta de contrato de recotización se bloquean cambios de producto/variante/material/tamaño/cantidad/unidad. Se admiten notas, cabecera, distribución sin producción comprometida y trabajos nuevos cotizados oficialmente. Se preserva la política de distribución existente; los trabajos nuevos permiten distribución parcial. Se bloquea toda edición ordinaria del agregado cuando tiene cualquier historial de asignaciones, incluso liberadas: restricción conservadora, no cancelación automática.

La eliminación de trabajos y la importación editable de pedidos Desktop sin identidad cliente quedan deshabilitadas. Los mapas de asociaciones conservan identidad histórica; el control de relaciones activas ocurre al guardar mediante los servicios centrales. PRAGMA foreign_key_check valida las restricciones declaradas de la base, no constituye por sí solo prueba de todas las reglas lógicas.

## Esquema y compatibilidad histórica

Solo el constructor aislado prepara la migración 2A.1 y las tablas locales order_sync_job_identity, order_sync_design_identity y order_sync_rejections. Instala los triggers también sobre los mapeos con order_id. No se añadieron migraciones automáticas a ImageDatabase o al arranque del servidor operativo.

Se verificaron respaldo SQLite consistente, restauración en otro entorno temporal nuevo, instalación repetida de migración, foreign_key_check sin incidencias, persistencia de tokens/recibos y replay después de reconstruir el servidor. No se restauró ni abrió una copia histórica real de clientes; la compatibilidad previa proviene de fixtures/copia aislada y regresiones, no de una validación de toda base histórica posible. No se ensayó la caída física del proceso/OS; se inyectaron fallos y pérdida real de conexión HTTP.

## Evidencia de pruebas

- Regresiones previas del núcleo y contrato: 57 aprobadas (artifacts/s2a2-baseline.xml).
- HTTP inicial ampliado: 23 aprobadas, incluyendo servidor real loopback, reserva productiva, cuatro fases de fallo SQL, precommit, permisos cruzados, revocación, validación, múltiples trabajos y diseños, idempotencia/revisión concurrentes, código de enlace de un solo uso, límites/framing y backup/reinicio.
- Focalizada final con guardas de valores no finitos: **83 aprobadas, cero fallos** (26 HTTP + 21 transaccionales + 36 del contrato), artifacts/s2a2-final-focus.xml. La suite general final revalida además los últimos campos de capabilities/respuestas versionadas.
- Flutter: **6 aprobadas**, artifacts/s2a2-flutter-contract.log. El DTO coincide con tests/fixtures/order_sync_v1_request.json; una prueba explícita consume el recibo JSON realmente recibido por HTTP y generado en artifacts/s2a2-http-contract-response.json. No existe aún un consumidor productivo Flutter de estos recibos: se comprueban serialización y forma del contrato, no UX/sincronización de la app.
- HTTP final del código entregado: **28 aprobadas, cero fallos en 32,96 s**, artifacts/s2a2-http-release.xml. Incluye cierre por cabeceras incompletas y rechazo del archivo fuente faltante, añadidos después de recolectar la general.
- General final: **1402 aprobadas, 1 omitida, cero fallos**, 249 advertencias y 5 subtests aprobados, en 305,57 s; artifacts/s2a2-full-private.xml/log. Se ejecutó con copia privada del mismo Tcl/Tk instalado, sin cambiar pruebas ni aserciones. La ejecución anterior tuvo 1401 aprobadas y un fallo al cargar ttk/spinbox.tcl del runtime compartido (artifacts/s2a2-full-final.xml/log); el aislamiento del runtime resolvió ese fallo de entorno. Los dos últimos casos HTTP se verificaron posteriormente en la corrida de 28, no forman parte del recuento 1402.

Comandos de compatibilidad (desde la raíz y luego mobile/doccione_mobile):

```text
python -m pytest tests/test_order_sync_http.py
flutter test test/order_sync_proposal_test.dart test/order_sync_http_contract_test.dart contract_tests/order_sync_receipt_test.dart --no-pub
```

La prueba del recibo está fuera de test/ para que la suite móvil ordinaria no dependa de un artefacto generado. Para esa prueba explícita debe ejecutarse primero pytest; no se inventa un recibo si falta.

Compatibilidad pendiente para Sprint 2B: el DTO V1 convierte units/sheets locales a item/sheet y pasa el fixture compartido. Sin embargo, OrderDraft.revision es una revisión local, no el token de revisión del servidor; deberán almacenarse por separado. Los desktop_order_id/desktop_job_id del recibo son strings y no sustituyen directamente las claves id de los modelos/cachés legacy. El error estructurado error.code tampoco coincide con el error string del cliente legacy: requiere un cliente dedicado. Estas pruebas no habilitan recepción productiva, actualización de cachés ni envío de borradores.

El timeout de 3 s se aplica desde la lectura inicial de cabeceras. Una cabecera incompleta puede cerrar el socket sin respuesta JSON; la prueba confirma ausencia de escritura. No se promete un envelope JSON para todo error del parser HTTP previo al handler.

## Archivos y dictamen

Nuevos: app/api/order_sync_integration.py, tests/test_order_sync_http.py, tests/fixtures/order_sync_v1_request.json, dos pruebas contractuales Flutter y este informe. Adaptados: app/services/order_operation_service.py (snapshot adicional confirmado dentro del journal), app/api/mobile_jobs.py (rechazo fijo del namespace nuevo). Se conservaron los demás cambios preexistentes.

Base operativa: no se pasó su ruta a ningún entorno/servidor ni se instaló su migración. SHA-256 del archivo visionvault.db antes y después de las validaciones: EEE320DCA78CC2F5ABB9D5D04EEB758ED4B98B8B949A2B7FA721DF1F30A83EBF, sin cambios. Comparar el archivo principal no sustituye por sí solo una auditoría WAL completa.

Dictamen: adaptador apto para continuar el desarrollo controlado de Sprint 2B **en integración aislada**, con las regresiones indicadas aprobadas. No habilitar envío ni escritura operativa. Pendientes de producción: transporte TLS, unión con cuentas/permisos operativos, paginación, catálogo/galería completa, importación y eliminación segura de trabajos, recotización confirmada, detalle de errores UI y aceptación en dispositivo real. No se declara que las rutas legacy sean seguras por estas pruebas. No se publicó, etiquetó ni generó APK.
