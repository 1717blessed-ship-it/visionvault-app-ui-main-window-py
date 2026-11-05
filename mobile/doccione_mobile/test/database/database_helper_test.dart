import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:doccione_mobile/database/database_helper.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late DatabaseHelper dbHelper;
  late Directory temporaryDirectory;

  setUpAll(() async {
    // Initialize FFI for testing
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
    temporaryDirectory = await Directory.systemTemp.createTemp(
      'doccione_mobile_database_test_',
    );
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
      const MethodChannel('plugins.flutter.io/path_provider'),
      (call) async => switch (call.method) {
        'getApplicationDocumentsDirectory' ||
        'getApplicationDocumentsPath' =>
          temporaryDirectory.path,
        _ => null,
      },
    );
  });

  tearDownAll(() async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
      const MethodChannel('plugins.flutter.io/path_provider'),
      null,
    );
    if (temporaryDirectory.existsSync()) {
      await temporaryDirectory.delete(recursive: true);
    }
  });

  setUp(() async {
    dbHelper = DatabaseHelper();
    await dbHelper.deleteDatabase();
  });

  tearDown(() async {
    await dbHelper.deleteDatabase();
  });

  group('DatabaseHelper', () {
    test('should create database with correct version', () async {
      final db = await dbHelper.database;
      expect(db.isOpen, true);
      expect(await db.getVersion(), 18);
    });

    test('should create all required tables', () async {
      final db = await dbHelper.database;

      // Check tables exist
      final tables = await db.rawQuery(
          "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name");

      final tableNames = tables.map((t) => t['name'] as String).toList();
      expect(tableNames, contains('sync_state'));
      expect(tableNames, contains('jobs'));
      expect(tableNames, contains('orders'));
      expect(tableNames, contains('clients'));
    });

    test('should create all required indices', () async {
      final db = await dbHelper.database;

      // Check indices exist
      final indices = await db.rawQuery(
          "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name");

      final indexNames = indices.map((i) => i['name'] as String).toList();
      expect(indexNames, contains('idx_jobs_status'));
      expect(indexNames, contains('idx_jobs_updated'));
      expect(indexNames, contains('idx_orders_status'));
      expect(indexNames, contains('idx_clients_name'));
    });

    test('should initialize sync_state with single row', () async {
      final db = await dbHelper.database;

      final result = await db.query('sync_state');
      expect(result.length, 1);
      expect(result.first['id'], 1);
    });
  });
}
