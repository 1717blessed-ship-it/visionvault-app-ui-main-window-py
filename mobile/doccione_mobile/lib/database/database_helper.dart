import 'dart:io';
import 'dart:isolate';

import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart';
import 'package:path_provider/path_provider.dart';

/// Helper class for SQLite database operations with versioning support
class DatabaseHelper {
  static const int _databaseVersion = 18;
  static const String _databaseName = 'doccione_mobile.db';

  static DatabaseHelper? _instance;
  static Database? _database;
  static Future<Database>? _openingDatabase;

  DatabaseHelper._();

  factory DatabaseHelper() {
    _instance ??= DatabaseHelper._();
    return _instance!;
  }

  Future<Database> get database async {
    if (_database != null) return _database!;
    final opening = _openingDatabase ??= _initDatabase();
    try {
      return _database = await opening;
    } finally {
      if (identical(_openingDatabase, opening)) {
        _openingDatabase = null;
      }
    }
  }

  Future<Database> _initDatabase() async {
    final path = await _resolveDatabasePath();

    return await openDatabase(
      path,
      version: _databaseVersion,
      onCreate: _onCreate,
      onUpgrade: _onUpgrade,
    );
  }

  Future<void> _onCreate(Database db, int version) async {
    // Create sync_state table (without sync_in_progress)
    await db.execute('''
      CREATE TABLE sync_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        last_completed_snapshot TEXT,
        current_next_cursor TEXT,
        scope_id TEXT,
        last_sync_at TEXT,
        last_sync_error TEXT
      )
    ''');

    // Initialize sync_state with single row
    await db.insert('sync_state', {
      'id': 1,
      'last_completed_snapshot': null,
      'current_next_cursor': null,
      'scope_id': null,
      'last_sync_at': null,
      'last_sync_error': null,
    });

    // Create jobs table
    await db.execute('''
      CREATE TABLE jobs (
        id TEXT PRIMARY KEY,
        order_id TEXT,
        job_number TEXT,
        title TEXT,
        material TEXT,
        size TEXT,
        quantity INTEGER,
        status TEXT,
        notes TEXT,
        sort_order INTEGER,
        priority TEXT,
        client_id TEXT,
        assigned_to TEXT,
        due_date TEXT,
        created_at TEXT,
        updated_at TEXT,
        metadata TEXT
      )
    ''');

    // Create jobs indices
    await db.execute('CREATE INDEX idx_jobs_status ON jobs(status)');
    await db.execute('CREATE INDEX idx_jobs_updated ON jobs(updated_at DESC)');
    await db.execute('CREATE INDEX idx_jobs_client ON jobs(client_id)');

    // Create orders table
    await db.execute('''
      CREATE TABLE orders (
        id TEXT PRIMARY KEY,
        order_number TEXT,
        job_id TEXT,
        client_id TEXT,
        client TEXT,
        whatsapp TEXT,
        status TEXT,
        material TEXT,
        size TEXT,
        quantity INTEGER,
        delivery_date TEXT,
        print_priority TEXT,
        is_archived INTEGER,
        observations TEXT,
        order_concept TEXT,
        order_description TEXT,
        total_amount REAL,
        currency TEXT,
        order_date TEXT,
        created_at TEXT,
        updated_at TEXT,
        metadata TEXT
      )
    ''');

    // Create orders indices
    await db.execute('CREATE INDEX idx_orders_status ON orders(status)');
    await db
        .execute('CREATE INDEX idx_orders_updated ON orders(updated_at DESC)');
    await db.execute('CREATE INDEX idx_orders_job ON orders(job_id)');

    // Create clients table
    await db.execute('''
      CREATE TABLE clients (
        id TEXT PRIMARY KEY,
        name TEXT,
        email TEXT,
        phone TEXT,
        company TEXT,
        address TEXT,
        created_at TEXT,
        updated_at TEXT,
        metadata TEXT
      )
    ''');

    // Create clients indices
    await db.execute('CREATE INDEX idx_clients_name ON clients(name)');
    await db.execute(
        'CREATE INDEX idx_clients_updated ON clients(updated_at DESC)');

    // Create server_config table (singleton)
    await db.execute('''
      CREATE TABLE server_config (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        host TEXT NOT NULL DEFAULT 'localhost',
        port INTEGER NOT NULL DEFAULT 8765,
        scheme TEXT NOT NULL DEFAULT 'http'
      )
    ''');

    // Initialize server_config with default values
    await db.insert('server_config', {
      'id': 1,
      'host': 'localhost',
      'port': 8765,
      'scheme': 'http',
    });

    await _createVisitsTable(db);
    await _createVisitHistoryTable(db);
    await _createOfflineCatalogTables(db);
    await _createPendingOrdersTable(db);
    await _createOrderDraftsTable(db);
    await _createStickerCreatorTables(db);
  }

