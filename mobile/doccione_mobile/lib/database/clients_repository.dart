import 'package:sqflite/sqflite.dart';
import '../models/client.dart';
import 'database_helper.dart';

/// Repository for managing clients persistence with upsert support
class ClientsRepository {
  final DatabaseHelper _dbHelper;

  ClientsRepository(this._dbHelper);

  /// Upsert a single client (insert or update if exists)
  Future<void> upsertClient(Map<String, dynamic> clientData) async {
    final db = await _dbHelper.database;
    final client = Client.fromMap(clientData);
    
    await db.insert(
      'clients',
      client.toMap(),
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  /// Upsert multiple clients in a batch operation
  Future<void> upsertClients(List<Map<String, dynamic>> clientsData) async {
    final db = await _dbHelper.database;
    final batch = db.batch();

    for (final clientData in clientsData) {
      final client = Client.fromMap(clientData);
      batch.insert(
        'clients',
        client.toMap(),
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
    }

    await batch.commit(noResult: true);
  }

  /// Get all clients
  Future<List<Client>> getAllClients() async {
    final db = await _dbHelper.database;
    final List<Map<String, dynamic>> maps = await db.query(
      'clients',
      orderBy: 'name ASC',
    );

    return maps.map((map) => Client.fromMap(map)).toList();
  }

  /// Get client by ID
  Future<Client?> getClientById(String id) async {
    final db = await _dbHelper.database;
    final List<Map<String, dynamic>> maps = await db.query(
      'clients',
      where: 'id = ?',
      whereArgs: [id],
    );

    if (maps.isEmpty) return null;
    return Client.fromMap(maps.first);
  }

  /// Search clients by name
  Future<List<Client>> searchClientsByName(String query) async {
    final db = await _dbHelper.database;
    final List<Map<String, dynamic>> maps = await db.query(
      'clients',
      where: 'name LIKE ?',
      whereArgs: ['%$query%'],
      orderBy: 'name ASC',
    );

    return maps.map((map) => Client.fromMap(map)).toList();
  }

  /// Get clients by company
  Future<List<Client>> getClientsByCompany(String company) async {
    final db = await _dbHelper.database;
    final List<Map<String, dynamic>> maps = await db.query(
      'clients',
      where: 'company = ?',
      whereArgs: [company],
      orderBy: 'name ASC',
    );

    return maps.map((map) => Client.fromMap(map)).toList();
  }

  /// Count total clients
  Future<int> countClients() async {
    final db = await _dbHelper.database;
    final result = await db.rawQuery('SELECT COUNT(*) as count FROM clients');
    return Sqflite.firstIntValue(result) ?? 0;
  }

  /// Clear all clients (use with caution)
  Future<void> clearClients() async {
    final db = await _dbHelper.database;
    await db.delete('clients');
  }
}
