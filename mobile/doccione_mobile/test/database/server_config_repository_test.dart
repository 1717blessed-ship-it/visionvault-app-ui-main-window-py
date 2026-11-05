import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:doccione_mobile/database/database_helper.dart';
import 'package:doccione_mobile/database/server_config_repository.dart';
import 'package:doccione_mobile/config/server_config.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late DatabaseHelper dbHelper;
  late ServerConfigRepository repository;

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  setUp(() async {
    dbHelper = DatabaseHelper();
    await dbHelper.deleteDatabase();
    repository = ServerConfigRepository(dbHelper);
  });

  tearDown(() async {
    await dbHelper.close();
  });

  group('ServerConfigRepository', () {
    test('getConfig returns defaults for new database', () async {
      final config = await repository.getConfig();
      expect(config, ServerConfig.defaults);
    });

    test('updateConfig persists values', () async {
      const newConfig = ServerConfig(
        host: '10.0.0.5',
        port: 3000,
        scheme: 'https',
      );
      await repository.updateConfig(newConfig);
      final loaded = await repository.getConfig();
      expect(loaded, newConfig);
    });

    test('updateConfig overwrites previous values', () async {
      const first = ServerConfig(
        host: '10.0.0.1',
        port: 5000,
        scheme: 'http',
      );
      const second = ServerConfig(
        host: '192.168.0.100',
        port: 9000,
        scheme: 'https',
      );
      await repository.updateConfig(first);
      await repository.updateConfig(second);
      final loaded = await repository.getConfig();
      expect(loaded, second);
    });

    test('getConfig returns same values on multiple calls', () async {
      final config1 = await repository.getConfig();
      final config2 = await repository.getConfig();
      expect(config1, config2);
    });
  });
}
