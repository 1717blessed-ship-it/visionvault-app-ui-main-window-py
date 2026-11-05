import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import '../config/app_identity.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:http/http.dart' as http;
import 'dashboard_screen.dart';
import 'server_config_screen.dart';
import '../config/server_config.dart';
import '../database/database_helper.dart';
import '../database/server_config_repository.dart';
import '../services/sync_api_client.dart';

class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  String _firebaseStatus = 'Inicializando...';
  String? _fcmToken;
  String _deviceName = 'Desconocido';
  bool _isPaired = false;
  String _pairingStatus = 'No vinculado';
  final FlutterLocalNotificationsPlugin _localNotifications =
      FlutterLocalNotificationsPlugin();
  final List<RemoteMessage> _notifications = [];
  final TextEditingController _pairingCodeController = TextEditingController();
  final TextEditingController _usernameController = TextEditingController();
  final TextEditingController _passwordController = TextEditingController();
  final FlutterSecureStorage _secureStorage = const FlutterSecureStorage();
  StreamSubscription<String>? _tokenRefreshSubscription;
  StreamSubscription<RemoteMessage>? _foregroundMessageSubscription;
  StreamSubscription<RemoteMessage>? _openedMessageSubscription;
  String? _sessionToken;
  String? _linkToken;
  String _sellerName = '';
  bool _credentialsAccepted = false;
  bool _isAuthenticating = false;
  bool _isPairing = false;
  bool _showPassword = false;
  String _authStatus = 'Ingresá con la cuenta creada en Doccione Studio.';
  String _baseUrl = ServerConfig.defaults.baseUrl;
  bool _configLoaded = false;
  String? _configError;
  static const _unreachableHosts = {'localhost', '127.0.0.1', '0.0.0.0', ''};

  String get _pairingUrl => _baseUrl;

  @override
  void initState() {
    super.initState();
    _loadServerConfig();
    _loadSessionToken();
    _initializeFirebase();
    _initializeLocalNotifications();
    _setupMessageHandlers();
  }

  @override
  void dispose() {
    _tokenRefreshSubscription?.cancel();
    _foregroundMessageSubscription?.cancel();
    _openedMessageSubscription?.cancel();
    _pairingCodeController.dispose();
    _usernameController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _loadSessionToken() async {
    final token = await _secureStorage.read(key: 'session_token');
    if (!mounted) return;
    if (token != null) {
      setState(() {
        _sessionToken = token;
        _isPaired = true;
        _pairingStatus = 'Vinculado';
      });
    }
  }

  Future<void> _loadServerConfig() async {
    try {
      final repository = ServerConfigRepository(DatabaseHelper());
      final config = await repository.getConfig();
      if (!mounted) return;
      if (_unreachableHosts.contains(config.host)) {
        setState(() {
          _configLoaded = false;
          _configError = 'Configurá la IP de la PC antes de vincular';
        });
        return;
      }
      setState(() {
        _baseUrl = config.baseUrl;
        _configLoaded = true;
        _configError = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _configLoaded = false;
        _configError = 'Error cargando configuración: $e';
      });
    }
  }

  Future<void> _saveSessionToken(String token) async {
    await _secureStorage.write(key: 'session_token', value: token);
    if (!mounted) return;
    setState(() {
      _sessionToken = token;
    });
  }

  Future<void> _clearSessionToken() async {
    try {
      await DatabaseHelper().clearSessionCaches();
    } catch (_) {
      // El cierre de sesión nunca debe quedar bloqueado por la caché local.
    }
    await _secureStorage.delete(key: 'session_token');
    await _secureStorage.delete(key: 'seller_username');
    await _secureStorage.delete(key: 'seller_display_name');
    await _secureStorage.delete(key: 'seller_user_id');
    if (!mounted) return;
    setState(() {
      _sessionToken = null;
      _linkToken = null;
      _credentialsAccepted = false;
      _sellerName = '';
    });
  }

  Future<void> _logout() async {
    final token = _sessionToken;
    if (token != null && _configLoaded) {
      try {
        await http
            .post(
              Uri.parse('$_baseUrl/api/v1/mobile/auth/logout'),
              headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer $token',
              },
              body: '{}',
            )
            .timeout(const Duration(seconds: 10));
      } catch (_) {
        // La sesión local debe cerrarse aunque el servidor esté sin conexión.
      }
    }
    await _clearSessionToken();
    if (!mounted) return;
    setState(() {
      _isPaired = false;
      _pairingStatus = 'No vinculado';
      _authStatus = 'Ingresá con la cuenta creada en Doccione Studio.';
    });
  }

  Future<void> _handleSessionExpired() async {
    await _clearSessionToken();
    if (!mounted) return;
    setState(() {
      _isPaired = false;
      _pairingStatus = 'La sesión venció o fue revocada.';
      _authStatus = 'Iniciá sesión nuevamente para vincular este dispositivo.';
    });
  }

  String _apiError(http.Response response, String fallback) {
    try {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return data['error']?.toString() ?? fallback;
    } catch (_) {
      return fallback;
    }
  }

  Future<void> _authenticateSeller() async {
    final username = _usernameController.text.trim();
    final password = _passwordController.text;
    if (username.isEmpty || password.isEmpty) {
      setState(() {
        _authStatus = 'Ingresá usuario y contraseña.';
      });
      return;
    }
    if (!_configLoaded) {
      setState(() {
        _authStatus = 'Configurá el servidor antes de iniciar sesión.';
      });
      return;
    }

    setState(() {
      _isAuthenticating = true;
      _authStatus = 'Verificando credenciales...';
    });
    try {
      final response = await http
          .post(
            Uri.parse('$_baseUrl/api/v1/mobile/auth/login'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'username': username, 'password': password}),
          )
          .timeout(const Duration(seconds: 20));
      if (!mounted) return;
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        final user = data['user'] as Map<String, dynamic>? ?? {};
        final token = data['link_token']?.toString() ?? '';
        if (token.isEmpty) {
          throw const FormatException('El servidor no devolvió autorización');
        }
        setState(() {
          _linkToken = token;
          _sellerName =
              user['display_name']?.toString().trim().isNotEmpty == true
                  ? user['display_name'].toString()
                  : user['username']?.toString() ?? username;
          _credentialsAccepted = true;
          _isAuthenticating = false;
          _passwordController.clear();
          _authStatus = 'Identidad verificada';
          _pairingStatus = 'Ingresá el código que muestra Studio.';
        });
      } else {
        setState(() {
          _isAuthenticating = false;
          _authStatus = _apiError(
            response,
            'No se pudo iniciar sesión (${response.statusCode}).',
          );
        });
      }
    } on TimeoutException {
      if (!mounted) return;
      setState(() {
        _isAuthenticating = false;
        _authStatus = 'El servidor tardó demasiado en responder.';
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _isAuthenticating = false;
        _authStatus = 'No se pudo conectar: $error';
      });
    }
  }

  Future<void> _initializeFirebase() async {
    try {
      _deviceName = await _getDeviceName();

      // Solicitar permisos de notificación (Android 13+)
      FirebaseMessaging messaging = FirebaseMessaging.instance;
      NotificationSettings settings = await messaging.requestPermission(
        alert: true,
        announcement: false,
        badge: true,
        carPlay: false,
        criticalAlert: false,
        provisional: false,
        sound: true,
      );
      if (!mounted) return;

      // Android entrega el token FCM aunque el usuario no permita mostrar
      // notificaciones. El token sigue siendo necesario para identificar el
      // dispositivo durante el emparejamiento con Studio.
      _fcmToken = await messaging.getToken();
      if (!mounted) return;

      if (settings.authorizationStatus == AuthorizationStatus.authorized) {
        setState(() {
          _firebaseStatus = 'Conectado - Permisos otorgados';
        });
      } else if (settings.authorizationStatus ==
          AuthorizationStatus.provisional) {
        setState(() {
          _firebaseStatus = 'Conectado - Permisos provisionales';
        });
      } else {
        setState(() {
          _firebaseStatus = 'Permisos denegados';
        });
      }

      // Escuchar renovación de token
      _tokenRefreshSubscription =
          FirebaseMessaging.instance.onTokenRefresh.listen((newToken) {
        if (!mounted) return;
        final previousToken = _fcmToken;
        setState(() {
          _fcmToken = newToken;
        });
        if (previousToken != null && previousToken != newToken) {
          _updateTokenOnServer(previousToken, newToken);
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _firebaseStatus = 'Error: $e';
      });
    }
  }

  Future<void> _updateTokenOnServer(String oldToken, String newToken) async {
    final sessionToken = _sessionToken;
    if (sessionToken == null) return;
    try {
      final response = await http
          .post(
            Uri.parse('$_pairingUrl/api/device/update-token'),
            headers: {
              'Content-Type': 'application/json',
              'Authorization': 'Bearer $sessionToken',
            },
            body: jsonEncode({
              'old_token': oldToken,
              'new_token': newToken,
            }),
          )
          .timeout(const Duration(seconds: 15));
      // La próxima renovación reintentará si el servidor no aceptó el token.
      if (response.statusCode != 200) return;
    } catch (_) {}
  }

  Future<void> _pairDevice() async {
    final linkToken = _linkToken;
    if (!_credentialsAccepted || linkToken == null) {
      setState(() {
        _pairingStatus = 'Primero iniciá sesión.';
      });
      return;
    }
    final code = _pairingCodeController.text.trim();
    if (code.length != 6 || int.tryParse(code) == null) {
      setState(() {
        _pairingStatus = 'Código debe tener 6 dígitos';
      });
      return;
    }

    if (_fcmToken == null) {
      setState(() {
        _pairingStatus = 'Token FCM no disponible';
      });
      return;
    }

    setState(() {
      _isPairing = true;
      _pairingStatus = 'Vinculando...';
    });

    try {
      final response = await http
          .post(
            Uri.parse('$_pairingUrl/api/pair/validate'),
            headers: {
              'Content-Type': 'application/json',
              'Authorization': 'Bearer $linkToken',
            },
            body: jsonEncode({
              'code': code,
              'push_token': _fcmToken,
              'platform': 'android',
              'device_name': _deviceName,
              'app_version': AppIdentity.fullVersion,
            }),
          )
          .timeout(const Duration(seconds: 20));
      if (!mounted) return;

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        if (data['success'] == true) {
          // Guardar session token en almacenamiento seguro
          final sessionToken = data['session_token'];
          if (sessionToken != null) {
            await _saveSessionToken(sessionToken);
            final user = data['user'] as Map<String, dynamic>? ?? {};
            await _secureStorage.write(
              key: 'seller_username',
              value: user['username']?.toString() ??
                  _usernameController.text.trim(),
            );
            await _secureStorage.write(
              key: 'seller_display_name',
              value: user['display_name']?.toString() ?? _sellerName,
            );
            final userId = user['id']?.toString().trim();
            if (userId != null && userId.isNotEmpty) {
              await _secureStorage.write(key: 'seller_user_id', value: userId);
            }
          }
          if (!mounted) return;
          setState(() {
            _isPaired = true;
            _isPairing = false;
            _pairingStatus = 'Vinculado exitosamente';
            _pairingCodeController.clear();
          });
        } else {
          setState(() {
            _isPairing = false;
            _pairingStatus = 'Error: ${data['error']}';
          });
        }
      } else {
        setState(() {
          _isPairing = false;
          _pairingStatus = _apiError(
            response,
            'Error del servidor: ${response.statusCode}',
          );
          if (response.statusCode == 401) {
            _credentialsAccepted = false;
            _linkToken = null;
            _authStatus = 'La autorización venció. Iniciá sesión nuevamente.';
          }
        });
      }
    } on TimeoutException {
      if (!mounted) return;
      setState(() {
        _isPairing = false;
        _pairingStatus = 'El servidor tardó demasiado en responder.';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _isPairing = false;
        _pairingStatus = 'Error de conexión: $e';
      });
    }
  }

  Future<void> _initializeLocalNotifications() async {
    const AndroidInitializationSettings initializationSettingsAndroid =
        AndroidInitializationSettings('@mipmap/ic_launcher');

    const InitializationSettings initializationSettings =
        InitializationSettings(
      android: initializationSettingsAndroid,
    );

    await _localNotifications.initialize(
      initializationSettings,
      onDidReceiveNotificationResponse: _onLocalNotificationResponse,
    );

    // Crear canales Android
    const AndroidNotificationChannel urgentChannel = AndroidNotificationChannel(
      'doccione_urgent',
      'Urgente',
      description: 'Notificaciones urgentes de Doccione',
      importance: Importance.high,
    );

    const AndroidNotificationChannel ordersChannel = AndroidNotificationChannel(
      'doccione_orders_v2',
      'Pedidos',
      description: 'Cambios importantes de pedidos',
      importance: Importance.high,
    );

    const AndroidNotificationChannel productionChannel =
        AndroidNotificationChannel(
      'doccione_production',
      'Producción',
      description: 'Notificaciones de producción',
      importance: Importance.low,
    );

    await _localNotifications
        .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(urgentChannel);

    await _localNotifications
        .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(ordersChannel);

    await _localNotifications
        .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(productionChannel);
  }

  void _setupMessageHandlers() {
    // Mensajes cuando la app está en foreground
    _foregroundMessageSubscription =
        FirebaseMessaging.onMessage.listen((RemoteMessage message) {
      if (!mounted) return;
      _showLocalNotification(message);
      setState(() {
        _notifications.insert(0, message);
        if (_notifications.length > 50) _notifications.removeLast();
      });
    });

    // Mensajes cuando la app está en background pero abierta
    _openedMessageSubscription =
        FirebaseMessaging.onMessageOpenedApp.listen((RemoteMessage message) {
      if (!mounted) return;
      _navigateToNotificationDetail(message);
    });

    FirebaseMessaging.instance.getInitialMessage().then((message) {
      if (message != null && mounted) {
        _navigateToNotificationDetail(message);
      }
    });
  }

  Future<void> _showLocalNotification(RemoteMessage message) async {
    final priority = message.data['priority']?.toLowerCase();
    final urgent = priority == 'urgent' || priority == 'high';
    final channelId = urgent ? 'doccione_urgent' : 'doccione_orders_v2';
    final channelName = urgent ? 'Urgente' : 'Pedidos';
    final platformChannelSpecifics = NotificationDetails(
      android: AndroidNotificationDetails(
        channelId,
        channelName,
        importance: urgent ? Importance.max : Importance.high,
        priority: urgent ? Priority.max : Priority.high,
      ),
    );

    await _localNotifications.show(
      message.hashCode,
      message.notification?.title ?? 'Doccione',
      message.notification?.body ?? '',
      platformChannelSpecifics,
      payload: jsonEncode({
        'title': message.notification?.title ?? 'Doccione',
        'body': message.notification?.body ?? '',
        'data': message.data,
      }),
    );
  }

  Future<String> _getDeviceName() async {
    final hostname = Platform.localHostname.trim();
    return hostname.isEmpty ? 'Android' : 'Android - $hostname';
  }

  Future<void> _refreshToken() async {
    try {
      final newToken = await FirebaseMessaging.instance.getToken();
      final previousToken = _fcmToken;
      if (!mounted) return;
      setState(() {
        _fcmToken = newToken;
      });
      if (newToken != null &&
          previousToken != null &&
          newToken != previousToken) {
        await _updateTokenOnServer(previousToken, newToken);
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _firebaseStatus = 'Error al refrescar: $e';
      });
    }
  }

  Future<void> _copyToken() async {
    if (_fcmToken != null) {
      await Clipboard.setData(ClipboardData(text: _fcmToken!));
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Token copiado al portapapeles')),
      );
    }
  }

  void _onLocalNotificationResponse(NotificationResponse response) {
    final rawPayload = response.payload;
    if (rawPayload == null || rawPayload.isEmpty || !mounted) return;

    try {
      final payload = jsonDecode(rawPayload) as Map<String, dynamic>;
      final rawData = payload['data'];
      final Map<String, String> data = rawData is Map
          ? Map<String, String>.fromEntries(
              rawData.entries.map((entry) =>
                  MapEntry(entry.key.toString(), entry.value.toString())),
            )
          : <String, String>{};
      _navigateToNotificationDetailData(
        title: payload['title'] as String? ?? 'Doccione',
        body: payload['body'] as String? ?? '',
        data: data,
      );
    } on FormatException {
      // Los payloads antiguos no deben impedir abrir la aplicación.
    }
  }

  void _navigateToNotificationDetail(RemoteMessage message) {
    _navigateToNotificationDetailData(
      title: message.notification?.title ?? 'Sin título',
      body: message.notification?.body ?? '',
      data: Map<String, String>.fromEntries(
        message.data.entries
            .map((entry) => MapEntry(entry.key, entry.value.toString())),
      ),
    );
  }

  void _navigateToNotificationDetailData({
    required String title,
    required String body,
    required Map<String, String> data,
  }) {
    if (!mounted) return;
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) =>
            NotificationDetailPage(title: title, body: body, data: data),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    // If paired, show dashboard; otherwise show pairing screen
    if (_isPaired && _sessionToken != null) {
      return DashboardScreen(
        sessionToken: _sessionToken,
        onLogout: _logout,
        onSessionExpired: _handleSessionExpired,
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('Doccione Mobile'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
        actions: [
          IconButton(
            icon: const Icon(Icons.settings),
            tooltip: 'Configuración del servidor',
            onPressed: () async {
              await Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (context) => ServerConfigScreen(
                    repository: ServerConfigRepository(DatabaseHelper()),
                    onTestConnection: (baseUrl) async {
                      final client = SyncApiClient(baseUrl: baseUrl);
                      try {
                        return await client.testConnection();
                      } finally {
                        client.close();
                      }
                    },
                  ),
                ),
              );
              await _loadServerConfig();
            },
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Acceso y vinculación del vendedor
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(
                        _credentialsAccepted
                            ? Icons.verified_user_outlined
                            : Icons.person_outline,
                        color:
                            _credentialsAccepted ? Colors.green : Colors.orange,
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          _credentialsAccepted
                              ? 'Vincular este dispositivo'
                              : 'Ingreso de vendedor',
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    _credentialsAccepted ? _pairingStatus : _authStatus,
                  ),
                  const SizedBox(height: 16),
                  if (!_credentialsAccepted)
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        TextField(
                          key: const Key('seller-username-field'),
                          controller: _usernameController,
                          decoration: const InputDecoration(
                            labelText: 'Usuario',
                            prefixIcon: Icon(Icons.person_outline),
                            border: OutlineInputBorder(),
                          ),
                          textInputAction: TextInputAction.next,
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          key: const Key('seller-password-field'),
                          controller: _passwordController,
                          decoration: InputDecoration(
                            labelText: 'Contraseña',
                            prefixIcon: const Icon(Icons.lock_outline),
                            border: const OutlineInputBorder(),
                            suffixIcon: IconButton(
                              tooltip: _showPassword
                                  ? 'Ocultar contraseña'
                                  : 'Mostrar contraseña',
                              icon: Icon(
                                _showPassword
                                    ? Icons.visibility_off
                                    : Icons.visibility,
                              ),
                              onPressed: () => setState(
                                () => _showPassword = !_showPassword,
                              ),
                            ),
                          ),
                          obscureText: !_showPassword,
                          enableSuggestions: false,
                          autocorrect: false,
                          textInputAction: TextInputAction.done,
                          onSubmitted: (_) => _authenticateSeller(),
                        ),
                        const SizedBox(height: 12),
                        if (_configError != null)
                          Padding(
                            padding: const EdgeInsets.only(bottom: 8),
                            child: Row(
                              children: [
                                const Icon(Icons.warning_amber,
                                    color: Colors.orange, size: 16),
                                const SizedBox(width: 6),
                                Expanded(
                                  child: Text(
                                    _configError!,
                                    style: const TextStyle(
                                        color: Colors.orange, fontSize: 12),
                                  ),
                                ),
                                TextButton(
                                  onPressed: () async {
                                    await Navigator.push(
                                      context,
                                      MaterialPageRoute(
                                        builder: (context) =>
                                            ServerConfigScreen(
                                          repository: ServerConfigRepository(
                                              DatabaseHelper()),
                                          onTestConnection: (baseUrl) async {
                                            final client =
                                                SyncApiClient(baseUrl: baseUrl);
                                            try {
                                              return await client
                                                  .testConnection();
                                            } finally {
                                              client.close();
                                            }
                                          },
                                        ),
                                      ),
                                    );
                                    await _loadServerConfig();
                                  },
                                  child: const Text('Abrir Configuración'),
                                ),
                              ],
                            ),
                          ),
                        ElevatedButton.icon(
                          key: const Key('seller-login-button'),
                          onPressed: _configLoaded && !_isAuthenticating
                              ? _authenticateSeller
                              : null,
                          icon: _isAuthenticating
                              ? const SizedBox.square(
                                  dimension: 18,
                                  child:
                                      CircularProgressIndicator(strokeWidth: 2),
                                )
                              : const Icon(Icons.login),
                          label: Text(
                            _configLoaded
                                ? 'Ingresar'
                                : 'Configurar servidor primero',
                          ),
                        ),
                      ],
                    )
                  else
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: Colors.green.withValues(alpha: 0.12),
                            borderRadius: BorderRadius.circular(10),
                          ),
                          child: Row(
                            children: [
                              const Icon(
                                Icons.check_circle_outline,
                                color: Colors.green,
                              ),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  'Sesión verificada: $_sellerName',
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(height: 14),
                        TextField(
                          key: const Key('seller-pairing-code-field'),
                          controller: _pairingCodeController,
                          decoration: const InputDecoration(
                            labelText: 'Código de 6 dígitos de Studio',
                            hintText: '123456',
                            prefixIcon: Icon(Icons.pin_outlined),
                            border: OutlineInputBorder(),
                          ),
                          keyboardType: TextInputType.number,
                          maxLength: 6,
                          inputFormatters: [
                            FilteringTextInputFormatter.digitsOnly,
                          ],
                          onSubmitted: (_) => _pairDevice(),
                        ),
                        ElevatedButton.icon(
                          key: const Key('seller-pair-button'),
                          onPressed:
                              _configLoaded && !_isPairing ? _pairDevice : null,
                          icon: _isPairing
                              ? const SizedBox.square(
                                  dimension: 18,
                                  child:
                                      CircularProgressIndicator(strokeWidth: 2),
                                )
                              : const Icon(Icons.link),
                          label: const Text('Vincular y entrar'),
                        ),
                        TextButton(
                          onPressed: _isPairing
                              ? null
                              : () {
                                  setState(() {
                                    _credentialsAccepted = false;
                                    _linkToken = null;
                                    _sellerName = '';
                                    _pairingCodeController.clear();
                                    _authStatus =
                                        'Ingresá con la cuenta creada en Doccione Studio.';
                                  });
                                },
                          child: const Text('Usar otra cuenta'),
                        ),
                      ],
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Estado de Firebase',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Icon(
                        _firebaseStatus.contains('Conectado')
                            ? Icons.check_circle
                            : Icons.error,
                        color: _firebaseStatus.contains('Conectado')
                            ? Colors.green
                            : Colors.red,
                      ),
                      const SizedBox(width: 8),
                      Text(_firebaseStatus),
                    ],
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Dispositivo',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 8),
                  Text('Nombre: $_deviceName'),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Token FCM',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 8),
                  if (_fcmToken != null)
                    SelectableText(
                      _fcmToken!,
                      style: const TextStyle(
                          fontFamily: 'monospace', fontSize: 10),
                    )
                  else
                    const Text('Cargando...'),
                  const SizedBox(height: 16),
                  Row(
                    children: [
                      ElevatedButton.icon(
                        onPressed: _copyToken,
                        icon: const Icon(Icons.copy),
                        label: const Text('Copiar'),
                      ),
                      const SizedBox(width: 8),
                      ElevatedButton.icon(
                        onPressed: _refreshToken,
                        icon: const Icon(Icons.refresh),
                        label: const Text('Actualizar'),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Notificaciones recibidas',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 8),
                  if (_notifications.isEmpty)
                    const Text('No hay notificaciones')
                  else
                    ..._notifications.map((message) => ListTile(
                          title:
                              Text(message.notification?.title ?? 'Sin título'),
                          subtitle: Text(message.notification?.body ?? ''),
                          trailing: const Icon(Icons.notifications),
                          onTap: () => _navigateToNotificationDetail(message),
                        )),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class NotificationDetailPage extends StatelessWidget {
  final String title;
  final String body;
  final Map<String, String> data;

  const NotificationDetailPage({
    super.key,
    required this.title,
    required this.body,
    required this.data,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Detalle de notificación'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _buildDetailRow('Título', title),
          _buildDetailRow('Mensaje', body),
          const Divider(),
          _buildDetailRow('Event Type', data['event_type'] ?? 'N/A'),
          _buildDetailRow('Entity Type', data['entity_type'] ?? 'N/A'),
          _buildDetailRow('Entity ID', data['entity_id'] ?? 'N/A'),
          _buildDetailRow('Event UUID', data['event_uuid'] ?? 'N/A'),
          _buildDetailRow('Priority', data['priority'] ?? 'N/A'),
          _buildDetailRow('Route', data['route'] ?? 'N/A'),
          const Divider(),
          Text(
            'Datos completos:',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          SelectableText(
            data.toString(),
            style: const TextStyle(fontFamily: 'monospace', fontSize: 10),
          ),
        ],
      ),
    );
  }

  Widget _buildDetailRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 100,
            child: Text(
              '$label:',
              style: const TextStyle(fontWeight: FontWeight.bold),
            ),
          ),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }
}
