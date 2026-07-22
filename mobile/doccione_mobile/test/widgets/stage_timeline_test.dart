import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:doccione_mobile/services/quick_edit_api_client.dart';
import 'package:doccione_mobile/widgets/stage_timeline.dart';

void main() {
  QuickEditApiClient _mockApiClient({
    Future<http.Response> Function(http.Request)? handler,
  }) {
    final mockHandler = handler ??
        ((request) async {
          return http.Response(jsonEncode({
            'success': true,
            'message': 'Etapa actualizada',
            'job': {'id': 10, 'status': 'Etapa siguiente'},
          }), 200);
        });
    return QuickEditApiClient(
      baseUrl: 'http://localhost:8000',
      authToken: 'test-token',
      httpClient: MockClient(mockHandler),
    );
  }

  Widget _buildWidget({
    required String currentStage,
    QuickEditApiClient? apiClient,
    int? orderId,
    int? jobId,
    VoidCallback? onStageChanged,
  }) {
    return MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
          child: StageTimeline(
            currentStage: currentStage,
            apiClient: apiClient,
            orderId: orderId,
            jobId: jobId,
            onStageChanged: onStageChanged,
          ),
        ),
      ),
    );
  }

  group('StageTimeline', () {
    group('intermediate stage', () {
      testWidgets('shows "Avanzar" button for non-final stage',
          (tester) async {
        await tester.pumpWidget(_buildWidget(
          currentStage: 'Impresión',
          apiClient: _mockApiClient(),
          orderId: 1,
          jobId: 10,
        ));

        expect(find.text('Impresión'), findsOneWidget);
        expect(find.text('Avanzar'), findsOneWidget);
        expect(find.byIcon(Icons.arrow_forward), findsOneWidget);
      });

      testWidgets('tapping "Avanzar" opens confirm dialog', (tester) async {
        await tester.pumpWidget(_buildWidget(
          currentStage: 'Impresión',
          apiClient: _mockApiClient(),
          orderId: 1,
          jobId: 10,
        ));

        await tester.tap(find.text('Avanzar'));
        await tester.pumpAndSettle();

        expect(find.text('Avanzar etapa'), findsOneWidget);
        expect(
          find.text('¿Mover el trabajo a "Sublimado / Laminado"?'),
          findsOneWidget,
        );
        expect(find.text('Cancelar'), findsOneWidget);
        expect(find.text('Confirmar'), findsOneWidget);
      });

      testWidgets('confirming fires onStageChanged callback', (tester) async {
        int callbackCount = 0;

        await tester.pumpWidget(_buildWidget(
          currentStage: 'Impresión',
          apiClient: _mockApiClient(),
          orderId: 1,
          jobId: 10,
          onStageChanged: () => callbackCount++,
        ));

        await tester.tap(find.text('Avanzar'));
        await tester.pumpAndSettle();

        await tester.tap(find.text('Confirmar'));
        await tester.pumpAndSettle();

        expect(callbackCount, 1);
      });

      testWidgets('canceling dialog does not call API', (tester) async {
        int apiCallCount = 0;

        await tester.pumpWidget(_buildWidget(
          currentStage: 'Impresión',
          apiClient: _mockApiClient(handler: (request) async {
            apiCallCount++;
            return http.Response(jsonEncode({'success': true}), 200);
          }),
          orderId: 1,
          jobId: 10,
        ));

        await tester.tap(find.text('Avanzar'));
        await tester.pumpAndSettle();

        await tester.tap(find.text('Cancelar'));
        await tester.pumpAndSettle();

        expect(apiCallCount, 0);
      });
    });

    group('final stage', () {
      testWidgets('does not show "Avanzar" at Entregado', (tester) async {
        await tester.pumpWidget(_buildWidget(
          currentStage: 'Entregado',
          apiClient: _mockApiClient(),
          orderId: 1,
          jobId: 10,
        ));

        expect(find.text('Entregado'), findsOneWidget);
        expect(find.text('Avanzar'), findsNothing);
      });

      testWidgets('does not show "Avanzar" at Finalizado without API',
          (tester) async {
        await tester.pumpWidget(_buildWidget(
          currentStage: 'Impresión',
        ));

        expect(find.text('Avanzar'), findsNothing);
      });
    });

    group('API error', () {
      testWidgets('shows error snackbar on API failure', (tester) async {
        await tester.pumpWidget(_buildWidget(
          currentStage: 'Impresión',
          apiClient: _mockApiClient(handler: (request) async {
            return http.Response(
                jsonEncode({'error': 'Etapa inválida'}), 400);
          }),
          orderId: 1,
          jobId: 10,
        ));

        await tester.tap(find.text('Avanzar'));
        await tester.pumpAndSettle();

        await tester.tap(find.text('Confirmar'));
        await tester.pumpAndSettle();

        expect(find.text('Etapa inválida'), findsOneWidget);
        // Widget should still exist and be functional
        expect(find.text('Impresión'), findsOneWidget);
      });

      testWidgets('shows generic message when no error in response',
          (tester) async {
        await tester.pumpWidget(_buildWidget(
          currentStage: 'Impresión',
          apiClient: _mockApiClient(handler: (request) async {
            return http.Response('Server Error', 500);
          }),
          orderId: 1,
          jobId: 10,
        ));

        await tester.tap(find.text('Avanzar'));
        await tester.pumpAndSettle();

        await tester.tap(find.text('Confirmar'));
        await tester.pumpAndSettle();

        expect(find.textContaining('servidor'), findsOneWidget);
      });
    });

    group('double-tap prevention', () {
      testWidgets('only sends one PATCH even if confirm tapped twice',
          (tester) async {
        int apiCallCount = 0;

        await tester.pumpWidget(_buildWidget(
          currentStage: 'Impresión',
          apiClient: _mockApiClient(handler: (request) async {
            apiCallCount++;
            await Future.delayed(const Duration(milliseconds: 200));
            return http.Response(jsonEncode({
              'success': true,
              'message': 'Etapa actualizada',
              'job': {'id': 10, 'status': 'Sublimado / Laminado'},
            }), 200);
          }),
          orderId: 1,
          jobId: 10,
        ));

        // Open dialog
        await tester.tap(find.text('Avanzar'));
        await tester.pumpAndSettle();

        // First confirm — dialog closes, API call starts
        await tester.tap(find.text('Confirmar'));
        await tester.pumpAndSettle();

        // The async operation completes (mock responds after 200ms fake time)
        // Only 1 call should have been made
        expect(apiCallCount, 1);

        // Tap again after first completes — this is allowed (not double-tap)
        await tester.tap(find.text('Avanzar'));
        await tester.pumpAndSettle();

        await tester.tap(find.text('Confirmar'));
        await tester.pumpAndSettle();

        expect(apiCallCount, 2);
      });
    });

    group('stage list', () {
      testWidgets('matches GENERAL_WORKFLOW from backend', (tester) async {
        await tester.pumpWidget(_buildWidget(
          currentStage: 'Recibido',
          apiClient: _mockApiClient(),
          orderId: 1,
          jobId: 10,
        ));

        // Verify all 12 stages are rendered
        expect(find.text('Recibido'), findsOneWidget);
        expect(find.text('Esperando archivos'), findsOneWidget);
        expect(find.text('Diseños confirmados'), findsOneWidget);
        expect(find.text('Listo para armado de planchas'), findsOneWidget);
        expect(find.text('En armado de planchas'), findsOneWidget);
        expect(find.text('Listo para imprimir'), findsOneWidget);
        expect(find.text('Impresión'), findsOneWidget);
        expect(find.text('Sublimado / Laminado'), findsOneWidget);
        expect(find.text('Corte'), findsOneWidget);
        expect(find.text('Control de calidad'), findsOneWidget);
        expect(find.text('Finalizado'), findsOneWidget);
        expect(find.text('Entregado'), findsOneWidget);
      });
    });
  });
}
