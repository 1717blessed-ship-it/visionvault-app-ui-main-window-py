import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:doccione_mobile/database/database_helper.dart';
import 'package:doccione_mobile/database/order_drafts_repository.dart';
import 'package:doccione_mobile/models/order_draft.dart';
import 'package:doccione_mobile/services/order_integration_client.dart';
import 'package:doccione_mobile/services/order_integration_sync.dart';

class IntegrationFixture {
  static bool _ffiReady = false;
  late Process process;
  late StreamIterator<String> output;
  late Map<String, dynamic> info, pairing;
  late String url;
  late Directory temporary;
  late Database db;
  late OrderIntegrationStore store;
  late OrderDraftsRepository drafts;
  late OrderIntegrationClient client;
  late OrderIntegrationSync sync;
  DateTime now = DateTime.now();
  final StringBuffer diagnostics = StringBuffer();
  Future<Map<String, dynamic>> read() async {
    while (await output.moveNext().timeout(const Duration(seconds: 30))) {
      if (output.current.startsWith('S2B:')) {
        return objectMap(jsonDecode(output.current.substring(4)));
      }
    }
    throw StateError('Fixture ended: $diagnostics');
  }

  Future<Map<String, dynamic>> command(String action,
      [Map<String, dynamic> fields = const {}]) async {
    process.stdin.writeln(jsonEncode({'action': action, ...fields}));
    await process.stdin.flush();
    return read();
  }

  Future<void> start() async {
    process = await Process.start(
        'python', ['-u', '../../tools/order_sync_e2e_fixture.py'],
        environment: {'PYTHONIOENCODING': 'utf-8'});
    output = StreamIterator(
        process.stdout.transform(utf8.decoder).transform(const LineSplitter()));
    process.stderr.transform(utf8.decoder).listen(diagnostics.write);
    info = await read();
    url = info['url'] as String;
    pairing = await OrderIntegrationClient.pair(url, info['code'] as String);
    if (!_ffiReady) {
      sqfliteFfiInit();
      databaseFactory = databaseFactoryFfi;
      _ffiReady = true;
    }
    temporary = await Directory.systemTemp.createTemp('doccione-s2b-mobile-');
    db = await openDatabase(
        '${temporary.path}/doccione-mobile-order-integration-test.db');
    await reconnect();
  }

  Future<void> reconnect(
      {Duration timeout = const Duration(seconds: 8)}) async {
    store = OrderIntegrationStore(db, owner: 'integration-operator');
    await store.initialize();
    drafts = OrderDraftsRepository(DatabaseHelper(),
        ownerProvider: () async => 'integration-operator',
        databaseProvider: () async => db);
    client = OrderIntegrationClient(
        target: IntegrationTarget(
            baseUrl: url,
            serverId: pairing['integration_server_id'] as String,
            deviceId: '${pairing['device_id']}'),
        token: pairing['session_token'] as String,
        timeout: timeout);
    sync = OrderIntegrationSync(store, client, clock: () => now);
  }

  Future<OrderDraft> saved({String notes = '', bool designs = true}) =>
      drafts.save(
          OrderDraft(client: 'Cliente FICTICIO Flutter', notes: notes, jobs: [
        OrderWork(
            productCode: info['product'] as String,
            variantCode: info['variant'] as String,
            productName: 'Producto FICTICIO',
            material: info['material'] as String,
            size: '5cm',
            quantity: 100,
            designs: designs
                ? [
                    DesignAllocation(
                        designId: info['designs'][0] as String,
                        name: 'FICTICIO A',
                        quantity: 40),
                    DesignAllocation(
                        designId: info['designs'][1] as String,
                        name: 'FICTICIO B',
                        quantity: 35),
                    DesignAllocation(
                        designId: info['designs'][2] as String,
                        name: 'FICTICIO C',
                        quantity: 25)
                  ]
                : []),
        OrderWork(
            productCode: info['product'] as String,
            variantCode: info['variant'] as String,
            productName: 'Producto FICTICIO hojas',
            material: info['material'] as String,
            size: '5cm',
            quantity: 2,
            unitKind: 'sheets',
            designs: designs
                ? [
                    DesignAllocation(
                        designId: info['designs'][0] as String,
                        name: 'FICTICIO A',
                        quantity: 1)
                  ]
                : []),
      ]));
  Future<OrderDraft> edit(OrderDraft draft, {String notes = 'Edición local'}) =>
      drafts.save(OrderDraft(
          id: draft.id,
          revision: draft.revision,
          client: draft.client,
          whatsapp: draft.whatsapp,
          notes: notes,
          jobs: draft.jobs));
  Future<List<Map<String, Object?>>> rows() => store.operations(client.target);
  Future<void> close() async {
    client.close();
    sync.dispose();
    await db.close();
    process.stdin.writeln('{"action":"close"}');
    await process.stdin.close();
    await process.exitCode.timeout(const Duration(seconds: 15), onTimeout: () {
      process.kill();
      return -1;
    });
    await output.cancel();
    // Only this fixture's own fresh temporary directory.
    await temporary.delete(recursive: true);
  }
}
