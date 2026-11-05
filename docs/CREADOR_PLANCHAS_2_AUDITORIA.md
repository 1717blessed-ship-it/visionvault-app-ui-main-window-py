# Creador de Planchas 2.0 — auditoría funcional y productiva

Fecha: 23 de octubre de 2026. Dictamen: **base funcional amplia, pero no aprobar todavía el circuito diario completo de producción**. Hay bloqueos de impresión, recuperación y detección de archivos faltantes que deben resolverse antes de agregar funciones.

## Alcance y método

Se inspeccionaron modelo/editor, packing mixto, conversión libre, servicios de demanda/tandas, persistencia e impresión Windows. Se ejecutaron escenarios en memoria y pruebas existentes con temporales aislados. No se abrió ni migró la base operativa, no se imprimió, no se movieron reservas reales ni se cambió código productivo, calibraciones o módulos ajenos. Sólo se agregaron este informe y el script diagnóstico `tools/audit_creator_distribution.py`, que genera evidencias ficticias en `artifacts/creator-audit-20261023/`.

No se hizo una nueva auditoría interactiva de todas las pantallas: los riesgos de interfaz descritos aquí proceden de lectura de código; no equivalen a fallos visuales reproducidos. Impresora conectada, DEVMODE efectivo y comportamiento físico Brother pendientes de operador. No se consultó documentación externa ni se certifican especificaciones de hardware.

## Funcionalidades existentes

| Función | Estado y límites observados |
| --- | --- |
| Regular automática | Cinco franjas, orden por superficie y geometría reservada; rotación cuando está permitida; estándar normaliza tamaño productivo según nominal. No confundir nominal comercial con ancho físico de preparación. |
| Última fila incompleta | Corrección vigente: última fila parcial se agrupa a izquierda con gap normal; filas completas conservadas. Hay cobertura focalizada que vuelve a ejecutarse en esta auditoría. No es un rediseño del packing mixto geométrico. |
| Mixta automática | `StickerMixedPacker` admite nominales diferentes, geometría productiva, rotación, multipágina y compactación de hitboxes sin solaparlas. Las hitboxes incorporan aire interno; no exige además el mismo gap externo que el modo regular. |
| Libre | Edición de posición, rotación, bloqueo, cantidad y dimensiones; controles de redimensionado productivo y cambio nominal. La conversión explícita Mixta→Libre congela geometría y conserva trazabilidad. No se verificó una conversión reversible universal: regenerar Mixta es una operación específica, no deshacer garantizado cualquier edición libre. |
| Rellenar espacios | Busca candidatos reutilizables, excluye etiquetas privadas/no reutilizables, prueba huecos y rotación. Muestreo hasta 320 candidatos, hasta 80 propuestas y hasta 120 incorporaciones en completar; no garantiza máximo matemático. Objetivos de ocupación son heurísticos. |
| Varios diseños/copias | Expande cantidades a piezas con identidad de copia y grupo; diseños del mismo archivo pueden mantener líneas distintas. Pedidos aporta nominal/cantidad y origen. |
| Varias hojas | Paginación y navegación, guardado de conjunto, exportación y cola de varias páginas. **Caso imposible incompleto**, ver F2. |
| Vista previa | Canvas usa geometría en cm convertida a píxeles; render técnico y vista de cliente separados. El render técnico añade guías/marca de agua, no es el archivo imprimible. |
| Exportación | PNG A4 transparente a 300 DPI; JPEG de presentación; SVG portable con PNG embebido. **SVG no equivale a trayectorias vectoriales de corte**. |
| Persistencia | JSON editable y registros SQLite, metadatos de conjunto, PNG y rutas de fuentes. No es un paquete autocontenido de originales; depende de archivos disponibles. **Recuperación altera margen/gap**, ver F1. |
| Impresión | Perfiles por impresora, DEVMODE, cola/historial, reimpresión y envío en worker. Enviado a Windows queda «En cola»; no acredita por sí solo impresión física. **Validación de escala contradictoria**, ver F3. |
| Otros formatos | A4, A5 como media A4 y franja horizontal de 1/5 A4. El soporte/exportación sigue siendo A4 físico de 21×29,7 cm. Existe envío a Producción continua, circuito separado y no certificación de rollo de la L3210. Fotos/pósters no son el packing mixto de stickers. |

Fuentes principales: `app/planchas/model.py`, `editor.py`, `sticker_mixed.py`, `sticker_mixed_conversion.py`, `free_resize.py`, `free_nominal.py`.

## Integración con Pedidos y Producción

Hay dos accesos relevantes:

