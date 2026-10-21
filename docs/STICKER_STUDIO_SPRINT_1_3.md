# Sticker Studio 2.0 — Sprint 1.3

## Estado

La edición manual de máscara está implementada y validada técnicamente. El P1
del disco continúa **pendiente de aprobación visual humana** y el módulo no se
declara listo para producción.

## Implementación

- `app/stickers/mask_editing.py`: documento no destructivo de operaciones,
  trazos restaurar/borrar/proteger/refinar, persistencia JSON, undo/redo,
  materialización y aprobación explícita de referencia.
- `app/stickers/mask_contraction.py`: desplazamiento firmado compartido; el
  signo negativo implementa expansión con cobertura subpíxel.
- `app/stickers/pipeline.py`: etapa A/B/C/D compartida para contracción y
  expansión; respeta máscara de protección y persiste los parámetros.
- `app/stickers/editor.py`: transmite expansión y protección por trabajo.
- `app/stickers/editor_v2/canvas.py`: convierte pantalla a coordenadas exactas
  de imagen, registra trazos y renderiza máscara/PNG inmediatamente.
- `app/stickers/editor_v2/components.py`: herramientas, tamaño, dureza,
  opacidad, expansión, undo/redo y un inspector desplazable.
- `app/stickers/editor_v2/window.py`: aislamiento por sticker, persistencia,
  reprocesamiento desde base, materialización y aprobación humana.

El original nunca se escribe. Cada trabajo conserva una base alfa inmutable y
un historial de operaciones. Reprocesar vuelve a evaluar base + operaciones +
parámetros, sin pintar sobre la salida anterior. Si el hash o las dimensiones
de la base cambian, los trazos incompatibles no se reutilizan y la interfaz lo
advierte.

## Referencia humana

`Aprobar máscara de referencia` abre una confirmación explícita. Sólo después
de aceptar se escriben `approved_reference.png` y su manifiesto con hashes del
original y de la máscara. En ese momento también se compara contra la máscara
automática mediante IoU, error alfa, áreas, componentes, detalles perdidos y
restaurados, diferencia de borde y una lámina ampliada. El algoritmo nunca
aprueba la referencia.

## Validación

Pruebas focalizadas finales: **27 aprobadas**.

Suite completa final: **1150 aprobadas, 1 omitida, 5 subpruebas aprobadas y 4
advertencias históricas**.

Las pruebas cubren coordenadas de imagen, restauración, borrado, dureza,
opacidad, protección, expansión, refinamiento, undo/redo, independencia entre
stickers, persistencia, determinismo, aprobación explícita y comparación de
referencia.

## Evidencias

`artifacts/sticker-mask-editor-sprint13/` contiene:

- captura real del Canvas V2;
- originales 421×421 y 600×600;
- máscara base y documento de demostración no aprobado;
- candidatos PNG y máscaras para 0, 0,1, 0,2 y 0,5 mm;
- composiciones sobre negro y magenta;
- comparativas horizontales y `audit.json`.

Las operaciones de evidencia son deliberadamente neutras y figuran como
`unapproved`: sirven para probar el flujo, no para fingir una corrección humana.

## Pendientes

1. El usuario debe editar y aprobar la referencia real del disco.
2. Luego debe revisarse la comparación automática frente a esa referencia.
3. Continúan pendientes las validaciones físicas de impresión/corte.
4. No cerrar P1 ni declarar producción hasta completar esos pasos.
