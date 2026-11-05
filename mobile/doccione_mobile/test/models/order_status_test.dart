import 'package:flutter_test/flutter_test.dart';
import 'package:doccione_mobile/models/order_status.dart';

void main() {
  group('OrderStatus', () {
    test('normalizes current Studio and legacy mobile values', () {
      expect(OrderStatus.key('Pendiente'), 'pending');
      expect(OrderStatus.key('pending'), 'pending');
      expect(OrderStatus.key('En producción'), 'production');
      expect(OrderStatus.key('production'), 'production');
      expect(OrderStatus.key('Finalizado'), 'completed');
      expect(OrderStatus.key('completed'), 'completed');
      expect(OrderStatus.key('Entregado'), 'delivered');
    });

    test('priority aliases include numeric Studio values', () {
      expect(OrderPriority.databaseAliases('high'), contains('3'));
      expect(OrderPriority.databaseAliases('4'), contains('urgente'));
      expect(OrderPriority.databaseAliases('media'), contains('2'));
    });
  });
}
