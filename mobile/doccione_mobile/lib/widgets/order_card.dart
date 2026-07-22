import 'package:flutter/material.dart';
import 'package:doccione_mobile/models/order_with_details.dart';

class OrderCard extends StatelessWidget {
  final OrderWithDetails orderDetails;
  final VoidCallback? onTap;

  const OrderCard({
    super.key,
    required this.orderDetails,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final order = orderDetails.order;
    
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  // Order number
                  Text(
                    '#${order.orderNumber ?? (order.id.length > 8 ? order.id.substring(0, 8) : order.id)}',
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                  ),
                  const SizedBox(width: 8),
                  // Status badge
                  _buildStatusBadge(context),
                  const Spacer(),
                  // Arrow icon
                  const Icon(Icons.chevron_right, color: Colors.grey),
                ],
              ),
              const SizedBox(height: 12),
              // Client name
              Row(
                children: [
                  const Icon(Icons.person_outline, size: 16, color: Colors.grey),
                  const SizedBox(width: 4),
                  Expanded(
                    child: Text(
                      orderDetails.clientName,
                      style: Theme.of(context).textTheme.bodyMedium,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              // Primary job
              Row(
                children: [
                  const Icon(Icons.work_outline, size: 16, color: Colors.grey),
                  const SizedBox(width: 4),
                  Expanded(
                    child: Text(
                      orderDetails.primaryJobTitle,
                      style: Theme.of(context).textTheme.bodySmall,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              // Footer with dates and jobs count
              Row(
                children: [
                  Text(
                    orderDetails.formattedOrderDate,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Colors.grey[600],
                        ),
                  ),
                  const SizedBox(width: 16),
                  if (orderDetails.hasJobs)
                    Text(
                      '${orderDetails.jobsCount} ${orderDetails.jobsCount == 1 ? 'trabajo' : 'trabajos'}',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: Colors.grey[600],
                          ),
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildStatusBadge(BuildContext context) {
    final status = orderDetails.order.status ?? 'unknown';
    
    Color backgroundColor;
    Color textColor;
    String label;
    IconData icon;
    
    switch (status.toLowerCase()) {
      case 'pending':
        backgroundColor = Colors.blue.shade50;
        textColor = Colors.blue.shade700;
        label = 'Pendiente';
        icon = Icons.schedule;
        break;
      case 'production':
        backgroundColor = Colors.orange.shade50;
        textColor = Colors.orange.shade700;
        label = 'Producción';
        icon = Icons.build;
        break;
      case 'completed':
        backgroundColor = Colors.green.shade50;
        textColor = Colors.green.shade700;
        label = 'Completado';
        icon = Icons.check_circle;
        break;
      case 'delivered':
        backgroundColor = Colors.purple.shade50;
        textColor = Colors.purple.shade700;
        label = 'Entregado';
        icon = Icons.local_shipping;
        break;
      case 'cancelled':
        backgroundColor = Colors.red.shade50;
        textColor = Colors.red.shade700;
        label = 'Cancelado';
        icon = Icons.cancel;
        break;
      default:
        backgroundColor = Colors.grey.shade50;
        textColor = Colors.grey.shade700;
        label = status;
        icon = Icons.help_outline;
    }
    
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: backgroundColor,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: textColor),
          const SizedBox(width: 4),
          Text(
            label,
            style: TextStyle(
              color: textColor,
              fontSize: 12,
              fontWeight: FontWeight.w500,
            ),
          ),
        ],
      ),
    );
  }
}
