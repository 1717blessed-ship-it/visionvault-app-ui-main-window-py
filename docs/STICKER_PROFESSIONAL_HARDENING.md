# Creador de Stickers: auditoría y endurecimiento

## Sprint 1.2 (2026-10-19)

Se incorporó la contracción no destructiva de selección en milímetros mediante
campo de distancia firmado, con preview V2, historial, advertencias topológicas
y persistencia sin acumulación. Informe y evidencia:
`docs/STICKER_STUDIO_SPRINT_1_2.md`. Suite: 1139 aprobadas, una omitida. El P1
continúa abierto y no existe aprobación productiva.

## Sprint 1.1 (2026-10-19)

La estabilización posterior está registrada en
`docs/STICKER_STUDIO_SPRINT_1_1.md`: exportación V2 idéntica al master,
configuración aislada por job, GrabCut determinista y política compartida de
borde con fallo seguro ante halo ambiguo. Suite: 1130 aprobadas, una omitida.
El P1 sigue pendiente de referencia humana y no existe aprobación productiva.

## Continuación: Sticker Studio 2.0, Sprint 1 (2026-10-19)

Se añadió una interfaz profesional reversible como capa sobre `StickerStudio`.
La implementación está documentada en `docs/STICKER_STUDIO_2.md`. Los módulos
nuevos viven en `app/stickers/editor_v2/`; `app/ui/main_window.py` selecciona la
2.0 de forma predeterminada y conserva el clásico mediante la variable
`DOCCIONE_STICKER_STUDIO=classic`.

No se cambiaron el pipeline, las rutas A/B/C/D ni las calibraciones. El canvas
2.0 consume artefactos existentes con caché de preview, damero, ajuste,
zoom/pan, vistas por capa, comparación y contorno. El estado visual se conserva
por trabajo y es independiente del raster original y de la salida final.

Validación final de Sprint 1: compilación correcta; 7 pruebas focalizadas y
smoke test real de apertura/cierre Tk aprobados. Suite completa:
`1117 passed, 1 skipped, 4 warnings, 5 subtests passed` en 227,32 s. El entorno
de pruebas repara caches parciales de Tcl/Tk en el temporal del sistema. El P1
del disco y las validaciones visuales/físicas continúan abiertos; el módulo no
se declara listo para producción.

Continuidad visual (2026-10-17): ver `docs/STICKER_VISUAL_VALIDATION.md`.
Se preparó el banco de 36 entradas y ocho combinaciones de modos; se registraron
defectos visuales sin corregirlos automáticamente. El endurecimiento técnico y
la suite sin fallos no equivalen a aprobación visual ni física de producción.

Fecha: 2026-10-17. Trabajo sobre el módulo existente.

Las secciones iniciales documentan la primera fase. La continuación de este
informe describe los cambios posteriores de resolución, recuperación y entorno
de pruebas; prevalece para el estado técnico actual.

## Auditoría inicial

Se inspeccionaron pipeline.py, editor.py, models.py, profile_editor.py,
mask_candidates.py, exporter.py y los contratos de geometría de planchas.
La línea base ejecutada fue `python -m unittest tests.test_sticker_creator
tests.test_pipeline_classify -q`: 42 pruebas, todas correctas, 5,881 segundos.

Existían 18 categorías visuales, rasgos coexistentes, tres modos de creación,
máscaras por componente, pincel/lazos, zoom, deshacer, comparación de fondos,
base imprimible, troquel raster y perfil físico compartido con planchas.
La evaluación de candidatos ya existía y se reutilizó.

Problemas comprobados:

- Reescalado con premultiplicación manual sobre RGBA: Pillow volvía a
  premultiplicar durante resize, alterando colores de alfa parcial.
- Máscara editable guardada después de agregar padding y abierta contra la
  fuente sin padding: coordenadas inconsistentes.
- IDs de objetos dependientes del orden por superficie en cada corrida.
- Reemplazo de ClassifyResult en PNG opaco borraba la clasificación visual.
- Una máscara manual podía atravesar extracción de fondo y limpieza automática.
- Cancelación sin comprobaciones dentro del pipeline ni limpieza de la corrida.
- El guardado manual sobrescribía la máscara automática; faltaba rehacer.
- Reprocesar sustituía la referencia al resultado anterior sin acceso desde UI.

