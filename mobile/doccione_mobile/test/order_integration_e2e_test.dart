import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:doccione_mobile/services/order_integration_client.dart';
import 'package:doccione_mobile/services/order_integration_sync.dart';
import 'package:doccione_mobile/models/order_draft.dart';
import 'support/order_integration_fixture.dart';

void main() {
  late IntegrationFixture f;
  setUp(() async {
    f = IntegrationFixture();
    await f.start();
  });
  tearDown(() async {
    await f.close();
  });

  test(
      'E2E creación completa, diseños, unidades, hojas, recibo y reintentos sin duplicación',
      () async {
    final draft = await f.saved();
    await f.sync.enqueue(draft);
    final queued = (await f.rows()).single;
    expect(queued['state'], 'pending');
    expect(queued['base_revision'], 0);
    await Future.wait([f.sync.drain(), f.sync.drain()]);
    final confirmed = (await f.rows()).single;
    expect(confirmed['state'], 'confirmed',
        reason: '${confirmed['error']} ${f.diagnostics}');
    final receipt = objectMap(jsonDecode(confirmed['receipt'] as String));
    final payload = objectMap(jsonDecode(queued['payload'] as String));
    expect(receipt['payload_hash'], operationDigest(payload));
    final snapshot = objectMap(receipt['snapshot']);
    expect((snapshot['jobs'] as List).map((j) => j['quantity']), [100, 2]);
    expect(snapshot['jobs'][0]['designs'].length, 3);
    expect(snapshot['jobs'][1]['designs'].single['quantity'], 1);
    expect((snapshot['jobs'] as List).map((j) => j['unit_kind']),
        ['item', 'sheet']);
    expect(await f.client.send(payload), receipt);
    expect((await f.command('stats'))['orders'], 1);
    expect((await f.client.orders())['orders'].length, 1);
    expect((await f.client.catalog())['products'], isNotEmpty);
    final artifact = File('../../artifacts/s2b-e2e-confirmed.json');
    await artifact.writeAsString(const JsonEncoder.withIndent('  ').convert({
      'receipt': receipt,
      'queue_state': confirmed['state'],
      'counts': await f.command('stats')
    }));
  });

  test('E2E Desktop → Mobile, revisión separada y edición de retorno',
      () async {
    var draft = await f.saved();
    await f.sync.enqueue(draft);
    await f.sync.drain();
    final link = (await f.store.link(draft.id))!;
    await f.command('desktop_edit',
        {'id': link['desktop_id'], 'notes': 'Cambio Desktop real'});
    draft = await f.sync.refresh(draft.id);
    expect(draft.notes, 'Cambio Desktop real');
    expect(draft.revision, 2);
    final newer = (await f.store.link(draft.id))!;
    expect(newer['server_revision'] as int,
        greaterThan(link['server_revision'] as int));
    draft = await f.edit(draft, notes: 'Respuesta desde Flutter');
    await f.sync.enqueue(draft);
    await f.sync.drain();
    expect((await f.rows()).last['state'], 'confirmed',
        reason: '${(await f.rows()).last['error']} ${await f.command('stats', {
              'id': link['desktop_id']
            })}');
    final state = await f.command('stats', {'id': link['desktop_id']});
    expect(state['snapshot']['observations'], 'Respuesta desde Flutter');
    expect(state['orders'], 1);
    expect(state['jobs'], 2);
    final edit =
        objectMap(jsonDecode((await f.rows()).last['payload'] as String));
    await f.client.send(edit);
    expect((await f.command('stats'))['receipts'], 2);
  });

  test(
      'E2E conflicto conserva ambas versiones y rechaza refresh sobre cambios locales',
      () async {
    var draft = await f.saved();
    await f.sync.enqueue(draft);
    await f.sync.drain();
    final link = (await f.store.link(draft.id))!;
    draft = await f.edit(draft, notes: 'NO perder modificación local');
    await f.sync.enqueue(draft);
    await f.command('desktop_edit', {
      'id': link['desktop_id'],
      'notes': 'Modificación Desktop concurrente'
    });
    await f.sync.drain();
    final conflict = (await f.rows()).last;
    expect(conflict['state'], 'conflict');
    expect(conflict['error'], 'revision_conflict');
    expect(
        objectMap(
            jsonDecode(conflict['remote_conflict'] as String))['observations'],
        'Modificación Desktop concurrente');
    expect(
        (await f.store.draft(draft.id)).notes, 'NO perder modificación local');
    await expectLater(
        f.sync.refresh(draft.id), throwsA(isA<OrderSyncFailure>()));
    await expectLater(
        f.sync.retry(conflict['operation_id'] as String), throwsStateError);
    expect((await f.command('stats'))['receipts'], 1);
  });

  test(
      'E2E respuesta perdida después del commit y recuperación tras reiniciar SQLite Mobile',
      () async {
    final draft = await f.saved();
    await f.sync.enqueue(draft);
    final id = (await f.rows()).single['operation_id'];
    await f.command('drop_response');
    await f.sync.drain();
    expect((await f.rows()).single['state'], 'recoverable');
    expect((await f.command('stats'))['orders'], 1);
    f.client.close();
    f.sync.dispose();
    final path = f.db.path;
    await f.db.close();
    f.db = await openDatabase(path);
    await f.reconnect();
    f.now = f.now.add(const Duration(minutes: 6));
    await f.sync.drain();
    expect((await f.rows()).single['operation_id'], id);
    expect((await f.rows()).single['state'], 'confirmed');
    expect((await f.command('stats'))['orders'], 1);
  });

  test(
      'E2E rollback antes del commit conserva operación y permite retry exacto',
      () async {
    final draft = await f.saved();
    await f.sync.enqueue(draft);
    final before = (await f.rows()).single;
    await f.command('fail_before_commit');
    await f.sync.drain();
    expect((await f.rows()).single['state'], 'recoverable');
    expect((await f.command('stats'))['orders'], 0);
    expect((await f.command('stats'))['jobs'], 0);
    f.now = f.now.add(const Duration(minutes: 6));
    await f.sync.drain();
    expect((await f.rows()).single['state'], 'confirmed');
    expect((await f.rows()).single['payload'], before['payload']);
  });

  test(
      'E2E servidor apagado, backoff y reinicio con mismo realm en nuevo endpoint explícito',
      () async {
    final draft = await f.saved();
    await f.sync.enqueue(draft);
    final id = (await f.rows()).single['operation_id'];
    await f.command('offline');
    await f.sync.drain();
    expect((await f.rows()).single['state'], 'recoverable');
    f.url = (await f.command('restart'))['url'] as String;
    f.client.close();
    f.sync.dispose();
    await f.reconnect();
    await f.sync.drain();
    expect((await f.rows()).single['state'], 'recoverable'); // still backoff
    f.now = f.now.add(const Duration(minutes: 6));
    await f.sync.drain();
    expect((await f.rows()).single['state'], 'confirmed');
    expect((await f.rows()).single['operation_id'], id);
    expect((await f.command('stats'))['orders'], 1);
  });

  test('E2E timeout durante envío no provoca una segunda creación', () async {
    final draft = await f.saved();
    await f.sync.enqueue(draft);
    f.client.close();
    f.sync.dispose();
    await f.reconnect(timeout: const Duration(milliseconds: 150));
    await f.command('timeout');
    await f.sync.drain();
    expect((await f.rows()).single['state'], 'recoverable');
    await Future<void>.delayed(const Duration(milliseconds: 650));
    f.client.close();
    f.sync.dispose();
    await f.reconnect();
    f.now = f.now.add(const Duration(minutes: 6));
    await f.sync.drain();
    expect((await f.rows()).single['state'], 'confirmed');
    expect((await f.command('stats'))['orders'], 1);
  });

  test(
      'E2E colisión de idempotencia y precio enviado rechazados sin escritura parcial',
      () async {
    final draft = await f.saved();
    await f.sync.enqueue(draft);
    await f.sync.drain();
    final payload =
        objectMap(jsonDecode((await f.rows()).single['payload'] as String));
    await expectLater(
        f.client.send({...payload, 'observations': 'colisión'}),
        throwsA(isA<OrderSyncFailure>()
            .having((e) => e.code, 'code', 'operation_mismatch')));
    await expectLater(
        f.client.send(
            {...payload, 'operation_id': 'invalid-price', 'total_amount': 1}),
        throwsA(isA<OrderSyncFailure>().having((e) => e.status, 'HTTP', 422)));
    expect((await f.command('stats'))['orders'], 1);
    expect((await f.command('stats'))['receipts'], 1);
  });

  test('E2E revocación e identidad de servidor errónea conservan la cola',
      () async {
    final draft = await f.saved();
    await f.sync.enqueue(draft);
    final wrong = OrderIntegrationClient(
        target: IntegrationTarget(
            baseUrl: f.url,
            serverId: 'other-server',
            deviceId: '${f.pairing['device_id']}'),
        token: f.pairing['session_token'] as String);
    await expectLater(
        wrong.capabilities(),
        throwsA(isA<OrderSyncFailure>()
            .having((e) => e.code, 'code', 'server_identity_mismatch')));
    wrong.close();
    await f.command('revoke', {'device_id': f.pairing['device_id']});
    await f.sync.drain();
    expect((await f.rows()).single['state'], 'intervention');
    expect((await f.rows()).single['error'], 'unauthorized');
    expect((await f.command('stats'))['orders'], 0);
  });

  test(
      'E2E reserva de producción rechaza el agregado entero y conserva la edición',
      () async {
    var draft = await f.saved();
    await f.sync.enqueue(draft);
    await f.sync.drain();
    final link = (await f.store.link(draft.id))!;
    await f.command('production', {'id': link['desktop_id']});
    draft = await f.sync.refresh(draft.id);
    draft = await f.edit(draft, notes: 'No aplicar por reserva');
    await f.sync.enqueue(draft);
    await f.sync.drain();
    expect((await f.rows()).last['state'], 'intervention');
    expect((await f.rows()).last['error'], 'production_committed');
    expect((await f.store.draft(draft.id)).notes, 'No aplicar por reserva');
    expect(
        (await f.command('stats', {'id': link['desktop_id']}))['snapshot']
            ['observations'],
        '');
  });

  test('E2E sesión caducada, token incorrecto y ausencia de token son rechazos',
      () async {
    for (final token in ['invalid', '']) {
      final bad = OrderIntegrationClient(target: f.client.target, token: token);
      await expectLater(
          bad.orders(),
          throwsA(
              isA<OrderSyncFailure>().having((e) => e.status, 'HTTP', 401)));
      bad.close();
    }
    await f.command('expire', {'device_id': f.pairing['device_id']});
    await expectLater(f.client.capabilities(),
        throwsA(isA<OrderSyncFailure>().having((e) => e.status, 'HTTP', 401)));
  });

  test('E2E dos servidores aislados no comparten operaciones ni pedidos',
      () async {
    final other = IntegrationFixture();
    await other.start();
    try {
      var draft = await f.saved();
      await f.sync.enqueue(draft);
      await f.sync.drain();
      final otherClient = OrderIntegrationClient(
          target: IntegrationTarget(
              baseUrl: other.url,
              serverId: f.client.target.serverId,
              deviceId: f.client.target.deviceId),
          token: other.pairing['session_token'] as String);
      await expectLater(
          otherClient.capabilities(),
          throwsA(isA<OrderSyncFailure>()
              .having((e) => e.code, 'code', 'server_identity_mismatch')));
      otherClient.close();
      draft = await f.edit(draft);
      await expectLater(f.store.enqueue(draft, other.client.target),
          throwsA(isA<OrderSyncFailure>()));
      expect((await other.command('stats'))['orders'], 0);
      final anotherOwner =
          OrderIntegrationStore(f.db, owner: 'another-operator');
      expect(await anotherOwner.operations(f.client.target), isEmpty);
    } finally {
      await other.close();
    }
  });

  test(
      'E2E ediciones locales posteriores no quedan confirmadas por un recibo anterior',
      () async {
    var draft = await f.saved();
    await f.sync.enqueue(draft);
    draft = await f.edit(draft, notes: 'Cambio posterior al envío');
    await f.sync.drain();
    expect((await f.rows()).single['state'], 'confirmed');
    final link = (await f.store.link(draft.id))!;
    expect(link['local_revision'], lessThan(draft.revision));
    expect((await f.store.draft(draft.id)).notes, 'Cambio posterior al envío');
    await expectLater(
        f.sync.refresh(draft.id), throwsA(isA<OrderSyncFailure>()));
    await f.sync.enqueue(draft);
    await f.sync.drain();
    expect((await f.rows()).last['state'], 'confirmed');
  });

  test('E2E no se recotiza un trabajo confirmado al cambiar la regla oficial',
      () async {
    var draft = await f.saved();
    await f.sync.enqueue(draft);
    await f.sync.drain();
    final before =
        objectMap(jsonDecode((await f.rows()).single['receipt'] as String));
    final previous = before['snapshot']['jobs'][0]['subtotal'];
    await f.command('change_price');
    draft = await f.edit(draft);
    await f.sync.enqueue(draft);
    await f.sync.drain();
    final after =
        objectMap(jsonDecode((await f.rows()).last['receipt'] as String));
    expect(after['snapshot']['jobs'][0]['subtotal'], previous);
  });

  test(
      'E2E resolución explícita de cabecera conserva rechazo y crea una operación distinta',
      () async {
    var draft = await f.saved();
    await f.sync.enqueue(draft);
    await f.sync.drain();
    final link = (await f.store.link(draft.id))!;
    draft = await f.edit(draft, notes: 'Cabecera elegida explícitamente');
    await f.sync.enqueue(draft);
    await f.command('desktop_edit',
        {'id': link['desktop_id'], 'notes': 'Conflicto Desktop'});
    await f.sync.drain();
    final conflict = (await f.rows()).last;
    expect(conflict['state'], 'conflict');
    await f.sync.resolveHeaderConflict(conflict['operation_id'] as String);
    final rows = await f.rows();
    expect(rows.length, 3);
    expect(rows[1]['active'], 0);
    expect(rows[1]['state'], 'conflict');
    expect(rows.last['state'], 'pending');
    expect(rows.last['operation_id'], isNot(conflict['operation_id']));
    expect(rows[1]['payload'], conflict['payload']);
    expect(rows[1]['remote_conflict'], isNotNull);
    await f.sync.drain();
    expect((await f.rows()).last['state'], 'confirmed');
    expect(
        (await f.command('stats', {'id': link['desktop_id']}))['snapshot']
            ['observations'],
        'Cabecera elegida explícitamente');
  });

  test('E2E resolución no fusiona cantidades ni pierde la versión conflictiva',
      () async {
    var draft = await f.saved();
    await f.sync.enqueue(draft);
    await f.sync.drain();
    final link = (await f.store.link(draft.id))!;
    draft = await f.drafts.save(OrderDraft(
        id: draft.id,
        revision: draft.revision,
        client: draft.client,
        jobs: draft.jobs
            .map((j) =>
                OrderWork.fromJson({...j.toJson(), 'quantity': j.quantity + 1}))
            .toList()));
    await f.sync.enqueue(draft);
    await f.command('desktop_edit',
        {'id': link['desktop_id'], 'notes': 'Desktop ganó revisión'});
    await f.sync.drain();
    final conflict = (await f.rows()).last;
    await expectLater(
        f.sync.resolveHeaderConflict(conflict['operation_id'] as String),
        throwsA(isA<OrderSyncFailure>().having(
            (e) => e.code, 'code', 'commercial_conflict_requires_desktop')));
    expect((await f.rows()).last['active'], 1);
    expect((await f.rows()).length, 2);
    expect((await f.store.draft(draft.id)).jobs.first.quantity, 101);
  });

  test(
      'Destino productivo/LAN, versión incompatible y JSON malformado se rechazan',
      () async {
    for (final origin in [
      'https://example.com',
      'http://192.168.1.2:8000',
      'http://localhost:8000',
      'http://127.0.0.1:8000/api'
    ]) {
      expect(
          () => IntegrationTarget(
              baseUrl: origin, serverId: 'fixture', deviceId: '1'),
          throwsArgumentError);
    }
    for (final raw in [
      '[]',
      'not-json',
      '{"contract_version":2}',
      '{"contract_version":1.0}'
    ]) {
      final bad = OrderIntegrationClient(
          target: f.client.target,
          token: 'fixture',
          client: MockClient((_) async => http.Response(raw, 200)));
      await expectLater(bad.capabilities(), throwsA(isA<OrderSyncFailure>()));
      bad.close();
    }
  });

  test('E2E cola creada y recuperada por dos procesos Flutter distintos',
      () async {
    final source = await f.saved();
    final draft = OrderDraft(client: source.client, jobs: source.jobs);
    final config = {
      'database': f.db.path,
      'url': f.url,
      'server_id': f.client.target.serverId,
      'device_id': f.client.target.deviceId,
      'token': f.pairing['session_token'],
      'draft': draft.toJson()
    };
    final evidence = StringBuffer();
    for (final stage in ['enqueue', 'send']) {
      final result = await Process.run(
          'C:/flutter-sdk/bin/flutter.bat',
          [
            'test',
            'contract_tests/order_queue_process_test.dart',
            '--no-pub',
            '--reporter',
            'expanded'
          ],
          runInShell: true,
          environment: {
            'DOCCIONE_S2B_PROCESS_FIXTURE':
                jsonEncode({...config, 'stage': stage})
          });
      evidence.writeln(
          '$stage exit=${result.exitCode}\n${result.stdout}\n${result.stderr}');
      expect(result.exitCode, 0,
          reason: '$stage: ${result.stdout} ${result.stderr}');
    }
    await File('../../artifacts/s2b-process-restart.log')
        .writeAsString(evidence.toString());
    expect((await f.rows()).single['state'], 'confirmed');
    expect((await f.command('stats'))['orders'], 1);
  }, timeout: const Timeout(Duration(minutes: 3)));

  test('Recibo vacío/no correspondiente nunca confirma; no se siguen redirects',
      () async {
    final draft = await f.saved();
    await f.sync.enqueue(draft);
    final row = (await f.rows()).single;
    await expectLater(
        f.store.confirm(row, {'persisted': true}, f.client.target),
        throwsA(isA<OrderSyncFailure>()));
    expect((await f.rows()).single['state'], 'pending');
    final mock = MockClient((request) async {
      expect(request.followRedirects, false);
      return http.Response('', 302,
          headers: {'location': 'https://external.invalid'});
    });
    final redirected = OrderIntegrationClient(
        target: f.client.target, token: 'ephemeral', client: mock);
    await expectLater(
        redirected.capabilities(),
        throwsA(isA<OrderSyncFailure>()
            .having((e) => e.code, 'code', 'redirect_rejected')));
    redirected.close();
  });
}
