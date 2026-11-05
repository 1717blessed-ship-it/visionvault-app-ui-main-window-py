# Pedidos 2.0 — aceptación Sprint 3.1

Fecha: 23/10/2026. Validación exclusivamente sobre copias SQLite aisladas. Sin Sprint 4 ni operaciones físicas.

## Causas raíz y correcciones

1. La entrega dependía del estado textual y podía actualizar todos los trabajos sin comprobar cantidades terminadas. `delivery_readiness.py` define un contrato común sobre cantidades persistidas de todos los trabajos; las guardas SQLite protegen también escrituras directas e integraciones. Preparar, imprimir o liberar reservas no satisface la entrega.
2. El Centro de Ventas persistía recepción antes de validar el cierre: ahora ambos pasos son una transacción. Las comprobaciones de servicio toman bloqueo de escritura antes de validar; las guardas protegen frente a modificaciones concurrentes de cantidades y respaldo productivo. Entregar no cambia cobros.
3. El porcentaje del flujo textual se interpretaba como avance físico. La interfaz ahora lo identifica expresamente como estado del flujo, no cantidades. El panel distingue estados actuales, acumulados inclusivos, pendientes y reservas liberadas. No se inventaron eventos ni se reescribió historial para igualar estados.
4. Título y acciones competían por una fila; las columnas se comprimían hasta truncarse. Título compacto con ajuste de línea, acciones en filas adaptables, columnas con ancho mínimo y scroll horizontal, detalle completo con ajuste al contenedor y saldos pendientes explícitos.

## Contrato de entrega

- Todos los trabajos deben estar cumplidos; una línea incompleta impide el cierre total.
- Producción: cantidad terminada suficiente y ausencia de asignaciones activas sin terminar.
- Stock/servicio ya cumplido: constancia explícita mediante `confirm_direct_source`, con cantidad exacta, responsable y referencia, persistida como `delivery.source.confirmed`. No puede sustituir demanda ni historial productivo. No hay botón de excepción automática ni se consume stock de materias primas mediante esta constancia.
- El origen directo se valida contra título, material, tamaño y cantidad actuales. No se presupone cumplimiento por ausencia de diseños.
- Guardas impiden invalidar una entrega mediante edición de trabajos, eliminación de trabajos, modificación/eliminación de asignaciones o eliminación de su constancia justificativa.
- UI, servicio de estados, base, servicio productivo y Centro de Ventas quedan protegidos. Los endpoints existentes de entrega y cambio de estado reciben conflicto HTTP 409 ante rechazo SQLite. No se modificó el cliente Doccione Mobile.
- Migración `2026102302`, con respaldo específico `pre_verified_delivery` previo a inicializar el esquema de una base existente sin la vista.

## Bases y escenario ejecutado

Operativa: `visionvault.db`, consultada en modo lectura: **0 pedidos**, `quick_check=ok`. No se abrió como base de la aplicación de prueba.

Evidencia reproducible: `artifacts/acceptance-s31-20261023/verified-run/observations.json`.

| Copia aislada | Observación |
| --- | --- |
| `verified-run/partial.db` | A40/B35/C25; solicitado 100, terminado 10, falta terminar 90; preparado actual 20, impreso sin terminar 10; preparable 60; impreso acumulado 20; liberado registrado 9. Entrega rechazada, cobros sin cambios. |
| `verified-run/complete.db` | 100 terminadas, 0 pendientes; cumplimiento total verificado. Cierre previo simulado conservado. |
| `verified-run/historical.db` | Entregado antiguo con 100 pendientes: anomalía visible, sin reabrir ni fabricar producción retrospectiva. |
| `preview-*.db` | Copias del escenario parcial para abrir la aplicación Tkinter real. |

Reapertura verificada de las tres bases: snapshots persistidos sin cambios e integridad SQLite `ok`. Backups pre-migración registrados en el JSON.

Protección comprobada por SHA-256 antes/después del validador:

- Operativa: `f6abfb14fedfefb99653fa0928e1010cb1d8bd30da7955a7bc3ac4eb0a9340f2`.
- Física `artifacts/acceptance-s3-20261023/physical-pending.db`: `c5457335c8ae472e7c00b38d1b827c8bb50276c35f5796cb80aab79a16d01e0c`.
- Física: 3 unidades preparadas, 0 impresas, 0 terminadas, 0 `print_jobs`. Impresión y corte pendientes del operador. Sin cambios de calibración.

