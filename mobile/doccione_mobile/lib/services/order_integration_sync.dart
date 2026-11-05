import 'dart:convert';
import 'dart:math';
import 'package:flutter/foundation.dart';
import 'package:sqflite/sqflite.dart';
import '../models/order_draft.dart';
import '../models/order_sync_proposal.dart';
import 'order_integration_client.dart';

enum OrderTransferState {
  local,
  pending,
  syncing,
  confirmed,
  conflict,
  recoverable,
  intervention
}

const transferLabels = {
  OrderTransferState.local: 'Guardado local',
  OrderTransferState.pending: 'Pendiente de sincronización',
  OrderTransferState.syncing: 'Sincronizando',
  OrderTransferState.confirmed: 'Sincronizado y confirmado',
  OrderTransferState.conflict: 'Conflicto',
  OrderTransferState.recoverable: 'Error recuperable',
  OrderTransferState.intervention: 'Requiere intervención',
};

/// Explicitly installed only in an integration harness, not a production migration.
/// Uses existing order_drafts and optimistic local revision, not the remote cache.
class OrderIntegrationStore {
  final Database db;
  final String owner;
  OrderIntegrationStore(this.db, {required this.owner}) {
    if (kReleaseMode ||
        owner.isEmpty ||
        !db.path
            .replaceAll('\\', '/')
            .split('/')
            .last
            .startsWith('doccione-mobile-order-integration-')) {
      throw StateError(
          'Integration only: requires a separately named SQLite file.');
    }
  }
  Future<void> initialize() async {
    await db.execute('''CREATE TABLE IF NOT EXISTS order_drafts (
      id TEXT NOT NULL, owner_scope TEXT NOT NULL, revision INTEGER NOT NULL,
      payload TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(id,owner_scope))''');
    await db.execute('''CREATE TABLE IF NOT EXISTS integration_order_queue (
      operation_id TEXT PRIMARY KEY, owner TEXT NOT NULL, target TEXT NOT NULL,
      local_id TEXT NOT NULL, operation_type TEXT NOT NULL, payload TEXT NOT NULL,
      base_revision INTEGER NOT NULL, local_revision INTEGER NOT NULL,
      state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, error TEXT,
      created_at TEXT NOT NULL, next_attempt TEXT, receipt TEXT, remote_conflict TEXT,
      confirmed_at TEXT, active INTEGER NOT NULL DEFAULT 1)''');
    await db.execute('''CREATE TABLE IF NOT EXISTS integration_order_links (
      owner TEXT NOT NULL, local_id TEXT NOT NULL, target TEXT NOT NULL,
      desktop_id TEXT NOT NULL, server_revision INTEGER NOT NULL,
      local_revision INTEGER NOT NULL, snapshot TEXT NOT NULL, confirmed_at TEXT NOT NULL,
      PRIMARY KEY(owner,local_id), UNIQUE(owner,target,desktop_id))''');
  }

  Future<OrderDraft> draft(String id) async {
    final rows = await db.query('order_drafts',
        where: 'id=? AND owner_scope=?', whereArgs: [id, owner]);
    if (rows.length != 1) {
      throw StateError('Borrador no disponible para esta sesión.');
    }
    return OrderDraft.fromJson(
        objectMap(jsonDecode(rows.single['payload'] as String)));
  }

  Future<Map<String, Object?>?> link(String id) async {
    final rows = await db.query('integration_order_links',
        where: 'owner=? AND local_id=?', whereArgs: [owner, id]);
    return rows.isEmpty ? null : rows.single;
  }