  Future<void> _createVisitsTable(DatabaseExecutor db) async {
    await db.execute('''
      CREATE TABLE IF NOT EXISTS visit_pins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        note TEXT,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        created_at TEXT NOT NULL
        ,status TEXT NOT NULL DEFAULT 'pending'
        ,scheduled_at TEXT
        ,client_id TEXT
        ,client_phone TEXT
        ,client_uuid TEXT
        ,sync_dirty INTEGER NOT NULL DEFAULT 1
        ,deleted INTEGER NOT NULL DEFAULT 0
        ,updated_at TEXT NOT NULL
        ,server_version INTEGER NOT NULL DEFAULT 0
        ,sync_conflict INTEGER NOT NULL DEFAULT 0
        ,conflict_payload TEXT
        ,zone TEXT
        ,result TEXT
        ,last_contact_at TEXT
      )
    ''');
    await db.execute(
      'CREATE INDEX IF NOT EXISTS idx_visit_pins_created ON visit_pins(created_at DESC)',
    );
    await db.execute(
      'CREATE INDEX IF NOT EXISTS idx_visit_pins_schedule ON visit_pins(scheduled_at)',
    );
    await db.execute(
      'CREATE UNIQUE INDEX IF NOT EXISTS idx_visit_pins_uuid ON visit_pins(client_uuid)',
    );
  }

  Future<void> _createOfflineCatalogTables(DatabaseExecutor db) async {
    await db.execute('''
      CREATE TABLE IF NOT EXISTS catalog_designs (
        id TEXT PRIMARY KEY, data TEXT NOT NULL, cached_preview_path TEXT,
        updated_at TEXT NOT NULL
      )
    ''');
    await db.execute('''
      CREATE TABLE IF NOT EXISTS catalog_filters (
        kind TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (kind, value)
      )
    ''');
    await db.execute('''
      CREATE TABLE IF NOT EXISTS catalog_products (
        code TEXT PRIMARY KEY, data TEXT NOT NULL, cached_preview_path TEXT,
        updated_at TEXT NOT NULL
      )
    ''');
  }

  Future<void> _createVisitHistoryTable(DatabaseExecutor db) async {
    await db.execute(
        'CREATE TABLE IF NOT EXISTS visit_history (id INTEGER PRIMARY KEY AUTOINCREMENT, event_uuid TEXT NOT NULL, client_uuid TEXT NOT NULL, action TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL, sync_dirty INTEGER NOT NULL DEFAULT 1)');
    await db.execute(
        'CREATE INDEX IF NOT EXISTS idx_visit_history_pin ON visit_history(client_uuid, created_at DESC)');
    await db.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_visit_history_uuid ON visit_history(event_uuid)');
    await db.execute('''CREATE TABLE IF NOT EXISTS visit_attachments (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      attachment_uuid TEXT NOT NULL UNIQUE,
      client_uuid TEXT NOT NULL,
      local_path TEXT NOT NULL,
      file_name TEXT NOT NULL,
      mime_type TEXT NOT NULL,
      created_at TEXT NOT NULL,
      sync_dirty INTEGER NOT NULL DEFAULT 1,
      deleted INTEGER NOT NULL DEFAULT 0
    )''');
    await db.execute(
        'CREATE INDEX IF NOT EXISTS idx_visit_attachments_pin ON visit_attachments(client_uuid, created_at DESC)');
    await db.execute('''CREATE TABLE IF NOT EXISTS visit_reminder_state (
      key TEXT PRIMARY KEY, value TEXT NOT NULL
    )''');
  }

