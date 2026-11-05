# Pedidos 2.0 — Sprint 3: integración operativa

## Auditoría y contratos

No se crearon tablas paralelas ni migraciones en este sprint. Se reutilizan `order_jobs`, `order_design_demand_lines`, `order_design_job_links`, `plancha_item_assignments`, `production_batches`, `production_batch_planchas` y `order_events`.

`order_design_demand_lines` es la demanda productiva con identidad de línea. `order_design_job_links` permanece como vínculo histórico y solo se consulta como distribución histórica si no hay demanda v2. No se suman ambas tablas. Las reservas exclusivas se identifican por `requested_unit_key`; el índice parcial existente impide dos asignaciones activas de la misma unidad. `production_batch_planchas` vincula una tanda con sus planchas; las asignaciones vinculan cada plancha con pedido, trabajo y línea de diseño. Una plancha puede representar varios pedidos.

Los estados de asignación son etapas excluyentes:

| Indicador | Fuente / cálculo |
|---|---|
| Solicitado | `order_jobs.quantity` |
| Distribuido | Suma de demanda por trabajo; fallback histórico señalado |
| Sin distribuir | Solicitado menos distribuido |
| Preparada ahora | Asignaciones `prepared` |
| Impresa sin terminar | Asignaciones `printed` |
| Terminada | Asignaciones `finished` |
| Preparada acumulada activa | `prepared + printed + finished` |
| Impresa acumulada | `printed + finished` |
| Reserva liberada registrada | Asignaciones `released`, excluidas de disponibilidad comprometida |
| Asignada sin preparar | Distribuido menos asignaciones activas |
| Preparable | Disponibilidad del servicio de tandas, limitada al saldo solicitado y bloqueos |
| Falta imprimir | Solicitado menos impresa acumulada |
| Falta terminar | Solicitado menos terminada |
| Entregada | No hay registro independiente de cantidades por trabajo; se muestra sin dato |

`released` significa reserva liberada, no entrega ni producción terminada. El conteo de liberaciones corresponde a registros conservados: una unidad liberada y reservada nuevamente aparece en el historial de liberaciones y también en su nueva etapa activa, pero no se suman esos indicadores. No es un acumulado de producción física. El estado de entrega existente se muestra como estado de pedido, sin inferir unidades desde él.

## Cambios

- Nuevo `OrderProductionService`: consulta consistente por pedido, datos persistidos, disponibilidad y bloqueos, tandas relacionadas, preparación limitada a trabajos del pedido guardado.
- Nuevo `OrderProductionPanel`: integrado en cada espacio de pedido. Muestra trabajo/variante/material, unidad, distribución, saldos y etapas; permite seleccionar trabajos preparables y consultar las planchas de sus tandas. El detalle separa cifras actuales de acumulados.
- Se reutiliza el diálogo de tandas existente, filtrado al pedido y con los trabajos seleccionados. Cantidad parcial, grupos compatibles, vista previa y guardado siguen perteneciendo a `ProductionBatchService`. No se generan archivos de impresión con esta acción.
- El guardado de tandas revalida demanda, identidad solicitada, material, formato, unidad y copias disponibles bajo `BEGIN IMMEDIATE`, antes de crear cualquier registro. Los conflictos y vistas previas desactualizadas hacen rollback.
- La cancelación conserva planchas retiradas, asignaciones liberadas y vínculo con la tanda. Solo libera `prepared`, mantiene producción impresa/terminada y es idempotente. Las planchas totalmente retiradas se identifican como `Cancelada` y no se pueden enviar a nuevos trabajos de impresión.
- Eventos `production.batch.prepared` y `production.batch.cancelled` se guardan dentro de la transacción del pedido/tanda. El panel se actualiza al recibir `notify_production_change` y comprueba cambios de conexión propia u otras instancias mediante `total_changes` y `PRAGMA data_version` cuando está visible. No reescribe el borrador del operador para actualizar avances.
- Se bloquean reducciones por debajo de las reservas activas, eliminación de trabajos con historial de asignaciones, eliminación física de planchas de tandas, cantidades productivas no positivas y elementos repetidos.
- Se corrigió la regresión del Sprint 2 al guardar una ficha histórica con lista vacía de trabajos (`IndexError` al acceder al trabajo de compatibilidad). También se movió la actualización del cliente dentro de la transacción de guardado: un diseño protegido rechazado ya no deja una transacción abierta que bloquee el posterior guardado de tandas.

