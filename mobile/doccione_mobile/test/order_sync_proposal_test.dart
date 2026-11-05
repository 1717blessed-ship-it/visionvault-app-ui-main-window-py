import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:doccione_mobile/models/order_draft.dart';
import 'package:doccione_mobile/models/order_sync_proposal.dart';

void main() {
  OrderDraft draft() =>
      OrderDraft(id: 'local-1', client: 'Cliente prueba', jobs: [
        OrderWork(
            id: 'job-1',
            productCode: 'fixture',
            productName: 'Fixture',
            quantity: 100,
            designs: const [
              DesignAllocation(designId: 'opaque:a', name: 'A', quantity: 40)
            ]),
        OrderWork(
            id: 'job-2',
            productCode: 'fixture',
            productName: 'Fixture',
            quantity: 2,
            unitKind: 'sheets')
      ]);
  test(
      'serializa propuesta v1 con unidades Desktop explícitas y pendientes locales intactos',
      () {
    final local = draft();
    final proposal = OrderSyncProposal(
        operationId: 'operation-1', expectedRevision: 0, draft: local);
    final data = jsonDecode(proposal.serialize()) as Map<String, dynamic>;
    expect(data['contract_version'], 1);
    expect(
        (data['jobs'] as List).map((j) => j['unit_kind']), ['item', 'sheet']);
    expect(local.jobs.first.pending, 60);
    expect(data.containsKey('price'), false);
    expect(data.containsKey('status'), false);
    expect(data.containsKey('persisted'), false);
  });
  test('misma operación serializa igual; asociaciones estables tras recuperar',
      () {
    final local = draft();
    final restored = OrderDraft.fromJson(
        jsonDecode(jsonEncode(local.toJson())) as Map<String, dynamic>);
    expect(
        OrderSyncProposal(
                operationId: 'same', expectedRevision: 0, draft: local)
            .serialize(),
        OrderSyncProposal(
                operationId: 'same', expectedRevision: 0, draft: restored)
            .serialize());
  });
  test('edición exige identidad remota y revisión positiva', () {
    expect(
        () => OrderSyncProposal(
                operationId: 'op', expectedRevision: 1, draft: draft())
            .serialize(),
        throwsArgumentError);
    expect(
        () => OrderSyncProposal(
                operationId: 'op',
                expectedRevision: 0,
                desktopOrderId: '1',
                draft: draft())
            .serialize(),
        throwsArgumentError);
    expect(
        () => OrderSyncProposal(
                operationId: '', expectedRevision: 0, draft: draft())
            .serialize(),
        throwsArgumentError);
    expect(
        OrderSyncProposal(
                operationId: 'op',
                expectedRevision: 2,
                desktopOrderId: '1',
                draft: draft())
            .toJson()['expected_revision'],
        2);
  });
  test('borrador incompleto sigue siendo local y no es publicable', () {
    expect(
        () => OrderSyncProposal(
                operationId: 'op', expectedRevision: 0, draft: OrderDraft())
            .serialize(),
        throwsArgumentError);
  });
}
