# Corrección focalizada de defectos visuales

**Estado más reciente:** ver «Continuación de cierre focalizado» al final.
La primera parte conserva el informe histórico de la pasada de 1073 pruebas.
Actualización posterior: ver «Cierre controlado con referencia humana» para
la búsqueda de alfa original y el procedimiento pendiente de aprobación.

Fecha: 2026-10-17. **Corrección parcial: cuatro P1 corregidos en los casos
reproducidos, dos P1 abiertos y dos P2 pendientes. La fase no está cerrada.**
No se declara DoccioneStudio listo para producción.

## Evidencia y método

Se leyó el informe visual anterior y se contrastaron los ocho hallazgos con sus
casos, máscaras, originales, nativos y cortes. Se reutilizó el banco existente:
36 entradas y ocho combinaciones, sin cambiar fuentes ni etiquetas para mejorar
artificialmente las métricas. Tres entradas reales y 33 sintéticas; ocho ensayos
adicionales sintéticos. Las fotografías/escaneados sintéticos siguen sin representar
validación real de esos contenidos.

Línea base conservada: `artifacts/sticker-visual-v3/`.
Ejecución definitiva: `artifacts/sticker-corrections-release/`.

- [Manifiesto nuevo, 44 ejecuciones](../artifacts/sticker-corrections-release/manifest.json).
- [Registro de defectos actualizado](../artifacts/sticker-corrections-release/visual-review.json).
- [Métricas y vínculos antes/después](../artifacts/sticker-corrections-release/before_after/comparison.json).
- `before_after/<ID>.png`: alfa anterior/nuevo, nativo anterior/nuevo y corte
  anterior/nuevo. `sheets/01.png`…`18.png`: hojas regeneradas.
- `views/<ID>/`: fondos blanco/negro/damero, zoom 100/200 %, superposición de corte
  y comparativa; `pipeline/<UUID>/`: artefactos no modificados después de producirse.

Las 44 fuentes coinciden por SHA-256 con la línea base y permanecen sin modificar.
Las 44 etiquetas principales y rutas registradas también coinciden. No se alteró
el clasificador, el catálogo de 18 categorías ni la selección de A/B/C/D.
Se corrigieron operaciones de máscaras/base dentro del recorrido existente.

## VV-01 — Pérdida de pigmento sobre gris y verde, P1

**Causa confirmada:** `_light_neutral_exterior_alpha` calculaba saturación con
enteros int16. La diferencia de canales multiplicada por 255 puede alcanzar
65025: desbordaba 32767, se truncaba a saturación cero y convertía rosa/verde
saturados en supuestos neutros. La franja amarilla sobrevivía por sus condiciones
de valor, no porque fuera el único objeto legítimo. No era un error de erosión,
escala ni tamaño de componentes.

Cambio acotado: usar int32 para ese cálculo. No se ensanchó la máscara para
aumentar su área ni se recuperó el fondo exterior. Casos 06/07 A/B conservan el
rosa y la franja; la esquina exterior permanece transparente.

En A, IoU de máscara sintética pasa de 0,0443 a 1,0. En B pasa de 0,0332 aprox.
a 0,8887: conserva el pigmento, pero el hueco opaco del fondo cerrado sigue
ambiguo para la extracción exterior. No se presenta B como segmentación perfecta.

Prueba: `test_vv01_saturated_regions_survive_background_removal`, cuatro casos;
comprueba región rosa, fondo excluido, conservación >99 % de foreground conocido
y fuente sin modificar.
[Antes/después 06-A](../artifacts/sticker-corrections-release/before_after/06-A.png).

## VV-02 — Huecos y alfa parcial, P1

**Causa confirmada:** la política previa completaba huecos del PNG con blanco en
el propio diseño. La ruta B también reconstruía interiores. La base física y la
imagen visual se estaban confundiendo. No era un problema de jerarquía perdida
al exportar vectores: el relleno ocurría antes de guardar el alfa editable.

Cambio: invocar A sin relleno y conservar el alfa fuente fiable después del
despacho A/B, antes de protección y renderizado. No se aplica este reemplazo a
una máscara manual ni al modo de imagen completa. El RGB oculto se limpia con
el mecanismo existente. Si el sticker ya tiene borde blanco, se conserva su
indicación para no añadir otra corona en el nativo.

01-B, 02-B, 13-B y 14-B conservan su máscara visual, incluyendo alfa parcial,
con IoU 1,0. Las dos ejecuciones de cada regresión comparan el alfa fuente y el
editable; la base blanca sigue sólida y el corte sigue exterior. No se genera
automáticamente un corte interior porque el diseño tenga un hueco.

Prueba nueva parametrizada: `test_vv02_visual_alpha_holes_and_partial_alpha_survive_reprocess`.
Se actualizó la prueba histórica que **exigía** rellenar huecos: se cambió su
contrato por el nuevo requisito explícito del usuario, no para ocultar un fallo.
Ahora exige transparencia en diseño y blanco sólido en la base física por separado.
[Antes/después 01-B](../artifacts/sticker-corrections-release/before_after/01-B.png).

