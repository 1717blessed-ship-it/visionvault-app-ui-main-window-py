import 'package:flutter/material.dart';
import 'package:doccione_mobile/models/order_with_details.dart';
import 'package:doccione_mobile/models/order_status.dart';
import '../theme/doccione_palette.dart';

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
      margin: const EdgeInsets.fromLTRB(16, 10, 16, 0),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(20),
        child: Padding(
          padding: const EdgeInsets.all(18),
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
                  const Icon(
                    Icons.chevron_right,
                    color: DoccionePalette.muted,
                  ),
                ],
              ),
              const SizedBox(height: 12),
              // Client name
              Row(
                children: [
                  const Icon(
                    Icons.person_outline,
                    size: 16,
                    color: DoccionePalette.muted,
                  ),
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
                  const Icon(
                    Icons.work_outline,
                    size: 16,
                    color: DoccionePalette.muted,
                  ),
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
                          color: DoccionePalette.muted,
                        ),
                  ),
                  const SizedBox(width: 16),
                  if (orderDetails.hasJobs)
                    Text(
                      '${orderDetails.jobsCount} ${orderDetails.jobsCount == 1 ? 'trabajo' : 'trabajos'}',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: DoccionePalette.muted,
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

    switch (OrderStatus.key(status)) {
      case 'pending':
        backgroundColor = DoccionePalette.wine.withValues(alpha: .10);
        textColor = DoccionePalette.wine;
        label = 'Pendiente';
        icon = Icons.schedule;
        break;
      case 'production':
        backgroundColor = DoccionePalette.production.withValues(alpha: .12);
        textColor = DoccionePalette.production;
        label = 'Producción';
        icon = Icons.build;
        break;
      case 'completed':
        backgroundColor = DoccionePalette.success.withValues(alpha: .11);
        textColor = DoccionePalette.success;
        label = 'Completado';
        icon = Icons.check_circle;
        break;
      case 'delivered':
        backgroundColor = DoccionePalette.violetSoft;
        textColor = DoccionePalette.violet;
        label = 'Entregado';
        icon = Icons.local_shipping;
        break;
      case 'cancelled':
        backgroundColor = DoccionePalette.dangerSoft;
        textColor = DoccionePalette.danger;
        label = 'Cancelado';
        icon = Icons.cancel;
        break;
      default:
        backgroundColor = DoccionePalette.neutralSoft;
        textColor = DoccionePalette.muted;
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
