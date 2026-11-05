# Doccione Mobile — Sprint 2C.3: aceptación previa a instalación

Fecha: 2026-10-24. Estado: **detenido antes de instalar, pendiente de
autorización expresa del operador**.

## Conflicto detectado y corrección

El APK de Sprint 2C.2 usaba `com.doccione.mobile`. Ese paquete sí está
instalado en el Redmi y conserva datos en `/data/user/0/com.doccione.mobile`.
Por lo tanto, el APK anterior no debe instalarse ni usarse con `-r`.

Se añadió una identidad de compilación opt-in que no altera builds ordinarios:

- Aplicación normal: `com.doccione.mobile`, etiqueta `Doccione Mobile`.
- Piloto USB: `com.doccione.mobile.usbpilot`, etiqueta
  `Doccione USB Pilot`.

El paquete piloto no está instalado actualmente. Android le asignará un
directorio de datos independiente; no reemplaza ni comparte datos con la
aplicación existente.

## APK candidato definitivo

Archivo:

`artifacts/mobile-s2c3-apk/doccione-mobile-usb-pilot-debug.apk`

- SHA-256:
  `BDA1F675AA3499BB5904D3B03EAD52ED91465178689C3D14454ED1D53F8BB2F0`
- applicationId: `com.doccione.mobile.usbpilot`
- versión: `1.0.5` (`versionCode` 6)
- firma: Android Debug, RSA 2048, APK Signature Scheme v2
- certificado de firma SHA-256:
  `6f26664cc2847bff614889261a1b249aa15599c259f0f927f2b93eda292b7dc6`
- minSdk 24; targetSdk 36; compilación debug.

La inspección del ZIP no encontró archivos `.key`, `.p12`, `.pfx`, `.jks`,
keystores ni bloques PEM de clave privada. Contiene únicamente las CA públicas
de integración previstas.

## Entorno verificado

- Redmi `e21c82ad`, modelo `24115RA8EG`, autorizado por ADB.
- Servidor: únicamente `127.0.0.1:8875`.
- Base: SQLite temporal generada por `OrderIntegrationEnvironment`.
- Escrituras: habilitables solamente sobre datos ficticios de esa instancia.
- TLS: SAN IP `127.0.0.1`, válido hasta 2027-01-22.
- Petición sin autenticación: HTTP 401 después de validar TLS.
- ADB Reverse: `UsbFfs tcp:8875 tcp:8875`, verificado.
- Emparejamiento: código de un solo uso; sesiones revocables por el adaptador.
- API 8765: independiente y no modificada.

Tras la comprobación se detuvo el servidor temporal y se retiró ADB Reverse.
No quedó el piloto escuchando ni se instaló el APK.

## Comando de instalación propuesto

Ejecutar solo después de autorización expresa:

```powershell
C:\Android\Sdk\platform-tools\adb.exe -s e21c82ad install --no-streaming `
  "C:\Users\Win 10\Documents\Codex\2026-07-13\visionvault-app-ui-main-window-py\artifacts\mobile-s2c3-apk\doccione-mobile-usb-pilot-debug.apk"
```

No se usa `-r`. Si Android informa que el paquete ya existe, el procedimiento
debe detenerse y auditar ese paquete antes de continuar.
