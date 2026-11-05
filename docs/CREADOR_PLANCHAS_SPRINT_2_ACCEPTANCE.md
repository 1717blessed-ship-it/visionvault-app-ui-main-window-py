# Creador de Planchas 2.0 — Sprint 2: distribución y aprovechamiento

Fecha: **24/10/2026**. Rama independiente `codex/creador-planchas-s2-optimizacion`, creada desde el contexto de Sprint 1 sin reset, commit, publicación ni promoción. Los cambios preexistentes siguen presentes y no se atribuyen a este sprint.

## Dictamen ejecutivo

**Mantener Normal como predeterminado.** Existe una alternativa opcional de huecos, identificada **SIN FILAS**, con mejoras medibles para mezclas de tamaños y sin alterar tamaños, rotación ni identidades. Sólo se aplica a borradores sin reservas, con confirmación explícita, si disminuye el número de hojas y pasa la validación geométrica. Si no mejora, no cambia la composición actual.

No se habilita redistribución retroactiva de planchas guardadas, históricas, impresas ni reservadas. Tampoco se redistribuye Libre manual ni posiciones bloqueadas. No se cambió el motor de Sticker Studio A/B/C/D, calibraciones, reglas de Pedidos/Tandas ni datos operativos.

## Fase 0 y estado inicial comprobados

- Inicio sobre `codex/creador-planchas-s1-seguridad`, con checkout previamente modificado. No se revirtieron cambios ajenos. La rama nueva conserva la anterior como referencia, pero los cambios aún no están consolidados en commits separados: no afirmar independencia de contenido del working tree entre ramas.
- Antes de cambiar distribución: **142 pruebas focalizadas aprobadas**, 16,29 s; `artifacts/creator-s2-baseline.xml`.
- Benchmark previo: `artifacts/creator-s2-baseline-benchmark.json`; comparación posterior: `artifacts/creator-s2-comparison.json`.
- **Los diez hashes de geometría Normal anteriores y posteriores coinciden exactamente** (incluyen orden, posiciones, dimensiones e identidades). La corrección de última fila permanece cubierta.

## Auditoría de la colocación y oportunidad

El regular usa cinco franjas, prioridad por superficie, hitboxes reservadas y margen configurable. Las filas completas se justifican como antes; la última incompleta se agrupa a izquierda con el mínimo configurado. Las coordenadas verticales se determinan por las franjas, por lo que diseños bajos pueden dejar huecos internos sin utilizar. El parámetro `gap_cm` es la separación mínima de ambos ejes; no se agregó un control independiente horizontal/vertical.

Los modos Mixta y especial ya existen y no se reconstruyeron. Mixta geométrica usa aire interno en hitboxes que pueden tocarse; al compararla se conserva ese contrato para evaluar su composición actual. La alternativa nueva usa, además, el gap explícito entre hitboxes. No se interpreta ese aire como permiso para reducir piezas o contornos.

Libre guarda posiciones manuales; queda excluido. A4/A5/franja delimitan área útil dentro del soporte físico A4. Material/formato/unidad son restricciones productivas, no decisiones que el packing pueda deducir del aspecto de una imagen.

Oportunidad medida en el regular de cinco franjas con cajas físicas mezcladas de 4,8×4,8; 3,2×3 y 2,4×2 cm: 100 piezas usaban cuatro hojas y 200 usaban ocho, con aproximadamente 51 % de ocupación rectangular útil. Esto justifica probar una ruta geométrica opt-in sin reemplazar el regular.

## Alternativa implementada

`app/planchas/optional_distribution.py` reutiliza la partición de rectángulos libres existente del Creador (`Rect`/`update_free_rectangles`). Prueba dos órdenes deterministas, por superficie y por altura, y coloca en huecos compatibles. La separación se reserva como halo derecho/inferior; la mesa se extiende matemáticamente sólo por ese halo, sin permitir que la hitbox física supere el margen. Las posiciones guardadas son las coordenadas que consumen canvas y exportación.

La alternativa:

1. Clona entradas: comparar no modifica el original.
2. Conserva la referencia Normal actual cuando se aportan páginas válidas; esto incluye páginas Mixta ya calculadas, sin reinterpretar su packing como cinco franjas.
3. Para una entrada geométrica sin páginas calcula el normal mediante el mismo distribuidor existente. Si éste requiriera cambiar tamaños/rotaciones, se solicita preparar primero la geometría normal, no se redimensiona como parte de comparar.
4. No rota ni escala piezas. Conserva dimensiones productivas, hitbox, contorno, IDs, copias, vínculos y claves de unidades solicitadas. Reordenar posiciones es intencional únicamente en la alternativa aceptada.
5. Verifica multiconjunto exacto de IDs, parámetros finitos, límites y separación de cada par. Rechaza identidades duplicadas, unidades comerciales `sheet` y contextos incompatibles/incompletos.
6. Sólo selecciona un candidato con **menos hojas**. Con igual número conserva Normal, aunque un reparto diferente pudiera parecer más compacto. No se pretende óptimo matemático global.

