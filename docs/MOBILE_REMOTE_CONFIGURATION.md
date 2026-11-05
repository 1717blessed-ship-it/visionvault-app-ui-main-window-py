# Configuración remota de Doccione Mobile

Studio publica una configuración operativa dentro de
`GET /api/v1/mobile/capabilities`. El contrato de sincronización anterior se
conserva y la configuración nueva viaja en `runtime_config`.

## Cambios que alcanzan al APK instalado

Después de actualizar y reiniciar Doccione Studio, el servidor puede:

- pausar mutaciones mediante modo mantenimiento;
- habilitar o deshabilitar catálogo de diseños, productos, pedidos de
  stickers, edición rápida, cobros y notificaciones push;
- cambiar la cantidad de diseños entregados al catálogo antiguo;
- personalizar un prefijo o pie para notificaciones;
- seguir publicando diseños, productos, precios, descuentos, usuarios y
  permisos desde las fuentes existentes de Studio.

El APK instalado no puede mostrar anuncios ni reconstruir sus controles con
opciones nuevas, pero el servidor hace cumplir las restricciones y devuelve
mensajes compatibles.

## Cambios preparados para la próxima versión móvil

La aplicación Flutter ahora interpreta `runtime_config` con valores locales de
respaldo. Una vez publicada esa versión podrá, sin nuevos APK:

- mostrar anuncios, mantenimiento y avisos de actualización;
- ocultar accesos rápidos mediante feature flags;
- recibir etapas y colores del workflow;
- recibir materiales, medios de pago, prioridades, estados editables y
  formatos de stickers;
- mostrar miniaturas de productos servidas por la API sin exponer rutas de la
  PC.

Si Studio es antiguo, no responde o entrega una configuración incompleta, la
app usa sus valores integrados y continúa sincronizando.

## Administración en Studio

Abrir **Configuración y herramientas → App móvil**. Desde allí se publican:

- funciones habilitadas;
- anuncio y mantenimiento;
- versión mínima, versión recomendada y URL de actualización;
- materiales, medios de pago, formatos y estados;
- tamaño del catálogo y personalización general de push.

Los formatos de stickers se limitan a los cuatro formatos que el motor de
cotización actual conoce. Se pueden ocultar o reordenar, pero agregar un nombre
nuevo requiere implementar primero su regla operativa.

## Claves avanzadas

Los templates push por evento se pueden guardar en `app_settings` con este
formato:

```text
mobile_runtime.notification.<event_type>.title
mobile_runtime.notification.<event_type>.message
```

Aceptan `{title}`, `{message}` y `{event_type}`. Un template inválido se ignora
y conserva el texto original.