  Future<List<Map<String, Object?>>> operations(IntegrationTarget target,
          {String? localId}) =>
      db.query('integration_order_queue',
          where:
              'owner=? AND target=?${localId == null ? '' : ' AND local_id=?'}',
          whereArgs: [owner, target.key, if (localId != null) localId],
          orderBy: 'created_at,operation_id');
  Future<String> enqueue(OrderDraft local, IntegrationTarget target) async {
    final operationId = List.generate(
            24,
            (_) =>
                Random.secure().nextInt(256).toRadixString(16).padLeft(2, '0'))
        .join();
    return db.transaction((tx) async {
      final saved = await tx.query('order_drafts',
          where: 'id=? AND owner_scope=?', whereArgs: [local.id, owner]);
      if (saved.length != 1 ||
          saved.single['payload'] != jsonEncode(local.toJson())) {
        throw StateError(
            'Guardá la revisión local vigente antes de preparar el envío.');
      }
      final links = await tx.query('integration_order_links',
          where: 'owner=? AND local_id=?', whereArgs: [owner, local.id]);
      final pending = await tx.query('integration_order_queue',
          where: 'owner=? AND local_id=? AND state!=? AND active=1',
          whereArgs: [owner, local.id, 'confirmed']);
      if (pending.isNotEmpty) {
        if (pending.single['target'] == target.key &&
            pending.single['local_revision'] == local.revision) {
          return pending.single['operation_id'] as String;
        }
        throw StateError(
            'Resolver la operación anterior sin reemplazar su identidad ni payload.');
      }
      final l = links.isEmpty ? null : links.single;
      if (l != null && l['target'] != target.key) {
        throw const OrderSyncFailure('server_identity_mismatch');
      }
      // A confirmed operation cannot confirm later unsent changes.
      if (l != null && l['local_revision'] == local.revision) {
        throw StateError('Sin cambios locales para enviar.');
      }
      final proposal = OrderSyncProposal(
          operationId: operationId,
          draft: local,
          desktopOrderId: l?['desktop_id'] as String?,
          expectedRevision: l?['server_revision'] as int? ?? 0);
      final payload = proposal.toJson();
      bool tooLong(String value, int max) => value.length > max;
      if (tooLong(local.id, 120) ||
          tooLong(local.client, 120) ||
          tooLong(local.whatsapp, 40) ||
          tooLong(local.notes, 2000) ||
          local.jobs.any((j) =>
              tooLong(j.id, 120) ||
              tooLong(j.productCode, 120) ||
              tooLong(j.variantCode, 120) ||
              tooLong(j.material, 120) ||
              tooLong(j.size, 40) ||
              tooLong(j.notes, 2000) ||
              j.designs.any((d) =>
                  tooLong(d.designId, 256) ||
                  tooLong(jsonEncode([j.id, d.designId]), 512)))) {
        throw const OrderSyncFailure('validation_failed', 422);
      }
      if (utf8.encode(jsonEncode(payload)).length > 65536 ||
          local.jobs.length > 30 ||
          local.jobs.any((j) => j.quantity > 10000 || j.designs.length > 100)) {
        throw const OrderSyncFailure('payload_too_large', 413);
      }
      await tx.insert('integration_order_queue', {
        'operation_id': operationId,
        'owner': owner,
        'target': target.key,
        'local_id': local.id,
        'operation_type': l == null ? 'create' : 'update',
        'payload': jsonEncode(payload),
        'base_revision': proposal.expectedRevision,
        'local_revision': local.revision,
        'state': 'pending',
        'created_at': DateTime.now().toUtc().toIso8601String()
      });
      return operationId;
    });
  }

  Future<void> patch(String id, Map<String, Object?> values) =>
      db.update('integration_order_queue', values,
          where: 'operation_id=? AND owner=?',
          whereArgs: [id, owner]).then((_) {});