## VV-03 — Fondos variables, P1 abierto

**Causa confirmada a nivel de etapa:** el tratamiento directo de PNG opaco usa
extracción conectada por neutros/distancia al fondo, suficiente para el lienzo
uniforme pero no para representar las bandas de un degradado/textura. El fondo
residual ya está en la máscara extraída, antes del postprocesado. No se arregla
con expansión, suavizado ni copiando esa máscara como si fuera una corrección.

No se reemplazó la segmentación ni se forzó otra ruta. Se añadió advertencia
específica cuando el perímetro RGB varía ampliamente, excepto damero identificado.
Es una señal conservadora, no un clasificador semántico. Puede detectar también
un objeto que toca el marco: solicita revisión, no elimina ese objeto.

Durante la comprobación apareció un efecto secundario: la recuperación podía
copiar la misma máscara sin el contexto de fondo variable y considerarla mejor
por tener menos advertencias. Se añadió una guarda para no intentar esa falsa
mejora. El resultado mantiene el aviso y la ruta, sin bucles ni reemplazo manual.

Prueba: `test_vv03_complex_background_remains_explicitly_unresolved`, que exige
advertencia, marca persistente y ausencia de recuperación engañosa. NO comprueba
ni afirma fondo correctamente eliminado. Los seis casos 08/09/15 A/B siguen
visualmente incorrectos y necesitan corrección manual/evaluación independiente
de segmentación con referencias reales. Un cambio general de segmentación no
sería una corrección acotada y segura demostrada por este banco.
[Caso aún abierto 15-B](../artifacts/sticker-corrections-release/before_after/15-B.png).

## VV-04 — Extremos aplanados del nativo pequeño, P1

**Causa confirmada por intervención controlada:** el cierre morfológico de la
base operaba junto al límite del raster de 130×130 y su condición de borde
producía mesetas. No hacía falta reducir más la simplificación ni ampliar el diseño.

Cambio: construir y suavizar la base en un raster temporal con padding cero,
al mismo DPI, y recortar después a las dimensiones originales de salida. No se
amplía la fuente, no cambia su colocación ni el tamaño físico del perfil. La
misma corrección evita propagar el aplanamiento al corte contraído desde la base.

Prueba: `test_vv04_selected_small_object_does_not_flatten_at_canvas_boundary`.
Comprueba que base/corte no toquen el marco superior/inferior, que la punta sea
más estrecha que el centro y que los IDs 1/2/3 permanezcan estables. Los escalones
de un raster pequeño no se presentan como un defecto resuelto de detalle inventado.
[Antes/después del objeto](../artifacts/sticker-corrections-release/before_after/mode-objects-selected.png).

## VV-05 — Disco sobre damero, P1 parcialmente mitigado, abierto

La evidencia sitúa la irregularidad en la máscara de extracción exterior: una
franja de captura queda retenida y forma parte del borde/base. Se probó el
refinamiento GrabCut ya existente; reemplazar toda la máscara elimina aproximadamente
6,8 % del área y no hay alfa real de referencia para garantizar qué partes de
blanco/metal pertenecen al diseño. Se rechazó ese reemplazo general como solución.

Se reutilizó el refinamiento **solo en la corona incierta de hasta dos píxeles**
del damero neutro (no en el corazón cromático). No puede añadir fondo ni sustituir
el interior de la bola/estrellas. No se borran componentes por su tamaño en este
paso. La máscara manual no pasa por esta ruta.

Prueba: `test_vv05_checker_cleanup_cannot_erase_silver_or_star_cores` comprueba
conservación >99,9 % del interior seguro y exclusión del damero exterior. Es una
prueba de seguridad, **no una certificación de contorno perfecto**.
El borde queda más limpio, pero aún tiene irregularidades, especialmente junto
a adornos inferiores. Se mantiene P1 abierto; ampliar erosión o borrar estrellas
para alisar la silueta dañaría contenido legítimo.
[Disco antes/después](../artifacts/sticker-corrections-release/before_after/04-B.png).

## VV-06 — Halo gris, P2 pendiente

La línea está incorporada en el RGB de la fuente de labios y de las sondas de
sombra. La exclusión exterior no puede distinguir con certeza una sombra del
gris intencional de un arte plateado. Se revisaron blanco, negro y zoom: permanece
visible. No se extendió el blanqueo ni la erosión a todos los píxeles del borde.
Debe resolverse con evidencia localizada/edición, no a costa de acuarelas o metal.
No se añadieron pruebas que finjan eliminarlo.
[Labios](../artifacts/sticker-corrections-release/before_after/05-B.png).

## VV-07 — Orientación, P2 pendiente de intención

La causa no es deformación: la normalización de producción existente gira a
vertical cuando ancho/alto >=1,20 y `preserve_orientation` es falso. Hay parámetro
para preservar la orientación en operaciones explícitas, pero esta fase no
rediseña su exposición en la interfaz ni cambia la política general. Las
proporciones se mantienen. Se deja pendiente aclaración/revisión humana de uso.
[Imagen completa](../artifacts/sticker-corrections-release/before_after/17-A.png).