## Cambios implementados

- `quality.py`: QualityReport y validate_sticker. Resultado APROBADO, REVISAR o
  ERROR; lista separada de errores verificables y advertencias heurísticas.
  Comprueba máscara vacía, maestro opaco/vacío, dimensiones raster/físicas,
  troquel vacío o degenerado, resolución y componentes pequeños. Ofrece
  comparación de superficie cuando se proporciona una referencia alineada.
  No considera defectos los huecos intencionales o el alfa parcial.
- `objects.py`: match_object_ids conserva IDs con IoU >= 0,65, margen >= 0,20
  frente al segundo candidato y correspondencia única. Las ambigüedades generan
  IDs nuevos sin reciclar los anteriores y requieren revisión.
- `pipeline.py`: envoltorio process conserva argumentos históricos y añade
  cancelación cooperativa. Una cancelación borra exclusivamente la carpeta UUID
  de esa corrida; las anteriores permanecen. La cancelación se comprueba entre
  etapas; no interrumpe una operación nativa/IA que aún no haya retornado.
- Reescalado mediante RGBa premultiplicado de Pillow; eliminación del bloque
  redundante de arrays float32. Máscara editable y fuente alineadas separadas
  de los artefactos legacy.
- Prioridad de máscaras manuales, conservación de huecos y componentes manuales,
  alfa totalmente parcial permitido como contenido visible y clasificación
  conservada en la ruta de PNG opaco.
- Capas design_layer y printable_base_mask alineadas al maestro, además del
  troquel existente. cut_mask_override modifica únicamente el troquel y valida
  sus dimensiones. El grosor físico del borde se registra en milímetros.
- Metadata aditiva schema_version=2, quality_report, coordenadas de capas y
  reprocess_parameters. Los campos legacy y formatos de corte se conservan.
- `editor.py`: rehacer (botón y atajos), guardado manual separado, corrección de
  corte con archivo propio, restauración de resultados anteriores, separación
  de objetos seleccionados en trabajos individuales y recuperación asistida
  reutilizando la máscara candidata evaluada. Límite de un intento asistido por
  trabajo y cinco referencias de alternativas en la sesión. Ningún candidato
  reemplaza automáticamente una corrección manual.
- Los errores técnicos impiden confirmar; las advertencias permiten revisión
  y confirmación consciente. Los botones de revisión se distribuyen en filas.

## Pruebas y compatibilidad

Comando final: `python -m unittest tests.test_sticker_creator
tests.test_pipeline_classify tests.test_sticker_hardening -q`.

53 pruebas correctas: las 42 originales más 11 nuevas. Las nuevas cubren
errores de máscaras/troquel, alfa parcial y huecos intencionales, advertencias,
tamaño físico, IDs persistentes/ambiguos, cancelación, coordenadas de edición,
metadata de reproducción, máscaras manuales, corte independiente, rehacer,
dimensiones de pedidos en planchas y composición con borde existente.

Los tres fixtures de regresión reales (corazón y disco sobre damero, labios
sobre blanco) se incluyen en tests/fixtures/sticker_regression. Se procesan
completamente y se comprueba categoría, alfa del maestro y ausencia de errores
técnicos. Su estado REVISAR es compatible con advertencias de resolución u
otros indicios; no equivale a afirmar que sus bordes son visualmente perfectos.

También se verificó compilación de los archivos Python modificados. En esta
primera fase pytest no estaba instalado; la continuación documenta su instalación
y la ejecución de la suite completa. No se cambió
la lógica de pedidos, reservas, calibración ni geometría de producción.

## Rendimiento y límites

La suite original se mantuvo cerca de seis segundos tras las correcciones.
La suite ampliada ronda ocho segundos e incluye nuevos procesamientos: no es
una comparación de rendimiento equivalente ni una promesa de aceleración.
Se retiró una conversión float32 redundante; falta una medición representativa
de memoria/latencia por tipo de imagen. No se añadió caché general ni nuevas
dependencias.