## Alcance y archivos

Archivos de implementación del Sprint 3:

- `app/services/order_production_service.py` (nuevo).
- `app/ui/order_production_panel.py` (nuevo).
- `app/services/production_batch_service.py` (servicio existente, sin seguimiento previo en Git).
- `app/database/database.py` (se preservan cambios de Sprints 1/2).
- `app/ui/main_window.py` (se preservan cambios de Sprints 1/2).
- `tests/test_order_production_service.py` y `tests/test_order_production_panel.py` (nuevos).
- Este informe y XML de resultados.

No se modifican Sticker Studio 2.0, motor A/B/C/D, calibraciones, aplicación móvil ni el código del Creador de Planchas. Las adaptaciones se limitan a servicios de demanda/reservas y navegación de producción.

## Verificación

La suite general de cierre de Sprint 2 se ejecutó antes de modificar producción: **1204 aprobadas, 1 fallida, 1 omitida, 5 subtests aprobados**. La antigua expectativa de migraciones pasó dentro de esa suite. El fallo nuevo fue el `IndexError` histórico mencionado arriba; se reprodujo aisladamente y la corrección aprobó **27 pruebas** de pedidos, migraciones y pagos antes de continuar producción.

Pruebas focalizadas de producción y pedidos: **55 aprobadas**. Incluyen demanda completa/parcial, unidades/hojas, varias tandas, recuperación después de cerrar, exclusividad, concurrencia, vista previa obsoleta, cancelación con historial, reducciones y eliminación peligrosas, estados desconocidos y separación financiera. El escenario 100/80/60/40/30 verifica: 20 sin distribuir, 20 asignadas sin preparar, 20 preparadas sin imprimir, 10 impresas sin terminar, 30 terminadas, 60 pendientes de imprimir y 70 pendientes de terminar.

Verificación nativa de Tkinter y servicios: **18 aprobadas**, incluida la construcción real del panel y actualización tras otra conexión. Esto es evidencia automatizada de widgets y datos; no equivale a aceptación visual por el operador.

La aplicación real abrió con su base habitual; se navegó a Pedidos y la vista mostraba **0 pedidos**, sin crear registros operativos para la captura. Evidencia: `artifacts/sprint3-real-orders.png`. Se verificó también el historial de cobros de una base de ensayo en la aplicación completa. La captura/control de ventanas fue intermitente y algunas observaciones correspondían a ventanas ajenas; esas imágenes no se guardaron como evidencia de Pedidos. La aceptación visual del panel con un pedido operativo real permanece pendiente.

Suite general final nativa: **1215 aprobadas, 1 omitida, 5 subtests aprobados, sin fallos** en 309,65 segundos. La prueba de versiones de migración y el guardado histórico anteriormente fallidos pasaron dentro de la suite completa. Hay cuatro advertencias preexistentes de `test_white_border_white_background.py` porque sus pruebas devuelven booleanos. La omitida no se contabiliza como aprobada. XML: `artifacts/sprint3-final-results.xml`. La prueba Tkinter nueva se agregó después de iniciada la recolección general y se ejecutó por separado dentro de las 18 pruebas nativas aprobadas.

Compilación de Python y `git diff --check` sobre los archivos rastreados modificados: correctos. Los avisos de Git sobre LF/CRLF describen su conversión de finales de línea; no son errores de diff.

## Pendientes y recomendación

La confirmación física de impresión y terminación permanece en los flujos productivos existentes; el panel no inventa avances desde el estado textual de un trabajo. Los trabajos sin demanda productiva o con historial ambiguo se presentan como bloqueados con explicación. No se crean cantidades de entrega por trabajo porque el modelo actual no las registra.

Siguiente paso recomendado: aceptación operativa con un pedido real, producir una tanda pequeña mediante el circuito físico de impresión/terminación y acordar si se necesitan entregas parciales por trabajo. Una entrega cuantitativa requeriría un contrato propio, no inferir cantidades del estado comercial de pedido.
