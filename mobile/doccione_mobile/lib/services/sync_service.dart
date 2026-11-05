import '../database/database_helper.dart';
import '../database/offline_catalog_repository.dart';
import '../database/sync_state_repository.dart';
import '../models/sync_result.dart';
import 'sync_api_client.dart';
import 'handlers/sync_entity_handler.dart';

/// Service for managing synchronization with backend
class SyncService {
  final DatabaseHelper _dbHelper;
  final SyncStateRepository _syncStateRepo;
  final SyncApiClient _apiClient;
  final OfflineCatalogRepository _offlineCatalogRepo;
  final Map<String, SyncEntityHandler> _handlers = {};

  SyncService({
    required DatabaseHelper dbHelper,
    required SyncStateRepository syncStateRepo,
    required SyncApiClient apiClient,
  })  : _dbHelper = dbHelper,
        _syncStateRepo = syncStateRepo,
        _apiClient = apiClient,
        _offlineCatalogRepo = OfflineCatalogRepository(dbHelper);

  /// Register a handler for a specific entity type
  void registerHandler(String entityType, SyncEntityHandler handler) {
    _handlers[entityType] = handler;
  }

  void close() {
    _apiClient.close();
  }

  /// Check if there's an incomplete synchronization
  Future<bool> hasIncompleteSync() async {
    return await _syncStateRepo.hasIncompleteSync();
  }

  /// Start a new synchronization from scratch
  Future<SyncResult> startSync({int limit = 100}) async {
    final totalStopwatch = Stopwatch()..start();

    try {
      // Clear any existing incomplete sync
      await _syncStateRepo.clearCurrentNextCursor();
      await _syncStateRepo.clearLastSyncError();

      // Perform first sync page
      return await _performSyncPage(
        cursor: null,
        limit: limit,
        totalStopwatch: totalStopwatch,
      );
    } catch (e) {
      totalStopwatch.stop();
      final errorMessage = e.toString();
      await _syncStateRepo.setLastSyncError(errorMessage);

      return SyncResult.error(
        error: errorMessage,
        totalDuration: totalStopwatch.elapsed,
      );
    }
  }

  /// Continue an incomplete synchronization
  Future<SyncResult> continueSync({int limit = 100}) async {
    final totalStopwatch = Stopwatch()..start();

    try {
      final cursor = await _syncStateRepo.getCurrentNextCursor();

      if (cursor == null) {
        totalStopwatch.stop();
        return SyncResult.error(
          error: 'No incomplete sync to continue',
          totalDuration: totalStopwatch.elapsed,
        );
      }

      return await _performSyncPage(
        cursor: cursor,
        limit: limit,
        totalStopwatch: totalStopwatch,
      );
    } catch (e) {
      totalStopwatch.stop();
      final errorMessage = e.toString();
      await _syncStateRepo.setLastSyncError(errorMessage);

      return SyncResult.error(
        error: errorMessage,
        totalDuration: totalStopwatch.elapsed,
      );
    }
  }

  /// Perform a single page of synchronization
  Future<SyncResult> _performSyncPage({
    required String? cursor,
    required int limit,
    required Stopwatch totalStopwatch,
  }) async {
    // HTTP request
    final httpStopwatch = Stopwatch()..start();
    final response = await _apiClient.syncPull(
      cursor: cursor,
      limit: limit,
    );
    httpStopwatch.stop();

    // Parse response — backend contract:
    // { snapshot_until, complete, next_cursor, entities: { X: { items, has_more } } }
    final parseStopwatch = Stopwatch()..start();
    final snapshotId = response['snapshot_until'] as String;
    final scopeId = response['scope_id'] as String?;
    final nextCursor = response['next_cursor'] as String?;
    final complete = response['complete'] as bool;
    final entities = response['entities'] as Map<String, dynamic>;

    final jobs = _extractEntityItems(entities, 'jobs');
    final orders = _extractEntityItems(entities, 'orders');
    final clients = _extractEntityItems(entities, 'clients');
    parseStopwatch.stop();

    // Database transaction
    final dbStopwatch = Stopwatch()..start();
    final db = await _dbHelper.database;

    await db.transaction((txn) async {
      if (scopeId != null) {
        final currentState = await txn.query(
          'sync_state',
          columns: ['scope_id'],
          where: 'id = ?',
          whereArgs: [1],
          limit: 1,
        );
        final currentScope = currentState.isEmpty
            ? null
            : currentState.first['scope_id'] as String?;
        if (currentScope != scopeId) {
          // Evita que queden visibles pedidos sincronizados para la empresa o
          // para otro vendedor antes de que existiera el aislamiento.
          await txn.delete('jobs');
          await txn.delete('orders');
          await txn.delete('clients');
          await _syncStateRepo.setScopeId(scopeId, txn: txn);
        }
      }

      // Process each entity type within transaction, using the txn handle
      if (_handlers.containsKey('jobs') && jobs.isNotEmpty) {
        await _handlers['jobs']!.process(jobs, txn: txn);
      }

      if (_handlers.containsKey('orders') && orders.isNotEmpty) {
        await _handlers['orders']!.process(orders, txn: txn);
      }

      if (_handlers.containsKey('clients') && clients.isNotEmpty) {
        await _handlers['clients']!.process(clients, txn: txn);
      }

      // Update sync state within the same transaction
      if (complete) {
        await _syncStateRepo.completeSync(snapshotId, txn: txn);
      } else if (nextCursor != null) {
        await _syncStateRepo.setCurrentNextCursor(nextCursor, txn: txn);
      }
    });
    dbStopwatch.stop();

    if (complete) {
      try {
        await _refreshCatalogDesigns();
      } catch (_) {
        // No bloquear la sincronización principal si la biblioteca de diseños falla.
      }
    }

    totalStopwatch.stop();

    return SyncResult.success(
      jobsUpdated: jobs.length,
      ordersUpdated: orders.length,
      clientsUpdated: clients.length,
      completed: complete,
      httpDuration: httpStopwatch.elapsed,
      parseDuration: parseStopwatch.elapsed,
      databaseDuration: dbStopwatch.elapsed,
      totalDuration: totalStopwatch.elapsed,
      nextCursor: nextCursor,
    );
  }

