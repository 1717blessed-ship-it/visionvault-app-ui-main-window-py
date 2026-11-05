// Explicit child-process test. Not part of ordinary test/ discovery.
import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:doccione_mobile/database/database_helper.dart';
import 'package:doccione_mobile/database/order_drafts_repository.dart';
import 'package:doccione_mobile/models/order_draft.dart';
import 'package:doccione_mobile/services/order_integration_client.dart';
import 'package:doccione_mobile/services/order_integration_sync.dart';

void main() {
  test('cola durable en proceso Flutter independiente', () async {
    final config = objectMap(
        jsonDecode(Platform.environment['DOCCIONE_S2B_PROCESS_FIXTURE']!));
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
    final db = await openDatabase(config['database'] as String);
    final store = OrderIntegrationStore(db, owner: 'integration-operator');
    await store.initialize();
    final target = IntegrationTarget(
        baseUrl: config['url'] as String,
        serverId: config['server_id'] as String,
        deviceId: config['device_id'] as String);
    OrderIntegrationClient? client;
    OrderIntegrationSync? sync;
    try {
      if (config['stage'] == 'enqueue') {
        final repo = OrderDraftsRepository(DatabaseHelper(),
            ownerProvider: () async => 'integration-operator',
            databaseProvider: () async => db);
        final saved =
            await repo.save(OrderDraft.fromJson(objectMap(config['draft'])));
        await store.enqueue(saved, target);
        expect((await store.operations(target)).single['state'], 'pending');
      } else {
        final before = (await store.operations(target)).single;
        expect(before['state'], 'pending');
        client = OrderIntegrationClient(
            target: target, token: config['token'] as String);
        sync = OrderIntegrationSync(store, client);
        await sync.drain();
        final after = (await store.operations(target)).single;
        expect(after['operation_id'], before['operation_id']);
        expect(after['payload'], before['payload']);
        expect(after['state'], 'confirmed', reason: '${after['error']}');
      }
    } finally {
      sync?.dispose();
      client?.close();
      await db.close();
    }
  });
}
