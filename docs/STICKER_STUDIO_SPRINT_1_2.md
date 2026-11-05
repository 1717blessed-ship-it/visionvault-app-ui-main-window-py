# Sticker Studio 2.0 — Sprint 1.2: contraer selección

Fecha: 2026-10-19. Estado técnico: implementado y sin regresiones. El P1 del
disco continúa pendiente de referencia humana y el módulo no está aprobado para
producción física.

## Implementación

Se añadió `app/stickers/mask_contraction.py`, una operación de alfa basada en
campo de distancia firmado. Convierte milímetros a píxeles con el DPI efectivo
de la fuente y desplaza el isocontorno hacia dentro sin escalar la imagen. La
cobertura se reconstruye con transición subpíxel; RGB no se modifica.

La etapa vive después de segmentación/limpieza y tratamiento de borde, y antes
de padding, recorte, base blanca y corte. Es común a A/B/C/D, incluido el caso
sin borde blanco. Cada corrida parte de `selection_alpha_original`; nunca usa
`selection_alpha_contracted` como entrada. `mask_editable` también conserva la
base previa a la contracción, evitando acumulación tras editar/reprocesar.

El lienzo maestro y `physical_size_cm` no cambian. El recorte se calcula con la
extensión de la selección base y no con la contraída, para impedir que el motor
amplíe nuevamente la silueta y anule el desplazamiento físico.

Los parámetros persistidos son:

- `selection_contraction_mm`, entre 0 y 2 mm;
- `selection_smoothing_mm`, entre 0 y 1 mm;
- reporte con DPI, equivalencia en píxeles, área retenida, componentes antes y
  después y advertencias.

## Interfaz

El inspector V2 incluye deslizador de contracción 0–2 mm, paso 0,1 mm, valor
inicial 0; suavizado; borde blanco independiente; selector de visualización
Original/Contraída/Ambas; Aplicar, Deshacer y Restablecer.

La vista previa se actualiza con debounce sin ejecutar el pipeline ni escribir
artefactos. Cian representa la selección original y magenta la contraída. Al
aplicar, el trabajo se reprocesa desde la máscara base y se genera el master
real. Los ajustes e historial están aislados por job.

Si desaparecen componentes, aumentan los componentes por una conexión cortada,
se elimina toda la selección o se pierde más de 15 % del área, el resultado se
marca para revisión. La advertencia no se oculta ni se interpreta como mejora.

## Validación

Pruebas unitarias y de integración cubren:

- identidad byte a byte a 0 mm;
- conversión 1 mm = 10 px a 254 DPI;
- alfa parcial y antialiasing;
- preservación de puntas de estrella a contracción pequeña;
- detección de conexiones cortadas y elementos pequeños eliminados;
- RGB inalterado;
- funcionamiento sin borde blanco;
- originales reales 421 × 421 y 600 × 600;
- dos reprocesamientos independientes idénticos;
- tamaño físico nominal conservado.

Smoke test Tk real: ventana, sliders y callbacks correctos.

Suite completa: **1139 passed, 1 skipped, 4 warnings, 5 subtests passed** en
247,27 s. Las advertencias históricas y la omisión externa no cambiaron.

## Evidencia visual

`artifacts/sticker-mask-contraction-sprint12/` contiene, para 0, 0,1, 0,2 y
0,5 mm:

- máscara original y contraída;
- master y master nativo;
- corte;
- vistas sobre blanco, negro, gris y magenta;
- hoja comparativa y `audit.json` con métricas físicas.

Las fuentes disponibles son el disco 421 × 421 con damero incrustado y su apoyo
opaco 600 × 600. No apareció otro original independiente de estrellas cromadas.

## Límite del P1

La contracción puede retirar material periférico, pero no demuestra qué píxeles
son halo y cuáles pertenecen al borde, las estrellas o sus conexiones. Las
salidas reales mantienen la revisión requerida. No se declara resuelto el P1
hasta disponer de una máscara 421 × 421 trazada y aprobada por una persona,
compararla regionalmente y validar impresión/corte físicos.

