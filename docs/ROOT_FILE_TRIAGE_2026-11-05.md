# Clasificación de archivos sueltos de raíz — 2026-11-05

Los archivos enumerados permanecen intactos. Esta clasificación define la
acción previa a preparar commits; no declara que sean prescindibles.

## Mantener en raíz sólo si son entradas soportadas

- `doccione_costos_stock.py`
- launchers `Iniciar Doccione*.bat` y `Compilar APK Doccione.cmd`
- `MOVER_Y_COMPILAR.ps1`, `copiar_archivos.ps1`, `verificar_entregables.ps1`

Cada entrada debe estar referenciada desde README o moverse a `tools/`.

## Migraciones y reparaciones históricas

Mover a `tools/migrations/` si siguen siendo repetibles; de lo contrario deben
quedar fuera del commit:

- `add_editor_logging.py`, `add_manifest_logic.py`, `add_migration_logic.py`;
- `migrate_to_v4.py`, `fix_index_version.py`, `fix_pending_orders.py`;
- `fix_editor_precise.py`, `fix_pipeline.py`, `fix_syntax.py`;
- `comparar_or_fix.py`, `limit_test_candidates.py`.

## Diagnósticos y verificadores

Mover a `tools/diagnostics/` sólo si no contienen rutas/datos locales:

- `check_*`, `debug_*`, `diagnostic_*`, `inspect_*`;
- `find_heart_sticker.py`, `repro_processed.py`;
- `verify_*`, `validate_paso1_perf.py`, `consolidar_resultados_auditoria.py`;
- `diagnostico_regresion_stickers.py`.

## Pruebas sueltas

Los archivos `test_*.py` de la raíz deben integrarse en `tests/` cuando sean
deterministas y tengan fixtures aislados. Los ensayos manuales o visuales deben
ir a `tests/manual/` o permanecer ignorados. No deben mezclarse con entrypoints.

## Documentación histórica

Los numerosos informes Markdown de raíz deben consolidarse bajo `docs/history/`
o reemplazarse por un índice. Los documentos de cierre vigentes son:

- `docs/REPOSITORY_CLOSURE_2026-11-05.md`;
- `docs/REPOSITORY_COMMIT_PLAN_2026-11-05.md`;
- este documento.

## Criterio de decisión

Se mantiene un archivo si tiene propietario funcional, comando reproducible,
entrada documentada y prueba/resultado verificable. Si sólo registra una
intervención pasada, se archiva; si contiene datos derivados o locales, se
ignora. Ningún archivo debe eliminarse sin revisión explícita.
