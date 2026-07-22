import 'package:sqflite/sqflite.dart';
import '../models/sync_state.dart';
import 'database_helper.dart';

/// Repository for managing sync state persistence
class SyncStateRepository {
  final DatabaseHelper _dbHelper;

  SyncStateRepository(this._dbHelper);

  /// Get the current sync state
  Future<SyncState> getSyncState() async {
    final db = await _dbHelper.database;
    final List<Map<String, dynamic>> maps = await db.query(
      'sync_state',
      where: 'id = ?',
      whereArgs: [1],
    );

    if (maps.isEmpty) {
      return SyncState();
    }

    return SyncState.fromMap(maps.first);
  }

  /// Get the current next cursor (null if no incomplete sync)
  Future<String?> getCurrentNextCursor() async {
    final state = await getSyncState();
    return state.currentNextCursor;
  }

  /// Set the current next cursor
  Future<void> setCurrentNextCursor(String? cursor, {Transaction? txn}) async {
    final executor = txn ?? await _dbHelper.database;
    await executor.update(
      'sync_state',
      {'current_next_cursor': cursor},
      where: 'id = ?',
      whereArgs: [1],
    );
  }

  /// Clear the current next cursor (sync completed successfully)
  Future<void> clearCurrentNextCursor() async {
    await setCurrentNextCursor(null);
  }

  /// Update last completed snapshot
  Future<void> setLastCompletedSnapshot(String snapshot) async {
    final db = await _dbHelper.database;
    await db.update(
      'sync_state',
      {
        'last_completed_snapshot': snapshot,
        'last_sync_at': DateTime.now().toIso8601String(),
      },
      where: 'id = ?',
      whereArgs: [1],
    );
  }

  /// Set sync error
  Future<void> setLastSyncError(String? error) async {
    final db = await _dbHelper.database;
    await db.update(
      'sync_state',
      {'last_sync_error': error},
      where: 'id = ?',
      whereArgs: [1],
    );
  }

  /// Clear sync error
  Future<void> clearLastSyncError() async {
    await setLastSyncError(null);
  }

  /// Check if there's an incomplete sync
  Future<bool> hasIncompleteSync() async {
    final cursor = await getCurrentNextCursor();
    return cursor != null;
  }

  /// Complete a full sync (clear cursor, update snapshot)
  Future<void> completeSync(String snapshot, {Transaction? txn}) async {
    final executor = txn ?? await _dbHelper.database;
    await executor.update(
      'sync_state',
      {
        'last_completed_snapshot': snapshot,
        'current_next_cursor': null,
        'last_sync_at': DateTime.now().toIso8601String(),
        'last_sync_error': null,
      },
      where: 'id = ?',
      whereArgs: [1],
    );
  }
}
