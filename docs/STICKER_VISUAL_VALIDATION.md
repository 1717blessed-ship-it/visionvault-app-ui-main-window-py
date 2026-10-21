# Creador de Stickers — validación visual profesional

Continuación: [correcciones focalizadas y estado actualizado](STICKER_VISUAL_CORRECTIONS.md).
Este informe conserva la evidencia de partida; no se sobrescribieron sus resultados.

Fecha: 2026-10-17. Estado: **REQUIERE CORRECCIONES Y REVISIÓN HUMANA**.
No habilita producción. No se imprimió ni cortó ninguna muestra.

## Resultado y alcance

Se ejecutaron 36 entradas (18 categorías × A/B) y ocho combinaciones compatibles
de modos: 44 procesamientos terminados, sin excepciones. Todos quedaron en
REVISAR; ninguno fue confirmado ni publicado. Los hashes de las 44 fuentes
permanecieron iguales antes/después del procesamiento.

Se examinaron visualmente las 18 hojas de categoría, las comparativas de modos
y los zooms de las tres muestras reales. Es evaluación asistida por el agente,
no aprobación humana. **Aprobados visualmente para producción: 0. Revisión
humana pendiente: los 44.** Hay seis hallazgos P1 y dos P2 documentados abajo.
No se comprobó corrupción de originales ni aprobación automática de defectos P0.
Esto no demuestra ausencia universal de P0.

El banco contiene tres referencias reales del usuario (corazón, disco, labios)
y 33 entradas sintéticas reproducibles. Solo dos categorías tienen referencias
reales. Los sintéticos de fotografía, ilustración compleja y escaneado son
sondas técnicas, NO fotografías, acuarelas ni escaneos reales certificados.
Algunas categorías comparten geometría a propósito para comparar fondos; no
son 36 diseños semánticamente independientes. Faltan 33 referencias reales
para sustituir todos los placeholders del banco.

## Auditoría del recorrido existente

1. `editor.py:add_paths` importa/encola; `_process_index` entrega fuente,
   parámetros y cancelación al procesador. No se usó la base de datos real.
2. `pipeline.py:classify` calcula rasgos y etiqueta visual. Hay una definición
   anterior sombreada por la posterior: se auditó el método efectivo. El catálogo
   visual es independiente de A/B/C/D; no se ajustó para coincidir con fixtures.
3. `process` aplica guardas y recuperación acotada; `_process_impl` selecciona
   ruta, modo completo, máscara explícita o componentes según intención.
4. La máscara editable se guarda alineada con `source_editable`; las máscaras
   por objeto y correcciones se mantienen separadas. La limpieza automática
   y el relleno de interiores necesitan revisión visual, no solo tests de forma.
5. La base blanca usa `_build_unified_white_base`; `resolution.render_native`
   la rasteriza al DPI efectivo, sin convertir la miniatura en salida.
6. El corte es una máscara raster contraída desde la base; la corrección manual
   se aplica aparte. El diagnóstico superpone sus contornos en verde; no genera
   un nuevo formato vectorial ni garantiza validez física de cualquier edición.
7. Se conservan maestro legacy, impresión, control y nativos. `native_master`
   conserva el diseño disponible 1:1; la miniatura sigue siendo una vista reducida.
8. Metadata, manifest y `ProcessingResult.from_metadata` conservan referencias.
   La publicación del banco/pedido mantiene su contrato existente y fue cubierta
   por la suite; NO se publicó evidencia de este banco en producción.
9. `render_current` muestra maestro/máscara/corte y fondos; su vista no sustituye
   al nativo. `_finish_result` conserva acceso a alternativas para revisión.

Se reutilizaron artefactos y metadatos del pipeline. Las utilidades anteriores
`diagnostico_regresion_stickers.py` y `scripts/visual_validation_helper.py` se
inspeccionaron: la primera depende de otro banco de nueve imágenes y la segunda
está dedicada a pósters. No cubrían la matriz de esta fase.

## Banco y evidencias

Ejecución final: `artifacts/sticker-visual-v3/`. Se conservaron v1 y v2 como
evidencia previa; no se sobrescribieron. Las comparativas v2 y v3 son idénticas
byte a byte salvo el ensayo de corte independiente, cambiado deliberadamente.
La captura de interfaz pertenece a v1 y está identificada aparte.

- [Manifiesto automático de los 44 casos](../artifacts/sticker-visual-v3/manifest.json).
- [Observaciones visuales, severidad y reproducción](../artifacts/sticker-visual-v3/visual-review.json).
- `inputs/`: fuentes y máscaras sintéticas de referencia, con procedencia.
- `pipeline/<UUID>/`: artefactos sin edición del pipeline, incluidas alternativas.
- `views/<ID>/`: original, miniatura, nativo, alfa, base, corte, blanco, negro,
  damero generado, comparación, recorte 100 %, ampliación 200 % nearest-neighbour
  y superposición de corte. Las vistas no contaminan los archivos de producción.
