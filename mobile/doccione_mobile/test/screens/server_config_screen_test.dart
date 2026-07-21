import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:doccione_mobile/database/database_helper.dart';
import 'package:doccione_mobile/database/server_config_repository.dart';
import 'package:doccione_mobile/models/connection_test_result.dart';
import 'package:doccione_mobile/screens/server_config_screen.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late DatabaseHelper dbHelper;
  late ServerConfigRepository repository;

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  setUp(() async {
    dbHelper = DatabaseHelper();
    await dbHelper.deleteDatabase();
    repository = ServerConfigRepository(dbHelper);
  });

  tearDown(() async {
    await dbHelper.close();
  });

  Future<void> pumpScreen(
    WidgetTester tester, {
    Future<ConnectionTestResult> Function(String baseUrl)? onTestConnection,
  }) async {
    await tester.pumpWidget(
      MaterialApp(
        home: ServerConfigScreen(
          repository: repository,
          onTestConnection: onTestConnection,
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  group('ServerConfigScreen', () {
    testWidgets('loads and displays current config', (tester) async {
      await pumpScreen(tester);
      expect(find.text('localhost'), findsOneWidget);
      expect(find.text('8765'), findsOneWidget);
      expect(find.text('http://localhost:8765'), findsOneWidget);
    });

    testWidgets('shows error for empty host', (tester) async {
      await pumpScreen(tester);
      final hostField = find.byType(TextFormField).first;
      await tester.enterText(hostField, '');
      await tester.pumpAndSettle();
      await tester.tap(find.text('Guardar'));
      await tester.pumpAndSettle();
      expect(find.text('El host es obligatorio'), findsOneWidget);
    });

    testWidgets('shows error for invalid port', (tester) async {
      await pumpScreen(tester);
      final portField = find.byType(TextFormField).last;
      await tester.enterText(portField, 'abc');
      await tester.pumpAndSettle();
      await tester.tap(find.text('Guardar'));
      await tester.pumpAndSettle();
      expect(find.text('Debe ser un número'), findsOneWidget);
    });

    testWidgets('shows error for port out of range', (tester) async {
      await pumpScreen(tester);
      final portField = find.byType(TextFormField).last;
      await tester.enterText(portField, '99999');
      await tester.pumpAndSettle();
      await tester.tap(find.text('Guardar'));
      await tester.pumpAndSettle();
      expect(find.text('Puerto debe estar entre 1 y 65535'), findsOneWidget);
    });

    testWidgets('saves config correctly', (tester) async {
      await pumpScreen(tester);
      final hostField = find.byType(TextFormField).first;
      await tester.enterText(hostField, '192.168.1.50');
      await tester.pumpAndSettle();
      await tester.tap(find.text('Guardar'));
      await tester.pumpAndSettle();
      expect(find.text('Configuración guardada correctamente'), findsOneWidget);
    });

    testWidgets('calls onTestConnection callback', (tester) async {
      bool callbackCalled = false;
      await pumpScreen(
        tester,
        onTestConnection: (baseUrl) async {
          callbackCalled = true;
          return ConnectionTestResult.ok(
            responseTime: const Duration(milliseconds: 100),
          );
        },
      );
      await tester.tap(find.text('Probar conexión'));
      await tester.pumpAndSettle();
      expect(callbackCalled, true);
    });

    testWidgets('shows test success message', (tester) async {
      await pumpScreen(
        tester,
        onTestConnection: (baseUrl) async => ConnectionTestResult.ok(
          responseTime: const Duration(milliseconds: 100),
        ),
      );
      await tester.tap(find.text('Probar conexión'));
      await tester.pumpAndSettle();
      expect(find.text('Conexión exitosa'), findsOneWidget);
    });

    testWidgets('shows Continuar button on success', (tester) async {
      await pumpScreen(
        tester,
        onTestConnection: (baseUrl) async => ConnectionTestResult.ok(
          responseTime: const Duration(milliseconds: 100),
        ),
      );
      await tester.tap(find.text('Probar conexión'));
      await tester.pumpAndSettle();
      expect(find.text('Continuar'), findsOneWidget);
    });

    testWidgets('shows test failure message', (tester) async {
      await pumpScreen(
        tester,
        onTestConnection: (baseUrl) async => ConnectionTestResult.unexpected(
          detail: 'No se pudo conectar',
        ),
      );
      await tester.tap(find.text('Probar conexión'));
      await tester.pumpAndSettle();
      expect(find.text('No se pudo conectar'), findsOneWidget);
    });

    testWidgets('does not show Continuar on failure', (tester) async {
      await pumpScreen(
        tester,
        onTestConnection: (baseUrl) async => ConnectionTestResult.unexpected(
          detail: 'Connection refused',
        ),
      );
      await tester.tap(find.text('Probar conexión'));
      await tester.pumpAndSettle();
      expect(find.text('Continuar'), findsNothing);
    });

    testWidgets('disables test button while testing', (tester) async {
      await pumpScreen(tester);
      final testButton = find.widgetWithText(OutlinedButton, 'Probar conexión');
      expect(testButton, findsOneWidget);
      final buttonWidget = tester.widget<OutlinedButton>(testButton);
      expect(buttonWidget.onPressed, isNotNull);
    });

    testWidgets('updates preview when values change', (tester) async {
      await pumpScreen(tester);
      expect(find.text('http://localhost:8765'), findsOneWidget);
      final hostField = find.byType(TextFormField).first;
      await tester.enterText(hostField, '10.0.0.1');
      await tester.pumpAndSettle();
      expect(find.text('http://10.0.0.1:8765'), findsOneWidget);
    });

    testWidgets('shows current config card', (tester) async {
      await pumpScreen(tester);
      expect(find.text('Configuración actual'), findsOneWidget);
      expect(find.text('Host: localhost'), findsOneWidget);
      expect(find.text('Puerto: 8765'), findsOneWidget);
      expect(find.text('Esquema: http'), findsOneWidget);
      expect(find.text('URL: http://localhost:8765'), findsOneWidget);
    });

    testWidgets('validates host with spaces', (tester) async {
      await pumpScreen(tester);
      final hostField = find.byType(TextFormField).first;
      await tester.enterText(hostField, 'my host');
      await tester.pumpAndSettle();
      await tester.tap(find.text('Guardar'));
      await tester.pumpAndSettle();
      expect(find.text('El host no debe contener espacios'), findsOneWidget);
    });
  });
}
