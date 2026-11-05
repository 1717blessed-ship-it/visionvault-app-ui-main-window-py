# Creador de Planchas 2.0 — Sprint 1: seguridad, persistencia y fidelidad

Fecha: 23/10/2026. Rama independiente: `codex/creador-planchas-s1-seguridad`. Sin commit, publicación ni promoción. Los cambios preexistentes del checkout se conservaron; esta rama los hereda sin atribuirlos al sprint.

## Causas raíz y correcciones

| Antes | Ahora |
| --- | --- |
| Render capturaba cualquier excepción de una pieza y continuaba. | Preflight de todas las fuentes: existencia/acceso, decodificación completa, contenido visible y tamaño válido. Error por diseño con nombre, referencia, ubicación, dimensiones y unidades no colocadas. Un fallo posterior de render también interrumpe, sin omisión silenciosa. |
| Escritura directa podía truncar el PNG válido anterior. | Temporal en el mismo directorio, escritura/sincronización y `os.replace`; se conserva el destino si falla antes de publicar. JPEG, SVG y JSON también usan escritura segura. |
| Guardado multipágina generaba/registraba hoja por hoja antes de saber si todas podían exportarse. | Staging completo de imágenes, JSON y manifiesto antes de registrar páginas productivas. Fallo de render/escritura de una página no registra las anteriores. La publicación restaura los destinos publicados si falla una sustitución recuperable. |
| `from_dict` imponía margen según formato y gap 0,05; constructor/apertura volvían a imponer margen/modo. | Restauración de valores explícitos finitos/no negativos, incluidos cero. Defaults sólo para campos ausentes. Constructor/apertura preservan modo/margen. Proyectos restaurados no se normalizan, escalan ni reacomodan al previsualizar; si la geometría queda fuera del área, la salida se rechaza. |
| Configuración global podía reemplazar preferencias al recuperar. | Snapshot de impresión/corte al guardar desde el editor; preferencias guardadas prevalecen. Campos adicionales versionados se conservan, incluidos parámetros de separación horizontal/vertical si estaban presentes. El modelo existente sigue usando un único gap de distribución: no se agregó un control nuevo de dos separaciones. |
| Archivos individuales no ofrecían una recuperación completa del conjunto desde un archivo raíz. | Manifiesto de páginas con snapshots completos y carga multipágina; siguen siendo compatibles los JSON individuales históricos. |
| Paginación terminaba sin devolver piezas imposibles. | `PaginationError` incluye informe estructurado por grupo: diseño/referencia/ruta, dimensiones, solicitado/colocado/no colocado, causa y acción. Las piezas válidas siguen pasando a hojas nuevas. No se habilitó una confirmación parcial implícita. |
| Validador exigía 100 y configuración guardaba 97,27; escala duplicada en dos módulos. | Una constante `PRINT_SCALE` compartida. Validador acepta perfiles calibrados 97,27 e históricos de escala lógica 100, sin cambiar sus valores ni multiplicarlos entre sí. Otros porcentajes se rechazan. |
| El backend podía aplicar otro ajuste para caber en el driver. | El envío desde el Creador activa `strict_calibration`: calcula una sola compensación y rechaza la hoja si no cabe; no hace un segundo auto-fit silencioso. El nuevo parámetro es opt-in: otras rutas mantienen su comportamiento anterior. |

No se cambió el algoritmo de packing ni la corrección de última fila. No se tocaron algoritmos A/B/C/D, Sticker Studio, reglas de reservas/Pedidos ni datos operativos.

Control final de datos protegidos: `visionvault.db` conserva SHA-256 `f6abfb14fedfefb99653fa0928e1010cb1d8bd30da7955a7bc3ac4eb0a9340f2`; la tanda física `physical-pending.db` conserva `c5457335c8ae472e7c00b38d1b827c8bb50276c35f5796cb80aab79a16d01e0c`. No se ejecutó impresión física ni se acreditaron unidades impresas/terminadas.

## Archivos de este sprint

