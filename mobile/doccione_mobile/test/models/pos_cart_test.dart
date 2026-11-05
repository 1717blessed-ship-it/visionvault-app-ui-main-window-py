import 'package:doccione_mobile/models/catalog_design.dart';
import 'package:doccione_mobile/models/pos_cart.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('removeProduct quita la línea completa del carrito', () {
    final cart = PosCart();
    cart.addProduct('TAZA');
    cart.addProduct('TAZA');
    cart.addProduct('REMERA');

    cart.removeProduct('TAZA');

    expect(cart.products, {'REMERA': 1});
    expect(cart.lineCount, 1);
  });

  test('replaceDesigns conserva únicamente los diseños visibles en checkout',
      () {
    const firstDesign = CatalogDesign(
      id: 'one',
      name: 'Uno',
      category: '',
      caption: '',
      tags: [],
      previewUrl: '/one.png',
      visibleWidth: 100,
      visibleHeight: 100,
    );
    const secondDesign = CatalogDesign(
      id: 'two',
      name: 'Dos',
      category: '',
      caption: '',
      tags: [],
      previewUrl: '/two.png',
      visibleWidth: 100,
      visibleHeight: 100,
    );
    const first = CatalogCartItem(
      design: firstDesign,
      material: 'Vinilo',
      size: '5cm',
      quantity: 10,
    );
    const second = CatalogCartItem(
      design: secondDesign,
      material: 'Vinilo',
      size: '5cm',
      quantity: 10,
    );
    final cart = PosCart()
      ..addDesign(first)
      ..addDesign(second);

    cart.replaceDesigns([second]);

    expect(cart.designs, [second]);
    expect(cart.lineCount, 1);
  });
}
