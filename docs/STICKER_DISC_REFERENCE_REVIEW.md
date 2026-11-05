# Disco: procedimiento de referencia humana (VV-05)

Estado: **PENDIENTE DE REVISIÓN HUMANA**. No existe todavía una referencia alfa
aprobada. No continuar modificando la limpieza automática de este caso.

## Material preparado

Carpeta: `artifacts/sticker-disc-human-review/`.

- `original.png`: copia exacta de la fuente de pruebas, **421 × 421**, alfa 255
  en todos los píxeles. Contiene damero RGB incrustado.
- `visual_support_600_OPAQUE.png`: mismo diseño de 600 × 600 sobre fondo claro.
  Es apoyo visual, **no alfa real ni máscara de referencia**.
- `automatic_proposal_NOT_REFERENCE.png`: alfa automático actual, solo propuesta.
- `rejected_candidate_NOT_REFERENCE.png`: candidato más amplio descartado.
- [Comparativa de revisión](../artifacts/sticker-disc-human-review/review_comparison.png).
- `algorithm_disagreement_NOT_ERROR_MAP.png` y `region_*_200pct.png`: magenta
  indica desacuerdo de algoritmos, **no píxeles demostrados como incorrectos**.
- `packet.json`: fuente, hash, dimensiones y seis regiones de desacuerdo.
- `approval_PENDING.json`: declaración de revisión **sin aprobar**. No se creó
  `mask_reviewed.png` ni una supuesta verdad de referencia a partir de la automática.
- `search_audit.json`: alcance y resultados de búsqueda de originales.

La fuente real del banco es `tests/fixtures/sticker_regression/disco_checker.png`;
su SHA-256 es `0d84cf0c255870106b608ad18d3819c6aae187d3bec5caca45ce31e50c968221`.
Los resultados actuales y rutas de máscaras están en el caso 04-B de
`artifacts/sticker-closure-final/manifest.json`. No editar esos archivos para
fabricar una referencia ni usar máscaras de maestro recortadas/reducidas.

## Qué debe decidir el revisor

### Intención confirmada por el usuario

La esfera, **cuatro estrellas** (grande superior derecha, pequeña izquierda y
dos inferiores derechas), el borde blanco y sus conexiones legítimas pertenecen
al sticker terminado. No recortar solo la esfera ni retirar el borde para alisar
la silueta. Conservar entrantes externos entre elementos; no rellenarlos como
si fueran agujeros internos. El patrón plateado interior es decoración, no fondo.

El fixture de 421×421 contiene además un damero **en el exterior**, visible en
el marco, y sigue clasificado `damero_incrustado`. La copia de 600×600 tiene fondo
claro uniforme y puede evaluarse como sticker terminado sobre fondo uniforme.
Son dos fondos distintos del mismo diseño: la intención del usuario no cambia
los píxeles de la captura. No se alteró el clasificador ni las expectativas históricas.

Conservar reflejos blancos, grises y negros internos, las facetas angulares,
las estrellas y su silueta deliberada. Un píxel gris del metal no representa
transparencia. Las puntas de estrellas no son ruido. El borde blanco visible en
la versión de apoyo puede ser parte intencional del sticker; no confundirlo con
una celda blanca del damero. La sombra/línea gris es además el P2 registrado:
no intentar borrarla mediante erosión global en esta revisión.

Las motas o escalones exteriores que no siguen el borde del original son
sospechosos de segmentación, pero su decisión final requiere revisar cada zona,
especialmente uniones esfera/estrellas y adornos inferiores. No imponer un círculo
perfecto. No convertir brillos internos en agujeros; solo dejar huecos respaldados
por el espacio negativo real del diseño.

## Construcción manual, sin usar una máscara automática como verdad

1. Abrir la copia **421 × 421** sin recortarla, rotarla ni reescalarla. Usar la
   versión de 600 × 600 solo para observar detalles: no trasplantar su máscara
   por resize. La correspondencia geométrica aproximada no garantiza alfa exacto.
   Se preparó `manual_reference_TEMPLATE_NOT_MASK.svg`: documento editable de
   421×421 con la fuente como guía y una capa de trazado **vacía**. No es una
   máscara, no contiene un contorno aprobado y no debe usarse como `mask_override`.
   Abrirlo en un editor vectorial compatible, mantener el tamaño de página y
   trazar a mano en `human-traced-foreground-EMPTY`. Para exportar la máscara,
   ocultar `source-guide-NOT-MASK`, mostrar `mask-background` y exportar PNG
   de la página completa a exactamente 421×421; convertirlo a L sin umbralizar
   los grises de antialiasing. Verificar dimensiones antes de revisarlo/aprobarlo.
2. Crear una máscara nueva L de 421 × 421 (negro = fondo, blanco = conservar).
   Trazar manualmente la silueta del objeto y el borde intencional sobre la fuente.
   Mantener el RGB original en una capa separada, bloqueada.
3. Alternativamente, usar la acción existente **Corregir silueta** del creador.
   Esta abre `mask_editable` contra `source_editable`, no contra el maestro con
   padding. La automática puede ser un borrador, pero se exige revisar toda la
   silueta: conservar píxeles por defecto no equivale a aprobarlos como referencia.
