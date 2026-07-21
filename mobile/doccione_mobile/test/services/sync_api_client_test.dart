import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:doccione_mobile/services/sync_api_client.dart';

void main() {
  const baseUrl = 'http://localhost:8000';
  const authToken = 'test-token-123';

  group('SyncApiClient', () {
    group('getCapabilities', () {
      test('should return capabilities on successful response', () async {
        final mockClient = MockClient((request) async {
          expect(request.url.toString(), '$baseUrl/api/v1/mobile/capabilities');
          expect(request.headers['Authorization'], 'Bearer $authToken');
          expect(request.headers['Content-Type'], 'application/json');

          return http.Response(
            jsonEncode({
              'version': '1.0',
              'features': ['sync', 'push_notifications'],
              'max_page_size': 1000,
            }),
            200,
          );
        });

        final client = SyncApiClient(
          baseUrl: baseUrl,
          authToken: authToken,
          httpClient: mockClient,
        );

        final capabilities = await client.getCapabilities();

        expect(capabilities['version'], '1.0');
        expect(capabilities['features'], ['sync', 'push_notifications']);
        expect(capabilities['max_page_size'], 1000);

        client.close();
      });

      test('should throw SyncApiException on HTTP error', () async {
        final mockClient = MockClient((request) async {
          return http.Response('Internal Server Error', 500);
        });

        final client = SyncApiClient(
          baseUrl: baseUrl,
          authToken: authToken,
          httpClient: mockClient,
        );

        expect(
          () => client.getCapabilities(),
          throwsA(isA<SyncApiException>()
              .having((e) => e.statusCode, 'statusCode', 500)),
        );

        client.close();
      });

      test('should throw SyncApiException on timeout', () async {
        final mockClient = MockClient((request) async {
          await Future.delayed(const Duration(seconds: 2));
          return http.Response('{}', 200);
        });

        final client = SyncApiClient(
          baseUrl: baseUrl,
          authToken: authToken,
          timeout: const Duration(milliseconds: 100),
          httpClient: mockClient,
        );

        expect(
          () => client.getCapabilities(),
          throwsA(isA<SyncApiException>()),
        );

        client.close();
      });
    });

    group('syncPull', () {
      test('should return sync data without cursor', () async {
        final mockClient = MockClient((request) async {
          expect(request.url.path, '/api/v1/mobile/sync/pull');
          expect(request.url.queryParameters['limit'], '100');
          expect(request.url.queryParameters.containsKey('cursor'), false);
          expect(request.headers['Authorization'], 'Bearer $authToken');

          return http.Response(
            jsonEncode({
              'snapshot_id': 'snap-123',
              'next_cursor': 'cursor-abc',
              'complete': false,
              'data': {
                'jobs': [
                  {'id': 'job-1', 'title': 'Job 1', 'updated_at': '2026-01-01T00:00:00Z'}
                ],
                'orders': [
                  {'id': 'order-1', 'job_id': 'job-1', 'updated_at': '2026-01-01T00:00:00Z'}
                ],
                'clients': [
                  {'id': 'client-1', 'name': 'Client 1', 'updated_at': '2026-01-01T00:00:00Z'}
                ],
              },
            }),
            200,
          );
        });

        final client = SyncApiClient(
          baseUrl: baseUrl,
          authToken: authToken,
          httpClient: mockClient,
        );

        final result = await client.syncPull(limit: 100);

        expect(result['snapshot_id'], 'snap-123');
        expect(result['next_cursor'], 'cursor-abc');
        expect(result['complete'], false);
        expect(result['data']['jobs'], hasLength(1));
        expect(result['data']['orders'], hasLength(1));
        expect(result['data']['clients'], hasLength(1));

        client.close();
      });

      test('should include cursor in request when provided', () async {
        final mockClient = MockClient((request) async {
          expect(request.url.queryParameters['cursor'], 'cursor-abc');
          expect(request.url.queryParameters['limit'], '50');

          return http.Response(
            jsonEncode({
              'snapshot_id': 'snap-123',
              'next_cursor': null,
              'complete': true,
              'data': {
                'jobs': [],
                'orders': [],
                'clients': [],
              },
            }),
            200,
          );
        });

        final client = SyncApiClient(
          baseUrl: baseUrl,
          authToken: authToken,
          httpClient: mockClient,
        );

        final result = await client.syncPull(cursor: 'cursor-abc', limit: 50);

        expect(result['complete'], true);
        expect(result['next_cursor'], null);

        client.close();
      });

      test('should throw SyncApiException on 400 error', () async {
        final mockClient = MockClient((request) async {
          return http.Response(
            jsonEncode({'error': 'Invalid cursor'}),
            400,
          );
        });

        final client = SyncApiClient(
          baseUrl: baseUrl,
          authToken: authToken,
          httpClient: mockClient,
        );

        expect(
          () => client.syncPull(cursor: 'invalid-cursor'),
          throwsA(isA<SyncApiException>()
              .having((e) => e.statusCode, 'statusCode', 400)
              .having((e) => e.message, 'message', contains('Invalid cursor'))),
        );

        client.close();
      });

      test('should throw SyncApiException on 401 error', () async {
        final mockClient = MockClient((request) async {
          return http.Response('Unauthorized', 401);
        });

        final client = SyncApiClient(
          baseUrl: baseUrl,
          authToken: authToken,
          httpClient: mockClient,
        );

        expect(
          () => client.syncPull(),
          throwsA(isA<SyncApiException>()
              .having((e) => e.statusCode, 'statusCode', 401)
              .having((e) => e.message, 'message', contains('Unauthorized'))),
        );

        client.close();
      });

      test('should throw SyncApiException on network error', () async {
        final mockClient = MockClient((request) async {
          throw http.ClientException('Network unreachable');
        });

        final client = SyncApiClient(
          baseUrl: baseUrl,
          authToken: authToken,
          httpClient: mockClient,
        );

        expect(
          () => client.syncPull(),
          throwsA(isA<SyncApiException>()
              .having((e) => e.message, 'message', contains('Network error'))),
        );

        client.close();
      });
    });

    group('testConnection', () {
      test('should return ok with healthInfo on valid health response', () async {
        final mockClient = MockClient((request) async {
          expect(request.url.path, '/api/v1/mobile/health');
          return http.Response(
            jsonEncode({
              'status': 'ok',
              'service': 'doccione-studio',
              'api_version': 'v1',
              'mobile_api': true,
              'version': '1.0.0',
            }),
            200,
          );
        });

        final client = SyncApiClient(
          baseUrl: baseUrl,
          httpClient: mockClient,
        );

        final result = await client.testConnection();

        expect(result.success, true);
        expect(result.statusCode, 200);
        expect(result.healthInfo, isNotNull);
        expect(result.healthInfo!['status'], 'ok');
        expect(result.healthInfo!['service'], 'doccione-studio');
        expect(result.healthInfo!['api_version'], 'v1');
        expect(result.healthInfo!['mobile_api'], true);

        client.close();
      });

      test('should fail when status is not ok', () async {
        final mockClient = MockClient((request) async {
          return http.Response(
            jsonEncode({
              'status': 'error',
              'service': 'doccione-studio',
              'api_version': 'v1',
              'mobile_api': true,
            }),
            200,
          );
        });

        final client = SyncApiClient(
          baseUrl: baseUrl,
          httpClient: mockClient,
        );

        final result = await client.testConnection();

        expect(result.success, false);
        expect(result.message, contains('status: error'));

        client.close();
      });

      test('should fail when service is not doccione-studio', () async {
        final mockClient = MockClient((request) async {
          return http.Response(
            jsonEncode({
              'status': 'ok',
              'service': 'unknown-service',
              'api_version': 'v1',
              'mobile_api': true,
            }),
            200,
          );
        });

        final client = SyncApiClient(
          baseUrl: baseUrl,
          httpClient: mockClient,
        );

        final result = await client.testConnection();

        expect(result.success, false);
        expect(result.message, contains('service: unknown-service'));

        client.close();
      });

      test('should fail when mobile_api is false', () async {
        final mockClient = MockClient((request) async {
          return http.Response(
            jsonEncode({
              'status': 'ok',
              'service': 'doccione-studio',
              'api_version': 'v1',
              'mobile_api': false,
            }),
            200,
          );
        });

        final client = SyncApiClient(
          baseUrl: baseUrl,
          httpClient: mockClient,
        );

        final result = await client.testConnection();

        expect(result.success, false);
        expect(result.message, contains('mobile_api'));

        client.close();
      });

      test('should return unauthorized on 401', () async {
        final mockClient = MockClient((request) async {
          return http.Response('Unauthorized', 401);
        });

        final client = SyncApiClient(
          baseUrl: baseUrl,
          httpClient: mockClient,
        );

        final result = await client.testConnection();

        expect(result.success, false);
        expect(result.statusCode, 401);

        client.close();
      });

      test('should return network error on connection refused', () async {
        final mockClient = MockClient((request) async {
          throw http.ClientException('Connection refused');
        });

        final client = SyncApiClient(
          baseUrl: baseUrl,
          httpClient: mockClient,
        );

        final result = await client.testConnection();

        expect(result.success, false);
        expect(result.message, contains('Servidor no encontrado'));

        client.close();
      });

      test('should return timeout on slow response', () async {
        final mockClient = MockClient((request) async {
          await Future.delayed(const Duration(seconds: 2));
          return http.Response('{}', 200);
        });

        final client = SyncApiClient(
          baseUrl: baseUrl,
          timeout: const Duration(milliseconds: 100),
          httpClient: mockClient,
        );

        final result = await client.testConnection();

        expect(result.success, false);
        expect(result.message, contains('Tiempo de espera agotado'));

        client.close();
      });

      test('should return server error on 500', () async {
        final mockClient = MockClient((request) async {
          return http.Response('Internal Server Error', 500);
        });

        final client = SyncApiClient(
          baseUrl: baseUrl,
          httpClient: mockClient,
        );

        final result = await client.testConnection();

        expect(result.success, false);
        expect(result.statusCode, 500);

        client.close();
      });
    });

    group('headers', () {
      test('should include auth token when provided', () async {
        final mockClient = MockClient((request) async {
          expect(request.headers['Authorization'], 'Bearer test-token');
          expect(request.headers['Content-Type'], 'application/json');
          expect(request.headers['Accept'], 'application/json');
          return http.Response('{}', 200);
        });

        final client = SyncApiClient(
          baseUrl: baseUrl,
          authToken: 'test-token',
          httpClient: mockClient,
        );

        await client.getCapabilities();
        client.close();
      });

      test('should work without auth token', () async {
        final mockClient = MockClient((request) async {
          expect(request.headers.containsKey('Authorization'), false);
          expect(request.headers['Content-Type'], 'application/json');
          return http.Response('{}', 200);
        });

        final client = SyncApiClient(
          baseUrl: baseUrl,
          httpClient: mockClient,
        );

        await client.getCapabilities();
        client.close();
      });
    });
  });
}
