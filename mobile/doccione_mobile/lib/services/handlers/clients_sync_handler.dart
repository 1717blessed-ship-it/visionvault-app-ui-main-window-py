import '../../database/clients_repository.dart';
import 'sync_entity_handler.dart';

/// Handler for synchronizing clients data
class ClientsSyncHandler implements SyncEntityHandler {
  final ClientsRepository _repository;

  ClientsSyncHandler(this._repository);

  @override
  String get entityType => 'clients';

  @override
  Future<void> process(List<Map<String, dynamic>> items) async {
    if (items.isEmpty) return;
    await _repository.upsertClients(items);
  }
}
