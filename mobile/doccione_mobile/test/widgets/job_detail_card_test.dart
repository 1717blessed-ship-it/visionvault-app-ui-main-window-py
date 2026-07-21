import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:doccione_mobile/widgets/job_detail_card.dart';
import 'package:doccione_mobile/models/job.dart';

void main() {
  group('JobDetailCard', () {
    testWidgets('displays job with all fields', (WidgetTester tester) async {
      final job = Job(
        id: 'job-1',
        orderId: 'order-1',
        title: 'Sticker Logo',
        material: 'Vinilo',
        size: '10x15 cm',
        quantity: 100,
        status: 'pending',
        notes: 'Fondo transparente',
        updatedAt: '2026-01-01T00:00:00Z',
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: JobDetailCard(
              job: job,
              index: 0,
            ),
          ),
        ),
      );

      expect(find.text('1'), findsOneWidget);
      expect(find.text('Sticker Logo'), findsOneWidget);
      expect(find.text('Vinilo'), findsOneWidget);
      expect(find.text('10x15 cm'), findsOneWidget);
      expect(find.text('100'), findsOneWidget);
      expect(find.text('Fondo transparente'), findsOneWidget);
      expect(find.text('Pendiente'), findsOneWidget);
    });

    testWidgets('displays job without optional fields', (WidgetTester tester) async {
      final job = Job(
        id: 'job-1',
        orderId: 'order-1',
        title: 'Trabajo Simple',
        status: 'completed',
        updatedAt: '2026-01-01T00:00:00Z',
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: JobDetailCard(
              job: job,
              index: 0,
            ),
          ),
        ),
      );

      expect(find.text('1'), findsOneWidget);
      expect(find.text('Trabajo Simple'), findsOneWidget);
      expect(find.text('Completado'), findsOneWidget);
      // Optional fields should not appear
      expect(find.textContaining('Material:'), findsNothing);
      expect(find.textContaining('Tamaño:'), findsNothing);
      expect(find.textContaining('Cantidad:'), findsNothing);
    });

    testWidgets('displays job without title', (WidgetTester tester) async {
      final job = Job(
        id: 'job-1',
        orderId: 'order-1',
        material: 'Lona',
        quantity: 5,
        updatedAt: '2026-01-01T00:00:00Z',
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: JobDetailCard(
              job: job,
              index: 0,
            ),
          ),
        ),
      );

      expect(find.text('Sin título'), findsOneWidget);
      expect(find.text('Lona'), findsOneWidget);
      expect(find.text('5'), findsOneWidget);
    });

    testWidgets('displays correct index number', (WidgetTester tester) async {
      final job = Job(
        id: 'job-3',
        orderId: 'order-1',
        title: 'Job Three',
        updatedAt: '2026-01-01T00:00:00Z',
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: JobDetailCard(
              job: job,
              index: 2, // Zero-indexed, so displays as 3
            ),
          ),
        ),
      );

      expect(find.text('3'), findsOneWidget);
      expect(find.text('Job Three'), findsOneWidget);
    });

    testWidgets('displays different status badges correctly', (WidgetTester tester) async {
      final statuses = [
        ('pending', 'Pendiente'),
        ('production', 'En Proceso'),
        ('completed', 'Completado'),
        ('cancelled', 'Cancelado'),
      ];

      for (final statusPair in statuses) {
        final job = Job(
          id: 'job-1',
          orderId: 'order-1',
          title: 'Test Job',
          status: statusPair.$1,
          updatedAt: '2026-01-01T00:00:00Z',
        );

        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: JobDetailCard(
                job: job,
                index: 0,
              ),
            ),
          ),
        );

        expect(find.text(statusPair.$2), findsOneWidget);
        
        await tester.pumpWidget(Container()); // Clear widget
      }
    });

    testWidgets('displays notes in separate container', (WidgetTester tester) async {
      final job = Job(
        id: 'job-1',
        orderId: 'order-1',
        title: 'Job with Notes',
        notes: 'These are important notes for the job',
        updatedAt: '2026-01-01T00:00:00Z',
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: JobDetailCard(
              job: job,
              index: 0,
            ),
          ),
        ),
      );

      expect(find.text('These are important notes for the job'), findsOneWidget);
      expect(find.byIcon(Icons.note_outlined), findsOneWidget);
    });

    testWidgets('does not display empty notes', (WidgetTester tester) async {
      final job = Job(
        id: 'job-1',
        orderId: 'order-1',
        title: 'Job without Notes',
        notes: '',
        updatedAt: '2026-01-01T00:00:00Z',
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: JobDetailCard(
              job: job,
              index: 0,
            ),
          ),
        ),
      );

      expect(find.byIcon(Icons.note_outlined), findsNothing);
    });

    testWidgets('displays material, size, and quantity icons', (WidgetTester tester) async {
      final job = Job(
        id: 'job-1',
        orderId: 'order-1',
        title: 'Complete Job',
        material: 'Paper',
        size: 'A4',
        quantity: 50,
        updatedAt: '2026-01-01T00:00:00Z',
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: JobDetailCard(
              job: job,
              index: 0,
            ),
          ),
        ),
      );

      expect(find.byIcon(Icons.category_outlined), findsOneWidget);
      expect(find.byIcon(Icons.straighten), findsOneWidget);
      expect(find.byIcon(Icons.format_list_numbered), findsOneWidget);
    });
  });
}