## VV-08 — Corte manual fuera de base, P1

**Causa confirmada:** se comprobaban dimensiones, contenido y degeneración del
corte, pero no su contención respecto de la base imprimible.

Cambio: control aditivo cuando hay corte manual, alineado al maestro. Se admite
una tolerancia de un píxel por discretización (no recalibración física). Píxeles
de corte fuera de esa base generan `cut_outside_base` en errores. El bloqueo de
confirmación ya existente consume esos errores; no se modificó aprobación/UI.

El ensayo manual deliberadamente inválido ahora termina el cálculo pero queda
en ERROR. No se recorta ni sobrescribe su máscara. El nativo de diseño coincide
byte a byte con el resultado sin cambio de corte. Un corte válido interior no se
rechaza. Se mantienen las dos pruebas, válida e inválida, y el archivo fuente.
[Corte manual antes/después](../artifacts/sticker-corrections-release/before_after/mode-independent-cut.png).

## Integridad y efectos secundarios

Archivos modificados en esta fase:

- `app/stickers/pipeline.py`: aritmética segura, huecos visuales, borde existente,
  refinamiento restringido de damero y aviso/metadata de fondo variable.
- `app/stickers/resolution.py`: padding temporal para base/corte nativos.
- `app/stickers/quality.py`: contención del corte manual con error verificable.
- `app/stickers/recovery.py`: no borrar contexto de una extracción compleja fallida.
- `tests/test_sticker_visual_corrections.py`: trece casos de regresión nuevos.
- `tests/test_sticker_creator.py`: contrato explícito hueco visual/base blanca.
- `scripts/validate_sticker_visuals.py`: comparativas de dos ejecuciones, separadas
  de los artefactos productivos, sin sobrescribir el banco anterior.
- Informes de validación/correcciones y evidencia nueva.

No se tocaron pedidos, DB, planchas, catálogo, perfiles ni calibraciones. Tampoco
se cambió la lógica de clasificación para ocultar resultados adversos. Las rutas
registradas y los tipos coinciden en las 44 comparaciones finales. La ruta D
continúa sin cobertura visual real en este banco; la suite conserva sus contratos.

Efectos que requieren revisión: nativos con pequeñas diferencias de base en el
marco; alfa de PNG con huecos ahora respeta diseño en vez del relleno histórico;
la comprobación de corte puede bloquear ediciones antes admitidas; GrabCut añade
trabajo en dameros neutros pero su intervención final está limitada a la corona.
El padding temporal consume memoria adicional. No se afirma rendimiento/RAM
certificados para imágenes grandes. La advertencia de fondo variable es heurística.

Las máscaras manuales, sus huecos y el corte editado se conservan sin reescribir;
los dos ensayos de reprocesamiento manual guardan el mismo alfa. Los resultados
anteriores se mantienen intactos en v3: no se migraron ni se regeneraron en su lugar.

## Ejecución de pruebas

Banco definitivo: **44 COMPLETED, 0 excepciones**, 43 REVISAR y 1 ERROR esperado
por corte manual fuera de base. Las 18 hojas fueron regeneradas y examinadas;
las comparativas finales solo difieren de la pasada verificada en 02-A/B por la
protección contra borde blanco duplicado, que se revisó de nuevo.
Tiempo agregado de casos y diagnóstico: 20,76 s, no benchmark de fotografías/IA.

Se ejecutaron 59 pruebas focalizadas antes de los últimos guardas; pasaron con
tres subtests. Las trece regresiones nuevas también pasaron por separado (7,82 s)
antes del último ajuste de borde. La suite definitiva sobre todos los ajustes
terminó con **1073 passed, 1 skipped, 4 warnings, 5 subtests passed**, salida 0,
209,40 s. Incluye las cuatro pruebas de la herramienta visual y las trece nuevas
regresiones de esta fase en una única ejecución completa.
[JUnit definitivo](../pytest-visual-corrections-release-results.xml).
La omisión sigue correspondiendo a los archivos externos shield1…shield5 ausentes.
Las cuatro advertencias son PytestReturnNotNoneWarning históricas; no se cambiaron
sus expectativas. No se cuentan como aprobadas las pasadas completas intermedias
interrumpidas para incorporar correcciones. Compilación Python de los módulos
modificados correcta; verificación de vínculos de las 44 vistas y 18 hojas correcta.

Comando de la suite definitiva:

```powershell
python -m pytest -q --basetemp=pytest-visual-corrections-release-temp --junitxml=pytest-visual-corrections-release-results.xml -o cache_dir=pytest-visual-corrections-release-cache
```

Para repetir el banco usar siempre un directorio NUEVO:

```powershell
python -m scripts.validate_sticker_visuals --output artifacts/sticker-corrections-nueva
python -c "from scripts.validate_sticker_visuals import compare_runs; compare_runs('artifacts/sticker-visual-v3','artifacts/sticker-corrections-nueva')"
```

## Preparación y cierre