La primera fase conservaba un límite de resolución de trabajo de 1536 px.
Ese límite se retiró en la continuación descrita abajo. La fuente original
permanece intacta y la salida nativa conserva su detalle disponible.

El formato de corte actual es raster: se verifican ciclos extraídos y
degeneración, pero no una garantía de autointersecciones de exportaciones
vectoriales externas. La detección de pérdidas/huecos inesperados sigue siendo
limitada cuando no existe una referencia fiable. No se añadió un detector
semántico de contaminación de color ni una restauración universal de detalles.

La primera fase ofrecía recuperación asistida. La continuación añade evaluación
automática acotada y selección conservadora según métricas, descrita abajo.
El historial en UI dura la sesión; los archivos y parámetros se conservan en
disco. No se implementó restauración automática de toda la cola entre sesiones.
Los controles nuevos y los flujos de comparación requieren prueba visual en Tk.

## Validación real pendiente

- Inspección al 100/200 % de los tres ejemplos, acuarelas, reflejos, pelo,
  transparencias suaves, tipografía fina y bordes de color.
- Prueba de los botones/atajos nuevos, cambio entre alternativas, objetos
  individuales y edición de corte en la aplicación abierta.
- Muestras con imágenes grandes y múltiples objetos muy próximos o conectados;
  la separación actual se basa en componentes conectados, no en instancias
  semánticas de objetos superpuestos.
- Impresión a tamaño nominal, medición física, posición de base blanca, prueba
  de troquel y sangrado con la Brother ScanNCut usando la calibración existente.
- La continuación documenta la suite completa de producción/pedidos con pytest;
  su ejecución no sustituye la validación física.

Esta fase mejora el núcleo y aporta evidencia automatizada; no certifica todavía
un comportamiento perfecto para cualquier imagen ni la producción física.

## Continuación: resolución original y recuperación automática

### Resolución y compatibilidad de salida

Se eliminó la reducción de la copia de trabajo a 1536 px. El diseño y la
máscara editable se procesan a dimensiones originales, respetando EXIF.
Los analizadores existentes pueden usar muestras reducidas; la miniatura
sigue limitada a 256 px y jamás se usa como fuente de exportación.

El maestro habitual, impresión y control mantienen los píxeles/DPI y tamaños
del perfil existente. Se añaden tres PNG compatibles: native_master,
native_printable_base y native_cut. El diseño de estos archivos se compone
con escala 1:1 desde la silueta original, sin ampliarla ni pasar por el maestro
reducido. Su DPI efectivo conserva el tamaño físico del perfil. Los grosores
de borde y distancia de corte se convierten a ese DPI, con redondeo de un píxel.
La corrección de corte manual se remapea mediante vecino próximo.

Los radios del postprocesado expresados en mm ahora reciben el DPI efectivo
de las coordenadas fuente. Se guardan las transformaciones de máscaras manuales
redimensionadas, el factor fuente/maestro, el DPI efectivo y la geometría nativa.
Una fuente insuficiente genera REVISAR por resolución; no se atribuye detalle
adicional a la interpolación del maestro convencional. La salida nativa tampoco
amplía fuentes pequeñas.

Se conserva el límite previo de admisión de fuentes. Además, se rechaza una
salida nativa cuadrada superior a 40 megapíxeles para evitar asignaciones de
memoria excesivas; se explica cómo recortar/dividir el diseño y no se reduce
la fuente silenciosamente. No se promete procesar cualquier imagen arbitraria
con memoria ilimitada.

### Recuperación segura

Se evalúa como máximo una alternativa por corrida con indicios geométricos
recuperables. Usa la máscara extraída antes de la limpieza automática; no cambia
la segmentación A/B/C/D ni vuelve a ejecutar rutas incompatibles de IA.
Se conserva el alfa de esa extracción como artefacto propio cuando corresponde.
La pérdida de superficie durante la limpieza se mide en coordenadas alineadas.

La recuperación se omite ante máscaras/cortes manuales, transparencia fuente
real, selección de objetos, modo completo/múltiple o entradas aprobadas.
Tampoco se repite extracción para una mera advertencia de baja resolución.
Una alternativa solo se selecciona automáticamente si reduce la severidad,
no tiene errores técnicos, alcanza IoU >= 0,985 y conserva entre 97 % y 103 %
del área. Estos umbrales son reglas conservadoras, no probabilidades calibradas.
En otro caso se conserva la primaria y se ofrecen ambas para revisión.

