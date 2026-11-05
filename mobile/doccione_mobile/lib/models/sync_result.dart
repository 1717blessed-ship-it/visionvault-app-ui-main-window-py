/// Result of a synchronization operation with performance metrics
class SyncResult {
  final int jobsUpdated;
  final int ordersUpdated;
  final int clientsUpdated;
  final bool completed;

  // Performance metrics
  final Duration httpDuration;
  final Duration parseDuration;
  final Duration databaseDuration;
  final Duration totalDuration;

  final String? error;
  final String? nextCursor;

  SyncResult({
    required this.jobsUpdated,
    required this.ordersUpdated,
    required this.clientsUpdated,
    required this.completed,
    required this.httpDuration,
    required this.parseDuration,
    required this.databaseDuration,
    required this.totalDuration,
    this.error,
    this.nextCursor,
  });

  /// Create a result for a successful sync
  factory SyncResult.success({
    required int jobsUpdated,
    required int ordersUpdated,
    required int clientsUpdated,
    required bool completed,
    required Duration httpDuration,
    required Duration parseDuration,
    required Duration databaseDuration,
    required Duration totalDuration,
    String? nextCursor,
  }) {
    return SyncResult(
      jobsUpdated: jobsUpdated,
      ordersUpdated: ordersUpdated,
      clientsUpdated: clientsUpdated,
      completed: completed,
      httpDuration: httpDuration,
      parseDuration: parseDuration,
      databaseDuration: databaseDuration,
      totalDuration: totalDuration,
      nextCursor: nextCursor,
    );
  }

  /// Create a result for a failed sync
  factory SyncResult.error({
    required String error,
    required Duration totalDuration,
  }) {
    return SyncResult(
      jobsUpdated: 0,
      ordersUpdated: 0,
      clientsUpdated: 0,
      completed: false,
      httpDuration: Duration.zero,
      parseDuration: Duration.zero,
      databaseDuration: Duration.zero,
      totalDuration: totalDuration,
      error: error,
    );
  }

  bool get hasError => error != null;
  bool get isSuccess => error == null;

  @override
  String toString() {
    if (hasError) {
      return 'SyncResult.error(error: $error, duration: ${totalDuration.inMilliseconds}ms)';
    }
    return 'SyncResult.success(jobs: $jobsUpdated, orders: $ordersUpdated, clients: $clientsUpdated, '
        'completed: $completed, http: ${httpDuration.inMilliseconds}ms, '
        'parse: ${parseDuration.inMilliseconds}ms, db: ${databaseDuration.inMilliseconds}ms, '
        'total: ${totalDuration.inMilliseconds}ms)';
  }
}
