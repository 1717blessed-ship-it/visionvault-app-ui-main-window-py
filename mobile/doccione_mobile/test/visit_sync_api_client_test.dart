import 'dart:convert';

import 'package:doccione_mobile/models/visit_pin.dart';
import 'package:doccione_mobile/services/visit_sync_api_client.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  VisitPin pin({int version = 0}) => VisitPin(
        title: 'Comercio Centro',
        latitude: -27.48,
        longitude: -55.11,
        createdAt: DateTime(2026, 8, 12),
        updatedAt: DateTime(2026, 8, 12),
        clientUuid: 'visit-api-1',
        serverVersion: version,
      );

  test('envía la versión base y convierte HTTP 409 en conflicto', () async {
    late Map<String, dynamic> sent;
    final remote = pin(version: 4).copyWith(title: 'Versión remota');
    final client = MockClient((request) async {
      sent = jsonDecode(request.body) as Map<String, dynamic>;
      return http.Response(
        jsonEncode({'error': 'visit_conflict', 'visit': remote.toMap()}),
        409,
        headers: {'content-type': 'application/json'},
      );
    });
    final api = VisitSyncApiClient(
        baseUrl: 'https://example.test', sessionToken: 'token', client: client);

    await expectLater(
        api.upsert(pin(version: 3)), throwsA(isA<VisitSyncConflict>()));
    expect(sent['server_version'], 3);
    expect(sent['client_uuid'], 'visit-api-1');
    api.close();
  });

  test('descarga visitas remotas con su versión del servidor', () async {
    final client = MockClient((request) async => http.Response(
          jsonEncode({
            'visits': [pin(version: 7).toMap()]
          }),
          200,
          headers: {'content-type': 'application/json'},
        ));
    final api = VisitSyncApiClient(
        baseUrl: 'https://example.test', sessionToken: 'token', client: client);

    final visits = await api.pull();

    expect(visits.single.serverVersion, 7);
    expect(visits.single.clientUuid, 'visit-api-1');
    api.close();
  });
}
