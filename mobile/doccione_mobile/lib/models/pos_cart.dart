import 'catalog_design.dart';

/// Carrito único para el POS: las pantallas de diseños y productos comparten
/// estas líneas antes de enviarlas a Studio como una venta.
class PosCart {
  final List<CatalogCartItem> designs = [];
  final Map<String, PosProductLine> productLines = {};

  /// Compatibilidad con los pedidos ya existentes: consolida las variantes por
  /// producto cuando un endpoint antiguo no admite subproductos.
  Map<String, int> get products =>
      productLines.values.fold(<String, int>{}, (result, line) {
        result[line.productCode] =
            (result[line.productCode] ?? 0) + line.quantity;
        return result;
      });

  bool get isEmpty => designs.isEmpty && productLines.isEmpty;
  int get lineCount => designs.length + productLines.length;

  void addDesign(CatalogCartItem item) {
    final index = designs.indexWhere((current) =>
        current.design.id == item.design.id &&
        current.material == item.material &&
        current.size == item.size);
    if (index < 0) {
      designs.add(item);
      return;
    }
    final old = designs[index];
    designs[index] = CatalogCartItem(
        design: old.design,
        material: old.material,
        size: old.size,
        quantity: old.quantity + item.quantity);
  }

  void replaceDesigns(Iterable<CatalogCartItem> items) {
    designs
      ..clear()
      ..addAll(items);
  }

  void addProductLine(PosProductLine line) {
    final current = productLines[line.id];
    productLines[line.id] = current == null
        ? line
        : current.copyWith(quantity: current.quantity + line.quantity);
  }

  /// Adds a product without variant metadata.
  ///
  /// Kept for callers created before the variant-aware cart was introduced.
  /// New catalog flows should prefer [addProductLine] so names and prices are
  /// available at checkout.
  void addProduct(String productCode, {int quantity = 1}) {
    if (quantity < 1) return;
    addProductLine(PosProductLine(
      productCode: productCode,
      productName: productCode,
      unitPrice: 0,
      quantity: quantity,
    ));
  }

  /// Removes every variant belonging to [productCode].
  void removeProduct(String productCode) {
    productLines.removeWhere((_, line) => line.productCode == productCode);
  }

  void removeProductLine(String id) => productLines.remove(id);
  void clearProducts() => productLines.clear();
  void clear() {
    designs.clear();
    productLines.clear();
  }
}

class PosProductLine {
  final String productCode;
  final String productName;
  final String? variantCode;
  final String variantName;
  final String material;
  final String size;
  final double unitPrice;
  final int quantity;

  const PosProductLine({
    required this.productCode,
    required this.productName,
    this.variantCode,
    this.variantName = '',
    this.material = '',
    this.size = '',
    required this.unitPrice,
    required this.quantity,
  });

  String get id => '$productCode::${variantCode ?? 'base'}';
  String get label => variantName.isNotEmpty
      ? variantName
      : [material, size].where((value) => value.isNotEmpty).join(' · ');

  PosProductLine copyWith({int? quantity}) => PosProductLine(
        productCode: productCode,
        productName: productName,
        variantCode: variantCode,
        variantName: variantName,
        material: material,
        size: size,
        unitPrice: unitPrice,
        quantity: quantity ?? this.quantity,
      );

  Map<String, dynamic> toRequestJson() => {
        'product_code': productCode,
        'quantity': quantity,
        if (variantCode != null && variantCode!.isNotEmpty)
          'variant_code': variantCode,
      };
}

final posCart = PosCart();
