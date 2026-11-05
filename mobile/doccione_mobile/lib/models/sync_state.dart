class SyncState {
  final String? lastCompletedSnapshot;
  final String? currentNextCursor;
  final String? scopeId;
  final String? lastSyncAt;
  final String? lastSyncError;

  SyncState({
    this.lastCompletedSnapshot,
    this.currentNextCursor,
    this.scopeId,
    this.lastSyncAt,
    this.lastSyncError,
  });

  bool get isIncomplete => currentNextCursor != null;

  Map<String, dynamic> toMap() {
    return {
      'last_completed_snapshot': lastCompletedSnapshot,
      'current_next_cursor': currentNextCursor,
      'scope_id': scopeId,
      'last_sync_at': lastSyncAt,
      'last_sync_error': lastSyncError,
    };
  }

  factory SyncState.fromMap(Map<String, dynamic> map) {
    return SyncState(
      lastCompletedSnapshot: map['last_completed_snapshot'] as String?,
      currentNextCursor: map['current_next_cursor'] as String?,
      scopeId: map['scope_id'] as String?,
      lastSyncAt: map['last_sync_at'] as String?,
      lastSyncError: map['last_sync_error'] as String?,
    );
  }
}
