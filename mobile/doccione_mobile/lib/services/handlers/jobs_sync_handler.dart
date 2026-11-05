import 'package:sqflite/sqflite.dart';
import '../../database/jobs_repository.dart';
import 'sync_entity_handler.dart';

/// Handler for synchronizing jobs data
class JobsSyncHandler implements SyncEntityHandler {
  final JobsRepository _repository;

  JobsSyncHandler(this._repository);

  @override
  String get entityType => 'jobs';

  @override
  Future<void> process(List<Map<String, dynamic>> items,
      {Transaction? txn}) async {
    if (items.isEmpty) return;
    await _repository.upsertJobs(items, txn: txn);
  }
}
