import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:path/path.dart' as path;
import 'package:path_provider/path_provider.dart';

import '../database/pending_orders_repository.dart';
import '../models/pos_cart.dart';
import '../models/mockup_reference.dart';
import 'catalog_api_client.dart';
import 'session_scope.dart';

/// Cola durable: si Studio no responde, el pedido queda en el teléfono hasta
/// que el vendedor pulse sincronizar nuevamente al volver al negocio.
class OfflineOrdersService {
  final PendingOrdersRepository _repository;
  final CatalogApiClient _api;
  final Future<String?> Function() _ownerScopeProvider;
  OfflineOrdersService(this._repository, this._api,
      {Future<String?> Function()? ownerScopeProvider})
      : _ownerScopeProvider = ownerScopeProvider ?? SessionScope.current;

  Future<String> _ownerScope() async {
    final scope = await _ownerScopeProvider();
    if (scope == null || scope.trim().isEmpty) {
      throw StateError('No se puede guardar un pedido sin vendedor activo.');
    }
    return scope;
  }

  static String newRequestId() =>
      '${DateTime.now().microsecondsSinceEpoch}-${Random().nextInt(1 << 32)}';

  Future<void> queueStickerOrder({
    required String requestId,
    required String client,
    required String whatsapp,
    required String observations,
    required String mode,
    required List<String> catalogDesignIds,
    required List<File> images,
    List<MockupReference> referenceImages = const [],
  }) async {
    final copies = <String>[];
    final documents = await getApplicationDocumentsDirectory();
    final folder = Directory(path.join(documents.path, 'pending_order_images'));
    await folder.create(recursive: true);
    for (final image in images) {
      final extension = path.extension(image.path).isEmpty
          ? '.jpg'
          : path.extension(image.path);
      final copy = File(path.join(folder.path,
          '${DateTime.now().microsecondsSinceEpoch}_${Random().nextInt(1 << 20)}$extension'));
      await image.copy(copy.path);
      copies.add(copy.path);
    }
    final referenceCopies = <String>[];
    final referenceMetadata = <Map<String, Object?>>[];
    for (final reference in referenceImages) {
      final image = reference.file;
      final extension = path.extension(image.path).isEmpty
          ? '.jpg'
          : path.extension(image.path);
      final copy = File(path.join(folder.path,
          'mockup_${DateTime.now().microsecondsSinceEpoch}_${Random().nextInt(1 << 20)}$extension'));
      await image.copy(copy.path);
      copies.add(copy.path);
      referenceCopies.add(copy.path);
      referenceMetadata.add(reference.toUploadJson(storedPath: copy.path));
    }
    await _repository.enqueue(PendingOrder(
      id: requestId,
      type: 'sticker',
      imagePaths: copies,
      ownerScope: await _ownerScope(),
      payload: jsonEncode({
        'client': client,
        'whatsapp': whatsapp,
        'observations': observations,
        'mode': mode,
        'catalog_design_ids': catalogDesignIds,
        'reference_image_paths': referenceCopies,
        'reference_metadata': referenceMetadata,
      }),
    ));
  }

  Future<void> queueProductOrder({
    required String requestId,
    required String client,
    required String whatsapp,
    required String observations,
    required Map<String, int> items,
  }) async {
    await _repository.enqueue(PendingOrder(
      id: requestId,
      type: 'product',
      imagePaths: const [],
      ownerScope: await _ownerScope(),
      payload: jsonEncode({
        'client': client,
        'whatsapp': whatsapp,
        'observations': observations,
        'items': items,
      }),
    ));
  }

  Future<void> queueProductOrderLines({
    required String requestId,
    required String client,
    required String whatsapp,
    required String observations,
    required List<PosProductLine> items,
    int? targetOrderId,
  }) =>
      _enqueueProductOrderLines(
        requestId: requestId,
        client: client,
        whatsapp: whatsapp,
        observations: observations,
        items: items,
        targetOrderId: targetOrderId,
      );

  Future<void> _enqueueProductOrderLines({
    required String requestId,
    required String client,
    required String whatsapp,
    required String observations,
    required List<PosProductLine> items,
    int? targetOrderId,
  }) async =>
      _repository.enqueue(PendingOrder(
        id: requestId,
        type: 'product_lines',
        imagePaths: const [],
        ownerScope: await _ownerScope(),
        payload: jsonEncode({
          'client': client,
          'whatsapp': whatsapp,
          'observations': observations,
          'items': items.map((item) => item.toRequestJson()).toList(),
          if (targetOrderId != null) 'target_order_id': targetOrderId,
        }),
      ));

  Future<int> sendPending() async {
    var sent = 0;
    final ownerScope = await _ownerScope();
    for (final pending in await _repository.all(ownerScope: ownerScope)) {
      try {
        final data = jsonDecode(pending.payload) as Map<String, dynamic>;
        late final int orderId;
        if (pending.type == 'sticker') {
          final referencePaths =
              (data['reference_image_paths'] as List? ?? const [])
                  .cast<String>();
          final referenceMetadata =
              (data['reference_metadata'] as List? ?? const []);
          orderId = await _api.createStickerOrder(
            clientRequestId: pending.id,
            client: data['client'] as String,
            whatsapp: data['whatsapp'] as String,
            observations: data['observations'] as String,
            mode: data['mode'] as String,
            catalogDesignIds:
                (data['catalog_design_ids'] as List).cast<String>(),
            images: pending.imagePaths
                .where((item) => !referencePaths.contains(item))
                .map(File.new)
                .toList(),
            referenceImages: [
              for (var index = 0; index < referencePaths.length; index++)
                MockupReference.fromQueuedJson(
                  index < referenceMetadata.length
                      ? Map<String, dynamic>.from(
                          referenceMetadata[index] as Map)
                      : const <String, dynamic>{},
                  file: File(referencePaths[index]),
                ),
            ],
          );
        } else if (pending.type == 'product') {
          orderId = await _api.createProductOrder(
            client: data['client'] as String,
            whatsapp: data['whatsapp'] as String,
            observations: data['observations'] as String,
            items: Map<String, int>.from((data['items'] as Map).map(
              (key, value) => MapEntry(key.toString(), (value as num).toInt()),
            )),
          );
        } else if (pending.type == 'product_lines') {
          final items = (data['items'] as List)
              .map((value) => value as Map<String, dynamic>)
              .map((item) => PosProductLine(
                    productCode: item['product_code'].toString(),
                    productName: '',
                    variantCode: item['variant_code']?.toString(),
                    unitPrice: 0,
                    quantity: (item['quantity'] as num).toInt(),
                  ))
              .toList();
          orderId = await _api.createProductOrderLines(
            client: data['client'] as String,
            whatsapp: data['whatsapp'] as String,
            observations: data['observations'] as String,
            items: items,
            targetOrderId: data['target_order_id'] as int?,
          );
        } else {
          throw Exception(
              'Tipo de pedido pendiente desconocido: ${pending.type}');
        }
        await _repository.markUploaded(pending.id, orderId);
        for (final image in pending.imagePaths) {
          try {
            await File(image).delete();
          } catch (_) {
            // La cola ya se confirmó; un archivo huérfano no bloquea la venta.
          }
        }
        sent++;
      } catch (error) {
        await _repository.recordFailure(pending.id, error);
        break; // La red puede haber caído: conserva el orden de los pedidos.
      }
    }
    return sent;
  }
}