Todos los resultados siguen pendientes de aprobación visual humana. Revisar
especialmente la diferencia máscara visual/soporte blanco, el borde existente,
la bola disco, halo gris, líneas finas y los fondos complejos explícitamente fallidos.
Las alternativas no equivalen a aprobaciones. Ninguna salida se publicó durante
esta fase. Primero resolver VV-03/VV-05 con referencias suficientes o corrección
manual controlada; después completar las muestras reales y validar en sesión nueva.

El criterio de seis P1 corregidos **no se cumple**: hay dos abiertos documentados.
Se detuvieron las correcciones de alcance amplio/incierto y se completaron los
casos independientes, tal como autoriza la solicitud. Pendientes ambos P2 y las
pruebas físicas con Epson L3210/Brother ScanNCut X225. No se imprime ni se corta
con la pretensión de que esta suite sustituya mediciones reales.

## Continuación de cierre focalizado — 2026-10-17

### Estado individual actual

| Defecto | Estado | Alcance de la conclusión |
|---|---|---|
| VV-03, P1, fondo variable | Corregido en las seis sondas reproducidas; revisión humana pendiente | Propuesta local estable, IoU 1,0 contra máscaras sintéticas y revisión visual; no certifica fotografías reales |
| VV-05, P1, disco | ABIERTO, última máscara estable conservada | Limpieza ampliada rechazada por regresión; alternativa persistida sin seleccionarla |
| VV-06, P2, halo gris | PENDIENTE justificado | Sigue mezclado con el borde RGB original; no se amplió blanqueo/erosión arriesgados |
| VV-07, P2, orientación | PENDIENTE de intención | Se conserva la política vertical existente; no es deformación ni se cambió calibración |

Balance del banco: cinco de los seis P1 iniciales corregidos en los casos
reproducidos, **un P1 aún abierto**. El objetivo de cero P1 NO se alcanzó.
Los P2 no se modificaron: la solicitud condiciona su corrección a estabilizar
ambos P1, y el disco no pudo corregirse de forma segura.

### Auditoría y corrección de VV-03

Casos exactos: 08-A/B, 09-A/B y 15-A/B. Tipo principal detectado: `fondo_color`;
ruta registrada C. La extracción por neutros/distancia retenía bandas del fondo
antes de cualquier normalización, borde o corte. Las variantes B también retenían
fondo dentro del hueco. No era pérdida causada por reducción de resolución.

Se contrastó la segmentación local que ya existe en `_segment_ia` y la rutina
GrabCut existente `_refine_checkerboard_alpha`, que admite semillas de fondo.
Ambas separaron las sondas sin modelos nuevos. Se reutilizó la segunda rutina
para no entrar en la cascada que podría cargar rembg si un motor falla. La ruta
D y sus métodos no se modificaron ni se forzó D en el clasificador.

`background_refinement.variable_background_proposal` ejecuta ese mecanismo con
dos márgenes de semilla independientes y exige IoU >=0,995, área no vacía/no
dominante, resultado no rectangular y ausencia de contacto del resultado con el
marco. Si hay desacuerdo o fallo se conserva la extracción inicial y las dos
candidatas, con `manual_required`. Si hay acuerdo se presenta la propuesta local
con `proposal_requires_review`, nunca como aprobación automática. La advertencia
de fondo variable permanece y la recuperación no la elimina como falsa mejora.

Las máscaras se guardan en resolución fuente: `background_initial_alpha`,
`background_candidate_1` y `background_candidate_2`. No se sobrescriben originales,
resultados previos ni decisiones manuales. Las zonas protegidas siguen aplicándose
después de proponer la máscara. La propuesta aceptada no atraviesa la eliminación
de componentes por tamaño; conserva su hueco y el apéndice fino en B. La base
física sigue sólida, independiente de los huecos del diseño.

Los umbrales son guardas técnicas, **no confianza semántica calibrada**. El acuerdo
entre dos semillas no demuestra que todo sujeto real esté bien separado. Las
semillas presuponen fondo en el marco: fotos con sujetos cortados, colores
compartidos, pelo o transparencias suaves requieren revisión/corrección manual.
El indicador `complex_background_unresolved` permanece verdadero para exigir
revisión, aunque la propuesta se vea correcta en las sondas. No se presenta el
placeholder de fotografía como una fotografía real validada.

Resultado: los seis casos pasan de IoU 0,361–0,432 a **1,0** en la máscara visual
sintética, sin rellenar huecos ni perder el apéndice. Se examinaron las tres hojas
08/09/15 y sus fondos blanco/negro/damero y zooms. No se observó un halo nuevo en
esas sondas; no es garantía para bordes fotográficos mezclados con el fondo.
Las seis entradas reutilizan dos variantes sintéticas en tres categorías: no son
seis fotografías o diseños complejos independientes. El cierre se limita a esas
sondas reproducidas; falta diversidad real antes de extrapolar el resultado.

### VV-05: experimento rechazado y reversión específica

