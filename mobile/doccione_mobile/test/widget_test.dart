import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:doccione_mobile/models/catalog_design.dart';
import 'package:doccione_mobile/theme/doccione_palette.dart';
import 'package:doccione_mobile/widgets/real_size_preview.dart';
import 'package:doccione_mobile/widgets/uniform_image_preview.dart';

void main() {
  testWidgets('the shared mobile theme renders an app shell', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: DoccioneTheme.dark(),
        home: const Scaffold(body: Text('Doccione')),
      ),
    );

    expect(find.text('Doccione'), findsOneWidget);
    final context = tester.element(find.text('Doccione'));
    final theme = Theme.of(context);
    expect(theme.brightness, Brightness.dark);
    expect(theme.scaffoldBackgroundColor, DoccionePalette.canvas);
    expect(theme.cardTheme.color, DoccionePalette.surface);
    expect(
      theme.inputDecorationTheme.fillColor,
      DoccionePalette.surfaceElevated,
    );
  });

  testWidgets('catalog previews share a square frame with a black stroke',
      (tester) async {
    final image = MemoryImage(base64Decode(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2n9sAAAAASUVORK5CYII=',
    ));

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Center(
            child: SizedBox(
              width: 200,
              height: 120,
              child: UniformImagePreview(imageProvider: image),
            ),
          ),
        ),
      ),
    );
    await tester.pump(const Duration(milliseconds: 50));

    final preview = find.byType(UniformImagePreview);
    final frame = find.descendant(
      of: preview,
      matching: find.byType(DecoratedBox),
    );
    expect(tester.getSize(frame), const Size.square(120));

    final decoration =
        (tester.widget<DecoratedBox>(frame).decoration as BoxDecoration);
    final border = decoration.border! as Border;
    expect(border.top.color, Colors.black);
    expect(border.top.width, 2);
  });

  testWidgets('catalog can hide the design hitbox frame', (tester) async {
    final image = MemoryImage(base64Decode(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2n9sAAAAASUVORK5CYII=',
    ));

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox.square(
            dimension: 120,
            child: UniformImagePreview(
              imageProvider: image,
              showFrame: false,
            ),
          ),
        ),
      ),
    );

    final preview = find.byType(UniformImagePreview);
    expect(
      find.descendant(of: preview, matching: find.byType(DecoratedBox)),
      findsNothing,
    );
  });

  testWidgets('real-size preview preserves dimensions at 1:1 scale',
      (tester) async {
    final image = MemoryImage(base64Decode(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2n9sAAAAASUVORK5CYII=',
    ));
    const design = CatalogDesign(
      id: 'design-1',
      name: 'Diseño',
      category: 'Stickers',
      caption: '',
      tags: [],
      previewUrl: '/preview',
      visibleWidth: 200,
      visibleHeight: 100,
    );

    await tester.binding.setSurfaceSize(const Size(1000, 800));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        home: RealSizePreviewScreen(
          design: design,
          imageProvider: image,
          initialSizeCm: 5,
        ),
      ),
    );
    await tester.pump();

    final previewSize =
        tester.getSize(find.byKey(const Key('real-size-design')));
    const expectedLongSide =
        5 * RealSizePreviewScreen.logicalPixelsPerCentimeter;
    expect(previewSize.width, closeTo(expectedLongSide, .01));
    expect(previewSize.height, closeTo(expectedLongSide / 2, .01));
    expect(find.textContaining('5.0 × 2.5 cm'), findsOneWidget);
  });

  testWidgets('design-only preview uses 5.50 cm without form controls',
      (tester) async {
    final image = MemoryImage(base64Decode(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2n9sAAAAASUVORK5CYII=',
    ));
    const design = CatalogDesign(
      id: 'design-2',
      name: 'Diseño',
      category: 'Stickers',
      caption: '',
      tags: ['anime', 'flor'],
      previewUrl: '/preview',
      visibleWidth: 100,
      visibleHeight: 100,
    );

    await tester.binding.setSurfaceSize(const Size(1000, 800));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        home: RealSizePreviewScreen(
          design: design,
          imageProvider: image,
          initialSizeCm: 5.5,
          designOnly: true,
        ),
      ),
    );
    await tester.pump();

    final previewSize =
        tester.getSize(find.byKey(const Key('real-size-design')));
    const expectedSide = 5.5 * RealSizePreviewScreen.logicalPixelsPerCentimeter;
    expect(previewSize.width, closeTo(expectedSide, .01));
    expect(previewSize.height, closeTo(expectedSide, .01));
    expect(find.text('#anime'), findsOneWidget);
    expect(find.text('#flor'), findsOneWidget);
    expect(find.byType(AppBar), findsNothing);
    expect(find.byType(TextField), findsNothing);
  });
}
