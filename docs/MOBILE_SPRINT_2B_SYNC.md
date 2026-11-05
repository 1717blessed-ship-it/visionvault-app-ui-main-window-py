# Sprint 2B — sincronización bidireccional aislada

Fecha: 2026-10-24. Rama: `codex/mobile-s2b-sync-aislada`. No se publicó, etiquetó ni generó APK. No se habilitó sincronización operativa. Se preservó el árbol recibido, con numerosos cambios previos sin confirmar; este informe identifica únicamente el trabajo del sprint.

## Alcance y arquitectura

Se reutilizan Sprint 1.1 (editor, borradores, IDs y DTO), 2A.1 (revisión compartida, transacción, journal y outbox) y 2A.2 (HTTP V1, autorización y guardas). No se reimplementó el motor de precios, producción ni reservas.

Flujo implementado:

```text
Editor existente / revisión local
  → OrderDraftsRepository / order_drafts
  → OrderIntegrationStore / cola durable + vínculos remotos
  → OrderIntegrationClient / HTTP V1 loopback
  → OrderSyncHandler / autorización + catálogo
  → OrderOperationService / transacción única + revisión + journal
  → SQLite temporal Desktop
  → recibo persistido verificado / vínculo local-servidor
```

El borrador, el payload retenido de una operación, el snapshot remoto y el recibo histórico son objetos diferentes. `OrderDraft.revision` continúa siendo local. `integration_order_links.server_revision` conserva el token Desktop; no se supone que aumente exactamente en uno por acción.

El editor normal no construye este servicio ni comienza envíos. La entrada separada `lib/integration_order_main.dart` exige ejecución no release y `DOCCIONE_ORDER_INTEGRATION=true`; sigue sin ser la entrada productiva. Solicita enlace o recuperación explícitos y reutiliza el mismo editor. No se compiló ni probó esa entrada en un teléfono: se probaron su lógica compartida y el editor con el motor de pruebas Flutter.

## Frontera de aislamiento y credenciales

Desktop continúa creando exclusivamente su propia `integration.db` en un TemporaryDirectory; no admite una ruta de base ni bind público. Escrituras apagadas por defecto. Se encienden solo desde el constructor confiable de pruebas. El namespace operativo mantiene 503 y no acepta parámetros del cliente para habilitarlo.

Mobile admite solo HTTP en `127.0.0.1` con puerto explícito, sin paths, usuario, query ni fragmentos. Rechaza URLs LAN, dominios y redirecciones; no hay `badCertificateCallback`, certificados omitidos ni excepciones permanentes de TLS. **El transporte actual no permite piloto por Wi-Fi/LAN ni acceso remoto.** No se presenta loopback HTTP como homologación de HTTPS.

Cada base Desktop aislada conserva un UUID en `order_sync_environment`. Todas las respuestas del adaptador llevan `integration_server_id`; capabilities también informa el dispositivo autenticado. La cola se vincula a la tupla `integration-v1 / UUID / device_id`, además de su propietario local. Cambiar explícitamente de puerto después de un reinicio puede recuperar el mismo realm, pero cada respuesta debe conservar su UUID y las capacidades deben validar el mismo dispositivo. Una dirección igual no prueba identidad; una base nueva en esa dirección no puede confirmar las operaciones viejas.

La identidad está persistida dentro del respaldo: restaurar una copia como reemplazo del mismo servidor conserva el realm. No se certifica operar simultáneamente dos clones activos de ese mismo respaldo: requeriría reglas de autoridad/fork adicionales. El UUID no es una credencial ni reemplaza TLS o autorización.

El enlace utiliza el código local de un solo uso y los bearer revocables existentes de EventRepository. El código y token no están incorporados a fuentes, defines, cola ni APK. La entrada de integración reserva una clave separada de FlutterSecureStorage para recuperar la sesión; su funcionamiento en dispositivo/keystore real queda pendiente. Las credenciales de los procesos de prueba se transmiten por entorno efímero, nunca por argumentos ni por archivos del repositorio.

La SQLite Mobile de integración es un archivo separado `doccione-mobile-order-integration-*.db`, sin migrar `doccione_mobile.db`. El store rechaza nombres de archivo que no corresponden a ese espacio. La entrada obtiene una ruta propia, no una ruta ingresada por red. Los borradores contienen datos comerciales locales necesarios; tokens/códigos no se guardan allí. No se debe introducir información real en este piloto.

## Contrato utilizado

V1 de Sprint 2A.2, prefijo `/api/v1/mobile/order-sync/`:

