# Doccione Cloud

Base de despliegue para que la aplicación móvil no dependa de una IP local.
El VPS publica únicamente HTTPS y contiene PostgreSQL junto con la API. Cada
usuario pertenece a una organización, por lo que los datos de empresas
distintas no se cruzan.

## Qué está listo

- Docker Compose para PostgreSQL, API y HTTPS automático con Caddy.
- Healthcheck compatible con la app móvil: `/api/v1/mobile/health`.
- Creación protegida de la primera organización y propietario.
- Inicio de sesión con contraseña Argon2 y token firmado de 30 días.
- Aislamiento de organización incluido en el token y en el modelo de usuarios.

## Puesta en marcha en un VPS nuevo

1. Crear un VPS Ubuntu LTS con IP pública y asociar un dominio, por ejemplo
   `api.doccione.com`, a esa IP (registro DNS `A`).
2. Instalar Docker Engine y Docker Compose Plugin en el VPS.
3. Copiar la carpeta `cloud` al servidor, duplicar `.env.example` como `.env`
   y reemplazar todos los secretos. Agregar también `DOMAIN=api.doccione.com`.
4. Abrir solo los puertos TCP 80 y 443 en el firewall del VPS.
5. Ejecutar `docker compose up -d --build` desde esta carpeta.
6. Confirmar `https://api.doccione.com/api/v1/mobile/health`.
7. Crear la empresa una sola vez con el token de bootstrap:

```bash
curl -X POST https://api.doccione.com/api/v1/platform/bootstrap \
  -H 'Content-Type: application/json' \
  -H 'X-Bootstrap-Token: EL_SECRETO_DE_BOOTSTRAP' \
  -d '{"organization_name":"Mi empresa","organization_slug":"mi-empresa","owner_email":"admin@example.com","owner_password":"UnaClaveLarga123"}'
```

Después de crear la primera empresa, rotar `BOOTSTRAP_TOKEN` o restringir este
endpoint por red hasta incorporar el panel de altas administrativas.

## Trabajo que continúa

Esta base no migra automáticamente la SQLite local todavía. Los siguientes
módulos deben llevarse a la API cloud, conservando los contratos que ya usa la
app Android: pedidos, trabajos, catálogo, cobros, sincronización incremental,
archivos y notificaciones. La app debe recibir la URL fija de producción al
compilarse, sin mostrar configuración de IP al vendedor.

No se debe exponer el puerto 8765 ni la base PostgreSQL al público.