  Future<void> confirm(Map<String, Object?> operation,
      Map<String, dynamic> receipt, IntegrationTarget target) async {
    final payload = objectMap(jsonDecode(operation['payload'] as String));
    final snapshot = receipt['snapshot'] is Map
        ? objectMap(receipt['snapshot'])
        : <String, dynamic>{};
    final desktopId = receipt['desktop_order_id'];
    if (receipt['contract_version'] != 1 ||
        receipt['integration_server_id'] != target.serverId ||
        receipt['persisted'] != true ||
        receipt['operation_id'] != operation['operation_id'] ||
        receipt['payload_hash'] != operationDigest(payload) ||
        desktopId is! String ||
        !RegExp(r'^[1-9][0-9]*$').hasMatch(desktopId) ||
        receipt['revision'] is! int ||
        (receipt['revision'] as int) < 1 ||
        snapshot['desktop_order_id'] != desktopId ||
        snapshot['client_order_id'] != operation['local_id'] ||
        snapshot['revision'] != receipt['revision'] ||
        payload['desktop_order_id'] != null &&
            payload['desktop_order_id'] != desktopId ||
        operation['target'] != target.key) {
      throw const OrderSyncFailure('invalid_receipt');
    }
    final incoming = payload['jobs'] as List;
    final returned = snapshot['jobs'] as List;
    if (incoming.length != returned.length ||
        returned.any((j) => j['desktop_job_id'] is! String) ||
        returned.map((j) => j['desktop_job_id']).toSet().length !=
            returned.length ||
        returned.map((j) => j['client_job_id']).toSet().length !=
            returned.length ||
        !incoming.every((j) =>
            returned.any((r) => r['client_job_id'] == j['client_job_id']))) {
      throw const OrderSyncFailure('invalid_receipt');
    }
    for (final job in incoming) {
      final actual = returned
          .singleWhere((j) => j['client_job_id'] == job['client_job_id']);
      final designs = actual['designs'];
      if (actual['quantity'] != job['quantity'] ||
          actual['unit_kind'] != job['unit_kind'] ||
          designs is! List ||
          designs.length != (job['designs'] as List).length ||
          !((job['designs'] as List).every((d) => designs.any((r) =>
              r['association_id'] == d['association_id'] &&
              r['catalog_design_id'] == d['catalog_design_id'] &&
              r['quantity'] == d['quantity'] &&
              r['demand_line_id'] is String &&
              (r['demand_line_id'] as String).isNotEmpty)))) {
        throw const OrderSyncFailure('invalid_receipt');
      }
    }
    await db.transaction((tx) async {
      final durable = await tx.query('integration_order_queue',
          where: 'operation_id=? AND owner=?',
          whereArgs: [operation['operation_id'], owner]);
      final conflicting = await tx.query('integration_order_links',
          where: 'owner=? AND target=? AND desktop_id=? AND local_id!=?',
          whereArgs: [owner, target.key, desktopId, operation['local_id']]);
      if (durable.length != 1 ||
          durable.single['payload'] != operation['payload'] ||
          durable.single['target'] != target.key ||
          conflicting.isNotEmpty) {
        throw const OrderSyncFailure('client_identity_mismatch');
      }
      final previous = await tx.query('integration_order_links',
          where: 'owner=? AND local_id=?',
          whereArgs: [owner, operation['local_id']]);
      if (previous.isNotEmpty &&
          (previous.single['target'] != target.key ||
              previous.single['desktop_id'] != desktopId)) {
        throw const OrderSyncFailure('client_identity_mismatch');
      }
      final older = previous.isNotEmpty &&
          (previous.single['server_revision'] as int) >
              (receipt['revision'] as int);
      if (!older) {
        await tx.insert(
            'integration_order_links',
            {
              'owner': owner,
              'local_id': operation['local_id'],
              'target': target.key,
              'desktop_id': desktopId,
              'server_revision': receipt['revision'],
              'local_revision': operation['local_revision'],
              'snapshot': jsonEncode(snapshot),
              'confirmed_at': DateTime.now().toUtc().toIso8601String()
            },
            conflictAlgorithm: ConflictAlgorithm.replace);
      }
      await tx.update(
          'integration_order_queue',
          {
            'state': 'confirmed',
            'receipt': jsonEncode(receipt),
            'confirmed_at': DateTime.now().toUtc().toIso8601String(),
            'error': null,
            'next_attempt': null
          },
          where: 'operation_id=? AND owner=?',
          whereArgs: [operation['operation_id'], owner]);
    });
  }

  Future<OrderDraft> acceptRemote(String id, IntegrationTarget target,
      Map<String, dynamic> snapshot) async {
    return db.transaction((tx) async {
      final links = await tx.query('integration_order_links',
          where: 'owner=? AND local_id=?', whereArgs: [owner, id]);
      if (links.length != 1 ||
          links.single['target'] != target.key ||
          snapshot['desktop_order_id'] != links.single['desktop_id'] ||
          snapshot['revision'] is! int ||
          (snapshot['revision'] as int) <
              (links.single['server_revision'] as int)) {
        throw const OrderSyncFailure('server_identity_mismatch');
      }
      final rows = await tx.query('order_drafts',
          where: 'id=? AND owner_scope=?', whereArgs: [id, owner]);
      final pending = await tx.query('integration_order_queue',
          where: 'owner=? AND local_id=? AND state!=? AND active=1',
          whereArgs: [owner, id, 'confirmed']);
      if (rows.length != 1 ||
          pending.isNotEmpty ||
          rows.single['revision'] != links.single['local_revision']) {
        throw const OrderSyncFailure('local_changes_pending');
      }
      final local = OrderDraft.fromJson(
          objectMap(jsonDecode(rows.single['payload'] as String)));
      if (snapshot['revision'] == links.single['server_revision']) return local;
      final converted = draftFromSnapshot(snapshot, local: local);
      final saved = OrderDraft(
          id: local.id,
          revision: local.revision + 1,
          client: converted.client,
          whatsapp: converted.whatsapp,
          notes: converted.notes,
          jobs: converted.jobs);
      await tx.update(
          'order_drafts',
          {
            'revision': saved.revision,
            'payload': jsonEncode(saved.toJson()),
            'updated_at': DateTime.now().toUtc().toIso8601String()
          },
          where: 'id=? AND owner_scope=?',
          whereArgs: [id, owner]);
      await tx.update(
          'integration_order_links',
          {
            'local_revision': saved.revision,
            'server_revision': snapshot['revision'],
            'snapshot': jsonEncode(snapshot)
          },
          where: 'owner=? AND local_id=?',
          whereArgs: [owner, id]);
      return saved;
    });
  }

