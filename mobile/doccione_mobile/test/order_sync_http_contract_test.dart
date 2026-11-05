import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:doccione_mobile/models/order_draft.dart';
import 'package:doccione_mobile/models/order_sync_proposal.dart';

void main() {
  test('DTO Flutter coincide con fixture enviado por HTTP real aislado', () {
    final data = jsonDecode(
        File('../../tests/fixtures/order_sync_v1_request.json')
            .readAsStringSync()) as Map<String, dynamic>;
    final jobs = (data['jobs'] as List)
        .map((j) => OrderWork(
            id: j['client_job_id'] as String,
            productCode: j['product_code'] as String,
            productName: 'Fixture',
            variantCode: j['variant_code'] as String,
            material: j['material'] as String,
            size: j['size'] as String,
            quantity: j['quantity'] as int,
            unitKind: j['unit_kind'] == 'item' ? 'units' : 'sheets',
            notes: j['notes'] as String))
        .toList();
    final draft = OrderDraft(
        id: data['client_order_id'] as String,
        client: data['client'] as String,
        whatsapp: data['whatsapp'] as String,
        notes: data['observations'] as String,
        jobs: jobs);
    final proposed = OrderSyncProposal(
        operationId: data['operation_id'] as String,
        expectedRevision: data['expected_revision'] as int,
        draft: draft);
    expect(proposed.toJson(), data);
  });
}
