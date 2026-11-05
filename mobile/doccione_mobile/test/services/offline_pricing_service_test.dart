import 'package:doccione_mobile/models/catalog_design.dart';
import 'package:doccione_mobile/services/offline_pricing_service.dart';
import 'package:flutter_test/flutter_test.dart';

StudioProduct product(
        {required String code, double base = 0, double? min, double? max}) =>
    StudioProduct(
        id: 1,
        code: code,
        name: code,
        description: '',
        category: '',
        imagePath: '',
        basePrice: base,
        priceRules: 0,
        materials: const [],
        minPrice: min,
        maxPrice: max);

void main() {
  test('calcula un presupuesto sin conexión con precios del catálogo', () {
    final total = OfflinePricingService.productTotal(
      {'remera': 2, 'taza': 3},
      [product(code: 'remera', base: 1200), product(code: 'taza', min: 850)],
    );
    expect(total, 4950);
  });

  test('prioriza precio base y luego mínimo para la cotización local', () {
    expect(
        OfflinePricingService.unitPrice(product(code: 'a', base: 100, min: 80)),
        100);
    expect(
        OfflinePricingService.unitPrice(product(code: 'b', min: 80, max: 120)),
        80);
  });
}
