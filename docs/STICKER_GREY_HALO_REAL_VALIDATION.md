# Validación real del nuevo procesamiento de halo gris — 2026-10-19

## Dictamen inicial (antes de la corrección de integración)

**NO VALIDADO. VV-05/P1 pendiente de revisión humana; producción NO aprobada.**
Se ejecutó el pipeline real, sin forzar clasificación ni sustituir el original.
No se modificaron los algoritmos de producción, las rutas A/B/C/D ni las
calibraciones. No se fabricó ni aprobó una máscara de referencia.

## Fuente y reproducibilidad

- Fuente: `artifacts/sticker-disc-human-review/original.png`.
- 421 × 421; alfa original `(255,255)`: el damero exterior está incrustado.
- SHA-256: `0d84cf0c255870106b608ad18d3819c6aae187d3bec5caca45ce31e50c968221`.
- Inspección visual: esfera, cuatro estrellas, borde blanco y damero exterior.
- Fuente intacta después de las dos ejecuciones.
- Script nuevo: `scripts/validate_real_disc_halo.py`. Instrumenta temporalmente
  el proceso dentro de su propio intérprete, captura los estados reales y restaura
  el observador al terminar. No parchea los archivos de producción.
- Ejecución definitiva:
  `python -m scripts.validate_real_disc_halo artifacts/sticker-halo-real-20261019-v2`.
  La primera ejecución se conserva en `artifacts/sticker-halo-real-20261019`;
  v2 añade ampliaciones de estrellas y conexiones y trazado independiente de líneas fijas.

## Fallos comprobados

1. **Integración:** el disco toma `C - Fondo de color uniforme`. El módulo nuevo
   se habilita exclusivamente para B con `has_grey_border`. La instrumentación
   registró **cero llamadas** al módulo durante el pipeline completo.
2. **Ensayo aislado, no confundido con pipeline:** sobre la imagen y alfa
   capturados antes del tratamiento de halo, el módulo informa `halo_detected=false`,
   `grey_ratio=0`, contracción 0 y cero píxeles eliminados. La máscara denominada
   limpia en este ensayo permanece igual: NO demuestra limpieza.
3. **Acumulación de blanco:** aun sin detectar halo, el módulo aislado dilata
   30 px el alfa que ya conserva el borde blanco. La comparativa sobre magenta
   muestra una franja desproporcionada, conexiones engrosadas y margen próximo
   al límite del lienzo. No cumple «un único borde blanco limpio».
4. **Contracción no localizada:** la implementación actual usa erosión global
   de la silueta, no una máscara limitada a los píxeles contaminados. Su umbral
   de preservación de área es 0,15: conservar apenas 15 % del área podría pasar
   esa barrera. `safe_to_contract` no se consulta. No es garantía de puntas,
   semitransparencias o conexiones legítimas. Este riesgo se comprobó en código;
   no se forzó una contracción destructiva sobre el original.

No se observó pérdida del contenido de las cuatro estrellas en la propuesta
del pipeline a esta escala. Sí se aprecian escalones/irregularidades en el margen
y conexiones, especialmente alrededor de la estrella pequeña. Sin referencia
humana alineada no se puede asignar cada píxel gris a contaminación o diseño,
ni cuantificar precisión de silueta. Los reflejos internos se conservan como
contenido; no se usan como falsos huecos ni como objetivo de limpieza.

## Resolución y espesor físico

- Conversión correcta: `px = mm × DPI_efectivo / 25,4`.
- Perfil actual: 30 px a 300 DPI = **2,54 mm**, no 1,5 mm.
- Pipeline nativo: 436 × 436, 194,2877 DPI a 5,7 cm;
  `source_to_native_scale=1.0`. El lienzo cambia por recorte/márgenes, no por
  inventar detalle. El contenido efectivo registra aproximadamente 194,18 DPI.
- Un borde de 2,54 mm a ese DPI correspondería a unos **19,43 px**, redondeado 19.
  El ensayo aislado recibe el DPI nominal 300 y aplica 30 px sobre coordenadas
  fuente: no demuestra calibración física correcta. No se publicará con esa
  equivalencia. La salida nativa del pipeline informa borde añadido 0 porque
  preserva el existente; esto no certifica un grosor uniforme del borde original.
- `pipeline_source_resolution_421.png` conserva el sistema de coordenadas
  421 × 421 del original y aplica su máscara editable. Es evidencia de segmentación,
  **no** el maestro final del pipeline ni una referencia aprobada.
- `pipeline_final_transparent.png` es una copia exacta del maestro nativo real
  436 × 436. No se lo redimensionó a 421 para aparentar cumplimiento exacto.
- El resultado aislado 421 × 421 es diagnóstico fallido, no una exportación final
  aprobada. El requerimiento integral de PNG final 421 × 421 limpio no se cumple.

## Evidencias