  /// Only after a definite 409 and explicit review. Never rebases an uncertain send.
  Future<void> resolveHeaderConflict(String operationId,
      IntegrationTarget target, Map<String, dynamic> remote) async {
    await db.transaction((tx) async {
      final rows = await tx.query('integration_order_queue',
          where: 'operation_id=? AND owner=? AND target=? AND active=1',
          whereArgs: [operationId, owner, target.key]);
      if (rows.length != 1 || rows.single['state'] != 'conflict') {
        throw StateError('No es un conflicto rechazado.');
      }
      final original = rows.single;
      final saved = await tx.query('order_drafts',
          where: 'id=? AND owner_scope=?',
          whereArgs: [original['local_id'], owner]);
      if (saved.length != 1 ||
          saved.single['revision'] != original['local_revision']) {
        throw const OrderSyncFailure('local_changes_pending');
      }
      final local = OrderDraft.fromJson(
          objectMap(jsonDecode(saved.single['payload'] as String)));
      final remoteDraft = draftFromSnapshot(remote, local: local);
      final originalPayload =
          objectMap(jsonDecode(original['payload'] as String));
      if (remote['desktop_order_id'] != originalPayload['desktop_order_id'] ||
          remote['revision'] is! int ||
          (remote['revision'] as int) < (original['base_revision'] as int)) {
        throw const OrderSyncFailure('invalid_response');
      }
      String signature(OrderWork job) => jsonEncode([
            job.id,
            job.productCode,
            job.variantCode,
            job.material,
            job.size,
            job.quantity,
            job.unitKind,
            job.designs.map((d) => [d.designId, d.quantity]).toList()
          ]);
      if (local.jobs.length != remoteDraft.jobs.length ||
          !local.jobs.every((j) =>
              remoteDraft.jobs.any((r) => signature(r) == signature(j)))) {
        throw const OrderSyncFailure('commercial_conflict_requires_desktop');
      }
      final newId = List.generate(
          24,
          (_) => Random.secure()
              .nextInt(256)
              .toRadixString(16)
              .padLeft(2, '0')).join();
      final payload = OrderSyncProposal(
              operationId: newId,
              draft: local,
              desktopOrderId: remote['desktop_order_id'] as String,
              expectedRevision: remote['revision'] as int)
          .toJson();
      await tx.update(
          'integration_order_queue',
          {
            'active': 0,
            'error': 'conflict_replaced_explicitly',
            'remote_conflict': jsonEncode(remote)
          },
          where: 'operation_id=? AND owner=?',
          whereArgs: [operationId, owner]);
      await tx.insert('integration_order_queue', {
        'operation_id': newId,
        'owner': owner,
        'target': target.key,
        'local_id': local.id,
        'operation_type': 'update',
        'payload': jsonEncode(payload),
        'base_revision': remote['revision'],
        'local_revision': local.revision,
        'state': 'pending',
        'created_at': DateTime.now().toUtc().toIso8601String()
      });
    });
  }
}

/// Manual bounded drain. No timer, startup registration or production sync hook.
class OrderIntegrationSync extends ChangeNotifier {
  final OrderIntegrationStore store;
  final OrderIntegrationClient client;
  final DateTime Function() clock;
  bool running = false;
  Future<void>? _inFlight;
  Future<void> get idle => _inFlight ?? Future<void>.value();
  String connection = 'Sin comprobar';
  OrderIntegrationSync(this.store, this.client, {DateTime Function()? clock})
      : clock = clock ?? DateTime.now;
  Future<void> enqueue(OrderDraft draft) async {
    await store.enqueue(draft, client.target);
    notifyListeners();
  }

