# Distribución externa del banco de stickers móvil

El catálogo móvil contiene 5.310 imágenes y aproximadamente 173 MiB. Las
imágenes no se versionan en Git; `manifest.json` y `sticker_bank.lock.json` sí.
El APK continúa empaquetando el banco completo para conservar el modo offline,
pero el payload debe restaurarse y verificarse antes de compilar una entrega.

## Archivos versionados

- `mobile/doccione_mobile/assets/sticker_bank/manifest.json`: catálogo consumido
  por Flutter.
- `mobile/doccione_mobile/assets/sticker_bank.lock.json`: tamaño y SHA-256 de
  cada imagen, hash del catálogo y hash agregado del árbol.
- `tools/mobile_sticker_bank.py`: generación y verificación reproducibles.

Las imágenes bajo `assets/sticker_bank/` permanecen locales e ignoradas por
Git. No se borran al adoptar esta política.

## Preparar una entrega

1. Restaurar el paquete externo dentro de
   `mobile/doccione_mobile/assets/sticker_bank/` sin sustituir el manifiesto por
   una versión distinta.
2. Verificar:

   ```powershell
   .\.venv\Scripts\python.exe tools\mobile_sticker_bank.py verify
   ```

3. Compilar mediante `tools/build_mobile_apk.ps1`. El script ejecuta la misma
   verificación estricta y cancela el build si falta o cambia una imagen.

Resultado esperado para esta versión:

- imágenes: 5.310;
- bytes de imágenes: 181.571.778;
- tree SHA-256:
  `3e36aa4b3374d3a4cbcf576335f3e7ae7cf4ab843c9b610f9a1b3ae6e9a9be24`.

## Actualizar el banco

Después de modificar deliberadamente catálogo o imágenes:

```powershell
.\.venv\Scripts\python.exe tools\mobile_sticker_bank.py lock
.\.venv\Scripts\python.exe tools\mobile_sticker_bank.py verify
```

Revisar y confirmar juntos `manifest.json` y `sticker_bank.lock.json`. El
paquete externo debe identificarse por el tree SHA-256 registrado. No confirmar
las imágenes directamente en Git.

## CI

CI usa `verify --allow-manifest-only`: valida la correspondencia entre catálogo
y lock sin exigir el payload pesado. Esto es suficiente para análisis y tests,
pero no autoriza un APK. Todo build distribuible conserva la verificación
estricta.
