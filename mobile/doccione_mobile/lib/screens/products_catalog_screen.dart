import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import '../models/catalog_design.dart';
import '../models/pos_cart.dart';
import '../services/catalog_api_client.dart';
import '../services/bundled_product_catalog.dart';
import '../database/database_helper.dart';
import '../database/offline_catalog_repository.dart';
import '../database/pending_orders_repository.dart';
import '../services/offline_orders_service.dart';
import '../services/offline_pricing_service.dart';

class ProductsCatalogScreen extends StatefulWidget {
  final String baseUrl;
  final String sessionToken;
  const ProductsCatalogScreen(
      {super.key, required this.baseUrl, required this.sessionToken});
  @override
  State<ProductsCatalogScreen> createState() => _ProductsCatalogScreenState();
}

class _ProductsCatalogScreenState extends State<ProductsCatalogScreen> {
  late final CatalogApiClient _api;
  late final OfflineCatalogRepository _offlineCatalog;
  List<StudioProduct> _products = [];
  bool _loading = true;
  String? _error;
  final PosCart _cart = posCart;
  @override
  void initState() {
    super.initState();
    _api = CatalogApiClient(
        baseUrl: widget.baseUrl, authToken: widget.sessionToken);
    _offlineCatalog = OfflineCatalogRepository(DatabaseHelper());
    _load();
  }

  @override
  void dispose() {
    _api.close();
    super.dispose();
  }

  Future<void> _load({bool refresh = false}) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    // Primero se muestra una copia local para que el flujo funcione offline.
    var products = await _offlineCatalog.getProducts();
    if (products.isEmpty) {
      products = await BundledProductCatalog.load();
      if (products.isNotEmpty) await _offlineCatalog.saveProducts(products);
    }
    if (mounted) {
      setState(() {
        _products = products;
        _error = products.isEmpty
            ? 'No hay catálogo disponible sin conexión.'
            : null;
        _loading = false;
      });
    }

