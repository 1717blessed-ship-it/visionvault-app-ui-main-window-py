import 'package:flutter/material.dart';
import 'package:doccione_mobile/models/order_with_details.dart';
import 'package:doccione_mobile/services/stage_service.dart';
import '../theme/doccione_palette.dart';

/// Read-only overview of the production state of sales created on this device.
class SalesTimelineCard extends StatelessWidget {
  final List<OrderWithDetails> sales;
  final VoidCallback? onViewAll;
  final int maxVisibleSales;

  const SalesTimelineCard({
    super.key,
    required this.sales,
    this.onViewAll,
    this.maxVisibleSales = 3,
  });

  @override
  Widget build(BuildContext context) {
    final visibleSales = sales.take(maxVisibleSales).toList();

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 40,
                  height: 40,
                  decoration: BoxDecoration(
                    color: DoccionePalette.wine.withValues(alpha: .10),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: const Icon(
                    Icons.route_outlined,
                    color: DoccionePalette.wine,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Estado de tus ventas',
                        style: Theme.of(context)
                            .textTheme
                            .titleLarge
                            ?.copyWith(fontWeight: FontWeight.w700),
                      ),
                      Text(
                        'Seguimiento de los pedidos que cargaste',
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color: DoccionePalette.muted,
                            ),
                      ),
                    ],
                  ),
                ),
                if (onViewAll != null && sales.isNotEmpty)
                  TextButton(
                    onPressed: onViewAll,
                    child: const Text('Ver todas'),
                  ),
              ],
            ),
            const SizedBox(height: 18),
            if (visibleSales.isEmpty)
              const _EmptySalesTimeline()
            else
              for (var index = 0; index < visibleSales.length; index++) ...[
                _SaleTimelineItem(orderDetails: visibleSales[index]),
                if (index < visibleSales.length - 1) const Divider(height: 28),
              ],
          ],
        ),
      ),
    );
  }
}

class _SaleTimelineItem extends StatelessWidget {
  final OrderWithDetails orderDetails;

  const _SaleTimelineItem({required this.orderDetails});

  static const _milestoneLabels = [
    'Recibido',
    'Preparación',
    'Producción',
    'Listo',
    'Entregado',
  ];

  @override
  Widget build(BuildContext context) {
    final stage = _currentStage(orderDetails);
    final stageIndex = StageService.generalWorkflow.indexOf(stage);
    final currentMilestone = _milestoneForStage(stageIndex);
    final order = orderDetails.order;
    final orderLabel = order.orderNumber ??
        (order.id.length > 8 ? order.id.substring(0, 8) : order.id);
    final clientName =
        orderDetails.client?.name ?? order.client ?? orderDetails.clientName;

    return Semantics(
      label: 'Pedido $orderLabel, estado actual $stage',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Pedido #$orderLabel',
                      style: Theme.of(context)
                          .textTheme
                          .titleSmall
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      clientName,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: DoccionePalette.muted,
                          ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 10),
              Container(
                constraints: const BoxConstraints(maxWidth: 170),
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                decoration: BoxDecoration(
                  color: _stageColor(stage).withValues(alpha: .11),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Text(
                  stage,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: _stageColor(stage),
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: List.generate(
              _milestoneLabels.length,
              (index) => Expanded(
                child: _TimelineMilestone(
                  label: _milestoneLabels[index],
                  isCompleted: index < currentMilestone,
                  isCurrent: index == currentMilestone,
                  leftConnected: index > 0 && index <= currentMilestone,
                  rightConnected: index < currentMilestone,
                  isFirst: index == 0,
                  isLast: index == _milestoneLabels.length - 1,
                ),
              ),
            ),
          ),
          if (orderDetails.jobsCount > 1) ...[
            const SizedBox(height: 8),
            Text(
              '${orderDetails.jobsCount} trabajos incluidos · se muestra la etapa menos avanzada',
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: DoccionePalette.muted,
                  ),
            ),
          ],
        ],
      ),
    );
  }

  static String _currentStage(OrderWithDetails orderDetails) {
    if (orderDetails.jobs.isEmpty) {
      return StageService.normalizeStatus(orderDetails.order.status);
    }

    var earliestStage = StageService.generalWorkflow.first;
    var earliestIndex = StageService.generalWorkflow.length;

    for (final job in orderDetails.jobs) {
      final normalized = StageService.normalizeStatus(job.status);
      final index = StageService.generalWorkflow.indexOf(normalized);
      if (index >= 0 && index < earliestIndex) {
        earliestIndex = index;
        earliestStage = normalized;
      }
    }

    return earliestStage;
  }

  static int _milestoneForStage(int stageIndex) {
    if (stageIndex >= 11) return 4;
    if (stageIndex >= 10) return 3;
    if (stageIndex >= 6) return 2;
    if (stageIndex >= 3) return 1;
    return 0;
  }

  static Color _stageColor(String stage) {
    final colorValue = StageService.stageColors[stage];
    return Color(colorValue ?? 0xFF6B7280);
  }
}