Cada salida ocupa una carpeta UUID independiente; se persisten las dos rutas,
sus IDs, la elegida y las métricas. La interfaz carga la otra propuesta en
«Alternativa anterior». Un fallo de la alternativa conserva la primaria y se
registra; una cancelación elimina las corridas nuevas de esa operación y no
modifica resultados previos. No existe un bucle recursivo de recuperación.
Esta política no asegura reparar segmentaciones sin una referencia fiable.

### Persistencia e integración

ProcessingResult.from_metadata abre archivos nuevos y legacy sin reprocesarlos.
La persistencia SQLite conserva los artefactos nativos y sus parámetros. Al
publicar en banco o pedido se mantiene el maestro habitual como archivo publicado
para preservar el contrato existente, y se conservan las referencias a la
salida nativa, máscaras, corte y originales. La metadata se actualiza de forma
atómica con la ruta publicada y el estado Confirmado.

No se modifican reservas, asignaciones, precios, privacidad de pedidos,
calibraciones ni reglas de geometría A4. Se comprueba que una plancha que recibe
native_master usa el tamaño nominal solicitado, independientemente de su DPI.
El nativo queda disponible en los artefactos del trabajo; no se sustituye
silenciosamente el PNG histórico de la biblioteca por un raster distinto.

### Archivos de esta continuación

- app/stickers/pipeline.py: resolución original, máscara de recuperación,
  métricas de superficie, escalado, exportación nativa, recuperación y reapertura.
- app/stickers/resolution.py: render_native y conversiones físicas del nativo.
- app/stickers/recovery.py: recovery_allowed y compare_recovery.
- app/stickers/quality.py: evaluación de resolución según contenido/escala real.
- app/stickers/editor.py: acceso a las alternativas automáticas persistidas.
- app/database/database.py: conservación de artefactos y metadata al publicar.
- requirements-test.txt: pytest, watchdog y reportlab para pruebas.
- tests/conftest.py y .gitignore: caché local Tcl/Tk en Windows.
- tests/test_sticker_native_recovery.py: regresiones nuevas.
- app/planchas/poster_print_editor.py: precisión decimal del MediaBox PDF A4,
  sin cambios en calibración, dimensiones calculadas o escala del contenido.
- Este informe.

### Entorno y comprobaciones de esta continuación

Se instalaron pytest 9.1.1, watchdog 6.0.0 y reportlab 5.0.1 en el Python 3.14 utilizado.
La colección inicial encontró 1042 pruebas. La primera ejecución completa
registró 1031 correctas, 2 omitidas y 9 fallidas: cinco por falta de watchdog y
cuatro por lectura de Tcl en el entorno administrado. Tras instalar watchdog,
una ejecución completa registró 1052 correctas y 2 omitidas (187,89 s).
Una pasada posterior mostró un fallo intermitente al leer init.tcl en la primera
prueba gráfica, mientras la misma prueba aislada pasó. Se añadió un caché local
de los scripts de la instalación Tcl/Tk existente: las cuatro pruebas gráficas
pasaron sin cambiar sus expectativas ni omitirlas.
Se añadió también una comprobación de arranque de Tcl que admite hasta tres
intentos ante su error transitorio de apertura: se verifica el runtime antes
de ejecutar tests y un fallo persistente sigue deteniendo la ejecución.
No se reintentan ni se alteran aserciones de pruebas.

Con el entorno Tcl local la suite registró 1055 correctas y 2 omitidas
(186,18 s), sin fallos. Se revisaron las omisiones: una correspondía a reportlab
ausente y otra al conjunto externo shield1.png…shield5.png no disponible.
Tras instalar reportlab se ejecutó la prueba antes omitida y apareció el
redondeo decimal del MediaBox (841,8898 frente a 841,889764 puntos exigidos por
la prueba existente). Se corrigió únicamente la escritura decimal del tamaño
de página, conservando el cálculo y los ajustes de calibración. Las 34 pruebas
de PDF A4, nativos, perfiles e integración ejecutadas después pasaron.

