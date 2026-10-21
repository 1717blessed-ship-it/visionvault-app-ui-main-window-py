# Sticker Studio 2.0.2 — mantenimiento de interfaz

Fecha: 2026-10-21. Estado: candidato verificado; no publicado ni etiquetado.

## Base y alcance

- Estable preservada: `sticker-studio-v2.0.0`, commit
  `bd7f93bf0f5b063b95936769eb8f82e60b2daed1`.
- Base utilizada: candidato 2.0.1 verificado, commit `aa6142d`. Continúa sin
  etiqueta ni publicación.
- Rama: `codex/sticker-studio-2.0.2-virtual-tray`.
- Alcance exclusivo: bandeja V2, respuesta interactiva, caché geométrica,
  pruebas y benchmarks. No se modificaron el pipeline, rutas A/B/C/D,
  calibraciones, perfiles ni editor clásico.

## Cuellos de botella

1. La bandeja destruía y recreaba una tarjeta completa por trabajo ante cada
   selección o cambio de estado: 200 trabajos implicaban 200 tarjetas vivas.
2. Cada actualización recorría y configuraba todos los widgets aunque sólo
   cambiara la selección.
3. Las miniaturas nuevas se decodificaban de forma síncrona.
4. Una misma máscara y los mismos parámetros recalculaban el campo de
   distancias en previews repetidos.
5. El preview tenía debounce y generaciones, pero faltaba consolidar el master
   al soltar el slider y bloquear revisión/exportación mientras hubiera un
   ajuste provisional.

## Implementación

- Bandeja virtual horizontal: crea únicamente tarjetas visibles más dos de
  precarga por lado; conserva la extensión lógica completa del scroll.
- Reciclaje seguro de tarjetas, identidad por objeto de trabajo, selección
  independiente de visibilidad y posición de scroll preservada al refrescar.
- Caché de miniaturas por ruta resuelta, `mtime_ns` y tamaño; carga visible
  incremental mediante `after`, sin bloquear una tanda completa en Tkinter.
- Los cambios de selección/estado actualizan sólo tarjetas activas. Ctrl,
  Shift, menú contextual y eliminación mantienen índices reales.
- Contracción, expansión, suavizado y borde muestran preview provisional con
  el worker/generación existente. Al soltar se solicita el master definitivo;
  una pausa de 650 ms actúa como respaldo para teclado u otras entradas.
- Un resultado definitivo con parámetros antiguos se descarta y reprocesa con
  el último estado. Un preview nunca puede revisarse, enviarse o exportarse.
- Caché geométrica exacta por hash/dimensiones de máscara, operaciones
  manuales, desplazamiento, DPI y suavizado. Límite por bytes: 64 MiB.

## Benchmark reproducible

Cinco repeticiones de apertura/selección y tres de rueda, mismo Windows y
archivos reales preservados. Valores en milisegundos; se informa la mediana.

| Trabajos | Apertura 2.0.1 | Apertura 2.0.2 | Selección 2.0.1 | Selección 2.0.2 | Tarjetas vivas antes/después |
|---:|---:|---:|---:|---:|---:|
| 20 | 740,20 | 496,23 | 181,32 | 28,57 | 20 / 11 |
| 50 | 922,14 | 542,25 | 499,62 | 30,76 | 50 / 11 |
| 100 | 1.462,12 | 557,01 | 961,90 | 31,03 | 100 / 11 |
| 200 | 2.092,22 | 538,17 | 1.894,18 | 31,08 | 200 / 11 |

Para 200 trabajos, apertura mejora 74,3 % y selección 98,4 %. La asignación
Python máxima medida baja de 2,07 MiB a 1,04 MiB. En tamaños pequeños existe
un costo fijo de aproximadamente 0,3–0,4 MiB por virtualización y colas.

El desplazamiento incremental con rueda queda entre 3,43 y 8,25 ms de mediana,
con p95 entre 9,10 y 12,08 ms. Es algo más costoso que mover 200 widgets ya
creados (2,78–5,12 ms), pero permanece bajo un cuadro de 16,7 ms y evita el
costo masivo de apertura/selección. Saltos directos a zonas lejanas tardan
aproximadamente 30–79 ms; la miniatura se completa incrementalmente.

### Caché geométrica

- 2.0.1 sin caché, repetición idéntica: mediana 11,235 ms, p95 14,459 ms.
- 2.0.2 con caché exacta: mediana 0,029 ms, p95 0,106 ms.
- Todos los resultados repetidos fueron idénticos.

## Garantía de producción

- Lote real: 20/20 procesados, 20/20 master/export idénticos.
- Comparación contra 2.0.1: todos los raster comunes, máscaras, masters y PNG
  exportados tienen el mismo SHA-256.
- Mismos originales, clasificación, estados de calidad, rutas, dimensiones,
  DPI, contracción y tratamiento de borde.
- Matriz real de disco 421×421 y soporte 600×600: 18/18 configuraciones
  idénticas, incluyendo contracción, expansión, suavizado y los tres
  tratamientos de borde.
- El tiempo de motor no se atribuye a este mantenimiento: no se modificó el
  pipeline y una corrida concurrente con otras pruebas tuvo carga no comparable.

Evidencias: `artifacts/sticker-performance-2.0.2/`.

## Pruebas específicas

- Bandeja con 200 trabajos y selección fuera de pantalla.
- Posición conservada al cambiar estados.
- Eliminación con índices virtualizados.
- Caché de miniaturas e invalidación por archivo.
- Caché geométrica exacta y acotada.
- Debounce: veinte cambios rápidos producen una sola consolidación.
- Descarte de resultado definitivo obsoleto.
- Bloqueo de exportación durante parámetros provisionales.
- Persistencia, deshacer/rehacer, revisión y publicación existentes.

Regresión general final: **1.181 pruebas aprobadas, 1 omitida y 5 subpruebas
aprobadas** en 263,63 s. Persisten cuatro advertencias históricas de pytest por
funciones de prueba que retornan `bool`; no son fallos ni regresiones nuevas.

## Riesgos y decisión

- El salto directo a una región no visitada crea/reconfigura hasta once
  tarjetas y puede mostrar `CARGANDO…` brevemente. Es deliberado para no
  bloquear Tkinter decodificando imágenes completas.
- No se incorporó paralelismo de producción ni una aproximación geométrica.
- No se publica 2.0.2 automáticamente.

Recomendación: **aceptar como candidato 2.0.2**. La suite general final quedó
limpia, la mejora es material con 50–200 trabajos y no modifica producción.
