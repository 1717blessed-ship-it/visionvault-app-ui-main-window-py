/// Cotizador local de fotocopias. Replica la fórmula usada por Doccione Studio:
/// precio por hoja física × juegos, con el recargo urgente aplicado al final.
class FotocopiaQuote {
  final String productCode;
  final double unitPrice;
  final int physicalSheets;
  final int copies;
  final bool urgent;
  final double basePrice;
  final double surcharge;
  final double total;

  const FotocopiaQuote({
    required this.productCode,
    required this.unitPrice,
    required this.physicalSheets,
    required this.copies,
    required this.urgent,
    required this.basePrice,
    required this.surcharge,
    required this.total,
  });

  int get totalSheets => physicalSheets * copies;
}

class FotocopiaPricingService {
  FotocopiaPricingService._();

  static const urgentSurchargePercent = 30.0;
  static const _unitPrices = <String, double>{
    'fotocopia_bn_simple': 50,
    'fotocopia_bn_doble': 80,
    'fotocopia_color_simple': 120,
    'fotocopia_color_doble': 180,
  };

  static FotocopiaQuote calculate({
    required bool color,
    required bool doubleSided,
    required int physicalSheets,
    required int copies,
    bool urgent = false,
    double? manualPrice,
  }) {
    final code = color
        ? (doubleSided ? 'fotocopia_color_doble' : 'fotocopia_color_simple')
        : (doubleSided ? 'fotocopia_bn_doble' : 'fotocopia_bn_simple');
    final sheets = physicalSheets < 1 ? 1 : physicalSheets;
    final games = copies < 1 ? 1 : copies;
    final unitPrice = _unitPrices[code]!;
    final base = unitPrice * sheets * games;
    final surcharge = urgent ? base * urgentSurchargePercent / 100 : 0.0;
    return FotocopiaQuote(
      productCode: code,
      unitPrice: unitPrice,
      physicalSheets: sheets,
      copies: games,
      urgent: urgent,
      basePrice: base,
      surcharge: surcharge,
      total: manualPrice ?? base + surcharge,
    );
  }
}