  Future<void> _createOrderDraftsTable(DatabaseExecutor db) async {
    await db.execute('''CREATE TABLE IF NOT EXISTS order_drafts (
      id TEXT NOT NULL, owner_scope TEXT NOT NULL, revision INTEGER NOT NULL,
      payload TEXT NOT NULL, updated_at TEXT NOT NULL,
      PRIMARY KEY (id, owner_scope))''');
  }

  Future<void> _createPendingOrdersTable(DatabaseExecutor db) async {
    await db.execute('''
      CREATE TABLE IF NOT EXISTS pending_orders (
        id TEXT PRIMARY KEY, type TEXT NOT NULL, payload TEXT NOT NULL,
        image_paths TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL,
        last_error TEXT, attempts INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending', remote_order_id INTEGER,
        completed_at TEXT, owner_scope TEXT NOT NULL
      )
    ''');
    await db.execute(
        'CREATE INDEX IF NOT EXISTS idx_pending_orders_owner_status ON pending_orders(owner_scope, status, created_at)');
  }

  Future<String> _resolveDatabasePath() async {
    // path_provider is not registered by default in widget tests; do not wait
    // for an unresolved method-channel Future before using sqflite's path.
    if (Platform.environment['FLUTTER_TEST'] == 'true') {
      final databasesDirectory = await getDatabasesPath();
      return join(databasesDirectory,
          'doccione_mobile_${pid}_${Isolate.current.hashCode}.db');
    }
    try {
      final documentsDirectory = await getApplicationDocumentsDirectory();
      return join(documentsDirectory.path, _databaseName);
    } catch (_) {
      // Flutter tests and desktop embedders may not register path_provider.
      // The sqflite factory still exposes a valid database directory there.
      final databasesDirectory = await getDatabasesPath();
      return join(databasesDirectory, _databaseName);
    }
  }

  Future<void> _createStickerCreatorTables(DatabaseExecutor db) async {
    await db.execute('''
      CREATE TABLE IF NOT EXISTS sticker_creator_jobs (
        id TEXT PRIMARY KEY,
        source_path TEXT NOT NULL,
        result_path TEXT,
        mask_path TEXT,
        status TEXT NOT NULL,
        quality_notes TEXT NOT NULL DEFAULT '[]',
        category TEXT NOT NULL DEFAULT '',
        tags TEXT NOT NULL DEFAULT '[]',
        profile TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      )
    ''');
    await db.execute(
      'CREATE INDEX IF NOT EXISTS idx_sticker_creator_jobs_updated ON sticker_creator_jobs(updated_at DESC)',
    );
  }

  Future<void> _addColumnIfMissing(
    Database db,
    String table,
    String column,
    String columnDefinition,
  ) async {
    final columns = await db.rawQuery('PRAGMA table_info($table)');
    final exists = columns.any((entry) => entry['name'] == column);
    if (!exists) {
      await db.execute('ALTER TABLE $table ADD COLUMN $columnDefinition');
    }
  }

