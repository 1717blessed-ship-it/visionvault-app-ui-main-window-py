import 'package:sqflite/sqflite.dart';
import '../models/order.dart';
import '../models/dashboard_metrics.dart';
import '../models/order_with_details.dart';
import '../models/client.dart';
import '../models/job.dart';
import 'database_helper.dart';
import 'sync_state_repository.dart';
import 'jobs_repository.dart';
import 'clients_repository.dart';

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

  /// Get dashboard metrics with aggregated statistics
  Future<DashboardMetrics> getDashboardMetrics(
    SyncStateRepository syncStateRepo,
    JobsRepository jobsRepo,
    ClientsRepository clientsRepo,
  ) async {
    final db = await _dbHelper.database;
    
    // Get today's date in YYYY-MM-DD format
    final today = DateTime.now();
    final todayStr = '${today.year}-${today.month.toString().padLeft(2, '0')}-${today.day.toString().padLeft(2, '0')}';
    
    // Query orders statistics
    final result = await db.rawQuery('''
      SELECT 
        COUNT(CASE WHEN DATE(order_date) = ? THEN 1 END) as orders_today,
        COUNT(CASE WHEN status = 'production' THEN 1 END) as orders_production,
        COUNT(CASE WHEN status = 'pending' THEN 1 END) as orders_pending,
        COUNT(CASE WHEN status = 'completed' THEN 1 END) as orders_completed
      FROM orders
    ''', [todayStr]);
    
    // Get counts from other repositories
    final totalJobs = await jobsRepo.countJobs();
    final totalClients = await clientsRepo.countClients();
    
    // Get sync state
    final syncState = await syncStateRepo.getSyncState();
    
    final map = result.first;
    return DashboardMetrics(
      ordersToday: (map['orders_today'] as int?) ?? 0,
      ordersInProduction: (map['orders_production'] as int?) ?? 0,
      ordersPending: (map['orders_pending'] as int?) ?? 0,
      ordersCompleted: (map['orders_completed'] as int?) ?? 0,
      totalJobs: totalJobs,
      totalClients: totalClients,
      lastSyncAt: syncState.lastSyncAt != null 
          ? DateTime.tryParse(syncState.lastSyncAt!)
          : null,
      lastSyncError: syncState.lastSyncError,
    );
  }

  /// Get orders by date
  Future<List<Order>> getOrdersByDate(DateTime date) async {
    final db = await _dbHelper.database;
    final dateStr = '${date.year}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';
    
    final List<Map<String, dynamic>> maps = await db.query(
      'orders',
      where: 'DATE(order_date) = ?',
      whereArgs: [dateStr],
      orderBy: 'order_date DESC',
    );

    return maps.map((map) => Order.fromMap(map)).toList();
  }

  /// Get orders with related client and jobs data
  /// 
  /// [status] - Optional filter by order status
  /// [limit] - Maximum number of orders to return (default 50)
  Future<List<OrderWithDetails>> getOrdersWithDetails({
    String? status,
    int limit = 50,
  }) async {
    final db = await _dbHelper.database;
    
    // Build query with optional status filter
    String whereClause = '';
    List<dynamic> whereArgs = [];
    
    if (status != null) {
      whereClause = 'o.status = ?';
      whereArgs.add(status);
    }
    
    // Query orders with optional filter
    final orderMaps = await db.query(
      'orders',
      where: whereClause.isEmpty ? null : whereClause,
      whereArgs: whereArgs.isEmpty ? null : whereArgs,
      orderBy: 'order_date DESC, updated_at DESC',
      limit: limit,
    );
    
    final List<OrderWithDetails> result = [];
    
    for (final orderMap in orderMaps) {
      final order = Order.fromMap(orderMap);
      
      // Get client if clientId exists
      Client? client;
      if (order.clientId != null) {
        final clientMaps = await db.query(
          'clients',
          where: 'id = ?',
          whereArgs: [order.clientId],
          limit: 1,
        );
        if (clientMaps.isNotEmpty) {
          client = Client.fromMap(clientMaps.first);
        }
      }
      
      // Get jobs for this order
      final jobMaps = await db.query(
        'jobs',
        where: 'order_id = ?',
        whereArgs: [order.id],
        orderBy: 'created_at ASC',
      );
      final jobs = jobMaps.map((map) => Job.fromMap(map)).toList();
      
      result.add(OrderWithDetails(
        order: order,
        client: client,
        jobs: jobs,
      ));
    }
    
    return result;
  }
}
