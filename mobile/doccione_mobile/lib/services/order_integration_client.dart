import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';
import 'package:crypto/crypto.dart';
import '../models/order_draft.dart';

/// Not wired into production. Only explicit, non-release loopback integration.
class IntegrationTarget {
  final Uri origin;
  final String serverId, deviceId;
  IntegrationTarget(
      {required String baseUrl, required this.serverId, required this.deviceId})
      : origin = Uri.parse(baseUrl) {
    const lanPilot = bool.fromEnvironment('DOCCIONE_ORDER_INTEGRATION_LAN');
    const usbPilot = bool.fromEnvironment('DOCCIONE_ORDER_INTEGRATION_USB');
    const lanHost = String.fromEnvironment('DOCCIONE_ORDER_INTEGRATION_HOST');
    final loopback = !lanPilot &&
        !usbPilot &&
        origin.scheme == 'http' &&
        origin.host == '127.0.0.1';
    final pinnedUsb = usbPilot &&
        !lanPilot &&
        origin.scheme == 'https' &&
        origin.host == '127.0.0.1' &&
        origin.port == 8875;
    final pinnedLan = lanPilot &&
        lanHost.isNotEmpty &&
        origin.scheme == 'https' &&
        origin.host == lanHost;
    if (kReleaseMode ||
        (usbPilot && lanPilot) ||
        (!loopback && !pinnedLan && !pinnedUsb) ||
        !origin.hasPort ||
        origin.port < 1 ||
        origin.userInfo.isNotEmpty ||
        !['', '/'].contains(origin.path) ||
        origin.hasQuery ||
        origin.hasFragment ||
        serverId.isEmpty ||
        deviceId.isEmpty) {
      throw ArgumentError(
          'Solo integración loopback explícita, nunca producción.');
    }
  }
  // Endpoint may change explicitly after a restart; the durable realm must not.
  String get key => jsonEncode(['integration-v1', serverId, deviceId]);
}

/// Trust only the public pilot CA; Dart still verifies expiry, chain and SAN.
/// This has deliberately no badCertificateCallback or trust-all escape hatch.
Future<http.Client> createPinnedIntegrationClient() async {
  const lanPilot = bool.fromEnvironment('DOCCIONE_ORDER_INTEGRATION_LAN');
  const usbPilot = bool.fromEnvironment('DOCCIONE_ORDER_INTEGRATION_USB');
  if (kReleaseMode || lanPilot == usbPilot) {
    throw StateError(
        'Transporte TLS disponible solo en un piloto debug explícito.');
  }
  final pem = await rootBundle.load(usbPilot
      ? 'assets/integration_usb_pilot_ca.pem'
      : 'assets/integration_pilot_ca.pem');
  final context = SecurityContext(withTrustedRoots: false)
    ..setTrustedCertificatesBytes(
        pem.buffer.asUint8List(pem.offsetInBytes, pem.lengthInBytes));
  final io = HttpClient(context: context)
    ..connectionTimeout = const Duration(seconds: 8);
  return IOClient(io);
}

class OrderSyncFailure implements Exception {
  final String code;
  final int? status;
  const OrderSyncFailure(this.code, [this.status]);
  bool get recoverable =>
      status == null && code == 'connection_unavailable' ||
      status == 408 ||
      status == 429 ||
      status == 500 ||
      status == 502 ||
      status == 504;
  bool get conflict => code == 'revision_conflict';
  @override
  String toString() => code; // Never include credentials, body or paths.
}

Map<String, dynamic> objectMap(dynamic value) =>
    Map<String, dynamic>.from(value as Map);
dynamic _sorted(dynamic value) {
  if (value is Map) {
    final keys = value.keys.cast<String>().toList()..sort();
    return {for (final k in keys) k: _sorted(value[k])};
  }
  return value is List ? value.map(_sorted).toList() : value;
}

String operationDigest(Map<String, dynamic> payload) => sha256
    .convert(utf8.encode(jsonEncode(_sorted({
      'type': 'order_snapshot_v1',
      'order_id': payload['desktop_order_id'] == null
          ? null
          : int.parse(payload['desktop_order_id'] as String),
      'expected_revision': payload['expected_revision'],
      'payload': payload
    }))))
    .toString();

/// Dedicated V1 client; never calls legacy catalog/order write routes.
class OrderIntegrationClient {
  static const prefix = '/api/v1/mobile/order-sync/';
  final IntegrationTarget target;
  final String _token;
  final http.Client _http;
  final Duration timeout;
  OrderIntegrationClient(
      {required this.target,
      required String token,
      http.Client? client,
      this.timeout = const Duration(seconds: 8)})
      : _token = token,
        _http = client ?? http.Client();