Caso: 04-B, `disco_checker.png`, tipo `damero_incrustado`, ruta C. Se inspeccionaron
original, alfa, componentes conectados, base blanca, corte y nativo por separado.
La extracción inicial por tonos neutros conserva 169 componentes; la franja de
captura y blancos retenidos participan en la silueta y amplifican irregularidades.
El refinamiento GrabCut completo reduce a dos componentes, pero retira 6181 píxeles
(aproximadamente 6,8 % de la máscara), todos neutros claros; gran parte son blancos
253–255 y pueden incluir borde intencional. Su profundidad respecto del borde
alcanza unos 16 px. No hay alfa real aprobado que distinga inequívocamente todos
esos blancos de la captura. No se atribuye la irregularidad a una esfera imperfecta
ni se ajustó una circunferencia o un casco convexo.

Se ensayó quitar únicamente neutros claros exteriores, preservando una corona
de dos píxeles alrededor de la segmentación. El resultado modificó el borde blanco
y dejó uniones escalonadas: la prueba de conservación del núcleo existente bajó
a 0,96968, por debajo de >0,999 exigido. **No se aceptó ni se cambió la expectativa
de la prueba.** Se revirtió exclusivamente ese cambio y se retiró su helper del
código final, manteniendo el refinamiento estable de dos píxeles anterior.

La corrida experimental se conserva en `artifacts/sticker-closure-probe1/`;
**no usarla para producción**. El nativo/máscara/corte finales del disco son
idénticos a los de la última versión estable. Ahora también se conservan
`checkerboard_initial_alpha` y `checkerboard_segmentation_candidate` como
evidencia para revisión; `checkerboard_review.wider_candidate_selected=false`
deja explícito que no se seleccionó el candidato amplio.

Para cerrar este P1 hace falta una máscara revisada del borde legítimo, especialmente
entre esfera y estrellas y en adornos inferiores, o una referencia con alfa real.
Sin esa información no es seguro aumentar la limpieza automática. No se borran
adornos por tamaño ni se inventa el contenido que quedaría debajo del borde.

### Pruebas específicas y protección de los casos anteriores

Se añadieron trece casos en `tests/test_sticker_visual_closure.py`:

- Seis casos de fondos variables: conservación de foreground, hueco y detalle
  fino, exclusión de fondo, máscaras candidatas en resolución fuente, metadata
  reabierta y archivo original sin modificar.
- Desacuerdo entre propuestas: exige revisión manual y conserva ambas.
- Fallo que devuelve la semilla rectangular: no se admite como una silueta válida.
- Dos casos de protección: alfa manual parcial con hueco y modo imagen completa
  no invocan la propuesta automática.
- Cancelación entre propuestas: elimina solo la corrida nueva, conserva la previa.
- Reprocesamiento: conserva geometría y metadata anterior sin sobrescribir.
- Disco: conserva propuesta amplia separada, máscara estable y referencias al reabrir.

No se modificaron expectativas de pruebas existentes. La prueba del disco que
falló durante el experimento sigue intacta y obliga a conservar la última versión
segura. Las 71 regresiones focalizadas pasaron después de la reversión y antes
de añadir la última prueba de persistencia del candidato del disco.

Suite completa definitiva de esta continuación, incluyendo las trece pruebas nuevas:
**1086 passed, 1 skipped, 4 warnings, 5 subtests passed**, salida 0, 251,45 s.
La única omisión sigue siendo el banco externo shield1…shield5 no disponible;
las cuatro advertencias son PytestReturnNotNoneWarning históricas. No se cambiaron
expectativas para ocultarlas ni se aceptó el fallo experimental del disco.
[JUnit de esta continuación](../pytest-sticker-closure-final-results.xml).

```powershell
python -m pytest -q --basetemp=pytest-sticker-closure-final-temp --junitxml=pytest-sticker-closure-final-results.xml -o cache_dir=pytest-sticker-closure-final-cache
python -m scripts.validate_sticker_visuals --output artifacts/sticker-closure-nueva
python -c "from scripts.validate_sticker_visuals import compare_runs; compare_runs('artifacts/sticker-corrections-release','artifacts/sticker-closure-nueva')"
```

Para reproducir usar carpetas nuevas: los nombres anteriores ya contienen
evidencias. Compilación Python de los módulos modificados correcta. Verificadas
las rutas de las 44 vistas, las 18 hojas y los dos candidatos de disco persistidos.

### Evidencia final y alcance de la revisión

- [Manifiesto final, 44 casos](../artifacts/sticker-closure-final/manifest.json).
- [Comparación contra la última versión estable](../artifacts/sticker-closure-final/before_after/comparison.json).
- [Fondo complejo B antes/después](../artifacts/sticker-closure-final/before_after/15-B.png).
- [Disco antes/después, máscara estable conservada](../artifacts/sticker-closure-final/before_after/04-B.png).
- [Registro actualizado de revisión](../artifacts/sticker-closure-final/visual-review.json).

Se repitieron las 44 ejecuciones y regeneraron las 18 hojas. Resultado técnico:
44 COMPLETED, 0 excepciones, 43 REVISAR y el ERROR esperado del corte manual
deliberadamente inválido. Fuentes, etiquetas y rutas coinciden en las 44
comparaciones con la versión estable; todos los hashes fuente permanecen intactos.
Solo cambian seis comparativas visuales: 08/09/15 A/B. Las otras 38 comparativas,
incluidos corazón, labios, disco y modos manuales, son idénticas byte a byte.
Tiempo agregado de casos/diagnóstico: 40,589 s; incluye propuestas dobles y carga
de pruebas simultánea, no es un benchmark aislado ni de fotografías reales.