- `sheets/01.png`…`18.png`: dos casos por hoja; las miniaturas son para inspección
  global. Abrir `native_master` o `edge_100pct.png` para evaluación pixel a pixel.
- `execution.log`: trazas existentes del procesador.

El manifiesto registra ID, fuente, procedencia, tipo esperado/detectado, rasgos,
modo, ruta, tamaños fuente/nativo, dimensión física, control de calidad,
advertencias/errores, alternativas, segundos, hashes y rutas de evidencias.
Su campo `visual_validation=PENDING` significa **pendiente de aprobación humana**;
las observaciones del agente están en el archivo separado `visual-review.json`.
COMPLETED solo significa finalización técnica.

| ID y categoría | Fuente A / B | Observación principal | Hoja |
|---|---|---|---|
| 01 Arte transparente | Sintética / sintética | B pierde hueco del diseño | [01](../artifacts/sticker-visual-v3/sheets/01.png) |
| 02 Borde blanco terminado | Sintética / sintética | B pierde hueco; verificar conservación de borde | [02](../artifacts/sticker-visual-v3/sheets/02.png) |
| 03 Halo gris | Sintética / sintética | Línea gris residual | [03](../artifacts/sticker-visual-v3/sheets/03.png) |
| 04 Damero incrustado | Corazón real / disco real | Corazón conservado globalmente; disco irregular | [04](../artifacts/sticker-visual-v3/sheets/04.png) |
| 05 Fondo blanco | Sintética / labios reales | Labios con línea gris exterior | [05](../artifacts/sticker-visual-v3/sheets/05.png) |
| 06 Fondo neutro | Sintética / sintética | Pérdida grave del círculo rosa | [06](../artifacts/sticker-visual-v3/sheets/06.png) |
| 07 Fondo uniforme de color | Sintética / sintética | Misma pérdida sobre verde | [07](../artifacts/sticker-visual-v3/sheets/07.png) |
| 08 Fotografía | Placeholder / placeholder | Fondo residual; fotografía real no evaluada | [08](../artifacts/sticker-visual-v3/sheets/08.png) |
| 09 Ilustración compleja | Sintética / sintética | Extracción incompleta del fondo | [09](../artifacts/sticker-visual-v3/sheets/09.png) |
| 10 Logo/tipografía | Sintética / sintética | Se lee; rota a vertical; faltan logos reales | [10](../artifacts/sticker-visual-v3/sheets/10.png) |
| 11 Líneas finas | Sintética / sintética | Línea de 2 px visible; revisar escala física | [11](../artifacts/sticker-visual-v3/sheets/11.png) |
| 12 Múltiples objetos | Sintética / sintética | 3 componentes A; 2 B conectados; base agrupada | [12](../artifacts/sticker-visual-v3/sheets/12.png) |
| 13 Semitransparencias | Sintética / sintética | A conserva alfa; B altera hueco | [13](../artifacts/sticker-visual-v3/sheets/13.png) |
| 14 Borde de color | Sintética / sintética | Azul visible; B altera hueco | [14](../artifacts/sticker-visual-v3/sheets/14.png) |
| 15 Degradado/textura | Sintética / sintética | Fondo residual importante | [15](../artifacts/sticker-visual-v3/sheets/15.png) |
| 16 Sujeto cortado | Sintética / sintética | Mantiene truncamiento; no reconstruye faltantes | [16](../artifacts/sticker-visual-v3/sheets/16.png) |
| 17 Imagen completa | Sintética / sintética | Fondo conservado, rotación automática | [17](../artifacts/sticker-visual-v3/sheets/17.png) |
| 18 Dibujo escaneado | Placeholder / placeholder | Trazo conservado globalmente; falta escaneo real | [18](../artifacts/sticker-visual-v3/sheets/18.png) |

Coincidencia exacta entre etiqueta principal esperada y detectada: 14/36.
NO es precisión estadística del clasificador: etiquetas coexistentes, placeholders
y modo completo explícito impiden interpretarla así. Conservar `detected_types`
y rasgos complementarios antes de sacar conclusiones o modificar clasificación.
El banco recorrió A/B/C; **D no quedó validada visualmente**. No se forzó una ruta
ni se descargó un modelo para aparentar cobertura fotográfica.

## Tres modos: comprobaciones y límites

- Silueta: todos salvo 12/17. Se inspeccionaron fondos, contorno, huecos, borde y
  corte. Hay fallos de extracción y relleno de huecos: no aprobado globalmente.