| Operación | Ruta real |
|---|---|
| Enlace explícito | POST pair |
| Negociación y scope | GET capabilities |
| Productos, variantes y diseños disponibles | GET catalog |
| Pedidos autorizados/revisiones | GET orders |
| Agregado vigente | GET orders/{id} |
| Preflight sin guardar pedido | POST validate |
| Alta o edición completa | POST operations |
| Recuperación de confirmación | GET operations/{operation_id} |

No se inventaron endpoints nuevos ni se llamó a las escrituras legacy. Cambios aditivos V1: identidad de entorno en respuestas, dispositivo en capabilities, notas del trabajo en snapshot y metadatos de hasta 100 diseños públicos/reutilizables en catalog. No se exponen paths ni se implementa descarga de previews: el selector existente puede asociar los diseños por nombre/ID. No hay paginación ni galería completa.

El DTO convierte units/sheets locales a item/sheet. Solo propone cliente/contacto/notas, trabajos y distribución. Precios, costos, estados, pagos y reservas son autoridad Desktop. La cotización local nunca confirma una venta. La validación comercial definitiva ocurre dentro de la transacción del servidor.

## Cola, confirmación y recuperación

`integration_order_queue` retiene ID criptográficamente aleatorio estable, propietario, identidad del servidor/dispositivo, identidad del pedido local, tipo, payload serializado, revisión base, revisión local enviada, estado, intentos, último código de error, creación, siguiente intento, recibo, fecha de recepción de confirmación y snapshot conflictivo. Los payloads no se regeneran al reintentar.

Preparar envío exige un borrador ya guardado y vigente; estructura/cantidades/límites se validan localmente. No se requiere conexión para conservarlo. No se puede sustituir una operación pendiente por otra ni enviarla con otra identidad. Guardar después de preparar conserva la nueva edición local separadamente.

Antes de enviar se comprueban capacidades/realm/dispositivo. Se consulta primero el resultado de la operación; si no existe se envía exactamente el payload retenido. La confirmación exige persisted=true, versión, ID de operación, SHA-256 canónico del payload/tipo/pedido/revisión, identidad local/remota, revisión y mapeos de trabajos/demanda coherentes. Un 200 vacío o un recibo ajeno nunca confirma. Cola y vínculo se actualizan en una transacción SQLite local. No se borra ninguna operación ni borrador, incluso después de confirmar.

La entrega de un recibo antiguo no confirma una edición local posterior ni hace retroceder una revisión remota más reciente. Un error al recibir/validar la confirmación conserva la operación; la recuperación consulta el journal antes de volver a escribir.

Drain es manual, no se registra en inicio, timers, SyncService productivo ni conectividad. Procesa como máximo 10 operaciones por invocación y evita reentrada. Backoff exponencial acotado (2–256 s) queda persistido; no hay bucle automático. Red desconectada/timeout y errores transitorios no se confunden con rechazo comercial. Tras corregir una sesión o validación, el operador puede rearmar el mismo intento; no se regenera el ID. El cierre del entorno espera el drain en curso antes de cerrar su base/cliente.

## Estados y experiencia

| Estado | Significado |
|---|---|
| Guardado local | No hay una operación confirmada para la edición actual |
| Pendiente | Payload retenido, todavía sin confirmación |
| Sincronizando | Intento en curso, sin éxito anticipado |
| Sincronizado y confirmado | Recibo real válido para esa revisión local |
| Conflicto | Revisión rechazada; ambas versiones conservadas |
| Error recuperable | Conexión/timeout/transitorio; espera/reintento controlado |
| Requiere intervención | Permiso, sesión, validación, producción o respuesta incompatible |

El panel se inyecta en el editor existente: muestra conexión, estado del pedido, cantidad de operaciones activas pendientes, fecha de recepción de la última confirmación, ID/revisión y errores. Una edición posterior retira el indicador de confirmado para la edición actual. Se distingue guardar local de preparar/enviar/confirmar. No hay un segundo módulo de Pedidos.

## Bidireccionalidad y conflictos

GET del agregado entrega el snapshot vigente, no el recibo histórico. Mobile lo aplica solo si coincide con su vínculo y no existen operaciones activas pendientes ni revisiones locales posteriores a la base confirmada. La actualización del borrador/vínculo es atómica y aumenta la revisión local. Los IDs Desktop no se usan como IDs locales.

Una modificación Desktop incrementa la revisión mediante los triggers existentes, también cuando no proviene de HTTP. Un envío basado en la revisión anterior recibe revision_conflict: no hay escritura parcial, se conserva el payload local y se consulta/persiste la versión remota autorizada. La interfaz permite ver ambos estados.

