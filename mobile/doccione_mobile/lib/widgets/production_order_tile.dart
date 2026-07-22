import 'package:flutter/material.dart';
import 'package:doccione_mobile/models/order_with_details.dart';
import 'package:doccione_mobile/services/quick_edit_api_client.dart';
import 'package:doccione_mobile/services/stage_service.dart';
import 'package:doccione_mobile/widgets/quick_action_sheet.dart';

/// A reusable order tile for production-context views.
///
/// Shows client avatar, priority badge, job info, and an "Advance" action.
/// Designed to be embedded in any production view (board drill-down, stage
/// list, search results, etc.) without coupling to a specific screen.
///
/// Required: [orderDetails].
/// Optional: [apiClient] enables the advance/unblock action; [onAdvanced]
/// is called after a successful status change so the parent can refresh.
class ProductionOrderTile extends StatelessWidget {
  final OrderWithDetails orderDetails;
  final QuickEditApiClient? apiClient;
  final bool isBlocking;
  final ValueChanged<OrderWithDetails>? onAdvanced;
  final VoidCallback? onTap;

  const ProductionOrderTile({
    super.key,
    required this.orderDetails,
    this.apiClient,
    this.isBlocking = false,
    this.onAdvanced,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final order = orderDetails.order;
    final currentStage = StageService.normalizeStatus(order.status);
    final next = StageService.nextStage(currentStage);
    final priority = StageService.priorityInt(order.printPriority);
    final age = StageService.ageDays(orderDetails);
    final canAdvance = apiClient != null && !isBlocking && next != null;

    return Card(
      margin: const EdgeInsets.symmetric(vertical: 6),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              _buildThumbnail(),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      orderDetails.clientName,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                            fontWeight: FontWeight.w600,
                          ),
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: 2),
                    Text(
                      orderDetails.primaryJobTitle,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: Colors.grey[600],
                          ),
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: 4),
                    Row(
                      children: [
                        Text(
                          '${orderDetails.jobsCount} '
                          '${orderDetails.jobsCount == 1 ? 'trabajo' : 'trabajos'}',
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                color: Colors.grey[500],
                              ),
                        ),
                        if (age != null) ...[
                          const SizedBox(width: 8),
                          Text(
                            '· hace ${age}d',
                            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                  color: Colors.grey[500],
                                ),
                          ),
                        ],
                      ],
                    ),
                  ],
                ),
              ),
              Column(
                children: [
                  _PriorityBadge(priority: priority),
                  const SizedBox(height: 6),
                  if (canAdvance)
                    _AdvanceButton(
                      label: 'Avanzar',
                      icon: Icons.arrow_forward,
                      onPressed: () => _advance(context, next!),
                    ),
                  if (isBlocking)
                    _AdvanceButton(
                      label: 'Desbloquear',
                      icon: Icons.lock_open,
                      onPressed: () => _unblock(context),
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildThumbnail() {
    final material = orderDetails.order.material;
    if (material != null && material.isNotEmpty) {
      return CircleAvatar(
        backgroundColor: StageService.priorityColor(
          orderDetails.order.printPriority,
        ).withOpacity(0.12),
        child: Icon(
          StageService.materialIcon(material),
          color: StageService.priorityColor(orderDetails.order.printPriority),
          size: 20,
        ),
      );
    }
    final name = orderDetails.clientName;
    final initial = name.isNotEmpty ? name[0].toUpperCase() : '?';
    return CircleAvatar(child: Text(initial));
  }

  Future<void> _advance(BuildContext context, String nextStage) async {
    if (apiClient == null) return;
    final orderId = int.tryParse(orderDetails.order.id);
    if (orderId == null) return;

    final result = await apiClient!.updateOrderStatus(orderId, nextStage);
    if (result.success && context.mounted) {
      final updated = orderDetails.copyWith(
        order: orderDetails.order.copyWith(status: nextStage),
      );
      onAdvanced?.call(updated);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('✔ Avanzado a "$nextStage"'),
          duration: const Duration(seconds: 2),
        ),
      );
    } else if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(result.errorMessage ?? 'Error al avanzar'),
          backgroundColor: Colors.red,
        ),
      );
    }
  }

  void _unblock(BuildContext context) {
    if (apiClient == null) return;
    final orderId = int.tryParse(orderDetails.order.id);
    if (orderId == null) return;

    QuickActionSheet.show(
      context,
      action: QuickAction.status,
      api: apiClient!,
      orderId: orderId,
      currentStatus: orderDetails.order.status,
      onSuccess: () {
        onAdvanced?.call(orderDetails);
      },
    );
  }
}

class _PriorityBadge extends StatelessWidget {
  final int priority;
  const _PriorityBadge({required this.priority});

  @override
  Widget build(BuildContext context) {
    if (priority <= 0) return const SizedBox.shrink();

    final color = StageService.priorityColor(priority.toString());
    final label = {
      1: 'Baja',
      2: 'Media',
      3: 'Alta',
      4: 'Urgente',
    }[priority];

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withOpacity(0.12),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(
        label ?? '',
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w600,
          color: color,
        ),
      ),
    );
  }
}

class _AdvanceButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final VoidCallback onPressed;

  const _AdvanceButton({
    required this.label,
    required this.icon,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 32,
      child: TextButton.icon(
        onPressed: onPressed,
        icon: Icon(icon, size: 14),
        label: Text(label, style: const TextStyle(fontSize: 12)),
        style: TextButton.styleFrom(
          padding: const EdgeInsets.symmetric(horizontal: 10),
          foregroundColor: Colors.orange.shade700,
        ),
      ),
    );
  }
}
