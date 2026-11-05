import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:doccione_mobile/services/quick_edit_api_client.dart';
import 'package:doccione_mobile/services/stage_service.dart';
import 'package:doccione_mobile/models/mobile_runtime_config.dart';
import 'package:doccione_mobile/theme/doccione_palette.dart';

/// Actions available from the quick-action sheet.
enum QuickAction {
  status,
  priority,
  payment,
  delivery,
  jobStage,
  jobQuantitySize,
}

/// Single entry-point for all quick-edit sheets.
/// The caller picks the [action], this widget renders the right editor.
class QuickActionSheet {
  QuickActionSheet._();

  // ── Constants ──────────────────────────────────────────────────────────

  static List<String> get _orderStatuses => StageService.orderStatuses;
  static Map<int, String> get _priorities => {
        for (final item in StageService.priorities) item.value: item.label,
      };
  static List<String> get _jobStages => StageService.generalWorkflow;

  // ── Public API ─────────────────────────────────────────────────────────

  static Future<void> show(
    BuildContext context, {
    required QuickAction action,
    required QuickEditApiClient api,
    required int orderId,
    required VoidCallback onSuccess,
    Future<void> Function()? onCancelled,
    int? jobId,
    String? currentStatus,
    int? currentPriority,
    String? currentStage,
    int? currentQuantity,
    String? currentSize,
  }) {
    final runtime = MobileRuntimeConfigStore.current;
    if (runtime.maintenanceEnabled) {
      _showUnavailable(
        context,
        runtime.maintenanceMessage.isEmpty
            ? 'Studio está en mantenimiento.'
            : runtime.maintenanceMessage,
      );
      return Future.value();
    }
    if (!runtime.featureEnabled('quick_edits') &&
        action != QuickAction.payment) {
      _showUnavailable(
        context,
        'Las ediciones están temporalmente deshabilitadas desde Studio.',
      );
      return Future.value();
    }
    if (action == QuickAction.payment && !runtime.featureEnabled('payments')) {
      _showUnavailable(
        context,
        'El registro de cobros está temporalmente deshabilitado.',
      );
      return Future.value();
    }
    switch (action) {
      case QuickAction.status:
        return showModalBottomSheet<void>(
          context: context,
          isScrollControlled: true,
          builder: (_) => _StatusEditor(
            api: api,
            orderId: orderId,
            currentStatus: currentStatus ?? 'Pendiente',
            onSuccess: onSuccess,
            onCancelled: onCancelled,
          ),
        );
      case QuickAction.priority:
        return showModalBottomSheet<void>(
          context: context,
          isScrollControlled: true,
          builder: (_) => _PriorityEditor(
            api: api,
            orderId: orderId,
            currentPriority: currentPriority ?? 0,
            onSuccess: onSuccess,
          ),
        );
      case QuickAction.jobStage:
        if (jobId == null) return Future.value();
        return showModalBottomSheet<void>(
          context: context,
          isScrollControlled: true,
          builder: (_) => _JobStageEditor(
            api: api,
            orderId: orderId,
            jobId: jobId,
            currentStage: currentStage ?? 'Recibido',
            onSuccess: onSuccess,
          ),
        );
      case QuickAction.jobQuantitySize:
        if (jobId == null) return Future.value();
        return showModalBottomSheet<void>(
          context: context,
          isScrollControlled: true,
          builder: (_) => _JobQuantitySizeEditor(
            api: api,
            orderId: orderId,
            jobId: jobId,
            currentQuantity: currentQuantity ?? 1,
            currentSize: currentSize ?? '',
            onSuccess: onSuccess,
          ),
        );
      case QuickAction.payment:
        return showModalBottomSheet<void>(
          context: context,
          isScrollControlled: true,
          builder: (_) => _PaymentEditor(
            api: api,
            orderId: orderId,
            onSuccess: onSuccess,
          ),
        );
      case QuickAction.delivery:
        return showDialog<void>(
          context: context,
          builder: (_) => _DeliveryConfirm(
            api: api,
            orderId: orderId,
            onSuccess: onSuccess,
          ),
        );
    }
  }

  static void _showUnavailable(BuildContext context, String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message)),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// Private editors
// ═══════════════════════════════════════════════════════════════════════════

class _StatusEditor extends StatefulWidget {
  final QuickEditApiClient api;
  final int orderId;
  final String currentStatus;
  final VoidCallback onSuccess;
  final Future<void> Function()? onCancelled;

  const _StatusEditor({
    required this.api,
    required this.orderId,
    required this.currentStatus,
    required this.onSuccess,
    this.onCancelled,
  });

  @override
  State<_StatusEditor> createState() => _StatusEditorState();
}

