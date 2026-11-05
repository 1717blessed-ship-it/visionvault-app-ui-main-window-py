# Pedidos 2.0 — Sprint 2

## Base y auditoría

Se conservan los cambios del Sprint 1 en `app/database/database.py` y sus regresiones en `tests/test_order_sprint1_integrity.py`. El repositorio tenía numerosos archivos modificados y sin seguimiento antes de comenzar; no se revirtieron. No se modificaron Sticker Studio, los algoritmos A/B/C/D, calibraciones, el Creador de Planchas ni la aplicación móvil.

La base inicial focalizada aprobó 10 pruebas. La ejecución nativa fuera del sandbox aprobó 26 pruebas con el conftest Tcl/Tk original, incluida la identidad de planchas entre subprocesos. No fue necesario reinstalar ni modificar el runtime. Una primera ruta temporal nativa devolvió acceso denegado; una ruta nueva permitió ejecutar las pruebas.

## Implementación

- Cada trabajo conserva `distribution_policy`: `complete`, `partial` o `legacy`. Los históricos mantienen `legacy`; abrir o guardar no cambia su política. La interfaz permite elegir una política y muestra solicitado, asignado y sin distribuir, con hojas o unidades. Estas cifras se presentan separadas de la producción.
- Una distribución completa exige igualdad; la parcial permite saldo sin asignar. Se rechazan cantidades no positivas, exceso, líneas repetidas, trabajos ajenos y unidades incompatibles. Las validaciones también se aplican al guardar únicamente diseños. Se conservan las restricciones de reservas y producción existentes.
- El historial de cobros muestra activos y anulados, referencia, motivo y fecha de anulación. La acción solicita motivo y evita una segunda anulación. El último cobro activo y los reportes de ventas excluyen anulaciones.
- `register_order_payment` conserva claves opcionales. La unicidad existente corresponde a `(order_id, idempotency_key)` para claves no vacías, e incluye pagos anulados. Reintentos idénticos devuelven el saldo actual sin otro movimiento; importe, medio o referencia incompatibles se rechazan. `BEGIN IMMEDIATE` serializa comprobación e inserción; un pago anulado no se reactiva mediante reintento. Pagos manuales sin clave siguen siendo movimientos distintos.
- Los cambios de producto, variante, subtotal, costo total o regla se registran como eventos `Trabajo comercial`, con valores anteriores/nuevos, trabajo, fecha y origen `order_editor`. Guardados idénticos no duplican eventos. No se recalculan trabajos históricos por abrirlos. La ruta ACEPTAR conserva el subtotal al editar únicamente campos no comerciales y actualiza vínculos de catálogo cuando cambia la identidad del producto.

## Migración

`2026102301`, registrada en `app/database/migrations.py`, incorpora una columna aditiva con valor histórico `legacy`. El ejecutor existente aplica la migración transaccionalmente. Antes de inicializar un archivo existente sin esa columna se genera un respaldo mediante la API SQLite, incluyendo WAL, aun si el mantenimiento diario está diferido. La regresión elimina la columna de una base de prueba, vuelve a abrirla y comprueba preservación y respaldo.

## Archivos del Sprint 2

- `app/database/database.py`
- `app/database/migrations.py` (archivo preexistente sin seguimiento)
- `app/sales/repository.py` (archivo preexistente sin seguimiento)
- `app/ui/main_window.py`
- `tests/test_order_sprint2.py`
- `tests/test_database_maintenance.py` (expectativa de versiones actualizada)
- `tools/preview_orders_sprint2.py`
- Este informe.

## Verificación

- Focalizada final: **43 aprobadas**. Incluye políticas completas/parciales, hojas/unidades, rollback, migración histórica, conservación de política, cambios comerciales, reportes y concurrencia de pagos, junto con regresiones de producción.
- Suite general nativa `tests`: **1202 aprobadas, 1 fallida, 1 omitida, 5 subtests aprobados**, con cuatro advertencias preexistentes por pruebas que devuelven booleanos. El único fallo fue la expectativa de tres migraciones en `test_database_maintenance`; se actualizó para incluir `2026102301` y se comprobó después dentro de la focalizada final. La suite completa fue recolectada antes de esa actualización y antes de las dos últimas regresiones; no se presenta como una suite final completamente verde.
- Compilación de los archivos Python modificados y `git diff --check` correctos.
- XML de la ejecución general: `artifacts/sprint2-full-results.xml`.
- La aplicación se abrió con datos ficticios en `artifacts/orders-sprint2-preview/preview.db`. La herramienta de captura devolvió ventanas de fondo ajenas a Doccione aun seleccionando y activando su ventana; no se adjuntan esas imágenes como evidencia. La revisión visual completa queda pendiente. El script permite reproducir la vista real del historial.

## Límites y Sprint 3

La aplicación móvil está expresamente fuera del alcance: sus endpoints actuales escriben pagos directamente y aún no consumen el contrato idempotente del repositorio; el Sprint 2 no afirma protección de reintentos en esos endpoints. Requieren un sprint autorizado de integración, con pruebas HTTP y clientes existentes. El historial comercial describe cambios persistidos, no constituye un sistema nuevo de aprobaciones comerciales.

Próximo sprint: conectar integraciones autorizadas al contrato de pagos, validar la edición con pruebas reales de interacción y capturas confiables, y mejorar la presentación de detalle por trabajo tras evaluación visual con el operador. Repetir la suite general sobre el estado final antes de una publicación.