    // Studio es la autoridad para precios y variantes. Un error de red deja
    // intacta la copia local ya visible.
    try {
      final remote = await _api.getProducts();
      if (remote.isEmpty) return;
      await _offlineCatalog.saveProducts(remote);
      unawaited(_cacheProductPreviews(remote));
      if (mounted) {
        setState(() {
          _products = remote;
          _error = null;
        });
      }
    } catch (_) {
      // La caché ya se mostró; no convertir el modo offline en un error fatal.
    }
  }

  Future<void> _cacheProductPreviews(List<StudioProduct> products) async {
    for (final product in products) {
      if (product.imagePath.isEmpty) continue;
      final previewUrl = product.imagePath.startsWith('http')
          ? product.imagePath
          : '${widget.baseUrl}${product.imagePath}';
      try {
        final bytes = await _api.download(previewUrl);
        await _offlineCatalog.cacheProductPreview(product, bytes);
        final cachedPath =
            await _offlineCatalog.productPreviewPath(product.code);
        if (!mounted || cachedPath == null) continue;
        setState(() {
          final index =
              _products.indexWhere((item) => item.code == product.code);
          if (index != -1) {
            _products[index] = StudioProduct(
              id: product.id,
              code: product.code,
              name: product.name,
              description: product.description,
              category: product.category,
              imagePath: product.imagePath,
              basePrice: product.basePrice,
              priceRules: product.priceRules,
              materials: product.materials,
              minPrice: product.minPrice,
              maxPrice: product.maxPrice,
              options: product.options,
              cachedPreviewPath: cachedPath,
            );
          }
        });
      } catch (_) {
        // ignore
      }
    }
  }

  ImageProvider<Object>? _productImageProvider(StudioProduct product) {
    if (product.cachedPreviewPath != null &&
        File(product.cachedPreviewPath!).existsSync()) {
      return FileImage(File(product.cachedPreviewPath!));
    }
    if (product.imagePath.isEmpty) {
      return null;
    }
    if (product.imagePath.startsWith('assets/')) {
      return AssetImage(product.imagePath);
    }
    return null;
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Productos de Studio'), actions: [
          Badge(
              isLabelVisible: !_cart.isEmpty,
              label: Text('${_cart.lineCount}'),
              child: IconButton(
                  onPressed: _cart.productLines.isEmpty ? null : _checkout,
                  icon: const Icon(Icons.shopping_cart_outlined)))
        ]),
        body: _loading
            ? const Center(child: CircularProgressIndicator())
            : _error != null
                ? Center(
                    child: FilledButton(
                        onPressed: _load, child: const Text('Reintentar')))
                : ListView.separated(
                    padding: const EdgeInsets.all(16),
                    itemCount: _products.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 12),
                    itemBuilder: (_, index) {
                      final product = _products[index];
                      return Card(
                        clipBehavior: Clip.antiAlias,
                        child: InkWell(
                          onTap: (product.priceRules > 0 ||
                                  product.basePrice > 0 ||
                                  product.minPrice != null ||
                                  product.maxPrice != null)
                              ? () => _showQuantityDialog(product)
                              : null,
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              SizedBox(
                                height: 120,
                                width: double.infinity,
                                child: _buildProductImage(product),
                              ),
                              Padding(
                                padding: const EdgeInsets.all(12),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    if (product.category.isNotEmpty)
                                      Text(
                                        product.category.toUpperCase(),
                                        style: Theme.of(context)
                                            .textTheme
                                            .labelSmall
                                            ?.copyWith(
                                              color: Theme.of(context)
                                                  .colorScheme
                                                  .primary,
                                              fontWeight: FontWeight.bold,
                                            ),
                                      ),
                                    const SizedBox(height: 4),
                                    Text(
                                      product.name,
                                      style: Theme.of(context)
                                          .textTheme
                                          .titleMedium
                                          ?.copyWith(
                                            fontWeight: FontWeight.bold,
                                          ),
                                    ),
                                    if (product.description.isNotEmpty) ...[
                                      const SizedBox(height: 4),
                                      Text(
                                        product.description,
                                        style: Theme.of(context)
                                            .textTheme
                                            .bodySmall
                                            ?.copyWith(
                                              color: Colors.grey[600],
                                            ),
                                        maxLines: 2,
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                    ],
                                    const SizedBox(height: 8),
                                    Row(
                                      children: [
                                        Text(
                                          product.displayPrice,
                                          style: Theme.of(context)
                                              .textTheme
                                              .titleMedium
                                              ?.copyWith(
                                                color: (product.priceRules >
                                                            0 ||
                                                        product.basePrice > 0 ||
                                                        product.minPrice !=
                                                            null ||
                                                        product.maxPrice !=
                                                            null)
                                                    ? Theme.of(context)
                                                        .colorScheme
                                                        .primary
                                                    : Colors.grey,
                                                fontWeight: FontWeight.bold,
                                              ),
                                        ),
                                        const Spacer(),
                                        if (product.priceRules > 0)
                                          const Icon(
                                              Icons.add_shopping_cart_outlined)
                                        else
                                          const Icon(
                                              Icons.warning_amber_rounded,
                                              color: Colors.orange),
                                      ],
                                    ),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
        floatingActionButton: _cart.productLines.isEmpty
            ? null
            : FloatingActionButton.extended(
                onPressed: _checkout,
                icon: const Icon(Icons.shopping_cart_checkout),
                label: Text('Carrito (${_cart.lineCount})')),
      );

  Future<void> _checkout() async {
    // El presupuesto se forma con el catálogo persistido, sin depender de red.
    final total = _cartTotal();
    if (!mounted) return;
    final result = await showDialog<_ProductCheckoutResult>(
        context: context,
        builder: (_) => _ProductCheckoutDialog(
            api: _api,
            cart: _cart,
            products: _products,
            initialTotal: total,
            offlineOrders: OfflineOrdersService(
              PendingOrdersRepository(DatabaseHelper()),
              _api,
            )));
    if (!mounted) return;
    if (result == _ProductCheckoutResult.submitted ||
        result == _ProductCheckoutResult.queued) {
      setState(_cart.clearProducts);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(result == _ProductCheckoutResult.queued
              ? 'Sin conexión: la venta quedó guardada para sincronizar.'
              : 'Venta creada en Pedidos')));
    } else {
      setState(() {});
    }
  }

  double _cartTotal() => _cart.productLines.values
      .fold<double>(0, (total, line) => total + line.unitPrice * line.quantity);

  Widget _buildProductImage(StudioProduct product) {
    final provider = _productImageProvider(product);
    if (provider != null) {
      return Image(
        image: provider,
        fit: BoxFit.cover,
        errorBuilder: (_, __, ___) => const Center(
          child: Icon(Icons.image_not_supported, size: 40),
        ),
      );
    }
    return const Center(
      child: Icon(Icons.inventory_2_outlined, size: 40),
    );
  }

  Future<void> _showQuantityDialog(StudioProduct product) async {
    final quantityController = TextEditingController(text: '1');
    var quantity = 1;
    StudioProductOption? selectedOption;

    await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(product.name),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (_productImageProvider(product) != null)
              SizedBox(
                height: 120,
                child: Image(
                  image: _productImageProvider(product)!,
                  fit: BoxFit.cover,
                  errorBuilder: (_, __, ___) => const Center(
                    child: Icon(Icons.image_not_supported, size: 40),
                  ),
                ),
              ),
            const SizedBox(height: 12),
            Text(product.description.isEmpty
                ? product.category
                : product.description),
            const SizedBox(height: 12),
            if (product.options.isNotEmpty) ...[
              DropdownButtonFormField<StudioProductOption?>(
                initialValue: selectedOption,
                decoration:
                    const InputDecoration(labelText: 'Subproducto / variante'),
                items: [
                  const DropdownMenuItem<StudioProductOption?>(
                    value: null,
                    child: Text('Producto base'),
                  ),
                  ...product.options
                      .map((option) => DropdownMenuItem<StudioProductOption?>(
                            value: option,
                            child: Text(option.variantName.isNotEmpty
                                ? option.variantName
                                : [option.material, option.size]
                                    .where((value) => value.isNotEmpty)
                                    .join(' · ')),
                          )),
                ],
                onChanged: (option) => selectedOption = option,
              ),
              const SizedBox(height: 12),
            ],
            TextField(
              controller: quantityController,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: 'Cantidad'),
              onChanged: (value) {
                quantity = int.tryParse(value) ?? 1;
              },
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () {
              Navigator.pop(dialogContext);
              if (quantity > 0) {
                setState(() {
                  _cart.addProductLine(PosProductLine(
                    productCode: product.code,
                    productName: product.name,
                    variantCode: selectedOption?.variantCode,
                    variantName: selectedOption?.variantName ?? '',
                    material: selectedOption?.material ?? '',
                    size: selectedOption?.size ?? '',
                    unitPrice: selectedOption?.price ??
                        OfflinePricingService.unitPrice(product),
                    quantity: quantity,
                  ));
                });
              }
            },
            child: const Text('Agregar'),
          ),
        ],
      ),
    );
  }
}

