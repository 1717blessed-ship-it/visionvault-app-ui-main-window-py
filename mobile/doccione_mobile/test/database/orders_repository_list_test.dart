import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:doccione_mobile/database/database_helper.dart';
import 'package:doccione_mobile/database/orders_repository.dart';
import 'package:doccione_mobile/database/clients_repository.dart';
import 'package:doccione_mobile/database/jobs_repository.dart';

void main() {
  late DatabaseHelper dbHelper;
  late OrdersRepository ordersRepo;
  late ClientsRepository clientsRepo;
  late JobsRepository jobsRepo;

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  setUp(() async {
    dbHelper = DatabaseHelper();
    await dbHelper.deleteDatabase();

    ordersRepo = OrdersRepository(dbHelper);
    clientsRepo = ClientsRepository(dbHelper);
    jobsRepo = JobsRepository(dbHelper);
  });

  tearDown(() async {
    await dbHelper.deleteDatabase();
  });

  group('OrdersRepository - getOrdersWithDetails', () {
    test('should return empty list when no orders', () async {
      final result = await ordersRepo.getOrdersWithDetails();

      expect(result, isEmpty);
    });

    test('should return orders with client and jobs', () async {
      // Create client
      await clientsRepo.upsertClients([
        {
          'id': 'client-1',
          'name': 'Juan Pérez',
          'phone': '+54123456789',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      // Create order
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'order_number': '154',
          'client_id': 'client-1',
          'status': 'production',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      // Create jobs
      await jobsRepo.upsertJobs([
        {
          'id': 'job-1',
          'order_id': 'order-1',
          'title': 'Sticker Logo',
          'quantity': 10,
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'job-2',
          'order_id': 'order-1',
          'title': 'Sticker QR',
          'quantity': 25,
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.getOrdersWithDetails();

      expect(result.length, 1);
      expect(result[0].order.id, 'order-1');
      expect(result[0].client?.name, 'Juan Pérez');
      expect(result[0].jobs.length, 2);
      expect(result[0].jobs[0].title, 'Sticker Logo');
    });

    test('should filter by status', () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'status': 'pending',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-2',
          'status': 'production',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-3',
          'status': 'completed',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final pending = await ordersRepo.getOrdersWithDetails(status: 'pending');
      final production =
          await ordersRepo.getOrdersWithDetails(status: 'production');
      final completed =
          await ordersRepo.getOrdersWithDetails(status: 'completed');

      expect(pending.length, 1);
      expect(pending[0].order.id, 'order-1');
      expect(production.length, 1);
      expect(production[0].order.id, 'order-2');
      expect(completed.length, 1);
      expect(completed[0].order.id, 'order-3');
    });

    test('should respect limit parameter', () async {
      for (int i = 0; i < 10; i++) {
        await ordersRepo.upsertOrders([
          {
            'id': 'order-$i',
            'order_date': '2026-07-21',
            'updated_at': '2026-01-01T00:00:00Z',
          },
        ]);
      }

      final result = await ordersRepo.getOrdersWithDetails(limit: 5);

      expect(result.length, 5);
    });

    test('should handle orders without client', () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'client_id': null,
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.getOrdersWithDetails();

      expect(result.length, 1);
      expect(result[0].client, isNull);
      expect(result[0].clientName, 'Sin cliente');
    });

    test('should handle orders without jobs', () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.getOrdersWithDetails();

      expect(result.length, 1);
      expect(result[0].jobs, isEmpty);
      expect(result[0].hasJobs, false);
      expect(result[0].primaryJobTitle, 'Sin trabajos');
    });

    test('should order by date descending', () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'order_date': '2026-07-20',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-2',
          'order_date': '2026-07-22',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-3',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.getOrdersWithDetails();

      expect(result[0].order.id, 'order-2'); // Most recent
      expect(result[1].order.id, 'order-3');
      expect(result[2].order.id, 'order-1'); // Oldest
    });
  });

  group('OrderWithDetails model', () {
    test('should format dates correctly', () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'order_date': '2026-07-21',
          'delivery_date': '2026-07-25',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.getOrdersWithDetails();
      final details = result[0];

      expect(details.formattedOrderDate, '21/07/2026');
      expect(details.formattedDeliveryDate, '25/07/2026');
    });

    test('should concatenate job titles', () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      await jobsRepo.upsertJobs([
        {
          'id': 'job-1',
          'order_id': 'order-1',
          'title': 'Sticker A',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'job-2',
          'order_id': 'order-1',
          'title': 'Sticker B',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.getOrdersWithDetails();
      final details = result[0];

      expect(details.primaryJobTitle, 'Sticker A');
      expect(details.jobTitles, 'Sticker A, Sticker B');
      expect(details.jobsCount, 2);
    });
  });
}