No se agregan diseños de relleno de Biblioteca ni se consumen unidades que no formaban parte de la selección. «Completar huecos» aquí significa recolocar las unidades existentes en espacios disponibles, no inventar una demanda nueva.

## Uso y alcance de la interfaz

Nuevo control **⇆ Comparar aprovechamiento (opcional, sin filas)** en el grupo Armado. Muestra Normal/Alternativa con hojas, colocadas, pendientes, imposibles, ocupación y superficie libre de hitboxes. Antes de aplicar pregunta confirmación. Cancelar o no mejorar conserva la composición original. Los errores de archivos usan el preflight del Sprint 1.

Después de aplicar: navegación por páginas existente, hoja actual, unidades de la hoja y resumen total; señalización «HUECOS SIN FILAS». El modo regular conserva su regla de última fila. Volver a la acción normal de organizar conserva el motor habitual y retira la identificación de huecos de esa página; no se agregó un selector reversible global de conjuntos ni una migración de layouts históricos.

Bloqueos deliberados:

- Cualquier proyecto guardado/cargado o con `plancha_id`, posiciones bloqueadas o Libre manual.
- Copias con reservas activas: no se modifican reservas para redistribuir una tanda existente.
- Para trabajos de Pedidos: requieren identidad trazable, consulta de material/unidad y compatibilidad de todo el grupo. Distintos materiales o formatos se comparan por separado, no se mezclan silenciosamente.
- Hojas comerciales no se compactan como si fueran stickers individuales.

Integración: el comparador no escribe SQLite. La prueba usa la preview de Tandas, sustituye sólo los proyectos de su grupo compatible por el resultado y guarda con `ProductionBatchService.save` existente: **100 reservas `prepared`, 100 claves únicas**, sin cambiar demanda ni estados. Un intento posterior desde UI sobre esas copias reservadas se bloquea y mantiene dump SQLite idéntico. No se añadió selector de optimización dentro del diálogo de Tandas ni se habilitó reempaque de tandas persistidas; la UI del editor se limita a borradores sin reserva.

## Definición de los indicadores

- **Ocupación:** suma de `width_cm×height_cm` físicos de diseños / suma de áreas útiles de las hojas ×100. No usa la caja A4 total si el formato es parcial. No es área de silueta ni de tinta y no expresa rentabilidad.
- **Superficie libre de hitboxes:** área útil total menos suma de áreas reservadas. Incluye fragmentos y corredores no necesariamente aprovechables por otra pieza; no garantiza capacidad adicional. No confundir con el «espacio libre» rectangular por diseño ya existente.
- **Colocadas:** número de identidades físicas de unidad; pendiente/imposible son cero sólo en comparaciones completas satisfactorias. El error estructurado de piezas imposibles del Sprint 1 sigue bloqueando una salida falsa de éxito.
- Cada comparación preserva formatos, margen y gap; no compara algoritmos usando tamaños distintos para aparentar ahorro.

## Benchmarks

`python tools/benchmark_creator_sprint2.py --compare`. Diez escenarios 10/25/50/100/200, un tamaño y mezcla de tres tamaños; tres repeticiones para mediana. Pico de memoria mediante `tracemalloc` en otra repetición, **memoria Python trazada, no RSS del proceso**. Incluye creación de modelos sintéticos y comparación; no carga/decodifica fuentes ni renderiza PNG, consulta SQLite o accede al driver. La comparación incorpora calcular/verificar Normal más los candidatos y es deliberadamente más lenta que el normal solo. Son mediciones locales bajo carga concurrente de pruebas, no SLA.

Estas dimensiones físicas fijas son un benchmark geométrico: **no equivalen al producto estándar nominal de 5 cm ya compensado**. No se usa una supuesta capacidad comercial de 20 para prometer producción de estándar 5 cm. Hay pruebas separadas de Mixta/normal y de integración con nominales de Pedidos.

### Mezcla de tamaños, separación 0,05 cm y margen 0,15 cm

| Unidades | Hojas normal → elegida | Ocupación normal → elegida | Tiempo normal → comparación | Pico Python normal → comparación |
| --- | --- | --- | --- | --- |
| 10 | 1 → 1 | 22,24 → 22,24 % | 0,12 → 1,28 ms | 9,2 → 33,2 KiB |
| 25 | 1 → 1 | 53,00 → 53,00 % | 0,32 → 3,64 ms | 18,0 → 78,6 KiB |
| 50 | 2 → 2 | 51,90 → 51,90 % | 0,56 → 8,55 ms | 35,5 → 157,8 KiB |
| 100 | 4 → 3 | 51,70 → 68,93 % | 2,06 → 21,30 ms | 75,3 → 319,2 KiB |
| 200 | 8 → 5 | 51,42 → 82,28 % | 6,09 → 65,03 ms | 144,1 → 634,2 KiB |

100: distribución por hoja Normal `[20,23,32,25]`; elegida `[24,44,32]`. 200: ahorro de tres hojas (37,5 %) en este escenario. Todas las unidades se conservan. Ninguna mejora se acepta sólo por contar menos hojas: hay verificación geométrica previa.