1. `open_plancha_for_order`: recibe diseños guardados, pedido/trabajo y línea de diseño, cantidad, nominal y copias todavía disponibles. No debe volver a pedir cantidades/tamaños ya definidos. Advierte sobre diseños legados sin trazabilidad y excluye copias activamente reservadas. Abre por defecto A4; no pasa explícitamente en este método la agrupación por material/formato/unidad que sí hace Tandas.
2. `ProductionBatchService`: agrupa por material normalizado, formato, modo y unidad; admite seleccionar cantidades parciales y mezclar líneas compatibles. Recupera cantidad disponible descontando asignaciones no liberadas, usa claves de copia, revalida al guardar con `BEGIN IMMEDIATE`, impide reservas duplicadas. `sheet` tiene correspondencia explícita una unidad comercial→una hoja, no un sticker por cada dibujo interno.

El operador debe elegir **cuánto preparar ahora**, confirmar la tanda y resolver datos ausentes; esto no es recarga redundante del pedido. Material/unidad/dimensiones faltantes o ambiguos bloquean la ruta de tandas y requieren corrección explícita. Los diseños legados sin trabajo no suman cantidades productivas.

Integración incompleta/riesgos de paridad:

- La ruta directa recorre todos los diseños del pedido, mientras Tandas agrupa compatibilidad. No está acreditado que todas las entradas apliquen idénticas restricciones para pedidos de varios trabajos/materiales.
- La vista previa de tandas usa `PlanchaProject.calculate_pagination` clásico/especial; regenerar Mixta usa `StickerMixedPacker`. No son la misma ruta. Comparar por la misma entrada antes de prometer idéntico aprovechamiento y tamaño entre accesos.
- Guardado/exportación desde editor ofrece rutas distintas de la reserva transaccional de tandas. Revisar paridad de aprobación/origen sin tocar reglas de Pedidos como parte de esta auditoría.
- El servicio de candidatos consulta globalmente líneas y hace varias consultas por línea; `OrderProductionService.snapshot` obtiene candidatos globales antes de filtrar el pedido. Riesgo de coste al crecer la base, **sin benchmark de base grande en esta auditoría**.

## Medición de distribución

Script: `python tools/audit_creator_distribution.py`. Evidencia completa: `artifacts/creator-audit-20261023/distribution.json`.

30 escenarios: 20 regulares de geometría fija (10/25/50/100/200; igual/mixto; separación 0,05/0,15 cm), 5 estándar nominal y 5 Mixta moderna. Repeticiones: 5 para geometría fija y 3 para modernos. Sólo tiempo de packing en memoria; no incluye carga/contorneado de imágenes, PNG, SQLite, UI ni driver. Milisegundos son mediciones locales, no SLA; varían con la carga de la suite general simultánea.

### Estándar nominal 5 cm, tres diseños A/B/C con cantidades 40/35/25 a n=100

Los diseños ficticios conservan proporción cuadrada; el estándar usa su propia normalización productiva. La capacidad aquí es 15 por hoja, no los 20 de cuadrados arbitrarios de 4,8 cm. No se comparan ambos como si fueran el mismo producto.

| Cantidad | Hojas | Distribución | Ocupación útil media | Última hoja | Mediana packing |
| --- | --- | --- | --- | --- | --- |
| 10 | 1 | 10 | 53,01 % | 53,01 % | 0,30 ms |
| 25 | 2 | 15+10 | 66,27 % | 53,01 % | 0,90 ms |
| 50 | 4 | 15+15+15+5 | 66,27 % | 26,51 % | 3,26 ms |
| 100 | 7 | 6×15+10 | 75,73 % | 53,01 % | 16,01 ms |
| 200 | 14 | 13×15+5 | 75,73 % | 26,51 % | 51,61 ms |

### Mixta moderna: nominales 5/8/10 cm, cantidades 40/35/25 a n=100

| Cantidad | Hojas | Ocupación útil media | Última hoja | Mediana packing |
| --- | --- | --- | --- | --- |
| 10 | 2 | 48,27 % | 18,40 % | 1,03 ms |
| 25 | 4 | 61,75 % | 4,07 % | 4,52 ms |
| 50 | 6 | 82,28 % | 68,91 % | 7,74 ms |
| 100 | 13 | 76,41 % | 4,07 % | 22,87 ms |
| 200 | 24 | 82,74 % | 73,18 % | 53,80 ms |

En los 30 escenarios no se detectó pérdida/duplicación de unidades válidas, salida de área ni solapamiento bajo el contrato de cada modo. La comprobación inicial exigía gap externo a las hitboxes mixtas; se corrigió el diagnóstico al comprobar que Mixta usa aire interno: **no es un defecto de colisión demostrado**.

