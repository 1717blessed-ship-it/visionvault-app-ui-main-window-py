import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:doccione_mobile/models/job.dart';
import 'package:doccione_mobile/models/order.dart';
import 'package:doccione_mobile/models/order_with_details.dart';
import 'package:doccione_mobile/widgets/sales_timeline_card.dart';

void main() {
  OrderWithDetails sale({
    String id = '42',
    String? status = 'En producción',
    List<Job> jobs = const [],
  }) {
    return OrderWithDetails(
      order: Order(
        id: id,
        orderNumber: id,
        client: 'Cliente de prueba',
        status: status,
      ),
      jobs: jobs,
    );
  }

  Widget subject(List<OrderWithDetails> sales) {
    return MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
          child: SalesTimelineCard(sales: sales),
        ),
      ),
    );
  }

  testWidgets('replaces the production summary with the sales timeline',
      (tester) async {
    await tester.pumpWidget(subject([
      sale(
        jobs: [
          Job(id: '8', orderId: '42', status: 'Impresión'),
        ],
      ),
    ]));

    expect(find.text('Estado de tus ventas'), findsOneWidget);
    expect(find.text('Resumen de producción'), findsNothing);
    expect(find.text('Pedido #42'), findsOneWidget);
    expect(find.text('Impresión'), findsOneWidget);
    expect(find.text('Recibido'), findsOneWidget);
    expect(find.text('Preparación'), findsOneWidget);
    expect(find.text('Producción'), findsOneWidget);
    expect(find.text('Listo'), findsOneWidget);
    expect(find.text('Entregado'), findsOneWidget);
  });

  testWidgets('shows the least advanced stage for a multi-job order',
      (tester) async {
    await tester.pumpWidget(subject([
      sale(
        jobs: [
          Job(id: '8', orderId: '42', status: 'Control de calidad'),
          Job(id: '9', orderId: '42', status: 'Corte'),
        ],
      ),
    ]));

    expect(find.text('Corte'), findsOneWidget);
    expect(
      find.text('2 trabajos incluidos · se muestra la etapa menos avanzada'),
      findsOneWidget,
    );
  });

  testWidgets('shows a useful empty state before the first sale',
      (tester) async {
    await tester.pumpWidget(subject(const []));

    expect(find.text('Todavía no hay ventas para seguir'), findsOneWidget);
    expect(
      find.text(
        'Cuando cargues una venta, su estado aparecerá en esta línea de tiempo.',
      ),
      findsOneWidget,
    );
  });
}
