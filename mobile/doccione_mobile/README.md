# Doccione Mobile

Aplicación Android MVP para recibir notificaciones push de Doccione Studio.

## Requisitos previos

1. **Flutter SDK**: Instalar desde [flutter.dev](https://flutter.dev/docs/get-started/install)
2. **Android Studio**: Para compilar y ejecutar en Android
3. **Dispositivo Android físico**: Para probar notificaciones reales

## Instalación

1. Clonar o navegar al directorio `mobile/doccione_mobile/`
2. Ejecutar `flutter pub get`
3. Configurar `android/local.properties` con las rutas correctas:
   - `sdk.dir`: Ruta al Android SDK
   - `flutter.sdk`: Ruta al Flutter SDK

## Configuración de Firebase

1. Seguir la guía en `../../docs/FIREBASE_SETUP.md`
2. Colocar `google-services.json` en `android/app/`
3. El `applicationId` es `com.doccione.mobile`

## Ejecutar la aplicación

```bash
flutter run
```

## Funcionalidades

- ✅ Inicialización de Firebase
- ✅ Solicitud de permisos de notificaciones
- ✅ Canales Android (urgent, orders, production)
- ✅ Obtención y display de token FCM
- ✅ Botón para copiar token
- ✅ Botón para actualizar token
- ✅ Recepción de notificaciones (abierto, background, cerrado)
- ✅ Notificación local cuando app está abierta
- ✅ Pantalla de detalle al tocar notificación

## Prueba de notificaciones

1. Abrir Doccione Mobile
2. Copiar el token FCM
3. Registrar el dispositivo en Doccione Studio (Centro de notificaciones)
4. Enviar notificación de prueba desde Doccione Studio
5. Verificar recepción en los tres estados:
   - App abierta
   - App en segundo plano
   - App cerrada