Los 20 casos de geometría fija generaron 1–10 hojas para iguales y 1–8 para tamaños mezclados. Tiempo mediano inferior a 5 ms en esa ejecución. La recuperación de los 10 casos con gap 0,15 cambió metadatos, aunque las posiciones permanecieran: F1. No se afirma que el packing sea óptimo; una última hoja poco ocupada puede ser un saldo legítimo. Optimizar este núcleo no es hoy la primera prioridad de rendimiento.

Ocupación aquí = suma de rectángulos físicos de diseños/área útil de todas las hojas; no superficie exacta de siluetas ni rendimiento monetario. El JSON distingue área reservada en escenarios fijos. El `occupancy()` actual tampoco descuenta transparencias de las figuras y limita el porcentaje a 100: no sustituye la validación geométrica.

## Defectos reproducidos y riesgos separados

### F1 — Recuperación no respeta margen/separación [alta]

`PlanchaProject.from_dict` ignora `margin_cm`/`gap_cm` guardados y utiliza margen fijo según formato y gap 0,05. Reproductor en JSON: antes 0,30/0,15 cm → después 0,15/0,05 cm. Las coordenadas pueden no cambiar inmediatamente, pero se pierde la configuración que condiciona edición, validación y siguiente packing. Corregir compatibilidad de versiones sin reacomodar históricos automáticamente.

### F2 — Piezas imposibles sin resultado explícito [alta]

`calculate_pagination([pieza 30×30 cm])` devuelve `[]`: 1 entrada, 0 hojas, 0 piezas devueltas. Si deja de caber cualquier remanente, el bucle termina sin resultado de rechazados. Además `organize_with_pagination` retorna `[]` con el comentario «todos distribuidos». Riesgo de informar finalización sin todas las unidades. No es pérdida comprobada en SQLite; es pérdida de información en el contrato del paginador.

### F3 — Impresión bloqueada por escala contradictoria [crítica]

`printing_config`/`save_printing_config` usan 97,27; `_print_validation_error` exige `int(scale)==100`. Reproductor con A4 válido y configuración predeterminada: «La configuración fija no coincide con A4 vertical y escala 100 %.», antes de consultar disponibilidad de impresora. La solución futura debe unificar validación y semántica de escala **sin cambiar calibración 0,9727**.

### F4 — Archivo faltante omitido silenciosamente [crítica]

`render_sheet` captura excepciones por pieza y continúa. Reproductor: proyecto de un diseño cuyo archivo no existe devuelve A4 2480×3508, alfa completamente vacío, sin excepción. Riesgo de exportar/imprimir cantidades incompletas. Se requiere preflight y fallo explícito por pieza, no sustituir o inventar imágenes.

### Riesgos observados por código, no reproducidos extremo a extremo

- `export_all_planchas`/`print_all_planchas` incrementan contadores tras funciones que pueden retornar sin éxito, y manipulan widgets en un thread secundario: riesgo de resumen engañoso y errores Tk.
- `print_all_planchas` cambia proyecto/index sin seleccionar claramente `plancha_id` y PNG específicos de cada página: riesgo de reutilizar artefacto/identidad de la hoja activa. Necesita test con adaptador de cola, sin enviar a impresora real.
- `save_plancha_set` guarda archivos y confirma por página; fallo intermedio puede dejar conjunto parcial y el estado temporal del editor sin restaurar (no hay `finally` en ese tramo). Guardar repetidamente crea registros nuevos: comprobar impacto en identidades/reservas.
- SVG y rutas `silent=True` no usan el mismo control visible de aprobación que el PNG individual: revisar intención y permisos, no dar por válida una exportación de producción por el formato.
- Carga/preview de estándar llama normalización y puede reorganizar si cambia geometría. Los tests de conservación legacy/libre no demuestran inmutabilidad de todos los históricos estándar confirmados. Auditar protección de estado antes de cambiar normalizaciones.

## Cadena física Epson L3210 → Brother ScanNCut X225

PNG: 21×29,7 cm, 300 DPI, 2480×3508 px por redondeo; fuentes se recortan a bbox visible y mantienen proporción. El lienzo/PNG y el canvas comparten coordenadas; la vista de cliente no contiene las mismas guías técnicas.

Calibración vigente inspeccionada: `PRINT_SCALE=0.9727`, `CUT_INSET_MM=1.50`; estimación `final=producción×0.9727−0.30 cm`. Márgenes base productivos: A4 0,15 cm y A5 0,05 cm; otros helpers geométricos tienen defaults propios (p.ej. 0,5 cm), por lo que hay que comparar rutas y no asumir un margen universal.