- Completo: 17-A/B rectangular más `mode-Circular`, `mode-Ovalada` y
  `mode-Personalizada` con máscara explícita. Se observa fondo dentro de la
  forma y proporciones conservadas; la rotación automática es comportamiento
  existente. Nominal del perfil: 5,70 cm; requiere medición física.
- Objetos: 12-A detecta IDs 1/2/3 y guarda máscaras separadas; B conecta dos
  elementos con un puente y devuelve dos componentes (no separación semántica).
  `mode-objects-selected` deja ID 1 y excluye 2/3. `mode-objects-reprocess`
  conserva IDs/bboxes. La agrupación conserva objetos pero añade puentes blancos
  según la base existente; revisar si la intención es agrupar o separar.
- Edición manual: `mode-manual-first` y `mode-manual-reprocess` conservan la misma
  máscara byte a byte y su hueco. La base blanca rellena el interior del sticker:
  hueco en diseño y perforación del soporte NO son la misma cosa.
- Corte independiente: máscara elíptica deliberadamente distinta en
  `mode-independent-cut`; `native_cut` cambia y `native_master` es idéntico al de
  17-A. Demuestra independencia, NO aptitud física del corte elegido (ver VV-08).

Once casos generaron alternativa conservada; ninguno reemplazó automáticamente
la primaria (`select_alternative=false`). No se evaluó visualmente cada artefacto
de esas once alternativas; sus carpetas/metadatos están disponibles para revisión.
Los 44 casos tardaron 24,69 s sumando las mediciones de procesamiento y diagnóstico
individuales. No es benchmark de IA ni medición de RAM en fuentes grandes.

## Defectos documentados antes de cualquier corrección

Pasos comunes: ejecutar el comando del banco abajo, localizar el ID en manifest,
abrir original/máscara/negro/zoom/corte. El JSON de revisión añade pasos,
resultado esperado/obtenido, evidencia y módulo posible para cada hallazgo.
Las causas indicadas son hipótesis, no un diagnóstico causal cerrado.

| ID | Severidad | Casos | Esperado → observado | Módulo a investigar |
|---|---|---|---|---|
| VV-01 | P1 | 06-A/B, 07-A/B | Solo retirar fondo → casi todo el rosa desaparece; IoU 0,033–0,044 | Extracción uniforme/PNG opaco |
| VV-02 | P1 | 01-B, 02-B, 13-B, 14-B | Conservar hueco del diseño → se rellena en alfa editable | Política de interiores PNG |
| VV-03 | P1 | 08/09/15 A/B | Retirar degradado/textura → grandes zonas de fondo permanecen | Clasificación/extracción C |
| VV-04 | P1 | mode-objects-selected | Contorno exterior redondo → base/corte aplanados en lienzo 130×130 | Margen de salida nativa |
| VV-05 | P1 | 04-B disco real | Borde continuo → irregularidades y fragmentos; preservar estrellas intencionales | Damero/base existente |
| VV-06 | P2 | 03-A/B, 05-B | Limpiar sombra gris → línea gris residual, también presente en fuente | Limpieza exterior de halo |
| VV-07 | P2 | 10/11/16/17/18 A/B | Orientación previsible → rota a vertical, sin estiramiento observado | Presentación/intención de orientación |
| VV-08 | P1 | mode-independent-cut | Advertir corte fuera de base → sin aviso específico de contención | Calidad geométrica de corte manual |

Las advertencias actuales de REVISAR (resolución, partículas, posible borde
perdido) no describen necesariamente la pérdida semántica observada. No se puede
usar un control de calidad técnico sin errores como certificado visual.
No se corrigió ninguno de estos hallazgos, siguiendo el alcance de esta fase.

Prioridad recomendada: reproducir VV-01 y VV-04 con regresiones específicas;
después VV-02/VV-03/VV-05 y contención del corte VV-08. No retocar umbrales del
clasificador solo para mejorar 14/36. Mantener versiones y comparar contra este
banco al corregir, sin eliminar la evidencia previa.

## Interfaz real y procedimiento manual

Se utilizó la habilidad de control de Windows para observar la ventana existente
«Creador de stickers». La primera captura estaba ocluida; tras activar exactamente
esa ventana se obtuvo [evidencia real](../artifacts/sticker-visual-v1/ui-live.png).
Mostraba el corazón, un trabajo Rechazado y scroll vertical. No se modificó cola,
rechazo, máscaras, perfil ni publicación. El proceso abierto puede preceder a los
últimos cambios en disco: esta captura NO certifica una sesión recién cargada.

