import 'package:doccione_mobile/services/order_integration_client.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  const usbPilot = bool.fromEnvironment('DOCCIONE_ORDER_INTEGRATION_USB');
  test('USB pilot accepts only TLS loopback on the fixed port', () {
    expect(
        IntegrationTarget(
            baseUrl: 'https://127.0.0.1:8875',
            serverId: 'server',
            deviceId: 'device'),
        isA<IntegrationTarget>());
    for (final invalid in [
      'http://127.0.0.1:8875',
      'https://127.0.0.1:8876',
      'https://192.168.1.21:8875',
    ]) {
      expect(
          () => IntegrationTarget(
              baseUrl: invalid, serverId: 'server', deviceId: 'device'),
          throwsArgumentError,
          reason: invalid);
    }
  }, skip: !usbPilot ? 'requiere define USB explícito' : false);
}