class _StatusEditorState extends State<_StatusEditor> {
  bool _isSaving = false;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (_isSaving) const LinearProgressIndicator(minHeight: 3),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Text(
              'Cambiar estado del pedido',
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(fontWeight: FontWeight.bold),
            ),
          ),
          Flexible(
            child: IgnorePointer(
              ignoring: _isSaving,
              child: Opacity(
                opacity: _isSaving ? 0.5 : 1.0,
                child: ListView(
                  shrinkWrap: true,
                  children: QuickActionSheet._orderStatuses
                      .map(
                        (status) => RadioListTile<String>(
                          title: Text(status),
                          value: status,
                          // Compatibilidad con Flutter estable actual; migrar
                          // el grupo completo cuando RadioGroup sea obligatorio.
                          // ignore: deprecated_member_use
                          groupValue: widget.currentStatus,
                          // ignore: deprecated_member_use
                          onChanged: _isSaving
                              ? null
                              : (value) async {
                                  if (value == null ||
                                      value == widget.currentStatus) {
                                    Navigator.pop(context);
                                    return;
                                  }
                                  setState(() => _isSaving = true);
                                  final result = await widget.api
                                      .updateOrderStatus(widget.orderId, value);
                                  if (!context.mounted) return;
                                  if (result.success) {
                                    final normalized =
                                        value.trim().toLowerCase();
                                    final cancelled =
                                        normalized == 'cancelado' ||
                                            normalized == 'cancelled';
                                    if (cancelled &&
                                        widget.onCancelled != null) {
                                      showSuccess(
                                        context,
                                        'Pedido cancelado y quitado de este móvil',
                                      );
                                      Navigator.pop(context);
                                      await widget.onCancelled!();
                                    } else {
                                      showSuccess(context,
                                          '✔ Estado cambiado a "$value"');
                                      Navigator.pop(context);
                                      widget.onSuccess();
                                    }
                                  } else {
                                    setState(() => _isSaving = false);
                                    showError(context, result.errorMessage);
                                  }
                                },
                        ),
                      )
                      .toList(),
                ),
              ),
            ),
          ),
          const SizedBox(height: 8),
        ],
      ),
    );
  }
}

class _PriorityEditor extends StatefulWidget {
  final QuickEditApiClient api;
  final int orderId;
  final int currentPriority;
  final VoidCallback onSuccess;

  const _PriorityEditor({
    required this.api,
    required this.orderId,
    required this.currentPriority,
    required this.onSuccess,
  });

  @override
  State<_PriorityEditor> createState() => _PriorityEditorState();
}

class _PriorityEditorState extends State<_PriorityEditor> {
  bool _isSaving = false;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (_isSaving) const LinearProgressIndicator(minHeight: 3),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Text(
              'Cambiar prioridad',
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(fontWeight: FontWeight.bold),
            ),
          ),
          Flexible(
            child: IgnorePointer(
              ignoring: _isSaving,
              child: Opacity(
                opacity: _isSaving ? 0.5 : 1.0,
                child: ListView(
                  shrinkWrap: true,
                  children: QuickActionSheet._priorities.entries
                      .map(
                        (entry) => RadioListTile<int>(
                          title: Text(entry.value),
                          value: entry.key,
                          // Compatibilidad con Flutter estable actual.
                          // ignore: deprecated_member_use
                          groupValue: widget.currentPriority,
                          // ignore: deprecated_member_use
                          onChanged: _isSaving
                              ? null
                              : (value) async {
                                  if (value == null ||
                                      value == widget.currentPriority) {
                                    Navigator.pop(context);
                                    return;
                                  }
                                  setState(() => _isSaving = true);
                                  final label =
                                      QuickActionSheet._priorities[value] ??
                                          '$value';
                                  final result = await widget.api
                                      .updateOrderPriority(
                                          widget.orderId, value);
                                  if (!context.mounted) return;
                                  if (result.success) {
                                    showSuccess(context,
                                        '✔ Prioridad cambiada a "$label"');
                                    Navigator.pop(context);
                                    widget.onSuccess();
                                  } else {
                                    setState(() => _isSaving = false);
                                    showError(context, result.errorMessage);
                                  }
                                },
                        ),
                      )
                      .toList(),
                ),
              ),
            ),
          ),
          const SizedBox(height: 8),
        ],
      ),
    );
  }
}

class _JobStageEditor extends StatefulWidget {
  final QuickEditApiClient api;
  final int orderId;
  final int jobId;
  final String currentStage;
  final VoidCallback onSuccess;

  const _JobStageEditor({
    required this.api,
    required this.orderId,
    required this.jobId,
    required this.currentStage,
    required this.onSuccess,
  });

  @override
  State<_JobStageEditor> createState() => _JobStageEditorState();
}

