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
  /// Optimized to avoid N+1 query pattern:
  /// - 1 query for orders
  /// - 1 batch query for all clients (WHERE IN)
  /// - 1 batch query for all jobs (WHERE IN)
  /// 
  /// [status] - Optional filter by order status
  /// [limit] - Maximum number of orders to return (default 50)
  Future<List<OrderWithDetails>> getOrdersWithDetails({
    String? status,
    int limit = 50,
  }) async {
    final db = await _dbHelper.database;
    
    // 1. Query orders with optional status filter
    String whereClause = '';
    List<dynamic> whereArgs = [];
    
    if (status != null) {
      whereClause = 'status = ?';
      whereArgs.add(status);
    }
    
    final orderMaps = await db.query(
      'orders',
      where: whereClause.isEmpty ? null : whereClause,
      whereArgs: whereArgs.isEmpty ? null : whereArgs,
      orderBy: 'order_date DESC, updated_at DESC',
      limit: limit,
    );
    
    if (orderMaps.isEmpty) {
      return [];
    }
    
    final orders = orderMaps.map((map) => Order.fromMap(map)).toList();
    
    // 2. Batch query all clients (WHERE IN)
    final clientIds = orders
        .where((o) => o.clientId != null)
        .map((o) => o.clientId!)
        .toSet()
        .toList();
    
    final Map<String, Client> clientsMap = {};
    
    if (clientIds.isNotEmpty) {
      final placeholders = clientIds.map((_) => '?').join(',');
      final clientMaps = await db.rawQuery(
        'SELECT * FROM clients WHERE id IN ($placeholders)',
        clientIds,
      );
      
      for (final clientMap in clientMaps) {
        final client = Client.fromMap(clientMap);
        clientsMap[client.id] = client;
      }
    }
    
    // 3. Batch query all jobs (WHERE IN)
    final orderIds = orders.map((o) => o.id).toList();
    
    final Map<String, List<Job>> jobsMap = {};
    
    if (orderIds.isNotEmpty) {
      final placeholders = orderIds.map((_) => '?').join(',');
      final jobMaps = await db.rawQuery(
        'SELECT * FROM jobs WHERE order_id IN ($placeholders) ORDER BY created_at ASC',
        orderIds,
      );
      
      for (final jobMap in jobMaps) {
        final job = Job.fromMap(jobMap);
        final orderId = job.orderId;
        if (orderId != null) {
          jobsMap.putIfAbsent(orderId, () => []).add(job);
        }
      }
    }
    
    // 4. Assemble results
    return orders.map((order) {
      return OrderWithDetails(
        order: order,
        client: order.clientId != null ? clientsMap[order.clientId] : null,
        jobs: jobsMap[order.id] ?? [],
      );
    }).toList();
  }
}
