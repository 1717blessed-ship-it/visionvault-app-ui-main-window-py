import 'dart:async';
import 'dart:convert';

import 'package:doccione_mobile/services/quick_edit_api_client.dart';
import 'package:doccione_mobile/widgets/quick_action_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  testWidgets(
      'cancelling updates Studio status then removes only the local copy',
      (tester) async {
    var cancelledLocally = false;
    var regularSuccess = false;
    final client = QuickEditApiClient(
      baseUrl: 'http://localhost:8766',
      authToken: 'token',
      httpClient: MockClient((request) async {
        expect(request.method, 'PATCH');
        expect(request.url.path, '/api/v1/mobile/orders/42/status');
        expect(jsonDecode(request.body)['status'], 'Cancelado');
        return http.Response(
          jsonEncode({'success': true}),
          200,
          headers: {'content-type': 'application/json'},
        );
      }),
    );
    addTearDown(client.close);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => FilledButton(
              onPressed: () => QuickActionSheet.show(
                context,
                action: QuickAction.status,
                api: client,
                orderId: 42,
                currentStatus: 'Pendiente',
                onSuccess: () => regularSuccess = true,
                onCancelled: () async => cancelledLocally = true,
              ),
              child: const Text('Editar estado'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Editar estado'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cancelado'));
    await tester.pumpAndSettle();

    expect(cancelledLocally, isTrue);
    expect(regularSuccess, isFalse);
    expect(
        find.text('Pedido cancelado y quitado de este móvil'), findsOneWidget);
  });

  testWidgets('priority editor stays mounted until Studio confirms the change',
      (tester) async {
    final response = Completer<http.Response>();
    var refreshed = false;
    final client = QuickEditApiClient(
      baseUrl: 'http://localhost:8766',
      authToken: 'token',
      httpClient: MockClient((request) async {
        expect(request.method, 'PATCH');
        expect(request.url.path, '/api/v1/mobile/orders/42/priority');
        expect(jsonDecode(request.body)['print_priority'], 4);
        return response.future;
      }),
    );
    addTearDown(client.close);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => FilledButton(
              onPressed: () => QuickActionSheet.show(
                context,
                action: QuickAction.priority,
                api: client,
                orderId: 42,
                currentPriority: 0,
                onSuccess: () => refreshed = true,
              ),
              child: const Text('Editar prioridad'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Editar prioridad'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Urgente'));
    await tester.pump();

    expect(find.text('Cambiar prioridad'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    expect(refreshed, isFalse);

    response.complete(http.Response(
      jsonEncode({'success': true}),
      200,
      headers: {'content-type': 'application/json'},
    ));
    await tester.pumpAndSettle();

    expect(refreshed, isTrue);
    expect(find.text('✔ Prioridad cambiada a "Urgente"'), findsOneWidget);
  });
}