Carpeta: `artifacts/sticker-halo-real-20261019-v2/`.

- `original.png`: copia exacta, sin modificaciones.
- `mask_before_contraction.png`, `pipeline_before_halo.png`: estado real previo.
- `pipeline_mask_clean.png`: alfa resultante del pipeline; no certificación de limpieza.
- `pipeline_source_resolution_421.png`: extracción alineada al original.
- `pipeline_final_transparent.png`: PNG nativo real.
- `on_black.png`, `on_magenta.png`, `on_white.png`: composiciones del PNG nativo.
- `before_after.png`: original, pipeline nativo, módulo aislado y antes del borde aislado.
  El panel nativo se ajusta únicamente para mostrarlo en la hoja comparativa.
- `pipeline_300pct.png`, `module_300pct.png`: inspección ampliada sin interpolación.
- `*_400pct.png`: cuatro regiones (estrella superior, izquierda, conexión inferior
  y estrella pequeña). Orden: original / extracción del pipeline / módulo aislado.
- `isolated_module_NOT_PIPELINE/`: máscara sin contracción, resultado antes
  del blanco, PNG aislado, alfa retornado, vistas negro/magenta/blanco y mapa
  de eliminaciones. El mapa vacío NO equivale a ausencia de defectos.
- `audit.json`, `execution.log`: parámetros, resultados, rutas y hashes.

## Regresión

Banco completo regenerado con:
`python -m scripts.validate_sticker_visuals --output artifacts/sticker-halo-regression-20261019`.

44 ejecuciones completadas; 43 REVISAR y un ERROR esperado del corte manual
inválido. Comparadas con `artifacts/sticker-disc-controlled-final` usando
`compare_runs`: **132/132 artefactos idénticos byte a byte** (máscara editable,
maestro nativo y corte de los 44 casos), mismas fuentes, rutas y tipos.
Incluye disco, corazón, labios, fondos complejos, alfa, edición manual y nativos.
Las comparativas están en `artifacts/sticker-halo-regression-20261019/before_after/`.
No hay regresión observada en ese banco que requiera revertir cambios.
Identidad automatizada no equivale a aprobación visual humana ni prueba de
cobertura efectiva del nuevo módulo.

Suite completa:
`python -m pytest -q --basetemp=pytest-halo-real-20261019-temp -o cache_dir=pytest-halo-real-20261019-cache --junitxml=pytest-halo-real-20261019-results.xml --tb=short`.
Se ejecutó con acceso al runtime Tcl/Tk instalado. Resultado: **1099 passed,
1 skipped, 4 warnings, 5 subtests passed**, salida 0, **217,64 s**.
JUnit: `pytest-halo-real-20261019-results.xml`.

Frente a la referencia de 1086 aprobadas/una omitida son 13 aprobadas adicionales:
seis de `test_sticker_reference_review.py` (antes ejecutadas por separado) y
siete de `test_grey_halo_decontamination.py` ya presentes al comenzar esta
validación. Se verificó la diferencia de casos por nombre en ambos JUnit.
No se añadieron pruebas unitarias nuevas en este turno ni se relajaron expectativas.
Los ensayos del módulo de halo son sintéticos: que pasen no valida el disco.
La omisión corresponde al conjunto externo shield1…shield5 ausente
(mensaje: `Shield file shield1.png not found`). Las cuatro advertencias históricas
son `PytestReturnNotNoneWarning` en `test_white_border_white_background.py`;
los retornos no equivalen a aserciones y esos tests no se presentan como
validación visual. Compilación del script nuevo correcta con `py_compile`.

## Pendientes y límites

No habilitar globalmente el módulo para C ni aumentar la erosión para intentar
compensar este fallo. Hace falta corregir la integración de forma acotada,
distinguir borde blanco existente de contaminación, calcular espesores al DPI
de trabajo y detenerse ante pérdida local de detalles. Antes de cerrar VV-05
se requiere la máscara 421 × 421 revisada y aprobada por una persona y su
comparación regional. Los dos P2 (halo/sombra de labios y política de orientación)
siguen abiertos, sin cambios globales para intentar resolverlos.

No se guardaron aprobaciones, no se publicaron stickers ni se alteraron resultados
anteriores. Las validaciones físicas de impresión/corte permanecen pendientes.

## Corrección de integración real — 2026-10-19

### Estado actual

**Integración y bloqueo de doble borde corregidos; P1 visual NO cerrado.**
El disco conserva C y pasa una vez por la nueva etapa común. El resultado
explícito es `manual_required / embedded_checkerboard_requires_manual_reference`,
sin borrar contenido ni añadir blanco. No equivale a halo eliminado, referencia
aprobada ni permiso de producción. Las secciones anteriores conservan la evidencia
histórica del fallo; esta sección describe el código actualizado.

### Causas y cambios

