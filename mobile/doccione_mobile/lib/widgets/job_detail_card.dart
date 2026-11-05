import 'package:flutter/material.dart';
import 'package:doccione_mobile/models/job.dart';
import 'package:doccione_mobile/widgets/quick_action_sheet.dart';
import 'package:doccione_mobile/services/quick_edit_api_client.dart';
import 'package:doccione_mobile/theme/doccione_palette.dart';

/// Widget to display job details in a card format
class JobDetailCard extends StatelessWidget {
  final Job job;
  final int index;
  final QuickEditApiClient? apiClient;
  final int? orderId;
  final VoidCallback? onRefresh;
  final void Function(String? status, int? quantity, String? size)? onJobEdited;

  const JobDetailCard({
    super.key,
    required this.job,
    required this.index,
    this.apiClient,
    this.orderId,
    this.onRefresh,
    this.onJobEdited,
  });

  @override
  Widget build(BuildContext context) {
    final hasApi = apiClient != null && orderId != null;
    final jobUid = int.tryParse(job.id);

    Widget card = Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 32,
                  height: 32,
                  decoration: BoxDecoration(
                    color:
                        Theme.of(context).primaryColor.withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: Center(
                    child: Text(
                      '${index + 1}',
                      style: TextStyle(
                        color: Theme.of(context).primaryColor,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    job.title ?? 'Sin título',
                    style: Theme.of(context)
                        .textTheme
                        .titleMedium
                        ?.copyWith(fontWeight: FontWeight.bold),
                  ),
                ),
                _buildStatusBadge(context),
                if (hasApi && jobUid != null)
                  PopupMenuButton<String>(
                    icon: const Icon(Icons.more_vert, size: 20),
                    tooltip: 'Editar trabajo',
                    onSelected: (action) =>
                        _handleJobAction(context, action, jobUid),
                    itemBuilder: (context) => [
                      const PopupMenuItem(
                          value: 'stage', child: Text('Cambiar etapa')),
                      const PopupMenuItem(
                          value: 'quantity_size',
                          child: Text('Cantidad y tamaño')),
                    ],
                  ),
              ],
            ),
            const SizedBox(height: 12),
            if (job.material != null && job.material!.isNotEmpty)
              _buildInfoRow(
                  context, Icons.category_outlined, 'Material', job.material!),
            if (job.size != null && job.size!.isNotEmpty)
              _buildInfoRow(context, Icons.straighten, 'Tamaño', job.size!),
            if (job.quantity != null)
              _buildInfoRow(context, Icons.format_list_numbered, 'Cantidad',
                  '${job.quantity}'),
            if (job.notes != null && job.notes!.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: DoccionePalette.surfaceElevated,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Icon(
                        Icons.note_outlined,
                        size: 16,
                        color: DoccionePalette.muted,
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          job.notes!,
                          style: Theme.of(context)
                              .textTheme
                              .bodySmall
                              ?.copyWith(color: DoccionePalette.muted),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );

    if (hasApi) {
      return GestureDetector(
        onLongPress: () => _showJobQuickActions(context),
        child: card,
      );
    }
    return card;
  }

  void _showJobQuickActions(BuildContext context) {
    final jobUid = int.tryParse(job.id);
    if (jobUid == null || apiClient == null || orderId == null) return;
    showModalBottomSheet(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: const EdgeInsets.all(16),
              child: Text(
                'Editar "${job.title ?? 'Trabajo'}"',
                style: Theme.of(context)
                    .textTheme
                    .titleMedium
                    ?.copyWith(fontWeight: FontWeight.bold),
              ),
            ),
            ListTile(
              leading: const Icon(Icons.play_circle_outline),
              title: const Text('Cambiar etapa'),
              onTap: () {
                Navigator.pop(ctx);
                QuickActionSheet.show(
                  context,
                  action: QuickAction.jobStage,
                  api: apiClient!,
                  orderId: orderId!,
                  jobId: jobUid,
                  currentStage: job.status ?? 'Recibido',
                  onSuccess: () => _applyJobEdit(context, jobUid, stage: null),
                );
              },
            ),
            ListTile(
              leading: const Icon(Icons.numbers),
              title: const Text('Cantidad y tamaño'),
              onTap: () {
                Navigator.pop(ctx);
                QuickActionSheet.show(
                  context,
                  action: QuickAction.jobQuantitySize,
                  api: apiClient!,
                  orderId: orderId!,
                  jobId: jobUid,
                  currentQuantity: job.quantity ?? 1,
                  currentSize: job.size ?? '',
                  onSuccess: () => _applyJobEdit(context, jobUid),
                );
              },
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }

  void _handleJobAction(BuildContext context, String action, int jobUid) {
    switch (action) {
      case 'stage':
        QuickActionSheet.show(
          context,
          action: QuickAction.jobStage,
          api: apiClient!,
          orderId: orderId!,
          jobId: jobUid,
          currentStage: job.status ?? 'Recibido',
          onSuccess: () => _applyJobEdit(context, jobUid, stage: null),
        );
        break;
      case 'quantity_size':
        QuickActionSheet.show(
          context,
          action: QuickAction.jobQuantitySize,
          api: apiClient!,
          orderId: orderId!,
          jobId: jobUid,
          currentQuantity: job.quantity ?? 1,
          currentSize: job.size ?? '',
          onSuccess: () => _applyJobEdit(context, jobUid),
        );
        break;
    }
  }

  void _applyJobEdit(BuildContext context, int jobUid, {String? stage}) {
    onJobEdited?.call(null, null, null);
    onRefresh?.call();
  }

  Widget _buildInfoRow(
      BuildContext context, IconData icon, String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Row(
        children: [
          Icon(icon, size: 16, color: DoccionePalette.muted),
          const SizedBox(width: 8),
          Text(
            '$label: ',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: DoccionePalette.muted,
                  fontWeight: FontWeight.w500,
                ),
          ),
          Expanded(
            child: Text(value, style: Theme.of(context).textTheme.bodyMedium),
          ),
        ],
      ),
    );
  }

  Widget _buildStatusBadge(BuildContext context) {
    final status = job.status ?? 'unknown';
    Color backgroundColor;
    Color textColor;
    String label;

    switch (status.toLowerCase()) {
      case 'pending':
        backgroundColor = DoccionePalette.infoSoft;
        textColor = DoccionePalette.info;
        label = 'Pendiente';
        break;
      case 'in_progress':
      case 'production':
        backgroundColor = DoccionePalette.productionSoft;
        textColor = DoccionePalette.production;
        label = 'En Proceso';
        break;
      case 'completed':
        backgroundColor = DoccionePalette.successSoft;
        textColor = DoccionePalette.success;
        label = 'Completado';
        break;
      case 'cancelled':
        backgroundColor = DoccionePalette.dangerSoft;
        textColor = DoccionePalette.danger;
        label = 'Cancelado';
        break;
      default:
        backgroundColor = DoccionePalette.neutralSoft;
        textColor = DoccionePalette.muted;
        label = status;
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: backgroundColor,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(
        label,
        style: TextStyle(
            color: textColor, fontSize: 11, fontWeight: FontWeight.w600),
      ),
    );
  }
}
