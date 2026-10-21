# Sticker Studio 2.0 — Sprint 1.4

## Resultado

Se completó la operación cotidiana del editor sin modificar las rutas A/B/C/D,
el editor clásico ni las calibraciones de impresión. El P1 visual sigue abierto
hasta la aprobación humana de su máscara real.

## Movilidad

- Zoom bajo el cursor con rueda.
- Pan con botón central y espacio + arrastre, incluso con un pincel activo.
- Herramientas de cámara y máscara mutuamente excluyentes.
- Ajustar (`Ctrl+0`), zoom 100 % (`Ctrl+1`) y centrar.
- Vista independiente por sticker: modo, zoom, pan, comparación y corte.
- Paneles laterales redimensionables e inspector con scroll propio.
- Bandeja horizontal con rueda, miniaturas y navegación directa.

## Cola y estados

Los estados visibles son Pendiente, Procesando, Requiere revisión, Aprobado,
Exportado, Error, Cancelado y Rechazado. Terminar el pipeline nunca aprueba un
sticker. Se añadieron acciones reales para procesar pendientes o seleccionados,
cancelar, reintentar errores, reprocesar individualmente, limpiar finalizados y
exportar seleccionados aprobados. El guardado por trabajo evita mezclar perfiles.
Los botones de inicio se bloquean durante un trabajo para evitar dobles corridas.

## Bandeja y eliminación

- Selección individual, `Ctrl` y rangos con `Shift`.
- Menú contextual para procesar o quitar.
- Indicadores de selección, estado y error.
- Una única confirmación enumera los archivos afectados.
- Un trabajo activo no puede quitarse hasta cancelarlo o finalizarlo.
- Quitar una fila nunca borra el original, pedidos ni diseños guardados.
- Sólo resultados temporales no aprobados se notifican como descartados a la
  base; aprobados permanecen intactos.

## Guardado y recuperación

`work/stickers/studio_v2_session.json` se escribe atómicamente. Conserva rutas
del original, metadata del resultado, máscara manual, protección, contracción,
expansión, contorno, calidad, aprobación, errores y estado del Canvas. Una
corrida que figuraba Procesando se recupera como Cancelada. Si faltan artefactos
para un supuesto resultado, vuelve a Pendiente en lugar de mostrar un falso
resultado recuperado. `Ctrl+S` guarda explícitamente y el cierre advierte sobre
cambios aún no persistidos.

## Auditoría de controles

Todos los controles habilitados ejecutan acciones reales:

- Importar, pegar y carpeta: agregan originales sin procesarlos de forma sorpresiva.
- Deshacer/rehacer: historial manual por sticker.
- Guardar proyecto: persistencia atómica.
- Exportar final/seleccionados: copia exacta del master; requiere aprobación.
- Procesar pendientes/seleccionados: lote serial fuera del hilo UI.
- Cancelar/reintentar/limpiar/quitar: operaciones seguras y coherentes.
- Comparar, modo de vista, corte, centro, 100 % y ajustar: Canvas real.
- Herramientas de máscara, objetos y contorno: comandos reales existentes.
- Aplicar, restablecer, aprobar referencia y aprobar resultado: flujos separados.
- Lazo inteligente y Guardar proyecto decorativo anterior: el lazo sigue visible
  pero deshabilitado; Guardar proyecto ahora es funcional.

Los botones principales y del inspector tienen ayuda contextual. No se añadió
texto, formas, capas ni plantillas.

## Pruebas de uso

- A/H: pipeline real y exportación byte a byte del master cubiertos por las
  regresiones existentes.
- B: 20 trabajos con configuración independiente.
- C/D: eliminación múltiple cancelada y confirmada en una ventana Tk real;
  originales verificados intactos.
- E: cancelación cooperativa, estados Cancelado y reintento exclusivo de Error.
- F: historial y parámetros por sticker, navegación y render determinista.
- G: guardado, cierre lógico, reapertura y recuperación en ventana Tk real.
- I: estado de Canvas y separación entre pan y pinceles.

Pendiente de validación manual: sensación del zoom con distintos dispositivos,
uso sostenido con veinte imágenes grandes y minimizar/maximizar en los equipos
de producción. Estas comprobaciones no impiden la validación automatizada, pero
sí la declaración final de producción.

## Resultado automatizado final

`python -m pytest -q`: **1160 aprobadas, 1 omitida, 5 subpruebas aprobadas y 4
advertencias históricas**. Las advertencias corresponden a cuatro pruebas
anteriores que retornan un booleano en vez de utilizar `assert`; no son fallos
del Sprint 1.4.
