# Doccione Mobile — Sprint 2C.2: recuperación Gradle en Windows

Fecha de validación: 2026-10-24.

## Resultado

La compilación Android quedó recuperada y se generó un APK interno nuevo para
el piloto USB. No se instaló ni publicó.

## Causa raíz

El fallo ocurre antes de las tareas de compilación, al construir el canal de
lectura de la conexión local de Gradle:

```text
SocketConnection$SocketInputStream -> Selector.open()
PipeImpl -> UnixDomainSockets.connect0()
java.net.SocketException: Invalid argument: connect
```

En este Windows, los JDK modernos detectan AF_UNIX como disponible, crean el
pipe interno de `Selector` con un socket de dominio Unix y el `connect` nativo
falla. Una conexión TCP real a `127.0.0.1` funciona correctamente. Por tanto,
no es un fallo de la interfaz loopback TCP, de la red doméstica ni del
firewall.

Además, el Java predeterminado era Temurin 25.0.4. Gradle 8.14 soporta ejecutar
el daemon hasta Java 24; se seleccionó el JBR 21.0.10 de Android Studio, que sí
es compatible. El JBR 21 presenta el mismo fallo AF_UNIX, por lo que cambiar de
JDK por sí solo no era suficiente.

## Versiones verificadas

- Gradle Wrapper: 8.14.
- Android Gradle Plugin: 8.11.1.
- Kotlin Android plugin: 2.2.20.
- Java predeterminado anterior: Temurin 25.0.4+7.
- Java de compilación: JetBrains Runtime 21.0.10, incluido con Android Studio.
- `JAVA_HOME`, `JAVA_TOOL_OPTIONS`, `JDK_JAVA_OPTIONS` y `GRADLE_OPTS` estaban
  vacíos inicialmente.

## Solución aplicada

Se compiló una sustitución temporal de la clase interna `PipeImpl` del mismo
JDK. El único cambio hace que, cuando está presente la propiedad privada de
esta ejecución `doccione.nio.forceTcpPipe=true`, OpenJDK omita AF_UNIX y use su
fallback TCP loopback existente.

El parche se inyectó solo en los procesos de compilación mediante
`--patch-module`; no se modificó el JDK instalado, el registro, el firewall ni
ninguna variable global. La copia temporal se eliminó al finalizar. La fuente
y la clase de evidencia permanecen en:

`artifacts/mobile-s2c2-gradle-diagnostics/`

También se limitó la JVM a cuatro procesadores/workers porque el valor
automático del entorno inició una cantidad excesiva de compiladores Kotlin y
provocó saturación durante la primera configuración.

## Pruebas

- `Selector.open()` con Temurin 25: falla por AF_UNIX.
- `Selector.open()` con JBR 21: falla por AF_UNIX.
- Socket TCP Java sobre `127.0.0.1`: aprobado.
- JBR 21 con fallback TCP temporal: `Selector.open()` aprobado.
- `gradle help --no-daemon`: **BUILD SUCCESSFUL**, 34 s.
- `flutter build apk --debug` con el entrypoint USB: aprobado.
- `flutter analyze`: 56 avisos preexistentes, sin incidencias nuevas USB.
- Suite Flutter completa: **334 aprobadas, 1 omitida**. La omitida es la
  prueba USB que requiere deliberadamente su define de compilación.
- Prueba USB con `DOCCIONE_ORDER_INTEGRATION_USB=true`: **1 aprobada**.

## APK interno

Archivo:

`artifacts/mobile-s2c2-apk/doccione-mobile-usb-integration-debug.apk`

SHA-256:

`39B0F1029B5164F96593DB67F052676253AF16EE193D0B77F73FFAB0C1DD61BD`

El APK fue generado con:

- `lib/integration_order_main.dart`
- `DOCCIONE_ORDER_INTEGRATION=true`
- `DOCCIONE_ORDER_INTEGRATION_USB=true`

La inspección ZIP confirmó la CA pública USB y ninguna clave privada PEM. No
se incluyeron credenciales productivas y el APK no fue instalado.

## Integridad y seguridad

- Hash de respaldo consistente de la base operativa antes y después:
  `82B510D46E5D1F07D55B6337C14BCFBFC3F282E8E7EF5A50F22FFBBC918E6734`.
- No se modificaron router, DHCP, firewall, puerto 8765, bases operativas,
  pedidos, Sticker Studio, Creador de Planchas ni calibraciones.
- El piloto mantiene `127.0.0.1:8875`, ADB Reverse, HTTPS con CA USB,
  emparejamiento, autenticación y SQLite temporal ficticia.

## Dictamen

La cadena de compilación y el APK interno están aprobados. El siguiente paso
es la instalación manual autorizada y la validación física en el Redmi. El
piloto USB todavía no sustituye la homologación Wi-Fi.
