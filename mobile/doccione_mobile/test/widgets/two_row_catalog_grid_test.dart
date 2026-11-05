import 'package:doccione_mobile/widgets/two_row_catalog_grid.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('el catálogo muestra dos filas y avanza horizontalmente',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TwoRowCatalogGrid(
            itemCount: 6,
            itemBuilder: (_, index) => Text('Diseño $index'),
          ),
        ),
      ),
    );

    final grid = tester.widget<GridView>(find.byType(GridView));
    final delegate =
        grid.gridDelegate as SliverGridDelegateWithFixedCrossAxisCount;

    expect(grid.scrollDirection, Axis.horizontal);
    expect(delegate.crossAxisCount, TwoRowCatalogGrid.rowCount);
    expect(delegate.crossAxisCount, 2);
    expect(delegate.childAspectRatio, 1);
    expect(delegate.mainAxisSpacing, 7);
    expect(delegate.crossAxisSpacing, 7);
  });

  testWidgets('acepta tres filas para mostrar un catálogo más denso',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TwoRowCatalogGrid(
            rows: 3,
            itemCount: 9,
            itemBuilder: (_, index) => Text('Diseño $index'),
          ),
        ),
      ),
    );

    final grid = tester.widget<GridView>(find.byType(GridView));
    final delegate =
        grid.gridDelegate as SliverGridDelegateWithFixedCrossAxisCount;
    expect(delegate.crossAxisCount, 3);
  });
}
