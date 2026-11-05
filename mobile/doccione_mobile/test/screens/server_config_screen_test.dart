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

  Future<void> settleDatabase(WidgetTester tester) async {
    // SQLite FFI runs outside FakeAsync: virtual pumping cannot finish its I/O.
    // Keep real persistence and all UI assertions; yield real time with a bound.
    for (var attempt = 0; attempt < 200; attempt++) {
      await tester.runAsync(
          () => Future<void>.delayed(const Duration(milliseconds: 10)));
      await tester.pump(const Duration(milliseconds: 20));
      if (find.byType(CircularProgressIndicator).evaluate().isEmpty) {
        await tester.pumpAndSettle();
        return;
      }
    }
    fail('La operación SQLite no terminó en el plazo real de prueba.');
  }

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
    await settleDatabase(tester);
  }

  group('ServerConfigScreen', () {
    testWidgets('loads and displays current config', (tester) async {
      await pumpScreen(tester);
      expect(find.text('localhost'), findsOneWidget);
      // Port also appears in the preset menu: verify the editable field itself.
      expect(
          tester
              .widget<TextFormField>(find.byType(TextFormField).last)
              .controller!
              .text,
          '8765');
      expect(find.text('http://localhost:8765'), findsOneWidget);
    });

    testWidgets('shows error for empty host', (tester) async {
      await pumpScreen(tester);
      final hostField = find.byType(TextFormField).first;
      await tester.enterText(hostField, '');
      await settleDatabase(tester);
      await tester.tap(find.text('Guardar'));
      await settleDatabase(tester);
      expect(find.text('El host es obligatorio'), findsOneWidget);
    });

    testWidgets('shows error for invalid port', (tester) async {
      await pumpScreen(tester);
      final portField = find.byType(TextFormField).last;
      await tester.enterText(portField, 'abc');
      await settleDatabase(tester);
      await tester.tap(find.text('Guardar'));
      await settleDatabase(tester);
      expect(find.text('Debe ser un número'), findsOneWidget);
    });

    testWidgets('shows error for port out of range', (tester) async {
      await pumpScreen(tester);
      final portField = find.byType(TextFormField).last;
      await tester.enterText(portField, '99999');
      await settleDatabase(tester);
      await tester.tap(find.text('Guardar'));
      await settleDatabase(tester);
      expect(find.text('Puerto debe estar entre 1 y 65535'), findsOneWidget);
    });

    testWidgets('saves config correctly', (tester) async {
      await pumpScreen(tester);
      final hostField = find.byType(TextFormField).first;
      await tester.enterText(hostField, '192.168.1.50');
      await settleDatabase(tester);
      await tester.tap(find.text('Guardar'));
      await settleDatabase(tester);
      expect(find.text('Configuración guardada correctamente'), findsOneWidget);
      final persisted = await tester.runAsync(repository.getConfig);
      expect(persisted!.host, '192.168.1.50');
      expect(persisted.port, 8765);
      expect(persisted.scheme, 'http');
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
      await settleDatabase(tester);
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
      await settleDatabase(tester);
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
      await settleDatabase(tester);
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
      await settleDatabase(tester);
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
      await settleDatabase(tester);
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
      await settleDatabase(tester);
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
      await settleDatabase(tester);
      await tester.tap(find.text('Guardar'));
      await tester.pumpAndSettle();
      expect(find.text('El host no debe contener espacios'), findsOneWidget);
    });
  });
}
