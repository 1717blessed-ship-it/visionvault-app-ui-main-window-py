# Plan de commits para cierre — 2026-11-05

Este plan clasifica el árbol actual sin atribuir autoría ni descartar cambios.
Cada grupo debe validarse y confirmarse por separado. Los comandos de `git add`
se omiten deliberadamente hasta terminar la revisión de contenido.

## 1. Higiene y ejecución local

Incluye `.gitignore`, launchers, `VisionVault.spec`, dependencias declaradas,
configuración de pruebas y scripts de diagnóstico mantenidos. Excluye resultados,
cachés, copias de recuperación y dependencias instaladas localmente.

Antes de confirmar, los scripts sueltos de migración, `fix_*`, `debug_*`,
`check_*` y pruebas `test_*.py` de la raíz deben moverse a `tools/`, `scripts/`
o `tests/`, o permanecer como archivos locales ignorados. No deben entrar al
commit sólo porque hoy están presentes.

## 2. Desktop: infraestructura, búsqueda y módulos comerciales

Rutas principales:

- `app/ai/`, `app/indexer/`, `app/events/`, `app/notifications/`;
- `app/database/`, `app/domain/`, `app/security/`;
- `app/fiscal/`, `app/sales/`, `app/whatsapp/`;
- servicios y pantallas de catálogo, costos, fotocopias y ventas;
- `costos/` y sus pruebas específicas.

Separar WhatsApp en otro commit si se desea poder revertir esa integración sin
afectar búsqueda, catálogo o persistencia.

## 3. Pedidos, producción y Creador de Planchas

Rutas principales:

- servicios `order_*`, `production_*`, `delivery_readiness` y stock;
- `app/ui/production_*`, `app/ui/order_production_panel.py`;
- `app/planchas/` y `app/printing/`;
- pruebas `test_order_*`, `test_production_*`, `test_plancha_*` y
  `test_creator_*`;
- documentos `ORDERS_2_*` y `CREADOR_PLANCHAS_*`.

Debe conservarse la separación entre validación digital y homologación física.

## 4. Sticker Studio

Incluye únicamente el delta real de `app/stickers/`, sus pruebas y documentos de
aceptación. Los PNG, XML, auditorías generadas y carpetas bajo `artifacts/` no se
versionan salvo un manifiesto de release explícitamente seleccionado.

## 5. Mobile: aplicación y sincronización

Incluye:

- fuentes de `mobile/doccione_mobile/lib/`;
- configuración Android/iOS necesaria;
- pruebas Dart y contract tests;
- certificados CA públicos de los pilotos;
- cliente/contrato Desktop asociado y pruebas de integración;
- documentación `MOBILE_*`.

No incluye `.gradle-*`, estado Flutter, APK, logs ni paquetes de compilación.

### Banco móvil — resuelto

`mobile/doccione_mobile/assets/sticker_bank/` contiene aproximadamente 5.313
archivos y 174,7 MiB. `pubspec.yaml` lo empaqueta de forma directa. Debe elegirse
una política antes del commit:

1. Git LFS con manifiesto y checksum;
2. paquete de release descargable/verificable durante preparación del build;
3. subconjunto curado versionado y banco completo externo.

Se adoptó paquete externo con manifiesto y lock versionados. Las imágenes quedan
ignoradas, el build release verifica el payload completo y CI valida catálogo y
lock en modo manifiesto. Véase `docs/MOBILE_STICKER_BANK_DISTRIBUTION.md`.

## 6. Cloud

`cloud/` es un backend completo con Docker, Alembic, API y pruebas. Debe ser un
commit independiente y, si su ciclo de despliegue es distinto, evaluarse como
repositorio o paquete separado. Sus `.env.example` pueden versionarse; archivos
`.env` reales siguen excluidos.

## 7. CI, pruebas y documentación final

Incluye `.github/workflows/mobile-quality.yml`, fixtures pequeños, documentación
vigente y el dictamen final. La configuración CI sólo debe confirmarse después de
probar sus comandos localmente o en un runner equivalente.

## Puertas antes de preparar el índice

- Pytest completo ejecutado: 1.412 aprobadas, 2 omitidas.
- `flutter analyze` limpio y `flutter test`: 334 aprobadas, 1 omitida.
- Banco móvil resuelto mediante payload externo verificable.
- Revisión de scripts sueltos de raíz completada.
- Sin secretos, bases, APK, logs, cachés ni dependencias instaladas en el índice.
- `git diff --check` sin errores.