## Evidencia visual real

Carpeta `artifacts/acceptance-s31-20261023/`:

- `panel-1040x680.png`: botones accesibles en filas, columnas desplazables y detalle de solicitado/pendiente.
- `panel-1280x720.png`: panel productivo y saldos (captura anterior al ensanche final de columnas; no representa exactamente la última revisión).
- `panel-1600x900.png`: ventana solicitada a ese tamaño, captura limitada por el monitor; no acredita cobertura completa a 1600×900.
- `panel-maximized.png`: revisión definitiva maximizada, cantidades actuales y acumuladas separadas.
- `timeline-corrected.png`: estado del flujo sin porcentaje productivo ficticio.
- `delivery-blocked.png`: clic real en Entregado; advertencia con solicitado 100, terminadas 10, pendientes 90.

Medidas reales en `layout-*.json`: pantalla 1360×768, aproximadamente 96 píxeles/pulgada, Tk scaling 1.3327. Ventanas normales 1040×680 y 1280×720 verificadas. Al solicitar 1600×900, Windows limitó la geometría a 1600×881 y la captura al área disponible; validación completa pendiente en monitor mayor. Maximizada: estado `zoomed`, 1360×745. No se cambió el escalado de Windows; otros DPI no acreditados.

## Pruebas

- Matriz focalizada final: **196 aprobadas**, 98.44 s; `artifacts/s31-focused-final.xml`.
- Cobertura nueva: producción completa/incompleta, varios trabajos, parcialmente terminada, tanda cancelada, reservas sin terminar, stock explícito, rechazo del override productivo, UI y servicios, API entrega y PATCH, concurrencia, históricos, respaldo y tamaños del panel.
- Primera suite general: 1226 aprobadas, 1 omitida, 5 subtests aprobados, 1 fallo de carga transitoria de `init.tcl` antes de ejecutar la lógica del test de selección de área. Repetición aislada de ese test: aprobada. No se cambió Sticker Studio para ocultarlo.
- Suite general definitiva: **1233 aprobadas, 1 omitida, 5 subtests aprobados, 0 fallos**, 300.62 s; `artifacts/s31-full-final.xml`. Se usó el Tcl instalado, con creación/destrucción de una raíz Tk antes de pytest; no se omitió el caso que falló en el primer arranque. Persisten 4 advertencias de tests preexistentes que retornan valores en lugar de `None`.

## Archivos de esta corrección

Producción: `app/services/delivery_readiness.py`, `app/database/migrations.py`, `app/database/database.py`, `app/domain/order_states.py`, `app/services/production_stage_service.py`, `app/sales/repository.py`, `app/api/mobile_jobs.py` (backend existente), `app/services/order_production_service.py`, `app/ui/order_production_panel.py`, `app/ui/main_window.py`.

Pruebas: `tests/test_delivery_readiness.py`, `tests/test_database_maintenance.py`, `tests/test_order_flow.py`, `tests/test_order_states.py`, `tests/test_production_stage_service.py`, `tests/test_plancha_item_traceability.py`, `tests/test_order_production_panel.py`.

Soporte: `tools/preview_orders_sprint31.py`, `tools/validate_orders_sprint31.py`, este informe y evidencias. El checkout ya contenía cambios de otros trabajos; no se revirtieron ni se atribuyen a Sprint 3.1. No se editaron módulos Sticker Studio ni el cliente Mobile en esta corrección.

## Limitaciones y dictamen

No se encontró un registro independiente y cuantitativo de entrega parcial por trabajo. No se añadió uno paralelo. Terminado significa cumplimiento productivo; Entregado sigue siendo confirmación total del operador y no prueba física automática de recepción. La constancia stock/servicio es un servicio explícito auditable, todavía sin pantalla específica de captura.

Los históricos cerrados inconsistentes se conservan y señalan; no quedan validados retroactivamente. La migración no depura su historial.

Dictamen: **aceptación técnica del Sprint 3.1 con reservas de validación visual/operativa**. Contrato de entrega, persistencia, históricos y pruebas focalizadas/generales aprobados. Clic real en Entregado rechazado; consulta SQLite posterior mantiene estado Nuevo y cantidades 10 terminadas/20 preparadas/10 impresas/9 liberadas. Uso operativo condicionado a confirmar impresión/corte físicos y completar validación en 1600×900 y otros DPI si se emplean. No se considera aprobada una resolución que el monitor no puede mostrar íntegramente. No se inició Sprint 4.
