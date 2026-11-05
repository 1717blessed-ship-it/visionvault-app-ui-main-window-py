import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:doccione_mobile/screens/order_detail_screen.dart';
import 'package:doccione_mobile/models/order.dart';
import 'package:doccione_mobile/models/client.dart';
import 'package:doccione_mobile/models/job.dart';
import 'package:doccione_mobile/models/order_with_details.dart';

void main() {
  group('OrderDetailScreen', () {
    testWidgets('displays order with client and jobs',
        (WidgetTester tester) async {
      final order = Order(
        id: 'order-1',
        orderNumber: 'ORD-001',
        client: 'John Doe',
        whatsapp: '+1234567890',
        status: 'pending',
        printPriority: 'high',
        orderDate: '2026-07-21',
        deliveryDate: '2026-07-25',
        material: 'Vinilo',
        size: '50x70 cm',
        quantity: 10,
        orderConcept: 'Stickers promocionales',
        orderDescription: 'Stickers para campaña de verano',
        observations: 'Cliente prefiere colores vibrantes',
        updatedAt: '2026-01-01T00:00:00Z',
      );

      final client = Client(
        id: 'client-1',
        name: 'John Doe',
        phone: '+1234567890',
      );

      final jobs = [
        Job(
          id: 'job-1',
          orderId: 'order-1',
          title: 'Sticker Logo',
          material: 'Vinilo',
          size: '10x15 cm',
          quantity: 100,
          status: 'pending',
          notes: 'Fondo transparente',
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
          home: OrderDetailScreen(
            orderDetails: orderDetails,
            onContactWhatsApp: () {},
          ),
        ),
      );

      // Check app bar
      expect(find.text('Pedido #ORD-001'), findsOneWidget);
      expect(find.byIcon(Icons.chat), findsOneWidget);

      // Check order info
      expect(find.text('Pendiente'), findsAtLeastNWidgets(1));
      expect(find.text('Prioridad Alta'), findsOneWidget);
      expect(find.text('John Doe'), findsOneWidget);
      expect(find.text('+1234567890'), findsOneWidget);
      expect(find.text('21/07/2026'), findsOneWidget);
      expect(find.text('25/07/2026'), findsOneWidget);
      expect(find.text('Vinilo'), findsAtLeastNWidgets(1));
      expect(find.text('50x70 cm'), findsOneWidget);
      expect(find.text('10'), findsOneWidget);

      // Check concept, description, and observations
      expect(find.text('Stickers promocionales'), findsOneWidget);
      expect(find.text('Stickers para campaña de verano'), findsOneWidget);
      expect(find.text('Cliente prefiere colores vibrantes'), findsOneWidget);

      // Check jobs section
      expect(find.text('Trabajos (1)'), findsOneWidget);
      expect(find.text('Sticker Logo'), findsOneWidget);
    });

    testWidgets('displays order without client', (WidgetTester tester) async {
      final order = Order(
        id: 'order-1',
        orderNumber: 'ORD-001',
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
          home: OrderDetailScreen(orderDetails: orderDetails),
        ),
      );

      expect(find.text('Sin cliente'), findsOneWidget);
    });

    testWidgets('displays order without whatsapp', (WidgetTester tester) async {
      final order = Order(
        id: 'order-1',
        orderNumber: 'ORD-001',
        client: 'Jane Doe',
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
          home: OrderDetailScreen(orderDetails: orderDetails),
        ),
      );

      // WhatsApp section should not be displayed
      expect(find.textContaining('WhatsApp'), findsNothing);

      // WhatsApp button should not be displayed
      expect(find.byIcon(Icons.chat), findsNothing);
    });

    testWidgets('displays order without jobs', (WidgetTester tester) async {
      final order = Order(
        id: 'order-1',
        orderNumber: 'ORD-001',
        client: 'John Doe',
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
          home: OrderDetailScreen(orderDetails: orderDetails),
        ),
      );

      expect(find.text('Trabajos (0)'), findsOneWidget);
      expect(
          find.text('No hay trabajos asociados a este pedido'), findsOneWidget);
    });

    testWidgets('displays order with empty optional fields',
        (WidgetTester tester) async {
      final order = Order(
        id: 'order-1',
        orderNumber: 'ORD-001',
        client: 'John Doe',
        status: 'pending',
        orderDate: '2026-07-21',
        // No material, size, quantity, concept, description, observations
        updatedAt: '2026-01-01T00:00:00Z',
      );

      final orderDetails = OrderWithDetails(
        order: order,
        client: null,
        jobs: [],
      );

      await tester.pumpWidget(
        MaterialApp(
          home: OrderDetailScreen(orderDetails: orderDetails),
        ),
      );

      // Optional fields should not appear
      expect(find.textContaining('Material'), findsNothing);
      expect(find.textContaining('Tamaño'), findsNothing);
      expect(find.textContaining('Cantidad'), findsNothing);
      expect(find.text('Concepto'), findsNothing);
      expect(find.text('Descripción'), findsNothing);
      expect(find.text('Observaciones'), findsNothing);
    });

    testWidgets('displays different order statuses correctly',
        (WidgetTester tester) async {
      final statuses = [
        ('pending', 'Pendiente'),
        ('production', 'Producción'),
        ('completed', 'Completado'),
        ('delivered', 'Entregado'),
        ('cancelled', 'Cancelado'),
      ];

      for (final statusPair in statuses) {
        final order = Order(
          id: 'order-1',
          orderNumber: 'ORD-001',
          client: 'Test Client',
          status: statusPair.$1,
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
            home: OrderDetailScreen(orderDetails: orderDetails),
          ),
        );

        expect(find.text(statusPair.$2), findsOneWidget);

        await tester.pumpWidget(Container()); // Clear widget
      }
    });

    testWidgets('displays different priorities correctly',
        (WidgetTester tester) async {
      final priorities = [
        ('high', 'Prioridad Alta'),
        ('medium', 'Prioridad Media'),
        ('low', 'Prioridad Baja'),
      ];

      for (final priorityPair in priorities) {
        final order = Order(
          id: 'order-1',
          orderNumber: 'ORD-001',
          client: 'Test Client',
          status: 'pending',
          printPriority: priorityPair.$1,
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
            home: OrderDetailScreen(orderDetails: orderDetails),
          ),
        );

        expect(find.text(priorityPair.$2), findsOneWidget);

        await tester.pumpWidget(Container()); // Clear widget
      }
    });

    testWidgets('displays multiple jobs in order', (WidgetTester tester) async {
      final order = Order(
        id: 'order-1',
        orderNumber: 'ORD-001',
        client: 'John Doe',
        status: 'pending',
        orderDate: '2026-07-21',
        updatedAt: '2026-01-01T00:00:00Z',
      );

      final jobs = [
        Job(
          id: 'job-1',
          orderId: 'order-1',
          title: 'Job One',
          material: 'Vinilo',
          updatedAt: '2026-01-01T00:00:00Z',
        ),
        Job(
          id: 'job-2',
          orderId: 'order-1',
          title: 'Job Two',
          material: 'Lona',
          updatedAt: '2026-01-01T00:00:00Z',
        ),
        Job(
          id: 'job-3',
          orderId: 'order-1',
          title: 'Job Three',
          material: 'Banner',
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
          home: OrderDetailScreen(orderDetails: orderDetails),
        ),
      );

      expect(find.text('Trabajos (3)'), findsOneWidget);
      expect(find.text('Job One'), findsOneWidget);
      expect(find.text('Job Two'), findsOneWidget);
      expect(find.text('Job Three'), findsOneWidget);

      // Check indices
      expect(find.text('1'), findsOneWidget);
      expect(find.text('2'), findsOneWidget);
      expect(find.text('3'), findsOneWidget);
    });

    testWidgets('screen is scrollable', (WidgetTester tester) async {
      final order = Order(
        id: 'order-1',
        orderNumber: 'ORD-001',
        client: 'John Doe',
        status: 'pending',
        orderDate: '2026-07-21',
        deliveryDate: '2026-07-25',
        material: 'Vinilo',
        orderConcept: 'Long concept text that should be scrollable',
        orderDescription: 'Long description text that should be scrollable',
        observations: 'Long observations text that should be scrollable',
        updatedAt: '2026-01-01T00:00:00Z',
      );

      final orderDetails = OrderWithDetails(
        order: order,
        client: null,
        jobs: [],
      );

      await tester.pumpWidget(
        MaterialApp(
          home: OrderDetailScreen(orderDetails: orderDetails),
        ),
      );

      // Verify SingleChildScrollView exists
      expect(find.byType(SingleChildScrollView), findsOneWidget);
    });

    testWidgets('displays whatsapp button when number available',
        (WidgetTester tester) async {
      final order = Order(
        id: 'order-1',
        orderNumber: 'ORD-001',
        client: 'Jane Doe',
        whatsapp: '+9876543210',
        status: 'pending',
        orderDate: '2026-07-21',
        updatedAt: '2026-01-01T00:00:00Z',
      );

      final orderDetails = OrderWithDetails(
        order: order,
        client: null,
        jobs: [],
      );

      bool callbackCalled = false;

      await tester.pumpWidget(
        MaterialApp(
          home: OrderDetailScreen(
            orderDetails: orderDetails,
            onContactWhatsApp: () {
              callbackCalled = true;
            },
          ),
        ),
      );

      // Should display WhatsApp number
      expect(find.text('+9876543210'), findsOneWidget);

      // Should display WhatsApp button
      expect(find.byIcon(Icons.chat), findsOneWidget);

      // Tap button should call callback
      await tester.tap(find.byIcon(Icons.chat));
      await tester.pumpAndSettle();

      expect(callbackCalled, true);
    });
  });
}
