import '../models/catalog_design.dart';

/// Calcula importes con los precios guardados en el teléfono.
///
/// Las reglas comerciales que dependan del servidor se validan nuevamente al
/// sincronizar, pero la persona que vende nunca queda sin un total orientativo.
class OfflinePricingService {
  const OfflinePricingService._();

  static double unitPrice(StudioProduct product) {
    if (product.basePrice > 0) return product.basePrice;
    if (product.minPrice != null) return product.minPrice!;
    if (product.maxPrice != null) return product.maxPrice!;
    return 0;
  }

  static double productTotal(
    Map<String, int> quantities,
    Iterable<StudioProduct> products,
  ) {
    final prices = {
      for (final product in products) product.code: unitPrice(product)
    };
    return quantities.entries.fold<double>(
      0,
      (total, entry) => total + (prices[entry.key] ?? 0) * entry.value,
    );
  }
}