Las pruebas específicas abarcan coordenadas originales superiores a 1536 px,
grosores de borde/corte medidos sobre el raster, DPI físico, advertencia de baja
resolución, alfa parcial, transformaciones de máscaras, reprocesamiento,
cancelación durante exportación y alternativa, comparación de siluetas,
protección de ediciones/aprobados, reapertura legacy, publicación y privacidad,
SQLite y consumo de nativos en planchas. Se incorporaron 15 casos nuevos a la
suite; se conservaron las 53 pruebas del creador de la fase anterior.

Resultado definitivo, sobre el código y entorno actualizados:

- `python -m pytest -x -q --basetemp=pytest-native-complete-temp
  --junitxml=pytest-native-complete-results.xml -o cache_dir=pytest-native-complete-cache`
- **1056 passed, 1 skipped, 4 warnings, 5 subtests passed**, código de salida 0,
  210,22 segundos. Informe JUnit: `pytest-native-complete-results.xml`.
- Única omisión: `test_shield_images_processing`, por ausencia del conjunto
  externo shield1.png…shield5.png. Los tres fixtures reales de corazón, disco
  y labios sí se procesaron en sus regresiones.
- Las cuatro advertencias son PytestReturnNotNoneWarning de tests históricos
  en test_white_border_white_background.py; no se cambiaron sus expectativas.
- `python -m pip check`: sin dependencias incompatibles.
- Compilación Python de los módulos modificados correcta.

Además se hizo un experimento de recuperación con pérdida de superficie
inducida en la limpieza de una imagen opaca: generó dos resultados reales,
guardó ambos y exigió comparación manual (IoU 0,4983), sin seleccionar
automáticamente una silueta diferente.

Para reproducir en una terminal con acceso a Tcl/Tk:

```powershell
python -m pip install -r requirements-test.txt
python -m pytest -q --basetemp=pytest-native-complete-temp --junitxml=pytest-native-complete-results.xml -o cache_dir=pytest-native-complete-cache
```

Usar un basetemp nuevo si se alternan usuarios o entornos con permisos distintos.
El caché Tcl/Tk local se genera con scripts del Python instalado; no descarga
otro runtime ni desactiva pruebas gráficas. No se alteraron tests históricos
para esconder fallos.

La ejecución completa pudo realizarse con acceso al runtime instalado y sus
recursos; el aislamiento inicial del agente producía errores de lectura de Tcl
que no se confundieron con fallos de geometría o calibración.

Siguen pendientes el caso de escudos sin sus archivos, la inspección visual del detalle/antialiasing, pruebas con
fuentes grandes representativas y memoria real, y la validación física de
impresión y ScanNCut. La suite automatizada no declara el sistema listo para
producción ni valida autointersecciones de formatos vectoriales externos.

## Sprint 1.6 — flujo, Canvas e historial

El 20 de octubre de 2026 se cerró la implementación automatizable del Sprint
1.6. Se desacoplaron revisión, exportación y envío; la vista Final quedó ligada
al master exportable; se unificó el historial no destructivo; y se incorporaron
procesamiento asíncrono con descarte por generación, caché LRU y navegación por
viewport. La suite completa registró **1174 aprobadas, 1 omitida, 4 advertencias
y 5 subtests aprobados** en 232,14 segundos. El detalle, métricas, evidencias y
pendientes se encuentran en `docs/STICKER_STUDIO_SPRINT_1_6.md`.

Esta ampliación no modifica rutas A/B/C/D ni calibraciones. El P1 real del disco
y la validación física continúan abiertos; por tanto, no constituye aprobación
para producción.

## Candidato productivo 2.0.0-rc.1

La homologación posterior procesó 20/20 entradas preservadas, comprobó 20/20
exports idénticos al master, midió un pico real de 462,27 MB y generó respaldo
SHA-256 de sesión, preferencias y perfiles. El dictamen es **APROBADO PARA USO
ASISTIDO**, no producción definitiva. Ver
`docs/STICKER_STUDIO_PRODUCTIVE_ACCEPTANCE.md` y
`docs/STICKER_STUDIO_PHYSICAL_ACCEPTANCE_FORM.md`.