class _TimelineMilestone extends StatelessWidget {
  final String label;
  final bool isCompleted;
  final bool isCurrent;
  final bool leftConnected;
  final bool rightConnected;
  final bool isFirst;
  final bool isLast;

  const _TimelineMilestone({
    required this.label,
    required this.isCompleted,
    required this.isCurrent,
    required this.leftConnected,
    required this.rightConnected,
    required this.isFirst,
    required this.isLast,
  });

  @override
  Widget build(BuildContext context) {
    final activeColor =
        isCurrent ? DoccionePalette.wine : DoccionePalette.success;
    final dotColor =
        (isCompleted || isCurrent) ? activeColor : DoccionePalette.subtle;

    return Column(
      children: [
        SizedBox(
          height: 20,
          child: Row(
            children: [
              Expanded(
                child: Container(
                  height: 2,
                  color: isFirst
                      ? Colors.transparent
                      : leftConnected
                          ? DoccionePalette.success
                          : DoccionePalette.border,
                ),
              ),
              AnimatedContainer(
                duration: const Duration(milliseconds: 250),
                width: isCurrent ? 18 : 14,
                height: isCurrent ? 18 : 14,
                decoration: BoxDecoration(
                  color: dotColor,
                  shape: BoxShape.circle,
                  border: Border.all(
                    color: isCurrent
                        ? DoccionePalette.wine.withValues(alpha: .25)
                        : dotColor,
                    width: isCurrent ? 4 : 1,
                  ),
                ),
                child: isCompleted
                    ? const Icon(Icons.check, size: 10, color: Colors.white)
                    : null,
              ),
              Expanded(
                child: Container(
                  height: 2,
                  color: isLast
                      ? Colors.transparent
                      : rightConnected
                          ? DoccionePalette.success
                          : DoccionePalette.border,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 5),
        Text(
          label,
          maxLines: 2,
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.labelSmall?.copyWith(
                color: isCurrent
                    ? DoccionePalette.wine
                    : isCompleted
                        ? DoccionePalette.success
                        : DoccionePalette.muted,
                fontWeight: isCurrent ? FontWeight.w700 : FontWeight.w500,
                fontSize: 10,
              ),
        ),
      ],
    );
  }
}

class _EmptySalesTimeline extends StatelessWidget {
  const _EmptySalesTimeline();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 22),
      decoration: BoxDecoration(
        color: DoccionePalette.surfaceElevated,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: DoccionePalette.border),
      ),
      child: Column(
        children: [
          const Icon(
            Icons.receipt_long_outlined,
            size: 34,
            color: DoccionePalette.subtle,
          ),
          const SizedBox(height: 10),
          Text(
            'Todavía no hay ventas para seguir',
            style: Theme.of(context)
                .textTheme
                .titleSmall
                ?.copyWith(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 4),
          Text(
            'Cuando cargues una venta, su estado aparecerá en esta línea de tiempo.',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: DoccionePalette.muted,
                ),
          ),
        ],
      ),
    );
  }
}
