import 'package:doccione_mobile/models/catalog_design.dart';

class ProductSelectionSummary {
  const ProductSelectionSummary._();

  static String buildLabel(StudioProduct product, StudioProductOption? option) {
    if (option == null) {
      return product.name;
    }

    final parts = <String>[
      product.name,
      if (option.variantName.isNotEmpty) option.variantName,
      if (option.material.isNotEmpty) option.material,
      if (option.size.isNotEmpty) option.size,
    ];

    return parts.join(' · ');
  }

  static double effectivePrice(
    StudioProduct product,
    StudioProductOption? option, {
    double? overridePrice,
  }) {
    if (overridePrice != null) {
      return overridePrice;
    }
    if (option?.price != null) {
      return option!.price!;
    }
    if (product.basePrice > 0) {
      return product.basePrice;
    }
    if (product.minPrice != null) {
      return product.minPrice!;
    }
    return 0;
  }
}