class _JobStageEditorState extends State<_JobStageEditor> {
  bool _isSaving = false;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (_isSaving) const LinearProgressIndicator(minHeight: 3),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Text(
              'Cambiar etapa del trabajo',
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(fontWeight: FontWeight.bold),
            ),
          ),
          Flexible(
            child: IgnorePointer(
              ignoring: _isSaving,
              child: Opacity(
                opacity: _isSaving ? 0.5 : 1.0,
                child: ListView(
                  shrinkWrap: true,
                  children: QuickActionSheet._jobStages
                      .map(
                        (stage) => RadioListTile<String>(
                          title: Text(stage),
                          value: stage,
                          // Compatibilidad con Flutter estable actual.
                          // ignore: deprecated_member_use
                          groupValue: widget.currentStage,
                          // ignore: deprecated_member_use
                          onChanged: _isSaving
                              ? null
                              : (value) async {
                                  if (value == null ||
                                      value == widget.currentStage) {
                                    Navigator.pop(context);
                                    return;
                                  }
                                  setState(() => _isSaving = true);
                                  final result = await widget.api
                                      .changeJobStage(widget.jobId, value);
                                  if (!context.mounted) return;
                                  if (result.success) {
                                    showSuccess(
                                        context, '✔ Etapa cambiada a "$value"');
                                    Navigator.pop(context);
                                    widget.onSuccess();
                                  } else {
                                    setState(() => _isSaving = false);
                                    showError(context, result.errorMessage);
                                  }
                                },
                        ),
                      )
                      .toList(),
                ),
              ),
            ),
          ),
          const SizedBox(height: 8),
        ],
      ),
    );
  }
}

class _JobQuantitySizeEditor extends StatefulWidget {
  final QuickEditApiClient api;
  final int orderId;
  final int jobId;
  final int currentQuantity;
  final String currentSize;
  final VoidCallback onSuccess;

  const _JobQuantitySizeEditor({
    required this.api,
    required this.orderId,
    required this.jobId,
    required this.currentQuantity,
    required this.currentSize,
    required this.onSuccess,
  });

  @override
  State<_JobQuantitySizeEditor> createState() => _JobQuantitySizeEditorState();
}

class _JobQuantitySizeEditorState extends State<_JobQuantitySizeEditor> {
  late final TextEditingController _quantityController;
  late final TextEditingController _sizeController;
  bool _isSaving = false;

  @override
  void initState() {
    super.initState();
    _quantityController =
        TextEditingController(text: widget.currentQuantity.toString());
    _sizeController = TextEditingController(text: widget.currentSize);
  }

  @override
  void dispose() {
    _quantityController.dispose();
    _sizeController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 16,
        right: 16,
        top: 16,
        bottom: MediaQuery.of(context).viewInsets.bottom + 16,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_isSaving) const LinearProgressIndicator(minHeight: 3),
          Text(
            'Modificar cantidad y tamaño',
            style: Theme.of(context)
                .textTheme
                .titleMedium
                ?.copyWith(fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _quantityController,
            keyboardType: TextInputType.number,
            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            enabled: !_isSaving,
            decoration: const InputDecoration(
              labelText: 'Cantidad',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _sizeController,
            enabled: !_isSaving,
            decoration: const InputDecoration(
              labelText: 'Tamaño (ej: 15cm)',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 16),
          ElevatedButton(
            onPressed: _isSaving ? null : _save,
            child: _isSaving
                ? const SizedBox(
                    height: 18,
                    width: 18,
                    child: CircularProgressIndicator(
                        strokeWidth: 2, color: Colors.white),
                  )
                : const Text('Guardar'),
          ),
        ],
      ),
    );
  }

  Future<void> _save() async {
    final quantity = int.tryParse(_quantityController.text);
    final size = _sizeController.text.trim();
    if (quantity == null || quantity < 1) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
            content: Text('La cantidad debe ser un número mayor a 0')),
      );
      return;
    }
    setState(() => _isSaving = true);
    final result = await widget.api.updateJobFields(
      widget.orderId,
      widget.jobId,
      quantity: quantity,
      size: size.isNotEmpty ? size : null,
    );
    if (!mounted) return;
    if (result.success) {
      final sizePart = size.isNotEmpty ? ' · Tamaño: $size' : '';
      showSuccess(
          context, '✔ Trabajo actualizado\nCantidad: $quantity$sizePart');
      Navigator.pop(context);
      widget.onSuccess();
    } else {
      setState(() => _isSaving = false);
      showError(context, result.errorMessage);
    }
  }
}

class _PaymentEditor extends StatefulWidget {
  final QuickEditApiClient api;
  final int orderId;
  final VoidCallback onSuccess;

  const _PaymentEditor({
    required this.api,
    required this.orderId,
    required this.onSuccess,
  });

  @override
  State<_PaymentEditor> createState() => _PaymentEditorState();
}

