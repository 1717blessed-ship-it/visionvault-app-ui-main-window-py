import 'dart:convert';
import 'order_draft.dart';

/// DTO V1: envío solo mediante el adaptador de integración explícito.
/// No habilita endpoints ni sincronización productiva.
/// Valida estructura de transporte, no reservas, precios ni reglas de Studio.
class OrderSyncProposal {
  final String operationId;
  final String? desktopOrderId;
  final int expectedRevision;
  final OrderDraft draft;
  const OrderSyncProposal(
      {required this.operationId,
      required this.expectedRevision,
      required this.draft,
      this.desktopOrderId});

  Map<String, dynamic> toJson() {
    if (draft.client.trim().isEmpty || draft.jobs.isEmpty) {
      throw ArgumentError(
          'Un borrador incompleto no es una operación preparada.');
    }
    if (operationId.trim().isEmpty ||
        draft.id.trim().isEmpty ||
        expectedRevision < 0 ||
        (desktopOrderId == null
            ? expectedRevision != 0
            : desktopOrderId!.trim().isEmpty || expectedRevision < 1)) {
      throw ArgumentError('Identidad o revisión de operación inválida.');
    }
    final jobs = <Map<String, dynamic>>[];
    final ids = <String>{};
    for (final job in draft.jobs) {
      job.validate();
      if (job.id.isEmpty || !ids.add(job.id)) {
        throw ArgumentError('Identidad de trabajo inválida.');
      }
      jobs.add({
        'client_job_id': job.id,
        'product_code': job.productCode,
        'variant_code': job.variantCode,
        'material': job.material,
        'size': job.size,
        'quantity': job.quantity,
        'unit_kind': job.unitKind == 'units' ? 'item' : 'sheet',
        'notes': job.notes,
        'designs': job.designs
            .map((d) => {
                  // Tuple encoding is stable and unambiguous even when IDs contain ':' .
                  'association_id': jsonEncode([job.id, d.designId]),
                  'catalog_design_id': d.designId, 'quantity': d.quantity,
                })
            .toList(),
      });
    }
    return {
      'contract_version': 1,
      'operation_id': operationId,
      'client_order_id': draft.id,
      'desktop_order_id': desktopOrderId,
      'expected_revision': expectedRevision,
      'client': draft.client,
      'whatsapp': draft.whatsapp,
      'observations': draft.notes,
      'jobs': jobs
    };
  }

  /// Stable encoding for a retained operation; no success/receipt is fabricated.
  String serialize() => jsonEncode(toJson());
}
