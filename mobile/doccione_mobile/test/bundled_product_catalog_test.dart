import 'package:flutter_test/flutter_test.dart';
import 'package:doccione_mobile/services/bundled_product_catalog.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('bundled product catalog loads from assets', () async {
    final products = await BundledProductCatalog.load();

    expect(products, isNotEmpty);
    expect(products.first.code, isNotEmpty);
  });
}
