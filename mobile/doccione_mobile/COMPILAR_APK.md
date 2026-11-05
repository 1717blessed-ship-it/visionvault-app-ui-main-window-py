# Compilar el APK

Abrí `GENERAR APK.bat` con doble clic. El APK aparecerá en `artifacts\\apk`.

El script usa unidades temporales para que no afecten los espacios en `C:\\Users\\Win 10` y restaura `android/local.properties` al terminar. Busca Flutter en `C:\\Users\\Win 10\\Downloads\\flutter`, `C:\\src\\flutter` y `.flutter_sdk_local`. También se puede ejecutar:

```powershell
.\build_apk_ready.ps1
.\build_apk_ready.ps1 -FlutterRoot 'D:\\Herramientas\\flutter'
```

Requisitos: Android SDK en `C:\\Android\\Sdk`, Java 17 o posterior. La primera vez se necesita Internet para descargar dependencias. El APK es release, pero sigue firmado con la clave debug actual; para Play Store falta configurar una keystore de producción, que no se genera ni se guarda aquí.
