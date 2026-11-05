# Aceptación operativa de Pedidos 2.0 — Sprint 3

Fecha: 23/10/2026. Alcance: validación, sin nuevas funciones ni correcciones del producto.

## Dictamen

**Aceptación automatizada y simulación: aprobadas. Aceptación operativa integral: condicionada, no otorgada todavía.**

La demanda, reservas, tandas, producción parcial, cancelación y recuperación funcionaron en el escenario representativo. Quedan pendientes impresión/corte físicos y dos observaciones de interfaz. Se detectó además un riesgo de cierre que requiere decisión o corrección antes de considerar seguro el cierre del pedido: el servicio permite marcar Entregado sin cantidades terminadas. No se inició Sprint 4 ni se modificaron reglas para ocultar ese resultado.

## Entorno y bases utilizadas

La aplicación iniciada con `main.py`, sin `--database`, resuelve la ruta absoluta:

`C:/Users/Win 10/Documents/Codex/2026-07-13/visionvault-app-ui-main-window-py/visionvault.db`

El lanzador `Iniciar Doccione Studio.bat` ejecuta ese `main.py`. Las líneas de proceso consultadas distinguen `main.py`, los antiguos visores `tools/preview_orders_sprint2.py` y la aceptación con `tools/validate_orders_sprint3.py ... --gui`. El visor antiguo utiliza su propia base `artifacts/orders-sprint2-preview/preview.db` y no se usó para este escenario.

La consulta SQLite `mode=ro` sobre la base habitual encontró **0 pedidos totales y 0 demandas**, antes y después de la validación. La vista real observada previamente estaba en «Todos», búsqueda vacía, y mostraba 0 pedidos; no había pedidos ocultos por estado o archivado, pues la consulta no aplicó filtros. No se cargaron pedidos reales ni se escribieron simulaciones en esa base.

Todas las bases nuevas están bajo:

`C:/Users/Win 10/Documents/Codex/2026-07-13/visionvault-app-ui-main-window-py/artifacts/acceptance-s3-20261023/`

- `simulation.db`: ejecución final, con cierre y producción **explícitamente simulados**.
- `01-created.db`: pedido guardado, tres diseños, sin producción.
- `02-prepared.db`: primera tanda de 20 preparada, sin impresión confirmada.
- `03-partial.db`: 20 impresas acumuladas y 10 terminadas, simuladas.
- `04-remaining.db`: dos tandas comprometidas, cancelaciones y saldos. Se abrió en la aplicación Tkinter completa para revisar el panel.
- `05-closed.db`: 100 terminadas y cierre simulado.
- `physical-pending.db`: rama separada para el operador, con 3 unidades A/B/C preparadas, **0 impresas, 0 terminadas y 0 trabajos de impresión**. Plancha A4, aprobación Borrador.
- `premature-close-probe.db`: copia específica de `02-prepared.db` usada para demostrar el cierre anticipado.

Las copias se realizaron con la API `sqlite3.backup`, no copiando un archivo WAL incompleto. El programa de validación rechaza sobrescribir destinos existentes.

## Escenario observado

Un pedido, un trabajo «Stickers de prueba 5 cm», vinilo blanco, 100 unidades, distribución completa. Diseño FICTICIO A:40, B:35, C:25. Los tres PNG están identificados visualmente y por nombre como ficticios. Cliente y observaciones advierten SIMULACIÓN, NO ES VENTA y BASE AISLADA.

Se utilizó `ImageDatabase.create_order_with_details`, `ProductionBatchService.preview/save/cancel`, `OrderProductionService.snapshot/preview` y los métodos existentes de confirmación de asignaciones. Se registró una seña ficticia de $10.000 sobre $40.000 para comprobar separación financiera; no fue una transacción real.

| Punto de control | Preparada sin imprimir | Impresa sin terminar | Terminada | Liberaciones registradas | Preparable | Falta terminar |
|---|---:|---:|---:|---:|---:|---:|
| Pedido creado | 0 | 0 | 0 | 0 | 100 | 100 |
| Primera tanda A8/B7/C5 | 20 | 0 | 0 | 0 | 80 | 100 |
| Avance parcial simulado | 0 | 10 | 10 | 0 | 80 | 90 |
| Cancelación segura + segunda tanda | 20 | 10 | 10 | 9 | 60 | 90 |
| Cierre final simulado | 0 | 0 | 100 | 9 | 0 | 0 |

En el cuarto punto: preparado acumulado activo=40, impreso acumulado=20, falta imprimir=80. Los 9 registros liberados pertenecen a una tanda cancelada sin imprimir y **no se suman** a la producción activa ni representan entrega.

### Comprobaciones