Resolución explícita acotada: tras revisar el conflicto, se puede preparar una nueva propuesta de cabecera/notas **solo si todos los trabajos, cantidades, unidades y diseños coinciden** con la versión Desktop consultada. El rechazo original permanece con su payload/snapshot y active=0, nunca se marca confirmado. La propuesta nueva tiene otro ID porque es una operación distinta, basada en la nueva revisión, no un retry de resultado incierto. No se envía automáticamente y puede volver a entrar en conflicto. Cambios comerciales, de distribución o productivos requieren intervención Desktop; no se fusionan ni se impone silenciosamente una versión ganadora.

## Escenario y defecto encontrado

Escenario ficticio E2E: cliente «Cliente FICTICIO Flutter», producto/variante activos creados por el fixture con servicios de catálogo, trabajo de 100 unidades a 5 cm y diseños A/B/C 40/35/25; segundo trabajo de 2 hojas con una hoja asignada al diseño A y una pendiente. Misma imagen en trabajos diferentes, unidades explícitas y precio oficial calculado en Desktop. Se confirman IDs, asociaciones, cuatro líneas de demanda, cantidades y revisión; el replay conserva un único pedido y dos trabajos.

Se modifican observaciones desde Desktop, se reciben en Mobile sin cambios pendientes, se guarda una respuesta desde Mobile y se confirma en Desktop. Una edición concurrente conserva la versión local y el snapshot remoto. Se prueba aparte una reserva real mediante ProductionBatchService en SQLite temporal, sin imprimir ni cambiar etapas físicas: la edición remota se rechaza integralmente.

**Defecto real detectado y corregido:** al editar trabajos que comparten una imagen, save_order_snapshot podía usar el vínculo histórico del path si el adaptador solo entregaba un índice. Se corrigió únicamente el adaptador: entrega order_job_id explícito para trabajos existentes y None explícito para resolver el índice de los nuevos, evitando el fallback por imagen. Se agregó una verificación de trabajo/cantidad/unidad de cada línea y del total antes del commit. No se modificó el servicio central ni sus reglas productivas. La regresión cubre una imagen compartida entre unidades y hojas, edición y agregado de otro trabajo, así como retry. Las nuevas comprobaciones Flutter rechazaron el recibo inconsistente, evitando mostrarlo como confirmado.

## Pruebas y evidencia

Punto de partida: 85 Desktop/HTTP y 19 Flutter aprobadas. Focalizada Desktop final: **88 aprobadas** (31 HTTP, 21 transaccionales, 36 de contrato), artifacts/s2b-regression-final.xml. Incluye namespace operativo 503, rollback, concurrencia, reservas, backups, autorización, límites y el nuevo mapeo de imagen compartida.

Flutter integración/editor: **20 aprobadas**, artifacts/s2b-e2e-release.log. Incluye HTTP nativo real, varios trabajos/diseños/variantes, ida/vuelta, retry de alta y edición, colisión, conflicto/resolución acotada, aislamiento entre servidores/propietarios, token incorrecto/ausente/revocado/caducado, validación, precio no autorizado, preservación de precio histórico, rechazo productivo, desconexión antes de envío, timeout durante commit, respuesta perdida después del commit y reentrada.

Recuperación probada tanto al cerrar/reabrir SQLite y reconstruir servicios como **entre dos procesos Flutter independientes**: primero guarda la operación y termina; el segundo recupera el mismo ID/payload, consulta/envía y obtiene confirmación. Evidencia: artifacts/s2b-process-restart.log. No es una afirmación de reinicio físico de Android ni de recuperación de su keystore.

Recibo real sin credenciales: artifacts/s2b-e2e-confirmed.json. Prueba de contrato compartido Python/Flutter conservada. Los comandos se ejecutan desde la raíz Desktop y desde mobile/doccione_mobile, respectivamente:

```text
python -m pytest tests/test_order_sync_http.py tests/test_order_operation_service.py tests/test_mobile_order_contract.py
flutter test test/order_integration_e2e_test.dart test/screens/order_integration_editor_test.dart --no-pub
flutter test --concurrency=2 --no-pub
```

Resultados finales:

- Desktop general: **1407 aprobadas, 1 omitida, cero fallos**, 249 advertencias y 5 subtests aprobados, 490,35 s. artifacts/s2b-full-final.xml/log. Runtime Tcl/Tk previamente comprobado, sin excluir ni modificar la prueba gráfica.
- Flutter general: **334 aprobadas, cero fallos**, artifacts/s2b-flutter-final.log. Incluye persistencia, widgets, integración HTTP y recuperación entre procesos.
- Contrato Flutter explícito: **6 aprobadas**, artifacts/s2b-contract-flutter.log; incluye consumo del recibo HTTP real de Python.
- Análisis estático focalizado: **sin incidencias**, artifacts/s2b-analyze-release.log (9 archivos del adaptador/pruebas). No se declara análisis global sin incidencias del árbol heredado.