4. Pincel/lazo y recuperar/quitar deben operar únicamente sobre alfa. Conservar
   todos los reflejos del interior. Resolver cada región magenta mirando el
   original y el apoyo claro, no por mayoría entre dos algoritmos.
5. Trabajar al 100/200 % en blanco, negro y damero generado. Conservar una
   transición alfa parcial cuando el borde realmente la requiera; no binarizar
   la referencia ni inferir opacidad a partir de la luminosidad del metal.
6. Guardar el borrador por separado como `mask_reviewed.png`, formato L PNG o
   RGBA cuyo canal A sea la máscara. **421 × 421 exactos**. No usar JPG, RGB plano,
   miniatura, máscara de corte ni una exportación física como referencia de alfa.
7. Una persona revisa y acepta expresamente silueta, borde blanco, estrellas,
   huecos y antialiasing. Registrar en notas cualquier zona aún ambigua. Si hay
   dudas sin resolver, conservar `approved=false`: la referencia no está validada.

El editor ya guarda la corrección como máscara manual separada y la entrega al
reprocesado mediante `mask_override`. No se añadió ni cambió una herramienta de
edición. El historial, el original y el resultado automático permanecen separados.

## Aprobación de la referencia, distinta de aprobación de producción

Después de la revisión humana, copiar `approval_PENDING.json` a `approval.json`.
La persona completa `reviewer`, `reviewed_at` (ISO con zona, por ejemplo
`2026-10-17T18:00:00-03:00`, usando su fecha real), notas y `mask_sha256`. Mantener
el hash de fuente, dimensiones y `coordinate_space="source"`. Solo entonces
cambiar `approved` a `true`. El asistente no lo hace automáticamente.

Para obtener el hash de la máscara guardada:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath 'artifacts/sticker-disc-human-review/mask_reviewed.png'
```

La declaración es un registro local del revisor, no una firma digital que
autentique por sí sola su identidad. Aprobar esta referencia NO aprueba impresión
ni corte. Si la máscara cambia, la aprobación anterior queda invalidada por hash.

## Comparación, únicamente cuando exista aprobación válida

```powershell
python -m scripts.sticker_reference_review compare --source artifacts/sticker-disc-human-review/original.png --automatic artifacts/sticker-disc-human-review/automatic_proposal_NOT_REFERENCE.png --approval artifacts/sticker-disc-human-review/approval.json --output artifacts/sticker-disc-reference-comparison-1
```

La herramienta rechaza aprobación ausente/falsa, revisor o fecha ausentes, hash
distinto, fuente ajena, máscara vacía y dimensiones desalineadas. No reescala una
referencia para hacerla coincidir. No se ejecutó esta comparación real todavía.

Resultados previstos: IoU de foreground, error absoluto del alfa, píxeles perdidos
y extra, diferencias de alfa parcial, precisión/recall de contorno a tolerancia
1 px, distancias simétricas p95/máxima y regiones conectadas de diferencia.
`difference_regions` usa umbral de diferencia >8 niveles alfa; el error medio
incluye todos los píxeles. El mapa marca rojo=contenido faltante, verde=exceso,
amarillo=diferencia alfa, y guarda zooms 200 % por región. No decidir con IoU solo:
un detalle fino puede fallar aunque la métrica global sea alta.

Con la misma aprobación se podrán comparar por separado la extracción inicial
`checkerboard_initial_alpha` y `mask_editable`, ambas en coordenadas fuente:

- Diferencia ya presente en extracción inicial: segmentación/fondo.
- Diferencia introducida después: limpieza del alfa.
- Alfa visual correcto pero borde/base incorrectos: construcción de base.
- Base correcta pero corte incorrecto: geometría de corte/perfil.

El corte nativo está en otro lienzo y DPI: no compararlo directamente con el alfa
fuente ni estirarlo para obtener una métrica artificial. Examinarlo por separado
con su superposición y parámetros físicos, que permanecen intactos.

Una vez validada la referencia, aplicar el cambio mínimo apoyado en regiones
demostradas. Si basta con una corrección manual, conservar su archivo y ruta en
los parámetros de reprocesamiento del resultado; reutilizar esa misma máscara,
no regenerarla con la limpieza automática. Verificar después guardado, reapertura,
reprocesamiento, contorno y resolución original antes de publicar.

**P1 pendiente de revisión humana. Dos P2 registrados. Producción no aprobada.**

## Vistas después del trazado humano

No hay aún resultado transparente derivado de una referencia revisada. Una vez
guardado el borrador, componer el RGB original con **ese alfa**, sin extraer el
brillo como transparencia, y comprobar blanco, negro y un color contrastante
(verde o azul), además del damero generado. Rotular estas vistas como borrador
no aprobado hasta la revisión humana. Comparar base imprimible y trayectoria
con el resultado reprocesado por máscara manual, conservando parámetros físicos.
No exportar la imagen guía con el damero como si fuera un resultado transparente.
