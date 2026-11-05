import 'dart:convert';
import 'dart:typed_data';

import 'package:doccione_mobile/theme/doccione_palette.dart';
import 'package:doccione_mobile/widgets/sticker_catalog_tile.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final transparentPixel = Uint8List.fromList(base64Decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk'
    '+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  ));

  testWidgets('la miniatura no superpone textos, marcos ni botones',
      (tester) async {
    var taps = 0;
    var longPresses = 0;

    await tester.pumpWidget(
      MaterialApp(
        home: Center(
          child: SizedBox.square(
            dimension: 100,
            child: StickerCatalogTile(
              key: const Key('catalog-tile'),
              imageProvider: MemoryImage(transparentPixel),
              semanticLabel: 'Sticker de prueba',
              onTap: () => taps++,
              onLongPress: () => longPresses++,
            ),
          ),
        ),
      ),
    );
    await tester.pump();

    final tile = find.byKey(const Key('catalog-tile'));
    expect(tester.getSize(tile), const Size.square(100));
    expect(
        find.descendant(of: tile, matching: find.byType(Text)), findsNothing);
    expect(
        find.descendant(of: tile, matching: find.byType(Icon)), findsNothing);

    final material = tester.widget<Material>(
      find.descendant(of: tile, matching: find.byType(Material)).first,
    );
    expect(material.color, DoccionePalette.surface);

    await tester.tap(tile);
    await tester.longPress(tile);
    expect(taps, 1);
    expect(longPresses, 1);
  });

  testWidgets('distingue doble toque, triple toque y pulsación larga',
      (tester) async {
    var previews = 0;
    var configurations = 0;
    var selections = 0;

    await tester.pumpWidget(
      MaterialApp(
        home: Center(
          child: SizedBox.square(
            dimension: 100,
            child: StickerCatalogTile(
              key: const Key('multi-touch-catalog-tile'),
              imageProvider: MemoryImage(transparentPixel),
              semanticLabel: 'Sticker con gestos',
              onDoubleTap: () => previews++,
              onTripleTap: () => configurations++,
              onLongPress: () => selections++,
            ),
          ),
        ),
      ),
    );
    await tester.pump();

    final tile = find.byKey(const Key('multi-touch-catalog-tile'));
    await tester.tap(tile);
    await tester.tap(tile);
    await tester.pump(
      StickerCatalogTile.multiTapTimeout + const Duration(milliseconds: 1),
    );
    expect(previews, 1);
    expect(configurations, 0);

    await tester.tap(tile);
    await tester.tap(tile);
    await tester.tap(tile);
    await tester.pump();
    expect(previews, 1);
    expect(configurations, 1);

    await tester.longPress(tile);
    await tester.pump(
      StickerCatalogTile.multiTapTimeout + const Duration(milliseconds: 1),
    );
    expect(selections, 1);
    expect(previews, 1);
    expect(configurations, 1);
  });
}
