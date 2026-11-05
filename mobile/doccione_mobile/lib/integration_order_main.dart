// Explicit debug entry point. Never imported by main.dart, never build an APK here.
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';
import 'database/database_helper.dart';
import 'database/order_drafts_repository.dart';
import 'screens/unified_order_creation_screen.dart';
import 'services/order_integration_client.dart';
import 'services/order_integration_sync.dart';

void main() {
  if (kReleaseMode ||
      !const bool.fromEnvironment('DOCCIONE_ORDER_INTEGRATION')) {
    throw StateError('Entrada bloqueada. Solo integración debug explícita.');
  }
  runApp(const MaterialApp(home: OrderIntegrationSetup()));
}

/// Loopback only; pairing tokens live in OS secure storage, never queue/defines.
class OrderIntegrationSetup extends StatefulWidget {
  const OrderIntegrationSetup({super.key});
  @override
  State<OrderIntegrationSetup> createState() => _OrderIntegrationSetupState();
}

class _OrderIntegrationSetupState extends State<OrderIntegrationSetup> {
  static const storage = FlutterSecureStorage();
  static const storageKey = 'isolated_order_sync_v1';
  static const lanPilot =
      bool.fromEnvironment('DOCCIONE_ORDER_INTEGRATION_LAN');
  static const usbPilot =
      bool.fromEnvironment('DOCCIONE_ORDER_INTEGRATION_USB');
  static const lanHost =
      String.fromEnvironment('DOCCIONE_ORDER_INTEGRATION_HOST');
  final endpoint = TextEditingController(
      text: usbPilot && !lanPilot
          ? 'https://127.0.0.1:8875'
          : lanPilot && lanHost.isNotEmpty
              ? 'https://$lanHost:8875'
              : 'http://127.0.0.1:');
  final code = TextEditingController();
  bool busy = false;
  String status =
      'Solo servidor temporal local. Sin sincronización automática.';
  @override
  void dispose() {
    endpoint.dispose();
    code.dispose();
    super.dispose();
  }

  Future<void> connect({bool restore = false}) async {
    if (busy) return;
    setState(() => busy = true);
    OrderIntegrationClient? client;
    http.Client? transport;
    Database? db;
    OrderIntegrationSync? sync;
    try {
      final endpointValue = endpoint.text.trim();
      if (Uri.tryParse(endpointValue)?.scheme == 'https') {
        transport = await createPinnedIntegrationClient();
      }
      final Map<String, dynamic> session;
      if (restore) {
        final raw = await storage.read(key: storageKey);
        if (raw == null) throw StateError('No hay sesión aislada guardada.');
        session = objectMap(jsonDecode(raw));
      } else {
        session = await OrderIntegrationClient.pair(
            endpointValue, code.text.trim(),
            client: transport);
        session['endpoint'] = endpointValue;
      }
      final target = IntegrationTarget(
          baseUrl: restore && endpoint.text.trim() != 'http://127.0.0.1:'
              ? endpoint.text.trim()
              : session['endpoint'] as String,
          serverId: session['integration_server_id'] as String,
          deviceId: '${session['device_id']}');
      client = OrderIntegrationClient(
          target: target,
          token: session['session_token'] as String,
          client: transport);
      transport = null; // ownership transferred to OrderIntegrationClient
      await client
          .capabilities(); // verify realm/device before opening its queue
      if (!RegExp(r'^[a-f0-9]{32}$').hasMatch(target.serverId) ||
          !RegExp(r'^[1-9][0-9]*$').hasMatch(target.deviceId)) {
        throw StateError('Identidad no admitida.');
      }
      session['endpoint'] = target.origin.origin;
      await storage.write(key: storageKey, value: jsonEncode(session));
      code.clear();
      final documents = await getApplicationDocumentsDirectory();
      db = await openDatabase(
          '${documents.path}/doccione-mobile-order-integration-${target.serverId}-${target.deviceId}.db');
      final owner = 'integration:${target.serverId}:${target.deviceId}';
      final store = OrderIntegrationStore(db, owner: owner);
      await store.initialize();
      sync = OrderIntegrationSync(store, client);
      final database = db;
      final repo = OrderDraftsRepository(DatabaseHelper(),
          ownerProvider: () async => owner,
          databaseProvider: () async => database);
      if (!mounted) return;
      await Navigator.of(context).push(MaterialPageRoute<void>(
          builder: (_) => UnifiedOrderCreationScreen(
              baseUrl: target.origin.origin,
              sessionToken: session['session_token'] as String,
              repository: repo,
              integrationSync: sync)));
    } on OrderSyncFailure catch (e) {
      if (mounted) setState(() => status = 'Conexión rechazada: ${e.code}');
    } catch (_) {
      if (mounted) {
        setState(() => status =
            'No se abrió la integración. Revisá el servidor, código y almacenamiento seguro.');
      }
    } finally {
      await sync?.idle;
      sync?.dispose();
      client?.close();
      transport?.close();
      await db?.close();
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
      appBar: AppBar(title: const Text('INTEGRACIÓN AISLADA · NO PRODUCCIÓN')),
      body: ListView(padding: const EdgeInsets.all(20), children: [
        Text(status),
        TextField(
            controller: endpoint,
            enabled: !busy,
            decoration: const InputDecoration(
                labelText: 'Servidor aislado temporal (HTTPS en piloto LAN)')),
        TextField(
            controller: code,
            enabled: !busy,
            obscureText: true,
            decoration: const InputDecoration(
                labelText: 'Código de enlace de un solo uso')),
        FilledButton(
            onPressed: busy ? null : () => connect(),
            child: const Text('Enlazar entorno aislado')),
        OutlinedButton(
            onPressed: busy ? null : () => connect(restore: true),
            child: const Text('Recuperar sesión y cola aisladas')),
        const Text(
            'Cambiar de servidor o volver a enlazar no transfiere pedidos. Las operaciones pendientes permanecen en su entorno original.'),
      ]));
}