La selección B con `has_grey_border` era una condición de enrutamiento demasiado
restrictiva para una operación complementaria. Ahora se evalúa después de obtener
el alfa base y antes del padding/recorte y del único renderizador imprimible,
independientemente de A/B/C/D. Se excluyen máscaras manuales, selección explícita
de objetos, imagen completa y alfa fiable sin señales de borde a evaluar.

El detector anterior miraba sólo un píxel del perímetro, únicamente grises
80…220 y sólo dentro del alfa ya extraído. En el disco ese perímetro tiene
100 % de blanco: el gris ambiguo que motivó el problema no estaba representado
allí como un halo conservado. Además el cálculo anterior medía el porcentaje
gris en la banda acumulada *descartada*, no en el nuevo contorno resultante.
No se puede deducir de ese falso negativo que el original esté limpio.

`halo_geometry.py` separa color y geometría: blanco y color son barreras,
las regiones grises se proponen sólo cuando conectan con el exterior del lienzo,
están cerca del contorno alfa y de blanco confirmado, y no tocan posible dibujo.
No se usan los huecos interiores como semillas. El límite de búsqueda es una
cota de seguridad (8…12 px), **no** un radio aplicado de erosión; la profundidad
de eliminación proviene exclusivamente de la región detectada. Píxeles grises
por sí solos no autorizan limpieza. El damero ambiguo devuelve revisión manual.

La etapa común sólo puede reducir alfa en esos píxeles identificados. Se
conservan el alfa parcial y RGB de todos los restantes, con veto a cambios de
componentes o pérdidas superiores al 15 % del área base; esta comprobación de
área es adicional, no sustituye las barreras/regiones y revisión local.
Zonas protegidas no pueden eliminarse. No hay erosión global, suavizado nuevo,
relleno de huecos ni reglas basadas en nombre/hash del archivo de prueba.
El hash sólo identifica la fuente de la herramienta de auditoría.

La antigua función generaba blanco incluso cuando `halo_detected=false` y
dilataba el alfa que ya incluía el aro original. La etapa común ya no genera
blanco: eso pertenece exclusivamente al renderizador existente. La API de
compatibilidad exige declaración explícita de contenido sin borde para generarlo
y veta esa declaración si detecta un aro blanco alrededor de contenido cromático.
La geometría reconoce también aros estrechos que el clasificador visual omite,
sin reclasificar la ruta técnica. El shim de dispatcher deja de construir blanco.
No se ejecutan dos veces la descontaminación y generación de borde.

La advertencia `halo_manual_review` y `grey_halo_review` se persisten. La
recuperación automática no puede reprocesar un caso ambiguo para perder esa
advertencia y aparentar una mejor calidad. La edición manual y sus reprocesados
mantienen prioridad. El troquel sigue derivándose por separado con los valores
de calibración originales.

### Física y resultado real

El perfil sigue solicitando 2,54 mm (30 px a 300 DPI). Se documenta en
`grey_halo_review.physical_border` el DPI nativo y el espesor realmente añadido.
En el disco: 194,2877 DPI, borde nuevo **0 px**, borde original conservado;
fuente 421 × 421, alfa editable 421 × 421, maestro nativo 436 × 436 con márgenes,
escala de detalle 1:1. No se fuerza 300 DPI efectivo ni se reescala a 421 el
maestro. La API comprobada a 194,2877 DPI convierte 2,54 mm a 19 px, no 30.
El grosor físico uniforme del borde **original** no está certificado.

### Evidencia final de esta corrección

`artifacts/sticker-halo-integrated-evidence-final/`:

- `halo_mask_initial.png`: máscara que entra realmente en la etapa común.
- `halo_region.png`: región propuesta; vacía en el disco. No significa ausencia
  de contaminación en el original, sino que no se identifica un recorte seguro.
- `halo_mask_clean.png`: misma máscara en el caso ambiguo, sin erosión ficticia.
- `halo_original_white_border.png`: blanco detectado geométricamente, no verdad humana.
- `halo_before_printable_border.png`: RGBA anterior al renderizado de base.
- `native_printable_base.png`: base física final; no se confunde con el diseño.
- `new_printable_border_ZERO_preserved_original.png`: capa vacía que documenta
  los cero píxeles de espesor nuevo configurado en este caso.
- `printable_base_added_pixels.png`: diferencias de soporte respecto al alfa
  de diseño, incluyendo cierre/suavizado heredado; no se etiquetan como nuevo
  borde de 30 px ni como error de referencia.
- `pipeline_final_transparent.png`, `on_black.png`, `on_magenta.png`,
  `on_white.png`, ampliaciones 300/400 %, `audit.json` y `execution.log`.
- `integration_before_after.png`: original / ensayo aislado antiguo fallido /
  extracción actual del pipeline, ambos en coordenadas fuente 421 × 421.
  No pretende que el antiguo ensayo aislado fuera un resultado del pipeline.

