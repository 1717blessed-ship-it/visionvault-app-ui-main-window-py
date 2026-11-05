# Sprint 2A.1 — frontera transaccional interna

Rama: codex/mobile-s2a1-integridad-transaccional. Fecha: 2026-10-24. No se habilitaron endpoints, sincronización, APK ni publicación. No se abrieron ni migraron bases operativas. El esquema nuevo se instaló únicamente en bases temporales/copias de pruebas.

## Causa raíz y auditoría

ImageDatabase combina métodos independientes que usan `with self.connection`, commit explícito y helpers que vuelven a confirmar: create_order/create_order_with_details, save_order_snapshot, finanzas, historial y eventos. Un SAVEPOINT externo no era dueño del commit. EventRepository.publish_event agrega app_events y notification_outbox y confirma; además, ImageDatabase guardaba el repositorio con una conexión de otro hilo. No es envío de red directo, pero debía compartir la transacción.

Se inspeccionaron las fronteras en app/database/database.py, app/events/event_repository.py, app/api/mobile_jobs.py, order_workflow_service, production_batch_service y production_stage_service. Hay BEGIN IMMEDIATE propios en pagos y workflows, commit/rollback explícitos en repositorios y SQL directo en rutas antiguas. No se reescribieron estos flujos ni su motor comercial. Los participantes con BEGIN propio no están admitidos dentro del coordinador: fallan de forma cerrada en lugar de confirmar o anidar una transacción ficticia.

Efectos externos: el participante probado crea/guarda fichas, trabajos y demanda, registra historial y outbox SQLite. No admite preparación/exportación de archivos, impresión, envío de notificaciones, HTTP ni servicios con conexiones alternativas. El envío real del outbox debe seguir ocurriendo desde su consumidor después del commit. Un callback arbitrario con efectos externos no se vuelve reversible por usar este coordinador.

## Implementación

OrderConnection es una subclase de sqlite3.Connection usada por la fábrica de ImageDatabase. Fuera del contexto administrado conserva commit/rollback/context manager independientes. `order_transaction()` exige conexión limpia, hace BEGIN IMMEDIATE, difiere commits internos y deja un único commit al propietario externo. Excepciones, solicitudes de rollback, errores SQLite ocultos y contexto interno fallido dejan la operación marcada para rollback. No se reutilizan ni confirman escrituras previas ajenas. Se rechaza propiedad anidada.

Control explícito de transacción por SQL, executescript, cierre y reemplazo de authorizer dentro del participante se rechazan. El authorizer SQLite también impide COMMIT desde un cursor o comentario SQL que evada el chequeo textual. No permite ATTACH/DETACH, ALTER TABLE ni quitar triggers durante la operación. Los cursores y executemany propagan el estado fallido ante errores SQLite. No es una sandbox contra código Python malicioso: los participantes son servicios Desktop confiables, nunca funciones enviadas por un cliente HTTP.

ImageDatabase.event_repo ahora obtiene el repositorio de la misma conexión por hilo; su commit queda diferido y sus filas/outbox participan del rollback. No se cambió el formato de eventos ni los consumidores externos.

OrderOperationService coordina: validar identidad → BEGIN IMMEDIATE → autorizar → comprobar cobertura de revisión → buscar recibo → rechazar colisión o devolver recibo autorizado → comprobar revisión esperada → ejecutar participante Desktop con sus validaciones comerciales/productivas → comprobar pedido persistido → historial → leer revisión autoritativa → registrar resultado idempotente → punto de fallo precommit → verificar que no cambió la revisión después de preparar recibo → commit único → devolver confirmación. No responde con datos precommit si falla el commit. La aplicación no crea un segundo motor de reglas.

El método execute es una primitiva interna con callbacks de autorización y aplicación confiables, no un adapter automático del payload Flutter. No sustituye permisos reales, cotización oficial, resolución de catálogo ni guardas: el participante debe llamar a los servicios existentes y propagar sus errores. Las pruebas lo hacen con create_order_with_details/save_order_snapshot. Exponer esta primitiva como ejecución arbitraria sería inseguro y no se implementó.

## Migración explícita y revisiones

install_order_integrity no se invoca al importar ni abrir ImageDatabase ni durante la solicitud. Requiere conexión limpia. Prepara las tablas de outbox existentes, crea order_integrity_revisions, remote_order_operations y triggers; históricos comienzan en 1 sin modificar sus campos. Instalación repetible, validada sobre copia. Para despliegue futuro se exige respaldo SQLite consistente previo; no se hizo respaldo de producción porque no se tocó producción. La preparación de esquema no se presenta como migración de despliegue automáticamente ejecutada y puede requerir reintento idempotente si se interrumpe.