Se examinaron visualmente las seis sondas modificadas, el disco y labios finales,
y las evidencias del experimento descartado. Las comparativas no modificadas
conservan la inspección de la fase anterior y su identidad se comprobó por bytes;
no se afirma una nueva aprobación humana de las 18 hojas. Ningún resultado se
confirmó o publicó; los 44 siguen pendientes de revisión humana.

### Archivos de esta continuación

- `app/stickers/background_refinement.py`: guardas para reutilizar segmentación
  local existente, sin nuevos modelos ni dependencias.
- `app/stickers/pipeline.py`: integración limitada al PNG opaco con fondo variable,
  persistencia de alternativas, advertencia de revisión y evidencia del disco
  sin sustituir su máscara estable.
- `tests/test_sticker_visual_closure.py`: trece regresiones nuevas.
- Este informe y las carpetas de evidencia nuevas, sin sobrescribir las anteriores.

No se editaron A/B/C/D, clasificación, perfiles físicos, planchas, pedidos,
persistencia de IDs ni calibraciones. El camino de segmentación de D permanece
intacto; se reutiliza un helper local desde el tratamiento de PNG opaco. No se
agregaron dependencias. Hay coste adicional de dos GrabCut para fuentes variables;
una operación nativa en curso no se cancela hasta que retorna, pero se comprueba
cancelación entre propuestas. No se promete memoria/latencia ilimitadas.

### Conclusión de seguridad de esta continuación

VV-03 ya no es reproducible en las seis sondas del banco, con las limitaciones
indicadas. **VV-05 continúa abierto.** Se aplicó la condición de seguridad del
pedido: rechazar regresión, revertir el cambio y conservar la versión estable.
VV-06/VV-07 siguen pendientes con la justificación anterior. La fase no cumple
cero P1 y no se declara cerrada ni lista para producción. El siguiente paso del
disco necesita decisión humana sobre la máscara/borde legítimos; las pruebas
físicas Epson L3210 y Brother ScanNCut X225 siguen pendientes.

## Cierre controlado con referencia humana — 2026-10-17

**VV-05: PENDIENTE DE REVISIÓN HUMANA.** Se detuvo la corrección automática del
defecto porque no hay referencia alfa validada. No se modificaron algoritmos ni
se volvió a aplicar la propuesta amplia rechazada. VV-06/VV-07 permanecen abiertos.

### Búsqueda de referencia original

Se revisaron 663 imágenes en `tests/fixtures`, `corrected_stickers`,
`work/stickers/inbox` y `assets`. La comparación visual/perceptual encontró la
fuente de 421×421 y dos copias del mismo diseño de 600×600, pero las tres son
opacas: alfa mínimo/máximo 255/255. También se contrastaron por características
locales las 36 imágenes con transparencia no vacía de esas carpetas: no apareció
una coincidencia del disco con alfa real. No se atribuye carácter de original
a resultados alfa generados por el propio pipeline. La búsqueda es local y
acotada: no demuestra que no exista otra versión fuera de esas ubicaciones.

Las dos copias de apoyo son `pegado_20261017_170013.png` y
`pegado_20261017_171639.png` en inbox; tienen el mismo SHA-256. Se inspeccionaron
visualmente y su correspondencia geométrica con el disco se comprobó con 903
coincidencias ORB, 743 inliers de transformación afín parcial y error mediano
0,611 px en coordenadas de la fuente. Eso acredita el mismo diseño visual, **no
un alfa aprobado ni alineamiento exacto de borde**. La copia clara de 600×600
queda como apoyo para una persona, sin convertirla automáticamente en máscara.

### Entrega para revisión

- [Procedimiento completo de máscara manual](STICKER_DISC_REFERENCE_REVIEW.md).
- [Comparativa original/propuesta/desacuerdo](../artifacts/sticker-disc-human-review/review_comparison.png).
- [Auditoría de búsqueda y correspondencia](../artifacts/sticker-disc-human-review/search_audit.json).
- [Paquete y regiones localizadas](../artifacts/sticker-disc-human-review/packet.json).
- [Declaración pendiente, no aprobada](../artifacts/sticker-disc-human-review/approval_PENDING.json).

El paquete contiene el original exacto de **421×421**, una copia de apoyo opaca,
la propuesta automática claramente rotulada como NO referencia y el candidato
descartado separado. Hay seis regiones de desacuerdo y ampliaciones 200 %.
Magenta significa desacuerdo entre algoritmos, NO error confirmado. No se creó
`mask_reviewed.png`, no se marcó ninguna referencia aprobada y no se calcularon
métricas reales contra una referencia inexistente.

Una persona debe trazar o revisar toda la máscara visual en coordenadas fuente,
conservar las estrellas, facetas y reflejos, decidir qué borde blanco es legítimo,
preservar huecos solo con evidencia y revisar antialiasing sobre varios fondos.
El protocolo permite un borrador desde la edición existente, pero prohíbe asumir
que ese borrador automático es correcto. También explica cómo empezar una máscara
nueva, guardar la corrección separadamente y conservarla al reprocesar.

