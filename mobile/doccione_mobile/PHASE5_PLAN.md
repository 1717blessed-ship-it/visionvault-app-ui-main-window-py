# Plan de Implementación — Fase 5: Integración Real Doccione Mobile ↔ Studio

## Restricciones Obligatorias

1. No modificar modelos Order, Job ni OrderWithDetails.
2. No crear sistema de vinculación nuevo; reutilizar autenticación/token existente.
3. Localizar y documentar todas las URLs hardcodeadas y puertos antes del primer cambio.
4. Configuración: host, puerto, esquema http/https, baseUrl calculada en único lugar.
5. No guardar URL completa duplicada en SQLite. Guardar host, puerto, esquema; construir baseUrl desde ServerConfig.
6. Validar host y rango de puerto antes de guardar.
7. Botón "Probar conexión" debe llamar a endpoint real de Studio, no solo verificar que el puerto responda.
8. Mantener última configuración válida si prueba de conexión falla.
9. Servidor de Studio debe poder escuchar en 0.0.0.0, no solo localhost.
10. Documentar regla de Windows Firewall y prueba con PC y teléfono en mismo Wi-Fi.
11. No implementar url_launcher, WhatsApp, Firebase ni sincronización en segundo plano.
12. No usar git rebase, reset ni stash.
13. No afirmar que Flutter tests o APK build pasaron si no fueron ejecutados.

---

## Auditoría de URLs Hardcodeadas

| Archivo | Línea | URL hardcodeada | Uso |
|---------|-------|-----------------|-----|
| `lib/screens/home_screen.dart` | 119 | `http://localhost:8765/api/device/update-token` | Renovación token FCM |
| `lib/screens/home_screen.dart` | 156 | `http://localhost:8765/api/pair/validate` | Vinculación de dispositivo |
| `lib/screens/dashboard_screen.dart` | 63 | `http://localhost:5000` | Base URL para SyncApiClient |
| `lib/widgets/sync_status_card.dart` | 54 | `http://localhost:8000` | Base URL para SyncApiClient |

**Puertos encontrados**: 8765, 5000, 8000 (3 valores diferentes, inconsistencia confirmada).

---

## ETAPA 1 — Configuración Centralizada del Servidor

### 1.1 Auditar URLs actuales
- Completada arriba.

### 1.2 Crear ServerConfig inmutable

**Archivo**: `lib/config/server_config.dart`

```dart
class ServerConfig {
  final String host;    // Ej: '192.168.1.50', 'localhost', '0.0.0.0'
  final int port;       // Ej: 8765
  final String scheme;  // 'http' o 'https'

  const ServerConfig({
    required this.host,
    required this.port,
    required this.scheme,
  });

  String get baseUrl => '$scheme://$host:$port';

  // Valores por defecto para Studio en red local
  static const ServerConfig defaults = ServerConfig(
    host: '192.168.1.100',
    port: 8765,
    scheme: 'http',
  );

  // Validación
  static bool isValidHost(String host) {
    // IP válida, localhost, o hostname
    return host.isNotEmpty && host.length <= 255;
  }

  static bool isValidPort(int port) {
    return port >= 1 && port <= 65535;
  }

  static bool isValidScheme(String scheme) {
    return scheme == 'http' || scheme == 'https';
  }

  // Serialización
  Map<String, dynamic> toMap() => {
    'host': host,
    'port': port,
    'scheme': scheme,
  };

  factory ServerConfig.fromMap(Map<String, dynamic> map) => ServerConfig(
    host: map['host'] as String? ?? '192.168.1.100',
    port: map['port'] as int? ?? 8765,
    scheme: map['scheme'] as String? ?? 'http',
  );

  ServerConfig copyWith({String? host, int? port, String? scheme}) {
    return ServerConfig(
      host: host ?? this.host,
      port: port ?? this.port,
      scheme: scheme ?? this.scheme,
    );
  }
}
```

### 1.3 Crear ServerConfigRepository

**Archivo**: `lib/database/server_config_repository.dart`

