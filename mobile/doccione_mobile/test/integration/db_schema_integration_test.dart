import 'dart:convert';
import 'dart:io';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite/sqflite.dart';
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

  setUpAll(() async {
    TestWidgetsFlutterBinding.ensureInitialized();

    final testDir = Directory.systemTemp.createTempSync('integration_test_');
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

  group('Schema v4 — CREATE TABLE matches models', () {
    test('jobs table has all 17 columns from Job.toMap()', () async {
      final db = await dbHelper.database;
      final columns = await db.rawQuery('PRAGMA table_info(jobs)');
      final names = columns.map((c) => c['name'] as String).toSet();

      final expected = {
        'id',
        'order_id',
        'job_number',
        'title',
        'material',
        'size',
        'quantity',
        'status',
        'notes',
        'sort_order',
        'priority',
        'client_id',
        'assigned_to',
        'due_date',
        'created_at',
        'updated_at',
        'metadata',
      };

      expect(names, expected);
    });

    test('orders table has all 22 columns from Order.toMap()', () async {
      final db = await dbHelper.database;
      final columns = await db.rawQuery('PRAGMA table_info(orders)');
      final names = columns.map((c) => c['name'] as String).toSet();

      final expected = {
        'id',
        'order_number',
        'job_id',
        'client_id',
        'client',
        'whatsapp',
        'status',
        'material',
        'size',
        'quantity',
        'delivery_date',
        'print_priority',
        'is_archived',
        'observations',
        'order_concept',
        'order_description',
        'total_amount',
        'currency',
        'order_date',
        'created_at',
        'updated_at',
        'metadata',
      };

      expect(names, expected);
    });

    test('clients table has all 9 columns from Client.toMap()', () async {
      final db = await dbHelper.database;
      final columns = await db.rawQuery('PRAGMA table_info(clients)');
      final names = columns.map((c) => c['name'] as String).toSet();

      final expected = {
        'id',
        'name',
        'email',
        'phone',
        'company',
        'address',
        'created_at',
        'updated_at',
        'metadata',
      };

      expect(names, expected);
    });

    test('database version is 18', () async {
      final db = await dbHelper.database;
      final version = await db.getVersion();
      expect(version, 18);
    });

    test('sync state stores the active seller scope', () async {
      final db = await dbHelper.database;
      final columns = await db.rawQuery('PRAGMA table_info(sync_state)');
      final names = columns.map((column) => column['name'] as String).toSet();
      expect(names, contains('scope_id'));
    });
  });

  group('Migration v2 → v3', () {
    test('ALTER TABLE adds all missing columns to existing database', () async {
      final db = await dbHelper.database;

      // Verify columns that were added in v3 exist
      final jobCols = await db.rawQuery('PRAGMA table_info(jobs)');
      final jobNames = jobCols.map((c) => c['name'] as String).toSet();
      expect(jobNames, contains('order_id'));
      expect(jobNames, contains('material'));
      expect(jobNames, contains('sort_order'));

      final orderCols = await db.rawQuery('PRAGMA table_info(orders)');
      final orderNames = orderCols.map((c) => c['name'] as String).toSet();
      expect(orderNames, contains('client'));
      expect(orderNames, contains('whatsapp'));
      expect(orderNames, contains('delivery_date'));
      expect(orderNames, contains('is_archived'));
    });
  });

  group('Migration v3 → v4', () {
    test('clears the unscoped company cache', () async {
      final db = await dbHelper.database;
      await db.insert('clients', {'id': 'C1', 'name': 'Empresa'});
      await db.insert('orders', {
        'id': 'O1',
        'client_id': 'C1',
        'client': 'Empresa',
      });
      await db.insert('jobs', {
        'id': 'J1',
        'order_id': 'O1',
        'title': 'Trabajo anterior',
      });

      // Reproduce el esquema de sync_state de v3 antes de reabrir la base.
      await db.execute('DROP TABLE sync_state');
      await db.execute('''
        CREATE TABLE sync_state (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          last_completed_snapshot TEXT,
          current_next_cursor TEXT,
          last_sync_at TEXT,
          last_sync_error TEXT
        )
      ''');
      await db.insert('sync_state', {
        'id': 1,
        'current_next_cursor': 'old-company-cursor',
      });
      await db.setVersion(3);
      await dbHelper.close();

      final upgraded = await dbHelper.database;
      expect(
        Sqflite.firstIntValue(
          await upgraded.rawQuery('SELECT COUNT(*) FROM jobs'),
        ),
        0,
      );
      expect(
        Sqflite.firstIntValue(
          await upgraded.rawQuery('SELECT COUNT(*) FROM orders'),
        ),
        0,
      );
      expect(
        Sqflite.firstIntValue(
          await upgraded.rawQuery('SELECT COUNT(*) FROM clients'),
        ),
        0,
      );
      final state = (await upgraded.query('sync_state')).single;
      expect(state['scope_id'], isNull);
      expect(state['current_next_cursor'], isNull);
    });
  });

  group('INSERT/SELECT with all columns', () {
    test('job round-trip: all 17 columns persisted and read back', () async {
      final db = await dbHelper.database;

      await db.insert('jobs', {
        'id': '100',
        'order_id': '200',
        'job_number': 'JN-001',
        'title': 'Job Title',
        'material': 'Acero',
        'size': '10x20',
        'quantity': 5,
        'status': 'pending',
        'notes': 'Some notes',
        'sort_order': 3,
        'priority': 'high',
        'client_id': 'C1',
        'assigned_to': 'Tech A',
        'due_date': '2026-08-01',
        'created_at': '2026-07-20T08:00:00',
        'updated_at': '2026-07-20T09:00:00',
        'metadata': '{"key":"value"}',
      });

      final rows = await db.query('jobs', where: 'id = ?', whereArgs: ['100']);
      expect(rows.length, 1);

      final row = rows.first;
      expect(row['order_id'], '200');
      expect(row['material'], 'Acero');
      expect(row['size'], '10x20');
      expect(row['quantity'], 5);
      expect(row['notes'], 'Some notes');
      expect(row['sort_order'], 3);
      expect(row['priority'], 'high');
    });

    test('order round-trip: all 22 columns persisted and read back', () async {
      final db = await dbHelper.database;

      await db.insert('orders', {
        'id': '300',
        'order_number': 'ON-001',
        'job_id': '100',
        'client_id': 'C1',
        'client': 'John Doe',
        'whatsapp': '+549115555',
        'status': 'production',
        'material': 'Acero',
        'size': '20x30',
        'quantity': 10,
        'delivery_date': '2026-08-15',
        'print_priority': 'high',
        'is_archived': 0,
        'observations': 'Urgent',
        'order_concept': 'Signage',
        'order_description': 'Outdoor sign',
        'total_amount': 1500.50,
        'currency': 'USD',
        'order_date': '2026-07-20',
        'created_at': '2026-07-20T08:00:00',
        'updated_at': '2026-07-20T09:00:00',
        'metadata': '{"r":1}',
      });

      final rows =
          await db.query('orders', where: 'id = ?', whereArgs: ['300']);
      expect(rows.length, 1);

      final row = rows.first;
      expect(row['client'], 'John Doe');
      expect(row['whatsapp'], '+549115555');
      expect(row['material'], 'Acero');
      expect(row['delivery_date'], '2026-08-15');
      expect(row['print_priority'], 'high');
      expect(row['is_archived'], 0);
      expect(row['observations'], 'Urgent');
      expect(row['order_concept'], 'Signage');
      expect(row['order_description'], 'Outdoor sign');
    });
  });

  group('Batch INSERT inside transaction — deadlock regression', () {
    test('batch.commit() within db.transaction() completes without hanging',
        () async {
      final db = await dbHelper.database;

      // This is the exact pattern that caused the deadlock before the fix.
      // db.transaction() opens a lock, then db.batch() inside would try
      // to acquire the same lock on the raw db handle.
      // With the fix, both operations must use `txn`, not `db`.
      await db.transaction((txn) async {
        final batch = txn.batch();
        batch.insert('jobs', {
          'id': 'B1',
          'title': 'Batch Job',
          'status': 'pending',
          'created_at': '2026-07-20',
          'updated_at': '2026-07-20',
        });
        batch.insert('orders', {
          'id': 'B2',
          'status': 'pending',
          'order_date': '2026-07-20',
          'created_at': '2026-07-20',
          'updated_at': '2026-07-20',
        });
        batch.insert('clients', {
          'id': 'B3',
          'name': 'Batch Client',
          'created_at': '2026-07-20',
          'updated_at': '2026-07-20',
        });
        await batch.commit(noResult: true);
      });

      final jobs = await db.query('jobs');
      final orders = await db.query('orders');
      final clients = await db.query('clients');

      expect(jobs.length, 1);
      expect(orders.length, 1);
      expect(clients.length, 1);
    });
  });

  group('Full SyncService flow with real database', () {
    test('sync inserts jobs, orders, clients — no SQLiteException', () async {
      final syncStateRepo = SyncStateRepository(dbHelper);
      final jobsRepo = JobsRepository(dbHelper);
      final ordersRepo = OrdersRepository(dbHelper);
      final clientsRepo = ClientsRepository(dbHelper);

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
                    'order_id': 10,
                    'title': 'Integration Job',
                    'material': 'Acero',
                    'size': '100x200',
                    'quantity': 3,
                    'status': 'pending',
                    'notes': 'Test note',
                    'sort_order': 0,
                    'priority': 'high',
                    'client_id': 1,
                    'assigned_to': 'Tech',
                    'due_date': '2026-08-01',
                    'created_at': '2026-07-20T08:00:00',
                    'updated_at': '2026-07-20T09:00:00',
                  },
                  {
                    'id': 2,
                    'title': 'Second Job',
                    'status': 'done',
                    'sort_order': 1,
                    'created_at': '2026-07-20T08:00:00',
                    'updated_at': '2026-07-20T10:00:00',
                  },
                ],
                'has_more': false,
              },
              'orders': {
                'items': [
                  {
                    'id': 10,
                    'client_id': 1,
                    'client': 'John Doe',
                    'whatsapp': '+549115555',
                    'status': 'production',
                    'material': 'Acero',
                    'quantity': 5,
                    'delivery_date': '2026-08-15',
                    'print_priority': 'high',
                    'is_archived': 0,
                    'order_date': '2026-07-20',
                    'created_at': '2026-07-20T08:00:00',
                    'updated_at': '2026-07-20T09:00:00',
                  },
                ],
                'has_more': false,
              },
              'clients': {
                'items': [
                  {
                    'id': 1,
                    'name': 'John Doe',
                    'phone': '+549115555',
                    'created_at': '2026-07-20T08:00:00',
                    'updated_at': '2026-07-20T09:00:00',
                  },
                ],
                'has_more': false,
              },
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

      // This must not throw SQLiteException or hang
      final result = await syncService.startSync();

      expect(result.isSuccess, true, reason: result.error);
      expect(result.completed, true);
      expect(result.jobsUpdated, 2);
      expect(result.ordersUpdated, 1);
      expect(result.clientsUpdated, 1);

      // Verify data persisted
      final jobs = await jobsRepo.getAllJobs();
      expect(jobs.length, 2);
      expect(jobs[0].id, '2');
      expect(jobs[1].id, '1');
      expect(jobs[1].material, 'Acero');
      expect(jobs[1].sortOrder, 0);

      final orders = await ordersRepo.getAllOrders();
      expect(orders.length, 1);
      expect(orders.first.id, '10');
      expect(orders.first.client, 'John Doe');
      expect(orders.first.whatsapp, '+549115555');
      expect(orders.first.material, 'Acero');
      expect(orders.first.deliveryDate, '2026-08-15');
      expect(orders.first.printPriority, 'high');

      final clients = await clientsRepo.getAllClients();
      expect(clients.length, 1);
      expect(clients.first.id, '1');
      expect(clients.first.name, 'John Doe');

      // Verify sync state
      final syncState = await syncStateRepo.getSyncState();
      expect(syncState.lastCompletedSnapshot, '2026-07-21T10:00:00');
      expect(syncState.lastSyncError, null);

      apiClient.close();
    });

    test('multi-page syncAll with real DB — 3 pages, no deadlock', () async {
      final syncStateRepo = SyncStateRepository(dbHelper);
      final jobsRepo = JobsRepository(dbHelper);
      final ordersRepo = OrdersRepository(dbHelper);
      final clientsRepo = ClientsRepository(dbHelper);

      int requestCount = 0;

      final mockClient = MockClient((request) async {
        if (request.url.path == '/api/v1/mobile/catalog/designs') {
          return http.Response(jsonEncode({'designs': []}), 200);
        }
        requestCount++;

        if (requestCount == 1) {
          return http.Response(
            jsonEncode({
              'server_time': '2026-07-21T10:00:00',
              'snapshot_until': '2026-07-21T10:00:00',
              'complete': false,
              'next_cursor': 'cursor-p2',
              'entities': {
                'jobs': {
                  'items': [
                    {
                      'id': 1,
                      'title': 'Page 1 Job',
                      'status': 'pending',
                      'sort_order': 0,
                      'created_at': '2026-07-20T08:00:00',
                      'updated_at': '2026-07-20T09:00:00',
                    },
                  ],
                  'has_more': true,
                },
                'orders': {'items': [], 'has_more': false},
                'clients': {'items': [], 'has_more': false},
              },
            }),
            200,
          );
        } else if (requestCount == 2) {
          return http.Response(
            jsonEncode({
              'server_time': '2026-07-21T10:00:00',
              'snapshot_until': '2026-07-21T10:00:00',
              'complete': false,
              'next_cursor': 'cursor-p3',
              'entities': {
                'jobs': {
                  'items': [
                    {
                      'id': 2,
                      'title': 'Page 2 Job',
                      'status': 'done',
                      'sort_order': 1,
                      'created_at': '2026-07-20T08:00:00',
                      'updated_at': '2026-07-20T10:00:00',
                    },
                  ],
                  'has_more': true,
                },
                'orders': {
                  'items': [
                    {
                      'id': 10,
                      'client_id': 1,
                      'status': 'pending',
                      'order_date': '2026-07-20',
                      'created_at': '2026-07-20T08:00:00',
                      'updated_at': '2026-07-20T09:00:00',
                    },
                  ],
                  'has_more': false,
                },
                'clients': {'items': [], 'has_more': false},
              },
            }),
            200,
          );
        } else {
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
                      'id': 3,
                      'title': 'Page 3 Job',
                      'status': 'pending',
                      'sort_order': 2,
                      'created_at': '2026-07-20T08:00:00',
                      'updated_at': '2026-07-20T11:00:00',
                    },
                  ],
                  'has_more': false,
                },
                'orders': {'items': [], 'has_more': false},
                'clients': {
                  'items': [
                    {
                      'id': 1,
                      'name': 'Client Page 3',
                      'created_at': '2026-07-20T08:00:00',
                      'updated_at': '2026-07-20T09:00:00',
                    },
                  ],
                  'has_more': false,
                },
              },
            }),
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

      final result = await syncService.syncAll();

      expect(result.isSuccess, true, reason: result.error);
      expect(result.completed, true);
      expect(result.jobsUpdated, 3);
      expect(requestCount, 3);

      final jobs = await jobsRepo.getAllJobs();
      expect(jobs.length, 3);

      final orders = await ordersRepo.getAllOrders();
      expect(orders.length, 1);

      final clients = await clientsRepo.getAllClients();
      expect(clients.length, 1);

      final hasIncomplete = await syncService.hasIncompleteSync();
      expect(hasIncomplete, false);

      apiClient.close();
    });

    test('rollback on handler error — no data persisted after exception',
        () async {
      final syncStateRepo = SyncStateRepository(dbHelper);

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
                    'title': 'Should Rollback',
                    'status': 'pending',
                    'sort_order': 0,
                    'created_at': '2026-07-20T08:00:00',
                    'updated_at': '2026-07-20T09:00:00',
                  },
                ],
                'has_more': false,
              },
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

      // Handler that throws mid-transaction
      syncService.registerHandler('jobs', _ExplodingHandler());

      final result = await syncService.startSync();

      expect(result.hasError, true);

      // Transaction rolled back — nothing persisted
      final db = await dbHelper.database;
      final jobs = await db.query('jobs');
      final orders = await db.query('orders');
      final clients = await db.query('clients');
      expect(jobs.length, 0);
      expect(orders.length, 0);
      expect(clients.length, 0);

      apiClient.close();
    });
  });
}

class _ExplodingHandler implements JobsSyncHandler {
  @override
  String get entityType => 'jobs';

  @override
  Future<void> process(List<Map<String, dynamic>> items,
      {Transaction? txn}) async {
    throw Exception('Simulated mid-transaction failure');
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}