La corrida de 20 E2E/editor es cobertura incluida en la general Flutter, no 20 pruebas adicionales al total 334. Los 31 casos HTTP están incluidos en las 88 focalizadas y en la general Desktop. No se suman recuentos superpuestos.

Incidencias de entorno: una general Desktop tuvo 1403 aprobadas, 1 omitida y fallo al leer ttk/cursors.tcl, aunque el archivo existía; artifacts/s2b-full.xml/log. Con el runtime previamente validado, Tk y la prueba gráfica aislada pasaron (artifacts/s2b-tk-check.xml); se repite la general sin modificar ni omitir la prueba. El primer fixture stdio necesitó PYTHONIOENCODING=utf-8 en Windows; no se cambió el JSON HTTP para ocultarlo. La primera captura esperaba al codificador PNG dentro del reloj virtual; se movió exclusivamente esa E/S del harness fuera de FakeAsync, manteniendo aserciones y HTTP real. Los fallos de conciliación de la primera general Flutter quedaron registrados y originaron la corrección real detallada arriba, no se atribuyeron al entorno.

## Capturas verificadas

Capturas del editor Flutter renderizado por flutter_tester con datos ficticios y HTTP real, no mockups dibujados ni fotografías de un dispositivo. Se cargaron fuentes legibles del Windows del host. No se declara prueba visual física Android.

- artifacts/s2b-editor-local.png
- artifacts/s2b-editor-pending.png
- artifacts/s2b-editor-confirmed.png
- artifacts/s2b-editor-conflict.png
- artifacts/s2b-editor-both-versions.png

## Archivos de esta entrega

Mobile nuevos: lib/services/order_integration_client.dart, order_integration_sync.dart, order_integration_catalog.dart; lib/widgets/order_integration_status.dart; lib/integration_order_main.dart; test/order_integration_e2e_test.dart; test/screens/order_integration_editor_test.dart; test/support/order_integration_fixture.dart; contract_tests/order_queue_process_test.dart. Adaptados: OrderDraftsRepository (proveedor de SQLite aislada; default productivo intacto), UnifiedOrderCreationScreen (inyección/panel), comentario del DTO, pubspec.yaml/lock (crypto 3.0.7 ya instalado pasa a dependencia directa).

Desktop: app/api/order_sync_integration.py (realm/metadatos/mapeo verificado y fallo de respuesta confiable solo para pruebas), tests/test_order_sync_http.py, tools/order_sync_e2e_fixture.py y este informe. No se editaron Sticker Studio, Planchas, calibraciones ni módulos de producción/reservas. No se modificó nuevamente el handler operativo.

## Datos reales, límites y dictamen

Hash inicial, intermedio y final del archivo visionvault.db: EEE320DCA78CC2F5ABB9D5D04EEB758ED4B98B8B949A2B7FA721DF1F30A83EBF, sin cambios. No se pasó su ruta al servidor ni al fixture y no se instalaron migraciones allí. El hash del archivo principal no equivale a una auditoría WAL integral.

Persisten las limitaciones del contrato seguro: edición comercial de trabajos existentes, eliminación/importación de trabajos Desktop sin mapeos, galería completa y producción comprometida no se habilitan. Un trabajo Desktop nuevo sin client_job_id o una asociación sin identidad admisible se rechazan para edición automática, conservando el borrador. La lista autorizada está acotada a 100. No se certifican rutas legacy por estas pruebas.

Pendientes para piloto móvil físico: transporte TLS/destino verificable fuera de loopback, identidad de vendedor/cuentas/permisos operativos (el fixture usa realm de dispositivos aislado), pruebas Android/secure storage/path provider, corte abrupto del dispositivo/OS y cambio físico de Wi-Fi. Se probaron desconexión HTTP real, endpoint cambiado explícitamente, restart del listener y procesos Flutter nuevos; no se simula haber realizado ensayos de hardware/red física.

Dictamen: Sprint 2B técnicamente verificado para pruebas controladas de integración loopback con datos ficticios. Flujo bidireccional, cola, revisión, idempotencia y recuperación demostrados bajo el alcance descrito. **No está listo para piloto móvil físico por Wi-Fi/LAN**: bloqueos concretos son transporte seguro/destino verificable fuera de loopback, unión a cuentas/permisos y aceptación Android real. No autoriza sincronización productiva, APK ni publicación. No se inicia otro sprint automáticamente.
