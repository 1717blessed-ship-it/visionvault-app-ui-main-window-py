import 'package:flutter/material.dart';
import 'package:doccione_mobile/models/order_with_details.dart';
import 'package:doccione_mobile/widgets/job_detail_card.dart';

/// Screen to display detailed information about an order
class OrderDetailScreen extends StatelessWidget {
  final OrderWithDetails orderDetails;
  final VoidCallback? onContactWhatsApp;

  const OrderDetailScreen({
    super.key,
    required this.orderDetails,
    this.onContactWhatsApp,
  });

  @override
  Widget build(BuildContext context) {
    final order = orderDetails.order;

    return Scaffold(
      appBar: AppBar(
        title: Text('Pedido #${order.orderNumber ?? order.id.substring(0, 8)}'),
        actions: [
          // WhatsApp button - only show if callback provided and number available
          if (onContactWhatsApp != null && _hasWhatsAppNumber())
            IconButton(
              icon: const Icon(Icons.chat),
              onPressed: onContactWhatsApp,
              tooltip: 'Contactar por WhatsApp',
            ),
        ],
      ),
      body: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Order header card
            Card(
              margin: const EdgeInsets.all(16),
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Status and Priority
                    Row(
                      children: [
                        _buildStatusBadge(context),
                        const SizedBox(width: 8),
                        if (order.printPriority != null && order.printPriority!.isNotEmpty)
                          _buildPriorityBadge(context),
                      ],
                    ),
                    const SizedBox(height: 16),
                    // Client
                    _buildInfoSection(
                      context,
                      Icons.person,
                      'Cliente',
                      orderDetails.client?.name ?? order.client ?? 'Sin cliente',
                    ),
                    // WhatsApp
                    if (_getWhatsAppNumber() != null)
                      _buildInfoSection(
                        context,
                        Icons.phone,
                        'WhatsApp',
                        _getWhatsAppNumber()!,
                      ),
                    // Order Date
                    _buildInfoSection(
                      context,
                      Icons.calendar_today,
                      'Fecha del pedido',
                      orderDetails.formattedOrderDate,
                    ),
                    // Delivery Date
                    _buildInfoSection(
                      context,
                      Icons.event,
                      'Fecha de entrega',
                      orderDetails.formattedDeliveryDate,
                    ),
                    // Material
                    if (order.material != null && order.material!.isNotEmpty)
                      _buildInfoSection(
                        context,
                        Icons.category,
                        'Material',
                        order.material!,
                      ),
                    // Size
                    if (order.size != null && order.size!.isNotEmpty)
                      _buildInfoSection(
                        context,
                        Icons.straighten,
                        'Tamaño',
                        order.size!,
                      ),
                    // Quantity
                    if (order.quantity != null)
                      _buildInfoSection(
                        context,
                        Icons.format_list_numbered,
                        'Cantidad',
                        '${order.quantity}',
                      ),
                  ],
                ),
              ),
            ),
            // Concept
            if (order.orderConcept != null && order.orderConcept!.isNotEmpty)
              Card(
                margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(Icons.lightbulb_outline, color: Colors.grey[600]),
                          const SizedBox(width: 8),
                          Text(
                            'Concepto',
                            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                                  fontWeight: FontWeight.bold,
                                ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Text(
                        order.orderConcept!,
                        style: Theme.of(context).textTheme.bodyMedium,
                      ),
                    ],
                  ),
                ),
              ),
            // Description
            if (order.orderDescription != null && order.orderDescription!.isNotEmpty)
              Card(
                margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(Icons.description_outlined, color: Colors.grey[600]),
                          const SizedBox(width: 8),
                          Text(
                            'Descripción',
                            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                                  fontWeight: FontWeight.bold,
                                ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Text(
                        order.orderDescription!,
                        style: Theme.of(context).textTheme.bodyMedium,
                      ),
                    ],
                  ),
                ),
              ),
            // Observations
            if (order.observations != null && order.observations!.isNotEmpty)
              Card(
                margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(Icons.note_outlined, color: Colors.grey[600]),
                          const SizedBox(width: 8),
                          Text(
                            'Observaciones',
                            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                                  fontWeight: FontWeight.bold,
                                ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Text(
                        order.observations!,
                        style: Theme.of(context).textTheme.bodyMedium,
                      ),
                    ],
                  ),
                ),
              ),
            // Jobs section
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 24, 16, 12),
              child: Row(
                children: [
                  Icon(Icons.work_outline, color: Colors.grey[700]),
                  const SizedBox(width: 8),
                  Text(
                    'Trabajos (${orderDetails.jobsCount})',
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                  ),
                ],
              ),
            ),
            // Jobs list
            if (orderDetails.hasJobs)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Column(
                  children: orderDetails.jobs
                      .asMap()
                      .entries
                      .map(
                        (entry) => JobDetailCard(
                          job: entry.value,
                          index: entry.key,
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
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          color: Colors.grey[600],
                        ),
                  ),
                ),
              ),
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }

  Widget _buildInfoSection(
    BuildContext context,
    IconData icon,
    String label,
    String value,
  ) {
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
                Text(
                  label,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Colors.grey[600],
                        fontWeight: FontWeight.w500,
                      ),
                ),
                const SizedBox(height: 2),
                Text(
                  value,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        fontWeight: FontWeight.w500,
                      ),
                ),
              ],
            ),
          ),
        ],
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
          Text(
            label,
            style: TextStyle(
              color: textColor,
              fontSize: 13,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPriorityBadge(BuildContext context) {
    final priority = orderDetails.order.printPriority!.toLowerCase();
    
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
          Text(
            label,
            style: TextStyle(
              color: textColor,
              fontSize: 13,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }

  bool _hasWhatsAppNumber() {
    return _getWhatsAppNumber() != null;
  }

  String? _getWhatsAppNumber() {
    // Only use order.whatsapp field - no fallback to client.phone
    if (orderDetails.order.whatsapp != null && orderDetails.order.whatsapp!.isNotEmpty) {
      return orderDetails.order.whatsapp;
    }
    return null;
  }
}
