/// Dashboard metrics model for displaying sync statistics
class DashboardMetrics {
  final int ordersToday;
  final int ordersInProduction;
  final int ordersPending;
  final int ordersCompleted;
  final int totalJobs;
  final int totalClients;
  final DateTime? lastSyncAt;
  final String? lastSyncError;

  DashboardMetrics({
    required this.ordersToday,
    required this.ordersInProduction,
    required this.ordersPending,
    required this.ordersCompleted,
    required this.totalJobs,
    required this.totalClients,
    this.lastSyncAt,
    this.lastSyncError,
  });

  bool get hasError => lastSyncError != null;
  bool get hasBeenSynced => lastSyncAt != null;

  String get lastSyncFormatted {
    if (lastSyncAt == null) return 'Nunca';
    
    final now = DateTime.now();
    final difference = now.difference(lastSyncAt!);
    
    if (difference.inMinutes < 1) {
      return 'Hace unos segundos';
    } else if (difference.inMinutes < 60) {
      return 'Hace ${difference.inMinutes} min';
    } else if (difference.inHours < 24) {
      return 'Hace ${difference.inHours} h';
    } else {
      return 'Hace ${difference.inDays} días';
    }
  }

  factory DashboardMetrics.empty() {
    return DashboardMetrics(
      ordersToday: 0,
      ordersInProduction: 0,
      ordersPending: 0,
      ordersCompleted: 0,
      totalJobs: 0,
      totalClients: 0,
    );
  }
}
