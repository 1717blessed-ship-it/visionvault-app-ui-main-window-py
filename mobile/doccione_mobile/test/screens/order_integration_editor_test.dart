import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/services.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:doccione_mobile/screens/unified_order_creation_screen.dart';
import '../support/order_integration_fixture.dart';

// Test-only native HTTP, retains default TLS validation. App code has no override.
class NativeTestHttp extends HttpOverrides {}

Future<void> settleIO(WidgetTester tester) async {
  for (var i = 0; i < 15; i++) {
    await tester
        .runAsync(() => Future<void>.delayed(const Duration(milliseconds: 30)));
    await tester.pump(const Duration(milliseconds: 30));
  }
}

Future<void> capture(WidgetTester tester, String name) async {
  await tester.pump();
  final boundary = tester.renderObject<RenderRepaintBoundary>(
      find.byKey(const Key('integration-capture')));
  await tester.runAsync(() async {
    final image = await boundary.toImage(pixelRatio: 1);
    final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
    await File('../../artifacts/s2b-editor-$name.png')
        .writeAsBytes(bytes!.buffer.asUint8List());
    image.dispose();
  });
}

String flutterRootPath() {
  var directory = File(Platform.resolvedExecutable).parent;
  final executable = Platform.isWindows ? 'flutter.bat' : 'flutter';
  while (directory.parent.path != directory.path) {
    if (File('${directory.path}/bin/$executable').existsSync()) {
      return directory.path;
    }
    directory = directory.parent;
  }
  throw StateError(
      'Flutter SDK root not found from Platform.resolvedExecutable');
}

File readableSystemFont() {
  final candidates = [
    if (Platform.isWindows) 'C:/Windows/Fonts/segoeui.ttf',
    if (Platform.isLinux) '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    if (Platform.isMacOS) '/System/Library/Fonts/Supplemental/Arial.ttf',
  ].map(File.new);
  return candidates.firstWhere((font) => font.existsSync(),
      orElse: () => throw StateError('No readable system font available'));
}

void main() {
  testWidgets(
      'editor real: cola pendiente, confirmación HTTP y conflicto con ambas versiones',
      (tester) async {
    final f = IntegrationFixture();
    await tester.runAsync(
        () => HttpOverrides.runWithHttpOverrides(f.start, NativeTestHttp()));
    addTearDown(() async {
      await f.close();
    });
    tester.view.resetPhysicalSize();
    tester.view.physicalSize = const Size(1100, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final draft = (await tester.runAsync(f.saved))!;
    await tester.runAsync(() async {
      final font = FontLoader('IntegrationReadable');
      final bytes = await readableSystemFont().readAsBytes();
      font.addFont(Future.value(ByteData.sublistView(bytes)));
      await font.load();
      final icons = FontLoader('MaterialIcons');
      final iconBytes = await File(
              '${flutterRootPath()}/bin/cache/artifacts/material_fonts/materialicons-regular.otf')
          .readAsBytes();
      icons.addFont(Future.value(ByteData.sublistView(iconBytes)));
      await icons.load();
    });
    await tester.pumpWidget(MaterialApp(
        theme: ThemeData(fontFamily: 'IntegrationReadable'),
        home: RepaintBoundary(
            key: const Key('integration-capture'),
            child: UnifiedOrderCreationScreen(
                baseUrl: f.url,
                sessionToken: f.pairing['session_token'] as String,
                repository: f.drafts,
                integrationSync: f.sync))));
    await settleIO(tester);
    await tester.tap(find.byTooltip('Recuperar borrador'));
    await settleIO(tester);
    await tester.tap(find.widgetWithText(ListTile, draft.client));
    await settleIO(tester);
    expect(find.text('INTEGRACIÓN AISLADA · NO PRODUCCIÓN'), findsOneWidget);
    await capture(tester, 'local');
    await tester.tap(find.text('Preparar envío aislado'));
    await settleIO(tester);
    expect(find.text('Pendiente de sincronización'), findsOneWidget);
    await capture(tester, 'pending');
    await tester.runAsync(f.sync.drain);
    await settleIO(tester);
    expect(find.text('Sincronizado y confirmado'), findsOneWidget);
    await capture(tester, 'confirmed');
    await tester.enterText(
        find.byType(TextField).last, 'Edición LOCAL a conservar');
    await tester.pump();
    expect(find.text('Sincronizado y confirmado'), findsNothing);
    await tester.tap(find.text('Guardar borrador (incluso incompleto)'));
    await settleIO(tester);
    await tester.tap(find.text('Preparar envío aislado'));
    await settleIO(tester);
    final link = (await tester.runAsync(() => f.store.link(draft.id)))!;
    await tester.runAsync(() => f.command('desktop_edit',
        {'id': link['desktop_id'], 'notes': 'EDICIÓN DESKTOP concurrente'}));
    await tester.runAsync(f.sync.drain);
    await settleIO(tester);
    expect(find.text('Conflicto'), findsOneWidget);
    await capture(tester, 'conflict');
    await tester.tap(find.text('Consultar ambas versiones'));
    await tester.pumpAndSettle();
    expect(find.textContaining('EDICIÓN DESKTOP concurrente'), findsOneWidget);
    await capture(tester, 'both-versions');
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  }, timeout: const Timeout(Duration(seconds: 90)));
}
