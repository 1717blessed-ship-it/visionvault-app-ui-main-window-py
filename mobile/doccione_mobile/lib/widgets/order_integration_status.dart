import 'dart:convert';
import 'package:flutter/material.dart';
import '../services/order_integration_sync.dart';

/// Only shown when an isolated controller is explicitly injected in the editor.
class OrderIntegrationStatus extends StatelessWidget {
  final OrderIntegrationSync sync;
  final String localId;
  final int localRevision;
  final bool dirty, busy;
  final VoidCallback enqueue, refresh;
  const OrderIntegrationStatus(
      {super.key,
      required this.sync,
      required this.localId,
      required this.localRevision,
      required this.dirty,
      required this.busy,
      required this.enqueue,
      required this.refresh});
  @override
  Widget build(BuildContext context) => AnimatedBuilder(
      animation: sync,
      builder: (context, _) => FutureBuilder<List<Map<String, Object?>>>(
          future: sync.store.operations(sync.client.target),
          builder: (context, result) {
            final all = result.data ?? [];
            final own = all
                .where((r) => r['local_id'] == localId && r['active'] == 1)
                .toList();
            final last = own.isEmpty ? null : own.last;
            final pending = all
                .where((r) => r['state'] != 'confirmed' && r['active'] == 1)
                .length;
            var state = last?['state'] as String? ?? 'local';
            if (state == 'confirmed' &&
                (dirty || last?['local_revision'] != localRevision)) {
              state = 'local';
            }
            final enumState = OrderTransferState.values.firstWhere(
                (v) => v.name == state,
                orElse: () => OrderTransferState.local);
            final label = transferLabels[enumState]!;
            return Card(
                color: Colors.amber.shade50,
                child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text('INTEGRACIÓN AISLADA · NO PRODUCCIÓN',
                              style: TextStyle(fontWeight: FontWeight.bold)),
                          Text(sync.connection),
                          Text(label, key: const Key('order-transfer-state')),
                          Text('$pending operaciones pendientes'),
                          if (last?['receipt'] != null)
                            Text(
                                'Última confirmación: ${last!['confirmed_at']} · ${objectReceipt(last['receipt'] as String)}'),
                          if (last?['error'] != null)
                            Text(
                                'Error: ${last!['error']} · cambios locales conservados'),
                          if (state == 'conflict')
                            TextButton(
                                onPressed: () => showDialog<void>(
                                    context: context,
                                    builder: (context) => AlertDialog(
                                            title: const Text(
                                                'Conflicto · sin fusión automática'),
                                            content: SingleChildScrollView(
                                                child: SelectableText(
                                                    'Operación local conservada:\n${last!['payload']}\n\nVersión Desktop:\n${last['remote_conflict'] ?? 'Consultar nuevamente; no disponible offline.'}')),
                                            actions: [
                                              TextButton(
                                                  onPressed: () =>
                                                      Navigator.pop(context),
                                                  child: const Text(
                                                      'Conservar ambas'))
                                            ])),
                                child: const Text('Consultar ambas versiones')),
                          Wrap(spacing: 8, children: [
                            if (state == 'conflict')
                              OutlinedButton(
                                  onPressed: busy || dirty || sync.running
                                      ? null
                                      : () async {
                                          final accepted = await showDialog<
                                                  bool>(
                                              context: context,
                                              builder: (context) => AlertDialog(
                                                      title: const Text(
                                                          'Proponer cabecera local explícitamente'),
                                                      content: const Text(
                                                          'Se consultará la revisión Desktop vigente. Solo se permite si trabajos, cantidades y diseños coinciden. Se conserva el rechazo original y se crea una operación nueva pendiente. No se envía automáticamente.'),
                                                      actions: [
                                                        TextButton(
                                                            onPressed: () =>
                                                                Navigator.pop(
                                                                    context,
                                                                    false),
                                                            child: const Text(
                                                                'Volver')),
                                                        FilledButton(
                                                            onPressed: () =>
                                                                Navigator.pop(
                                                                    context,
                                                                    true),
                                                            child: const Text(
                                                                'Preparar propuesta explícita'))
                                                      ]));
                                          if (accepted != true) return;
                                          try {
                                            await sync.resolveHeaderConflict(
                                                last!['operation_id']
                                                    as String);
                                          } catch (e) {
                                            if (context.mounted) {
                                              ScaffoldMessenger.of(context)
                                                  .showSnackBar(SnackBar(
                                                      content: Text(
                                                          'Sin fusionar datos: $e')));
                                            }
                                          }
                                        },
                                  child: const Text('Resolver solo cabecera')),
                            OutlinedButton(
                                onPressed: busy || dirty || sync.running
                                    ? null
                                    : enqueue,
                                child: const Text('Preparar envío aislado')),
                            OutlinedButton(
                                onPressed: busy || sync.running
                                    ? null
                                    : () => sync.drain(),
                                child: const Text('Sincronizar cola aislada')),
                            OutlinedButton(
                                onPressed: busy || dirty || sync.running
                                    ? null
                                    : refresh,
                                child: const Text('Consultar cambios Desktop')),
                            if (state == 'intervention' ||
                                state == 'recoverable')
                              OutlinedButton(
                                  onPressed: sync.running
                                      ? null
                                      : () async {
                                          await sync.retry(
                                              last!['operation_id'] as String);
                                        },
                                  child:
                                      const Text('Reintentar tras corregir')),
                          ]),
                          const Text(
                              'Un guardado local no es una confirmación. Precios y etapas: autoridad de Desktop.'),
                        ])));
          }));
}

String objectReceipt(String raw) {
  final receipt = jsonDecode(raw) as Map;
  return 'pedido ${receipt['desktop_order_id']} · revisión ${receipt['revision']}';
}
