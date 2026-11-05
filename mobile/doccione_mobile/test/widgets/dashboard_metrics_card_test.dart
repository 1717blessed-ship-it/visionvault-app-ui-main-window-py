import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:doccione_mobile/widgets/dashboard_metrics_card.dart';
import 'package:doccione_mobile/models/dashboard_metrics.dart';

void main() {
  group('DashboardMetricsCard', () {
    testWidgets('should display metrics correctly',
        (WidgetTester tester) async {
      final metrics = DashboardMetrics(
        ordersToday: 12,
        ordersInProduction: 8,
        ordersPending: 3,
        ordersCompleted: 1,
        totalJobs: 45,
        totalClients: 20,
        lastSyncAt: DateTime.now(),
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: DashboardMetricsCard(metrics: metrics),
          ),
        ),
      );

      expect(find.text('Resumen de producción'), findsOneWidget);
      expect(find.text('12'), findsOneWidget);
      expect(find.text('8'), findsOneWidget);
      expect(find.text('3'), findsOneWidget);
      expect(find.text('1'), findsOneWidget);
      expect(find.text('45'), findsOneWidget);
      expect(find.text('20'), findsOneWidget);
    });

    testWidgets('should display zero values', (WidgetTester tester) async {
      final metrics = DashboardMetrics.empty();

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: DashboardMetricsCard(metrics: metrics),
          ),
        ),
      );

      expect(find.text('0'), findsNWidgets(6)); // All metrics are 0
    });

    testWidgets('should display icons', (WidgetTester tester) async {
      final metrics = DashboardMetrics.empty();

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: DashboardMetricsCard(metrics: metrics),
          ),
        ),
      );

      expect(find.byIcon(Icons.today), findsOneWidget);
      expect(find.byIcon(Icons.build), findsOneWidget);
      expect(find.byIcon(Icons.schedule), findsOneWidget);
      expect(find.byIcon(Icons.check_circle), findsOneWidget);
      expect(find.byIcon(Icons.work_outline), findsOneWidget);
      expect(find.byIcon(Icons.people_outline), findsOneWidget);
    });
  });
}