El envío Windows `print_png_strip` aplica 0,9727 y puede reducir adicionalmente para caber en el área imprimible reportada por el driver. Riesgo de tamaño menor que el estimado si el perfil/papel hace actuar ese ajuste. Perfiles DEVMODE por impresora existen, pero no se leyó ni validó un perfil operativo real de la L3210 en esta auditoría. «100 %» de UI, tamaño PNG, escala interna calibrada y ajuste del driver son conceptos distintos que hoy no se comunican consistentemente.

Brother: hay contornos rasterizados y utilidades/formularios de calibración; no se encontró en esta ruta una exportación SVG de trayectorias ni un controlador específico X225. El SVG exportado contiene imagen. La lectura/compensación/offset y el corte del equipo no quedan certificados por pruebas Python. Pendiente: imprimir muestra con configuración vigente, medir lado preparado/impreso/final, escanear/cortar con el operador y registrar desviación sin cambiar constantes automáticamente. No enviar trabajos ni marcar impresión/terminación desde esta auditoría.

## Calidad y pruebas

- Focalizadas: **112 aprobadas**, 24,20 s, `artifacts/creator-audit-focused.xml`. Última fila, cinco franjas, paginación, preview, cantidades, Mixta, conversión libre, tamaño/nominal, tandas, saldos, trazabilidad y calibración.
- 42 advertencias de deprecación Pillow en las pruebas de render, no fallos.
- Suite general: **1259 aprobadas, 1 omitida, 5 subtests aprobados, 0 fallos**, 289,95 s; `artifacts/creator-audit-full.xml`. 46 advertencias: las 42 de Pillow más 4 tests preexistentes que retornan valores. La suite usa Tcl instalado y una comprobación inicial Tk, sin omitir escenarios gráficos por falta de runtime.
- Benchmark y reproductores no son nuevos tests de aceptación productiva. Reproductores fallidos se conservan como hallazgos, sin modificar el algoritmo para hacerlos pasar.
- Base operativa y base de tanda física mantienen los SHA-256 ya registrados antes de esta auditoría: `f6abfb14fedfefb99653fa0928e1010cb1d8bd30da7955a7bc3ac4eb0a9340f2` y `c5457335c8ae472e7c00b38d1b827c8bb50276c35f5796cb80aab79a16d01e0c`, respectivamente. No se atribuye cobertura a las rutas defectuosas sólo porque la suite existente esté verde.

## Propuesta Sprint 1 — cerrar el circuito existente

No implementada. Prioridad por riesgo, no por facilidad:

1. **P0: preflight de impresión/exportación único.** Resolver F3 y F4; rechazar archivos faltantes, tamaños inválidos y páginas incompletas con detalle por diseño. Conservar constantes y registrar escala efectiva. Aceptación: configuración calibrada válida pasa; falta de fuente bloquea antes de exportar/encolar.
2. **P0: resultado completo de paginación.** F2: colocadas+rechazadas=solicitadas, razones explícitas, ningún «generado» falso. Incluir lote con piezas imposibles mezcladas con válidas.
3. **P1: recuperación fiel y protección de históricos.** F1: conservar parámetros versionados y no reordenar confirmados/impresos; abrir/guardar sin cambios conserva hash geométrico. Definir migración legada explícita y respaldada.
4. **P1: lote consistente.** Identidad/PNG/aprobación por hoja, resultados de retorno comprobables, restauración con `finally`, operaciones Tk sólo en hilo principal y recuperación ante fallo a mitad del conjunto. No alterar las reservas existentes.
5. **P1: paridad de entradas desde Pedidos.** Misma información disponible y compatibilidad por trabajo/material/unidad, sin recapturar datos. Probar pedido A40/B35/C25, dos materiales y hojas vs unidades; preferir el contrato de preparación existente antes de crear otro.
6. **P2: comodidad y rendimiento medidos.** Resumen por diseño/hoja, mensaje de saldo/imposibles y perfil activo claro; medir por separado consulta, carga, render y escritura. Agrupar consultas de candidatos y usar caché/instrumentación donde el perfil lo justifique. No reescribir el algoritmo de packing en este primer sprint.

Dependencias de aceptación: muestras y operador Epson/Brother; definición de compatibilidad para rutas históricas; fixtures de proyectos versionados; adaptador de cola falso para no gastar material ni registrar producción ficticia. El objetivo del sprint propuesto es confiabilidad/integración, no añadir modos nuevos.
