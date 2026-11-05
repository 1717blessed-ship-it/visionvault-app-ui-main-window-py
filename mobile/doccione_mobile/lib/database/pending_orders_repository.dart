import 'dart:convert';
import 'package:sqflite/sqflite.dart';
import 'database_helper.dart';

class PendingOrder {
  final String id, type, payload, ownerScope;
  final List<String> imagePaths;
  const PendingOrder(
      {required this.id,
      required this.type,
      required this.payload,
      required this.imagePaths,
      required this.ownerScope});
}

class PendingOrdersRepository {
  final DatabaseHelper _dbHelper;
  PendingOrdersRepository(this._dbHelper);

  Future<void> enqueue(PendingOrder order) async {
    final db = await _dbHelper.database;
    await db.insert(
        'pending_orders',
        {
          'id': order.id,
          'type': order.type,
          'payload': order.payload,
          'image_paths': jsonEncode(order.imagePaths),
          'owner_scope': order.ownerScope,
          'created_at': DateTime.now().toUtc().toIso8601String(),
        },
        conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<List<PendingOrder>> all({required String ownerScope}) async {
    final db = await _dbHelper.database;
    final rows = await db.query('pending_orders',
        where: "status = 'pending' AND owner_scope = ?",
        whereArgs: [ownerScope],
        orderBy: 'created_at ASC');
    return rows
        .map((row) => PendingOrder(
              id: row['id'] as String,
              type: row['type'] as String,
              payload: row['payload'] as String,
              ownerScope: row['owner_scope'] as String,
              imagePaths: (jsonDecode(row['image_paths'] as String) as List)
                  .cast<String>(),
            ))
        .toList();
  }

  Future<void> markUploaded(String id, int orderId) async =>
      (await _dbHelper.database).update(
          'pending_orders',
          {
            'status': 'uploaded',
            'remote_order_id': orderId,
            'completed_at': DateTime.now().toUtc().toIso8601String(),
            'last_error': null
          },
          where: 'id = ?',
          whereArgs: [id]);
  Future<void> recordFailure(String id, Object error) async =>
      (await _dbHelper.database).rawUpdate(
          'UPDATE pending_orders SET attempts = attempts + 1, last_error = ? WHERE id = ?',
          [error.toString(), id]);
  Future<int> count({required String ownerScope}) async =>
      Sqflite.firstIntValue(await (await _dbHelper.database).rawQuery(
          "SELECT COUNT(*) FROM pending_orders WHERE status = 'pending' AND owner_scope = ?",
          [ownerScope])) ??
      0;
}
