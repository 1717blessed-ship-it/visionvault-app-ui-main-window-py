# Creador de Planchas 2.0 — preparación de homologación

Fecha: 2026-10-24. Rama comprobada: codex/creador-planchas-s2-optimizacion.

## Dictamen

Preparación digital completada; homologación física pendiente de mediciones y aprobación del operador. No se imprimió, cortó, publicó ni etiquetó. No se modificaron algoritmos, calibraciones, Sticker Studio, Pedidos, Mobile ni estados productivos reales. Se añadieron un generador diagnóstico, archivos ficticios, una base aislada y documentación; se preservaron los cambios preexistentes del árbol de trabajo.

## Evidencia automatizada actual

Se ejecutaron 172 pruebas pertinentes: **172 aprobadas, cero fallos**, 245 advertencias, 23,86 segundos. Evidencia: artifacts/physical-validation-regression.xml. Incluye seguridad Sprint 1, distribución Sprint 2, última fila, bandas/paginación, cantidades, geometría de preview, conversión libre, tamaños productivos, trazabilidad/reservas y calibración. Las protecciones de Sprint 1 están presentes y sus regresiones pasan: preflight y salida segura, persistencia de opciones/geometría, rechazo de piezas imposibles y bloqueo del segundo ajuste automático en impresión estricta. La última fila regular permanece a la izquierda con separación normal.

Las 1319 pruebas generales aprobadas son el resultado previamente reportado de Sprint 2, **no una nueva ejecución general en esta entrega**. No se modificó código productivo en esta preparación.

El generador utilizó los servicios/modelos/renderizador existentes. Comprobó conservación exacta de IDs, copias, fuentes y dimensiones; validación de layout sin solapes y dentro de límites; geometría de preview inmutable durante exportación; ocho PNG A4 válidos. Esto acredita geometría digital, no equivalencia física del controlador ni precisión del corte. La vista previa de aplicación no fue homologada visualmente en hardware en esta etapa. La hoja diagnóstica PNG final se inspeccionó visualmente y sus reglas son una superposición adicional documentada, no parte del JSON de stickers.

| Conjunto idéntico de 100 unidades | Normal | Optimizado |
|---|---:|---:|
| Hojas | 4 | 3 |
| Unidades por hoja | 20, 23, 32, 25 | 24, 44, 32 |
| Unidades pendientes/imposibles | 0 / 0 | 0 / 0 |
| Ocupación informada por distribuidor | 51,70 % | 68,93 % |

Reducción de hojas: 25 %. Diseños ficticios mixtos de cajas 4,8 × 4,8; 3,2 × 3; 2,4 × 2 cm. No equivale a una promesa de capacidad comercial de stickers nominales de 5 cm. Las posiciones pueden variar; las cantidades y dimensiones no.

## Configuración y material pendiente

Se leyó printing_config de visionvault.db en modo SQLite de solo lectura. Perfil vigente: SUBLIMACIÓN EPSON L3210, A4 vertical, Alta, Color, 97,27 %, 2 copias. Se copió a la base aislada, incluyendo DEVMODE sin modificarlo. Inventario Get-Printer: tres colas Epson L3210 con estado Normal; detalles y hash de perfil en artifacts/creator-physical-validation-20261024/validation-manifest.json.

Riesgo concreto: confirmar que la cola denominada SUBLIMACIÓN y su tinta/material son adecuadas para adhesivos. No se seleccionó una cola fotográfica por inferencia. Las opciones internas del controlador aún no están verificadas físicamente. Con dos copias, el juego de ocho archivos consume 16 hojas; debe confirmarse antes de enviar.

Se conservan factor 0,9727, 300 DPI y cut inset 1,5 mm; no hay segunda reducción. Reglas diagnósticas de 50 mm impresos compensadas localmente y referencia documental de 50 mm cuyo esperado impreso es 48,635 mm. Se documenta cuantización de píxeles, sin inventar mediciones. No hay archivo propietario ni ejecución de corte ScanNCut validada.

## Protección de bases y estados

Los SHA-256 de visionvault.db y artifacts/acceptance-s3-20261023/physical-pending.db coincidieron antes/después; valores completos en el manifiesto. No se invocaron migraciones ni escrituras sobre ellas. La tanda de tres unidades conserva tres asignaciones prepared, suma 3 y cero print_jobs.

Nueva base: artifacts/creator-physical-validation-20261024/homologation-isolated.db. Contiene ocho planchas ficticias, cero asignaciones de pedidos y cero print_jobs. No reemplaza la base operativa ni reserva producción. La ficha exige contrastar posteriormente los estados con operaciones realmente confirmadas; hoy no se marca nada impreso ni terminado.

## Entregables y pendientes

Carpeta artifacts/creator-physical-validation-20261024: una hoja A4 diagnóstica, cuatro PNG normales, tres optimizados, proyectos individuales y maestros, configuración, perfil de controlador copiado, manifiesto con hashes, base aislada, LEEME-HOMOLOGACION.md, FICHA-OPERADOR.md y operator-results.json con mediciones nulas.

No se encontraron fallos en las regresiones ejecutadas ni discrepancias geométricas en el conjunto generado. Permanecen pendientes: validación de perfil/material, escala X/Y real, desplazamiento y márgenes reales, contornos y repetibilidad del corte, pérdidas/daños, comparación física A/B y fotografías. Ningún valor esperado del informe es una medición realizada.

Recomendación: Sprint 1 y Sprint 2 tienen evidencia técnica favorable para promoción condicionada. No declarar listo para producción diaria ni homologado con Epson L3210/ScanNCut X225 hasta completar la ficha y resolver cualquier desviación. Mantener normal como predeterminado y optimización opcional; no iniciar nuevas funcionalidades ni publicar/etiquetar automáticamente.
