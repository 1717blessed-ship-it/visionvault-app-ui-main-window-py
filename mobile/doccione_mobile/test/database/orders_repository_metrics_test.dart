import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:doccione_mobile/database/database_helper.dart';
import 'package:doccione_mobile/database/orders_repository.dart';
import 'package:doccione_mobile/database/sync_state_repository.dart';
import 'package:doccione_mobile/database/jobs_repository.dart';
import 'package:doccione_mobile/database/clients_repository.dart';

void main() {
  late DatabaseHelper dbHelper;
  late OrdersRepository ordersRepo;
  late SyncStateRepository syncStateRepo;
  late JobsRepository jobsRepo;
  late ClientsRepository clientsRepo;

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  setUp(() async {
    dbHelper = DatabaseHelper();
    await dbHelper.deleteDatabase();

    ordersRepo = OrdersRepository(dbHelper);
    syncStateRepo = SyncStateRepository(dbHelper);
    jobsRepo = JobsRepository(dbHelper);
    clientsRepo = ClientsRepository(dbHelper);
  });

  tearDown(() async {
    await dbHelper.deleteDatabase();
  });

  group('OrdersRepository - Dashboard Metrics', () {
    test('should return empty metrics when no data', () async {
      final metrics = await ordersRepo.getDashboardMetrics(
        syncStateRepo,
        jobsRepo,
        clientsRepo,
      );

      expect(metrics.ordersToday, 0);
      expect(metrics.ordersInProduction, 0);
      expect(metrics.ordersPending, 0);
      expect(metrics.ordersCompleted, 0);
      expect(metrics.totalJobs, 0);
      expect(metrics.totalClients, 0);
      expect(metrics.lastSyncAt, null);
    });

    test('should count orders by status correctly', () async {
      final today = DateTime.now();
      final todayStr =
          '${today.year}-${today.month.toString().padLeft(2, '0')}-${today.day.toString().padLeft(2, '0')}';

      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'status': 'pending',
          'order_date': todayStr,
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-2',
          'status': 'production',
          'order_date': todayStr,
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-3',
          'status': 'production',
          'order_date': '2026-01-15',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-4',
          'status': 'completed',
          'order_date': todayStr,
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final metrics = await ordersRepo.getDashboardMetrics(
        syncStateRepo,
        jobsRepo,
        clientsRepo,
      );

      expect(metrics.ordersToday, 3); // orders 1, 2, 4
      expect(metrics.ordersInProduction, 2); // orders 2, 3
      expect(metrics.ordersPending, 1); // order 1
      expect(metrics.ordersCompleted, 1); // order 4
    });

    test('should include jobs and clients count', () async {
      await jobsRepo.upsertJobs([
        {'id': 'job-1', 'title': 'Job 1', 'updated_at': '2026-01-01T00:00:00Z'},
        {'id': 'job-2', 'title': 'Job 2', 'updated_at': '2026-01-01T00:00:00Z'},
        {'id': 'job-3', 'title': 'Job 3', 'updated_at': '2026-01-01T00:00:00Z'},
      ]);

      await clientsRepo.upsertClients([
        {
          'id': 'client-1',
          'name': 'Client 1',
          'updated_at': '2026-01-01T00:00:00Z'
        },
        {
          'id': 'client-2',
          'name': 'Client 2',
          'updated_at': '2026-01-01T00:00:00Z'
        },
      ]);

      final metrics = await ordersRepo.getDashboardMetrics(
        syncStateRepo,
        jobsRepo,
        clientsRepo,
      );

      expect(metrics.totalJobs, 3);
      expect(metrics.totalClients, 2);
    });

    test('should include last sync timestamp', () async {
      await syncStateRepo.completeSync('snap-123');

      final metrics = await ordersRepo.getDashboardMetrics(
        syncStateRepo,
        jobsRepo,
        clientsRepo,
      );

      expect(metrics.lastSyncAt, isNotNull);
      expect(metrics.hasBeenSynced, true);
    });

    test('should include last sync error if present', () async {
      await syncStateRepo.setLastSyncError('Network error');

      final metrics = await ordersRepo.getDashboardMetrics(
        syncStateRepo,
        jobsRepo,
        clientsRepo,
      );

      expect(metrics.lastSyncError, 'Network error');
      expect(metrics.hasError, true);
    });

    test('lastSyncFormatted should format time correctly', () async {
      await syncStateRepo.completeSync('snap-123');

      final metrics = await ordersRepo.getDashboardMetrics(
        syncStateRepo,
        jobsRepo,
        clientsRepo,
      );

      expect(metrics.lastSyncFormatted, contains('segundos'));
    });
  });

  group('OrdersRepository - getOrdersByDate', () {
    test('should get orders for specific date', () async {
      final date = DateTime(2026, 7, 21);
      const dateStr = '2026-07-21';

      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'order_date': dateStr,
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-2',
          'order_date': '2026-07-22',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'order-3',
          'order_date': dateStr,
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final orders = await ordersRepo.getOrdersByDate(date);

      expect(orders.length, 2);
      expect(orders[0].id, 'order-1');
      expect(orders[1].id, 'order-3');
    });

    test('should return empty list if no orders on date', () async {
      final date = DateTime(2026, 7, 21);

      await ordersRepo.upsertOrders([
        {
          'id': 'order-1',
          'order_date': '2026-07-22',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ]);

      final orders = await ordersRepo.getOrdersByDate(date);

      expect(orders.length, 0);
    });
  });
}
