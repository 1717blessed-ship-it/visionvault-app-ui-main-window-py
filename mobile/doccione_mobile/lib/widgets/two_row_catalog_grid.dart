import 'package:flutter/material.dart';

/// Catálogo optimizado para pantallas apaisadas.
///
/// El eje principal es horizontal, por lo que [rowCount] representa la
/// cantidad de filas visibles y los diseños siguientes se recorren de
/// izquierda a derecha.
class TwoRowCatalogGrid extends StatelessWidget {
  static const int rowCount = 2;

  final int itemCount;
  final IndexedWidgetBuilder itemBuilder;
  final int rows;
  final EdgeInsetsGeometry padding;
  final double childAspectRatio;
  final double mainAxisSpacing;
  final double crossAxisSpacing;

  const TwoRowCatalogGrid({
    super.key,
    required this.itemCount,
    required this.itemBuilder,
    this.rows = rowCount,
    this.padding = const EdgeInsets.all(6),
    this.childAspectRatio = 1,
    this.mainAxisSpacing = 7,
    this.crossAxisSpacing = 7,
  }) : assert(rows > 0);

  @override
  Widget build(BuildContext context) => GridView.builder(
        scrollDirection: Axis.horizontal,
        padding: padding,
        itemCount: itemCount,
        gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
          crossAxisCount: rows,
          childAspectRatio: childAspectRatio,
          mainAxisSpacing: mainAxisSpacing,
          crossAxisSpacing: crossAxisSpacing,
        ),
        itemBuilder: itemBuilder,
      );
}
