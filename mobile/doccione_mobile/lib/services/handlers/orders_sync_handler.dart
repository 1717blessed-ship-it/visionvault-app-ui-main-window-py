import 'package:sqflite/sqflite.dart';
import '../../database/orders_repository.dart';
import 'sync_entity_handler.dart';

/// Handler for synchronizing orders data
class OrdersSyncHandler implements SyncEntityHandler {
  final OrdersRepository _repository;

  OrdersSyncHandler(this._repository);

  @override
  String get entityType => 'orders';

  @override
  Future<void> process(List<Map<String, dynamic>> items, {Transaction? txn}) async {
    if (items.isEmpty) return;
    await _repository.upsertOrders(items, txn: txn);
  }
}