  Future<Map<String, dynamic>> _request(String route,
      {Map<String, dynamic>? body}) async {
    try {
      final req = http.Request(body == null ? 'GET' : 'POST',
          target.origin.resolve('$prefix$route'));
      req.followRedirects = false; // A redirect must never forward the bearer.
      req.headers.addAll({
        'Authorization': 'Bearer $_token',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      });
      if (body != null) {
        req.body = jsonEncode(body);
        if (utf8.encode(req.body).length > 65536) {
          throw const OrderSyncFailure('payload_too_large', 413);
        }
      }
      final response = await (() async {
        final stream = await _http.send(req);
        final bytes = <int>[];
        await for (final part in stream.stream) {
          bytes.addAll(part);
          if (bytes.length > 2 * 1024 * 1024) {
            throw const OrderSyncFailure('invalid_response');
          }
        }
        return http.Response.bytes(bytes, stream.statusCode);
      })()
          .timeout(timeout);
      if (response.statusCode >= 300 && response.statusCode < 400) {
        throw const OrderSyncFailure('redirect_rejected');
      }
      Map<String, dynamic> data;
      try {
        data = objectMap(jsonDecode(utf8.decode(response.bodyBytes)));
      } catch (_) {
        throw const OrderSyncFailure('invalid_response');
      }
      if (data['contract_version'] is! int || data['contract_version'] != 1) {
        throw const OrderSyncFailure('version_unsupported');
      }
      // Operational namespace errors have no integration identity: never accept them.
      if (data['integration_server_id'] != target.serverId) {
        throw const OrderSyncFailure('server_identity_mismatch');
      }
      if (response.statusCode >= 400) {
        final code =
            data['error'] is Map ? (data['error'] as Map)['code'] : null;
        throw OrderSyncFailure(
            code is String && RegExp(r'^[a-z_]+$').hasMatch(code)
                ? code
                : 'request_rejected',
            response.statusCode);
      }
      return data;
    } on OrderSyncFailure {
      rethrow;
    } on TimeoutException {
      throw const OrderSyncFailure('connection_unavailable');
    } catch (_) {
      throw const OrderSyncFailure('connection_unavailable');
    }
  }

  Future<Map<String, dynamic>> capabilities() async {
    final data = await _request('capabilities');
    if (data['integration_only'] != true ||
        '${data['device_id']}' != target.deviceId) {
      throw const OrderSyncFailure('scope_mismatch');
    }
    return data;
  }

  Future<Map<String, dynamic>> catalog() => _request('catalog');
  Future<Map<String, dynamic>> orders() => _request('orders');
  Future<Map<String, dynamic>> order(String id) =>
      _request('orders/${Uri.encodeComponent(id)}');
  Future<Map<String, dynamic>> validate(Map<String, dynamic> body) =>
      _request('validate', body: body);
  Future<Map<String, dynamic>> send(Map<String, dynamic> body) =>
      _request('operations', body: body);
  Future<Map<String, dynamic>?> result(String operationId) async {
    try {
      return await _request('operations/${Uri.encodeComponent(operationId)}');
    } on OrderSyncFailure catch (e) {
      if (e.status == 404 && e.code == 'not_found') return null;
      rethrow;
    }
  }

  /// Initial pairing is explicit, no code/token stored in queue or source.
  static Future<Map<String, dynamic>> pair(String baseUrl, String code,
      {http.Client? client}) async {
    // Check transport before sending even the pairing code.
    final target = IntegrationTarget(
        baseUrl: baseUrl, serverId: 'unpaired', deviceId: 'unpaired');
    final transport = client ?? http.Client();
    try {
      final req = http.Request('POST', target.origin.resolve('${prefix}pair'))
        ..followRedirects = false;
      req.headers['Content-Type'] = 'application/json';
      req.body = jsonEncode({'code': code});
      final response = await http.Response.fromStream(await transport.send(req))
          .timeout(const Duration(seconds: 8));
      final data = objectMap(jsonDecode(response.body));
      if (response.statusCode != 201 ||
          data['contract_version'] != 1 ||
          data['integration_server_id'] is! String ||
          data['session_token'] is! String ||
          data['device_id'] is! int) {
        throw const OrderSyncFailure('pairing_rejected');
      }
      return data;
    } finally {
      if (client == null) transport.close();
    }
  }

  void close() => _http.close();
}

/// Converts only an editable mapped snapshot. Unknown Desktop identities fail closed.
OrderDraft draftFromSnapshot(Map<String, dynamic> snapshot,
    {required OrderDraft local}) {
  if (snapshot['client_order_id'] != local.id) {
    throw const OrderSyncFailure('client_identity_mismatch');
  }
  final jobs = <OrderWork>[];
  final ids = <String>{};
  for (final raw in snapshot['jobs'] as List) {
    final j = objectMap(raw);
    final id = j['client_job_id'];
    if (id is! String || !ids.add(id)) {
      throw const OrderSyncFailure('desktop_mapping_required');
    }
    final old = local.jobs.where((v) => v.id == id).firstOrNull;
    final designs = <DesignAllocation>[];
    for (final value in j['designs'] as List) {
      final d = objectMap(value);
      final design = d['catalog_design_id'];
      if (design is! String ||
          d['association_id'] != jsonEncode([id, design])) {
        throw const OrderSyncFailure('desktop_mapping_required');
      }
      designs.add(DesignAllocation(
          designId: design, name: design, quantity: d['quantity'] as int));
    }
    if (!['item', 'sheet'].contains(j['unit_kind'])) {
      throw const OrderSyncFailure('invalid_response');
    }
    final job = OrderWork(
        id: id,
        productCode: j['product_code'] as String,
        productName: old?.productName ?? j['product_code'] as String,
        variantCode: j['variant_code'] as String? ?? '',
        variantName: old?.variantName ?? '',
        material: j['material'] as String? ?? '',
        size: j['size'] as String? ?? '',
        quantity: j['quantity'] as int,
        unitKind: j['unit_kind'] == 'sheet' ? 'sheets' : 'units',
        notes: j['notes'] as String? ?? '',
        designs: designs);
    job.validate();
    jobs.add(job);
  }
  return OrderDraft(
      id: local.id,
      revision: local.revision,
      client: snapshot['client'] as String,
      whatsapp: snapshot['whatsapp'] as String? ?? '',
      notes: snapshot['observations'] as String? ?? '',
      jobs: jobs);
}