class _PaymentEditorState extends State<_PaymentEditor> {
  final _amountController = TextEditingController();
  final _methodController = TextEditingController();
  final _noteController = TextEditingController();
  bool _isSaving = false;

  @override
  void dispose() {
    _amountController.dispose();
    _methodController.dispose();
    _noteController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 16,
        right: 16,
        top: 16,
        bottom: MediaQuery.of(context).viewInsets.bottom + 16,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_isSaving) const LinearProgressIndicator(minHeight: 3),
          Text(
            'Registrar cobro',
            style: Theme.of(context)
                .textTheme
                .titleMedium
                ?.copyWith(fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _amountController,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            enabled: !_isSaving,
            decoration: const InputDecoration(
              labelText: 'Monto',
              border: OutlineInputBorder(),
              prefixText: '\$ ',
            ),
            autofocus: true,
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _methodController,
            enabled: !_isSaving,
            decoration: const InputDecoration(
              labelText: 'Método (Efectivo, MP, Transferencia...)',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _noteController,
            enabled: !_isSaving,
            decoration: const InputDecoration(
              labelText: 'Nota (opcional)',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 16),
          ElevatedButton(
            onPressed: _isSaving ? null : _save,
            child: _isSaving
                ? const SizedBox(
                    height: 18,
                    width: 18,
                    child: CircularProgressIndicator(
                        strokeWidth: 2, color: Colors.white),
                  )
                : const Text('Registrar cobro'),
          ),
        ],
      ),
    );
  }

  Future<void> _save() async {
    final amount = double.tryParse(_amountController.text.replaceAll(',', '.'));
    if (amount == null || amount <= 0) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Ingresá un monto válido mayor a 0')),
      );
      return;
    }
    setState(() => _isSaving = true);
    final result = await widget.api.registerPayment(
      widget.orderId,
      amount: amount,
      method: _methodController.text.trim(),
      note: _noteController.text.trim(),
    );
    if (!mounted) return;
    if (result.success) {
      final msg =
          '✔ Cobro registrado: \$${amount.toStringAsFixed(amount.truncateToDouble() == amount ? 0 : 2)}';
      showSuccess(context, msg);
      Navigator.pop(context);
      widget.onSuccess();
    } else {
      setState(() => _isSaving = false);
      showError(context, result.errorMessage);
    }
  }
}

class _DeliveryConfirm extends StatefulWidget {
  final QuickEditApiClient api;
  final int orderId;
  final VoidCallback onSuccess;

  const _DeliveryConfirm({
    required this.api,
    required this.orderId,
    required this.onSuccess,
  });

  @override
  State<_DeliveryConfirm> createState() => _DeliveryConfirmState();
}

class _DeliveryConfirmState extends State<_DeliveryConfirm> {
  bool _isSaving = false;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Marcar como entregado'),
      content: const Text(
        '¿Marcar este pedido como Entregado? '
        'Todos los trabajos pasarán a estado Entregado.',
      ),
      actions: [
        TextButton(
          onPressed: _isSaving ? null : () => Navigator.pop(context),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          onPressed: _isSaving
              ? null
              : () async {
                  setState(() => _isSaving = true);
                  final result = await widget.api.markDelivered(widget.orderId);
                  if (!context.mounted) return;
                  if (result.success) {
                    showSuccess(context, '✔ Pedido marcado como entregado');
                    Navigator.pop(context);
                    widget.onSuccess();
                  } else {
                    setState(() => _isSaving = false);
                    showError(context, result.errorMessage);
                  }
                },
          child: _isSaving
              ? const SizedBox(
                  height: 18,
                  width: 18,
                  child: CircularProgressIndicator(
                      strokeWidth: 2, color: Colors.white),
                )
              : const Text('Entregar'),
        ),
      ],
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// Shared helpers
// ═══════════════════════════════════════════════════════════════════════════

void showSuccess(BuildContext context, String message) {
  final now = TimeOfDay.now();
  final timeStr =
      '${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}';
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      behavior: SnackBarBehavior.floating,
      content: Row(
        children: [
          const Icon(Icons.check_circle, color: Colors.green, size: 20),
          const SizedBox(width: 8),
          Expanded(
            child: Text(message, maxLines: 2, overflow: TextOverflow.ellipsis),
          ),
          Text(
            timeStr,
            style: const TextStyle(
              fontSize: 12,
              color: DoccionePalette.muted,
            ),
          ),
        ],
      ),
      duration: const Duration(seconds: 3),
    ),
  );
}

void showError(BuildContext context, String? errorMessage) {
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      behavior: SnackBarBehavior.floating,
      backgroundColor: Colors.red.shade700,
      content: Row(
        children: [
          const Icon(Icons.error_outline, color: Colors.white, size: 20),
          const SizedBox(width: 8),
          Expanded(child: Text(errorMessage ?? 'Error')),
        ],
      ),
    ),
  );
}
