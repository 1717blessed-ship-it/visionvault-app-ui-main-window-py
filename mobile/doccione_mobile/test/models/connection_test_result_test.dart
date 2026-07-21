import 'package:flutter_test/flutter_test.dart';
import 'package:doccione_mobile/models/connection_test_result.dart';

void main() {
  group('ConnectionTestResult', () {
    test('ok creates success result', () {
      final result = ConnectionTestResult.ok(responseTime: const Duration(milliseconds: 150));
      expect(result.success, true);
      expect(result.message, 'Conexión exitosa');
      expect(result.statusCode, 200);
      expect(result.responseTime!.inMilliseconds, 150);
      expect(result.healthInfo, isNull);
    });

    test('ok creates success result with healthInfo', () {
      final healthInfo = {
        'status': 'ok',
        'service': 'doccione-studio',
        'api_version': 'v1',
        'mobile_api': true,
      };
      final result = ConnectionTestResult.ok(
        responseTime: const Duration(milliseconds: 200),
        healthInfo: healthInfo,
      );
      expect(result.success, true);
      expect(result.healthInfo, healthInfo);
      expect(result.healthInfo!['service'], 'doccione-studio');
    });

    test('unauthorized creates failure result', () {
      final result = ConnectionTestResult.unauthorized(statusCode: 401);
      expect(result.success, false);
      expect(result.message, 'Token inválido');
      expect(result.statusCode, 401);
    });

    test('serverError creates failure result', () {
      final result = ConnectionTestResult.serverError(statusCode: 500);
      expect(result.success, false);
      expect(result.message, 'Error del servidor (500)');
      expect(result.statusCode, 500);
    });

    test('timeout creates failure result', () {
      final result = ConnectionTestResult.timeout();
      expect(result.success, false);
      expect(result.message, 'Tiempo de espera agotado');
      expect(result.statusCode, isNull);
    });

    test('networkError creates failure result', () {
      final result = ConnectionTestResult.networkError();
      expect(result.success, false);
      expect(result.message, 'Servidor no encontrado');
    });

    test('networkError with custom detail', () {
      final result = ConnectionTestResult.networkError(detail: 'Connection refused');
      expect(result.success, false);
      expect(result.message, 'Connection refused');
    });

    test('unexpected creates failure result', () {
      final result = ConnectionTestResult.unexpected();
      expect(result.success, false);
      expect(result.message, 'Respuesta inesperada del servidor');
    });

    test('unexpected with custom detail', () {
      final result = ConnectionTestResult.unexpected(detail: 'Custom error');
      expect(result.success, false);
      expect(result.message, 'Custom error');
    });
  });
}
