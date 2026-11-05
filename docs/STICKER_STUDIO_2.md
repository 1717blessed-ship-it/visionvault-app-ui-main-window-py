# Sticker Studio 2.0 — Sprint 1

Fecha: 2026-10-19.

## Alcance implementado

La interfaz 2.0 es una capa reversible sobre `StickerStudio`. Reutiliza sus
jobs, procesamiento asíncrono, recuperación, editores de máscara/corte y
aprobación. No modifica el pipeline, las rutas A/B/C/D ni las calibraciones de
impresión y corte.

La ventana se organiza en cinco zonas:

1. Barra superior con importación, pegado, carpeta, procesamiento, comparación
   y aprobación/exportación. Deshacer, rehacer y guardar proyecto aparecen
   deshabilitados porque aún no existe un contrato de sesión seguro para ellos.
2. Herramientas laterales conectadas a selección de área, procesamiento,
   reprocesamiento de fondo, edición de máscara, zonas protegidas, objetos,
   corte y navegación. El lazo inteligente futuro queda visible y deshabilitado.
3. Canvas central con damero, ajuste, zoom centrado en cursor, desplazamiento,
   vistas Original/Máscara/Resultado/Final, comparación dividida y overlay de
   corte. Esta previsualización sólo lee artefactos: nunca escribe la salida.
4. Inspector contextual con dimensiones reales, píxeles, resolución efectiva,
   borde físico, corte, fondo, calidad y reprocesamiento explícito.
5. Bandeja inferior horizontal con miniatura, nombre, estado, calidad y
   selección persistente por trabajo.

Los módulos nuevos separan estado de navegación (`state.py`), normalización de
artefactos (`adapter.py`), canvas (`canvas.py`), componentes (`components.py`) y
ventana/control de compatibilidad (`window.py`).

## Compatibilidad y retorno al clásico

La versión 2.0 es la predeterminada al abrir el creador desde la aplicación.
Para una sesión de soporte o comparación puede iniciarse con:

```powershell
$env:DOCCIONE_STICKER_STUDIO='classic'
python main.py
```

El editor clásico no fue eliminado. Sus pruebas e importación directa conservan
el mismo nombre y comportamiento.

## Validación de Sprint 1

- Compilación de los seis módulos nuevos y `main_window.py`: correcta.
- Pruebas focalizadas: 7 aprobadas. Cubren límites de zoom, estado por imagen,
  selección de artefactos sin mutación, dimensiones físicas reales, limpieza de
  estado y rueda del editor clásico.
- Smoke test Tk real: apertura y cierre correctos de `Creador de stickers 2.0`
  con base temporal y cola vacía.
- Suite completa final: `1117 passed, 1 skipped, 4 warnings, 5 subtests passed`
  en 227,32 s. Son las 1.112 pruebas ejecutables de referencia más cinco
  regresiones nuevas de Studio 2.0.
- El primer intento reveló un caché Tk incompleto. `tests/conftest.py` ahora
  mezcla/repara los scripts instalados en un directorio temporal estable; la
  prueba gráfica aislada y la suite completa posterior quedaron correctas.

## Límites deliberados

- El caso P1 de la bola disco de 421 × 421 continúa requiriendo validación
  humana. La UI muestra los artefactos reales y no maquilla el defecto.
- Guardar proyecto, historial global deshacer/rehacer y lazo inteligente no se
  simulan: permanecen deshabilitados hasta contar con contratos persistentes.
- Una aprobación sigue siendo una decisión explícita del operador.
- Este Sprint 1 no equivale a validación visual ni física de producción.

## Sprint 1.1

La estabilización de integración, exportación exacta, tratamiento explícito de
borde y evidencia con originales reales se documenta en
`docs/STICKER_STUDIO_SPRINT_1_1.md`. Suite actual: 1130 aprobadas, una omitida.
El P1 continúa pendiente de máscara humana aprobada.

## Sprint 1.2

La herramienta no destructiva de contracción por distancia firmada, su
integración en el inspector y sus evidencias se documentan en
`docs/STICKER_STUDIO_SPRINT_1_2.md`. Suite actual: 1139 aprobadas, una omitida.

# Actualización Sprint 1.3

La edición manual no destructiva de máscaras, expansión, protección, historial
por operación y aprobación humana de referencias se documentan en
`docs/STICKER_STUDIO_SPRINT_1_3.md`. El P1 permanece abierto hasta la aprobación
visual del usuario.

# Actualización Sprint 1.4

La operación de Canvas, cola, selección múltiple, eliminación segura,
exportación y recuperación se documenta en `docs/STICKER_STUDIO_SPRINT_1_4.md`.
El P1 visual continúa sujeto a aprobación humana.