No se automatizaron de manera fiable todos los controles ni el guardado gráfico.
Revisión manual pendiente sobre sesión nueva y base de prueba:

1. Abrir el creador sin usar pedidos reales; importar una copia del caso.
2. Comparar original, máscara, resultado y corte en blanco/negro/damero.
3. Abrir nativo al 100/200 %, sin confundir interpolación de pantalla con detalle.
4. Guardar pincel/lazo, deshacer/rehacer; reprocesar y comprobar persistencia.
5. Cambiar objeto seleccionado, confirmar exclusión y separar en trabajos; comprobar
   historial/alternativas sin reemplazar una corrección aprobada.
6. Corregir corte sin modificar diseño; revisar VV-08 antes de autorizar salida.
7. Reabrir resultados, conservar evidencias y registrar evaluador, fecha, decisión
   y observación por ID. No marcar APROBADO en lote porque no hubo excepciones.

## Entorno, pruebas y reproducción

Python 3.14; Pillow 12.3, numpy, OpenCV y dependencias de aplicación existentes.
No se añadieron dependencias pesadas ni se modificó requirements en esta fase.
Tcl/Tk requiere acceso al runtime instalado. Un intento aislado de las nuevas
pruebas falló en pytest_configure por acceso a init.tcl; con acceso al runtime
pasaron, sin cambiar ni omitir aserciones.

```powershell
python -m scripts.validate_sticker_visuals --output artifacts/sticker-visual-nueva
python -m pytest -q --basetemp=pytest-visual-validation-temp --junitxml=pytest-visual-validation-results.xml -o cache_dir=pytest-visual-validation-cache
python -m pytest tests/test_sticker_visual_validation.py -q --basetemp=pytest-visual-tool-final-temp -o cache_dir=pytest-visual-tool-final-cache
```

Usar carpetas nuevas para cada corrida: la utilidad rechaza sobrescribir un
directorio existente. No usar los nombres de basetemp ya ocupados al reproducir.

- Suite completa recolectada antes de añadir las cuatro pruebas de la utilidad:
  **1056 passed, 1 skipped, 4 warnings, 5 subtests passed**, 205,12 s; salida 0.
  [JUnit](../pytest-visual-validation-results.xml).
- Las cuatro nuevas pruebas de banco/procedencia, determinismo/hueco, damero y
  protección de evidencia pasaron por separado: **4 passed**, 1,39 s, salida 0.
  No se presenta esa ejecución separada como una suite única de 1060 casos.
- Omisión: conjunto externo shield1…shield5 no disponible, como en fase anterior.
- Warnings: cuatro PytestReturnNotNoneWarning históricos; no se corrigieron aquí.
- Banco v3: **44 COMPLETED, 0 excepciones, 44 fuentes sin modificar**.

## Archivos de esta fase e integridad

- `scripts/validate_sticker_visuals.py`: banco determinista, runner sobre pipeline
  real, vistas, zooms, contornos superpuestos, hojas y manifiesto.
- `tests/test_sticker_visual_validation.py`: cuatro pruebas nuevas de la herramienta.
- `docs/STICKER_VISUAL_VALIDATION.md`: este informe.
- `docs/STICKER_PROFESSIONAL_HARDENING.md`: enlace de continuidad.
- `artifacts/sticker-visual-v1/`, `v2/`, `v3/` y JUnit: evidencia de ejecución;
  `v3/visual-review.json`: hallazgos del agente separados del resultado automático.

No se editaron pipeline, editor, modelos, DB, planchas, A/B/C/D ni calibraciones
en esta fase. El repositorio ya contenía cambios ajenos; se preservaron.

## Preparación para Epson L3210 y Brother ScanNCut X225

No iniciar una tirada como si este informe autorizara producción. Primero corregir
y revisar P1, completar muestras reales (fotografía/pelo, acuarela rosa pálida,
reflejos, blancos sobre blanco, escaneos, transparencias y tipografía fina), ruta D
y controles de edición en sesión nueva. Revisar las once alternativas pendientes.

Después preparar una plancha A4 de prueba con muestras visualmente aceptadas y
IDs, tamaño nominal y perfil registrados. Usar las rutas y calibraciones existentes;
sin ajustar a página ni introducir otra compensación de escala. Medir nominal,
registro, borde y separación; anotar papel, calidad/controlador, márgenes y fecha.
Probar lectura/corte con Brother y comparar trayectoria con borde impreso, incluida
curva cóncava y estrella. Registrar tolerancias acordadas y medidas reales antes
de declarar conformidad. Si hay desvío, conservar plancha y configuración para
diagnóstico; no recalibrar automáticamente a partir de una sola muestra.

**Validación física: pendiente. Creador listo para producción: NO.**
