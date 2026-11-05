import 'package:sqflite/sqflite.dart';

/// Abstract handler for synchronizing a specific entity type
abstract class SyncEntityHandler {
  /// Process a list of entity items from sync response.
  /// When [txn] is provided, all DB operations must use it directly
  /// to stay within the caller's transaction.
  Future<void> process(List<Map<String, dynamic>> items, {Transaction? txn});

  /// Get the name of the entity type this handler manages
  String get entityType;
}
