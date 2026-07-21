# Guía Completa de Configuración - Doccione Mobile

Esta guía explica paso a paso cómo configurar el sistema completo de notificaciones push entre Doccione Studio (escritorio) y Doccione Mobile (Android).

## Requisitos previos

### Para Doccione Studio (PC)
- Python 3.13+ instalado
- Acceso a Firebase Console
- `firebase-admin` instalado (ver Paso 1)

### Para Doccione Mobile (Android)
- Flutter SDK instalado
- Android Studio instalado
- Dispositivo Android físico (Android 5.0+)
- Cuenta de Google

---

## Paso 1: Instalar Flutter SDK

1. Descargar Flutter SDK desde [flutter.dev](https://flutter.dev/docs/get-started/install/windows)
2. Extraer en `C:\flutter` (o tu ruta preferida)
3. Agregar `C:\flutter\bin` al PATH del sistema
4. Verificar instalación:

```powershell
flutter --version
```

5. Ejecutar `flutter doctor` y resolver dependencias faltantes

---

## Paso 2: Crear proyecto Firebase

1. Ir a [Firebase Console](https://console.firebase.google.com/)
2. Iniciar sesión con cuenta de Google
3. Hacer clic en "Agregar proyecto"
4. Nombre del proyecto: `Doccione Studio`
5. Habilitar Google Analytics (opcional)
6. Hacer clic en "Crear proyecto"

---

## Paso 3: Registrar aplicación Android

1. En el proyecto Firebase, hacer clic en "Agregar app"
2. Seleccionar icono Android
3. **Nombre del paquete**: `com.doccione.mobile`
4. **Nombre de la app**: `Doccione Mobile`
5. **Firma de depuración**: Opcional para desarrollo
6. Hacer clic en "Registrar app"

---

## Paso 4: Configurar Android (google-services.json)

1. Descargar `google-services.json` desde Firebase Console
2. Colocar en: `mobile/doccione_mobile/android/app/google-services.json`
3. Este archivo conecta la app Android con Firebase

---

## Paso 5: Configurar PC (firebase-service-account.json)

### Opción A: Archivo local (recomendado)

1. En Firebase Console, ir a **Configuración del proyecto** (engranaje)
2. Pestaña **Cuentas de servicio**
3. Hacer clic en **Generar nueva clave privada**
4. Seleccionar cuenta de servicio (termina en `@firebase-adminsdk.iam.gserviceaccount.com`)
5. Descargar archivo JSON
6. Renombrar a `firebase-service-account.json`
7. Colocar en: `secrets/firebase-service-account.json` (raíz del proyecto)

### Opción B: Variable de entorno

1. Colocar el archivo JSON en cualquier ubicación segura
2. Configurar variable de entorno:

```powershell
setx GOOGLE_APPLICATION_CREDENTIALS "C:\ruta\a\firebase-service-account.json"
```

3. Reiniciar terminal/IDE

---

## Paso 6: Instalar dependencias Python

En el directorio del proyecto Doccione Studio:

```powershell
pip install -r requirements.txt
```

Esto instalará `firebase-admin>=6.5` automáticamente.

---

## Paso 7: Configurar Flutter

1. Navegar a `mobile/doccione_mobile/`
2. Editar `android/local.properties`:

```properties
sdk.dir=C:\\Users\\TuUsuario\\AppData\\Local\\Android\\sdk
flutter.sdk=C:\\flutter
```

3. Instalar dependencias Flutter:

```powershell
flutter pub get
```

---

## Paso 8: Ejecutar Doccione Mobile

1. Conectar dispositivo Android vía USB
2. Habilitar depuración USB en el dispositivo
3. Verificar conexión:

```powershell
flutter devices
```

4. Ejecutar la app:

```powershell
flutter run
```

---

## Paso 9: Obtener token FCM

1. En Doccione Mobile, esperar a que Firebase se conecte
2. Copiar el token FCM mostrado en pantalla
3. Usar el botón "Copiar" para facilitar esto

---

## Paso 10: Registrar dispositivo en Doccione Studio

1. Abrir Doccione Studio
2. Ir al Centro de notificaciones
3. Hacer clic en "Agregar dispositivo"
4. Pegar el token FCM
5. Nombre del dispositivo: `Doccione Mobile`
6. Plataforma: `Android`
7. Hacer clic en "Guardar"

---

## Paso 11: Enviar notificación de prueba

1. En Doccione Studio, Centro de notificaciones
2. Seleccionar el dispositivo registrado
3. Hacer clic en "Enviar prueba"
4. Verificar recepción en el dispositivo Android

---

## Paso 12: Verificar recepción en tres estados

### App abierta
- Debería aparecer notificación local en pantalla
- También en lista de notificaciones de la app

### App en segundo plano
- Debería aparecer notificación en barra de estado
- Al tocar, abrir la app y mostrar detalle

### App cerrada
- Debería aparecer notificación en barra de estado
- Al tocar, abrir la app y mostrar detalle

---

## Paso 13: Verificar outbox en Doccione Studio

1. En Centro de notificaciones de Doccione Studio
2. Ver estadísticas del outbox
3. El mensaje debería estar en estado `sent`

---

## Solución de problemas

### Flutter no se reconoce
- Verificar que Flutter esté en el PATH
- Reiniciar terminal/IDE

### Error: "google-services.json no encontrado"
- Verificar que el archivo esté en `android/app/`
- Verificar que el nombre sea exactamente `google-services.json`

### Error: "Firebase no inicializado" (PC)
- Verificar que `firebase-admin` esté instalado
- Verificar que `firebase-service-account.json` exista
- Verificar variable de entorno si usas esa opción

### Error: "Permiso denegado" (Firebase)
- Verificar permisos de la cuenta de servicio
- En Firebase Console: IAM y administrador > Cuentas de servicio
- Asegurar rol "Editor" o "Administrador de Firebase Cloud Messaging"

### Token inválido
- El token FCM puede haber expirado
- Usar botón "Actualizar token" en Doccione Mobile
- Registrar nuevo token en Doccione Studio

### No se reciben notificaciones
- Verificar que el dispositivo esté registrado
- Verificar que las preferencias de notificación estén activadas
- Verificar que el dispositivo no esté en modo "No molestar"
- Verificar que la app tenga permiso de notificaciones

---

## Seguridad

**IMPORTANTE:**
- NUNCA commitear `firebase-service-account.json` a Git
- NUNCA commitear `google-services.json` a Git
- NUNCA compartir credenciales de Firebase
- El `.gitignore` ya está configurado para excluir estos archivos

---

## Próximos pasos

Una vez que la notificación de prueba funcione correctamente:

1. ✅ El sistema está listo para producción
2. Los eventos de Doccione Studio se enviarán automáticamente
3. Puedes configurar preferencias por dispositivo
4. Puedes agregar más dispositivos Android
