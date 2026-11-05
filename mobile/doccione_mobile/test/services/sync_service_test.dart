import 'dart:convert';
import 'dart:io';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:doccione_mobile/database/database_helper.dart';
import 'package:doccione_mobile/database/sync_state_repository.dart';
import 'package:doccione_mobile/database/jobs_repository.dart';
import 'package:doccione_mobile/database/orders_repository.dart';
import 'package:doccione_mobile/database/clients_repository.dart';
import 'package:doccione_mobile/database/offline_catalog_repository.dart';
import 'package:doccione_mobile/services/sync_api_client.dart';
import 'package:doccione_mobile/services/sync_service.dart';
import 'package:doccione_mobile/services/handlers/jobs_sync_handler.dart';
import 'package:doccione_mobile/services/handlers/orders_sync_handler.dart';
import 'package:doccione_mobile/services/handlers/clients_sync_handler.dart';

/// Helper: build a response matching the real backend contract.
/// Backend format: { snapshot_until, complete, next_cursor, entities: { X: { items, has_more } } }
Map<String, dynamic> _backendResponse({
  required String snapshotUntil,
  required bool complete,
  String? nextCursor,
  List<Map<String, dynamic>>? jobs,
  List<Map<String, dynamic>>? orders,
  List<Map<String, dynamic>>? clients,
  bool jobsHasMore = false,
  bool ordersHasMore = false,
  bool clientsHasMore = false,
  String? scopeId,
}) {
  return {
    'server_time': '2026-07-21T10:00:00',
    'snapshot_until': snapshotUntil,
    if (scopeId != null) 'scope_id': scopeId,
    'complete': complete,
    'next_cursor': nextCursor,
    'entities': {
      'jobs': {
        'items': jobs ?? [],
        'has_more': jobsHasMore,
      },
      'orders': {
        'items': orders ?? [],
        'has_more': ordersHasMore,
      },
      'clients': {
        'items': clients ?? [],
        'has_more': clientsHasMore,
      },
    },
  };
}

