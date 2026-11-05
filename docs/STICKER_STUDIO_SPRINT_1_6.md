# Sticker Studio 2.0 — Sprint 1.6

Fecha de validación: 20 de octubre de 2026.

## Resultado

Los hitos A y B quedaron implementados y cubiertos por pruebas automatizadas. El
editor no se declara listo para producción: la máscara real de la bola disco
continúa pendiente de aprobación humana y siguen pendientes la impresión y el
corte físicos.

## Hito A — correcciones P1 funcionales

- Se separaron los estados de procesamiento, revisión del master, envío a
  Últimos Procesados y exportaciones. Exportar ya no exige publicación.
- La revisión se vincula al SHA-256 del master. Cambiar parámetros, máscara,
  deshacer, rehacer o reprocesar invalida la revisión y obliga a revisar y
  reenviar la nueva versión.
- Enviar a Últimos Procesados conserva el trabajo en la sesión y es idempotente.
  Quitar posteriormente el trabajo de la bandeja no elimina sus artefactos
  persistidos.
- La vista Final usa el master real del pipeline. La exportación copia ese mismo
  archivo byte por byte. Las guías y el contorno de corte permanecen exclusivos
  del editor.
- El preview sólo crea contorno cuando corresponde a Reemplazar o Agregar nuevo;
  Conservar y limpiar no recibe un segundo borde.

### Causas raíz corregidas

1. Confirmar mezclaba revisión, publicación y cierre de sesión en una sola
   transición irreversible.
2. El preview podía sintetizar una composición distinta del master y dibujar un
   borde adicional sin respetar el tratamiento efectivo.
3. El historial de máscara y los parámetros vivían en mecanismos separados y
   los cambios continuos del inspector no formaban operaciones lógicas.

## Hito B — experiencia y rendimiento

- Historial no destructivo por sticker para pincel, borrador, restauración,
  protección, parámetros de contracción/expansión/suavizado y borde. Una nueva
  modificación elimina la rama de rehacer.
- Contracción y expansión se calculan en un trabajador único con debounce de
  140 ms e identificador de generación. Los resultados obsoletos se descartan y
  Tkinter sólo se actualiza en el hilo principal.
- Durante paneo se mueve el bitmap visible y se recompone en alta calidad al
  soltar. El zoom por rueda agrupa renders a intervalos de aproximadamente
  16 ms. A zoom alto sólo se escala el viewport visible.
- Caché LRU de previews con límite de 192 MiB.
- Zoom numérico, doble clic Ajustar/100 %, fondos damero/blanco/negro/gris/
  magenta y comparador con divisor.
- Rueda en el inspector, Espacio + arrastre con protección de campos de texto,
  herramienta activa resaltada y vista independiente por sticker.
- Se retiró el lazo no implementado y se aclararon Procesar este sticker,
  Reprocesar fondo y Aplicar contracción y generar borde.
- Se añadieron estados Guardando, Guardado, Cambios pendientes y Calculando, e
  indicadores de máscara manual, referencia humana, revisión, envío, tratamiento
  de borde y advertencias del informe de calidad.

El minimapa por encima de 200 % no se incorporó: era opcional y se priorizó el
viewport recortado, que aporta la mejora medible sin añadir otra superficie de
navegación o riesgo de conflicto con los pinceles.

## Flujos verificados

- Importar → procesar → revisar master → exportar sin publicar.
- Revisar → enviar a Últimos Procesados → seguir editando/exportando sin perder
  el trabajo.
- Cambio posterior del master → revisión y envío previos invalidados.
- Conservar y limpiar, Reemplazar y Automático sin duplicación de borde en el
  preview.
- Aplicar parámetros → deshacer → rehacer como una operación agrupada.
- Selección múltiple, retiro seguro, recuperación de sesión y estado por sticker.
- Ventanas 1040×680, 1280×720 y 1600×900 con Canvas y controles operativos.
- Editor clásico conservado y sin cambios en calibraciones ni rutas A/B/C/D.

## Pruebas

Compilación:

```text
python -m py_compile app/stickers/editor.py app/stickers/editor_v2/*.py scripts/benchmark_sticker_canvas_sprint16.py
Resultado: correcta
```

Suite focalizada:

```text
98 passed in 22.58s
```

Suite general:

```text
1174 passed, 1 skipped, 4 warnings, 5 subtests passed in 232.14s
```

La omisión conocida requiere los archivos externos shield1.png…shield5.png. Las
cuatro advertencias históricas son `PytestReturnNotNoneWarning` de
`test_white_border_white_background.py`; no se modificaron para esconderlas.

## Métricas reproducibles del Canvas

Fuente: PNG RGBA real de 2000×2000, mismo entorno, 30 movimientos y 20 eventos
de zoom. Script: `scripts/benchmark_sticker_canvas_sprint16.py`.

| Medición | Antes / recomposición completa | Después / interacción optimizada | Mejora |
|---|---:|---:|---:|
| Paneo, 30 movimientos | 2902.259 ms | 16.515 ms | 175.73× |
| Zoom, 20 eventos | 1641.855 ms | 71.144 ms | 23.08× |

La API disponible no informó working set del proceso (`null`); por eso no se
declara una reducción de memoria. Sí se verificó explícitamente el límite de
caché de 192 MiB. Resultado completo:
`artifacts/sticker-studio-sprint16/canvas_benchmark.json`.

## Evidencia visual

- `artifacts/sticker-studio-sprint16/sticker_studio_2_sprint16.png`: captura de
  una instancia real del Canvas V2 a 1360×820.
- `artifacts/sticker-studio-sprint16/interface_capture_source.png`: fuente de la
  captura controlada.
- `artifacts/sticker-studio-sprint16/interface_capture_mask.png`: alfa mostrado.
- `artifacts/sticker-studio-sprint16/interface_capture_master.png`: master final.

## Archivos modificados

- `app/stickers/editor.py`
- `app/stickers/editor_v2/adapter.py`
- `app/stickers/editor_v2/canvas.py`
- `app/stickers/editor_v2/components.py`
- `app/stickers/editor_v2/review.py`
- `app/stickers/editor_v2/session.py`
- `app/stickers/editor_v2/state.py`
- `app/stickers/editor_v2/window.py`
- `tests/test_sticker_studio_v2.py`
- `tests/test_sticker_studio_v2_operations.py`
- `scripts/benchmark_sticker_canvas_sprint16.py`
- `scripts/capture_sticker_studio_sprint16.py`
- `docs/STICKER_STUDIO_SPRINT_1_6.md`

## Pendientes

- Aprobación humana de la máscara real 421×421 de la bola disco; el P1 visual
  permanece abierto.
- Validación visual humana de los originales reales 421×421 y 600×600 y de sus
  detalles finos en los cinco fondos.
- Prueba física A4, medida final, impresión, recorrido de corte y ScanNCut.
- Medición de memoria con un monitor de proceso disponible y lote de archivos
  grandes de producción proporcionado por el usuario.
- Revisión manual de accesibilidad y foco en Windows con teclado real.

Estado: **automatización aprobada; producción requiere validación humana y
física**.
