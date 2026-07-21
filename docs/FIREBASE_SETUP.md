# Configuración de Firebase para Doccione Studio

Esta guía explica cómo configurar Firebase para habilitar las notificaciones push entre Doccione Studio (escritorio) y Doccione Mobile (Android).

## Paso 1: Crear o seleccionar proyecto Firebase

1. Ve a [Firebase Console](https://console.firebase.google.com/)
2. Inicia sesión con tu cuenta de Google
3. Crea un nuevo proyecto o selecciona uno existente
4. Nombre sugerido: `Doccione Studio`

## Paso 2: Registrar aplicación Android

1. En el proyecto Firebase, haz clic en "Agregar app"
2. Selecciona el icono de Android
3. **Nombre del paquete**: `com.doccione.mobile`
4. **Nombre de la app**: `Doccione Mobile`
5. **Firma de depuración**: Opcional para desarrollo
6. Haz clic en "Registrar app"

## Paso 3: Descargar google-services.json

1. Después de registrar la app, descarga `google-services.json`
2. Colócalo en: `mobile/doccione_mobile/android/app/google-services.json`
3. Este archivo contiene la configuración para que la app Android se conecte a Firebase

## Paso 4: Descargar cuenta de servicio para la PC

1. En Firebase Console, ve a **Configuración del proyecto** (icono de engranaje)
2. Selecciona la pestaña **Cuentas de servicio**
3. Haz clic en **Generar nueva clave privada**
4. Selecciona tu cuenta de servicio (generalmente termina en `@firebase-adminsdk.iam.gserviceaccount.com`)
5. Descarga el archivo JSON (se llamará algo como `firebase-service-account.json`)
6. **IMPORTANTE**: Renómbralo a `firebase-service-account.json` si tiene otro nombre
7. Colócalo en: `secrets/firebase-service-account.json` (en la raíz del proyecto de escritorio)
8. **Alternativa**: Configura la variable de entorno `GOOGLE_APPLICATION_CREDENTIALS` apuntando a este archivo

## Paso 5: Instalar firebase-admin en la PC

1. En el proyecto Doccione Studio, ejecuta:

```powershell
pip install firebase-admin>=6.5
```

2. O instala todas las dependencias:

```powershell
pip install -r requirements.txt
```

## Paso 6: Verificar configuración

1. Ejecuta Doccione Studio
2. Abre el Centro de notificaciones
3. Deberías ver un mensaje indicando que Firebase está inicializado correctamente
4. Si ves "Firebase no configurado", verifica que:
   - `firebase-admin` está instalado
   - `secrets/firebase-service-account.json` existe
   - O que `GOOGLE_APPLICATION_CREDENTIALS` está configurada

## Notas de seguridad

- **NUNCA** commits `firebase-service-account.json` a Git
- **NUNCA** compartas la cuenta de servicio
- El archivo `.gitignore` ya está configurado para excluir:
  - `secrets/`
  - `firebase-service-account.json`
  - `**/firebase-service-account.json`

## Solución de problemas

### Error: "Firebase no inicializado"
- Verifica que `firebase-admin` esté instalado
- Verifica que el archivo de credenciales exista
- Verifica que la variable de entorno esté configurada (si usas esa opción)

### Error: "Token inválido"
- El token FCM del dispositivo puede haber expirado
- El dispositivo debe volver a generar un token
- Usa el botón "Actualizar token" en Doccione Mobile

### Error: "Permiso denegado"
- Verifica que la cuenta de servicio tenga permisos de Cloud Messaging
- En Firebase Console: IAM y administrador > Cuentas de servicio
- Asegúrate de que tenga el rol "Editor" o "Administrador de Firebase Cloud Messaging"
