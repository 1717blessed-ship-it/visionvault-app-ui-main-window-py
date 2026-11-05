/// Compatibility helpers for order states received from Studio.
///
/// Older mobile caches used English identifiers while current Studio data uses
/// Spanish labels. Keeping the mapping at the read boundary lets both formats
/// coexist during upgrades and incremental synchronization.
abstract final class OrderStatus {
  static String key(String? value) {
    switch ((value ?? '').trim().toLowerCase()) {
      case 'pending':
      case 'pendiente':
      case 'new':
      case 'nuevo':
        return 'pending';
      case 'production':
      case 'producción':
      case 'produccion':
      case 'en producción':
      case 'en produccion':
        return 'production';
      case 'completed':
      case 'complete':
      case 'completado':
      case 'finalizado':
        return 'completed';
      case 'delivered':
      case 'entregado':
        return 'delivered';
      case 'cancelled':
      case 'canceled':
      case 'cancelado':
        return 'cancelled';
      case 'archived':
      case 'archivado':
        return 'archived';
      default:
        return (value ?? '').trim().toLowerCase();
    }
  }

  static List<String> databaseAliases(String value) {
    switch (key(value)) {
      case 'pending':
        return const ['pending', 'pendiente', 'new', 'nuevo'];
      case 'production':
        return const [
          'production',
          'producción',
          'produccion',
          'en producción',
          'en produccion',
        ];
      case 'completed':
        return const ['completed', 'complete', 'completado', 'finalizado'];
      case 'delivered':
        return const ['delivered', 'entregado'];
      case 'cancelled':
        return const ['cancelled', 'canceled', 'cancelado'];
      case 'archived':
        return const ['archived', 'archivado'];
      default:
        return [value.trim().toLowerCase()];
    }
  }
}

abstract final class OrderPriority {
  static List<String> databaseAliases(String value) {
    switch (value.trim().toLowerCase()) {
      case '4':
      case 'urgent':
      case 'urgente':
        return const ['4', 'urgent', 'urgente'];
      case '3':
      case 'high':
      case 'alta':
        return const ['3', 'high', 'alta'];
      case '2':
      case 'medium':
      case 'media':
        return const ['2', 'medium', 'media'];
      case '1':
      case 'low':
      case 'baja':
        return const ['1', 'low', 'baja'];
      case '0':
      case 'none':
      case 'sin prisa':
        return const ['0', 'none', 'sin prisa'];
      default:
        return [value.trim().toLowerCase()];
    }
  }
}
