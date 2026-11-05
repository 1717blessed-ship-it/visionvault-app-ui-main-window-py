import 'package:flutter_test/flutter_test.dart';
import 'package:doccione_mobile/config/server_config.dart';

/// Replicates _unreachableHosts from HomePage.
const unreachableHosts = {'localhost', '127.0.0.1', '0.0.0.0', ''};

/// Simulates the _pairingUrl getter from HomePage.
String pairingUrlFrom(String baseUrl) {
  const int pairingPort = 8765;
  final uri = Uri.parse(baseUrl);
  return '${uri.scheme}://${uri.host}:$pairingPort';
}

/// Simulates _loadServerConfig validation logic.
/// Returns (configLoaded, configError, baseUrl) after loading a config.
({bool loaded, String? error, String baseUrl}) loadConfig(ServerConfig config) {
  if (unreachableHosts.contains(config.host)) {
    return (
      loaded: false,
      error: 'Configurá la IP de la PC antes de vincular',
      baseUrl: ''
    );
  }
  return (loaded: true, error: null, baseUrl: config.baseUrl);
}

String buttonTextForState(bool configLoaded) =>
    configLoaded ? 'Vincular' : 'Configurar servidor primero';

Function? onPressedForState(bool configLoaded) => configLoaded ? () {} : null;

void main() {
  group('host validation for Android', () {
    test('localhost keeps Vincular disabled', () {
      const config =
          ServerConfig(host: 'localhost', port: 8765, scheme: 'http');
      final result = loadConfig(config);
      expect(result.loaded, false);
      expect(result.error, 'Configurá la IP de la PC antes de vincular');
      expect(onPressedForState(result.loaded), isNull);
      expect(buttonTextForState(result.loaded), 'Configurar servidor primero');
    });

    test('127.0.0.1 keeps Vincular disabled', () {
      const config =
          ServerConfig(host: '127.0.0.1', port: 8765, scheme: 'http');
      final result = loadConfig(config);
      expect(result.loaded, false);
      expect(result.error, isNotNull);
      expect(onPressedForState(result.loaded), isNull);
    });

    test('0.0.0.0 keeps Vincular disabled', () {
      const config = ServerConfig(host: '0.0.0.0', port: 8765, scheme: 'http');
      final result = loadConfig(config);
      expect(result.loaded, false);
      expect(result.error, isNotNull);
      expect(onPressedForState(result.loaded), isNull);
    });

    test('empty host keeps Vincular disabled', () {
      const config = ServerConfig(host: '', port: 8765, scheme: 'http');
      final result = loadConfig(config);
      expect(result.loaded, false);
      expect(result.error, isNotNull);
      expect(onPressedForState(result.loaded), isNull);
    });

    test('192.168.1.46:8766 enables Vincular', () {
      const config =
          ServerConfig(host: '192.168.1.46', port: 8766, scheme: 'http');
      final result = loadConfig(config);
      expect(result.loaded, true);
      expect(result.error, isNull);
      expect(onPressedForState(result.loaded), isNotNull);
      expect(buttonTextForState(result.loaded), 'Vincular');
    });

    test('10.0.0.50 enables Vincular', () {
      const config =
          ServerConfig(host: '10.0.0.50', port: 9000, scheme: 'http');
      final result = loadConfig(config);
      expect(result.loaded, true);
      expect(result.error, isNull);
    });

    test('my-server.local enables Vincular', () {
      const config =
          ServerConfig(host: 'my-server.local', port: 8765, scheme: 'http');
      final result = loadConfig(config);
      expect(result.loaded, true);
      expect(result.error, isNull);
    });
  });

  group('pairingUrl derivation', () {
    test(
        'saved 192.168.1.46:8766 -> pairing at 192.168.1.46:8765, never localhost',
        () {
      const saved =
          ServerConfig(host: '192.168.1.46', port: 8766, scheme: 'http');
      final url = pairingUrlFrom(saved.baseUrl);
      expect(url, 'http://192.168.1.46:8765');
      expect(url, isNot(contains('localhost')));
      expect(url, contains('192.168.1.46'));
    });

    test('pairing URL always uses port 8765 regardless of configured port', () {
      const configs = [
        ServerConfig(host: '1.2.3.4', port: 3000, scheme: 'http'),
        ServerConfig(host: '1.2.3.4', port: 9000, scheme: 'http'),
        ServerConfig(host: '1.2.3.4', port: 8766, scheme: 'http'),
      ];
      for (final config in configs) {
        final url = pairingUrlFrom(config.baseUrl);
        expect(url, endsWith(':8765'));
      }
    });

    test('pairing URL uses configured scheme', () {
      const config =
          ServerConfig(host: '10.0.0.1', port: 8766, scheme: 'https');
      final url = pairingUrlFrom(config.baseUrl);
      expect(url, 'https://10.0.0.1:8765');
    });

    test('exact pairing request URL for the real bug scenario', () {
      const saved =
          ServerConfig(host: '192.168.1.46', port: 8766, scheme: 'http');
      final baseUrl = pairingUrlFrom(saved.baseUrl);
      final fullUrl = '$baseUrl/api/pair/validate';
      expect(fullUrl, 'http://192.168.1.46:8765/api/pair/validate');
      expect(fullUrl, isNot(contains('localhost')));
    });
  });

  group('button state', () {
    test('disabled when configLoaded is false', () {
      expect(onPressedForState(false), isNull);
    });

    test('enabled when configLoaded is true', () {
      expect(onPressedForState(true), isNotNull);
    });

    test('text shows "Configurar servidor primero" when disabled', () {
      expect(buttonTextForState(false), 'Configurar servidor primero');
    });

    test('text shows "Vincular" when enabled', () {
      expect(buttonTextForState(true), 'Vincular');
    });
  });
}
