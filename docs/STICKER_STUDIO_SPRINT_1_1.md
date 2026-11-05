# Sticker Studio 2.0 — Sprint 1.1

Fecha: 2026-10-19. Estado: integración estabilizada; P1 visual pendiente de
referencia humana; producción no aprobada.

## Fuentes reales disponibles

- `artifacts/sticker-disc-human-review/original.png`: 421 × 421, RGBA opaco,
  damero incrustado, esfera y cuatro estrellas.
- `artifacts/sticker-disc-human-review/visual_support_600_OPAQUE.png`: 600 ×
  600, RGBA opaco sobre blanco. Es el apoyo de mayor resolución del mismo
  diseño cromado; no es un alfa original ni una máscara aprobada.

No apareció un tercer original independiente de “estrellas cromadas”. La bola
disco reportada y el archivo de 421 × 421 son el mismo caso. Tampoco existe
`mask_reviewed.png` con aprobación humana. Por ello no se declara validada la
eliminación exacta del halo del P1.

## Causas raíz y correcciones

1. **Diferencias entre corridas idénticas.** Las tres llamadas a GrabCut
   dependían del RNG global de OpenCV. Se fija una semilla antes de cada llamada.
   Dos ejecuciones independientes, clásico y V2, producen ahora el mismo caso,
   perfil, tamaño, SHA-256 y cero píxeles diferentes.
2. **Exportación V2 ambigua.** El botón superior llamaba al flujo de aprobación,
   pero no exportaba un archivo. Ahora `Exportar final` copia byte a byte el
   artefacto `master` que usa la vista Final. No recompone, redimensiona ni
   cambia el DPI. La aprobación continúa separada y explícita en el inspector.
3. **Posible mezcla de configuración en una cola.** Borde físico y calidad se
   guardan en el job y su snapshot se aplica inmediatamente antes de la corrida
   serial. Cambiar de miniatura no modifica un trabajo que ya está procesándose.
4. **Política implícita de borde.** Se añadió una decisión común, separada de
   A/B/C/D: Automático, Conservar y limpiar, Reemplazar y Agregar nuevo. Queda
   persistida en metadata y parámetros de reproceso.
5. **Contorno duplicado en casos ambiguos.** Agregar se bloquea cuando ya existe
   un aro blanco. Reemplazar sólo retira blanco exterior conectado, limitado por
   profundidad, y vuelve a conservación si no puede aislar el borde. Si además
   el halo requiere revisión, no intenta reemplazar automáticamente. No hay
   erosión global, blanqueamiento general ni cambio de las rutas técnicas.

## Evidencia real

Carpeta: `artifacts/sticker-studio-sprint11/`.

Cada fuente tiene cuatro corridas, sus artefactos intermedios completos,
`exported_final.png` y composiciones sobre blanco, negro, gris y magenta.
`treatments_on_magenta.png` compara Automático, Conservar, Reemplazar y Agregar.
`audit.json` registra fuentes, hashes, clasificación, decisión de borde, halo,
alfa, transparencia y correspondencia exacta entre master/exportación.

Resultados de los casos reales:

- Todas las exportaciones son RGBA con alfa `(0,255)` y byte a byte iguales al
  master mostrado por V2.
- Automático y Conservar preservan el borde existente.
- Reemplazar queda en `Conservar y limpiar / requires_review` porque el halo es
  ambiguo; no produce el borde acumulado observado durante el diagnóstico.
- Agregar queda en `Conservar y limpiar / requires_review` porque ya existe un
  borde; no suma 30 px.
- La salida nativa registra `border_px=0` en estas decisiones conservadoras.
- Esfera y cuatro estrellas permanecen visibles. Las irregularidades finas del
  original de 421 × 421 siguen pendientes de una referencia trazada/aprobada.

## Clásico frente a V2

Ambos llaman al mismo `StickerProcessor`. V2 sólo selecciona artefactos reales:
Original=`source_path`, Máscara=`mask_editable/mask`, Resultado=`design_layer`
y Final=`master`. La comparación diferencial se ejecutó en dos workspaces
independientes con el mismo original y perfil:

- misma clasificación C;
- mismo perfil y 673 × 673;
- SHA-256 idéntico;
- cero píxeles distintos.

El editor clásico continúa disponible con `DOCCIONE_STICKER_STUDIO=classic`.
No se cambiaron perfiles, geometría de planchas, compensación de impresión,
inset de corte ni rutas A/B/C/D.

## Pruebas

- Focales: tratamiento de borde, originales reales, halo, V2, creador e
  hardening, todas aprobadas.
- Suite general: **1130 passed, 1 skipped, 4 warnings, 5 subtests passed** en
  256,69 s.
- La omisión externa y las cuatro advertencias históricas de tests que retornan
  booleanos permanecen sin cambios.

## Pendientes

- Crear y aprobar humanamente `mask_reviewed.png` de 421 × 421, comparar por
  regiones y reprocesar mediante `mask_override`.
- Validar físicamente espesor y corte impresos.
- Conseguir un original independiente si “estrellas cromadas 600 × 600” se
  refería a otro archivo distinto del apoyo de la bola disco.

El sistema evita ahora empeorar el caso ambiguo, pero eso no demuestra que cada
píxel del halo haya sido eliminado. **P1 pendiente; no listo para producción.**

