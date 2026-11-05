import 'package:sqflite/sqflite.dart';
import '../models/order.dart';
import '../models/dashboard_metrics.dart';
import '../models/order_with_details.dart';
import '../models/order_status.dart';
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
  Future<void> upsertOrder(Map<String, dynamic> orderData,
      {Transaction? txn}) async {
    final executor = txn ?? await _dbHelper.database;
    final order = Order.fromMap(orderData);

    await executor.insert(
      'orders',
      order.toMap(),
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  /// Upsert multiple orders in a batch operation
  Future<void> upsertOrders(List<Map<String, dynamic>> ordersData,
      {Transaction? txn}) async {
    final executor = txn ?? await _dbHelper.database;
    final batch = executor.batch();

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

  /// Applies remote changes to the local cache.
  ///
  /// Cancelled orders remain in Studio for traceability, but they are removed
  /// from the phone together with their cached jobs.
  Future<void> applySyncedOrders(
    List<Map<String, dynamic>> ordersData, {
    Transaction? txn,
  }) async {
    final executor = txn ?? await _dbHelper.database;
    final batch = executor.batch();

    for (final orderData in ordersData) {
      final order = Order.fromMap(orderData);
      final status = (order.status ?? '').trim().toLowerCase();
      if (status == 'cancelado' || status == 'cancelled') {
        batch.delete('jobs', where: 'order_id = ?', whereArgs: [order.id]);
        batch.delete('orders', where: 'id = ?', whereArgs: [order.id]);
      } else {
        batch.insert(
          'orders',
          order.toMap(),
          conflictAlgorithm: ConflictAlgorithm.replace,
        );
      }
    }

    await batch.commit(noResult: true);
  }

  /// Removes only the phone's cached copy; it never mutates Studio.
  Future<void> deleteOrderLocally(String orderId, {Transaction? txn}) async {
    Future<void> remove(DatabaseExecutor executor) async {
      await executor.delete(
        'jobs',
        where: 'order_id = ?',
        whereArgs: [orderId],
      );
      await executor.delete(
        'orders',
        where: 'id = ?',
        whereArgs: [orderId],
      );
    }

    if (txn != null) {
      await remove(txn);
      return;
    }
    final db = await _dbHelper.database;
    await db.transaction(remove);
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
    final aliases = OrderStatus.databaseAliases(status);
    final placeholders = List.filled(aliases.length, '?').join(', ');
    final List<Map<String, dynamic>> maps = await db.rawQuery(
      '''SELECT * FROM orders
         WHERE LOWER(TRIM(status)) IN ($placeholders)
         ORDER BY updated_at DESC''',
      aliases,
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
    final todayStr =
        '${today.year}-${today.month.toString().padLeft(2, '0')}-${today.day.toString().padLeft(2, '0')}';

    // Query orders statistics
    final result = await db.rawQuery('''
      SELECT 
        COUNT(CASE WHEN DATE(order_date) = ? THEN 1 END) as orders_today,
        COUNT(CASE WHEN LOWER(TRIM(status)) IN
          ('production', 'producción', 'produccion', 'en producción', 'en produccion')
          THEN 1 END) as orders_production,
        COUNT(CASE WHEN LOWER(TRIM(status)) IN
          ('pending', 'pendiente', 'new', 'nuevo')
          THEN 1 END) as orders_pending,
        COUNT(CASE WHEN LOWER(TRIM(status)) IN
          ('completed', 'complete', 'completado', 'finalizado')
          THEN 1 END) as orders_completed
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
    final dateStr =
        '${date.year}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';

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
      final aliases = OrderStatus.databaseAliases(status);
      final placeholders = List.filled(aliases.length, '?').join(', ');
      whereClause = 'LOWER(TRIM(status)) IN ($placeholders)';
      whereArgs.addAll(aliases);
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

  /// Search and filter orders with related data
  ///
  /// Optimized to avoid N+1 query pattern using batch queries.
  ///
  /// [searchQuery] - Search in order number, client name, whatsapp, material, and job titles
  /// [status] - Filter by order status
  /// [priority] - Filter by print priority
  /// [showArchived] - Include archived orders (default: false)
  /// [deliveryDateFrom] - Filter orders with delivery date >= this date
  /// [deliveryDateTo] - Filter orders with delivery date <= this date
  /// [sortBy] - Sort field: 'delivery_date', 'priority', 'order_date', 'client'
  /// [sortDescending] - Sort direction (default: false for ascending)
  /// [limit] - Maximum number of orders to return (default: 100)
  Future<List<OrderWithDetails>> searchOrders({
    String? searchQuery,
    String? status,
    String? priority,
    bool showArchived = false,
    String? deliveryDateFrom,
    String? deliveryDateTo,
    String sortBy = 'order_date',
    bool sortDescending = true,
    int limit = 100,
  }) async {
    final db = await _dbHelper.database;

    // Build WHERE clause
    final List<String> whereClauses = [];
    final List<dynamic> whereArgs = [];

    // Archived filter
    if (!showArchived) {
      whereClauses.add('(o.is_archived IS NULL OR o.is_archived = 0)');
    }

    // Status filter
    if (status != null) {
      final aliases = OrderStatus.databaseAliases(status);
      final placeholders = List.filled(aliases.length, '?').join(', ');
      whereClauses.add('LOWER(TRIM(o.status)) IN ($placeholders)');
      whereArgs.addAll(aliases);
    }

    // Priority filter
    if (priority != null) {
      final aliases = OrderPriority.databaseAliases(priority);
      final placeholders = List.filled(aliases.length, '?').join(', ');
      whereClauses.add(
        'LOWER(TRIM(CAST(o.print_priority AS TEXT))) IN ($placeholders)',
      );
      whereArgs.addAll(aliases);
    }

    // Delivery date range filter
    if (deliveryDateFrom != null) {
      whereClauses.add('o.delivery_date >= ?');
      whereArgs.add(deliveryDateFrom);
    }
    if (deliveryDateTo != null) {
      whereClauses.add('o.delivery_date <= ?');
      whereArgs.add(deliveryDateTo);
    }

    // Search query filter (searches in order, client, and jobs)
    if (searchQuery != null && searchQuery.isNotEmpty) {
      whereClauses.add('''
        (o.order_number LIKE ? OR 
         o.client LIKE ? OR 
         o.whatsapp LIKE ? OR 
         o.material LIKE ? OR 
         o.id IN (SELECT DISTINCT order_id FROM jobs WHERE title LIKE ? OR material LIKE ?))
      ''');
      final searchPattern = '%$searchQuery%';
      whereArgs.addAll([
        searchPattern,
        searchPattern,
        searchPattern,
        searchPattern,
        searchPattern,
        searchPattern
      ]);
    }

    final whereClause = whereClauses.isEmpty ? '' : whereClauses.join(' AND ');

    // Build ORDER BY clause
    String orderByClause;
    final sortDir = sortDescending ? 'DESC' : 'ASC';

    switch (sortBy) {
      case 'delivery_date':
        orderByClause = 'o.delivery_date $sortDir, o.order_date DESC';
        break;
      case 'priority':
        // Sort by priority: high > medium > low, then by order_date
        orderByClause = '''
          CASE LOWER(TRIM(CAST(o.print_priority AS TEXT)))
            WHEN '4' THEN 4
            WHEN 'urgent' THEN 4
            WHEN 'urgente' THEN 4
            WHEN '3' THEN 3
            WHEN 'high' THEN 3
            WHEN 'alta' THEN 3
            WHEN '2' THEN 2
            WHEN 'medium' THEN 2
            WHEN 'media' THEN 2
            WHEN '1' THEN 1
            WHEN 'low' THEN 1
            WHEN 'baja' THEN 1
            ELSE 0
          END $sortDir,
          o.order_date DESC
        ''';
        break;
      case 'client':
        orderByClause = 'o.client $sortDir, o.order_date DESC';
        break;
      case 'order_date':
      default:
        orderByClause = 'o.order_date $sortDir, o.updated_at DESC';
        break;
    }

    // 1. Query orders with filters
    final orderMaps = await db.rawQuery('''
      SELECT DISTINCT o.* 
      FROM orders o
      ${whereClause.isEmpty ? '' : 'WHERE $whereClause'}
      ORDER BY $orderByClause
      LIMIT ?
    ''', [...whereArgs, limit]);

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
        'SELECT * FROM jobs WHERE order_id IN ($placeholders) ORDER BY sort_order ASC, created_at ASC',
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
