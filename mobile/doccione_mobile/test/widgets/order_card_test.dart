import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:doccione_mobile/widgets/order_card.dart';
import 'package:doccione_mobile/models/order_with_details.dart';
import 'package:doccione_mobile/models/order.dart';
import 'package:doccione_mobile/models/client.dart';
import 'package:doccione_mobile/models/job.dart';

void main() {
  group('OrderCard', () {
    testWidgets('should display order information',
        (WidgetTester tester) async {
      final order = Order(
        id: 'order-1',
        orderNumber: '154',
        clientId: 'client-1',
        status: 'production',
        orderDate: '2026-07-21',
        updatedAt: '2026-01-01T00:00:00Z',
      );

      final client = Client(
        id: 'client-1',
        name: 'Juan Pérez',
        phone: '+54123456789',
        updatedAt: '2026-01-01T00:00:00Z',
      );

      final jobs = [
        Job(
          id: 'job-1',
          orderId: 'order-1',
          title: 'Sticker Logo',
          quantity: 10,
          updatedAt: '2026-01-01T00:00:00Z',
        ),
      ];

      final orderDetails = OrderWithDetails(
        order: order,
        client: client,
        jobs: jobs,
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: OrderCard(orderDetails: orderDetails),
          ),
        ),
      );

      expect(find.text('#154'), findsOneWidget);
      expect(find.text('Juan Pérez'), findsOneWidget);
      expect(find.text('Sticker Logo'), findsOneWidget);
      expect(find.text('21/07/2026'), findsOneWidget);
      expect(find.text('1 trabajo'), findsOneWidget);
    });

    testWidgets('should show correct status badge for pending',
        (WidgetTester tester) async {
      final order = Order(
        id: 'order-1',
        status: 'pending',
        orderDate: '2026-07-21',
        updatedAt: '2026-01-01T00:00:00Z',
      );

      final orderDetails = OrderWithDetails(
        order: order,
        client: null,
        jobs: [],
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: OrderCard(orderDetails: orderDetails),
          ),
        ),
      );

      expect(find.text('Pendiente'), findsOneWidget);
      expect(find.byIcon(Icons.schedule), findsOneWidget);
    });

    testWidgets('should show correct status badge for production',
        (WidgetTester tester) async {
      final order = Order(
        id: 'order-1',
        status: 'production',
        orderDate: '2026-07-21',
        updatedAt: '2026-01-01T00:00:00Z',
      );

      final orderDetails = OrderWithDetails(
        order: order,
        client: null,
        jobs: [],
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: OrderCard(orderDetails: orderDetails),
          ),
        ),
      );

      expect(find.text('Producción'), findsOneWidget);
      expect(find.byIcon(Icons.build), findsOneWidget);
    });

    testWidgets('should show correct status badge for completed',
        (WidgetTester tester) async {
      final order = Order(
        id: 'order-1',
        status: 'completed',
        orderDate: '2026-07-21',
        updatedAt: '2026-01-01T00:00:00Z',
      );

      final orderDetails = OrderWithDetails(
        order: order,
        client: null,
        jobs: [],
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: OrderCard(orderDetails: orderDetails),
          ),
        ),
      );

      expect(find.text('Completado'), findsOneWidget);
      expect(find.byIcon(Icons.check_circle), findsOneWidget);
    });

    testWidgets('should handle tap event', (WidgetTester tester) async {
      bool tapped = false;

      final order = Order(
        id: 'order-1',
        orderDate: '2026-07-21',
        updatedAt: '2026-01-01T00:00:00Z',
      );

      final orderDetails = OrderWithDetails(
        order: order,
        client: null,
        jobs: [],
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: OrderCard(
              orderDetails: orderDetails,
              onTap: () {
                tapped = true;
              },
            ),
          ),
        ),
      );

      await tester.tap(find.byType(OrderCard));
      expect(tapped, true);
    });

    testWidgets('should pluralize jobs count', (WidgetTester tester) async {
      final order = Order(
        id: 'order-1',
        orderDate: '2026-07-21',
        updatedAt: '2026-01-01T00:00:00Z',
      );

      final jobs = [
        Job(
          id: 'job-1',
          orderId: 'order-1',
          title: 'Job 1',
          updatedAt: '2026-01-01T00:00:00Z',
        ),
        Job(
          id: 'job-2',
          orderId: 'order-1',
          title: 'Job 2',
          updatedAt: '2026-01-01T00:00:00Z',
        ),
      ];

      final orderDetails = OrderWithDetails(
        order: order,
        client: null,
        jobs: jobs,
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: OrderCard(orderDetails: orderDetails),
          ),
        ),
      );

      expect(find.text('2 trabajos'), findsOneWidget);
    });

    testWidgets('should show fallback when no client',
        (WidgetTester tester) async {
      final order = Order(
        id: 'order-1',
        orderDate: '2026-07-21',
        updatedAt: '2026-01-01T00:00:00Z',
      );

      final orderDetails = OrderWithDetails(
        order: order,
        client: null,
        jobs: [],
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: OrderCard(orderDetails: orderDetails),
          ),
        ),
      );

      expect(find.text('Sin cliente'), findsOneWidget);
      expect(find.text('Sin trabajos'), findsOneWidget);
    });
  });
}