enum _ProductCheckoutResult { submitted, queued }

class _ProductCheckoutDialog extends StatefulWidget {
  final CatalogApiClient api;
  final PosCart cart;
  final List<StudioProduct> products;
  final double initialTotal;
  final OfflineOrdersService offlineOrders;

  const _ProductCheckoutDialog(
      {required this.api,
      required this.cart,
      required this.products,
      required this.initialTotal,
      required this.offlineOrders});

  @override
  State<_ProductCheckoutDialog> createState() => _ProductCheckoutDialogState();
}

class _ProductCheckoutDialogState extends State<_ProductCheckoutDialog> {
  final _client = TextEditingController();
  final _whatsapp = TextEditingController();
  final _notes = TextEditingController();
  final _targetOrder = TextEditingController();
  double? _total;
  bool _quoting = false;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _total = widget.initialTotal;
  }

  @override
  void dispose() {
    _client.dispose();
    _whatsapp.dispose();
    _notes.dispose();
    _targetOrder.dispose();
    super.dispose();
  }

  double _totalForCart() => widget.cart.productLines.values
      .fold<double>(0, (total, line) => total + line.unitPrice * line.quantity);

  Future<void> _removeProduct(String productLineId) async {
    widget.cart.removeProductLine(productLineId);
    if (widget.cart.productLines.isEmpty) {
      if (mounted) Navigator.pop(context);
      return;
    }
    await _refreshTotal();
  }

  Future<void> _refreshTotal() async {
    setState(() {
      _quoting = true;
      _total = null;
      _error = null;
    });
    // Usa el último catálogo sincronizado; funciona incluso en modo avión.
    final total = _totalForCart();
    if (!mounted) return;
    setState(() {
      _total = total;
      _quoting = false;
    });
  }

  Future<void> _submit() async {
    if (_client.text.trim().isEmpty) {
      setState(() => _error = 'Indicá el nombre del cliente.');
      return;
    }
    if (widget.cart.productLines.isEmpty || _total == null) return;
    final targetOrderId = int.tryParse(_targetOrder.text.trim());
    if (_targetOrder.text.trim().isNotEmpty && targetOrderId == null) {
      setState(() => _error = 'El nÃºmero de pedido debe ser vÃ¡lido.');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await widget.api.createProductOrderLines(
          client: _client.text.trim(),
          whatsapp: _whatsapp.text.trim(),
          observations: _notes.text.trim(),
          items: widget.cart.productLines.values.toList(),
          targetOrderId: targetOrderId);
      if (mounted) Navigator.pop(context, _ProductCheckoutResult.submitted);
    } catch (error) {
      await widget.offlineOrders.queueProductOrderLines(
        requestId: OfflineOrdersService.newRequestId(),
        client: _client.text.trim(),
        whatsapp: _whatsapp.text.trim(),
        observations: _notes.text.trim(),
        items: widget.cart.productLines.values.toList(),
        targetOrderId: targetOrderId,
      );
      if (mounted) Navigator.pop(context, _ProductCheckoutResult.queued);
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('Confirmar venta'),
        content: SizedBox(
          width: double.maxFinite,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                ...widget.cart.productLines.values.map((line) => ListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text(line.productName),
                      subtitle: Text([
                        if (line.label.isNotEmpty) line.label,
                        'Cantidad: ${line.quantity}',
                      ].join(' · ')),
                      trailing: IconButton(
                        onPressed:
                            _saving ? null : () => _removeProduct(line.id),
                        icon: const Icon(Icons.delete_outline),
                        tooltip: 'Quitar producto',
                      ),
                    )),
                if (_quoting)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 12),
                    child: Center(child: CircularProgressIndicator()),
                  )
                else if (_total != null)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 10),
                    child: Text('TOTAL: \$${_total!.toStringAsFixed(2)}',
                        textAlign: TextAlign.center,
                        style: Theme.of(context)
                            .textTheme
                            .titleMedium
                            ?.copyWith(fontWeight: FontWeight.w800)),
                  ),
                TextField(
                    controller: _client,
                    enabled: !_saving,
                    decoration: const InputDecoration(labelText: 'Cliente *')),
                TextField(
                    controller: _whatsapp,
                    enabled: !_saving,
                    keyboardType: TextInputType.phone,
                    decoration: const InputDecoration(labelText: 'WhatsApp')),
                TextField(
                    controller: _notes,
                    enabled: !_saving,
                    maxLines: 2,
                    decoration:
                        const InputDecoration(labelText: 'Observaciones')),
                TextField(
                    controller: _targetOrder,
                    enabled: !_saving,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'Vincular al pedido # (opcional)',
                      helperText:
                          'Agrega estos productos a un pedido ya creado',
                    )),
                if (_error != null) ...[
                  const SizedBox(height: 10),
                  Text(_error!,
                      style: TextStyle(
                          color: Theme.of(context).colorScheme.error)),
                  if (_total == null)
                    Align(
                      alignment: Alignment.centerLeft,
                      child: TextButton.icon(
                        onPressed: _quoting ? null : _refreshTotal,
                        icon: const Icon(Icons.refresh),
                        label: const Text('Recalcular total'),
                      ),
                    ),
                ],
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
              onPressed: _saving ? null : () => Navigator.pop(context),
              child: const Text('Cancelar')),
          FilledButton(
              onPressed: _saving || _quoting || _total == null ? null : _submit,
              child: _saving
                  ? const SizedBox.square(
                      dimension: 18,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : const Text('Vender'))
        ],
      );
}
