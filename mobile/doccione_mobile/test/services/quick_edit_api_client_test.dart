import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:doccione_mobile/services/quick_edit_api_client.dart';

void main() {
  const baseUrl = 'http://localhost:8000';
  const authToken = 'test-token-123';

  MockClient mockClient0(Future<http.Response> Function(http.Request) handler) {
    return MockClient(handler);
  }

  group('QuickEditApiClient', () {
    group('updateOrderStatus', () {
      test('should send PATCH with correct body', () async {
        final mockClient = mockClient0((request) async {
          expect(request.method, 'PATCH');
          expect(request.url.toString(),
              '$baseUrl/api/v1/mobile/orders/42/status');
          expect(request.headers['Authorization'], 'Bearer $authToken');
          final body = jsonDecode(request.body);
          expect(body['status'], 'Finalizado');
          return http.Response(
              jsonEncode({
                'success': true,
                'order': {'id': 42, 'status': 'Finalizado'}
              }),
              200);
        });

        final client = QuickEditApiClient(
            baseUrl: baseUrl, authToken: authToken, httpClient: mockClient);
        final result = await client.updateOrderStatus(42, 'Finalizado');

        expect(result.success, true);
        expect(result.data!['order']['status'], 'Finalizado');
        client.close();
      });

      test('should return failure on 400', () async {
        final mockClient = mockClient0((request) async {
          return http.Response(jsonEncode({'error': 'Invalid status'}), 400);
        });

        final client = QuickEditApiClient(
            baseUrl: baseUrl, authToken: authToken, httpClient: mockClient);
        final result = await client.updateOrderStatus(42, 'BadStatus');

        expect(result.success, false);
        expect(result.errorMessage, 'Invalid status');
        client.close();
      });

      test('should return failure on 404', () async {
        final mockClient = mockClient0((request) async {
          return http.Response(
              jsonEncode({'error': 'Order 99 not found'}), 404);
        });

        final client = QuickEditApiClient(
            baseUrl: baseUrl, authToken: authToken, httpClient: mockClient);
        final result = await client.updateOrderStatus(99, 'Finalizado');

        expect(result.success, false);
        expect(result.errorMessage, contains('not found'));
        client.close();
      });
    });

    group('updateOrderPriority', () {
      test('should send PATCH with correct body', () async {
        final mockClient = mockClient0((request) async {
          expect(request.method, 'PATCH');
          expect(request.url.toString(),
              '$baseUrl/api/v1/mobile/orders/10/priority');
          final body = jsonDecode(request.body);
          expect(body['print_priority'], 3);
          return http.Response(
              jsonEncode({
                'success': true,
                'order': {'id': 10, 'print_priority': 3}
              }),
              200);
        });

        final client = QuickEditApiClient(
            baseUrl: baseUrl, authToken: authToken, httpClient: mockClient);
        final result = await client.updateOrderPriority(10, 3);

        expect(result.success, true);
        expect(result.data!['order']['print_priority'], 3);
        client.close();
      });

      test('should return failure on out-of-range', () async {
        final mockClient = mockClient0((request) async {
          return http.Response(
              jsonEncode({'error': 'print_priority must be between 0 and 4'}),
              400);
        });

        final client = QuickEditApiClient(
            baseUrl: baseUrl, authToken: authToken, httpClient: mockClient);
        final result = await client.updateOrderPriority(10, 10);

        expect(result.success, false);
        expect(result.errorMessage, contains('between 0 and 4'));
        client.close();
      });
    });

    group('updateJobFields', () {
      test('should send PATCH with quantity and size', () async {
        final mockClient = mockClient0((request) async {
          expect(request.method, 'PATCH');
          expect(
              request.url.toString(), '$baseUrl/api/v1/mobile/orders/5/jobs/7');
          final body = jsonDecode(request.body);
          expect(body['quantity'], 25);
          expect(body['size'], '15cm');
          return http.Response(
              jsonEncode({
                'success': true,
                'job': {'id': 7, 'quantity': 25, 'size': '15cm'}
              }),
              200);
        });

        final client = QuickEditApiClient(
            baseUrl: baseUrl, authToken: authToken, httpClient: mockClient);
        final result =
            await client.updateJobFields(5, 7, quantity: 25, size: '15cm');

        expect(result.success, true);
        expect(result.data!['job']['quantity'], 25);
        client.close();
      });

      test('should send PATCH with only quantity', () async {
        final mockClient = mockClient0((request) async {
          final body = jsonDecode(request.body);
          expect(body.containsKey('quantity'), true);
          expect(body.containsKey('size'), false);
          return http.Response(
              jsonEncode({
                'success': true,
                'job': {'id': 7, 'quantity': 10}
              }),
              200);
        });

        final client = QuickEditApiClient(
            baseUrl: baseUrl, authToken: authToken, httpClient: mockClient);
        final result = await client.updateJobFields(5, 7, quantity: 10);

        expect(result.success, true);
        client.close();
      });

      test('should return failure when job not found', () async {
        final mockClient = mockClient0((request) async {
          return http.Response(jsonEncode({'error': 'Job 999 not found'}), 404);
        });

        final client = QuickEditApiClient(
            baseUrl: baseUrl, authToken: authToken, httpClient: mockClient);
        final result = await client.updateJobFields(5, 999, quantity: 5);

        expect(result.success, false);
        client.close();
      });
    });

    group('registerPayment', () {
      test('should send POST with payment data', () async {
        final mockClient = mockClient0((request) async {
          expect(request.method, 'POST');
          expect(request.url.toString(),
              '$baseUrl/api/v1/mobile/orders/20/payments');
          final body = jsonDecode(request.body);
          expect(body['amount'], 2500.0);
          expect(body['method'], 'Efectivo');
          expect(body['note'], 'Seña');
          return http.Response(
              jsonEncode({
                'success': true,
                'payment': {'amount': 2500.0, 'method': 'Efectivo'},
                'financials': {
                  'budget_total': 5000,
                  'paid_amount': 2500,
                  'payment_status': 'Seña recibida'
                },
              }),
              200);
        });

        final client = QuickEditApiClient(
            baseUrl: baseUrl, authToken: authToken, httpClient: mockClient);
        final result = await client.registerPayment(20,
            amount: 2500, method: 'Efectivo', note: 'Seña');

        expect(result.success, true);
        expect(result.data!['financials']['payment_status'], 'Seña recibida');
        client.close();
      });

      test('should return failure on invalid amount', () async {
        final mockClient = mockClient0((request) async {
          return http.Response(
              jsonEncode({'error': 'amount must be greater than zero'}), 400);
        });

        final client = QuickEditApiClient(
            baseUrl: baseUrl, authToken: authToken, httpClient: mockClient);
        final result = await client.registerPayment(20, amount: 0);

        expect(result.success, false);
        expect(result.errorMessage, contains('greater than zero'));
        client.close();
      });
    });

    group('markDelivered', () {
      test('should send POST to deliver endpoint', () async {
        final mockClient = mockClient0((request) async {
          expect(request.method, 'POST');
          expect(request.url.toString(),
              '$baseUrl/api/v1/mobile/orders/30/deliver');
          final body = jsonDecode(request.body);
          expect(body, isEmpty);
          return http.Response(
              jsonEncode({
                'success': true,
                'order': {'id': 30, 'status': 'Entregado'},
              }),
              200);
        });

        final client = QuickEditApiClient(
            baseUrl: baseUrl, authToken: authToken, httpClient: mockClient);
        final result = await client.markDelivered(30);

        expect(result.success, true);
        expect(result.data!['order']['status'], 'Entregado');
        client.close();
      });

      test('should return failure when order not found', () async {
        final mockClient = mockClient0((request) async {
          return http.Response(
              jsonEncode({'error': 'Order 999 not found'}), 404);
        });

        final client = QuickEditApiClient(
            baseUrl: baseUrl, authToken: authToken, httpClient: mockClient);
        final result = await client.markDelivered(999);

        expect(result.success, false);
        client.close();
      });
    });

    group('changeJobStage', () {
      test('should send POST to stage endpoint', () async {
        final mockClient = mockClient0((request) async {
          expect(request.method, 'POST');
          expect(
              request.url.toString(), '$baseUrl/api/v1/mobile/jobs/15/stage');
          final body = jsonDecode(request.body);
          expect(body['stage'], 'Impresión');
          return http.Response(
              jsonEncode({
                'success': true,
                'message': 'Etapa actualizada',
                'job': {'id': 15, 'status': 'Impresión'},
              }),
              200);
        });

        final client = QuickEditApiClient(
            baseUrl: baseUrl, authToken: authToken, httpClient: mockClient);
        final result = await client.changeJobStage(15, 'Impresión');

        expect(result.success, true);
        expect(result.data!['job']['status'], 'Impresión');
        client.close();
      });
    });

    group('error handling', () {
      test('should handle connection refused', () async {
        final mockClient = mockClient0((request) async {
          throw http.ClientException('Connection refused');
        });

        final client = QuickEditApiClient(
            baseUrl: baseUrl, authToken: authToken, httpClient: mockClient);
        final result = await client.updateOrderStatus(1, 'Finalizado');

        expect(result.success, false);
        expect(result.errorMessage, contains('Error de red'));
        client.close();
      });

      test('should handle timeout', () async {
        final mockClient = mockClient0((request) async {
          await Future.delayed(const Duration(seconds: 5));
          return http.Response('{}', 200);
        });

        final client = QuickEditApiClient(
          baseUrl: baseUrl,
          authToken: authToken,
          httpClient: mockClient,
          timeout: const Duration(milliseconds: 50),
        );
        final result = await client.updateOrderStatus(1, 'Finalizado');

        expect(result.success, false);
        expect(result.errorMessage, contains('agotado'));
        client.close();
      });

      test('should handle server error', () async {
        final mockClient = mockClient0((request) async {
          return http.Response('Internal Server Error', 500);
        });

        final client = QuickEditApiClient(
            baseUrl: baseUrl, authToken: authToken, httpClient: mockClient);
        final result = await client.updateOrderStatus(1, 'Finalizado');

        expect(result.success, false);
        expect(result.errorMessage, contains('servidor'));
        client.close();
      });
    });
  });
}
