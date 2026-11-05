import 'dart:convert';
import 'package:sqflite/sqflite.dart';
import '../models/order_draft.dart';
import '../services/session_scope.dart';
import 'database_helper.dart';

/// Separado del caché remoto: una sincronización nunca reemplaza estos borradores.
class OrderDraftsRepository {
  final DatabaseHelper helper;
  final Future<String?> Function() ownerProvider;
  final Future<Database> Function()? databaseProvider;
  OrderDraftsRepository(this.helper,
      {Future<String?> Function()? ownerProvider, this.databaseProvider})
      : ownerProvider = ownerProvider ?? SessionScope.current;
  Future<Database> get _database => databaseProvider?.call() ?? helper.database;
  Future<String> _owner() async {
    final owner = await ownerProvider();
    if (owner == null || owner.trim().isEmpty) {
      throw StateError('Vendedor no identificado.');
    }
    return owner;
  }

  Future<List<OrderDraft>> all() async {
    final owner = await _owner();
    final db = await _database;
    final rows = await db.query('order_drafts',
        where: 'owner_scope = ?',
        whereArgs: [owner],
        orderBy: 'updated_at DESC');
    return rows
        .map((r) => OrderDraft.fromJson(
            jsonDecode(r['payload'] as String) as Map<String, dynamic>))
        .toList();
  }

  Future<OrderDraft> save(OrderDraft draft) async {
    for (final job in draft.jobs) {
      job.validate();
    }
    if (draft.jobs.map((j) => j.id).toSet().length != draft.jobs.length) {
      throw ArgumentError('Trabajos duplicados.');
    }
    final owner = await _owner();
    final db = await _database;
    return db.transaction((txn) async {
      final previous = await txn.query('order_drafts',
          where: 'id = ? AND owner_scope = ?', whereArgs: [draft.id, owner]);
      final revision =
          previous.isEmpty ? 0 : previous.single['revision'] as int;
      if (revision != draft.revision) {
        throw StateError('Conflicto: reabrí el borrador antes de guardar.');
      }
      final saved = OrderDraft(
          id: draft.id,
          revision: revision + 1,
          client: draft.client,
          whatsapp: draft.whatsapp,
          notes: draft.notes,
          jobs: draft.jobs);
      final values = {
        'id': draft.id,
        'owner_scope': owner,
        'revision': saved.revision,
        'payload': jsonEncode(saved.toJson()),
        'updated_at': DateTime.now().toIso8601String()
      };
      if (previous.isEmpty) {
        await txn.insert('order_drafts', values,
            conflictAlgorithm: ConflictAlgorithm.abort);
      } else {
        await txn.update('order_drafts', values,
            where: 'id = ? AND owner_scope = ?', whereArgs: [draft.id, owner]);
      }
      return saved;
    });
  }
}
