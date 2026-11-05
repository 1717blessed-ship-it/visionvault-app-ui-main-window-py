# Creador de Planchas: última fila incompleta

Corrección localizada en `app/planchas/model.py`.

Causa: `_optimize_five_bands` y su variante con piezas bloqueadas justificaban todas las filas al ancho útil y centraban las filas de una sola pieza. `justify_rows` también repartía el espacio sobrante.

Cambio: únicamente la última fila ocupada que admite otra pieza del menor ancho presente, con separación normal, comienza en `margin_cm` y avanza consecutivamente. La detección usa centímetros/ancho reservado de la ruta de cinco franjas, no una cantidad fija por fila. Las filas completas conservan su cálculo anterior; no se cambia el orden, la coordenada vertical, los tamaños, el reparto entre páginas ni la capacidad del packing. Las filas con posiciones bloqueadas se conservan. En la justificación especial se mantiene la comprobación de colisión con las otras filas antes de aplicar el movimiento.

El ajuste se ejecuta durante distribución automática, no como migración ni al cargar un proyecto guardado. No se modifican bases, planchas históricas, reservas, Sticker Studio A/B/C/D, DPI ni calibraciones. Vista previa y exportación siguen consumiendo las mismas coordenadas persistidas, sin parche exclusivo del canvas.

Pruebas ejecutadas: **90 aprobadas**, reporte `artifacts/last-row-focused.xml`. Incluyen 26 casos nuevos: última fila de 1/2/3 piezas, dos separaciones, filas completas intactas, lote de dos hojas 20+6, anchos mixtos, posiciones bloqueadas, persistencia/manual libre y composición real de exportación. También se ejecutaron las pruebas existentes de paginación, cinco franjas, geometría, cantidad, contorno y redimensionado libre. El renderizador emite 42 advertencias existentes de deprecación Pillow; ningún fallo. No se ejecutó la suite general en esta corrección puntual.

No se realizó impresión física. El pedido recibido terminó cortado en «Una fila incompleta con»; no se presupusieron requisitos posteriores no recibidos.
