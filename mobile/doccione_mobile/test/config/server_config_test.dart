import 'package:flutter_test/flutter_test.dart';
import 'package:doccione_mobile/config/server_config.dart';

void main() {
  group('ServerConfig', () {
    test('defaults creates valid config', () {
      const config = ServerConfig.defaults;
      expect(config.host, 'localhost');
      expect(config.port, 8765);
      expect(config.scheme, 'http');
      expect(config.baseUrl, 'http://localhost:8765');
    });

    test('baseUrl constructs correctly', () {
      const config = ServerConfig(
        host: '10.0.0.5',
        port: 9000,
        scheme: 'https',
      );
      expect(config.baseUrl, 'https://10.0.0.5:9000');
    });

    test('toMap and fromMap roundtrip', () {
      const original = ServerConfig(
        host: '172.16.0.1',
        port: 5000,
        scheme: 'https',
      );
      final map = original.toMap();
      final restored = ServerConfig.fromMap(map);
      expect(restored, original);
    });

    test('fromMap uses defaults for missing fields', () {
      final config = ServerConfig.fromMap({});
      expect(config.host, 'localhost');
      expect(config.port, 8765);
      expect(config.scheme, 'http');
    });

    test('copyWith overrides only specified fields', () {
      const original = ServerConfig.defaults;
      final modified = original.copyWith(host: '10.0.0.1', port: 3000);
      expect(modified.host, '10.0.0.1');
      expect(modified.port, 3000);
      expect(modified.scheme, 'http');
    });

    test('isValidHost accepts valid hosts', () {
      expect(ServerConfig.isValidHost('localhost'), true);
      expect(ServerConfig.isValidHost('192.168.1.1'), true);
      expect(ServerConfig.isValidHost('10.0.0.1'), true);
      expect(ServerConfig.isValidHost('my-server.local'), true);
      expect(ServerConfig.isValidHost('studio.local'), true);
    });

    test('isValidHost rejects invalid hosts', () {
      expect(ServerConfig.isValidHost(''), false);
      expect(ServerConfig.isValidHost('a' * 256), false);
      expect(ServerConfig.isValidHost('999.168.1.1'), false);
      expect(ServerConfig.isValidHost('192.168.1.256'), false);
      expect(ServerConfig.isValidHost('http://192.168.1.1'), false);
      expect(ServerConfig.isValidHost('studio local'), false);
      expect(ServerConfig.isValidHost('-studio.local'), false);
    });

    test('isValidPort accepts valid ports', () {
      expect(ServerConfig.isValidPort(1), true);
      expect(ServerConfig.isValidPort(8765), true);
      expect(ServerConfig.isValidPort(65535), true);
    });

    test('isValidPort rejects invalid ports', () {
      expect(ServerConfig.isValidPort(0), false);
      expect(ServerConfig.isValidPort(-1), false);
      expect(ServerConfig.isValidPort(65536), false);
    });

    test('detects local and VPN hosts', () {
      expect(ServerConfig.isPrivateOrLocalHost('localhost'), true);
      expect(ServerConfig.isPrivateOrLocalHost('studio.local'), true);
      expect(ServerConfig.isPrivateOrLocalHost('10.8.0.12'), true);
      expect(ServerConfig.isPrivateOrLocalHost('100.100.20.15'), true);
      expect(ServerConfig.isPrivateOrLocalHost('172.31.20.4'), true);
      expect(ServerConfig.isPrivateOrLocalHost('192.168.1.50'), true);
      expect(ServerConfig.isPrivateOrLocalHost('172.32.0.1'), false);
      expect(ServerConfig.isPrivateOrLocalHost('studio.example.com'), false);
    });

    test('isValidScheme accepts http and https', () {
      expect(ServerConfig.isValidScheme('http'), true);
      expect(ServerConfig.isValidScheme('https'), true);
    });

    test('isValidScheme rejects other schemes', () {
      expect(ServerConfig.isValidScheme('ftp'), false);
      expect(ServerConfig.isValidScheme('ws'), false);
      expect(ServerConfig.isValidScheme(''), false);
    });

    test('isValid validates all fields', () {
      expect(ServerConfig.isValid('localhost', 8765, 'http'), true);
      expect(ServerConfig.isValid('', 8765, 'http'), false);
      expect(ServerConfig.isValid('localhost', 0, 'http'), false);
      expect(ServerConfig.isValid('localhost', 8765, 'ftp'), false);
    });

    test('equality works correctly', () {
      const a = ServerConfig(host: 'localhost', port: 80, scheme: 'http');
      const b = ServerConfig(host: 'localhost', port: 80, scheme: 'http');
      const c = ServerConfig(host: 'localhost', port: 443, scheme: 'https');
      expect(a, b);
      expect(a == c, false);
    });

    test('toString returns baseUrl', () {
      const config = ServerConfig.defaults;
      expect(config.toString(), 'ServerConfig(http://localhost:8765)');
    });
  });
}