  Future<void> _onUpgrade(Database db, int oldVersion, int newVersion) async {
    if (oldVersion < 18) await _createOrderDraftsTable(db);
    if (oldVersion < 2) {
      // Create server_config table for existing databases
      await db.execute('''
        CREATE TABLE IF NOT EXISTS server_config (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          host TEXT NOT NULL DEFAULT 'localhost',
          port INTEGER NOT NULL DEFAULT 8765,
          scheme TEXT NOT NULL DEFAULT 'http'
        )
      ''');

      // Insert default values if table is empty
      final existing = await db.query('server_config', where: 'id = 1');
      if (existing.isEmpty) {
        await db.insert('server_config', {
          'id': 1,
          'host': 'localhost',
          'port': 8765,
          'scheme': 'http',
        });
      }
    }

    if (oldVersion < 3) {
      // Phase 4: add columns to jobs table
      await db.execute('ALTER TABLE jobs ADD COLUMN order_id TEXT');
      await db.execute('ALTER TABLE jobs ADD COLUMN material TEXT');
      await db.execute('ALTER TABLE jobs ADD COLUMN size TEXT');
      await db.execute('ALTER TABLE jobs ADD COLUMN quantity INTEGER');
      await db.execute('ALTER TABLE jobs ADD COLUMN notes TEXT');
      await db.execute('ALTER TABLE jobs ADD COLUMN sort_order INTEGER');

      // Phase 4: add columns to orders table
      await db.execute('ALTER TABLE orders ADD COLUMN client TEXT');
      await db.execute('ALTER TABLE orders ADD COLUMN whatsapp TEXT');
      await db.execute('ALTER TABLE orders ADD COLUMN material TEXT');
      await db.execute('ALTER TABLE orders ADD COLUMN size TEXT');
      await db.execute('ALTER TABLE orders ADD COLUMN quantity INTEGER');
      await db.execute('ALTER TABLE orders ADD COLUMN delivery_date TEXT');
      await db.execute('ALTER TABLE orders ADD COLUMN print_priority TEXT');
      await db.execute('ALTER TABLE orders ADD COLUMN is_archived INTEGER');
      await db.execute('ALTER TABLE orders ADD COLUMN observations TEXT');
      await db.execute('ALTER TABLE orders ADD COLUMN order_concept TEXT');
      await db.execute('ALTER TABLE orders ADD COLUMN order_description TEXT');
    }

    if (oldVersion < 4) {
      // Estos datos son un caché reconstruible. Se vacía al activar el alcance
      // por vendedor para que una versión anterior no muestre pedidos de la
      // empresa ni siquiera antes de la primera sincronización v4.
      await db.execute('ALTER TABLE sync_state ADD COLUMN scope_id TEXT');
      await db.delete('jobs');
      await db.delete('orders');
      await db.delete('clients');
      await db.update(
        'sync_state',
        {'current_next_cursor': null},
        where: 'id = ?',
        whereArgs: [1],
      );
    }

    if (oldVersion < 5) {
      await _createVisitsTable(db);
    }
    if (oldVersion < 6) {
      await _createOfflineCatalogTables(db);
    }
    if (oldVersion < 7) {
      await _createPendingOrdersTable(db);
    }
    if (oldVersion < 8) {
      // Algunas instalaciones v7 ya recibieron parte de este esquema. Cada
      // columna se valida por separado para que la actualización se pueda
      // retomar después de una instalación interrumpida.
      await _addColumnIfMissing(
        db,
        'pending_orders',
        'status',
        "status TEXT NOT NULL DEFAULT 'pending'",
      );
      await _addColumnIfMissing(
        db,
        'pending_orders',
        'remote_order_id',
        'remote_order_id INTEGER',
      );
      await _addColumnIfMissing(
        db,
        'pending_orders',
        'completed_at',
        'completed_at TEXT',
      );
    }
    if (oldVersion < 9) {
      await _addColumnIfMissing(
        db,
        'catalog_products',
        'cached_preview_path',
        'cached_preview_path TEXT',
      );
    }
    if (oldVersion < 10) {
      await _addColumnIfMissing(
          db, 'visit_pins', 'status', "status TEXT NOT NULL DEFAULT 'pending'");
      await _addColumnIfMissing(
          db, 'visit_pins', 'scheduled_at', 'scheduled_at TEXT');
      await _addColumnIfMissing(
          db, 'visit_pins', 'client_id', 'client_id TEXT');
      await _addColumnIfMissing(
          db, 'visit_pins', 'client_phone', 'client_phone TEXT');
      await db.execute(
          'CREATE INDEX IF NOT EXISTS idx_visit_pins_schedule ON visit_pins(scheduled_at)');
    }
    if (oldVersion < 11) {
      await _addColumnIfMissing(
          db, 'visit_pins', 'client_uuid', 'client_uuid TEXT');
      await db.execute(
          'CREATE UNIQUE INDEX IF NOT EXISTS idx_visit_pins_uuid ON visit_pins(client_uuid)');
      await db.execute(
          "UPDATE visit_pins SET client_uuid = 'legacy-' || id WHERE client_uuid IS NULL");
    }
    if (oldVersion < 12) {
      await _addColumnIfMissing(db, 'visit_pins', 'sync_dirty',
          'sync_dirty INTEGER NOT NULL DEFAULT 1');
    }
    if (oldVersion < 13) {
      await _addColumnIfMissing(
          db, 'visit_pins', 'deleted', 'deleted INTEGER NOT NULL DEFAULT 0');
    }
    if (oldVersion < 14) await _createVisitHistoryTable(db);
    if (oldVersion < 15) {
      await _addColumnIfMissing(
          db, 'visit_pins', 'updated_at', 'updated_at TEXT');
      await _addColumnIfMissing(db, 'visit_pins', 'server_version',
          'server_version INTEGER NOT NULL DEFAULT 0');
      await _addColumnIfMissing(db, 'visit_pins', 'sync_conflict',
          'sync_conflict INTEGER NOT NULL DEFAULT 0');
      await _addColumnIfMissing(
          db, 'visit_pins', 'conflict_payload', 'conflict_payload TEXT');
      await _addColumnIfMissing(db, 'visit_pins', 'zone', 'zone TEXT');
      await _addColumnIfMissing(db, 'visit_pins', 'result', 'result TEXT');
      await _addColumnIfMissing(
          db, 'visit_pins', 'last_contact_at', 'last_contact_at TEXT');
      await db.execute(
          'UPDATE visit_pins SET updated_at = created_at WHERE updated_at IS NULL');

      await _addColumnIfMissing(
          db, 'visit_history', 'event_uuid', 'event_uuid TEXT');
      await _addColumnIfMissing(db, 'visit_history', 'sync_dirty',
          'sync_dirty INTEGER NOT NULL DEFAULT 1');
      await db.execute(
          "UPDATE visit_history SET event_uuid = 'history-' || id WHERE event_uuid IS NULL");
      await _createVisitHistoryTable(db);
    }
    if (oldVersion < 16) await _createStickerCreatorTables(db);
    if (oldVersion < 17) {
      await _addColumnIfMissing(db, 'pending_orders', 'owner_scope',
          "owner_scope TEXT NOT NULL DEFAULT ''");
      // Las colas antiguas no tienen un dueño comprobable. Se conservan para
      // auditoría, pero no pueden enviarse usando la cuenta de otra persona.
      await db.update(
        'pending_orders',
        {'status': 'needs_owner'},
        where: "status = 'pending' AND owner_scope = ''",
      );
      await db.execute(
          'CREATE INDEX IF NOT EXISTS idx_pending_orders_owner_status ON pending_orders(owner_scope, status, created_at)');
    }
  }

  /// Close the database connection
  Future<void> close() async {
    final db = _database ?? await _openingDatabase;
    if (db != null && db.isOpen) await db.close();
    _database = null;
    _openingDatabase = null;
  }

  /// Los datos sincronizados y las visitas son privados de una sesión. La cola
  /// de pedidos se conserva porque ya está vinculada a su owner_scope.
  Future<void> clearSessionCaches() async {
    final db = await database;
    await db.transaction((txn) async {
      for (final table in [
        'jobs',
        'orders',
        'clients',
        'visit_pins',
        'visit_history',
        'visit_attachments',
      ]) {
        await txn.delete(table);
      }
      await txn.update(
          'sync_state',
          {
            'last_completed_snapshot': null,
            'current_next_cursor': null,
            'scope_id': null,
            'last_sync_at': null,
            'last_sync_error': null,
          },
          where: 'id = ?',
          whereArgs: [1]);
    });
  }

  /// Delete the database (useful for testing)
  Future<void> deleteDatabase() async {
    await close();
    final path = await _resolveDatabasePath();
    await databaseFactory.deleteDatabase(path);
  }
}