  Future<void> drain() =>
      _inFlight ??= _drain().whenComplete(() => _inFlight = null);
  Future<void> _drain() async {
    if (running) return;
    running = true;
    notifyListeners();
    try {
      final capabilities = await client.capabilities();
      connection = 'Conectado · integración aislada';
      if (capabilities['writes_enabled'] != true) {
        throw const OrderSyncFailure('writes_disabled', 503);
      }
      final rows = await store.operations(client.target);
      for (final row in rows
          .where((r) =>
              r['active'] == 1 &&
              ['pending', 'syncing', 'recoverable'].contains(r['state']))
          .take(10)) {
        final due = row['next_attempt'] as String?;
        if (due != null && DateTime.parse(due).isAfter(clock())) continue;
        final id = row['operation_id'] as String;
        final attempts = (row['attempts'] as int) + 1;
        await store.patch(id, {'state': 'syncing', 'attempts': attempts});
        notifyListeners();
        try {
          final payload = objectMap(jsonDecode(row['payload'] as String));
          // Recover an uncertain commit FIRST; never invent a new operation ID.
          final result = await client.result(id) ?? await client.send(payload);
          await store.confirm(row, result, client.target);
        } on OrderSyncFailure catch (e) {
          await _failure(row, e, attempts);
          if (e.recoverable || e.status == 401 || e.status == 403) break;
        } catch (_) {
          await _failure(
              row, const OrderSyncFailure('invalid_receipt'), attempts);
        }
        notifyListeners();
      }
    } on OrderSyncFailure catch (e) {
      connection = e.recoverable
          ? 'Sin conexión · cambios conservados'
          : 'Conexión rechazada: ${e.code}';
      for (final row in (await store.operations(client.target)).where((r) =>
          r['active'] == 1 &&
          ['pending', 'syncing', 'recoverable'].contains(r['state']))) {
        await _failure(row, e, (row['attempts'] as int) + 1);
      }
    } finally {
      running = false;
      notifyListeners();
    }
  }

  Future<void> _failure(
      Map<String, Object?> row, OrderSyncFailure e, int attempts) async {
    Map<String, dynamic>? remote;
    if (e.conflict) {
      final payload = objectMap(jsonDecode(row['payload'] as String));
      try {
        remote = objectMap((await client
            .order(payload['desktop_order_id'] as String))['snapshot']);
      } catch (_) {/* local remains durable */}
    }
    await store.patch(row['operation_id'] as String, {
      'state': e.conflict
          ? 'conflict'
          : e.recoverable
              ? 'recoverable'
              : 'intervention',
      'attempts': attempts,
      'error': e.code,
      'remote_conflict': remote == null ? null : jsonEncode(remote),
      'next_attempt': e.recoverable
          ? clock()
              .add(Duration(seconds: min(300, 1 << min(attempts, 8))))
              .toUtc()
              .toIso8601String()
          : null
    });
  }

  Future<OrderDraft> refresh(String id) async {
    await client.capabilities();
    final link = await store.link(id);
    if (link == null || link['target'] != client.target.key) {
      throw const OrderSyncFailure('server_identity_mismatch');
    }
    final data = await client.order(link['desktop_id'] as String);
    final local = await store.acceptRemote(
        id, client.target, objectMap(data['snapshot']));
    notifyListeners();
    return local;
  }

  /// Retry auth/intervention only after operator correction; conflicts never auto-rebase.
  Future<void> retry(String id) async {
    final row = (await store.operations(client.target))
        .singleWhere((r) => r['operation_id'] == id);
    if (row['state'] == 'conflict' || row['state'] == 'confirmed') {
      throw StateError('No se puede reescribir esta operación.');
    }
    await store.patch(id, {'state': 'pending', 'next_attempt': null});
    notifyListeners();
  }

  Future<void> resolveHeaderConflict(String id) async {
    if (running) throw StateError('Esperá el envío en curso.');
    await client.capabilities();
    final row = (await store.operations(client.target))
        .singleWhere((r) => r['operation_id'] == id);
    final payload = objectMap(jsonDecode(row['payload'] as String));
    final remote = objectMap((await client
        .order(payload['desktop_order_id'] as String))['snapshot']);
    await store.resolveHeaderConflict(id, client.target, remote);
    notifyListeners();
  }
}