- `app/planchas/output_safety.py`: preflight, errores, escrituras atómicas, staging/publicación de conjunto y comunicación de fallos en acciones del editor.
- `app/planchas/model.py`: persistencia de configuración, carga/guardado de conjuntos y rechazo explícito de paginación incompleta; sin cambiar estrategias ni capacidad del packing.
- `app/planchas/editor.py`: integración de validación, exportación segura, recuperación fiel, preferencias persistidas y envío de impresión estricto.
- `app/planchas/production_geometry.py`: contrato de perfiles y cálculo de píxeles calibrados; constantes existentes conservadas.
- `app/printing/windows_print.py`: importa la fuente única y admite el modo estricto solicitado por el Creador. No se editaron perfiles del driver.
- `tests/test_creator_sprint1_safety.py`: 30 casos nuevos de seguridad/compatibilidad.
- `tools/validate_creator_sprint1.py`: evidencia reproducible exclusivamente ficticia; este informe y artefactos relacionados.

## Contrato de persistencia y compatibilidad

El proyecto mantiene orden de ítems, identidades/copias, dimensiones, coordenadas, rotación, cantidades, formato, modo y opciones guardadas. `gap_cm` y `margin_cm` se restauran sin sustituirlos por defaults actuales. Parámetros ausentes en documentos históricos usan los defaults compatibles: margen A4 0,15 cm (A5 0,05) y gap 0,05; valores explícitos inválidos se informan, no se corrigen silenciosamente.

Preferencias de impresión/corte y metadatos adicionales se conservan; perfiles históricos sin snapshot siguen usando la configuración global existente, porque no es posible reconstruir valores que nunca se guardaron. No se inventa una calibración histórica. Los manifiestos no embeben los archivos originales: siguen dependiendo de sus rutas y las verifican antes de una salida.

Prueba obligatoria ejecutada por dos vías complementarias: proyecto con margen/gap personalizados y perfil guardado, perfil global diferente al recuperar, igualdad completa de snapshots y píxeles; además una reapertura desde un proceso Python nuevo compara dimensiones y hash raster. No se ejecutó un reinicio interactivo de toda la aplicación Windows; no se atribuye esa cobertura a la prueba de proceso.

## Escala y calibración: recorrido completo

1. **Producto lógico:** nominal comercial en cm. La preparación productiva existente puede compensar el nominal mediante `(nominal + 2×inset_cm) / PRINT_SCALE`; es una estimación de tamaño preparado, no una segunda operación de escalado de impresora.
2. **Distribución/documento:** coordenadas y tamaños preparados en cm. PNG A4 21×29,7 cm a 300 DPI, 2480×3508 px por redondeo. La exportación no multiplica el lienzo por 0,9727.
3. **Perfil:** 100 % histórico describe escala lógica/documental; 97,27 % describe la compensación vigente. Se admiten ambos perfiles conocidos sin convertir uno en el otro. Valores desconocidos requieren revisión explícita.
4. **Backend:** `production_geometry.PRINT_SCALE = 0.9727` es la fuente única. Desde Creador se calcula `px_destino = px_origen × dpi_driver / dpi_origen × 0.9727` una vez. Una hoja A4 2480×3508 px a driver 600 DPI resulta en **4825×6824 px**, antes de offsets/centrado del dispositivo. Un área inferior provoca error, no otra reducción.
5. **Corte:** `CUT_INSET_MM = 1.50`, sin cambios. Estimación final existente: `producción_cm × 0.9727 − 0.30 cm`. Brother debe ser confirmado físicamente por el operador.

DEVMODE, opciones internas del driver, alimentación, papel y escaneo/corte no se homologan con un test Python. No se imprimió ni cortó; no se modificaron calibraciones Epson L3210/Brother ScanNCut X225. El modo estricto puede bloquear un perfil que antes se reducía automáticamente: es un rechazo deliberado para preservar escala, no una recalibración.

## Conciliación de unidades y fallos

La paginación conserva el contrato de lista en casos válidos y genera páginas hasta colocar todas las unidades. Si hay remanentes imposibles, levanta `PaginationError` con informe; no devuelve una lista aparentemente completa. El editor conserva el error y bloquea exportar ese armado como completo. El servicio de tandas recibe el rechazo antes de guardar sus reservas. La ruta de Mixta conserva su reporte de imposibles existente.

