import 'package:doccione_mobile/models/order.dart';
import 'package:doccione_mobile/models/client.dart';
import 'package:doccione_mobile/models/job.dart';

/// Order with related client and jobs data
class OrderWithDetails {
  final Order order;
  final Client? client;
  final List<Job> jobs;

  OrderWithDetails({
    required this.order,
    this.client,
    required this.jobs,
  });

  String get clientName => client?.name ?? 'Sin cliente';
  String get clientPhone => client?.phone ?? '';
  
  int get jobsCount => jobs.length;
  
  bool get hasJobs => jobs.isNotEmpty;
  
  /// Get formatted order date
  String get formattedOrderDate {
    if (order.orderDate == null) return 'Sin fecha';
    final date = order.orderDate!;
    return '${date.day.toString().padLeft(2, '0')}/${date.month.toString().padLeft(2, '0')}/${date.year}';
  }
  
  /// Get formatted delivery date
  String get formattedDeliveryDate {
    if (order.deliveryDate == null) return 'Sin fecha';
    final date = order.deliveryDate!;
    return '${date.day.toString().padLeft(2, '0')}/${date.month.toString().padLeft(2, '0')}/${date.year}';
  }
  
  /// Get primary job title (first job or empty)
  String get primaryJobTitle {
    if (jobs.isEmpty) return 'Sin trabajos';
    return jobs.first.title ?? 'Sin título';
  }
  
  /// Get concatenated job titles
  String get jobTitles {
    if (jobs.isEmpty) return 'Sin trabajos';
    return jobs.map((j) => j.title ?? 'Sin título').join(', ');
  }
}
