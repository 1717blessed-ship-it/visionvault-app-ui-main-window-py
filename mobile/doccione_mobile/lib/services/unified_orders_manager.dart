import 'dart:io';
import 'package:flutter/foundation.dart';

import '../database/database_helper.dart';
import '../database/orders_repository.dart';
import '../database/pending_orders_repository.dart';
import '../models/order.dart';
import '../models/order_item.dart';
import '../models/product_variant.dart';
import '../services/offline_orders_service.dart';
import 'catalog_api_client.dart';

/// Unified Order Manager - Centralizes all order operations
/// Handles creation, editing, querying, and selection of products with subproducts
class UnifiedOrdersManager {
  final DatabaseHelper _dbHelper;
  late final OrdersRepository _ordersRepo;
  late final PendingOrdersRepository _pendingOrdersRepo;
  final CatalogApiClient _api;
  late final OfflineOrdersService _offlineService;

  // Current order being edited
  Order? _currentOrder;
  List<OrderItem> _currentItems = [];
  final Map<String, List<ProductVariant>> _variantsCache = {};

  UnifiedOrdersManager(
    this._dbHelper, {
    required CatalogApiClient api,
  }) : _api = api {
    _ordersRepo = OrdersRepository(_dbHelper);
    _pendingOrdersRepo = PendingOrdersRepository(_dbHelper);
    _offlineService = OfflineOrdersService(_pendingOrdersRepo, _api);
  }

  // ============= ORDER CREATION & MANAGEMENT =============

  /// Creates a new order with initial details
  Future<Order> createNewOrder({
    required String client,
    required String? whatsapp,
    required String? status,
    String? deliveryDate,
    String? printPriority,
    String? observations,
  }) async {
    final id = 'order_${DateTime.now().microsecondsSinceEpoch}';

    final order = Order(
      id: id,
      client: client,
      whatsapp: whatsapp,
      status: status ?? 'pending',
      deliveryDate: deliveryDate,
      printPriority: printPriority,
      observations: observations,
      orderDate: DateTime.now().toIso8601String(),
      createdAt: DateTime.now().toIso8601String(),
      updatedAt: DateTime.now().toIso8601String(),
    );

    _currentOrder = order;
    _currentItems = [];
    return order;
  }

  /// Loads an existing order for editing
  Future<Order?> loadOrder(String orderId) async {
    _currentOrder = await _ordersRepo.getOrderById(orderId);
    // TODO: Load order items from database
    _currentItems = [];
    return _currentOrder;
  }

  /// Saves the current order and its items
  Future<String> saveCurrentOrder() async {
    if (_currentOrder == null) {
      throw Exception('No order loaded for saving');
    }

    // Save order
    await _ordersRepo.upsertOrder(_currentOrder!.toMap());

    // TODO: Save order items to database

    return _currentOrder!.id;
  }

  // ============= ITEM MANAGEMENT =============

  /// Adds a product to the current order (without variant)
  Future<OrderItem> addProductToOrder({
    required String productId,
    required String productName,
    required int quantity,
    double? unitPrice,
  }) async {
    if (_currentOrder == null) {
      throw Exception('No order loaded');
    }

    final item = OrderItem(
      id: 'item_${DateTime.now().microsecondsSinceEpoch}',
      orderId: _currentOrder!.id,
      productId: productId,
      productName: productName,
      quantity: quantity,
      unitPrice: unitPrice,
      totalPrice: unitPrice != null ? unitPrice * quantity : null,
    );

    _currentItems.add(item);
    return item;
  }

  /// Adds a product with a specific variant/subproduct to the order
  Future<OrderItem> addProductVariantToOrder({
    required String productId,
    required String productName,
    required String variantId,
    required String variantName,
    required int quantity,
    double? unitPrice,
  }) async {
    if (_currentOrder == null) {
      throw Exception('No order loaded');
    }

    final item = OrderItem(
      id: 'item_${DateTime.now().microsecondsSinceEpoch}',
      orderId: _currentOrder!.id,
      productId: productId,
      productName: productName,
      variantId: variantId,
      variantName: variantName,
      quantity: quantity,
      unitPrice: unitPrice,
      totalPrice: unitPrice != null ? unitPrice * quantity : null,
    );

    _currentItems.add(item);
    return item;
  }

  /// Removes an item from the current order
  void removeItemFromOrder(String itemId) {
    _currentItems.removeWhere((item) => item.id == itemId);
  }

  /// Updates an existing order item
  void updateOrderItem(
    String itemId, {
    int? quantity,
    double? unitPrice,
    String? variantId,
    String? variantName,
  }) {
    final index = _currentItems.indexWhere((item) => item.id == itemId);
    if (index == -1) return;

    final current = _currentItems[index];
    final newQuantity = quantity ?? current.quantity;
    final newUnitPrice = unitPrice ?? current.unitPrice;

    _currentItems[index] = current.copyWith(
      quantity: newQuantity,
      unitPrice: newUnitPrice,
      totalPrice: newUnitPrice != null ? newUnitPrice * newQuantity : null,
      variantId: variantId ?? current.variantId,
      variantName: variantName ?? current.variantName,
    );
  }

  // ============= VARIANT/SUBPRODUCT MANAGEMENT =============

  /// Fetches available variants for a product
  Future<List<ProductVariant>> getProductVariants(String productId) async {
    // Check cache first
    if (_variantsCache.containsKey(productId)) {
      return _variantsCache[productId] ?? [];
    }

    try {
      // TODO: Implement API call to fetch variants
      // final variants = await _api!.getProductVariants(productId);
      // _variantsCache[productId] = variants;
      // return variants;
      return [];
    } catch (e) {
      debugPrint('Error fetching variants for product $productId: $e');
      return [];
    }
  }

  /// Gets cached variants without API call
  List<ProductVariant>? getCachedVariants(String productId) {
    return _variantsCache[productId];
  }

  /// Pre-caches variants for multiple products
  Future<void> preloadVariants(List<String> productIds) async {
    for (final productId in productIds) {
      if (!_variantsCache.containsKey(productId)) {
        await getProductVariants(productId);
      }
    }
  }

  // ============= GETTERS =============

  Order? get currentOrder => _currentOrder;
  List<OrderItem> get currentItems => _currentItems;

  double get orderTotal {
    return _currentItems.fold<double>(
      0.0,
      (sum, item) => sum + (item.totalPrice ?? 0.0),
    );
  }

  int get totalQuantity {
    return _currentItems.fold<int>(
      0,
      (sum, item) => sum + item.quantity,
    );
  }

  // ============= OFFLINE SUPPORT =============

  /// Queues a sticker order for later sync
  Future<String> queueStickerOrder({
    required String client,
    required String whatsapp,
    required String observations,
    required String mode,
    required List<String> catalogDesignIds,
    required List<File> images,
  }) async {
    final requestId = OfflineOrdersService.newRequestId();
    await _offlineService.queueStickerOrder(
      requestId: requestId,
      client: client,
      whatsapp: whatsapp,
      observations: observations,
      mode: mode,
      catalogDesignIds: catalogDesignIds,
      images: images,
    );
    return requestId;
  }

  /// Syncs pending orders with the server
  Future<int> syncPendingOrders() async {
    return await _offlineService.sendPending();
  }

  // ============= CACHE MANAGEMENT =============

  void clearVariantsCache() {
    _variantsCache.clear();
  }

  void clearCurrentOrder() {
    _currentOrder = null;
    _currentItems = [];
  }
}
