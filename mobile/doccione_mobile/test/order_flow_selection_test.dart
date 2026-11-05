import 'package:flutter_test/flutter_test.dart';
import 'package:doccione_mobile/models/catalog_design.dart';
import 'package:doccione_mobile/models/order_flow_selection.dart';

void main() {
  group('ProductSelectionSummary', () {
    test('builds a readable label from product and option', () {
      const product = StudioProduct(
        id: 1,
        code: 'sticker',
        name: 'Sticker Premium',
        description: 'Sticker premium',
        category: 'Stickers',
        imagePath: '',
        basePrice: 1200,
        priceRules: 1,
        materials: ['PVC'],
      );
      const option = StudioProductOption(
        variantCode: 'v1',
        variantName: 'Negro',
        material: 'PVC',
        size: '30x40',
      );

      expect(
        ProductSelectionSummary.buildLabel(product, option),
        'Sticker Premium · Negro · PVC · 30x40',
      );
    });

    test('falls back to the product name when no option is selected', () {
      const product = StudioProduct(
        id: 2,
        code: 'poster',
        name: 'Poster 50x70',
        description: 'Poster',
        category: 'Posters',
        imagePath: '',
        basePrice: 2500,
        priceRules: 1,
        materials: ['Lona'],
      );

      expect(ProductSelectionSummary.buildLabel(product, null), 'Poster 50x70');
    });

    test('uses the provided price when the selection has a custom value', () {
      const product = StudioProduct(
        id: 3,
        code: 'card',
        name: 'Card',
        description: 'Card',
        category: 'Cards',
        imagePath: '',
        basePrice: 900,
        priceRules: 1,
        materials: ['Cartulina'],
      );

      expect(
        ProductSelectionSummary.effectivePrice(product, null,
            overridePrice: 1100),
        1100,
      );
    });

    test('uses option price before base price when option has a price', () {
      const product = StudioProduct(
        id: 4,
        code: 'poster',
        name: 'Poster 50x70',
        description: 'Poster',
        category: 'Posters',
        imagePath: '',
        basePrice: 2500,
        priceRules: 1,
        materials: ['Lona'],
      );
      const option = StudioProductOption(
        variantCode: 'v2',
        variantName: 'Lona Brillante',
        material: 'Lona',
        size: '50x70',
        price: 3200,
      );

      expect(
        ProductSelectionSummary.effectivePrice(product, option),
        3200,
      );
    });
  });
}
