# Configuracion de Meta Developers para Embedded Signup

Una vez que ejecutaste `tools/start_whatsapp_onboarding.ps1` y tenes la URL publica
de Cloudflare, segui estos pasos en Meta Developers para autorizar el dominio.

---

## Datos necesarios

Estos valores se generan al ejecutar el script y quedan guardados en
`onboarding_tunnel_info.txt` en la raiz del proyecto:

| Variable | Valor ejemplo |
|---|---|
| APP_DOMAIN | `palabras.trycloudflare.com` |
| ONBOARDING_PUBLIC_URL | `https://palabras.trycloudflare.com/` |
| VALID_OAUTH_REDIRECT_URI | `https://palabras.trycloudflare.com/` |

---

## Pasos en Meta Developers

### 1. Configuracion de la app > Basica

1. Ir a: https://developers.facebook.com/apps/1350164413306835/settings/basic/
2. En **Dominios de la app** (App Domains), agregar:
   ```
   APP_DOMAIN
   ```
   (reemplazar APP_DOMAIN por el valor del archivo de informacion)
3. Hacer clic en **Guardar cambios**.

### 2. Inicio de sesion con Facebook para empresas > Configurar

1. Ir a: https://developers.facebook.com/apps/1350164413306835/WhatsApp-Business/settings/
   o buscar "Inicio de sesion con Facebook para empresas" en el menu lateral.
2. Hacer clic en **Configurar** (o Settings).
3. Asegurar que los siguientes valores esten configurados:

   | Opcion | Valor |
   |---|---|
   | Inicio de sesion del cliente OAuth | **Si** |
   | Inicio de sesion OAuth web | **Si** |
   | Aplicar HTTPS | **Si** |
   | Inicio de sesion con SDK JavaScript | **Si** |

4. En **Dominios permitidos para SDK JavaScript** (JavaScript SDK Allowed Domains),
   agregar:
   ```
   APP_DOMAIN
   ```

5. En **URI de redireccionamiento OAuth validos** (Valid OAuth Redirect URIs),
   agregar:
   ```
   VALID_OAUTH_REDIRECT_URI
   ```

6. **No cambiar ninguna otra opcion.**
7. Hacer clic en **Guardar cambios**.

### 3. Verificar configuracion

1. Volver a la URL publica del tunel en el navegador.
2. Hacer clic en "Conectar WhatsApp Business".
3. El SDK de Facebook deberia cargar sin errores de dominio.
4. Embedded Signup deberia abrirse correctamente.

---

## Solucion de problemas

| Error | Causa probable | Solucion |
|---|---|---|
| "No se puede cargar la URL. El dominio de esta URL no esta incluido en los dominios de la app." | APP_DOMAIN no configurado en Meta | Verificar Paso 1 |
| "URL bloqueada: esta URL de redireccionamiento no esta en la lista blanca" | VALID_OAUTH_REDIRECT_URI no configurado | Verificar Paso 2.5 |
| "El SDK no se pudo cargar" | Dominio no permitido para JS SDK | Verificar Paso 2.4 |
| Error de CORS en consola | Origen no permitido | Verificar que la URL en el navegador coincida exactamente con lo configurado |

---

## Notas importantes

- La URL de Cloudflare cambia cada vez que se reinicia el tunel.
- Si detenes y reinicias el script, deberas actualizar los valores en Meta.
- Para produccion, considera usar un dominio personalizado en Cloudflare en lugar
  de `*.trycloudflare.com`.
- Nunca compartas la URL publica del tunel: cualquiera que la conozca puede
  acceder al servidor de onboarding local.
