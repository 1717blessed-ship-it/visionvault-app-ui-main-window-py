import 'dart:convert';
import 'package:sqflite/sqflite.dart';
import '../database/database_helper.dart';
import '../database/sync_state_repository.dart';
import '../models/sync_result.dart';
import 'sync_api_client.dart';
import 'handlers/sync_entity_handler.dart';

/// Service for managing synchronization with backend
class SyncService {
  final DatabaseHelper _dbHelper;
  final SyncStateRepository _syncStateRepo;
  final SyncApiClient _apiClient;
  final Map<String, SyncEntityHandler> _handlers = {};

  SyncService({
    required DatabaseHelper dbHelper,
    required SyncStateRepository syncStateRepo,
    required SyncApiClient apiClient,
  })  : _dbHelper = dbHelper,
        _syncStateRepo = syncStateRepo,
        _apiClient = apiClient;

  /// Register a handler for a specific entity type
  void registerHandler(String entityType, SyncEntityHandler handler) {
    _handlers[entityType] = handler;
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

    // Parse response
    final parseStopwatch = Stopwatch()..start();
    final snapshotId = response['snapshot_id'] as String;
    final nextCursor = response['next_cursor'] as String?;
    final complete = response['complete'] as bool;
    final data = response['data'] as Map<String, dynamic>;

    final jobs = (data['jobs'] as List<dynamic>?)
            ?.cast<Map<String, dynamic>>() ??
        [];
    final orders = (data['orders'] as List<dynamic>?)
            ?.cast<Map<String, dynamic>>() ??
        [];
    final clients = (data['clients'] as List<dynamic>?)
            ?.cast<Map<String, dynamic>>() ??
        [];
    parseStopwatch.stop();

    // Database transaction
    final dbStopwatch = Stopwatch()..start();
    final db = await _dbHelper.database;

    await db.transaction((txn) async {
      // Create temporary database helper for transaction
      final txnDbHelper = _TransactionDatabaseHelper(txn);

      // Process each entity type within transaction
      if (_handlers.containsKey('jobs') && jobs.isNotEmpty) {
        await _handlers['jobs']!.process(jobs);
      }

      if (_handlers.containsKey('orders') && orders.isNotEmpty) {
        await _handlers['orders']!.process(orders);
      }

      if (_handlers.containsKey('clients') && clients.isNotEmpty) {
        await _handlers['clients']!.process(clients);
      }

      // Update sync state within transaction
      if (complete) {
        // Sync completed - clear cursor and update snapshot
        await _syncStateRepo.completeSync(snapshotId);
      } else if (nextCursor != null) {
        // More pages to sync - save cursor
        await _syncStateRepo.setCurrentNextCursor(nextCursor);
      }
    });
    dbStopwatch.stop();

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
}

/// Helper class to wrap a transaction for DatabaseHelper interface
class _TransactionDatabaseHelper {
  final Transaction _transaction;

  _TransactionDatabaseHelper(this._transaction);

  Transaction get transaction => _transaction;
}
