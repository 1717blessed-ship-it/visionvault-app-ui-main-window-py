import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:doccione_mobile/database/database_helper.dart';
import 'package:doccione_mobile/database/orders_repository.dart';
import 'package:doccione_mobile/database/jobs_repository.dart';
import 'package:doccione_mobile/database/clients_repository.dart';

void main() {
  sqfliteFfiInit();
  databaseFactory = databaseFactoryFfi;

  late DatabaseHelper dbHelper;
  late OrdersRepository ordersRepo;
  late JobsRepository jobsRepo;
  late ClientsRepository clientsRepo;

  setUp(() async {
    dbHelper = DatabaseHelper();
    await dbHelper.deleteDatabase();
    ordersRepo = OrdersRepository(dbHelper);
    jobsRepo = JobsRepository(dbHelper);
    clientsRepo = ClientsRepository(dbHelper);
  });

  tearDown(() async {
    await dbHelper.close();
  });

  group('OrdersRepository.searchOrders', () {
    test('should search by order number', () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'order_number': 'ORD-001',
          'client': 'John Doe',
          'status': 'pending',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-2',
          'order_number': 'ORD-002',
          'client': 'Jane Smith',
          'status': 'pending',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.searchOrders(searchQuery: 'ORD-001');

      expect(result.length, 1);
      expect(result[0].order.orderNumber, 'ORD-001');
    });

    test('should search by client name', () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'client': 'John Doe',
          'status': 'pending',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-2',
          'client': 'Jane Smith',
          'status': 'pending',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.searchOrders(searchQuery: 'Jane');

      expect(result.length, 1);
      expect(result[0].order.client, 'Jane Smith');
    });

    test('should search by whatsapp', () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'client': 'John Doe',
          'whatsapp': '+1234567890',
          'status': 'pending',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-2',
          'client': 'Jane Smith',
          'whatsapp': '+9876543210',
          'status': 'pending',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.searchOrders(searchQuery: '987654');

      expect(result.length, 1);
      expect(result[0].order.whatsapp, '+9876543210');
    });

    test('should search by material', () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'client': 'John Doe',
          'material': 'Vinilo',
          'status': 'pending',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-2',
          'client': 'Jane Smith',
          'material': 'Lona',
          'status': 'pending',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.searchOrders(searchQuery: 'Vinilo');

      expect(result.length, 1);
      expect(result[0].order.material, 'Vinilo');
    });

    test('should search by job title', () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'client': 'John Doe',
          'status': 'pending',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-2',
          'client': 'Jane Smith',
          'status': 'pending',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      await jobsRepo.upsertJobs([
        {
          'id': 'job-1',
          'order_id': 'order-1',
          'title': 'Sticker Logo',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'job-2',
          'order_id': 'order-2',
          'title': 'Banner Promocional',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.searchOrders(searchQuery: 'Logo');

      expect(result.length, 1);
      expect(result[0].jobs.length, 1);
      expect(result[0].jobs[0].title, 'Sticker Logo');
    });

    test('should filter by status', () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'client': 'John Doe',
          'status': 'pending',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-2',
          'client': 'Jane Smith',
          'status': 'completed',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.searchOrders(status: 'pending');

      expect(result.length, 1);
      expect(result[0].order.status, 'pending');
    });

    test('should filter current Studio status using legacy semantic key',
        () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-spanish-pending',
          'client': 'Studio Client',
          'status': 'Pendiente',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-production',
          'client': 'Production Client',
          'status': 'En producción',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.searchOrders(status: 'pending');

      expect(result.map((item) => item.order.id), ['order-spanish-pending']);
    });

    test('should filter by priority', () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'client': 'John Doe',
          'status': 'pending',
          'print_priority': 'high',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-2',
          'client': 'Jane Smith',
          'status': 'pending',
          'print_priority': 'low',
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.searchOrders(priority: 'high');

      expect(result.length, 1);
      expect(result[0].order.printPriority, 'high');
    });

    test('should match numeric Studio priorities with legacy aliases',
        () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-numeric-high',
          'client': 'Studio Client',
          'status': 'Pendiente',
          'print_priority': 3,
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.searchOrders(priority: 'high');

      expect(result.map((item) => item.order.id), ['order-numeric-high']);
    });

    test('should hide archived by default', () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'client': 'John Doe',
          'status': 'pending',
          'is_archived': 0,
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-2',
          'client': 'Jane Smith',
          'status': 'pending',
          'is_archived': 1,
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.searchOrders(showArchived: false);

      expect(result.length, 1);
      expect(result[0].order.isArchived, false);
    });

    test('should show archived when requested', () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'client': 'John Doe',
          'status': 'pending',
          'is_archived': 0,
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-2',
          'client': 'Jane Smith',
          'status': 'pending',
          'is_archived': 1,
          'order_date': '2026-07-21',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.searchOrders(showArchived: true);

      expect(result.length, 2);
    });

    test('should sort by order_date descending', () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'client': 'John Doe',
          'status': 'pending',
          'order_date': '2026-07-20',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-2',
          'client': 'Jane Smith',
          'status': 'pending',
          'order_date': '2026-07-22',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.searchOrders(
        sortBy: 'order_date',
        sortDescending: true,
      );

      expect(result.length, 2);
      expect(result[0].order.orderDate, '2026-07-22');
      expect(result[1].order.orderDate, '2026-07-20');
    });

    test('should sort by delivery_date ascending', () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'client': 'John Doe',
          'status': 'pending',
          'delivery_date': '2026-07-25',
          'order_date': '2026-07-20',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-2',
          'client': 'Jane Smith',
          'status': 'pending',
          'delivery_date': '2026-07-23',
          'order_date': '2026-07-20',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.searchOrders(
        sortBy: 'delivery_date',
        sortDescending: false,
      );

      expect(result.length, 2);
      expect(result[0].order.deliveryDate, '2026-07-23');
      expect(result[1].order.deliveryDate, '2026-07-25');
    });

    test('should sort by priority', () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'client': 'John Doe',
          'status': 'pending',
          'print_priority': 'low',
          'order_date': '2026-07-20',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-2',
          'client': 'Jane Smith',
          'status': 'pending',
          'print_priority': 'high',
          'order_date': '2026-07-20',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-3',
          'client': 'Bob Wilson',
          'status': 'pending',
          'print_priority': 'medium',
          'order_date': '2026-07-20',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.searchOrders(
        sortBy: 'priority',
        sortDescending: true,
      );

      expect(result.length, 3);
      expect(result[0].order.printPriority, 'high');
      expect(result[1].order.printPriority, 'medium');
      expect(result[2].order.printPriority, 'low');
    });

    test('should sort by client name', () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'client': 'Charlie',
          'status': 'pending',
          'order_date': '2026-07-20',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-2',
          'client': 'Alice',
          'status': 'pending',
          'order_date': '2026-07-20',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-3',
          'client': 'Bob',
          'status': 'pending',
          'order_date': '2026-07-20',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.searchOrders(
        sortBy: 'client',
        sortDescending: false,
      );

      expect(result.length, 3);
      expect(result[0].order.client, 'Alice');
      expect(result[1].order.client, 'Bob');
      expect(result[2].order.client, 'Charlie');
    });

    test('should combine search and filters', () async {
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'client': 'John Doe',
          'status': 'pending',
          'print_priority': 'high',
          'material': 'Vinilo',
          'order_date': '2026-07-20',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-2',
          'client': 'Jane Smith',
          'status': 'pending',
          'print_priority': 'low',
          'material': 'Vinilo',
          'order_date': '2026-07-20',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-3',
          'client': 'Bob Wilson',
          'status': 'completed',
          'print_priority': 'high',
          'material': 'Lona',
          'order_date': '2026-07-20',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.searchOrders(
        searchQuery: 'Vinilo',
        status: 'pending',
        priority: 'high',
      );

      expect(result.length, 1);
      expect(result[0].order.client, 'John Doe');
    });

    test('should use batch queries to avoid N+1', () async {
      // Create orders
      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'client_id': 'client-1',
          'client': 'John Doe',
          'status': 'pending',
          'order_date': '2026-07-20',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-2',
          'client_id': 'client-2',
          'client': 'Jane Smith',
          'status': 'pending',
          'order_date': '2026-07-20',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      // Create clients
      await clientsRepo.upsertClients([
        {
          'id': 'client-1',
          'name': 'John Doe',
          'phone': '+1234567890',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'client-2',
          'name': 'Jane Smith',
          'phone': '+9876543210',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      // Create jobs
      await jobsRepo.upsertJobs([
        {
          'id': 'job-1',
          'order_id': 'order-1',
          'title': 'Job 1',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'job-2',
          'order_id': 'order-2',
          'title': 'Job 2',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final result = await ordersRepo.searchOrders();

      // Verify we got all data in single batch query
      expect(result.length, 2);
      expect(result[0].client, isNotNull);
      expect(result[0].jobs.length, 1);
      expect(result[1].client, isNotNull);
      expect(result[1].jobs.length, 1);
    });
  });
}