Inspección: esfera y cuatro estrellas continúan visibles; el exceso blanco
del ensayo aislado anterior ya no se reproduce. Persisten irregularidades y
conexiones que necesitan trazado/revisión humana. No se ofrece como mejora de
segmentación una máscara idéntica a la anterior. No se utilizó la candidata
humana no aprobada como verdad de referencia.

### Pruebas de integración y regresión

Se añadieron **13 casos** en `tests/test_grey_halo_integration.py`: tres fixtures
reales a través de `process()`, persistencia/reapertura y artefactos alineados;
cuatro combinaciones de aro/halo/estrellas/conexiones/reflejos internos;
tres declaraciones de borde (True/False/None) que deben impedir sumar 30 px;
eliminación localizada efectiva en una región conocida, prioridad manual en
dos reprocesados, y conversión de mm al DPI efectivo con alfa consistente.
Pruebas focales finales: **20 passed**, 5,36 s (13 nuevas y siete del módulo).
La prueba sintética histórica que solicita generar blanco ahora declara
explícitamente `existing_border=False`; conserva sus aserciones y no sirve
como validación visual del disco.

Banco definitivo: `artifacts/sticker-halo-integrated-release-regression/`.
44 ejecuciones completas, 43 REVISAR y el ERROR esperado de corte inválido.
Comparación contra `artifacts/sticker-halo-regression-20261019`: **132/132
artefactos máscara/maestro/corte idénticos byte a byte**, mismas fuentes,
rutas y tipos. Las 18 hojas y 44 comparativas están regeneradas; no se
detectó pérdida de contenido que exigiera revertir. El banco no certifica
casos fotográficos reales distintos a los tres fixtures existentes.

Suite completa definitiva, ejecutada sin otra suite gráfica simultánea:

`python -m pytest -q --basetemp=pytest-halo-integrated-serial-temp -o cache_dir=pytest-halo-integrated-serial-cache --junitxml=pytest-halo-integrated-serial-results.xml --tb=short`.

**1111 passed, 1 failed, 1 skipped, 4 warnings, 5 subtests passed**, salida 1,
**233,10 s**. JUnit: `pytest-halo-integrated-serial-results.xml`.
Frente al baseline de 1099 aprobadas, se incorporaron 13 casos; hay 1112
casos no omitidos y **no se declara la suite completamente aprobada**.

Fallo: `tests/test_area_selection.py::test_area_selection_draw_and_confirm`,
en `root = tk.Tk()` antes de utilizar el procesador. Tk no puede cargar
`.pytest_runtime/tcl/tk8.6/tk.tcl`. En un diagnóstico con la recolección completa
también falló la lectura de `init.tcl`; dirigir TCL_LIBRARY/TK_LIBRARY al runtime
instalado no resolvió esa variante. El mismo test ejecutado solo aprobó
(`1 passed`, 0,47 s), pero **no se resta** el fallo de la ejecución completa.
Queda pendiente estabilizar y validar el arranque Tcl/Tk bajo recolección completa.
No se cambió ese test ni conftest, no se lo omitió, ni se relajaron sus aserciones.

Una pasada intermedia, anterior a los dos parámetros adicionales de borde y
al registro físico definitivo, terminó con 1110 aprobadas/una omitida en
239,84 s (`pytest-halo-integrated-final-results.xml`); no valida por sí sola
la revisión final. Se detuvo una pasada solapada usando únicamente el PID
verificado de ese pytest para evitar interferencias gráficas. El diagnóstico
posterior mostró que el error Tcl/Tk también ocurre en serie: el solapamiento
no era una explicación suficiente. No se computa la pasada detenida como éxito.

Persisten la omisión shield1…shield5 ausente y las cuatro advertencias históricas
de retornos en `test_white_border_white_background.py`. No se ha demostrado
regresión de máscara/contenido en las 44 comparativas ni en las pruebas nuevas;
eso no equivale a un resultado global sin fallos.

### Archivos modificados y límites

Producción: `app/stickers/pipeline.py`, `grey_halo_decontamination.py`,
`recovery.py`; nuevo helper `halo_geometry.py`. Herramienta:
`scripts/validate_real_disc_halo.py`. Tests: nuevo
`tests/test_grey_halo_integration.py` y contrato explícito en
`tests/test_grey_halo_decontamination.py`. Informes: este documento y
`STICKER_VISUAL_CORRECTIONS.md`. Compilación Python correcta.

No se cambiaron modelos A/B/C/D, perfiles, calibraciones, pedidos ni planchas.
No se reconstruyó el pipeline. Los dos P2 siguen abiertos. El siguiente cierre
visual exige una máscara revisada y aprobada, alineada con el original, seguida
de comparación regional y validación física. **P1 pendiente de revisión humana;
producción no aprobada.**
