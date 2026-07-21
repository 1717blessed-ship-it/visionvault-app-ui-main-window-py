/// Abstract handler for synchronizing a specific entity type
abstract class SyncEntityHandler {
  /// Process a list of entity items from sync response
  /// This method should upsert the items into the database
  Future<void> process(List<Map<String, dynamic>> items);
  
  /// Get the name of the entity type this handler manages
  String get entityType;
}
