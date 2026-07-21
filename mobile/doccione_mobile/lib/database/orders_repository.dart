import 'package:sqflite/sqflite.dart';
import '../models/order.dart';
import 'database_helper.dart';

/// Repository for managing orders persistence with upsert support
class OrdersRepository {
  final DatabaseHelper _dbHelper;

  OrdersRepository(this._dbHelper);

  /// Upsert a single order (insert or update if exists)
  Future<void> upsertOrder(Map<String, dynamic> orderData) async {
    final db = await _dbHelper.database;
    final order = Order.fromMap(orderData);
    
    await db.insert(
      'orders',
      order.toMap(),
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  /// Upsert multiple orders in a batch operation
  Future<void> upsertOrders(List<Map<String, dynamic>> ordersData) async {
    final db = await _dbHelper.database;
    final batch = db.batch();

    for (final orderData in ordersData) {
      final order = Order.fromMap(orderData);
      batch.insert(
        'orders',
        order.toMap(),
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
    }

    await batch.commit(noResult: true);
  }

  /// Get all orders
  Future<List<Order>> getAllOrders() async {
    final db = await _dbHelper.database;
    final List<Map<String, dynamic>> maps = await db.query(
      'orders',
      orderBy: 'updated_at DESC',
    );

    return maps.map((map) => Order.fromMap(map)).toList();
  }

  /// Get order by ID
  Future<Order?> getOrderById(String id) async {
    final db = await _dbHelper.database;
    final List<Map<String, dynamic>> maps = await db.query(
      'orders',
      where: 'id = ?',
      whereArgs: [id],
    );

    if (maps.isEmpty) return null;
    return Order.fromMap(maps.first);
  }

  /// Get orders by status
  Future<List<Order>> getOrdersByStatus(String status) async {
    final db = await _dbHelper.database;
    final List<Map<String, dynamic>> maps = await db.query(
      'orders',
      where: 'status = ?',
      whereArgs: [status],
      orderBy: 'updated_at DESC',
    );

    return maps.map((map) => Order.fromMap(map)).toList();
  }

  /// Get orders by job ID
  Future<List<Order>> getOrdersByJobId(String jobId) async {
    final db = await _dbHelper.database;
    final List<Map<String, dynamic>> maps = await db.query(
      'orders',
      where: 'job_id = ?',
      whereArgs: [jobId],
      orderBy: 'updated_at DESC',
    );

    return maps.map((map) => Order.fromMap(map)).toList();
  }

  /// Get orders by client ID
  Future<List<Order>> getOrdersByClientId(String clientId) async {
    final db = await _dbHelper.database;
    final List<Map<String, dynamic>> maps = await db.query(
      'orders',
      where: 'client_id = ?',
      whereArgs: [clientId],
      orderBy: 'updated_at DESC',
    );

    return maps.map((map) => Order.fromMap(map)).toList();
  }

  /// Count total orders
  Future<int> countOrders() async {
    final db = await _dbHelper.database;
    final result = await db.rawQuery('SELECT COUNT(*) as count FROM orders');
    return Sqflite.firstIntValue(result) ?? 0;
  }

  /// Clear all orders (use with caution)
  Future<void> clearOrders() async {
    final db = await _dbHelper.database;
    await db.delete('orders');
  }
}
