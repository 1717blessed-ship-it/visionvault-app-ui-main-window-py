import 'package:flutter/material.dart';
import '../models/dashboard_metrics.dart';

/// Widget that displays dashboard metrics in a card
class DashboardMetricsCard extends StatelessWidget {
  final DashboardMetrics metrics;

  const DashboardMetricsCard({
    super.key,
    required this.metrics,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Resumen',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: _buildMetricItem(
                    context,
                    'Hoy',
                    metrics.ordersToday,
                    Icons.today,
                    Colors.blue,
                  ),
                ),
                Expanded(
                  child: _buildMetricItem(
                    context,
                    'Producción',
                    metrics.ordersInProduction,
                    Icons.build,
                    Colors.orange,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: _buildMetricItem(
                    context,
                    'Pendientes',
                    metrics.ordersPending,
                    Icons.schedule,
                    Colors.amber,
                  ),
                ),
                Expanded(
                  child: _buildMetricItem(
                    context,
                    'Terminados',
                    metrics.ordersCompleted,
                    Icons.check_circle,
                    Colors.green,
                  ),
                ),
              ],
            ),
            const Divider(height: 24),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceAround,
              children: [
                _buildSmallMetric(
                  context,
                  'Trabajos',
                  metrics.totalJobs,
                  Icons.work_outline,
                ),
                _buildSmallMetric(
                  context,
                  'Clientes',
                  metrics.totalClients,
                  Icons.people_outline,
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildMetricItem(
    BuildContext context,
    String label,
    int value,
    IconData icon,
    Color color,
  ) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        children: [
          Icon(icon, color: color, size: 28),
          const SizedBox(height: 8),
          Text(
            value.toString(),
            style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  fontWeight: FontWeight.bold,
                  color: color,
                ),
          ),
          const SizedBox(height: 4),
          Text(
            label,
            style: Theme.of(context).textTheme.labelSmall,
          ),
        ],
      ),
    );
  }

  Widget _buildSmallMetric(
    BuildContext context,
    String label,
    int value,
    IconData icon,
  ) {
    return Column(
      children: [
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 20, color: Colors.grey[600]),
            const SizedBox(width: 4),
            Text(
              value.toString(),
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.bold,
                  ),
            ),
          ],
        ),
        const SizedBox(height: 4),
        Text(
          label,
          style: Theme.of(context).textTheme.labelSmall,
        ),
      ],
    );
  }
}
