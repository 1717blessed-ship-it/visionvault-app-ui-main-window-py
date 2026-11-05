# Doccione Mobile — piloto USB/ADB Reverse

Estado: **implementado técnicamente; piloto físico bloqueado por compilación
Gradle en este equipo**. Este transporte no reemplaza la homologación Wi-Fi.

## Límites de seguridad

- El servidor escucha exclusivamente en `127.0.0.1:8875` con TLS 1.2 o
  superior.
- El comando USB no acepta dirección de bind ni ruta de base de datos.
- La base SQLite pertenece a un directorio temporal y se destruye al detener
  el proceso. Las escrituras solo se habilitan mediante
  `--enable-fictitious-writes` y afectan exclusivamente esa base.
- El cliente Android debug acepta únicamente `https://127.0.0.1:8875` cuando
  se compila con `DOCCIONE_ORDER_INTEGRATION_USB=true`.
- La CA USB es independiente de la CA Wi-Fi. El APK contiene solo el
  certificado público; las claves privadas permanecen en
  `secrets/order-sync-usb-pilot/` (ignorado por Git y ACL restringida).
- No existe `badCertificateCallback`, trust-all, acceso LAN ni acceso a bases
  operativas.

## Preparación

Comprobar y redirigir el dispositivo autorizado:

```powershell
C:\Android\Sdk\platform-tools\adb.exe devices -l
C:\Android\Sdk\platform-tools\adb.exe -s e21c82ad reverse tcp:8875 tcp:8875
C:\Android\Sdk\platform-tools\adb.exe -s e21c82ad reverse --list
```

Generar material TLS USB (solo si debe rotarse):

```powershell
.\.venv\Scripts\python.exe tools\order_sync_usb_pilot.py create-certificates `
  --output secrets\order-sync-usb-pilot `
  --public-ca mobile\doccione_mobile\assets\integration_usb_pilot_ca.pem
```

Iniciar el piloto con datos ficticios:

```powershell
.\.venv\Scripts\python.exe tools\order_sync_usb_pilot.py serve `
  --certificate secrets\order-sync-usb-pilot\pilot-server.pem `
  --private-key secrets\order-sync-usb-pilot\pilot-server.key `
  --enable-fictitious-writes
```

El servidor imprime la ruta temporal, URL y código de emparejamiento de un
solo uso. El código debe ingresarse únicamente en el cliente de integración.

## Compilación interna

```powershell
C:\flutter-sdk\bin\flutter.bat build apk --debug `
  -t lib\integration_order_main.dart `
  --dart-define=DOCCIONE_ORDER_INTEGRATION=true `
  --dart-define=DOCCIONE_ORDER_INTEGRATION_USB=true `
  --no-pub
```

No agregar `DOCCIONE_ORDER_INTEGRATION_LAN`; ambos modos simultáneos son
rechazados. No usar este entry point para builds release.

## Retirada segura

1. Detener el servidor con `Ctrl+C`; esto elimina su base temporal.
2. Retirar solo esta redirección, sin afectar otras:

```powershell
C:\Android\Sdk\platform-tools\adb.exe -s e21c82ad reverse --remove tcp:8875
```

3. Confirmar que `adb reverse --list` ya no contiene `tcp:8875` y que
   `netstat -ano -p tcp` no muestra un listener en `127.0.0.1:8875`.

## Evidencia de esta ejecución

- Redmi detectado y autorizado: `e21c82ad`, modelo `24115RA8EG`.
- Redirección observada: `UsbFfs tcp:8875 tcp:8875`.
- Listener observado: solo `127.0.0.1:8875`.
- TLS con CA USB: handshake correcto; `/capabilities` devolvió `401` sin
  token, confirmando que autenticación sigue activa.
- TLS con CA Wi-Fi: certificado rechazado.
- CA USB SHA-256 (DER):
  `2870d96badfdf328f638766649ec85f94bb7fc8e382ae4edd15605fb1185e6f5`.
- Pruebas Flutter de sincronización: 19 aprobadas. Una primera ejecución tuvo
  un fallo ambiental de propiedad Git al lanzar un segundo proceso Flutter;
  repetida con `safe.directory` limitado al SDK: aprobada.
- Análisis Flutter: sin incidencias nuevas en los archivos USB; conserva 56
  avisos preexistentes del proyecto.
- Compilación APK: bloqueada porque Gradle no pudo establecer su conexión
  loopback interna, incluso en ejecución fuera del sandbox. No se instaló ni
  reutilizó un APK anterior.
- La prueba física de creación, modificación, conflicto y reintento queda
  pendiente hasta obtener un APK nuevo verificable.

No se modificaron DHCP, firewall, perfil de red, puertos del router, bases
operativas ni servidores productivos.
