import 'package:flutter/material.dart';
import 'package:doccione_mobile/models/job.dart';

/// Widget to display job details in a card format
class JobDetailCard extends StatelessWidget {
  final Job job;
  final int index;

  const JobDetailCard({
    super.key,
    required this.job,
    required this.index,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                // Job number/index
                Container(
                  width: 32,
                  height: 32,
                  decoration: BoxDecoration(
                    color: Theme.of(context).primaryColor.withOpacity(0.1),
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
                // Title
                Expanded(
                  child: Text(
                    job.title ?? 'Sin título',
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                  ),
                ),
                // Status badge
                _buildStatusBadge(context),
              ],
            ),
            const SizedBox(height: 12),
            // Material
            if (job.material != null && job.material!.isNotEmpty)
              _buildInfoRow(
                context,
                Icons.category_outlined,
                'Material',
                job.material!,
              ),
            // Size
            if (job.size != null && job.size!.isNotEmpty)
              _buildInfoRow(
                context,
                Icons.straighten,
                'Tamaño',
                job.size!,
              ),
            // Quantity
            if (job.quantity != null)
              _buildInfoRow(
                context,
                Icons.format_list_numbered,
                'Cantidad',
                '${job.quantity}',
              ),
            // Notes
            if (job.notes != null && job.notes!.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.grey.shade50,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(
                        Icons.note_outlined,
                        size: 16,
                        color: Colors.grey[600],
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          job.notes!,
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                color: Colors.grey[700],
                              ),
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
  }

  Widget _buildInfoRow(
    BuildContext context,
    IconData icon,
    String label,
    String value,
  ) {
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Row(
        children: [
          Icon(icon, size: 16, color: Colors.grey[600]),
          const SizedBox(width: 8),
          Text(
            '$label: ',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Colors.grey[600],
                  fontWeight: FontWeight.w500,
                ),
          ),
          Expanded(
            child: Text(
              value,
              style: Theme.of(context).textTheme.bodyMedium,
            ),
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
        backgroundColor = Colors.blue.shade50;
        textColor = Colors.blue.shade700;
        label = 'Pendiente';
        break;
      case 'in_progress':
      case 'production':
        backgroundColor = Colors.orange.shade50;
        textColor = Colors.orange.shade700;
        label = 'En Proceso';
        break;
      case 'completed':
        backgroundColor = Colors.green.shade50;
        textColor = Colors.green.shade700;
        label = 'Completado';
        break;
      case 'cancelled':
        backgroundColor = Colors.red.shade50;
        textColor = Colors.red.shade700;
        label = 'Cancelado';
        break;
      default:
        backgroundColor = Colors.grey.shade50;
        textColor = Colors.grey.shade700;
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
          color: textColor,
          fontSize: 11,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}