Los reflejos y las facetas angulares son contenido válido; las puntas de estrellas
son silueta deliberada. El contorno irregular ya aparece en el alfa fuente antes
del render nativo y llega a base/corte, por lo que la etapa problemática sigue
siendo extracción/limpieza de máscara, no un supuesto círculo imperfecto ni la
calibración física. No se pueden decidir con certeza todos los píxeles blancos
fronterizos sin referencia revisada. Se mantiene esa limitación, en vez de borrar
blancos o pequeñas piezas por criterio global.

### Comparación preparada, condicionada a aprobación humana

`scripts/sticker_reference_review.py` prepara el paquete y compara únicamente
cuando existe una declaración explícita de aprobación con revisor, fecha con
zona horaria, hash de fuente, hash de máscara y dimensiones exactas. Rechaza
referencias pendientes, vacías, ajenas, alteradas o desalineadas; no las reescala.
Es un registro local de revisión, no un sistema de autenticación criptográfica.

Después de una revisión válida generará IoU, error de alfa, pérdida/exceso,
diferencias de alfa parcial, precisión/recall de contorno a 1 px, distancias
simétricas p95/máxima y mapas/regiones ampliadas. Esto evita esconder pérdida de
un detalle fino detrás de una buena métrica global. La comparación **no se
ejecutó sobre el disco real**: falta la aprobación/máscara de una persona.

No se adoptó ninguna corrección focalizada de producción sin ese dato. El flujo
existente `open_mask` usa `mask_editable` con `source_editable`; guarda corrección
manual separada y `_reprocess_edited_mask` conserva su ruta para el reprocesado.
La máscara visual no se confunde con la base imprimible ni con el corte nativo.

### Regresión e integridad

Suite completa de aplicación: **1086 passed, 1 skipped, 4 warnings,
5 subtests passed**, salida 0, **247,88 s**.
[JUnit](../pytest-disc-review-final-results.xml).
La omisión sigue siendo el conjunto externo shield1…shield5 ausente y los cuatro
warnings son los PytestReturnNotNoneWarning históricos.

Las seis pruebas nuevas de la herramienta se añadieron después de recolectar
esa suite y se ejecutaron aparte: **6 passed**, 0,45 s. No se presenta la suma
como una única ejecución de 1092 pruebas. Comprueban que no se fabrica referencia,
que una aprobación pendiente no produce métricas, que errores locales diminutos
se exponen aunque IoU sea alto, y que hashes/dimensiones/fuente ajena se rechazan.
Las declaraciones aprobadas usadas por esos tests son **sintéticas y temporales**,
no aprobaciones del disco real. Compilación Python de los nuevos archivos correcta.

Se repitieron las 44 ejecuciones estables, incluidas disco, corazón, labios,
fondos complejos, bordes, alfa parcial, máscaras manuales, resolución y persistencia;
se regeneraron sus 18 hojas. Todas las comparativas son idénticas byte a byte a
la pasada estable, sin cambios en rutas, tipos o hashes fuente. Los tests actuales
de preservación manual, nativos y persistencia se conservan en la suite completa.

- [Manifiesto de comprobación](../artifacts/sticker-disc-controlled-final/manifest.json).
- [Comparaciones contra la versión estable](../artifacts/sticker-disc-controlled-final/before_after/comparison.json).

Solo se inspeccionaron visualmente en esta fase el paquete del disco, sus apoyos
claros y las evidencias previas. La identidad de las otras vistas es comprobación
automatizada, no una nueva aprobación visual humana. Resultado de ejecución:
44 COMPLETED, 43 REVISAR y el ERROR esperado del ensayo de corte manual inválido;
tiempo agregado 34,892 s. Ningún resultado se publicó.

Archivos añadidos: `scripts/sticker_reference_review.py`,
`tests/test_sticker_reference_review.py`, `docs/STICKER_DISC_REFERENCE_REVIEW.md`
y el paquete de revisión/evidencias. Se actualizó este informe. **No se editaron
pipeline, editor, A/B/C/D, clasificación, pedidos, planchas, calibraciones ni
resultados previos en esta fase.**

El siguiente paso requiere una persona: guardar y aprobar una máscara revisada
de 421×421, o aportar la versión correspondiente con alfa real. Hasta entonces
VV-05 sigue pendiente y se detiene su corrección automática. Dos P2 siguen
registrados. El módulo no se declara listo para producción.

### Aclaración visual y plantilla manual de la referencia

La nueva indicación del usuario confirma que **esfera, cuatro estrellas, borde
blanco y conexiones legítimas** son contenido válido. Se incorporó esa intención
al procedimiento sin tratar reflejos como damero ni eliminar adornos pequeños.
El envío contenía únicamente texto: no se recibió una nueva imagen alfa.
El fixture conserva damero exterior incrustado; la copia de apoyo de 600×600
conserva fondo claro uniforme. No se modificó su clasificación histórica para
confundir el patrón interior de espejos con el fondo del marco.

