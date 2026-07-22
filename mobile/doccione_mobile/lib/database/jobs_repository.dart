import 'package:sqflite/sqflite.dart';
import '../models/job.dart';
import 'database_helper.dart';

/// Repository for managing jobs persistence with upsert support
class JobsRepository {
  final DatabaseHelper _dbHelper;

  JobsRepository(this._dbHelper);

  /// Upsert a single job (insert or update if exists)
  Future<void> upsertJob(Map<String, dynamic> jobData, {Transaction? txn}) async {
    final executor = txn ?? await _dbHelper.database;
    final job = Job.fromMap(jobData);

    await executor.insert(
      'jobs',
      job.toMap(),
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  /// Upsert multiple jobs in a batch operation
  Future<void> upsertJobs(List<Map<String, dynamic>> jobsData, {Transaction? txn}) async {
    final executor = txn ?? await _dbHelper.database;
    final batch = executor.batch();

    for (final jobData in jobsData) {
      final job = Job.fromMap(jobData);
      batch.insert(
        'jobs',
        job.toMap(),
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
    }

    await batch.commit(noResult: true);
  }

  /// Get all jobs
  Future<List<Job>> getAllJobs() async {
    final db = await _dbHelper.database;
    final List<Map<String, dynamic>> maps = await db.query(
      'jobs',
      orderBy: 'updated_at DESC',
    );

    return maps.map((map) => Job.fromMap(map)).toList();
  }

  /// Get job by ID
  Future<Job?> getJobById(String id) async {
    final db = await _dbHelper.database;
    final List<Map<String, dynamic>> maps = await db.query(
      'jobs',
      where: 'id = ?',
      whereArgs: [id],
    );

    if (maps.isEmpty) return null;
    return Job.fromMap(maps.first);
  }

  /// Get jobs by status
  Future<List<Job>> getJobsByStatus(String status) async {
    final db = await _dbHelper.database;
    final List<Map<String, dynamic>> maps = await db.query(
      'jobs',
      where: 'status = ?',
      whereArgs: [status],
      orderBy: 'updated_at DESC',
    );

    return maps.map((map) => Job.fromMap(map)).toList();
  }

  /// Get jobs by client ID
  Future<List<Job>> getJobsByClientId(String clientId) async {
    final db = await _dbHelper.database;
    final List<Map<String, dynamic>> maps = await db.query(
      'jobs',
      where: 'client_id = ?',
      whereArgs: [clientId],
      orderBy: 'updated_at DESC',
    );

    return maps.map((map) => Job.fromMap(map)).toList();
  }

  /// Count total jobs
  Future<int> countJobs() async {
    final db = await _dbHelper.database;
    final result = await db.rawQuery('SELECT COUNT(*) as count FROM jobs');
    return Sqflite.firstIntValue(result) ?? 0;
  }

  /// Clear all jobs (use with caution)
  Future<void> clearJobs() async {
    final db = await _dbHelper.database;
    await db.delete('jobs');
  }
}
