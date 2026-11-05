import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:doccione_mobile/models/order_draft.dart';
import 'package:doccione_mobile/database/database_helper.dart';
import 'package:doccione_mobile/database/order_drafts_repository.dart';
import 'package:doccione_mobile/screens/unified_order_creation_screen.dart';
import 'package:doccione_mobile/services/catalog_api_client.dart';

class MemoryDrafts extends OrderDraftsRepository {
  OrderDraft? saved;
  MemoryDrafts() : super(DatabaseHelper());
  @override
  Future<List<OrderDraft>> all() async => saved == null ? [] : [saved!];
  @override
  Future<OrderDraft> save(OrderDraft draft) async {
    saved = OrderDraft(
        id: draft.id,
        revision: draft.revision + 1,
        client: draft.client,
        whatsapp: draft.whatsapp,
        notes: draft.notes,
        jobs: draft.jobs);
    return saved!;
  }
}

void main() {
  testWidgets('guardado incompleto explícitamente local y recuperable',
      (tester) async {
    final repo = MemoryDrafts();
    final api = CatalogApiClient(
        baseUrl: 'https://fixture.invalid',
        authToken: 'test',
        httpClient:
            MockClient((_) async => http.Response('{"products":[]}', 200)));
    addTearDown(api.close);
    await tester.pumpWidget(MaterialApp(
        home: UnifiedOrderCreationScreen(
            baseUrl: api.baseUrl,
            sessionToken: 'test',
            api: api,
            repository: repo)));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'Cliente de prueba');
    await tester.tap(find.text('Guardar borrador (incluso incompleto)'));
    await tester.pumpAndSettle();
    expect(repo.saved!.client, 'Cliente de prueba');
    expect(find.textContaining('NO enviado a Desktop'), findsOneWidget);
    await tester.tap(find.byTooltip('Recuperar borrador'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(ListTile, 'Cliente de prueba'));
    await tester.pumpAndSettle();
    expect(find.text('Recuperado local · no sincronizado'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets('no ofrece productos ficticios ni precio definitivo',
      (tester) async {
    final api = CatalogApiClient(
        baseUrl: 'https://fixture.invalid',
        authToken: 'test',
        httpClient:
            MockClient((_) async => http.Response('{"products":[]}', 200)));
    addTearDown(api.close);
    await tester.pumpWidget(MaterialApp(
        home: UnifiedOrderCreationScreen(
            baseUrl: api.baseUrl,
            sessionToken: 'test',
            api: api,
            repository: MemoryDrafts())));
    await tester.pumpAndSettle();
    expect(find.textContaining('Presupuesto pendiente'), findsOneWidget);
    expect(find.text('Sticker Pack'), findsNothing);
    final button = tester.widget<OutlinedButton>(
        find.widgetWithText(OutlinedButton, 'Agregar trabajo'));
    expect(button.onPressed, isNull);
  });
}
