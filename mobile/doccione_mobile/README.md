# Doccione Mobile

Aplicación Android para que cada vendedor opere pedidos y producción de
Doccione Studio desde la red local, una VPN o Internet mediante HTTPS.

## Qué permite hacer

- Iniciar sesión con el usuario y la contraseña de un vendedor antes de
  vincular el teléfono con un código de seis dígitos.
- Conservar la sesión en el almacenamiento seguro del sistema y entrar
  directamente en los siguientes usos, sin guardar la contraseña.
- Configurar IP, puerto y esquema del servidor Studio; probar la conexión antes de guardarla.
- Sincronizar pedidos, clientes y trabajos a una base local SQLite para consultar el contenido sin esperar al servidor.
- Ver métricas, buscar y filtrar pedidos, y consultar su detalle.
- Cambiar estados, prioridades y etapas de producción; ajustar cantidad/tamaño, registrar cobros y marcar entregas.
- Recibir notificaciones Firebase, abrir su detalle desde primer plano, segundo plano o aplicación cerrada, y actualizar el token FCM.

## Catálogo de diseños

El acceso se abre desde el ícono de colección del panel principal. El catálogo muestra únicamente una miniatura PNG generada por Studio: la ruta y el archivo original nunca se envían al teléfono.

Para habilitar un diseño, marcálo como **reutilizable** y sacalo del estado **privado** en Doccione Studio. Esta es una autorización explícita; los diseños privados o no reutilizables no aparecen en el móvil. Asignar categorías y etiquetas en Studio permite encontrarlos desde el buscador móvil. Desde cada miniatura se puede elegir material, cantidad y tamaño, sumar varias líneas a un pedido y enviarlo a Studio con los datos del cliente.

Las ediciones operativas requieren conectividad: todavía no existe una cola de cambios offline ni sincronización de vuelta diferida.

## Preparación

1. Instalar Flutter y Android Studio, y ejecutar `flutter pub get` en esta carpeta.
2. Crear `android/local.properties` con las rutas del SDK Android y Flutter.
3. Configurar Firebase: ubicar `google-services.json` en `android/app/`. No subir este archivo al repositorio.
4. Iniciar Doccione Studio. Su API móvil debe escuchar en `0.0.0.0:8765`.
5. En **Configuración → Acceso móvil → Vendedores y contraseñas**, crear al
   menos un vendedor activo. La contraseña debe tener diez caracteres o más,
   con letras y números.
6. En Windows, permitir conexiones TCP entrantes al puerto configurado en Firewall.
7. Para Wi-Fi o VPN, usar la IP privada de la PC. En el teléfono no usar
   `localhost`, `127.0.0.1` ni `0.0.0.0`.

## Flujo operativo

1. Abrir Configuración del servidor, ingresar IP/puerto y usar **Probar conexión**.
2. Ingresar el usuario y la contraseña creados en Studio.
3. Generar en Studio el código de vinculación e ingresarlo en el teléfono.
4. La app guarda únicamente el token de sesión y abre el panel directamente
   desde el siguiente inicio.
5. Esperar la sincronización inicial o ejecutar sincronización manual desde el panel.
6. Operar pedidos y trabajos. Tras cada cambio, refrescar para confirmar el estado publicado por Studio.

## Uso desde cualquier lugar

Hay dos configuraciones seguras:

- **VPN privada:** conectar la PC y el teléfono a la misma VPN y elegir
  **Local / VPN** en la app. Se usa la IP privada asignada a la PC.
- **Dominio público:** publicar Studio detrás de un reverse proxy con
  certificado TLS y elegir **Externa (Datos)**. La app exige `https`.

No se deben exponer directamente a Internet ni el puerto HTTP 8765 ni las
contraseñas. El backend rechaza login y vinculación por HTTP cuando la
conexión llega desde una IP pública. Para vendedores itinerantes, la whitelist
de IP debe permanecer deshabilitada, porque su IP cambia entre Wi-Fi y datos
móviles; el control de acceso es la cuenta, el código de un solo uso y el token
revocable del dispositivo.

Cambiar la contraseña o desactivar al vendedor desde Studio revoca todos sus
dispositivos. La próxima sincronización devuelve el teléfono al login.

## Verificación antes de publicar

- Ejecutar `flutter test` y `flutter analyze`.
- Probar vinculación y sincronización con datos reales desde un teléfono.
- Probar una notificación FCM con la app abierta, en segundo plano y cerrada.
- Configurar una clave de firma de producción: actualmente la configuración de release usa la clave de depuración y no debe distribuirse como versión final.

## Alcance actual

La aplicación está preparada y configurada para Android. HTTPS debe utilizarse siempre que la app salga de una red local confiable.
