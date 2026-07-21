import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:doccione_mobile/database/database_helper.dart';
import 'package:doccione_mobile/database/jobs_repository.dart';
import 'package:doccione_mobile/database/orders_repository.dart';
import 'package:doccione_mobile/database/clients_repository.dart';
import 'package:doccione_mobile/database/sync_state_repository.dart';

void main() {
  late DatabaseHelper dbHelper;
  late JobsRepository jobsRepo;
  late OrdersRepository ordersRepo;
  late ClientsRepository clientsRepo;
  late SyncStateRepository syncStateRepo;

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  setUp(() async {
    dbHelper = DatabaseHelper();
    await dbHelper.deleteDatabase();
    
    jobsRepo = JobsRepository(dbHelper);
    ordersRepo = OrdersRepository(dbHelper);
    clientsRepo = ClientsRepository(dbHelper);
    syncStateRepo = SyncStateRepository(dbHelper);
  });

  tearDown(() async {
    await dbHelper.deleteDatabase();
  });

  group('JobsRepository', () {
    test('should upsert job without duplicates', () async {
      final jobData = {
        'id': 'job-1',
        'job_number': 'J-001',
        'title': 'Test Job',
        'status': 'active',
        'updated_at': '2026-01-01T00:00:00Z',
      };

      // First insert
      await jobsRepo.upsertJob(jobData);
      var jobs = await jobsRepo.getAllJobs();
      expect(jobs.length, 1);
      expect(jobs.first.title, 'Test Job');

      // Update same job
      jobData['title'] = 'Updated Job';
      await jobsRepo.upsertJob(jobData);
      
      jobs = await jobsRepo.getAllJobs();
      expect(jobs.length, 1); // Should still be 1
      expect(jobs.first.title, 'Updated Job');
    });

    test('should upsert multiple jobs in batch', () async {
      final jobsData = [
        {
          'id': 'job-1',
          'job_number': 'J-001',
          'title': 'Job 1',
          'status': 'active',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'job-2',
          'job_number': 'J-002',
          'title': 'Job 2',
          'status': 'pending',
          'updated_at': '2026-01-02T00:00:00Z',
        },
      ];

      await jobsRepo.upsertJobs(jobsData);
      final jobs = await jobsRepo.getAllJobs();
      
      expect(jobs.length, 2);
      expect(jobs[0].jobNumber, 'J-002'); // Sorted by updated_at DESC
      expect(jobs[1].jobNumber, 'J-001');
    });

    test('should get jobs by status', () async {
      await jobsRepo.upsertJobs([
        {'id': 'job-1', 'status': 'active', 'updated_at': '2026-01-01T00:00:00Z'},
        {'id': 'job-2', 'status': 'completed', 'updated_at': '2026-01-02T00:00:00Z'},
        {'id': 'job-3', 'status': 'active', 'updated_at': '2026-01-03T00:00:00Z'},
      ]);

      final activeJobs = await jobsRepo.getJobsByStatus('active');
      expect(activeJobs.length, 2);
    });
  });

  group('OrdersRepository', () {
    test('should upsert order without duplicates', () async {
      final orderData = {
        'id': 'order-1',
        'order_number': 'O-001',
        'status': 'pending',
        'total_amount': 100.50,
        'updated_at': '2026-01-01T00:00:00Z',
      };

      await ordersRepo.upsertOrder(orderData);
      var orders = await ordersRepo.getAllOrders();
      expect(orders.length, 1);

      // Update
      orderData['total_amount'] = 200.75;
      await ordersRepo.upsertOrder(orderData);
      
      orders = await ordersRepo.getAllOrders();
      expect(orders.length, 1);
      expect(orders.first.totalAmount, 200.75);
    });

    test('should get orders by job ID', () async {
      await ordersRepo.upsertOrders([
        {'id': 'order-1', 'job_id': 'job-1', 'updated_at': '2026-01-01T00:00:00Z'},
        {'id': 'order-2', 'job_id': 'job-2', 'updated_at': '2026-01-02T00:00:00Z'},
        {'id': 'order-3', 'job_id': 'job-1', 'updated_at': '2026-01-03T00:00:00Z'},
      ]);

      final job1Orders = await ordersRepo.getOrdersByJobId('job-1');
      expect(job1Orders.length, 2);
    });
  });

  group('ClientsRepository', () {
    test('should upsert client without duplicates', () async {
      final clientData = {
        'id': 'client-1',
        'name': 'John Doe',
        'email': 'john@example.com',
        'updated_at': '2026-01-01T00:00:00Z',
      };

      await clientsRepo.upsertClient(clientData);
      var clients = await clientsRepo.getAllClients();
      expect(clients.length, 1);

      // Update
      clientData['email'] = 'john.doe@example.com';
      await clientsRepo.upsertClient(clientData);
      
      clients = await clientsRepo.getAllClients();
      expect(clients.length, 1);
      expect(clients.first.email, 'john.doe@example.com');
    });

    test('should search clients by name', () async {
      await clientsRepo.upsertClients([
        {'id': 'client-1', 'name': 'John Doe', 'updated_at': '2026-01-01T00:00:00Z'},
        {'id': 'client-2', 'name': 'Jane Smith', 'updated_at': '2026-01-02T00:00:00Z'},
        {'id': 'client-3', 'name': 'John Smith', 'updated_at': '2026-01-03T00:00:00Z'},
      ]);

      final johnClients = await clientsRepo.searchClientsByName('John');
      expect(johnClients.length, 2);
    });
  });

  group('SyncStateRepository', () {
    test('should get initial sync state', () async {
      final state = await syncStateRepo.getSyncState();
      expect(state.currentNextCursor, null);
      expect(state.lastCompletedSnapshot, null);
    });

    test('should set and get current cursor', () async {
      await syncStateRepo.setCurrentNextCursor('cursor-123');
      
      final cursor = await syncStateRepo.getCurrentNextCursor();
      expect(cursor, 'cursor-123');
      
      final hasIncomplete = await syncStateRepo.hasIncompleteSync();
      expect(hasIncomplete, true);
    });

    test('should clear current cursor', () async {
      await syncStateRepo.setCurrentNextCursor('cursor-123');
      await syncStateRepo.clearCurrentNextCursor();
      
      final cursor = await syncStateRepo.getCurrentNextCursor();
      expect(cursor, null);
      
      final hasIncomplete = await syncStateRepo.hasIncompleteSync();
      expect(hasIncomplete, false);
    });

    test('should complete sync', () async {
      await syncStateRepo.setCurrentNextCursor('cursor-123');
      await syncStateRepo.setLastSyncError('Some error');
      
      await syncStateRepo.completeSync('snapshot-456');
      
      final state = await syncStateRepo.getSyncState();
      expect(state.lastCompletedSnapshot, 'snapshot-456');
      expect(state.currentNextCursor, null);
      expect(state.lastSyncError, null);
      expect(state.lastSyncAt, isNotNull);
    });
  });
}