Para tamaños iguales, 10/25/50/100/200 conservaron exactamente 1/2/3/5/10 hojas y los hashes originales de distribución; no se aplica un cambio sin ahorro. Métricas completas y hashes están en el JSON, no se exige hash idéntico entre algoritmos que intencionalmente cambian posiciones.

## Evidencias y capturas

- `artifacts/creator-s2-visual-20261024/optimized-editor.png`: **captura real de Tkinter** con 100 unidades en tres hojas, 24 en la primera, resumen de ocupación y modo SIN FILAS. Harness `tools/preview_creator_sprint2.py`, sin base y con imágenes FICTICIO. No certifica apariencia de todos los temas/DPI; el harness usa estilos del editor, no una homologación visual completa de la aplicación.
- `artifacts/creator-s2-acceptance-20261024/normal.json` y `optimized.json`: snapshots completos y recuperables.
- `normal-01.png` a `normal-04.png`, `optimized-01.png` a `optimized-03.png`: renderizados reales del motor de exportación A4 300 DPI. **No son capturas de pantalla**.
- `observations.json`: cantidades, áreas y hashes de píxeles de las siete páginas. Cada página recuperada conserva exactamente sus píxeles de exportación y geometría de preview. No se compara el hash de una página normal con otro layout intencionalmente distinto.

La prueba de preview/exportación también comprueba coordenadas sin mutación, centros de las piezas renderizadas, persistencia y bloqueo al retirar la fuente. Se reutilizan las protecciones del Sprint 1, sin duplicar el renderizador.

## Archivos de Sprint 2

Productivos: `app/planchas/optional_distribution.py` (nuevo) y `app/planchas/editor.py` (control explícito, protección de borradores e indicadores). **No se modificó `model.py` ni `production_batch_service.py` en este sprint.** Sus cambios previos pertenecen a otros trabajos y no se revierten.

Pruebas: `tests/test_creator_sprint2_distribution.py` (30 nuevas). Soporte: `tools/benchmark_creator_sprint2.py`, `tools/preview_creator_sprint2.py`, `tools/validate_creator_sprint2.py`, este informe y artefactos. Sin cambios de Mobile, impresión/calibración ni Sticker Studio.

## Pruebas y compatibilidad

- Iniciales Sprint 1/última fila: **142 aprobadas**.
- Nuevas: **30 aprobadas**; tamaños iguales/mixtos, 40/35/25, normal sin cambios, fallback, determinismo, huecos, custom margen/gap/A5/franja, rotaciones/dimensiones intactas, incompatibles, Libre, bloqueo, hojas comerciales, IDs duplicados, imposibles, archivos faltantes, persistencia, exportación, cancelación/aplicación UI y reservas con servicio real aislado.
- Matriz focalizada final congelada: **172 aprobadas**, 35,08 s; `artifacts/creator-s2-focused-verified.xml`. 245 advertencias de deprecación Pillow en pruebas de rasterización, sin fallos.
- General intermedia completa: **1316 aprobadas, 1 omitida, 5 subtests aprobados**, 268,15 s; no acredita las pruebas/refuerzos añadidos después. Las repeticiones interrumpidas no se cuentan como aprobadas completas.
- General definitiva congelada: **1319 aprobadas, 1 omitida, 5 subtests aprobados, 0 fallos**, 302,18 s; `artifacts/creator-s2-verified.xml`. 249 advertencias (245 de rasterización Pillow y 4 tests preexistentes que retornan valores); no se modificaron módulos ajenos para ocultarlas.
- Advertencias de deprecación Pillow en pruebas de rasterización y advertencias preexistentes de tests que retornan valores, sin ocultar fallos.

Calibración 0,9727 y corte 1,50 mm permanecen bajo las pruebas Sprint 1. No se imprimió, no se cortó ni se homologó dimensión física.

Control de datos: `visionvault.db` mantiene SHA-256 `f6abfb14fedfefb99653fa0928e1010cb1d8bd30da7955a7bc3ac4eb0a9340f2`; `physical-pending.db` mantiene `c5457335c8ae472e7c00b38d1b827c8bb50276c35f5796cb80aab79a16d01e0c`. No se abrió la base operativa para escritura desde las herramientas del sprint. La tanda física continúa pendiente del operador.

## Pendientes y decisión de habilitación

Mantener disponible como **comparación opcional para borradores compatibles**; no convertirla en predeterminada. No hay garantía de óptimo global, rotación nueva ni aumento de tamaño. No hay optimización automática de tandas reservadas o partición silenciosa de trabajos incompatibles.

Pendiente para ampliar alcance: pruebas físicas sobre muestras del nuevo layout con el operador, validación visual completa en otros tamaños/DPI, y eventual UX de comparación antes de reservar dentro del diálogo Tandas si se solicita otro sprint. No se cambia ese flujo ni se amplían permisos automáticamente.

**Aceptación técnica del Sprint 2 aprobada para el alcance opcional y conservador descrito.** Normal permanece predeterminado; sólo aplicar la alternativa a borradores compatibles cuando reduzca hojas con geometría verificada. No se habilita como política automática de todas las tandas ni se declara homologación física. La base de pruebas e informes permiten reproducir la comparación, sin datos reales ni publicación automática.