  /// Perform a complete synchronization (all pages)
  /// This will continue fetching pages until sync is complete
  Future<SyncResult> syncAll({
    int limit = 100,
    Function(SyncResult)? onPageComplete,
  }) async {
    final totalStopwatch = Stopwatch()..start();

    int totalJobs = 0;
    int totalOrders = 0;
    int totalClients = 0;
    Duration totalHttpDuration = Duration.zero;
    Duration totalParseDuration = Duration.zero;
    Duration totalDatabaseDuration = Duration.zero;

    try {
      // Start sync
      var result = await startSync(limit: limit);

      if (result.hasError) {
        return result;
      }

      totalJobs += result.jobsUpdated;
      totalOrders += result.ordersUpdated;
      totalClients += result.clientsUpdated;
      totalHttpDuration += result.httpDuration;
      totalParseDuration += result.parseDuration;
      totalDatabaseDuration += result.databaseDuration;

      onPageComplete?.call(result);

      // Continue until complete
      while (!result.completed && result.nextCursor != null) {
        result = await continueSync(limit: limit);

        if (result.hasError) {
          return result;
        }

        totalJobs += result.jobsUpdated;
        totalOrders += result.ordersUpdated;
        totalClients += result.clientsUpdated;
        totalHttpDuration += result.httpDuration;
        totalParseDuration += result.parseDuration;
        totalDatabaseDuration += result.databaseDuration;

        onPageComplete?.call(result);
      }

      totalStopwatch.stop();

      return SyncResult.success(
        jobsUpdated: totalJobs,
        ordersUpdated: totalOrders,
        clientsUpdated: totalClients,
        completed: true,
        httpDuration: totalHttpDuration,
        parseDuration: totalParseDuration,
        databaseDuration: totalDatabaseDuration,
        totalDuration: totalStopwatch.elapsed,
      );
    } catch (e) {
      totalStopwatch.stop();
      final errorMessage = e.toString();
      await _syncStateRepo.setLastSyncError(errorMessage);

      return SyncResult.error(
        error: errorMessage,
        totalDuration: totalStopwatch.elapsed,
      );
    }
  }

  Future<void> _refreshCatalogDesigns() async {
    final designs = await _apiClient.getCatalogDesigns(limit: 500);
    await _offlineCatalogRepo.saveDesigns(designs);
  }

  /// Extract items from entities[type].items and coerce int IDs to String.
  List<Map<String, dynamic>> _extractEntityItems(
      Map<String, dynamic> entities, String type) {
    final entity = entities[type] as Map<String, dynamic>?;
    if (entity == null) return [];
    final items = entity['items'] as List<dynamic>? ?? [];
    return items
        .map((item) => _coerceIdTypes(item as Map<String, dynamic>))
        .toList();
  }

  /// Convert int ID fields to String for model compatibility.
  Map<String, dynamic> _coerceIdTypes(Map<String, dynamic> item) {
    final map = Map<String, dynamic>.from(item);
    for (final key in ['id', 'order_id', 'client_id', 'job_id']) {
      if (map[key] is int) {
        map[key] = map[key].toString();
      }
    }
    return map;
  }
}
