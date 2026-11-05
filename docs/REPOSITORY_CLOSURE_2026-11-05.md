# Cierre técnico del repositorio — 2026-11-05

## Dictamen

El árbol todavía no está listo para un commit único de cierre. La aplicación
reúne cambios de Desktop, Pedidos, Creador de Planchas, Sticker Studio, Mobile y
WhatsApp sobre la rama `codex/mobile-s2b-sync-aislada`. Antes de congelar una
versión deben separarse esos alcances en commits revisables o aprobarse
explícitamente un snapshot monolítico.

No se borraron archivos ni se alteraron datos operativos durante esta revisión.

## Higiene aplicada

Se amplió `.gitignore` para excluir resultados reproducibles y estado local:

- variantes de caché y temporales de pytest;
- salidas, diagnósticos y artefactos generados;
- dependencias locales de runtime;
- estado local de Flutter y Gradle;
- transcripciones, configuración UI y copias de recuperación.

También se añadió `.gitattributes`: fuentes/configuración usan LF, launchers
Windows usan CRLF y los formatos binarios quedan excluidos de normalización.

El inventario no versionado visible bajó de 113.340 a 439 archivos sin borrar
el contenido local. El banco móvil dejó de contaminar el estado de Git: sus
5.310 imágenes quedan como payload externo ignorado, mientras catálogo y lock
criptográfico permanecen versionables.

## Estado del árbol

- 110 archivos versionados modificados, sin eliminaciones versionadas.
- Aproximadamente 12.417 inserciones y 1.945 eliminaciones en esos archivos.
- Fuentes nuevas relevantes: 60 archivos Desktop, 52 Dart, 23 pruebas Flutter,
  74 pruebas Python, 25 documentos, 17 herramientas y 7 scripts.
- Hay archivos auxiliares históricos en la raíz que todavía deben clasificarse
  como herramienta mantenida, evidencia archivada o descarte local.

## Verificación ejecutada

### Python

- `python -m compileall -q app costos main.py`: aprobado para los archivos
  accesibles. Las carpetas de dependencias vendorizadas con ACL restringida no
  pudieron enumerarse y no forman parte del código de aplicación modificado.
- `pytest tests --basetemp=.test-runs/closure-suite-20261105`: **1.412
  aprobadas, 2 omitidas, 5 subtests aprobados**, 249 advertencias; 316,14 s.
- La ejecución inicial sin `--basetemp` produjo 371 errores de infraestructura
  porque Pytest no podía enumerar `Temp/pytest-of-Win 10`; no fueron fallos de
  producto. El temporal explícito deja el procedimiento reproducible.

### Flutter

- `flutter analyze`: **sin problemas** después de aplicar 44 correcciones
  automáticas de Dart y retirar/suprimir únicamente código sin uso justificado.
- `flutter test`: **334 aprobadas, 1 omitida**. La repetición posterior a las
  correcciones obtuvo el mismo resultado.
- El SDK informó 88 paquetes con versiones más nuevas incompatibles con las
  restricciones actuales. No se actualizaron dependencias durante el cierre.

## Puertas de cierre pendientes

1. Clasificar los archivos nuevos y separar commits por dominio.
2. Revisar secretos y binarios antes de preparar el índice de Git.
3. Generar el commit de cierre y, sólo con autorización explícita, tag/publicación.

`git diff --check` quedó aprobado después de retirar espacios finales en seis
archivos Python preexistentes. Esos archivos también aprobaron `py_compile`.

## Banco móvil externo

La política quedó implementada y documentada en
`docs/MOBILE_STICKER_BANK_DISTRIBUTION.md`. El lock registra 5.310 imágenes,
181.571.778 bytes y tree SHA-256
`3e36aa4b3374d3a4cbcf576335f3e7ae7cf4ab843c9b610f9a1b3ae6e9a9be24`.
La verificación estricta del banco local aprobó y sus tres pruebas nuevas
aprobaron. CI admite sólo manifiesto para análisis/tests; el build release exige
el payload completo y cancela ante ausencia o discrepancia.

## Criterio de aceptación recomendado

El repositorio puede declararse cerrado cuando las suites Python y Flutter
terminen con resultado registrado, el banco móvil tenga política de distribución,
el índice no contenga cachés ni secretos y cada dominio funcional tenga un commit
revisable. La homologación física de impresión/corte y el piloto Android pueden
seguir documentados como validaciones operativas externas sin bloquear el cierre
del código, siempre que la versión no se promocione como homologada físicamente.
