import 'package:flutter/material.dart';
import 'package:doccione_mobile/services/quick_edit_api_client.dart';

/// Interactive timeline showing job production stages.
/// Tapping the next stage advances the job through the pipeline.
class StageTimeline extends StatefulWidget {
  final String currentStage;
  final QuickEditApiClient? apiClient;
  final int? orderId;
  final int? jobId;
  final VoidCallback? onStageChanged;

  const StageTimeline({
    super.key,
    required this.currentStage,
    this.apiClient,
    this.orderId,
    this.jobId,
    this.onStageChanged,
  });

  @override
  State<StageTimeline> createState() => _StageTimelineState();
}

class _StageTimelineState extends State<StageTimeline> {
  bool _isSaving = false;

  static const _stages = [
    'Recibido',
    'Esperando archivos',
    'Diseños confirmados',
    'Listo para armado de planchas',
    'En armado de planchas',
    'Listo para imprimir',
    'Impresión',
    'Sublimado / Laminado',
    'Corte',
    'Control de calidad',
    'Finalizado',
    'Entregado',
  ];

  @override
  Widget build(BuildContext context) {
    final currentIndex = _stages.indexOf(widget.currentStage);
    final hasApi = widget.apiClient != null &&
        widget.orderId != null &&
        widget.jobId != null;
    final canAdvance =
        hasApi && currentIndex >= 0 && currentIndex < _stages.length - 1;

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.timeline, color: Colors.grey[600]),
                const SizedBox(width: 8),
                Text(
                  'Etapa del trabajo',
                  style: Theme.of(context)
                      .textTheme
                      .titleSmall
                      ?.copyWith(fontWeight: FontWeight.bold),
                ),
              ],
            ),
            const SizedBox(height: 16),
            ...List.generate(_stages.length, (i) {
              final stage = _stages[i];
              final isPast = i < currentIndex;
              final isCurrent = i == currentIndex;
              final isNext = i == currentIndex + 1;
              final isFuture = i > currentIndex;

              return _StageRow(
                stage: stage,
                isPast: isPast,
                isCurrent: isCurrent,
                isNext: isNext && canAdvance && !_isSaving,
                isFuture: isFuture,
                isLast: i == _stages.length - 1,
                isSaving: _isSaving && isNext,
                onTap: isNext && canAdvance && !_isSaving
                    ? () => _confirmAdvance(context, stage)
                    : null,
              );
            }),
          ],
        ),
      ),
    );
  }

  void _confirmAdvance(BuildContext context, String nextStage) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Avanzar etapa'),
        content: Text('¿Mover el trabajo a "$nextStage"?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: _isSaving
                ? null
                : () async {
                    Navigator.pop(ctx);
                    await _advanceStage(nextStage);
                  },
            child: const Text('Confirmar'),
          ),
        ],
      ),
    );
  }

  Future<void> _advanceStage(String nextStage) async {
    if (widget.apiClient == null || widget.jobId == null) return;
    setState(() => _isSaving = true);
    try {
      final result = await widget.apiClient!.changeJobStage(
        widget.jobId!,
        nextStage,
      );
      if (mounted) {
        if (result.success) {
          widget.onStageChanged?.call();
        } else {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(result.errorMessage ?? 'Error al avanzar etapa'),
              backgroundColor: Colors.red,
            ),
          );
        }
      }
    } finally {
      if (mounted) setState(() => _isSaving = false);
    }
  }
}

class _StageRow extends StatelessWidget {
  final String stage;
  final bool isPast;
  final bool isCurrent;
  final bool isNext;
  final bool isFuture;
  final bool isLast;
  final bool isSaving;
  final VoidCallback? onTap;

  const _StageRow({
    required this.stage,
    required this.isPast,
    required this.isCurrent,
    required this.isNext,
    required this.isFuture,
    required this.isLast,
    this.isSaving = false,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final dotColor = isCurrent
        ? Theme.of(context).colorScheme.primary
        : isPast
            ? Colors.green
            : isNext
                ? Colors.orange
                : Colors.grey.shade300;

    final textColor = isCurrent
        ? Theme.of(context).colorScheme.primary
        : isPast
            ? Colors.green.shade700
            : Colors.grey.shade500;

    final fontWeight = isCurrent ? FontWeight.bold : FontWeight.normal;

    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 8),
        child: Row(
          children: [
            Column(
              children: [
                Container(
                  width: 12,
                  height: 12,
                  decoration: BoxDecoration(
                    color: isCurrent
                        ? dotColor
                        : (isPast ? dotColor : Colors.transparent),
                    shape: BoxShape.circle,
                    border: Border.all(color: dotColor, width: 2),
                  ),
                  child: isCurrent
                      ? const Icon(Icons.circle, size: 6, color: Colors.white)
                      : isPast
                          ? const Icon(Icons.check,
                              size: 8, color: Colors.white)
                          : null,
                ),
                if (!isLast)
                  Container(
                    width: 2,
                    height: 24,
                    color:
                        isPast ? Colors.green.shade200 : Colors.grey.shade200,
                  ),
              ],
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                stage,
                style: TextStyle(
                  fontSize: 14,
                  color: textColor,
                  fontWeight: fontWeight,
                ),
              ),
            ),
            if (isNext && onTap != null)
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: Colors.orange.shade50,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Colors.orange.shade200),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (isSaving)
                      const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    else
                      Icon(Icons.arrow_forward,
                          size: 14, color: Colors.orange.shade700),
                    const SizedBox(width: 4),
                    Text(
                      isSaving ? 'Guardando…' : 'Avanzar',
                      style: TextStyle(
                          fontSize: 12,
                          color: Colors.orange.shade700,
                          fontWeight: FontWeight.w600),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}