- Primera tanda #1: 20 unidades repartidas A8/B7/C5, representadas en dos planchas. Cada plancha conserva su asociación al pedido y las líneas de demanda.
- Reintentar guardar la misma vista previa produjo el bloqueo «Una unidad ya está reservada o dejó de estar solicitada. Actualizá la vista previa». No se creó otra tanda.
- Cancelar la tanda #1 después de la impresión simulada conservó las 20 unidades; liberó 0. El estado de tanda cancelada no significa que se haya descartado producción impresa.
- Tanda #2: A3/B3/C3, sin imprimir; cancelarla liberó 9. Repetir la cancelación liberó 0. Permanecen plancha, asignaciones y vínculo histórico.
- Tanda #3: otras 20, usando únicamente copias disponibles. Quedaron 40 comprometidas y 60 preparables, sin alterar las primeras 20 impresas.
- Cierre/reapertura: el snapshot recuperado coincidió exactamente con el guardado antes de cerrar la conexión.
- Se preparó el saldo de 60 y se simuló completar las 100 antes del cierre final. La cantidad de diseños continuó siendo 3.
- No hubo `requested_unit_key` activos duplicados, ni saldos negativos en los checkpoints.
- `PRAGMA integrity_check`: `ok`; `PRAGMA foreign_key_check`: sin filas.
- Los avances y cancelaciones no alteraron cobros ni saldos financieros. La entrega cuantitativa por trabajo continúa sin registro independiente: el panel devuelve `delivered=None`, no 100 inferidas.

Evidencia estructurada: `observations.json`, con snapshots completos, IDs y resultados. Reproducción: `python tools/validate_orders_sprint3.py <carpeta-nueva>`; apertura de una etapa: `python tools/validate_orders_sprint3.py <archivo.db> --gui`.

## Capturas reales y revisión visual

Se abrió **VisionVaultApp real**, con la base `04-remaining.db`, no un mock del panel. Se observaron los diseños, cantidades, tandas y etapas persistidas. Capturas en la carpeta de aceptación:

- `three-designs-wide.png`: A40/B35/C25 con tamaño 5 cm.
- `panel-remaining-wide.png`: solicitado=100, distribuido=100, preparable=60, terminado=10, falta terminar=90; detalle de etapas y liberaciones.
- `related-batches.png`: primera tanda, cancelación y segunda tanda, con IDs de plancha.
- `panel-remaining.png`: evidencia del recorte en ventana angosta.
- `closed-blocked.png`: 100 terminadas, 0 pendientes, botón de preparación deshabilitado y explicación del bloqueo del pedido cerrado (todo simulado).
- `three-designs.png`: vista angosta de los mismos tres diseños.

La sesión de automatización perdió variables una vez («sky is not defined»); se reinicializó y recuperó la ventana por inventario. Eso fue un problema de la sesión de herramientas, no un fallo de Doccione. No se declararon como capturas válidas observaciones de ventanas ajenas.

## Defectos y observaciones

1. **Riesgo de cierre anticipado, reproducido por servicio existente:** en `premature-close-probe.db`, con 100 solicitadas, 20 preparadas, 0 impresas y 0 terminadas, `mark_order_delivered(1)` aceptó el estado Entregado. Quedaron 100 pendientes de terminar; el método no fabrica producción, pero tampoco valida completitud. Es un bloqueo para aprobar un cierre operativo sin control del operador. No se cambió el producto en esta validación.
2. **Recorte en ventana angosta:** títulos, columnas y líneas explicativas del panel pierden legibilidad a unos 1040 px de ancho total. Maximizar mejoró la lectura de los saldos; el título largo y el nombre de producto todavía pueden recortarse. No compromete el cálculo, pero necesita revisión de usabilidad.
3. **Dos indicadores de avance distintos:** la línea de tiempo textual siguió «Recibido · 5%» mientras el panel mostraba 20 impresas acumuladas y 10 terminadas. Son fuentes distintas (estado del flujo y asignaciones físicas). Las cifras productivas son correctas; el operador puede interpretar equivocadamente el porcentaje general como progreso físico. Debe aclararse o decidirse la sincronización antes de una aceptación plena.
4. **Terminología técnica en tandas:** se ven `prepared` y `cancelled` en lugar de etiquetas para el operador. No es un error de persistencia; queda como observación de claridad.

## Pruebas finales

- Focalizadas nativas, con `tests/conftest.py` y Tkinter real: **56 aprobadas**, sin omitir el test de interfaz. XML: `artifacts/acceptance-s3-focused.xml`.
- Suite general nativa: **1216 aprobadas, 1 omitida, 5 subtests aprobados, 0 fallos**, en 257,58 s. XML: `artifacts/acceptance-s3-general.xml`.
- La omitida sigue siendo `test_shield_images_processing`; no se presenta como aprobada. Cuatro advertencias preexistentes corresponden a tests que devuelven booleanos en `test_white_border_white_background.py`.
- Un primer intento focalizado con `--noconftest` dentro del sandbox no validó correctamente Tkinter. Se repitió la ejecución completa focalizada con el runtime nativo; el resultado citado es esa ejecución nativa.
- `git diff --check` de los archivos rastreados relevantes: correcto. Se preservaron los cambios ajenos presentes. En esta validación solo se agregó el programa de aceptación, este informe y artefactos de ensayo; no se editaron Sticker Studio, Mobile, calibraciones, motor A/B/C/D ni funciones del producto.

## Validación física pendiente

Abrir `physical-pending.db` y consultar la tanda #1 «PENDIENTE OPERADOR — prueba física 3 unidades A/B/C». La plancha A4 está en Borrador. El operador debe realizar las validaciones de diseño/aprobación/exportación existentes antes de imprimir. No se generó un trabajo de impresión ni se enviaron documentos a la impresora.

Confirmar físicamente material, medidas nominales de 5 cm, orientación y márgenes, registro de corte, calidad de impresión, adherencia y resultado del corte. Después registrar impresión y terminación reales por sus flujos existentes. No se alteraron calibraciones. Solo tras esa confirmación y la resolución del riesgo de cierre corresponde decidir la aceptación operativa definitiva.
