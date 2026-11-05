# Mobile Sprint 1.1 — estabilización y diseño de integración

Fecha: 2026-10-24. Rama: `codex/mobile-s1-pedidos-subproductos`. Sin publicación, APK ni cambios de backend. No se tocaron bases operativas, Sticker Studio, Planchas ni calibraciones.

## Investigación de fallos

Antes de modificar código se ejecutó el archivo de Configuración completo (`artifacts/mobile-s11-config-before.log`) y se lanzó cada uno de los 14 casos por separado: `artifacts/mobile-s11-individual-0.log` a `-13.log`. Todos fallaron individualmente en la espera de carga, aun sin compartir el resto de la suite. No se observó dependencia de red: las conexiones exitosas/fallidas usan callbacks locales; SQLite FFI sí utiliza E/S real.

Causa común: el helper bombeaba exclusivamente tiempo virtual de Flutter/FakeAsync mientras esperaba una consulta real a SQLite. El spinner continuaba y el test declaraba que no había cargado antes de ejecutar sus verificaciones específicas. No era evidencia de pérdida de URL, puerto ni datos por parte de Mobile.

La comparación de fuentes con HEAD `cb3d9a2` muestra que el helper de base usaba `pumpAndSettle`, también inadecuado para un spinner que depende de E/S real; el árbol anterior al Sprint 1.1 ya contenía una espera virtual acotada. La pantalla y repositorio de configuración tenían cambios previos que se preservaron. **No se ejecutó una suite sobre un checkout limpio de la rama base**: el árbol heredado contiene abundantes cambios no confirmados y HEAD no representa el Sprint 1 entregado completo. La comparación histórica es de fuentes; la reproducción empírica es contra el estado exacto recibido. No se atribuyen los fallos a una regresión productiva nueva sin esa evidencia.

La espera corregida da paso a E/S real mediante `tester.runAsync` y vuelve a bombear frames, con límite real de dos segundos y fallo explícito si no termina. Se conservan SQLite real, aserciones y cobertura de errores. Después del cambio pasaron 13 casos y se descubrió un segundo defecto oculto: el test de carga esperaba una única etiqueta «8765», pero la interfaz contiene ese texto tanto en el campo como en un preset. Se precisó el selector al controlador del campo de puerto, sin relajar el valor esperado.

Casos corregidos, todos del mismo grupo de carga: cargar configuración; host vacío; puerto inválido; puerto fuera de rango; guardar; llamar callback; mensaje de éxito; Continuar con éxito; mensaje de fallo; ausencia de Continuar con fallo; disponibilidad del botón de conexión; preview dinámico; tarjeta actual; host con espacios. Ninguno se excluyó ni se marcó skip. Se reforzó guardar comprobando además host, puerto y esquema leídos del repositorio persistente. URL/puerto/esquema y formatos existentes no se modificaron en producción.

## Editor local y limitaciones

Se mantienen múltiples trabajos y diseños, selección de opciones de catálogo sin variantes ficticias, cantidades parciales/completas, unidades y hojas, IDs locales estables, transacción de guardado, recuperación tras cerrar base, privacidad por vendedor y revisión optimista. Agregadas guardas de reentrada al guardar/recuperar. Los conflictos no sobrescriben el documento más reciente: queda el error y los cambios en memoria, con confirmación explícita antes de descartarlos. No se implementó un archivo durable separado para la versión conflictiva no guardada: cerrar el proceso sin guardar esa edición sigue requiriendo una solución futura de recuperación de conflictos.

No se afirma paridad integral con Desktop: catálogo sin opciones no permite inventar atributos; no hay edición remota completa, cotización final offline, ni vínculos productivos remotos. Quitar un vínculo del borrador es una modificación local, nunca eliminación de una demanda con producción. Pantallas de venta y edición operativa anteriores continúan separadas hasta disponer del contrato seguro; no se las fusionó prematuramente.

## Contrato y seguridad

Inventario de rutas, matriz de capacidades y propuesta de alcance backend: `docs/MOBILE_DESKTOP_CONTRACT_V1_PROPOSAL.md`. Se agregó `OrderSyncProposal` como **DTO de propuesta desconectado**, sin llamadas HTTP ni infraestructura. Convierte explícitamente `units` → `item` y `sheets` → `sheet`, conserva IDs locales y asociación estable por trabajo/diseño, valida estructura/revisión y rechaza usar un borrador incompleto como operación preparada. Nunca serializa precios históricos, costos ni estados administrativos como mutaciones propuestas.

La propuesta exige revisión monotónica compartida por toda escritura Desktop, operation_id/hash/recibo transaccional, permisos y transporte seguro, rechazo atómico de conflictos, reutilización de guardas centralizadas y consulta/replay del resultado ante respuesta perdida. No se implementó idempotencia backend nueva ni se simuló éxito de sincronización. Estados propuestos: guardado local, pendiente, sincronizando, confirmado, conflicto y error; hoy solo se habilitan estados locales, sin transición automática a confirmado.

Bloqueos críticos: los endpoints operativos antiguos de cantidad/tamaño y entrega usan SQL directo, sin demostrar las guardas modernas de reservas/entrega; producto/agregado no presenta idempotencia general como el alta sticker. Crear endpoints o modificar esas rutas requiere aprobar previamente el alcance documentado y verificarlas E2E en una base aislada. No se realizaron operaciones contra un servidor real ni bases operativas para probarlo.

## Pruebas

- Reproducción individual: 14/14 fallaron antes de corregir el harness; logs individuales conservados.
- Suite focalizada final: **51 aprobadas, cero fallos**; `artifacts/mobile-s11-focused.log`. Configuración/repo, serialización propuesta, cantidades, persistencia, conflictos y widgets locales.
- Primera suite general corregida: **312 aprobadas, cero fallos**; `artifacts/mobile-s11-full.log`.
- Suite general final: **313 aprobadas, cero fallos**; `artifacts/mobile-s11-full-final.log`.
- Análisis focalizado de archivos nuevos/contrato y test de configuración: sin errores ni warnings; una observación de estilo; `artifacts/mobile-s11-analyze.log`.

No se declara E2E del contrato propuesto, prueba Android física, compilación APK ni aprobación productiva integral. Las pruebas de reintento/idempotencia locales no acreditan idempotencia de ventas remotas.

## Archivos de esta entrega

`lib/models/order_sync_proposal.dart`, `test/order_sync_proposal_test.dart` (nuevos); `test/screens/server_config_screen_test.dart` (espera real, selector preciso y lectura persistida); `lib/screens/unified_order_creation_screen.dart` (guardas de reentrada); dos documentos de Sprint 1.1 y contrato. No confundir estos cambios con los del Sprint 1 o modificaciones heredadas.

## Recomendación

Estabilización de tests favorable; mantener borradores completos en modo local. Próximo alcance recomendado: aprobar el contrato backend, centralizar las mutaciones inseguras existentes, desarrollar recibos/revisiones e idempotencia con E2E aislada, y recién entonces conectar el editor. El estado verde de Flutter no elimina los bloqueos de integridad del backend. No generar ni publicar APK mientras esos bloqueos críticos permanezcan.
