import 'package:flutter/material.dart';
import '../models/dashboard_metrics.dart';
import '../screens/orders_list_screen.dart';
import '../theme/doccione_palette.dart';

/// Widget that displays dashboard metrics in a card
class DashboardMetricsCard extends StatelessWidget {
  final DashboardMetrics metrics;
  final String? sessionToken;

  const DashboardMetricsCard({
    super.key,
    required this.metrics,
    this.sessionToken,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Resumen de producción',
              style: Theme.of(context)
                  .textTheme
                  .titleLarge
                  ?.copyWith(fontWeight: FontWeight.w700),
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
                    DoccionePalette.info,
                    null, // No filter - today is computed, not a status
                  ),
                ),
                Expanded(
                  child: _buildMetricItem(
                    context,
                    'Producción',
                    metrics.ordersInProduction,
                    Icons.build,
                    DoccionePalette.production,
                    'production',
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
                    DoccionePalette.wine,
                    'pending',
                  ),
                ),
                Expanded(
                  child: _buildMetricItem(
                    context,
                    'Terminados',
                    metrics.ordersCompleted,
                    Icons.check_circle,
                    DoccionePalette.success,
                    'completed',
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
    String? filterStatus,
  ) {
    return InkWell(
      onTap: filterStatus != null
          ? () {
              Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (context) => OrdersListScreen(
                    initialStatus: filterStatus,
                    sessionToken: sessionToken,
                  ),
                ),
              );
            }
          : null,
      borderRadius: BorderRadius.circular(8),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 14),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.1),
          borderRadius: BorderRadius.circular(14),
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
            Icon(icon, size: 20, color: DoccionePalette.muted),
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
