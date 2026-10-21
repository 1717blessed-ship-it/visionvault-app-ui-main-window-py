# Doccione Sticker Studio 2.0 - Sprint 1.5

## Dictamen

**NO LISTO PARA PRODUCCION.** La operación automatizable queda aprobada, pero
el P1 visual del disco no tiene referencia humana aprobada y la impresión/corte
A4 aún no fue verificada físicamente.

## APROBADO - verificado mediante pruebas

### Interfaz

- Ventanas 1040x680, 1280x720 y 1600x900 con Canvas útil.
- Zoom, ajustar, 100 %, centrar y estado de vista por sticker.
- Selección individual, Ctrl, Shift, navegación y bandeja horizontal.
- Todos los botones habilitados tienen un comando real.
- Eliminación múltiple cancelada y confirmada sin borrar originales.
- Inspector desplazable, paneles redimensionables y recuperación de sesión.
- Separación entre desplazamiento de cámara y herramientas de máscara.

Matriz focalizada: **39 pruebas aprobadas**.

### Lote de producción

El conjunto contiene 20 derivados de carga de contenido real, entre 600x600 y
2000x2000 (360.000 a 4.000.000 píxeles). No se utilizaron solamente miniaturas.
Cada entrada conserva la ruta de su original real en el manifiesto.

- Procesados: 20/20.
- Errores: 0.
- Tiempo total: 55,0987 s.
- Pico de working set de Windows: 430,04 MB.
- Más lento: 2000x2000 en 5,8294 s.
- Exportaciones: 20/20 idénticas byte a byte a su master.
- Cancelación cooperativa: aprobada a partir del 35 %.
- Reintento posterior: completado en 4,5419 s como Requiere revisión.
- Ningún resultado fue aprobado automáticamente.

El detalle por archivo está en
`artifacts/sticker-studio-sprint15/batch20/benchmark.json`.

### Regresión

Suite completa final: **1162 aprobadas, 1 omitida, 5 subpruebas aprobadas y 4
advertencias históricas**. Las advertencias son las mismas cuatro pruebas
anteriores que retornan booleanos en lugar de utilizar `assert`.

## REQUIERE VALIDACION HUMANA

### P1 visual

Se prepararon dos carpetas, 421x421 y 600x600, con original, máscara automática,
una máscara candidata no aprobada, contorno, PNG candidato y composiciones sobre
blanco, negro y magenta. `manifest.json` mantiene `human_approved: false`.

La máscara denominada corregida es una **candidata producida mediante ajuste de
contracción**, no una corrección manual aprobada. Deben revisarse puntas, uniones,
halo gris, grosor blanco y reflejos legítimos antes de pulsar la aprobación en
el Canvas.

### Windows

- Sensación de zoom con mouse y touchpad reales.
- Espacio + arrastre y botón central durante una sesión prolongada.
- Minimizar, maximizar y restaurar en los equipos de producción.
- Fluidez subjetiva al navegar veinte imágenes grandes.

### Impresión y corte

La hoja A4 conserva las medidas nominales y no cambia calibraciones. Debe
imprimirse al 100 %, sin ajustar. Una persona debe comprobar:

- regla de 50 mm;
- stickers nominales de 57 mm;
- resolución efectiva y nitidez;
- halo y uniformidad del borde;
- recorrido físico de corte;
- correspondencia entre Canvas, PNG e impresión.

## BLOQUEADO - defecto reproducible

No se encontró un defecto reproducible nuevo durante esta etapa.

El pase a producción permanece bloqueado administrativamente por validaciones
humanas pendientes, no por una regresión automatizada.

## Evidencias

- `artifacts/sticker-studio-sprint15/batch20/`: entradas, masters exportados y
  métricas de carga.
- `artifacts/sticker-studio-sprint15/p1-human-review/`: paquete visual P1.
- `output/pdf/sticker_studio_sprint15_a4_physical_validation.pdf`: hoja física.
- `tmp/pdfs/sprint15/page-1.png`: render de control del PDF.

## Criterio de cierre pendiente

1. Aprobación humana de ambas máscaras P1.
2. Comparación automática contra esas referencias aprobadas.
3. Impresión A4 al 100 % y medición física.
4. Prueba real de corte y firma de la guía.
5. Validación ergonómica breve en Windows de producción.
