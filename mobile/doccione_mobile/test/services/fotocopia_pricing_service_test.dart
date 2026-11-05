import 'package:doccione_mobile/services/fotocopia_pricing_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('replica la cotización B/N simple de Studio', () {
    final quote = FotocopiaPricingService.calculate(
      color: false,
      doubleSided: false,
      physicalSheets: 10,
      copies: 5,
    );
    expect(quote.unitPrice, 50);
    expect(quote.totalSheets, 50);
    expect(quote.total, 2500);
  });

  test('aplica el 30% urgente después del subtotal', () {
    final quote = FotocopiaPricingService.calculate(
      color: true,
      doubleSided: true,
      physicalSheets: 20,
      copies: 1,
      urgent: true,
    );
    expect(quote.basePrice, 3600);
    expect(quote.surcharge, 1080);
    expect(quote.total, 4680);
  });

  test('el precio manual reemplaza el total calculado', () {
    final quote = FotocopiaPricingService.calculate(
      color: false,
      doubleSided: false,
      physicalSheets: 100,
      copies: 1,
      manualPrice: 4500,
    );
    expect(quote.total, 4500);
  });
}
