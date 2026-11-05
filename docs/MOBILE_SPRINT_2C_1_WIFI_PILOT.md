# Sprint 2C.1 — piloto Android ↔ Desktop aislado

Estado: **preparado técnicamente, bloqueado para prueba física mientras Windows
permanezca en perfil Público y no se conozca la IPv4 Wi-Fi del Redmi**.

## Separación

El API operativo continúa en `8765` y no fue modificado. El piloto usa `8875`,
HTTPS y `OrderIntegrationEnvironment`, que crea siempre una base nueva dentro de
un `TemporaryDirectory`. El comando no acepta rutas de base de datos. Al detener
el proceso se cierra y elimina el realm ficticio. El listener efímero y HTTP de
las pruebas sigue limitado a `127.0.0.1` y puerto aleatorio.

La activación del listener LAN exige configuración local explícita, certificado,
clave y una única IPv4 privada autorizada. Ninguna petición HTTP puede iniciar el
listener, cambiar su bind, activar escrituras o elegir una base.

## Certificado

Se generó una CA exclusiva del piloto y un certificado servidor con SAN IP
`192.168.1.21`. La clave privada está bajo `secrets/order-sync-pilot`, excluida de
Git y del APK, con ACL limitada al usuario actual. El APK debug explícito contiene
solo la CA pública. El cliente usa un `SecurityContext` sin raíces generales:
continúan vigentes la validación de cadena, vencimiento y SAN, y no existe
`badCertificateCallback`.

Huella SHA-256 de la CA: `7ee470930f940e76e1a867f65c6ccb3ebc877537001c2124a7ab09ea65eb1164`.

## Precondiciones manuales obligatorias

1. Cambiar `Ethernet 4 / Red 14` de Público a Privado y volver a comprobarlo.
2. Obtener la IPv4 actual del Redmi Note 14 Pro+ y reservarla en DHCP si es posible.
3. Eliminar o deshabilitar las reglas entrantes globales de Python en perfil
   Público. Crear una regla TCP solo para `8875`, perfil Privado, IP local
   `192.168.1.21` e IP remota exacta del Redmi. No abrir el router.
4. Verificar en el teléfono la huella anterior antes de introducir el código de
   emparejamiento de un solo uso.

## Inicio (solo después de las precondiciones)

Reemplazar `<IP_REDMI>` por la dirección comprobada:

```powershell
.\.venv\Scripts\python.exe .\tools\order_sync_lan_pilot.py serve `
  --bind 192.168.1.21 --port 8875 --allowed-client <IP_REDMI> `
  --certificate .\secrets\order-sync-pilot\pilot-server.pem `
  --private-key .\secrets\order-sync-pilot\pilot-server.key `
  --enable-fictitious-writes
```

La salida muestra la URL `https://192.168.1.21:8875` y un código de enlace de un
solo uso. Ctrl+C revoca de hecho el realm completo al destruir la base temporal.

El build interno debe conservarse en debug y requiere las tres definiciones:

```powershell
flutter run -t lib/integration_order_main.dart `
  --dart-define=DOCCIONE_ORDER_INTEGRATION=true `
  --dart-define=DOCCIONE_ORDER_INTEGRATION_LAN=true `
  --dart-define=DOCCIONE_ORDER_INTEGRATION_HOST=192.168.1.21
```

No se genera APK hasta completar la auditoría de firewall, compilación y prueba
TLS. La prueba física debe registrar Wi-Fi, HTTPS, emparejamiento, capacidades,
catálogo, pedido ficticio, revisión, edición aislada, reconexión, idempotencia y
rechazo de cualquier ruta operativa. Una prueba desde Windows o emulador no la
reemplaza.

## Evidencia del 24-10-2026

- Red Windows: `Red 14`, interfaz `Ethernet 4`, categoría **Public**, IPv4
  `192.168.1.21`, gateway `192.168.1.1`.
- Se encontraron reglas entrantes amplias `Python`, `python.exe` y `pythonw.exe`
  tanto para Private como Public. No fueron modificadas automáticamente.
- Handshake local: TLS 1.3 aceptado con SAN IP `192.168.1.21`. Una conexión que
  exigía identidad `192.168.1.22` fue rechazada por mismatch del certificado.
- Suite focalizada Desktop: **34 passed**. Incluye las 31 pruebas del contrato y
  3 controles nuevos de cierre seguro LAN.
- Suite Desktop general: **1388 passed, 21 failed, 2 skipped**. Los 21 fallos
  requieren Tk y fallaron porque el Python activo no encuentra `init.tcl`; no
  involucran el adaptador ni el transporte nuevo.
- La ejecución Flutter no produjo salida y fue interrumpida; compilación y tests
  Flutter quedan pendientes, sin presentar un APK.
- Copias SQLite consistentes de la base operativa antes/después:
  `A4C9DBC4E5BA9F0DFC1A10A46BF11BB6806241BA46DDFE11F53A988E56B09D55`.
- No se ejecutó una prueba desde Android y no se creó regla de firewall para
  `8875`. Dictamen: **bloqueado para piloto físico**, preparado para completar
  las precondiciones con la IPv4 comprobada del Redmi.

### Cierre de configuración

- Dispositivo físico detectado por ADB: Redmi Note 14 Pro+ (`24115RA8EG`),
  Android 15, IPv4 Wi-Fi dinámica `192.168.1.41/24`, SSID `DOCCIONE`. Desktop y
  teléfono pertenecen a `192.168.1.0/24`. El ping desde Windows no recibió
  respuesta; esto no demuestra aislamiento porque Android puede omitir ICMP.
- El perfil Windows continúa **Public**. No se cambió sin autorización expresa.
- Hay diez reglas `Allow` entrantes, TCP/UDP, puerto/dirección `Any`, para
  `C:\python313\python.exe`, Python 3.14 `python.exe` y `pythonw.exe`. Cuatro
  permiten perfil Public. Las reglas Public de `python.exe` tienen además dos
  bloqueos explícitos; `pythonw.exe` conserva permisos Public amplios.
- Se guardaron inventarios CSV y una representación legible en
  `artifacts/mobile-s2c1-firewall-20261024-160402`. La exportación binaria `.wfw`
  fue rechazada porque la consola no tenía elevación administrativa; debe
  completarse antes de modificar reglas.
- Tcl/Tk 8.6.15 funciona correctamente fuera del sandbox. Con temporal nuevo,
  la suite produjo **1408 passed, 1 failed, 2 skipped**; el único fallo Tk pasó
  inmediatamente en proceso aislado (**1 passed**) y es contaminación/transición
  del entorno de prueba, no una regresión funcional comprobada.
- Flutter Doctor funciona fuera del sandbox: Flutter 3.44.7/Dart 3.12.2 y el
  Redmi físico son detectados. Quedan licencias Android pendientes, un segundo
  SDK Flutter en PATH y Visual Studio incompleto (irrelevante para Android).
- `flutter analyze --no-pub`: sin errores de compilación; 56 avisos/info
  preexistentes. Suite focalizada order-sync: **19 passed**. Suite Flutter
  completa: **334 passed**.
- El listener `8875` permanece detenido. `8765` continúa escuchando. No se creó
  APK ni se realizó emparejamiento físico.
