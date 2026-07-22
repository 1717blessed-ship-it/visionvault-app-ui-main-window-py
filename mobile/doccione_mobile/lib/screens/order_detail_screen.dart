import 'package:flutter/material.dart';
import 'package:doccione_mobile/models/order.dart';
import 'package:doccione_mobile/models/order_with_details.dart';
import 'package:doccione_mobile/widgets/job_detail_card.dart';
import 'package:doccione_mobile/widgets/stage_timeline.dart';
import 'package:doccione_mobile/widgets/quick_action_sheet.dart';
import 'package:doccione_mobile/services/quick_edit_api_client.dart';

enum _SyncState { synced, saving, error }

/// Screen to display detailed information about an order
class OrderDetailScreen extends StatefulWidget {
  final OrderWithDetails orderDetails;
  final VoidCallback? onContactWhatsApp;
  final QuickEditApiClient? apiClient;
  final VoidCallback? onRefresh;

  const OrderDetailScreen({
    super.key,
    required this.orderDetails,
    this.onContactWhatsApp,
    this.apiClient,
    this.onRefresh,
  });

  @override
  State<OrderDetailScreen> createState() => _OrderDetailScreenState();
}

class _OrderDetailScreenState extends State<OrderDetailScreen>
    with SingleTickerProviderStateMixin {
  late OrderWithDetails _orderDetails;
  _SyncState _syncState = _SyncState.synced;
  DateTime? _lastSyncTime;

  // ── Status change animation ──────────────────────────────────────────
  late AnimationController _flashController;
  bool _showCheckmark = false;

  @override
  void initState() {
    super.initState();
    _orderDetails = widget.orderDetails;
    _lastSyncTime = DateTime.now();
    _flashController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 250),
    );
  }

  @override
  void dispose() {
    _flashController.dispose();
    super.dispose();
  }

  @override
  void didUpdateWidget(covariant OrderDetailScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.orderDetails != oldWidget.orderDetails) {
      _orderDetails = widget.orderDetails;
    }
  }

  Order get _order => _orderDetails.order;
  bool get _hasApi => widget.apiClient != null;
  int? get _orderId => int.tryParse(_order.id);

  void _openQuickAction(QuickAction action, {int? jobId, String? currentStage, int? currentQuantity, String? currentSize}) {
    if (!_hasApi || _orderId == null) return;
    setState(() => _syncState = _SyncState.saving);
    QuickActionSheet.show(
      context,
      action: action,
      api: widget.apiClient!,
      orderId: _orderId!,
      onSuccess: () => _applyEdit(action),
      jobId: jobId,
      currentStatus: _order.status,
      currentPriority: int.tryParse(_order.printPriority ?? '') ?? 0,
      currentStage: currentStage,
      currentQuantity: currentQuantity,
      currentSize: currentSize,
    );
  }

  void _applyEdit(QuickAction action) {
    setState(() {
      _syncState = _SyncState.synced;
      _lastSyncTime = DateTime.now();
      switch (action) {
        case QuickAction.status:
          widget.onRefresh?.call();
          _flashBadge();
          return;
        case QuickAction.priority:
          widget.onRefresh?.call();
          return;
        case QuickAction.delivery:
          _orderDetails = OrderWithDetails(
            order: _order.copyWith(status: 'Entregado'),
            client: _orderDetails.client,
            jobs: _orderDetails.jobs.map((j) => j.copyWith(status: 'Entregado')).toList(),
          );
          _flashBadge();
          break;
        case QuickAction.payment:
          widget.onRefresh?.call();
          return;
        case QuickAction.jobStage:
        case QuickAction.jobQuantitySize:
          widget.onRefresh?.call();
          return;
      }
    });
  }

  void _flashBadge() {
    _flashController.forward(from: 0).then((_) {
      if (mounted) setState(() => _showCheckmark = false);
    });
    setState(() => _showCheckmark = true);
  }

  void _onJobEdited(int jobIndex, {String? status, int? quantity, String? size}) {
    final jobs = List.of(_orderDetails.jobs);
    if (jobIndex < 0 || jobIndex >= jobs.length) return;
    final old = jobs[jobIndex];
    jobs[jobIndex] = old.copyWith(
      status: status ?? old.status,
      quantity: quantity ?? old.quantity,
      size: size ?? old.size,
    );
    setState(() {
      _orderDetails = OrderWithDetails(
        order: _orderDetails.order,
        client: _orderDetails.client,
        jobs: jobs,
      );
      _lastSyncTime = DateTime.now();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('Pedido #${_order.orderNumber ?? (_order.id.length > 8 ? _order.id.substring(0, 8) : _order.id)}'),
        actions: [
          if (_hasApi && _orderId != null)
            PopupMenuButton<String>(
              icon: const Icon(Icons.edit),
              tooltip: 'Edición rápida',
              onSelected: (action) => _handleQuickAction(action),
              itemBuilder: (context) => [
                const PopupMenuItem(value: 'status', child: Text('Cambiar estado')),
                const PopupMenuItem(value: 'priority', child: Text('Cambiar prioridad')),
                const PopupMenuItem(value: 'deliver', child: Text('Marcar entregado')),
                const PopupMenuItem(value: 'payment', child: Text('Registrar cobro')),
              ],
            ),
          if (widget.onContactWhatsApp != null && _hasWhatsAppNumber())
            IconButton(
              icon: const Icon(Icons.chat),
              onPressed: widget.onContactWhatsApp,
              tooltip: 'Contactar por WhatsApp',
            ),
        ],
      ),
      body: Column(
        children: [
          if (_hasApi) _buildSyncIndicator(),
          Expanded(
            child: SingleChildScrollView(
              child: _buildContent(),
            ),
          ),
        ],
      ),
    );
  }

  // ── Sync indicator: 3 states ────────────────────────────────────────

  Widget _buildSyncIndicator() {
    final (Color bg, Color fg, IconData icon, String text) = switch (_syncState) {
      _SyncState.saving => (
        Colors.orange.shade50,
        Colors.orange.shade700,
        Icons.sync,
        'Guardando...',
      ),
      _SyncState.error => (
        Colors.red.shade50,
        Colors.red.shade700,
        Icons.error_outline,
        'Error al guardar',
      ),
      _SyncState.synced => (
        Colors.green.shade50,
        Colors.green.shade700,
        Icons.check_circle_outline,
        _formatSyncTime(),
      ),
    };

    return AnimatedContainer(
      duration: const Duration(milliseconds: 200),
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      color: bg,
      child: Row(
        children: [
          Icon(icon, size: 14, color: fg),
          const SizedBox(width: 6),
          Text(text, style: TextStyle(fontSize: 12, color: fg)),
        ],
      ),
    );
  }

  String _formatSyncTime() {
    if (_lastSyncTime == null) return 'Sincronizado';
    final diff = DateTime.now().difference(_lastSyncTime!);
    if (diff.inSeconds < 60) return 'Sincronizado hace ${diff.inSeconds}s';
    if (diff.inMinutes < 60) return 'Sincronizado hace ${diff.inMinutes}m';
    return 'Sincronizado hace ${diff.inHours}h';
  }

  // ── Content ─────────────────────────────────────────────────────────

  Widget _buildContent() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Card(
          margin: const EdgeInsets.all(16),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    _buildStatusBadge(context),
                    const SizedBox(width: 8),
                    if (_order.printPriority != null && _order.printPriority!.isNotEmpty)
                      _buildPriorityBadge(context),
                  ],
                ),
                const SizedBox(height: 16),
                _buildInfoSection(context, Icons.person, 'Cliente', _orderDetails.client?.name ?? _order.client ?? 'Sin cliente'),
                if (_getWhatsAppNumber() != null)
                  _buildInfoSection(context, Icons.phone, 'WhatsApp', _getWhatsAppNumber()!),
                _buildInfoSection(context, Icons.calendar_today, 'Fecha del pedido', _orderDetails.formattedOrderDate),
                _buildInfoSection(context, Icons.event, 'Fecha de entrega', _orderDetails.formattedDeliveryDate),
                if (_order.material != null && _order.material!.isNotEmpty)
                  _buildInfoSection(context, Icons.category, 'Material', _order.material!),
                if (_order.size != null && _order.size!.isNotEmpty)
                  _buildInfoSection(context, Icons.straighten, 'Tamaño', _order.size!),
                if (_order.quantity != null)
                  _buildInfoSection(context, Icons.format_list_numbered, 'Cantidad', '${_order.quantity}'),
              ],
            ),
          ),
        ),
        if (_order.orderConcept != null && _order.orderConcept!.isNotEmpty)
          _buildTextCard(context, 'Concepto', Icons.lightbulb_outline, _order.orderConcept!),
        if (_order.orderDescription != null && _order.orderDescription!.isNotEmpty)
          _buildTextCard(context, 'Descripción', Icons.description_outlined, _order.orderDescription!),
        if (_order.observations != null && _order.observations!.isNotEmpty)
          _buildTextCard(context, 'Observaciones', Icons.note_outlined, _order.observations!),
        // ── Interactive timeline for jobs ──
        if (_orderDetails.hasJobs)
          for (int i = 0; i < _orderDetails.jobs.length; i++)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
              child: StageTimeline(
                currentStage: _orderDetails.jobs[i].status ?? 'Recibido',
                apiClient: widget.apiClient,
                orderId: _orderId,
                jobId: int.tryParse(_orderDetails.jobs[i].id),
                onStageChanged: () {
                  setState(() {
                    _syncState = _SyncState.synced;
                    _lastSyncTime = DateTime.now();
                  });
                  widget.onRefresh?.call();
                },
              ),
            ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 24, 16, 12),
          child: Row(
            children: [
              Icon(Icons.work_outline, color: Colors.grey[700]),
              const SizedBox(width: 8),
              Text(
                'Trabajos (${_orderDetails.jobsCount})',
                style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold),
              ),
            ],
          ),
        ),
        if (_orderDetails.hasJobs)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Column(
              children: _orderDetails.jobs
                  .asMap()
                  .entries
                  .map(
                    (entry) => JobDetailCard(
                      job: entry.value,
                      index: entry.key,
                      apiClient: widget.apiClient,
                      orderId: _orderId,
                      onRefresh: widget.onRefresh,
                      onJobEdited: (status, quantity, size) => _onJobEdited(entry.key, status: status, quantity: quantity, size: size),
                    ),
                  )
                  .toList(),
            ),
          )
        else
          Padding(
            padding: const EdgeInsets.all(16),
            child: Center(
              child: Text(
                'No hay trabajos asociados a este pedido',
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: Colors.grey[600]),
              ),
            ),
          ),
        const SizedBox(height: 24),
      ],
    );
  }

  void _handleQuickAction(String action) {
    switch (action) {
      case 'status':
        _openQuickAction(QuickAction.status);
        break;
      case 'priority':
        _openQuickAction(QuickAction.priority);
        break;
      case 'deliver':
        _openQuickAction(QuickAction.delivery);
        break;
      case 'payment':
        _openQuickAction(QuickAction.payment);
        break;
    }
  }

  Widget _buildInfoSection(BuildContext context, IconData icon, String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 20, color: Colors.grey[600]),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label, style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey[600], fontWeight: FontWeight.w500)),
                const SizedBox(height: 2),
                Text(value, style: Theme.of(context).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w500)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildStatusBadge(BuildContext context) {
    final status = _order.status ?? 'unknown';
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

    return AnimatedBuilder(
      animation: _flashController,
      builder: (context, child) {
        final isFlashing = _flashController.isAnimating;
        return Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          decoration: BoxDecoration(
            color: isFlashing ? Colors.green.shade100 : backgroundColor,
            borderRadius: BorderRadius.circular(16),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (_showCheckmark && isFlashing)
                Icon(Icons.check, size: 16, color: Colors.green.shade700)
              else
                Icon(icon, size: 16, color: textColor),
              const SizedBox(width: 6),
              Text(label, style: TextStyle(color: textColor, fontSize: 13, fontWeight: FontWeight.w600)),
            ],
          ),
        );
      },
    );
  }

  Widget _buildPriorityBadge(BuildContext context) {
    final priority = _order.printPriority!.toLowerCase();
    Color backgroundColor;
    Color textColor;
    String label;
    IconData icon;

    switch (priority) {
      case 'high':
      case 'alta':
        backgroundColor = Colors.red.shade50;
        textColor = Colors.red.shade700;
        label = 'Prioridad Alta';
        icon = Icons.priority_high;
        break;
      case 'medium':
      case 'media':
        backgroundColor = Colors.orange.shade50;
        textColor = Colors.orange.shade700;
        label = 'Prioridad Media';
        icon = Icons.remove;
        break;
      case 'low':
      case 'baja':
        backgroundColor = Colors.blue.shade50;
        textColor = Colors.blue.shade700;
        label = 'Prioridad Baja';
        icon = Icons.arrow_downward;
        break;
      default:
        backgroundColor = Colors.grey.shade50;
        textColor = Colors.grey.shade700;
        label = priority;
        icon = Icons.flag;
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: backgroundColor,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 16, color: textColor),
          const SizedBox(width: 6),
          Text(label, style: TextStyle(color: textColor, fontSize: 13, fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }

  Widget _buildTextCard(BuildContext context, String title, IconData icon, String content) {
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, color: Colors.grey[600]),
                const SizedBox(width: 8),
                Text(title, style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
              ],
            ),
            const SizedBox(height: 8),
            Text(content, style: Theme.of(context).textTheme.bodyMedium),
          ],
        ),
      ),
    );
  }

  bool _hasWhatsAppNumber() => _getWhatsAppNumber() != null;

  String? _getWhatsAppNumber() {
    if (_order.whatsapp != null && _order.whatsapp!.isNotEmpty) {
      return _order.whatsapp;
    }
    return null;
  }
}
