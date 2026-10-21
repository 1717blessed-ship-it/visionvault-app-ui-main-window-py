# Sticker Studio 2.0 — aceptación productiva final

Versión candidata: **2.0.0-rc.1**  
Fecha: 20 de octubre de 2026  
Estado global: **APROBADO PARA USO ASISTIDO**

Esta homologación congela nuevas funcionalidades. No se declara reemplazo total
del editor clásico ni disponibilidad productiva sin asistencia hasta completar
la aprobación visual P1 y la prueba física de impresión/corte.

## Tabla de aceptación

| Subsistema | Estado | Evidencia / condición |
|---|---|---|
| Pipeline A/B/C/D | APROBADO | 20/20 entradas procesadas sin excepción; rutas y calibraciones no modificadas durante la homologación. |
| Master, vista Final y exportación | APROBADO | Vista Final enlazada al master; 20/20 exportaciones con SHA-256 idéntico al master. |
| Contracción, expansión y edición manual | APROBADO PARA USO ASISTIDO | Regresión automatizada aprobada; la calidad de la silueta debe revisarse antes de marcar el master. |
| Deshacer/rehacer | APROBADO | Historial independiente por sticker y rama redo invalidada tras una edición nueva. |
| Revisión vinculada al master | APROBADO | La revisión utiliza SHA-256; reprocesar o editar invalida revisión y envío previos. |
| Exportar sin publicar | APROBADO | Flujo automatizado y contrato byte a byte verificados. |
| Últimos Procesados | APROBADO | Envío idempotente, sin retirar el trabajo de la sesión ni borrar sus artefactos al quitarlo de la bandeja. |
| Sesión, cancelación y reintento | APROBADO | Respaldo verificable; cancelación cooperativa al 35 % y reintento correcto. |
| Navegación Windows | APROBADO PARA USO ASISTIDO | Métricas locales favorables; falta una sesión ergonómica prolongada con mouse/touchpad del operador. |
| Máscara real disco 421×421 | PENDIENTE DE VALIDACIÓN HUMANA | Candidata disponible; `human_approved` permanece `false`. |
| Máscara real estrellas 600×600 | PENDIENTE DE VALIDACIÓN HUMANA | Candidata disponible; `human_approved` permanece `false`. |
| Hoja A4, impresión y ScanNCut | PENDIENTE DE VALIDACIÓN HUMANA | PDF preparado; faltan impresión al 100 %, medición y corte físico. |
| Sustitución definitiva del editor clásico | BLOQUEADO | Depende de aprobar los dos puntos anteriores. El retorno al editor clásico permanece disponible. |

## Validación de 20 imágenes preservadas

Se reutilizó el conjunto preservado del Sprint 1.5, sin volver a reescalar ni
crear entradas. Son derivados de carga de contenido real, entre 360.000 y
4.000.000 píxeles. No equivalen a veinte diseños únicos: contienen diez fuentes
repetidas a dos escalas/ciclos, circunstancia registrada para no presentar el
lote como una diversidad que no tiene.

- Procesadas correctamente: **20/20**.
- Errores de ejecución: **0**.
- Master RGBA y exportación comparados: **20/20 idénticos por SHA-256**.
- Clasificación automática: **6 Listo, 10 Revisar y 4 Error de calidad**.
  Los cuatro `Error` no fueron excepciones del proceso: generaron master y
  export idénticos, pero deben permanecer bloqueados para revisión humana.
- Tiempo de apertura/decodificación del lote: **0,3316 s**.
- Tiempo de procesamiento: **38,8602 s**.
- CPU acumulada: **57,7656 s**, equivalente promedio a **148,6 % de un núcleo**.
- Cancelación cooperativa: correcta.
- Reintento posterior: correcto en **3,8785 s**.
- Ningún resultado fue aprobado automáticamente.

El detalle por archivo está en
`artifacts/sticker-studio-production-candidate/acceptance_metrics.json`.

## Rendimiento del proceso en Windows