Fuentes inválidas se clasifican en preflight; materiales/unidades incompatibles continúan siendo bloqueados por el servicio de tandas existente. El paginador geométrico no inventa ni decide material. Se diferencian pieza físicamente demasiado grande para A4, incompatibilidad de márgenes y restricción de formato/franja o fallo de distribución. No se ofrece una salida parcial implícita ni se descartan unidades para hacer pasar el lote.

Preflight y salida fallida registran el motivo en logging. No liberan, consumen ni cambian reservas. Uso/estado/PNG final se actualizan sólo después de la escritura satisfactoria. La prueba de integración crea tres reservas `prepared` reales en una **base aislada** y verifica un dump SQLite idéntico después de un fallo de fuente. Enviar a spool no se convirtió en impresión física: se conserva el flujo de confirmación existente.

## Evidencias geométricas

`artifacts/creator-s1-acceptance-20261023/`:

- `project.json`: seis diseños ficticios con margen 0,30 cm y gap 0,12 cm.
- `before.png` y `after.png`: A4 300 DPI antes y después de guardar/recuperar.
- `observations.json`: snapshots, calibración, dimensiones y rechazo de pieza 30×30 cm.

SHA-256 de los píxeles RGBA en ambas imágenes:

`fe7ec16266aafc7fe37df9db2575596506a5c8b1566d038f414d0f1de1ad8bc2`

No son capturas de UI ni pruebas físicas: son renderizados del mismo motor usado en exportación.

## Pruebas

- Nuevas pruebas de seguridad: **30 aprobadas**. Archivo faltante, corrupto, acceso denegado simulado, transparente/vacío, lote parcialmente válido, errores de escritura/sustitución, recuperación, histórico sin campos vs cero explícito, manifiesto multipágina, escala válida/desconocida, rechazo de segundo fit, piezas imposibles, 50/100/200, reservas, archivo anterior y reapertura en proceso nuevo.
- Matriz focalizada definitiva: **142 aprobadas**, 19,88 s; `artifacts/creator-s1-focused-release.xml`. Incluye última fila, filas completas, modos libre/mixto, paginación, geometría, reservas, trazabilidad y utilidades de calibración. 77 advertencias preexistentes de deprecación Pillow en caminos de render.
- Primera ejecución general intermedia: **1283 aprobadas**, 1 omitida, 5 subtests aprobados; 265,87 s. No acredita los refuerzos posteriores.
- Una repetición intermedia se interrumpió para reiniciar con la fuente de escala unificada. No se contabiliza como suite completa aprobada.
- Suite general definitiva: **1289 aprobadas, 1 omitida, 5 subtests aprobados, 0 fallos**, 261,42 s; `artifacts/creator-s1-release.xml`. Las 81 advertencias corresponden a deprecaciones Pillow y tests preexistentes que retornan valores; no se ocultaron fallos ni se modificaron pruebas ajenas para lograr el resultado.

## Límites y aceptación

No hay transacción distribuida entre disco y SQLite ni garantía frente a pérdida eléctrica; se usan staging, sustitución atómica por archivo y restauración ante fallos recuperables. Un fallo extraordinario de restauración del sistema de archivos requiere intervención; no se declara atomicidad ACID de múltiples archivos.

El guardado de metadatos SQLite del conjunto sigue usando los servicios existentes. Un fallo de base después de generar los archivos puede requerir reconciliar registros; no se reescribió el módulo de Producción ni su política transaccional en este sprint. No se promueve automáticamente una tanda incompleta.

No se agregó búsqueda automática de rutas: no había un mecanismo específico de relocalización en este editor para reutilizar. El error muestra la ruta para corregir la fuente de manera explícita. No se recuperan datos de configuración histórica que nunca existieron.

Dictamen: **Sprint 1 aceptado técnicamente**, con aceptación dimensional física pendiente del operador en Epson L3210/Brother ScanNCut X225. Las cuatro causas auditadas tienen corrección y pruebas, la última fila y las integraciones existentes conservan sus regresiones, y las exportaciones antes/después tienen geometría y píxeles idénticos. No se declara homologación física ni se cambian constantes de calibración. No se inicia otro sprint ni se publica esta rama.