Se añadió `artifacts/sticker-disc-human-review/manual_reference_TEMPLATE_NOT_MASK.svg`,
un documento 421×421 con imagen guía y capa de trazado vacía. Es preparación
para edición manual, **no máscara de referencia ni segmentación automática**.
No se crearon contornos supuestamente correctos, alfa aprobado ni aprobación
humana. El procedimiento explica ocultar la guía, exportar a dimensiones exactas
y revisar los cuatro adornos, el borde, entrantes y antialiasing antes de aprobar.
Las vistas de la referencia solicitadas quedan condicionadas a ese trazado real;
no se presentan las propuestas automáticas como resultados de referencia.

No hubo cambios en el pipeline, calibraciones ni expectativas de tests en esta
actualización documental. VV-05 continúa **pendiente de revisión humana**, los
dos P2 siguen registrados y no hay declaración de producción lista.

### Validación real del nuevo módulo de halo gris — 2026-10-19

Se ejecutó el original real 421 × 421, SHA-256
`0d84cf0c255870106b608ad18d3819c6aae187d3bec5caca45ce31e50c968221`,
sin cambiarlo ni forzar su clasificación. **Validación NO superada**:
la ruta C no llama al módulo nuevo (reservado a B con halo). El ensayo aislado
con el alfa real no detecta halo, no contrae y agrega 30 px de blanco sobre el
borde existente. Las evidencias distinguen explícitamente pipeline y módulo
aislado. La salida nativa real es 436 × 436 a 194,29 DPI sin reescalar el diseño;
la extracción alineada 421 × 421 no se etiqueta como maestro final aprobado.

Suite completa: **1099 passed, 1 skipped, 4 warnings, 5 subtests passed**,
217,64 s, salida 0. Frente a 1086: seis tests de referencia y siete sintéticos
de halo adicionales, ya existentes. Persisten la omisión shield1…shield5 y
las cuatro advertencias de retornos en tests. Las 44 ejecuciones visuales se
regeneraron: mismas fuentes/rutas/tipos y 132/132 artefactos máscara/maestro/corte
idénticos a la última referencia estable. No se detectaron regresiones que
requirieran revertir; tampoco se considera esto validación del módulo nuevo.

Informe: [STICKER_GREY_HALO_REAL_VALIDATION.md](STICKER_GREY_HALO_REAL_VALIDATION.md).
Evidencias: `artifacts/sticker-halo-real-20261019-v2/`; regresión:
`artifacts/sticker-halo-regression-20261019/`; JUnit:
`pytest-halo-real-20261019-results.xml`.
Se añadió únicamente el script de auditoría `scripts/validate_real_disc_halo.py`
y el informe, además de esta actualización y evidencias. Sin cambios en
algoritmos, rutas ni calibraciones. **VV-05 sigue abierto, pendiente de referencia
humana aprobada y corrección controlada de integración/borde.** Los dos P2 y
las validaciones físicas siguen pendientes; producción no aprobada.

### Integración complementaria corregida, sin cierre visual del P1

El disco real ya atraviesa una vez la evaluación común de halo manteniendo C.
La etapa no genera blanco, sólo admite eliminación localizada de regiones
identificadas y no modifica el caso ambiguo de damero: `manual_required`.
La API aislada deja de sumar automáticamente 30 px al aro existente; se detectan
también aros estrechos con alfa fiable, sin cambiar la clasificación técnica.
Una recuperación automática no puede ocultar la nueva advertencia de revisión.

Se añadieron 13 pruebas de integración y se conservaron siete del módulo
(20 aprobadas en la ejecución focal). En las 44 ejecuciones visuales definitivas,
132/132 máscaras/maestros/cortes coinciden byte a byte con el baseline:
sin nuevas pérdidas, mismas fuentes/rutas/tipos. La candidata humana no se
usó como referencia aprobada. El disco mantiene maestro nativo 436 × 436,
fuente/alfa editable 421 × 421, 194,29 DPI, borde nuevo 0 px; no se inventó detalle.

Evidencia: `artifacts/sticker-halo-integrated-evidence-final/`.
Regresión: `artifacts/sticker-halo-integrated-release-regression/`.
El informe principal `STICKER_GREY_HALO_REAL_VALIDATION.md` contiene las causas,
guardas, archivos modificados y resultados reales de suite, incluido el diagnóstico
Tcl/Tk. **Integración corregida no significa P1 visual resuelto ni producción
aprobada.** La referencia humana, las dos P2 y las pruebas físicas siguen pendientes.

Suite final en serie: **1111 aprobadas, una fallida, una omitida, cuatro
advertencias y cinco subtests aprobados**, 233,10 s, salida 1. La fallida es
`test_area_selection_draw_and_confirm`: no puede cargar `tk.tcl` al crear Tk;
el test aislado pasa, pero el fallo de la suite completa permanece registrado.
La suite **no se declara verde**. JUnit: `pytest-halo-integrated-serial-results.xml`.
La corrección del halo no cierra este pendiente de entorno ni habilita producción.
