import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:doccione_mobile/database/database_helper.dart';
import 'package:doccione_mobile/database/sync_state_repository.dart';
import 'package:doccione_mobile/database/jobs_repository.dart';
import 'package:doccione_mobile/database/orders_repository.dart';
import 'package:doccione_mobile/database/clients_repository.dart';
import 'package:doccione_mobile/services/sync_api_client.dart';
import 'package:doccione_mobile/services/sync_service.dart';
import 'package:doccione_mobile/services/handlers/jobs_sync_handler.dart';
import 'package:doccione_mobile/services/handlers/orders_sync_handler.dart';
import 'package:doccione_mobile/services/handlers/clients_sync_handler.dart';

void main() {
  late DatabaseHelper dbHelper;
  late SyncStateRepository syncStateRepo;
  late JobsRepository jobsRepo;
  late OrdersRepository ordersRepo;
  late ClientsRepository clientsRepo;

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  setUp(() async {
    dbHelper = DatabaseHelper();
    await dbHelper.deleteDatabase();
    
    syncStateRepo = SyncStateRepository(dbHelper);
    jobsRepo = JobsRepository(dbHelper);
    ordersRepo = OrdersRepository(dbHelper);
    clientsRepo = ClientsRepository(dbHelper);
  });

  tearDown(() async {
    await dbHelper.deleteDatabase();
  });

  group('SyncService', () {
    test('should start sync and process single page', () async {
      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'snapshot_id': 'snap-123',
            'next_cursor': null,
            'complete': true,
            'data': {
              'jobs': [
                {'id': 'job-1', 'title': 'Job 1', 'updated_at': '2026-01-01T00:00:00Z'}
              ],
              'orders': [
                {'id': 'order-1', 'job_id': 'job-1', 'updated_at': '2026-01-01T00:00:00Z'}
              ],
              'clients': [
                {'id': 'client-1', 'name': 'Client 1', 'updated_at': '2026-01-01T00:00:00Z'}
              ],
            },
          }),
          200,
        );
      });

      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8000',
        authToken: 'test-token',
        httpClient: mockClient,
      );

      final syncService = SyncService(
        dbHelper: dbHelper,
        syncStateRepo: syncStateRepo,
        apiClient: apiClient,
      );

      syncService.registerHandler('jobs', JobsSyncHandler(jobsRepo));
      syncService.registerHandler('orders', OrdersSyncHandler(ordersRepo));
      syncService.registerHandler('clients', ClientsSyncHandler(clientsRepo));

      final result = await syncService.startSync();

      expect(result.isSuccess, true);
      expect(result.completed, true);
      expect(result.jobsUpdated, 1);
      expect(result.ordersUpdated, 1);
      expect(result.clientsUpdated, 1);
      expect(result.httpDuration.inMilliseconds, greaterThan(0));
      expect(result.parseDuration.inMilliseconds, greaterThanOrEqualTo(0));
      expect(result.databaseDuration.inMilliseconds, greaterThan(0));
      expect(result.totalDuration.inMilliseconds, greaterThan(0));

      // Verify data was saved
      final jobs = await jobsRepo.getAllJobs();
      expect(jobs.length, 1);
      expect(jobs.first.id, 'job-1');

      final orders = await ordersRepo.getAllOrders();
      expect(orders.length, 1);

      final clients = await clientsRepo.getAllClients();
      expect(clients.length, 1);

      // Verify sync state
      final syncState = await syncStateRepo.getSyncState();
      expect(syncState.lastCompletedSnapshot, 'snap-123');
      expect(syncState.currentNextCursor, null);

      apiClient.close();
    });

    test('should handle paginated sync with cursor', () async {
      int requestCount = 0;
      
      final mockClient = MockClient((request) async {
        requestCount++;
        
        if (requestCount == 1) {
          // First page
          return http.Response(
            jsonEncode({
              'snapshot_id': 'snap-123',
              'next_cursor': 'cursor-page2',
              'complete': false,
              'data': {
                'jobs': [
                  {'id': 'job-1', 'title': 'Job 1', 'updated_at': '2026-01-01T00:00:00Z'}
                ],
                'orders': [],
                'clients': [],
              },
            }),
            200,
          );
        } else {
          // Second page
          expect(request.url.queryParameters['cursor'], 'cursor-page2');
          return http.Response(
            jsonEncode({
              'snapshot_id': 'snap-123',
              'next_cursor': null,
              'complete': true,
              'data': {
                'jobs': [
                  {'id': 'job-2', 'title': 'Job 2', 'updated_at': '2026-01-02T00:00:00Z'}
                ],
                'orders': [],
                'clients': [],
              },
            }),
            200,
          );
        }
      });

      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8000',
        authToken: 'test-token',
        httpClient: mockClient,
      );

      final syncService = SyncService(
        dbHelper: dbHelper,
        syncStateRepo: syncStateRepo,
        apiClient: apiClient,
      );

      syncService.registerHandler('jobs', JobsSyncHandler(jobsRepo));
      syncService.registerHandler('orders', OrdersSyncHandler(ordersRepo));
      syncService.registerHandler('clients', ClientsSyncHandler(clientsRepo));

      // Start sync (first page)
      var result = await syncService.startSync();
      expect(result.isSuccess, true);
      expect(result.completed, false);
      expect(result.jobsUpdated, 1);
      expect(result.nextCursor, 'cursor-page2');

      // Verify cursor was saved
      final hasIncomplete = await syncService.hasIncompleteSync();
      expect(hasIncomplete, true);

      // Continue sync (second page)
      result = await syncService.continueSync();
      expect(result.isSuccess, true);
      expect(result.completed, true);
      expect(result.jobsUpdated, 1);

      // Verify all jobs were saved
      final jobs = await jobsRepo.getAllJobs();
      expect(jobs.length, 2);

      // Verify sync completed
      final syncState = await syncStateRepo.getSyncState();
      expect(syncState.currentNextCursor, null);

      apiClient.close();
    });

    test('should handle sync errors and save error state', () async {
      final mockClient = MockClient((request) async {
        return http.Response('Internal Server Error', 500);
      });

      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8000',
        authToken: 'test-token',
        httpClient: mockClient,
      );

      final syncService = SyncService(
        dbHelper: dbHelper,
        syncStateRepo: syncStateRepo,
        apiClient: apiClient,
      );

      syncService.registerHandler('jobs', JobsSyncHandler(jobsRepo));

      final result = await syncService.startSync();

      expect(result.hasError, true);
      expect(result.error, isNotNull);
      expect(result.jobsUpdated, 0);

      // Verify error was saved
      final syncState = await syncStateRepo.getSyncState();
      expect(syncState.lastSyncError, isNotNull);

      apiClient.close();
    });

    test('should perform complete sync with syncAll', () async {
      int requestCount = 0;
      
      final mockClient = MockClient((request) async {
        requestCount++;
        
        if (requestCount == 1) {
          return http.Response(
            jsonEncode({
              'snapshot_id': 'snap-123',
              'next_cursor': 'cursor-page2',
              'complete': false,
              'data': {
                'jobs': [
                  {'id': 'job-1', 'title': 'Job 1', 'updated_at': '2026-01-01T00:00:00Z'}
                ],
                'orders': [],
                'clients': [],
              },
            }),
            200,
          );
        } else if (requestCount == 2) {
          return http.Response(
            jsonEncode({
              'snapshot_id': 'snap-123',
              'next_cursor': 'cursor-page3',
              'complete': false,
              'data': {
                'jobs': [
                  {'id': 'job-2', 'title': 'Job 2', 'updated_at': '2026-01-02T00:00:00Z'}
                ],
                'orders': [],
                'clients': [],
              },
            }),
            200,
          );
        } else {
          return http.Response(
            jsonEncode({
              'snapshot_id': 'snap-123',
              'next_cursor': null,
              'complete': true,
              'data': {
                'jobs': [
                  {'id': 'job-3', 'title': 'Job 3', 'updated_at': '2026-01-03T00:00:00Z'}
                ],
                'orders': [],
                'clients': [],
              },
            }),
            200,
          );
        }
      });

      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8000',
        authToken: 'test-token',
        httpClient: mockClient,
      );

      final syncService = SyncService(
        dbHelper: dbHelper,
        syncStateRepo: syncStateRepo,
        apiClient: apiClient,
      );

      syncService.registerHandler('jobs', JobsSyncHandler(jobsRepo));
      syncService.registerHandler('orders', OrdersSyncHandler(ordersRepo));
      syncService.registerHandler('clients', ClientsSyncHandler(clientsRepo));

      int pageCount = 0;
      final result = await syncService.syncAll(
        onPageComplete: (pageResult) {
          pageCount++;
          expect(pageResult.isSuccess, true);
        },
      );

      expect(result.isSuccess, true);
      expect(result.completed, true);
      expect(result.jobsUpdated, 3); // Total from all pages
      expect(pageCount, 3); // 3 pages processed

      // Verify all jobs were saved
      final jobs = await jobsRepo.getAllJobs();
      expect(jobs.length, 3);

      // Verify sync completed
      final hasIncomplete = await syncService.hasIncompleteSync();
      expect(hasIncomplete, false);

      apiClient.close();
    });

    test('should rollback transaction on database error', () async {
      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'snapshot_id': 'snap-123',
            'next_cursor': null,
            'complete': true,
            'data': {
              'jobs': [
                {'id': 'job-1', 'title': 'Job 1', 'updated_at': '2026-01-01T00:00:00Z'}
              ],
              'orders': [],
              'clients': [],
            },
          }),
          200,
        );
      });

      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8000',
        authToken: 'test-token',
        httpClient: mockClient,
      );

      final syncService = SyncService(
        dbHelper: dbHelper,
        syncStateRepo: syncStateRepo,
        apiClient: apiClient,
      );

      // Register handler that throws error
      syncService.registerHandler('jobs', _FailingJobsHandler());

      final result = await syncService.startSync();

      expect(result.hasError, true);

      // Verify no jobs were saved (transaction rolled back)
      final jobs = await jobsRepo.getAllJobs();
      expect(jobs.length, 0);

      apiClient.close();
    });

    test('should not continue sync when no incomplete sync exists', () async {
      final mockClient = MockClient((request) async {
        throw Exception('Should not be called');
      });

      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8000',
        authToken: 'test-token',
        httpClient: mockClient,
      );

      final syncService = SyncService(
        dbHelper: dbHelper,
        syncStateRepo: syncStateRepo,
        apiClient: apiClient,
      );

      final result = await syncService.continueSync();

      expect(result.hasError, true);
      expect(result.error, contains('No incomplete sync'));

      apiClient.close();
    });
  });
}

/// Handler that always fails (for testing transaction rollback)
class _FailingJobsHandler implements JobsSyncHandler {
  @override
  String get entityType => 'jobs';

  @override
  Future<void> process(List<Map<String, dynamic>> items) async {
    throw Exception('Simulated database error');
  }
  
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}
