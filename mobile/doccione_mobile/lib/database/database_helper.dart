import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart';
import 'package:path_provider/path_provider.dart';

/// Helper class for SQLite database operations with versioning support
class DatabaseHelper {
  static const int _databaseVersion = 3;
  static const String _databaseName = 'doccione_mobile.db';

  static DatabaseHelper? _instance;
  static Database? _database;

  DatabaseHelper._();

  factory DatabaseHelper() {
    _instance ??= DatabaseHelper._();
    return _instance!;
  }

  Future<Database> get database async {
    if (_database != null) return _database!;
    _database = await _initDatabase();
    return _database!;
  }

  Future<Database> _initDatabase() async {
    final documentsDirectory = await getApplicationDocumentsDirectory();
    final path = join(documentsDirectory.path, _databaseName);

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
        last_sync_at TEXT,
        last_sync_error TEXT
      )
    ''');

    // Initialize sync_state with single row
    await db.insert('sync_state', {
      'id': 1,
      'last_completed_snapshot': null,
      'current_next_cursor': null,
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
    await db.execute('CREATE INDEX idx_orders_updated ON orders(updated_at DESC)');
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
    await db.execute('CREATE INDEX idx_clients_updated ON clients(updated_at DESC)');

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
  }

  Future<void> _onUpgrade(Database db, int oldVersion, int newVersion) async {
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
  }

  /// Close the database connection
  Future<void> close() async {
    final db = await database;
    await db.close();
    _database = null;
  }

  /// Delete the database (useful for testing)
  Future<void> deleteDatabase() async {
    final documentsDirectory = await getApplicationDocumentsDirectory();
    final path = join(documentsDirectory.path, _databaseName);
    await databaseFactory.deleteDatabase(path);
    _database = null;
  }
}