| Métrica | Resultado |
|---|---:|
| Working set antes de cargar | 45,26 MB |
| Pico real de working set | 462,27 MB |
| Working set después de liberar y ejecutar GC | 64,62 MB |
| Memoria retenida sobre la línea base | 19,36 MB |
| Cambio/decodificación de 20 previews | 0,1025 s |
| Promedio por cambio de preview | 5,124 ms |
| Paneo optimizado, 30 movimientos 2000×2000 | 16,515 ms |
| Zoom agrupado, 20 eventos 2000×2000 | 71,144 ms |

El monitor utilizó el working set nativo de Windows del proceso real. La mejora
de interacción queda demostrada por tiempos, pero la sensación subjetiva con el
mouse/touchpad y una sesión prolongada aún requiere al operador. El intento de
inspección dinámica adicional mediante el controlador de ventanas quedó
bloqueado porque su runtime local no pudo inicializar sus recursos; esto no se
confundió con un fallo del editor.

## Congelación y respaldo

- El código candidato se registra como `2.0.0-rc.1` en un commit específico.
- Editor clásico: preservado.
- Perfil por defecto registrado sin alteración automática: 300 ppp, master
  5,70 cm, escala de impresión 0,9727, inset de corte 1,0 mm y borde final 30 px.
- Se respaldaron `ui_settings.json`, la sesión V2 y 413 perfiles de producción:
  **415 archivos** en total.
- Cada archivo posee SHA-256 en
  `artifacts/sticker-studio-production-candidate/freeze-backup/SHA256SUMS.txt`.
- Manifiesto completo:
  `artifacts/sticker-studio-production-candidate/freeze-backup/manifest.json`.

## P1 visual: procedimiento de aprobación humana

Abrir cada carpeta bajo
`artifacts/sticker-studio-sprint15/p1-human-review/` y comparar, en este orden:

1. `original.png`.
2. `automatic_mask.png`.
3. `corrected_mask_candidate_unapproved.png`.
4. `cut_contour.png`.
5. `final_png_candidate_unapproved.png` sobre blanco, negro y magenta.

Para el disco, revisar halo gris exterior, cuatro estrellas, puntas, conexiones,
borde blanco real y reflejos interiores. Para estrellas 600×600, revisar puntas,
separaciones, semitransparencia y acumulación de borde. Sólo la acción explícita
del usuario puede cambiar el estado de `human_approved: false`.

## Protocolo físico A4 / Brother ScanNCut X225

Archivo:
`output/pdf/sticker_studio_sprint15_a4_physical_validation.pdf`.

1. No modificar compensaciones ni perfiles.
2. Imprimir en tamaño real/100 %, desactivar “Ajustar”, “Escalar” y márgenes del
   controlador. Registrar impresora, controlador, papel y orientación.
3. Medir la regla incluida con calibre o regla milimetrada: nominal **50,00 mm**.
4. Medir los seis stickers en ambos ejes: nominal **57,00 mm**.
5. Registrar diferencia firmada, no corregir todavía.
6. Cargar la misma hoja en Brother ScanNCut X225, ejecutar escaneo y corte con
   las compensaciones vigentes.
7. Medir desplazamiento X/Y y separación del corte respecto del borde.
8. Clasificar el origen probable: archivo/PDF, controlador de impresión,
   alimentación del papel o sistema de corte.
9. Sólo después de obtener mediciones repetibles decidir una compensación.

## Regresión

La suite general del mismo código de aplicación registró:

```text
1174 passed, 1 skipped, 4 warnings, 5 subtests passed in 232.14s
```

La omisión corresponde al conjunto externo shield1.png…shield5.png ausente. Las
cuatro advertencias son `PytestReturnNotNoneWarning` históricas. Los scripts de
homologación se compilaron y ejecutaron correctamente.

## Decisión

Sticker Studio 2.0 puede utilizarse en **modo asistido**, conservando el editor
clásico como respaldo y exigiendo revisión humana antes de exportar casos
ambiguos. El reemplazo definitivo del clásico permanece bloqueado hasta:

1. aprobación humana del disco 421×421 y estrellas 600×600;
2. impresión A4 medida al 100 %;
3. corte real con Brother ScanNCut X225;
4. firma de aceptación del operador.