```dart
class ServerConfigRepository {
  final DatabaseHelper _dbHelper;

  ServerConfigRepository(this._dbHelper);

  Future<ServerConfig> getConfig() async {
    final db = await _dbHelper.database;
    final result = await db.query('server_config', where: 'id = 1');
    if (result.isEmpty) return ServerConfig.defaults;
    return ServerConfig.fromMap(result.first);
  }

  Future<void> updateConfig(ServerConfig config) async {
    final db = await _dbHelper.database;
    await db.update(
      'server_config',
      config.toMap(),
      where: 'id = 1',
    );
  }
}
```

### 1.4 Crear migración SQLite segura

**Archivo**: `lib/database/database_helper.dart`

Cambios:
- `_databaseVersion` → 2
- `_onCreate`: agregar tabla `server_config` + INSERT defaults
- `_onUpgrade`: crear tabla si `oldVersion < 2`

```sql
CREATE TABLE server_config (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  host TEXT NOT NULL DEFAULT '192.168.1.100',
  port INTEGER NOT NULL DEFAULT 8765,
  scheme TEXT NOT NULL DEFAULT 'http'
);
```

**Compatibilidad con bases existentes**: La migración solo crea la tabla si no existe. No toca tablas existentes (jobs, orders, clients, sync_state). Los datos existentes no se pierden.

### 1.5 Tests

**Archivo**: `test/config/server_config_test.dart`
- Serialización toMap/fromMap
- Valores por defecto
- Validación de host y puerto
- baseUrl se construye correctamente

**Archivo**: `test/database/server_config_repository_test.dart`
- Persistencia: guardar y leer config
- Valores por defecto se insertan al crear DB

---

## ETAPA 2 — Pantalla de Configuración (próxima etapa)

---

## ETAPA 3 — Integración con Servicios Existentes (próxima etapa)

---

## ETAPA 4 — Prueba de Conexión (próxima etapa)

---

## ETAPA 5 — Sincronización Real (próxima etapa)

---

## ETAPA 6 — APK Release (próxima etapa)

---

## Archivos — Etapa 1

### Crear
| Archivo | Responsabilidad |
|---------|-----------------|
| `lib/config/server_config.dart` | Modelo inmutable de configuración |
| `lib/database/server_config_repository.dart` | Persistencia en SQLite |
| `test/config/server_config_test.dart` | Tests del modelo |
| `test/database/server_config_repository_test.dart` | Tests del repository |

### Modificar
| Archivo | Cambios |
|---------|---------|
| `lib/database/database_helper.dart` | Tabla `server_config`, migración v1→v2 |

### NO modificar (Etapa 1)
- `home_screen.dart`
- `dashboard_screen.dart`
- `sync_status_card.dart`
- `sync_api_client.dart`
- Modelos Order, Job, OrderWithDetails

---

## Orden de Commits

1. **Commit 1**: feat(phase5): add persistent server configuration
2. **Commit 2**: feat(phase5): add server configuration screen
3. **Commit 3**: feat(phase5): integrate config into home_screen pairing flow
4. **Commit 4**: feat(phase5): integrate config into sync services + connection test
5. **Commit 5**: feat(phase5): final verification + release APK

---

## Documentación — Windows Firewall y Red

Al finalizar la Etapa 2, crear sección en README o archivo dedicado:
- Cómo abrir el puerto en Windows Firewall (regla de entrada)
- Verificar que PC y teléfono están en la misma red Wi-Fi
- Probar con `ping` desde el teléfono a la IP de la PC
- Studio debe escuchar en `0.0.0.0`, no `127.0.0.1`

---

## Resultado Esperado

1. Abrir Doccione Studio en la PC (escuchando en 0.0.0.0:8765)
2. Instalar APK en teléfono Android
3. Configurar IP/puerto desde la pantalla de configuración
4. Vincular dispositivo mediante código de 6 dígitos
5. Sincronizar pedidos, clientes y trabajos reales
6. Consultar pedidos desde el teléfono
7. Mantener sesión iniciada entre reinicios
8. Generar APK Release listo para distribuir
