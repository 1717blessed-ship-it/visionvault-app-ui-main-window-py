import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:http/http.dart' as http;
import 'dashboard_screen.dart';
import 'server_config_screen.dart';
import '../database/database_helper.dart';
import '../database/server_config_repository.dart';

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
  final FlutterLocalNotificationsPlugin _localNotifications = FlutterLocalNotificationsPlugin();
  final List<RemoteMessage> _notifications = [];
  final TextEditingController _pairingCodeController = TextEditingController();
  final FlutterSecureStorage _secureStorage = const FlutterSecureStorage();
  String? _sessionToken;

  @override
  void initState() {
    super.initState();
    _loadSessionToken();
    _initializeFirebase();
    _initializeLocalNotifications();
    _setupMessageHandlers();
  }

  @override
  void dispose() {
    _pairingCodeController.dispose();
    super.dispose();
  }

  Future<void> _loadSessionToken() async {
    final token = await _secureStorage.read(key: 'session_token');
    if (token != null) {
      setState(() {
        _sessionToken = token;
        _isPaired = true;
        _pairingStatus = 'Vinculado';
      });
    }
  }

  Future<void> _saveSessionToken(String token) async {
    await _secureStorage.write(key: 'session_token', value: token);
    setState(() {
      _sessionToken = token;
    });
  }

  Future<void> _clearSessionToken() async {
    await _secureStorage.delete(key: 'session_token');
    setState(() {
      _sessionToken = null;
    });
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

      if (settings.authorizationStatus == AuthorizationStatus.authorized) {
        _fcmToken = await messaging.getToken();
        setState(() {
          _firebaseStatus = 'Conectado - Permisos otorgados';
        });
      } else if (settings.authorizationStatus == AuthorizationStatus.provisional) {
        _fcmToken = await messaging.getToken();
        setState(() {
          _firebaseStatus = 'Conectado - Permisos provisionales';
        });
      } else {
        setState(() {
          _firebaseStatus = 'Permisos denegados';
        });
      }

      // Escuchar renovación de token
      FirebaseMessaging.instance.onTokenRefresh.listen((newToken) {
        setState(() {
          _fcmToken = newToken;
        });
        // Enviar actualización de token al servidor
        _updateTokenOnServer(_fcmToken ?? '', newToken);
      });
    } catch (e) {
      setState(() {
        _firebaseStatus = 'Error: $e';
      });
    }
  }

  Future<void> _updateTokenOnServer(String oldToken, String newToken) async {
    try {
      final response = await http.post(
        Uri.parse('http://localhost:8765/api/device/update-token'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'old_token': oldToken,
          'new_token': newToken,
        }),
      );
      if (response.statusCode == 200) {
        print('Token actualizado en servidor');
      }
    } catch (e) {
      print('Error actualizando token: $e');
    }
  }

  Future<void> _pairDevice() async {
    final code = _pairingCodeController.text.trim();
    if (code.length != 6) {
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
      _pairingStatus = 'Vinculando...';
    });

    try {
      final response = await http.post(
        Uri.parse('http://localhost:8765/api/pair/validate'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'code': code,
          'push_token': _fcmToken,
          'platform': 'android',
          'device_name': _deviceName,
          'app_version': '1.0.0',
        }),
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        if (data['success'] == true) {
          // Guardar session token en almacenamiento seguro
          final sessionToken = data['session_token'];
          if (sessionToken != null) {
            await _saveSessionToken(sessionToken);
          }
          setState(() {
            _isPaired = true;
            _pairingStatus = 'Vinculado exitosamente';
            _pairingCodeController.clear();
          });
        } else {
          setState(() {
            _pairingStatus = 'Error: ${data['error']}';
          });
        }
      } else {
        setState(() {
          _pairingStatus = 'Error del servidor: ${response.statusCode}';
        });
      }
    } catch (e) {
      setState(() {
        _pairingStatus = 'Error de conexión: $e';
      });
    }
  }

  Future<void> _initializeLocalNotifications() async {
    const AndroidInitializationSettings initializationSettingsAndroid =
        AndroidInitializationSettings('@mipmap/ic_launcher');

    const InitializationSettings initializationSettings = InitializationSettings(
      android: initializationSettingsAndroid,
    );

    await _localNotifications.initialize(initializationSettings);

    // Crear canales Android
    const AndroidNotificationChannel urgentChannel = AndroidNotificationChannel(
      'doccione_urgent',
      'Urgente',
      description: 'Notificaciones urgentes de Doccione',
      importance: Importance.high,
    );

    const AndroidNotificationChannel ordersChannel = AndroidNotificationChannel(
      'doccione_orders',
      'Pedidos',
      description: 'Notificaciones de pedidos',
      importance: Importance.low,
    );

    const AndroidNotificationChannel productionChannel = AndroidNotificationChannel(
      'doccione_production',
      'Producción',
      description: 'Notificaciones de producción',
      importance: Importance.low,
    );

    await _localNotifications
        .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(urgentChannel);

    await _localNotifications
        .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(ordersChannel);

    await _localNotifications
        .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(productionChannel);
  }

  void _setupMessageHandlers() {
    // Mensajes cuando la app está en foreground
    FirebaseMessaging.onMessage.listen((RemoteMessage message) {
      _showLocalNotification(message);
      setState(() {
        _notifications.insert(0, message);
        if (_notifications.length > 50) _notifications.removeLast();
      });
    });

    // Mensajes cuando la app está en background pero abierta
    FirebaseMessaging.onMessageOpenedApp.listen((RemoteMessage message) {
      _navigateToNotificationDetail(message);
    });
  }

  Future<void> _showLocalNotification(RemoteMessage message) async {
    const AndroidNotificationDetails androidPlatformChannelSpecifics =
        AndroidNotificationDetails(
      'doccione_orders',
      'Pedidos',
      importance: Importance.max,
      priority: Priority.high,
    );

    const NotificationDetails platformChannelSpecifics =
        NotificationDetails(android: androidPlatformChannelSpecifics);

    await _localNotifications.show(
      message.hashCode,
      message.notification?.title ?? 'Doccione',
      message.notification?.body ?? '',
      platformChannelSpecifics,
      payload: message.data.toString(),
    );
  }

  Future<String> _getDeviceName() async {
    // Simplificado - en producción usaría device_info_plus
    return 'Android Device';
  }

  Future<void> _refreshToken() async {
    try {
      final newToken = await FirebaseMessaging.instance.getToken();
      setState(() {
        _fcmToken = newToken;
      });
    } catch (e) {
      setState(() {
        _firebaseStatus = 'Error al refrescar: $e';
      });
    }
  }

  void _copyToken() {
    if (_fcmToken != null) {
      // En una app real usaría flutter/services para copiar al clipboard
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Token copiado al portapapeles')),
      );
    }
  }

  void _navigateToNotificationDetail(RemoteMessage message) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => NotificationDetailPage(message: message),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    // If paired, show dashboard; otherwise show pairing screen
    if (_isPaired && _sessionToken != null) {
      return DashboardScreen(sessionToken: _sessionToken);
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('Doccione Mobile'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
        actions: [
          IconButton(
            icon: const Icon(Icons.settings),
            tooltip: 'Configuración del servidor',
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (context) => ServerConfigScreen(
                    repository: ServerConfigRepository(DatabaseHelper()),
                  ),
                ),
              );
            },
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Vinculación de dispositivo
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(
                        _isPaired ? Icons.link : Icons.link_off,
                        color: _isPaired ? Colors.green : Colors.orange,
                      ),
                      const SizedBox(width: 8),
                      Text(
                        'Vinculación con Doccione Studio',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(_pairingStatus),
                  const SizedBox(height: 16),
                  if (!_isPaired)
                    Column(
                      children: [
                        TextField(
                          controller: _pairingCodeController,
                          decoration: const InputDecoration(
                            labelText: 'Código de 6 dígitos',
                            hintText: '123456',
                            border: OutlineInputBorder(),
                          ),
                          keyboardType: TextInputType.number,
                          maxLength: 6,
                        ),
                        const SizedBox(height: 8),
                        ElevatedButton.icon(
                          onPressed: _pairDevice,
                          icon: const Icon(Icons.link),
                          label: const Text('Vincular'),
                        ),
                      ],
                    )
                  else
                    ElevatedButton.icon(
                      onPressed: () async {
                        await _clearSessionToken();
                        setState(() {
                          _isPaired = false;
                          _pairingStatus = 'No vinculado';
                        });
                      },
                      icon: const Icon(Icons.link_off),
                      label: const Text('Desvincular'),
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
                      style: const TextStyle(fontFamily: 'monospace', fontSize: 10),
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
                          title: Text(message.notification?.title ?? 'Sin título'),
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
  final RemoteMessage message;

  const NotificationDetailPage({super.key, required this.message});

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
          _buildDetailRow('Título', message.notification?.title ?? 'N/A'),
          _buildDetailRow('Mensaje', message.notification?.body ?? 'N/A'),
          const Divider(),
          _buildDetailRow('Event Type', message.data['event_type'] ?? 'N/A'),
          _buildDetailRow('Entity Type', message.data['entity_type'] ?? 'N/A'),
          _buildDetailRow('Entity ID', message.data['entity_id'] ?? 'N/A'),
          _buildDetailRow('Event UUID', message.data['event_uuid'] ?? 'N/A'),
          _buildDetailRow('Priority', message.data['priority'] ?? 'N/A'),
          _buildDetailRow('Route', message.data['route'] ?? 'N/A'),
          const Divider(),
          Text(
            'Datos completos:',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          SelectableText(
            message.data.toString(),
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