void main() {
  late DatabaseHelper dbHelper;
  late SyncStateRepository syncStateRepo;
  late JobsRepository jobsRepo;
  late OrdersRepository ordersRepo;
  late ClientsRepository clientsRepo;

  setUpAll(() async {
    TestWidgetsFlutterBinding.ensureInitialized();

    // Mock path_provider for tests
    final testDir = Directory.systemTemp.createTempSync('sync_test_');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
      const MethodChannel('plugins.flutter.io/path_provider'),
      (MethodCall methodCall) async {
        if (methodCall.method == 'getApplicationDocumentsDirectory') {
          return testDir.path;
        }
        return null;
      },
    );

    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  setUp(() async {
    dbHelper = DatabaseHelper();

    syncStateRepo = SyncStateRepository(dbHelper);
    jobsRepo = JobsRepository(dbHelper);
    ordersRepo = OrdersRepository(dbHelper);
    clientsRepo = ClientsRepository(dbHelper);
  });

  tearDown(() async {
    try {
      await dbHelper.close();
      await dbHelper.deleteDatabase();
    } catch (_) {}
  });

  tearDownAll(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
      const MethodChannel('plugins.flutter.io/path_provider'),
      null,
    );
  });

  group('SyncService — backend contract (entities/items)', () {
    test('single page: jobs, orders, clients with int IDs coerced to String',
        () async {
      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode(_backendResponse(
            snapshotUntil: '2026-07-21T10:00:00',
            complete: true,
            jobs: [
              {
                'id': 1,
                'order_id': 10,
                'title': 'Job 1',
                'material': 'Acero',
                'status': 'pending',
                'sort_order': 0,
                'created_at': '2026-07-20T08:00:00',
                'updated_at': '2026-07-20T09:00:00'
              }
            ],
            orders: [
              {
                'id': 10,
                'client_id': 1,
                'client': 'John',
                'whatsapp': '123',
                'order_date': '2026-07-20',
                'status': 'pending',
                'material': 'Acero',
                'quantity': 5,
                'delivery_date': '2026-07-25',
                'print_priority': 'high',
                'is_archived': 0,
                'created_at': '2026-07-20T08:00:00',
                'updated_at': '2026-07-20T09:00:00'
              }
            ],
            clients: [
              {
                'id': 1,
                'name': 'John',
                'whatsapp': '123',
                'client_type': 'regular',
                'created_at': '2026-07-20T08:00:00',
                'updated_at': '2026-07-20T09:00:00'
              }
            ],
          )),
          200,
        );
      });

      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8766',
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

      // Verify data persisted
      final jobs = await jobsRepo.getAllJobs();
      expect(jobs.length, 1);
      expect(jobs.first.id, '1');

      final orders = await ordersRepo.getAllOrders();
      expect(orders.length, 1);
      expect(orders.first.id, '10');

      final clients = await clientsRepo.getAllClients();
      expect(clients.length, 1);
      expect(clients.first.id, '1');

      // Verify sync state uses snapshot_until value
      final syncState = await syncStateRepo.getSyncState();
      expect(syncState.lastCompletedSnapshot, '2026-07-21T10:00:00');
      expect(syncState.currentNextCursor, null);

      apiClient.close();
    });

    test('a seller scope removes cached company orders before upsert',
        () async {
      await ordersRepo.upsertOrder({
        'id': '900',
        'client': 'Cliente empresa',
        'order_date': '2026-07-19',
        'status': 'pending',
        'created_at': '2026-07-19T08:00:00',
        'updated_at': '2026-07-19T09:00:00',
      });
      await jobsRepo.upsertJob({
        'id': '901',
        'order_id': '900',
        'title': 'Trabajo empresa',
        'status': 'pending',
        'created_at': '2026-07-19T08:00:00',
        'updated_at': '2026-07-19T09:00:00',
      });
      await clientsRepo.upsertClient({
        'id': '902',
        'name': 'Cliente empresa',
        'created_at': '2026-07-19T08:00:00',
        'updated_at': '2026-07-19T09:00:00',
      });

      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode(_backendResponse(
            snapshotUntil: '2026-07-21T10:00:00',
            scopeId: 'seller-device:7',
            complete: true,
            jobs: [
              {
                'id': 11,
                'order_id': 10,
                'title': 'Trabajo propio',
                'status': 'pending',
                'created_at': '2026-07-20T08:00:00',
                'updated_at': '2026-07-20T09:00:00'
              }
            ],
            orders: [
              {
                'id': 10,
                'client_id': 12,
                'client': 'Cliente propio',
                'order_date': '2026-07-20',
                'status': 'pending',
                'created_at': '2026-07-20T08:00:00',
                'updated_at': '2026-07-20T09:00:00'
              }
            ],
            clients: [
              {
                'id': 12,
                'name': 'Cliente propio',
                'created_at': '2026-07-20T08:00:00',
                'updated_at': '2026-07-20T09:00:00'
              }
            ],
          )),
          200,
        );
      });
      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8766',
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
      expect((await ordersRepo.getAllOrders()).map((item) => item.id), ['10']);
      expect((await jobsRepo.getAllJobs()).map((item) => item.id), ['11']);
      expect(
          (await clientsRepo.getAllClients()).map((item) => item.id), ['12']);
      expect((await syncStateRepo.getSyncState()).scopeId, 'seller-device:7');
      apiClient.close();
    });

    test('sync refreshes offline catalog designs from Studio library',
        () async {
      final mockClient = MockClient((request) async {
        if (request.url.path == '/api/v1/mobile/sync/pull') {
          return http.Response(
            jsonEncode(_backendResponse(
              snapshotUntil: '2026-07-21T12:00:00',
              complete: true,
            )),
            200,
          );
        }
        if (request.url.path == '/api/v1/mobile/catalog/designs') {
          return http.Response(
            jsonEncode({
              'designs': [
                {
                  'id': 'design-1',
                  'name': 'Nuevo diseño',
                  'category': 'Stickers',
                  'caption': 'Diseño nuevo',
                  'tags': ['nuevo'],
                  'preview_url': '/previews/design-1.png',
                  'visible_width': 100,
                  'visible_height': 100,
                  'modified_ms': 1710000000000,
                }
              ]
            }),
            200,
          );
        }
        if (request.url.path == '/api/v1/mobile/catalog/categories') {
          return http.Response(jsonEncode({'categories': []}), 200);
        }
        if (request.url.path == '/api/v1/mobile/catalog/tags') {
          return http.Response(jsonEncode({'tags': []}), 200);
        }
        return http.Response(jsonEncode({}), 404);
      });

      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8766',
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

      final offlineCatalogRepo = OfflineCatalogRepository(dbHelper);
      final result = await syncService.startSync();

      expect(result.isSuccess, true);
      final designs = await offlineCatalogRepo.getDesigns();
      expect(designs.map((design) => design.id), ['design-1']);
      expect(designs.first.name, 'Nuevo diseño');
      apiClient.close();
    });

    test('cancelled remote order is removed from the mobile cache', () async {
      await ordersRepo.upsertOrder({
        'id': '10',
        'status': 'pending',
        'updated_at': '2026-07-20T09:00:00',
      });
      await jobsRepo.upsertJob({
        'id': '11',
        'order_id': '10',
        'status': 'pending',
        'updated_at': '2026-07-20T09:00:00',
      });
      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode(_backendResponse(
            snapshotUntil: '2026-07-21T12:00:00',
            complete: true,
            jobs: [
              {
                'id': 11,
                'order_id': 10,
                'status': 'cancelled',
                'updated_at': '2026-07-21T11:00:00',
              }
            ],
            orders: [
              {
                'id': 10,
                'status': 'cancelled',
                'updated_at': '2026-07-21T11:00:00',
              }
            ],
          )),
          200,
        );
      });
      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8766',
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

      final result = await syncService.startSync();

      expect(result.isSuccess, true);
      expect(await ordersRepo.getOrderById('10'), isNull);
      expect(await jobsRepo.getJobById('11'), isNull);
      apiClient.close();
    });

    test('zero orders, multiple jobs, empty clients', () async {
      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode(_backendResponse(
            snapshotUntil: '2026-07-21T11:00:00',
            complete: true,
            jobs: [
              {
                'id': 1,
                'title': 'Job A',
                'status': 'pending',
                'sort_order': 0,
                'created_at': '2026-07-20T08:00:00',
                'updated_at': '2026-07-20T09:00:00'
              },
              {
                'id': 2,
                'title': 'Job B',
                'status': 'done',
                'sort_order': 1,
                'created_at': '2026-07-20T08:00:00',
                'updated_at': '2026-07-20T10:00:00'
              },
              {
                'id': 3,
                'title': 'Job C',
                'status': 'pending',
                'sort_order': 2,
                'created_at': '2026-07-20T08:00:00',
                'updated_at': '2026-07-20T11:00:00'
              },
            ],
            orders: [],
            clients: [],
          )),
          200,
        );
      });

      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8766',
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
      expect(result.jobsUpdated, 3);
      expect(result.ordersUpdated, 0);
      expect(result.clientsUpdated, 0);

      final jobs = await jobsRepo.getAllJobs();
      expect(jobs.length, 3);

      final orders = await ordersRepo.getAllOrders();
      expect(orders.length, 0);

      final clients = await clientsRepo.getAllClients();
      expect(clients.length, 0);

      apiClient.close();
    });

    test('paginated sync with cursor', () async {
      int requestCount = 0;

      final mockClient = MockClient((request) async {
        requestCount++;

        if (requestCount == 1) {
          return http.Response(
            jsonEncode(_backendResponse(
              snapshotUntil: '2026-07-21T10:00:00',
              complete: false,
              nextCursor: 'cursor-page2',
              jobs: [
                {
                  'id': 1,
                  'title': 'Job 1',
                  'status': 'pending',
                  'sort_order': 0,
                  'created_at': '2026-07-20T08:00:00',
                  'updated_at': '2026-07-20T09:00:00'
                }
              ],
              jobsHasMore: true,
            )),
            200,
          );
        } else {
          expect(request.url.queryParameters['cursor'], 'cursor-page2');
          return http.Response(
            jsonEncode(_backendResponse(
              snapshotUntil: '2026-07-21T10:00:00',
              complete: true,
              jobs: [
                {
                  'id': 2,
                  'title': 'Job 2',
                  'status': 'done',
                  'sort_order': 1,
                  'created_at': '2026-07-20T08:00:00',
                  'updated_at': '2026-07-20T10:00:00'
                }
              ],
            )),
            200,
          );
        }
      });

      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8766',
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

      final hasIncomplete = await syncService.hasIncompleteSync();
      expect(hasIncomplete, true);

      // Continue sync (second page)
      result = await syncService.continueSync();
      expect(result.isSuccess, true);
      expect(result.completed, true);
      expect(result.jobsUpdated, 1);

      final jobs = await jobsRepo.getAllJobs();
      expect(jobs.length, 2);

      final syncState = await syncStateRepo.getSyncState();
      expect(syncState.currentNextCursor, null);

      apiClient.close();
    });

    test('syncAll across 3 pages', () async {
      int requestCount = 0;

      final mockClient = MockClient((request) async {
        requestCount++;

        if (requestCount == 1) {
          return http.Response(
            jsonEncode(_backendResponse(
              snapshotUntil: '2026-07-21T10:00:00',
              complete: false,
              nextCursor: 'cursor-page2',
              jobs: [
                {
                  'id': 1,
                  'title': 'Job 1',
                  'status': 'pending',
                  'sort_order': 0,
                  'created_at': '2026-07-20T08:00:00',
                  'updated_at': '2026-07-20T09:00:00'
                }
              ],
              jobsHasMore: true,
            )),
            200,
          );
        } else if (requestCount == 2) {
          return http.Response(
            jsonEncode(_backendResponse(
              snapshotUntil: '2026-07-21T10:00:00',
              complete: false,
              nextCursor: 'cursor-page3',
              jobs: [
                {
                  'id': 2,
                  'title': 'Job 2',
                  'status': 'done',
                  'sort_order': 1,
                  'created_at': '2026-07-20T08:00:00',
                  'updated_at': '2026-07-20T10:00:00'
                }
              ],
              jobsHasMore: true,
            )),
            200,
          );
        } else {
          return http.Response(
            jsonEncode(_backendResponse(
              snapshotUntil: '2026-07-21T10:00:00',
              complete: true,
              jobs: [
                {
                  'id': 3,
                  'title': 'Job 3',
                  'status': 'pending',
                  'sort_order': 2,
                  'created_at': '2026-07-20T08:00:00',
                  'updated_at': '2026-07-20T11:00:00'
                }
              ],
            )),
            200,
          );
        }
      });

      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8766',
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
      expect(result.jobsUpdated, 3);
      expect(pageCount, 3);

      final jobs = await jobsRepo.getAllJobs();
      expect(jobs.length, 3);

      final hasIncomplete = await syncService.hasIncompleteSync();
      expect(hasIncomplete, false);

      apiClient.close();
    });

    test('has_more true triggers pagination, has_more false completes',
        () async {
      int syncPullRequestCount = 0;

      final mockClient = MockClient((request) async {
        if (request.url.path == '/api/v1/mobile/sync/pull') {
          syncPullRequestCount++;
        }

        if (syncPullRequestCount == 1) {
          return http.Response(
            jsonEncode(_backendResponse(
              snapshotUntil: '2026-07-21T10:00:00',
              complete: false,
              nextCursor: 'cursor-p2',
              jobs: [
                {
                  'id': 1,
                  'title': 'Job 1',
                  'status': 'pending',
                  'sort_order': 0,
                  'created_at': '2026-07-20T08:00:00',
                  'updated_at': '2026-07-20T09:00:00'
                }
              ],
              jobsHasMore: true,
              orders: [],
              clients: [],
            )),
            200,
          );
        } else {
          return http.Response(
            jsonEncode(_backendResponse(
              snapshotUntil: '2026-07-21T10:00:00',
              complete: true,
              jobs: [
                {
                  'id': 2,
                  'title': 'Job 2',
                  'status': 'done',
                  'sort_order': 1,
                  'created_at': '2026-07-20T08:00:00',
                  'updated_at': '2026-07-20T10:00:00'
                }
              ],
              jobsHasMore: false,
            )),
            200,
          );
        }
      });

      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8766',
        authToken: 'test-token',
        httpClient: mockClient,
      );

      final syncService = SyncService(
        dbHelper: dbHelper,
        syncStateRepo: syncStateRepo,
        apiClient: apiClient,
      );

      syncService.registerHandler('jobs', JobsSyncHandler(jobsRepo));

      final result = await syncService.syncAll();

      expect(result.isSuccess, true);
      expect(result.completed, true);
      expect(syncPullRequestCount, 2);

      final jobs = await jobsRepo.getAllJobs();
      expect(jobs.length, 2);

      apiClient.close();
    });

    test('malformed response: missing snapshot_until throws and returns error',
        () async {
      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'complete': true,
            'next_cursor': null,
            'entities': {
              'jobs': {'items': [], 'has_more': false},
              'orders': {'items': [], 'has_more': false},
              'clients': {'items': [], 'has_more': false},
            },
          }),
          200,
        );
      });

      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8766',
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

      // Verify error was saved
      final syncState = await syncStateRepo.getSyncState();
      expect(syncState.lastSyncError, isNotNull);

      apiClient.close();
    });

    test('malformed response: missing entities throws and returns error',
        () async {
      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'snapshot_until': '2026-07-21T10:00:00',
            'complete': true,
            'next_cursor': null,
          }),
          200,
        );
      });

      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8766',
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

      apiClient.close();
    });

    test('HTTP 500 returns error and saves state', () async {
      final mockClient = MockClient((request) async {
        return http.Response('Internal Server Error', 500);
      });

      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8766',
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

      final syncState = await syncStateRepo.getSyncState();
      expect(syncState.lastSyncError, isNotNull);

      apiClient.close();
    });

    test('rollback on handler error — no data persisted', () async {
      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode(_backendResponse(
            snapshotUntil: '2026-07-21T10:00:00',
            complete: true,
            jobs: [
              {
                'id': 1,
                'title': 'Job 1',
                'status': 'pending',
                'sort_order': 0,
                'created_at': '2026-07-20T08:00:00',
                'updated_at': '2026-07-20T09:00:00'
              }
            ],
          )),
          200,
        );
      });

      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8766',
        authToken: 'test-token',
        httpClient: mockClient,
      );

      final syncService = SyncService(
        dbHelper: dbHelper,
        syncStateRepo: syncStateRepo,
        apiClient: apiClient,
      );

      syncService.registerHandler('jobs', _FailingJobsHandler());

      final result = await syncService.startSync();

      expect(result.hasError, true);

      final jobs = await jobsRepo.getAllJobs();
      expect(jobs.length, 0);

      apiClient.close();
    });

    test('continueSync returns error when no incomplete sync exists', () async {
      final mockClient = MockClient((request) async {
        throw Exception('Should not be called');
      });

      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8766',
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

    test('int IDs coerced to String in all entity types', () async {
      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode(_backendResponse(
            snapshotUntil: '2026-07-21T10:00:00',
            complete: true,
            jobs: [
              {
                'id': 42,
                'order_id': 99,
                'title': 'Int ID Job',
                'status': 'pending',
                'sort_order': 0,
                'created_at': '2026-07-20T08:00:00',
                'updated_at': '2026-07-20T09:00:00'
              }
            ],
            orders: [
              {
                'id': 77,
                'client_id': 33,
                'client': 'Test',
                'status': 'pending',
                'created_at': '2026-07-20T08:00:00',
                'updated_at': '2026-07-20T09:00:00'
              }
            ],
            clients: [
              {
                'id': 55,
                'name': 'Int Client',
                'created_at': '2026-07-20T08:00:00',
                'updated_at': '2026-07-20T09:00:00'
              }
            ],
          )),
          200,
        );
      });

      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8766',
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

      final jobs = await jobsRepo.getAllJobs();
      expect(jobs.first.id, '42');

      final orders = await ordersRepo.getAllOrders();
      expect(orders.first.id, '77');

      final clients = await clientsRepo.getAllClients();
      expect(clients.first.id, '55');

      apiClient.close();
    });

    test('entity type missing from response treated as empty list', () async {
      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'server_time': '2026-07-21T10:00:00',
            'snapshot_until': '2026-07-21T10:00:00',
            'complete': true,
            'next_cursor': null,
            'entities': {
              'jobs': {
                'items': [
                  {
                    'id': 1,
                    'title': 'Job Only',
                    'status': 'pending',
                    'sort_order': 0,
                    'created_at': '2026-07-20T08:00:00',
                    'updated_at': '2026-07-20T09:00:00'
                  }
                ],
                'has_more': false,
              },
              // orders and clients intentionally absent
            },
          }),
          200,
        );
      });

      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8766',
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
      expect(result.ordersUpdated, 0);
      expect(result.clientsUpdated, 0);

      final jobs = await jobsRepo.getAllJobs();
      expect(jobs.length, 1);

      apiClient.close();
    });

    test('snapshot_until value stored as lastCompletedSnapshot', () async {
      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode(_backendResponse(
            snapshotUntil: '2026-07-21T15:30:00',
            complete: true,
          )),
          200,
        );
      });

      final apiClient = SyncApiClient(
        baseUrl: 'http://localhost:8766',
        authToken: 'test-token',
        httpClient: mockClient,
      );

      final syncService = SyncService(
        dbHelper: dbHelper,
        syncStateRepo: syncStateRepo,
        apiClient: apiClient,
      );

      syncService.registerHandler('jobs', JobsSyncHandler(jobsRepo));

      await syncService.startSync();

      final syncState = await syncStateRepo.getSyncState();
      expect(syncState.lastCompletedSnapshot, '2026-07-21T15:30:00');

      apiClient.close();
    });
  });
}

/// Handler that always fails (for testing transaction rollback)
class _FailingJobsHandler implements JobsSyncHandler {
  @override
  String get entityType => 'jobs';

  @override
  Future<void> process(List<Map<String, dynamic>> items,
      {Transaction? txn}) async {
    throw Exception('Simulated database error');
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}