Los triggers INSERT/UPDATE/DELETE detectan cambios de cualquier conexión SQLite, incluidas rutas SQL antiguas. Cubren orders, order_jobs, order_designs, order_drafts, order_events, order_payments, order_previews, design_preparations, plancha_projects, plancha_item_assignments, print_jobs, print_history, order_design_job_links, order_design_demand_lines, order_job_production_estimates, order_job_internal_incidents, whatsapp_conversations y order_state_history. Las tablas con order_job_id resuelven su pedido a través de order_jobs. Si una nueva tabla tiene order_id/order_job_id y faltan triggers, el coordinador se niega a escribir hasta migrarla.

La revisión es un token monotónico de mutación, no necesariamente +1 por acción de usuario: varios statements pueden incrementarla varias veces. UPDATE redundante también invalida conservadoramente. Una transacción fallida revierte los incrementos. SELECT no incrementa. Las tablas de revisión/recibos se excluyen para evitar recursión. Revisiones y recibos conservan referencia histórica incluso si un pedido se elimina; no son filas de negocio nuevas del pedido.

Cobertura delimitada: captura escrituras en las tablas anteriores después de instalar triggers, no cambios de bytes de archivos, catálogo global o tablas nuevas sin FK nominal detectable. Esas dependencias requieren revalidación dentro del adapter futuro. En bases todavía no migradas **no se afirma protección de revisiones**, y el coordinador no las migra silenciosamente.

## Idempotencia y concurrencia

Clave persistente (actor, operation_id), scope provisto por autorización confiable. Hash canónico incluye tipo, pedido, revisión esperada y payload; mismo ID con contenido diferente es operation_mismatch. Tipos/actores distintos no se confunden; mismo actor e ID para otro tipo también produce conflicto. BEGIN IMMEDIATE serializa escritores antes de leer clave/revisión, y el índice único es defensa adicional.

Recibo y cambios se confirman juntos. No hay fila pending durable: una interrupción antes del commit deja ambos sin confirmar; después del commit el replay devuelve el recibo original aun si se perdió la respuesta. Reautoriza cada intento, incluso el acceso al pedido del recibo. El recibo original puede tener revisión anterior a cambios posteriores y no pretende ser un snapshot vigente. No se elimina el borrador móvil desde este servicio.

## Fallos y compatibilidad verificados

Se inyectaron errores en alta, segundo trabajo, demanda, validación de cantidad/comercial, historial, revisión, journal y precommit. Se verificó ausencia de pedidos/trabajos/demanda/historial/revisión/recibos/outbox parciales. También se probó error de outbox oculto por el helper, COMMIT por cursor, intento de desactivar guardas y modificación tardía después del recibo.

Dos solicitudes con la misma clave producen una sola alta y evento. Dos operaciones distintas con la misma revisión producen un éxito y un conflicto. Replay tras reiniciar conexión devuelve el recibo original. Una escritura SQL Desktop por otra conexión invalida revisión; rollback no la incrementa. Reducción con reservas se rechaza sin modificar cantidades/revisión; pagos históricos y subtotales se conservan al editar. No se prueba envío HTTP ni aplicación Android: permanecen desconectados.

Archivos: app/database/order_transaction.py (nuevo), app/services/order_operation_service.py (nuevo), app/database/database.py (fábrica y event_repo por hilo), tests/test_order_operation_service.py (nuevo), este informe. No hay cambios Flutter, Sticker Studio, Planchas o calibración.

## Resultados

Primer núcleo: 16 pruebas nuevas aprobadas. Regresión focalizada intermedia: 76 aprobadas. Núcleo ampliado: 21 aprobadas (artifacts/s2a1-transaction-final.xml).

La primera ejecución general terminó con 1370 aprobadas, 1 omitida y un fallo de selección de área: Tk no encontró button.tcl en el runtime temporal. Aislada pasó. Se observó durante ejecución simultánea de suites que preparan el mismo caché Tcl; no se modificó ni omitió la prueba. La repetición final, secuencial y con todas las guardas de cursor finales, terminó con **1376 aprobadas, 1 omitida, cero fallos; 5 subtests aprobados, 249 advertencias**, 282,85 s. Incluye las 21 pruebas nuevas. Evidencia: artifacts/s2a1-full-final.xml y artifacts/s2a1-full-final.log. El fallo inicial se conserva en artifacts/s2a1-full.xml/log y no se oculta.

## Dictamen y riesgos restantes

Garantías internas demostradas bajo los participantes y bases aisladas indicados; no equivalen a seguridad de una API remota. Sprint 2B debe añadir adapter versionado, validación/autorización concreta, catálogo/cotización dentro del lock, mapping cliente-servidor y pruebas HTTP reales antes de habilitar envío. La primitiva no permite por sí sola que Mobile cambie estados, precios o pagos: no está expuesta. Servicios con BEGIN propio, efectos externos o conexiones alternativas necesitan adaptación específica antes de usarse como participantes. No habilitar escrituras remotas por el solo hecho de pasar regresiones.

Dictamen: base interna apta para avanzar al desarrollo controlado del adaptador de Sprint 2B, con esas condiciones y migración explícita respaldada; **no autorización de despliegue ni de habilitar sincronización**. No se aplicó esta migración a una base operativa.
