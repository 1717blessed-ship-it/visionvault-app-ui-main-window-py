# Sticker Studio 2.0 — Performance Hardening

Fecha de medición: 2026-10-21. Estado: candidato de mantenimiento evaluado; no publicado.

## Control de versión

- Referencia preservada: `sticker-studio-v2.0.0`, commit pelado
  `bd7f93bf0f5b063b95936769eb8f82e60b2daed1`.
- Rama de trabajo: `codex/sticker-studio-performance-2.0.1`.
- El editor clásico, las rutas A/B/C/D, perfiles y calibraciones no fueron
  modificados.
- `2.0.1` es solamente una propuesta. No se creó ni movió ninguna etiqueta.

## Entorno reproducible

- Windows 11 10.0.26200, CPU AMD64 Family 25 Model 80, 12 procesadores lógicos.
- Python 3.14.6, Pillow 12.3.0, NumPy 2.5.1 y OpenCV 5.0.0.
- Lote: 20 derivados de carga de contenido real preservado, entre 600.000 y
  4.000.000 píxeles, procesados en el mismo equipo y perfil.
- Casos adicionales reales: disco 421×421 y soporte opaco 600×600.

La referencia inmutable está en
`artifacts/sticker-performance-2.0.0-baseline/`. Las salidas candidatas están
separadas en `artifacts/sticker-performance-2.0.1-optimized/`.

## Perfil inicial

El perfil `baseline.pstats` registró 2.715.477 llamadas en 43,786 s. Los cinco
costos con mayor impacto útil fueron:

1. Codificación/escritura PNG: 562 `Image.save`, 10,644 s acumulados.
2. Render nativo: 21 llamadas, 5,604 s.
3. Clasificación: 22 llamadas, 4,519 s.
4. Reducciones NumPy repetidas (`min`/`max`) sobre RGB: aproximadamente
   5,8 s acumulados entre ambas familias.
5. Segmentación/refinamientos por ruta (flujo B, regiones exteriores,
   interiores cerrados y damero): entre 1,86 y 3,18 s por etapa.

El muestreador de memoria usa una hebra con `sleep`; sus tiempos y el `join` no
se interpretan como costo del motor.

## Optimizaciones aceptadas

- Se calcula una sola vez la máscara exterior de damero durante la
  clasificación.
- Se reutiliza la conversión en escala de grises para densidad de bordes.
- Se conservan una sola vez los mínimos y máximos por canal usados por el
  análisis de halo. Las expresiones y umbrales permanecen idénticos.
- Tres artefactos que ya eran binariamente idénticos se materializan mediante
  copia del PNG persistido, evitando recodificación. No se elimina ningún
  artefacto del contrato.
- La bandeja V2 incorpora un caché LRU acotado a 256 miniaturas, invalidado por
  ruta resuelta, tamaño y `mtime_ns`. Una selección no vuelve a decodificar el
  original.

El perfil candidato redujo las escrituras PNG de 562 a 496. Las variaciones de
I/O hacen que una corrida individual de `cProfile` no sea una comparación de
tiempo suficiente; la decisión usa medianas independientes.

## Benchmark antes/después

Tres corridas independientes por versión:

| Métrica | 2.0.0 min/mediana/máx. | candidato min/mediana/máx. | Cambio de mediana |
|---|---:|---:|---:|
| Lote 20, pared (s) | 36,2865 / 37,0662 / 40,2999 | 31,7803 / 33,7684 / 36,8013 | **−8,9 %** |
| CPU (s) | 55,0156 / 55,0938 / 57,5938 | 47,7812 / 51,7969 / 54,1406 | **−6,0 %** |
| Pico RSS (MiB) | 462,71 / 462,77 / 463,85 | 452,46 / 462,21 / 462,27 | −0,1 % |
| Cambio de preview (ms) | 4,664 / 4,798 / 5,013 | 4,437 / 4,482 / 4,873 | **−6,6 %** |

El objetivo orientativo de 20–30 % no se alcanzó sin cambiar algoritmos o
codificación. La mejora obtenida sí es repetible y mantiene exactitud.

### Canvas y bandeja

- Canvas 2000×2000: paneo rápido 19,424 ms para 30 eventos frente a 3.221,277
  ms de recomposición completa; zoom diferido 69,869 ms para 20 eventos frente
  a 1.901,354 ms directo. Se preserva el LRU existente de 192 MiB.
- Cambio de selección con miniaturas calientes:
  - 20 elementos: 97,074 ms, 7,07× frente a decodificar de nuevo.
  - 50 elementos: 302,814 ms, 3,06×.
  - 100 elementos: 612,798 ms, 2,06×.

No se aumentó la memoria de caché del Canvas. La creación/destrozo de widgets
de toda la bandeja sigue siendo el costo dominante para 100 elementos; cambiar
su arquitectura se descartó por exceder una intervención conservadora.

## Garantía de identidad

- Lote de 20: todos los raster intermedios comunes, máscaras, masters y PNG
  exportados tienen el mismo SHA-256.
- Los 20 originales tienen el mismo SHA-256 y conservan el mismo estado de
  calidad.
- Los contratos semánticos coinciden: ruta/caso, motor, tipo, parámetros de
  reproceso, dimensiones, resolución nativa, DPI efectivo, contracción y
  tratamiento de borde.
- Matriz real: 18 corridas (2 originales × 9 configuraciones) sin diferencias.
  Incluye contracción 0/0,1/0,2/0,5 mm, expansión 0,2 mm, suavizado 0,2 mm y
  Conservar y limpiar/Reemplazar/Agregar nuevo.
- Master y exportación fueron idénticos en 20/20 trabajos en cada repetición.

Los comparadores reproducibles son
`scripts/compare_sticker_performance_outputs.py` y
`scripts/compare_sticker_performance_reference_matrix.py`.

## Pruebas

- Suite general: **1.175 aprobadas, 1 omitida, 5 subpruebas aprobadas**, 249,12 s.
- Advertencias: cuatro pruebas históricas de fondo blanco retornan `bool` en
  lugar de usar `assert`; no son fallos nuevos.
- La suite cubre cancelación/reintento, edición manual, persistencia,
  publicación, recuperación, concurrencia y editor clásico.
- Prueba nueva: una actualización de selección no vuelve a decodificar la
  miniatura.

## Optimizaciones descartadas o no aplicadas

- Paralelismo del motor: descartado. El pico actual ronda 462 MiB y los trabajos
  deben conservar orden, cancelación y aislamiento; multiplicar procesos eleva
  memoria y riesgo sin evidencia favorable.
- Cambio de compresión PNG, interpolación, precisión, umbrales o algoritmos:
  rechazado porque rompería identidad binaria o calidad.
- Caché de campos de distancia: no aplicado; requiere una política adicional
  de identidad/invalidez de máscara y el perfil actual no lo ubicó entre los
  cinco costos principales.
- Virtualización completa de bandeja: pendiente opcional, no necesaria para
  aceptar este hardening y demasiado invasiva para el alcance.
- Lotes de motor de 50/100 no se materializaron porque duplicar los mismos 20
  originales produciría varios GiB de artefactos sin ampliar cobertura. La UI
  sí fue medida con 20/50/100 elementos y la validación productiva usa 20
  archivos grandes reales.

## Recomendación

**Aceptar como candidato `2.0.1`**, sin publicarlo automáticamente. La mejora
de lote y respuesta es medible, memoria no aumenta y la salida es idéntica en
las referencias congeladas. La aceptación de rendimiento no cierra ni altera
el P1 visual del disco y no constituye homologación física de impresión/corte.
