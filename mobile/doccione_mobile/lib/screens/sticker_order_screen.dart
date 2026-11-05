import 'dart:async';
import 'dart:io';
import 'dart:math' as math;

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';
import 'package:path/path.dart' as path;
import 'package:path_provider/path_provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/catalog_design.dart';
import '../models/mobile_runtime_config.dart';
import '../models/mockup_reference.dart';
import '../models/order_flow_selection.dart';
import '../services/catalog_api_client.dart';
import '../services/bundled_sticker_catalog.dart';
import '../services/bundled_product_catalog.dart';
import '../services/offline_orders_service.dart';
import '../database/database_helper.dart';
import '../database/offline_catalog_repository.dart';
import '../database/pending_orders_repository.dart';
import '../database/clients_repository.dart';
import '../models/client.dart';
import '../theme/doccione_palette.dart';
import '../widgets/real_size_preview.dart';
import '../widgets/sticker_catalog_tile.dart';
import '../widgets/two_row_catalog_grid.dart';
import '../widgets/uniform_image_preview.dart';

class StickerOrderScreen extends StatefulWidget {
  final String baseUrl;
  final String sessionToken;
  final bool stickerCreatorOnly;
  final bool showCatalogDesigns;
  final String? initialClient;
  final String? initialWhatsapp;
  final String? initialNotes;

  const StickerOrderScreen({
    super.key,
    required this.baseUrl,
    required this.sessionToken,
    this.stickerCreatorOnly = false,
    this.showCatalogDesigns = false,
    this.initialClient,
    this.initialWhatsapp,
    this.initialNotes,
  });

  @override
  State<StickerOrderScreen> createState() => _StickerOrderScreenState();
}

class _StickerOrderScreenState extends State<StickerOrderScreen> {
  late final CatalogApiClient _api;
  late final OfflineCatalogRepository _offlineCatalog;
  late final ClientsRepository _clientsRepository;
  final _client = TextEditingController();
  final _whatsapp = TextEditingController();
  final _notes = TextEditingController();
  final _picker = ImagePicker();
  final List<File> _images = [];
  final List<MockupReference> _mockups = [];
  final List<CatalogDesign> _catalog = [];
  final Set<String> _selectedCatalog = {};
  final List<StudioProduct> _products = [];
  final List<StudioOrderItemDraft> _draftItems = [];
  Timer? _quoteDebounce;
  late String _mode;
  bool _loadingCatalog = false;
  bool _loadingProducts = false;
  bool _saving = false;
  bool _quoting = false;
  StickerQuote? _quote;
  double? _productQuoteTotal;
  String? _quoteError;
  int _quoteRevision = 0;

  int get _designCount => _images.length + _selectedCatalog.length;

  bool get _hasProductDrafts => _draftItems.isNotEmpty;
  bool get _hasStickerItems => _designCount > 0;
  bool get _orderIsEmpty => !_hasProductDrafts && !_hasStickerItems;
  bool get _canAddProducts => !_hasStickerItems;
  bool get _canAddStickerItems => !_hasProductDrafts;
  double get _productDraftTotal => _draftItems.fold<double>(
      0, (sum, item) => sum + item.unitPrice * item.quantity);
  double? get _shareTotal =>
      _productQuoteTotal ?? (_quote?.matched == true ? _quote!.total : null);

  void _clearCurrentOrder() {
    _images.clear();
    _mockups.clear();
    _selectedCatalog.clear();
    _draftItems.clear();
    _client.clear();
    _whatsapp.clear();
    _notes.clear();
    _quote = null;
    _productQuoteTotal = null;
    _quoteError = null;
    _quoteDebounce?.cancel();
    _quoteRevision++;
  }

  Future<void> _chooseClient() async {
    final clients = await _clientsRepository.getAllClients();
    if (!mounted) return;
    final selected = await showModalBottomSheet<Client>(
      context: context,
      builder: (context) => SafeArea(
        child: ListView.builder(
          itemCount: clients.length,
          itemBuilder: (_, index) {
            final client = clients[index];
            return ListTile(
              leading: const Icon(Icons.person_outline),
              title: Text(client.name ?? 'Sin nombre'),
              subtitle: Text(client.phone ?? ''),
              onTap: () => Navigator.pop(context, client),
            );
          },
        ),
      ),
    );
    if (selected == null || !mounted) return;
    setState(() {
      _client.text = selected.name ?? '';
      _whatsapp.text = selected.phone ?? '';
    });
  }

  Future<void> _shareQuote() async {
    final total = _shareTotal;
    if (total == null) return;
    final detail = _hasProductDrafts
        ? _draftItems
            .map((item) => '${item.product.name} x${item.quantity}')
            .join(', ')
        : 'Stickers: $_designCount diseño${_designCount == 1 ? '' : 's'}';
    final message =
        'Presupuesto Doccione\n$detail\nTotal: \$${total.toStringAsFixed(2)}';
    final phone = _whatsapp.text.replaceAll(RegExp(r'[^0-9]'), '');
    final uri = Uri.parse(phone.isEmpty
        ? 'https://wa.me/?text=${Uri.encodeComponent(message)}'
        : 'https://wa.me/$phone?text=${Uri.encodeComponent(message)}');
    if (!await launchUrl(uri, mode: LaunchMode.externalApplication) &&
        mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('No se pudo abrir WhatsApp.')),
      );
    }
  }

  Future<void> _cancelOrder() async {
    if (_orderIsEmpty || _saving) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        insetPadding: const EdgeInsets.symmetric(horizontal: 24, vertical: 20),
        title: const Text('Cancelar pedido'),
        content: const Text(
            '¿Querés cancelar la creación del pedido y borrar los datos actuales?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('No'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Sí, cancelar'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      _clearCurrentOrder();
    });
  }

  @override
  void initState() {
    super.initState();
    _client.text = widget.initialClient ?? '';
    _whatsapp.text = widget.initialWhatsapp ?? '';
    _notes.text = widget.initialNotes ?? '';
    _mode = MobileRuntimeConfigStore.current.stickerModes.first;
    _api = CatalogApiClient(
      baseUrl: widget.baseUrl,
      authToken: widget.sessionToken,
    );
    _offlineCatalog = OfflineCatalogRepository(DatabaseHelper());
    _clientsRepository = ClientsRepository(DatabaseHelper());
    if (widget.showCatalogDesigns) _loadCatalog();
    if (!widget.stickerCreatorOnly) _loadProducts();
  }

  @override
  void dispose() {
    _quoteDebounce?.cancel();
    _client.dispose();
    _whatsapp.dispose();
    _notes.dispose();
    _api.close();
    super.dispose();
  }

  Future<void> _loadCatalog() async {
    // Diseños e imágenes viajan dentro del APK, sin caché ni descarga remota.
    // El banco incluido es la fuente de carga inmediata: cada miniatura está
    // dentro del APK y no queda esperando una descarga anterior.
    final bundled = await BundledStickerCatalog.load();
    if (!mounted) return;
    setState(() {
      _catalog
        ..clear()
        ..addAll(bundled);
      _loadingCatalog = false;
    });
    unawaited(_applyDownloadedDesignUpdates());
  }

  Future<void> _applyDownloadedDesignUpdates() async {
    final stored = await _offlineCatalog.getDesigns();
    final downloaded = {
      for (final design in stored)
        if (design.cachedPreviewPath != null &&
            File(design.cachedPreviewPath!).existsSync())
          design.id: design,
    };
    if (downloaded.isEmpty || !mounted) return;
    setState(() {
      for (var index = 0; index < _catalog.length; index++) {
        final replacement = downloaded[_catalog[index].id];
        if (replacement != null) _catalog[index] = replacement;
      }
      final ids = _catalog.map((design) => design.id).toSet();
      _catalog.addAll(
          downloaded.values.where((design) => !ids.contains(design.id)));
    });
  }

  Future<void> _refreshCatalogFromNetwork() async {
    try {
      final items = await _api.getDesigns();
      await _offlineCatalog.saveDesigns(items);
      unawaited(_cacheDesignPreviews(items));
      if (!mounted) return;
      setState(() {
        _catalog
          ..clear()
          ..addAll(items);
      });
    } catch (_) {
      // Keep bundled catalog if network refresh fails.
    }
  }

  /// Descarga novedades sólo cuando la persona lo solicita. La entrada normal
  /// a la pantalla usa exclusivamente la copia ya guardada en el teléfono.
  // Conservado para la acción explícita de actualización del catálogo.
  // ignore: unused_element
  Future<void> _downloadDesignUpdates() async {
    setState(() => _loadingCatalog = true);
    await _refreshCatalogFromNetwork();
    if (!mounted) return;
    setState(() => _loadingCatalog = false);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Catálogo de diseños actualizado.')),
    );
  }

  Future<void> _cacheDesignPreviews(List<CatalogDesign> designs) async {
    for (final design in designs) {
      if (design.previewUrl.isEmpty) continue;
      final previewUrl = design.previewUrl.startsWith('http')
          ? design.previewUrl
          : '${widget.baseUrl}${design.previewUrl}';
      try {
        final bytes = await _api.download(previewUrl);
        await _offlineCatalog.cachePreview(design, bytes);
        final cachedPath = await _offlineCatalog.previewPath(design.id);
        if (!mounted || cachedPath == null) continue;
        setState(() {
          final index = _catalog.indexWhere((item) => item.id == design.id);
          if (index != -1) {
            _catalog[index] = CatalogDesign(
              id: design.id,
              name: design.name,
              category: design.category,
              caption: design.caption,
              tags: design.tags,
              previewUrl: design.previewUrl,
              visibleWidth: design.visibleWidth,
              visibleHeight: design.visibleHeight,
              cachedPreviewPath: cachedPath,
              assetPreviewPath: design.assetPreviewPath,
              modifiedMs: design.modifiedMs,
            );
          }
        });
      } catch (_) {
        // Ignore preview download failures.
      }
    }
  }

  Future<void> _loadProducts() async {
    setState(() {
      _loadingProducts = true;
      _quoteError = null;
    });
    final offlineProducts = await _offlineCatalog.getProducts();
    if (offlineProducts.isNotEmpty) {
      if (mounted) {
        setState(() {
          _products
            ..clear()
            ..addAll(offlineProducts);
          _loadingProducts = false;
        });
      }
      unawaited(_refreshProductsFromNetwork());
      return;
    }

    final legacyBundledProducts = await BundledProductCatalog.load();
    if (legacyBundledProducts.isNotEmpty) {
      await _offlineCatalog.saveProducts(legacyBundledProducts);
      if (mounted) {
        setState(() {
          _products
            ..clear()
            ..addAll(legacyBundledProducts);
          _loadingProducts = false;
        });
      }
      unawaited(_refreshProductsFromNetwork());
      return;
    }

    try {
      final products = await _api.getProducts();
      await _offlineCatalog.saveProducts(products);
      if (mounted) {
        setState(() {
          _products
            ..clear()
            ..addAll(products);
          _loadingProducts = false;
        });
      }
      unawaited(_cacheProductPreviews(products));
    } catch (_) {
      final cachedProducts = await _offlineCatalog.getProducts();
      if (mounted) {
        setState(() {
          _products
            ..clear()
            ..addAll(cachedProducts);
          _loadingProducts = false;
        });
      }
    }
  }

  Future<void> _refreshProductsFromNetwork() async {
    try {
      final products = await _api.getProducts();
      await _offlineCatalog.saveProducts(products);
      if (!mounted) return;
      setState(() {
        _products
          ..clear()
          ..addAll(products);
      });
      unawaited(_cacheProductPreviews(products));
    } catch (_) {
      // Keep existing products if refresh fails.
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
        // Ignore preview download failures.
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
    return NetworkImage(
      product.imagePath.startsWith('http')
          ? product.imagePath
          : '${widget.baseUrl}${product.imagePath}',
      headers: _api.headers,
    );
  }

  void _scheduleQuote() {
    _quoteDebounce?.cancel();
    final revision = ++_quoteRevision;
    if (_orderIsEmpty) {
      setState(() {
        _quote = null;
        _productQuoteTotal = null;
        _quoteError = null;
        _quoting = false;
      });
      return;
    }
    _quoteDebounce =
        Timer(const Duration(milliseconds: 250), () => _refreshQuote(revision));
  }

  Future<void> _refreshQuote(int revision) async {
    if (_orderIsEmpty) return;
    setState(() {
      _quoting = true;
      _quoteError = null;
    });

    if (_hasProductDrafts) {
      final total = _productDraftTotal;
      if (!mounted || revision != _quoteRevision) return;
      setState(() {
        _quote = null;
        _productQuoteTotal = total;
        _quoting = false;
      });
      return;
    }

    final mode = _mode;
    final designCount = _designCount;
    if (designCount == 0) return;
    try {
      final quote =
          await _api.quoteStickerOrder(mode: mode, designCount: designCount);
      if (!mounted || revision != _quoteRevision) return;
      setState(() {
        _quote = quote;
        _productQuoteTotal = null;
        _quoting = false;
      });
    } catch (error) {
      if (!mounted || revision != _quoteRevision) return;
      setState(() {
        _quoting = false;
        _quoteError = error.toString();
      });
    }
  }

  Future<void> _addImages() async {
    if (!_canAddStickerItems) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text(
              'Ya hay productos en el pedido. Cancelalo para agregar diseños.'),
        ));
      }
      return;
    }
    final picked = await _picker.pickMultiImage(
      imageQuality: 80,
      maxWidth: 2048,
      maxHeight: 2048,
    );
    const maxImages = 30;
    const maxBytes = 45 * 1024 * 1024;
    final remainingSlots = maxImages - _images.length;
    final accepted = <File>[];
    var totalBytes = await Future.wait(_images.map((image) => image.length()))
        .then((sizes) => sizes.fold<int>(0, (sum, size) => sum + size));
    for (final image in picked.take(remainingSlots)) {
      final file = File(image.path);
      final size = await file.length();
      if (totalBytes + size > maxBytes) break;
      accepted.add(file);
      totalBytes += size;
    }
    if (accepted.isNotEmpty && mounted) {
      setState(() {
        _images.addAll(accepted);
        _quote = null;
      });
      _scheduleQuote();
    }
    if (mounted && accepted.length != picked.length) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content:
            Text('Se limitaron las imágenes a 30 archivos y 45 MB por pedido.'),
      ));
    }
  }

  Future<void> _selectCatalogDesigns() async {
    if (!_canAddStickerItems) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text(
              'Ya hay productos en el pedido. Cancelalo para agregar diseños.'),
        ));
      }
      return;
    }
    if (_loadingCatalog) return;
    final selected = await showModalBottomSheet<Set<String>>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _StickerCatalogPicker(
        api: _api,
        initialCatalog: _catalog,
        initiallySelected: _selectedCatalog,
        onMockupCaptured: _attachCapturedMockup,
      ),
    );
    if (selected == null || !mounted) return;
    setState(() {
      _selectedCatalog
        ..clear()
        ..addAll(selected);
      _quote = null;
    });
    _scheduleQuote();
  }

  void _attachCapturedMockup(MockupReference mockup) {
    if (!_canAddStickerItems || !mounted) return;
    setState(() => _mockups.add(mockup));
  }

  Future<void> _openMockup(int index) async {
    final mockup = _mockups[index];
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(
            '${mockup.surface.label} · ${mockup.sizeCm.toStringAsFixed(0)} cm'),
        contentPadding: const EdgeInsets.fromLTRB(20, 12, 20, 8),
        content: ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 420),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Flexible(child: Image.file(mockup.file, fit: BoxFit.contain)),
            const SizedBox(height: 10),
            Align(
              alignment: Alignment.centerLeft,
              child: Text(
                  '${mockup.material} · ${mockup.approval.label}${mockup.comment.isEmpty ? '' : '\n${mockup.comment}'}'),
            ),
          ]),
        ),
        actions: [
          TextButton.icon(
            onPressed: () async {
              try {
                await const MethodChannel('com.doccione.mobile/share')
                    .invokeMethod<void>(
                        'shareImage', {'path': mockup.file.path});
              } on PlatformException {
                if (mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                        content: Text('No se pudo abrir el envío de la foto.')),
                  );
                }
              }
            },
            icon: const Icon(Icons.share_outlined),
            label: const Text('Enviar'),
          ),
          TextButton.icon(
            onPressed: () async {
              final updated = await _editMockupDetails(mockup);
              if (updated == null || !mounted) return;
              setState(() => _mockups[index] = updated);
              if (dialogContext.mounted) Navigator.pop(dialogContext);
            },
            icon: const Icon(Icons.edit_outlined),
            label: const Text('Editar'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('Cerrar'),
          ),
        ],
      ),
    );
  }

  Future<MockupReference?> _editMockupDetails(MockupReference mockup) async {
    var surface = mockup.surface;
    var approval = mockup.approval;
    var sizeCm = mockup.sizeCm;
    final material = TextEditingController(text: mockup.material);
    final comment = TextEditingController(text: mockup.comment);
    final result = await showDialog<MockupReference>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Datos del mockup'),
          content: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              DropdownButtonFormField<MockupSurface>(
                initialValue: surface,
                decoration: const InputDecoration(labelText: 'Superficie'),
                items: MockupSurface.values
                    .map((value) => DropdownMenuItem(
                          value: value,
                          child: Text(value.label),
                        ))
                    .toList(),
                onChanged: (value) {
                  if (value != null) setDialogState(() => surface = value);
                },
              ),
              const SizedBox(height: 10),
              TextField(
                controller: material,
                decoration: const InputDecoration(
                  labelText: 'Material',
                  hintText: 'Vinilo, transparente, holográfico…',
                ),
              ),
              const SizedBox(height: 14),
              Align(
                alignment: Alignment.centerLeft,
                child: Text('Medida: ${sizeCm.toStringAsFixed(0)} cm'),
              ),
              Slider(
                value: sizeCm.clamp(3, 29),
                min: 3,
                max: 29,
                divisions: 26,
                label: '${sizeCm.toStringAsFixed(0)} cm',
                onChanged: (value) => setDialogState(() => sizeCm = value),
              ),
              DropdownButtonFormField<MockupApproval>(
                initialValue: approval,
                decoration: const InputDecoration(labelText: 'Aprobación'),
                items: MockupApproval.values
                    .map((value) => DropdownMenuItem(
                          value: value,
                          child: Text(value.label),
                        ))
                    .toList(),
                onChanged: (value) {
                  if (value != null) setDialogState(() => approval = value);
                },
              ),
              const SizedBox(height: 10),
              TextField(
                controller: comment,
                maxLines: 3,
                decoration: const InputDecoration(labelText: 'Comentario'),
              ),
            ]),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('Cancelar'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(
                dialogContext,
                mockup.copyWith(
                  surface: surface,
                  material: material.text.trim().isEmpty
                      ? 'Sin especificar'
                      : material.text.trim(),
                  comment: comment.text.trim(),
                  approval: approval,
                  sizeCm: sizeCm,
                ),
              ),
              child: const Text('Guardar'),
            ),
          ],
        ),
      ),
    );
    material.dispose();
    comment.dispose();
    return result;
  }

  Map<String, int> get _productDraftQuantities {
    final items = <String, int>{};
    for (final draft in _draftItems) {
      items[draft.product.code] =
          (items[draft.product.code] ?? 0) + draft.quantity;
    }
    return items;
  }

  Future<void> _submit() async {
    if (_client.text.trim().isEmpty ||
        (!_hasStickerItems && !_hasProductDrafts)) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content:
            Text('Indicá el cliente y agregá imágenes, diseños o productos.'),
      ));
      return;
    }
    if (_hasStickerItems && _hasProductDrafts) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text(
          'No se pueden combinar productos y pedidos de stickers en un mismo envío. '
          'Separá los ítems en pedidos distintos.',
        ),
      ));
      return;
    }

    setState(() => _saving = true);
    final requestId = OfflineOrdersService.newRequestId();
    try {
      if (_hasProductDrafts) {
        await _api.createProductOrder(
          client: _client.text.trim(),
          whatsapp: _whatsapp.text.trim(),
          observations: _notes.text.trim(),
          items: _productDraftQuantities,
        );
        if (mounted) {
          setState(() {
            _clearCurrentOrder();
          });
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Venta creada en Pedidos')),
          );
        }
      } else {
        final id = await _api.createStickerOrder(
          clientRequestId: requestId,
          client: _client.text.trim(),
          whatsapp: _whatsapp.text.trim(),
          observations: _notes.text.trim(),
          mode: _mode,
          catalogDesignIds: _selectedCatalog.toList(),
          images: _images,
          referenceImages: _mockups,
        );
        if (mounted) {
          setState(() {
            _clearCurrentOrder();
          });
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Pedido #$id enviado a Studio')),
          );
        }
      }
    } catch (_) {
      if (_hasProductDrafts) {
        await OfflineOrdersService(
          PendingOrdersRepository(DatabaseHelper()),
          _api,
        ).queueProductOrder(
          requestId: requestId,
          client: _client.text.trim(),
          whatsapp: _whatsapp.text.trim(),
          observations: _notes.text.trim(),
          items: _productDraftQuantities,
        );
      } else {
        await OfflineOrdersService(
          PendingOrdersRepository(DatabaseHelper()),
          _api,
        ).queueStickerOrder(
          requestId: requestId,
          client: _client.text.trim(),
          whatsapp: _whatsapp.text.trim(),
          observations: _notes.text.trim(),
          mode: _mode,
          catalogDesignIds: _selectedCatalog.toList(),
          images: _images,
          referenceImages: _mockups,
        );
      }
      if (mounted) {
        setState(() {
          _clearCurrentOrder();
        });
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text(
                  'Sin conexión: el pedido quedó guardado y se enviará al sincronizar.')),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _addProductDraft(
      StudioProduct product, StudioProductOption? option,
      {required int quantity,
      required double unitPrice,
      int? editingIndex}) async {
    setState(() {
      final draft = StudioOrderItemDraft(
        product: product,
        option: option,
        quantity: quantity,
        unitPrice: unitPrice,
      );
      if (editingIndex != null &&
          editingIndex >= 0 &&
          editingIndex < _draftItems.length) {
        _draftItems[editingIndex] = draft;
      } else {
        _draftItems.add(draft);
      }
    });
    _scheduleQuote();
  }

  Future<void> _onProductTap(StudioProduct product) async {
    if (!_canAddProducts) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text(
            'Ya hay un pedido de diseños activo. Cancelalo para agregar productos.'),
      ));
      return;
    }
    if (product.options.isEmpty) {
      await _showQuantityEditor(product, null);
      return;
    }

    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      'Elegí un subproducto',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                  ),
                  IconButton(
                    onPressed: () => Navigator.pop(sheetContext),
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              ListTile(
                title: const Text('Sin subproducto'),
                subtitle: const Text('Usar el producto base'),
                onTap: () async {
                  Navigator.pop(sheetContext);
                  await _showQuantityEditor(product, null);
                },
              ),
              const Divider(),
              Expanded(
                child: ListView.separated(
                  shrinkWrap: true,
                  itemCount: product.options.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 8),
                  itemBuilder: (_, optionIndex) {
                    final option = product.options[optionIndex];
                    return ListTile(
                      title: Text(option.variantName.isEmpty
                          ? option.variantCode
                          : option.variantName),
                      subtitle: Text(
                        [option.material, option.size]
                            .where((value) => value.isNotEmpty)
                            .join(' · '),
                      ),
                      onTap: () async {
                        Navigator.pop(sheetContext);
                        await _showQuantityEditor(product, option);
                      },
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _showQuantityEditor(
      StudioProduct product, StudioProductOption? option,
      {int? editingIndex,
      int initialQuantity = 1,
      double? initialPrice}) async {
    final selectedPrice =
        initialPrice ?? ProductSelectionSummary.effectivePrice(product, option);
    final quantityController =
        TextEditingController(text: initialQuantity.toString());
    int quantity = initialQuantity;
    final double unitPrice =
        initialPrice ?? ProductSelectionSummary.effectivePrice(product, option);

    await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title:
            Text(editingIndex != null ? 'Editar producto' : 'Agregar a pedido'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (_productImageProvider(product) != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(12),
                  child: SizedBox(
                    height: 190,
                    width: 300,
                    child: Image(
                      image: _productImageProvider(product)!,
                      fit: BoxFit.cover,
                      errorBuilder: (_, __, ___) => const Center(
                        child: Icon(Icons.image_not_supported, size: 36),
                      ),
                    ),
                  ),
                ),
              ),
            Text(ProductSelectionSummary.buildLabel(product, option)),
            const SizedBox(height: 12),
            TextField(
              controller: quantityController,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: 'Cantidad'),
              onChanged: (value) => quantity = int.tryParse(value) ?? 1,
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                const Expanded(child: Text('Precio unitario')),
                Text(
                  '\$${selectedPrice.toStringAsFixed(0)}',
                  style: Theme.of(context)
                      .textTheme
                      .titleMedium
                      ?.copyWith(fontWeight: FontWeight.bold),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Align(
              alignment: Alignment.centerLeft,
              child: Text(
                option?.price != null
                    ? 'Precio del subproducto'
                    : 'Precio de lista',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () async {
              Navigator.pop(dialogContext);
              await _addProductDraft(
                product,
                option,
                quantity: quantity,
                unitPrice: unitPrice,
                editingIndex: editingIndex,
              );
            },
            child: Text(editingIndex != null ? 'Actualizar' : 'Agregar'),
          ),
        ],
      ),
    );
  }

  String _designName(String id) {
    for (final design in _catalog) {
      if (design.id == id) return design.name;
    }
    return 'Diseño seleccionado';
  }

  CatalogDesign? _designById(String id) {
    for (final design in _catalog) {
      if (design.id == id) return design;
    }
    return null;
  }

  ImageProvider<Object> _imageProvider(CatalogDesign design) {
    if (design.cachedPreviewPath != null &&
        File(design.cachedPreviewPath!).existsSync()) {
      return FileImage(File(design.cachedPreviewPath!));
    }
    final assetPath = design.assetPreviewPath;
    if (assetPath != null) return AssetImage(assetPath);
    return const AssetImage('assets/sticker_bank/manifest.json');
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: Text(widget.stickerCreatorOnly
              ? 'Creador de stickers'
              : 'Nuevo pedido'),
        ),
        body: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (!widget.stickerCreatorOnly) ...[
              Row(
                children: [
                  Expanded(
                    child: Text(
                      'Productos de Studio',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                  ),
                  IconButton(
                    onPressed: _loadingProducts ? null : _loadProducts,
                    icon: const Icon(Icons.refresh),
                    tooltip: 'Actualizar productos',
                  ),
                ],
              ),
              const SizedBox(height: 12),
              if (_loadingProducts)
                const Center(child: CircularProgressIndicator())
              else if (_products.isEmpty)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Text(
                      'No hay productos disponibles en este momento.',
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                  ),
                )
              else
                ExpansionTile(
                  initiallyExpanded: false,
                  title: const Text('Ver todos los productos de Studio'),
                  subtitle: Text('${_products.length} productos disponibles'),
                  children: _products.map((product) {
                    final hasOptions = product.options.isNotEmpty;
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Card(
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Row(children: [
                            SizedBox(
                                width: 72,
                                height: 72,
                                child: _productImageProvider(product) != null
                                    ? ClipRRect(
                                        borderRadius: BorderRadius.circular(8),
                                        child: Image(
                                          image:
                                              _productImageProvider(product)!,
                                          width: 72,
                                          height: 72,
                                          fit: BoxFit.cover,
                                          errorBuilder: (_, __, ___) =>
                                              const Icon(
                                                  Icons.image_not_supported),
                                        ),
                                      )
                                    : const Icon(Icons.inventory_2_outlined)),
                            const SizedBox(width: 12),
                            Expanded(
                                child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                  Text(product.name,
                                      style: Theme.of(context)
                                          .textTheme
                                          .titleSmall),
                                  const SizedBox(height: 3),
                                  Text(
                                      product.description.isEmpty
                                          ? product.category
                                          : product.description,
                                      maxLines: 2,
                                      overflow: TextOverflow.ellipsis),
                                  const SizedBox(height: 8),
                                  Wrap(
                                      spacing: 10,
                                      runSpacing: 6,
                                      crossAxisAlignment:
                                          WrapCrossAlignment.center,
                                      children: [
                                        Text(product.displayPrice,
                                            style: Theme.of(context)
                                                .textTheme
                                                .titleSmall
                                                ?.copyWith(
                                                    fontWeight:
                                                        FontWeight.bold)),
                                        FilledButton.icon(
                                          onPressed: _saving || _hasStickerItems
                                              ? null
                                              : () => _onProductTap(product),
                                          icon: const Icon(
                                              Icons.add_shopping_cart_outlined),
                                          label: Text(hasOptions
                                              ? 'Elegir'
                                              : 'Agregar'),
                                        ),
                                      ])
                                ])),
                          ]),
                        ),
                      ),
                    );
                  }).toList(),
                ),
              const SizedBox(height: 20),
              if (_draftItems.isEmpty)
                const SizedBox.shrink()
              else
                ..._draftItems.asMap().entries.map((entry) {
                  final item = entry.value;
                  final index = entry.key;
                  return Card(
                    margin: const EdgeInsets.only(bottom: 8),
                    child: ListTile(
                      title: Text(ProductSelectionSummary.buildLabel(
                          item.product, item.option)),
                      subtitle: Text(
                          'Cant: ${item.quantity} · Precio: \$${item.unitPrice.toStringAsFixed(0)}'),
                      trailing: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          IconButton(
                            icon: const Icon(Icons.edit_outlined),
                            onPressed: () => _showQuantityEditor(
                              item.product,
                              item.option,
                              editingIndex: index,
                              initialQuantity: item.quantity,
                              initialPrice: item.unitPrice,
                            ),
                          ),
                          IconButton(
                            icon: const Icon(Icons.delete_outline),
                            onPressed: () {
                              setState(() {
                                _draftItems.removeAt(index);
                              });
                              _scheduleQuote();
                            },
                          ),
                        ],
                      ),
                    ),
                  );
                }),
              const SizedBox(height: 20),
            ],
            Text('Formato', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            DropdownButtonFormField<String>(
              initialValue: _mode,
              items: MobileRuntimeConfigStore.current.stickerModes
                  .map((item) =>
                      DropdownMenuItem(value: item, child: Text(item)))
                  .toList(),
              onChanged: _saving
                  ? null
                  : (value) {
                      if (value == null) return;
                      setState(() {
                        _mode = value;
                        _quote = null;
                      });
                      _scheduleQuote();
                    },
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _client,
              enabled: !_saving,
              decoration: InputDecoration(
                labelText: 'Cliente *',
                suffixIcon: IconButton(
                  tooltip: 'Elegir cliente',
                  onPressed: _saving ? null : _chooseClient,
                  icon: const Icon(Icons.people_alt_outlined),
                ),
              ),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _whatsapp,
              enabled: !_saving,
              keyboardType: TextInputType.phone,
              decoration: const InputDecoration(labelText: 'WhatsApp'),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _notes,
              enabled: !_saving,
              maxLines: 2,
              decoration: const InputDecoration(labelText: 'Observaciones'),
            ),
            if (_mockups.isNotEmpty) ...[
              const SizedBox(height: 16),
              Text('Mockups de referencia (${_mockups.length})',
                  style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 6),
              SizedBox(
                height: 108,
                child: ListView.separated(
                  scrollDirection: Axis.horizontal,
                  itemCount: _mockups.length,
                  separatorBuilder: (_, __) => const SizedBox(width: 8),
                  itemBuilder: (_, index) => Stack(children: [
                    InkWell(
                      borderRadius: BorderRadius.circular(10),
                      onTap: () => _openMockup(index),
                      child: SizedBox(
                        width: 122,
                        height: 108,
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(10),
                          child: UniformImagePreview.file(_mockups[index].file,
                              semanticLabel: 'Mockup ${index + 1}'),
                        ),
                      ),
                    ),
                    Positioned(
                      right: 0,
                      child: IconButton(
                        tooltip: 'Quitar mockup',
                        style: IconButton.styleFrom(
                          backgroundColor: DoccionePalette.surfaceElevated,
                          foregroundColor: DoccionePalette.ink,
                        ),
                        icon: const Icon(Icons.close, size: 18),
                        onPressed: _saving
                            ? null
                            : () => setState(() => _mockups.removeAt(index)),
                      ),
                    ),
                  ]),
                ),
              ),
              const Text('No se imprimen ni se incluyen en el presupuesto.'),
            ],
            const SizedBox(height: 20),
            Row(children: [
              Text('Imágenes para crear stickers (${_images.length})',
                  style: Theme.of(context).textTheme.titleMedium),
              const Spacer(),
              TextButton.icon(
                onPressed: _saving ? null : _addImages,
                icon: const Icon(Icons.add_photo_alternate_outlined),
                label: const Text('Agregar'),
              ),
            ]),
            if (_images.isNotEmpty)
              SizedBox(
                height: 88,
                child: ListView.separated(
                  scrollDirection: Axis.horizontal,
                  itemCount: _images.length,
                  separatorBuilder: (_, __) => const SizedBox(width: 8),
                  itemBuilder: (_, index) => Stack(children: [
                    SizedBox.square(
                      dimension: 88,
                      child: UniformImagePreview.file(
                        _images[index],
                        semanticLabel: 'Imagen ${index + 1}',
                      ),
                    ),
                    Positioned(
                      right: 0,
                      child: IconButton(
                        style: IconButton.styleFrom(
                          backgroundColor: DoccionePalette.surfaceElevated,
                          foregroundColor: DoccionePalette.ink,
                        ),
                        icon: const Icon(Icons.close, size: 18),
                        onPressed: _saving
                            ? null
                            : () {
                                setState(() {
                                  _images.removeAt(index);
                                  _quote = null;
                                });
                                _scheduleQuote();
                              },
                      ),
                    ),
                  ]),
                ),
              )
            else
              const Text(
                'Elegí fotos de la cámara o galería. Studio las recibirá '
                'para procesarlas en el Creador de Stickers.',
              ),
            const SizedBox(height: 20),
            if (widget.showCatalogDesigns) ...[
              Row(children: [
                Expanded(
                  child: Text(
                      'Diseños del catálogo (${_selectedCatalog.length})',
                      style: Theme.of(context).textTheme.titleMedium),
                ),
                Badge(
                  key: const Key('sticker-catalog-selection-count'),
                  isLabelVisible: _selectedCatalog.isNotEmpty,
                  label: Text('${_selectedCatalog.length}'),
                  child: IconButton.outlined(
                    tooltip: 'Seleccionar diseños del catálogo',
                    onPressed: _saving || _loadingCatalog
                        ? null
                        : _selectCatalogDesigns,
                    icon: const Icon(Icons.collections_bookmark_outlined),
                  ),
                ),
              ]),
              const SizedBox(height: 8),
              if (_loadingCatalog)
                const Center(child: CircularProgressIndicator())
              else if (_selectedCatalog.isEmpty)
                const Text('Elegí diseños del catálogo y agregalos al pedido.')
              else
                SizedBox(
                  height: 180,
                  child: TwoRowCatalogGrid(
                    key: const Key('sticker-order-selected-catalog-grid'),
                    rows: 2,
                    padding: const EdgeInsets.all(4),
                    mainAxisSpacing: 6,
                    crossAxisSpacing: 6,
                    itemCount: _selectedCatalog.length,
                    itemBuilder: (_, index) {
                      final id = _selectedCatalog.elementAt(index);
                      final design = _designById(id);
                      if (design == null) {
                        return Center(child: Text(_designName(id)));
                      }
                      return StickerCatalogTile(
                        imageProvider: _imageProvider(design),
                        semanticLabel:
                            '${design.name}. Seleccionado. Tocá para quitarlo del pedido.',
                        selected: true,
                        onTap: _saving
                            ? null
                            : () {
                                setState(() {
                                  _selectedCatalog.remove(id);
                                  _quote = null;
                                });
                                _scheduleQuote();
                              },
                      );
                    },
                  ),
                ),
            ],
            const SizedBox(height: 20),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(children: [
                      Expanded(
                          child: Text('Crear pedido',
                              style: Theme.of(context).textTheme.titleMedium)),
                      TextButton.icon(
                        onPressed:
                            _saving || _orderIsEmpty ? null : _cancelOrder,
                        icon: const Icon(Icons.cancel_outlined),
                        label: const Text('Cancelar'),
                      ),
                    ]),
                    const SizedBox(height: 8),
                    Row(children: [
                      IconButton.outlined(
                        tooltip: 'Compartir presupuesto por WhatsApp',
                        onPressed:
                            _saving || _orderIsEmpty ? null : _shareQuote,
                        icon: const Icon(Icons.share_outlined),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                          child: FilledButton.icon(
                        onPressed: _saving ||
                                _orderIsEmpty ||
                                _client.text.trim().isEmpty
                            ? null
                            : _submit,
                        icon: const Icon(Icons.send),
                        label: const Text('Enviar a Studio'),
                      )),
                    ]),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 12),
            _LiveStickerQuote(
              count: _designCount,
              quoting: _quoting,
              quote: _quote,
              productTotal: _productQuoteTotal,
              error: _quoteError,
              onRetry: _orderIsEmpty ? null : _scheduleQuote,
            ),
          ],
        ),
      );
}

class StudioOrderItemDraft {
  final StudioProduct product;
  final StudioProductOption? option;
  final int quantity;
  final double unitPrice;

  const StudioOrderItemDraft({
    required this.product,
    required this.option,
    required this.quantity,
    required this.unitPrice,
  });
}

// Selector conservado para el flujo alternativo del catálogo de Studio.
// ignore: unused_element
class _ProductSelectorSheet extends StatelessWidget {
  final List<StudioProduct> products;
  final bool loading;
  final Future<void> Function(
      StudioProduct product, StudioProductOption? option) onSelect;

  const _ProductSelectorSheet({
    required this.products,
    required this.loading,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    'Seleccioná un producto',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                ),
                IconButton(
                  onPressed: () => Navigator.pop(context),
                  icon: const Icon(Icons.close),
                ),
              ],
            ),
            const SizedBox(height: 8),
            if (loading)
              const Center(child: CircularProgressIndicator())
            else if (products.isEmpty)
              const Text('No hay productos disponibles por el momento.')
            else
              Expanded(
                child: ListView.separated(
                  itemCount: products.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 8),
                  itemBuilder: (_, index) {
                    final product = products[index];
                    final hasOptions = product.options.isNotEmpty;
                    return Card(
                      child: ListTile(
                        title: Text(product.name),
                        subtitle: Text(product.description.isEmpty
                            ? product.category
                            : product.description),
                        trailing: Text(product.displayPrice),
                        onTap: () async {
                          if (!hasOptions) {
                            await onSelect(product, null);
                            return;
                          }
                          await showModalBottomSheet<void>(
                            context: context,
                            isScrollControlled: true,
                            builder: (sheetContext) => SafeArea(
                              child: Padding(
                                padding: const EdgeInsets.all(16),
                                child: Column(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Row(
                                      children: [
                                        Expanded(
                                          child: Text(
                                            'Elegí un subproducto',
                                            style: Theme.of(context)
                                                .textTheme
                                                .titleLarge,
                                          ),
                                        ),
                                        IconButton(
                                          onPressed: () =>
                                              Navigator.pop(sheetContext),
                                          icon: const Icon(Icons.close),
                                        ),
                                      ],
                                    ),
                                    const SizedBox(height: 8),
                                    ListTile(
                                      title: const Text('Sin subproducto'),
                                      subtitle:
                                          const Text('Usar el producto base'),
                                      onTap: () async {
                                        Navigator.pop(sheetContext);
                                        await onSelect(product, null);
                                      },
                                    ),
                                    const Divider(),
                                    Expanded(
                                      child: ListView.separated(
                                        itemCount: product.options.length,
                                        separatorBuilder: (_, __) =>
                                            const SizedBox(height: 8),
                                        itemBuilder: (_, optionIndex) {
                                          final option =
                                              product.options[optionIndex];
                                          return ListTile(
                                            title: Text(
                                                option.variantName.isEmpty
                                                    ? option.variantCode
                                                    : option.variantName),
                                            subtitle: Text(
                                              [option.material, option.size]
                                                  .where((value) =>
                                                      value.isNotEmpty)
                                                  .join(' · '),
                                            ),
                                            onTap: () async {
                                              Navigator.pop(sheetContext);
                                              await onSelect(product, option);
                                            },
                                          );
                                        },
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          );
                        },
                      ),
                    );
                  },
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _LiveStickerQuote extends StatelessWidget {
  final int count;
  final bool quoting;
  final StickerQuote? quote;
  final double? productTotal;
  final String? error;
  final VoidCallback? onRetry;

  const _LiveStickerQuote({
    required this.count,
    required this.quoting,
    required this.quote,
    required this.productTotal,
    required this.error,
    required this.onRetry,
  });

  @override
  Widget build(BuildContext context) => Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('Presupuesto en vivo',
                  style: Theme.of(context)
                      .textTheme
                      .titleMedium
                      ?.copyWith(fontWeight: FontWeight.w700)),
              const SizedBox(height: 4),
              if (count == 0 && productTotal == null)
                const Text(
                    'Agregá imágenes, diseños o productos para calcularlo.')
              else if (quoting)
                const Padding(
                  padding: EdgeInsets.all(8),
                  child: Center(child: CircularProgressIndicator()),
                )
              else if (quote != null) ...[
                Text(quote!.matched
                    ? 'TOTAL: \$${quote!.total.toStringAsFixed(2)}'
                    : 'Presupuesto pendiente'),
                if (quote!.ruleName != null) Text(quote!.ruleName!),
                if (quote!.warning != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text(quote!.warning!,
                        style: TextStyle(
                            color: Theme.of(context).colorScheme.error)),
                  ),
              ] else if (productTotal != null) ...[
                Text('TOTAL: \$${productTotal!.toStringAsFixed(2)}'),
              ] else if (error != null) ...[
                Text(error!,
                    style:
                        TextStyle(color: Theme.of(context).colorScheme.error)),
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton.icon(
                    onPressed: onRetry,
                    icon: const Icon(Icons.refresh),
                    label: const Text('Reintentar'),
                  ),
                ),
              ],
            ],
          ),
        ),
      );
}

class _StickerCatalogPicker extends StatefulWidget {
  final CatalogApiClient api;
  final List<CatalogDesign> initialCatalog;
  final Set<String> initiallySelected;
  final void Function(MockupReference mockup) onMockupCaptured;

  const _StickerCatalogPicker({
    required this.api,
    required this.initialCatalog,
    required this.initiallySelected,
    required this.onMockupCaptured,
  });

  @override
  State<_StickerCatalogPicker> createState() => _StickerCatalogPickerState();
}

class _StickerCatalogPickerState extends State<_StickerCatalogPicker> {
  late List<CatalogDesign> _catalog;
  late List<CatalogDesign> _allCatalog;
  late final Set<String> _selected;
  final _search = TextEditingController();
  String? _tag;
  bool _hideOptions = false;
  bool _loadingCatalog = false;
  bool _arAvailable = false;

  @override
  void initState() {
    super.initState();
    _catalog = List.of(widget.initialCatalog);
    _allCatalog = List.of(widget.initialCatalog);
    _selected = Set.of(widget.initiallySelected);
    unawaited(_refreshArAvailability());
  }

  Future<void> _refreshArAvailability() async {
    if (!Platform.isAndroid && !Platform.isIOS) return;
    var available = false;
    try {
      available = await const MethodChannel('com.doccione.mobile/share')
              .invokeMethod<bool>('isArAvailable') ??
          false;
    } on Object {
      // Builds without native AR and incompatible devices keep using the
      // offline camera without presenting an installation prompt.
    }
    if (mounted) setState(() => _arAvailable = available);
  }

  List<String> get _tags {
    final tags = <String>{};
    for (final design in _catalog) {
      tags.addAll(design.tags);
    }
    return tags.toList()..sort();
  }

  List<CatalogDesign> get _visibleCatalog {
    final query = _search.text.trim().toLowerCase();
    return _catalog.where((design) {
      final matchesTag = _tag == null || design.tags.contains(_tag);
      if (query.isEmpty) return matchesTag;
      final searchable = [
        design.name,
        design.category,
        design.caption,
        ...design.tags,
      ].join(' ').toLowerCase();
      return matchesTag && searchable.contains(query);
    }).toList();
  }

  Future<void> _reloadCatalog(
      {bool random = false, bool recent = false}) async {
    setState(() {
      _loadingCatalog = true;
    });
    try {
      final items = List<CatalogDesign>.of(_allCatalog);
      if (random) items.shuffle();
      if (recent) {
        items.sort((a, b) => b.modifiedMs.compareTo(a.modifiedMs));
      }
      if (!mounted) return;
      setState(() {
        _catalog = items;
        _loadingCatalog = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _loadingCatalog = false;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('No se pudo cargar el catálogo: $error')),
      );
    }
  }

  ImageProvider<Object> _imageProvider(CatalogDesign design) {
    final assetPath = design.assetPreviewPath;
    if (assetPath != null) return AssetImage(assetPath);
    // El manifest incluido siempre define un recurso local para cada diseño.
    if (design.previewUrl.isEmpty) {
      return const AssetImage('assets/sticker_bank/manifest.json');
    }
    return NetworkImage(
      '${widget.api.baseUrl}${design.previewUrl}',
      headers: widget.api.headers,
    );
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _showPreviewOptions(CatalogDesign design) async {
    await _refreshArAvailability();
    if (!mounted) return;
    final action = await showModalBottomSheet<_DesignPreviewAction>(
      context: context,
      builder: (sheetContext) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.visibility_outlined),
              title: const Text('Ver diseño'),
              onTap: () =>
                  Navigator.pop(sheetContext, _DesignPreviewAction.design),
            ),
            ListTile(
              leading: const Icon(Icons.camera_alt_outlined),
              title: const Text('Vista previa sin conexión'),
              subtitle: const Text(
                'Funciona sin internet ni Google Play Services para AR',
              ),
              onTap: () =>
                  Navigator.pop(sheetContext, _DesignPreviewAction.surface),
            ),
            if (_arAvailable)
              ListTile(
                leading: const Icon(Icons.view_in_ar_outlined),
                title: const Text('Probar con AR'),
                subtitle: const Text(
                  'Detecta superficies y ancla el diseño al mover el teléfono',
                ),
                onTap: () =>
                    Navigator.pop(sheetContext, _DesignPreviewAction.ar),
              ),
          ],
        ),
      ),
    );
    if (!mounted || action == null) return;
    if (action == _DesignPreviewAction.design) {
      await showRealSizePreview(
        context,
        design: design,
        imageProvider: _imageProvider(design),
      );
      return;
    }

    if (!mounted) return;
    if (action == _DesignPreviewAction.ar) {
      await _showNativeArSurfacePreview(design);
    } else {
      await _showCameraSurfacePreview(design);
    }
  }

  @override
  Widget build(BuildContext context) => SafeArea(
        child: SizedBox(
          height: MediaQuery.sizeOf(context).height * .96,
          child: Column(children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 18, 12, 8),
              child: Row(children: [
                Expanded(
                  child: Text('Seleccioná diseños',
                      style: Theme.of(context).textTheme.titleLarge),
                ),
                IconButton(
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(Icons.close)),
              ]),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 4),
              child: Row(
                children: [
                  Expanded(
                    child: FilledButton.icon(
                      onPressed: () =>
                          setState(() => _hideOptions = !_hideOptions),
                      icon: Icon(_hideOptions
                          ? Icons.visibility
                          : Icons.visibility_off),
                      label: Text(_hideOptions
                          ? 'Mostrar barra de opciones'
                          : 'Ocultar barra de opciones'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton(
                    tooltip: 'Aleatorios',
                    onPressed: _loadingCatalog
                        ? null
                        : () => _reloadCatalog(random: true),
                    icon: const Icon(Icons.shuffle),
                  ),
                  IconButton(
                    tooltip: 'Últimos procesados',
                    onPressed: _loadingCatalog
                        ? null
                        : () => _reloadCatalog(recent: true),
                    icon: const Icon(Icons.history),
                  ),
                ],
              ),
            ),
            if (!_hideOptions)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 4),
                child: TextField(
                  controller: _search,
                  onChanged: (_) => setState(() {}),
                  decoration: InputDecoration(
                    prefixIcon: const Icon(Icons.search),
                    hintText: 'Buscar diseño o etiqueta',
                    suffixIcon: _search.text.isEmpty
                        ? null
                        : IconButton(
                            tooltip: 'Limpiar búsqueda',
                            icon: const Icon(Icons.clear),
                            onPressed: () {
                              _search.clear();
                              setState(() {});
                            },
                          ),
                  ),
                ),
              ),
            if (!_hideOptions && _tags.isNotEmpty)
              SizedBox(
                height: 48,
                child: ListView(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  children: [
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4),
                      child: FilterChip(
                        label: const Text('Todas'),
                        selected: _tag == null,
                        onSelected: (_) => setState(() => _tag = null),
                      ),
                    ),
                    ..._tags.map(
                      (tag) => Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 4),
                        child: FilterChip(
                          label: Text('#$tag'),
                          selected: _tag == tag,
                          onSelected: (_) =>
                              setState(() => _tag = _tag == tag ? null : tag),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            Expanded(
              child: _visibleCatalog.isEmpty
                  ? const Center(child: Text('No hay diseños disponibles.'))
                  : TwoRowCatalogGrid(
                      key: const Key('sticker-picker-catalog-grid'),
                      rows: 3,
                      padding: const EdgeInsets.all(4),
                      mainAxisSpacing: 5,
                      crossAxisSpacing: 5,
                      itemCount: _visibleCatalog.length,
                      itemBuilder: (_, index) {
                        final design = _visibleCatalog[index];
                        final selected = _selected.contains(design.id);
                        return StickerCatalogTile(
                          imageProvider: _imageProvider(design),
                          semanticLabel:
                              '${design.name}. ${selected ? 'Seleccionado' : 'No seleccionado'}. Mantener presionado para ver a tamaño real.',
                          selected: selected,
                          onTap: () => setState(() => selected
                              ? _selected.remove(design.id)
                              : _selected.add(design.id)),
                          onLongPress: () => _showPreviewOptions(design),
                        );
                      },
                    ),
            ),
            Padding(
              padding: const EdgeInsets.all(16),
              child: FilledButton.icon(
                onPressed: () => Navigator.pop(context, Set.of(_selected)),
                icon: const Icon(Icons.add_shopping_cart),
                label: Text('Agregar seleccionados (${_selected.length})'),
              ),
            ),
          ]),
        ),
      );

  Future<void> _showCameraSurfacePreview(CatalogDesign design) async {
    final captured = await showDialog<_CapturedMockup>(
      context: context,
      builder: (_) => _LiveSurfacePreview(
        design: design,
        imageProvider: _imageProvider(design),
      ),
    );
    if (!mounted || captured == null) return;

    await _handleCapturedMockup(design, captured);
  }

  Future<void> _showNativeArSurfacePreview(CatalogDesign design) async {
    final result = await showDialog<Object>(
      context: context,
      barrierDismissible: false,
      builder: (_) => _NativeArPreview(design: design),
    );
    if (!mounted) return;
    if (result == _NativeArExit.manual) {
      await _showCameraSurfacePreview(design);
      return;
    }
    if (result is _CapturedMockup) {
      await _handleCapturedMockup(design, result);
    }
  }

  Future<void> _handleCapturedMockup(
    CatalogDesign design,
    _CapturedMockup captured,
  ) async {
    final action = await showModalBottomSheet<_CapturedPhotoAction>(
      context: context,
      builder: (sheetContext) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const ListTile(
            leading: Icon(Icons.photo_camera_outlined),
            title: Text('Foto de referencia capturada'),
            subtitle: Text('Elegí qué hacer con esta foto.'),
          ),
          ListTile(
            leading: const Icon(Icons.add_photo_alternate_outlined),
            title: const Text('Asociar a este pedido'),
            subtitle: const Text(
                'Se guarda como mockup de referencia, sin imprimir.'),
            onTap: () =>
                Navigator.pop(sheetContext, _CapturedPhotoAction.attach),
          ),
          ListTile(
            leading: const Icon(Icons.share_outlined),
            title: const Text('Enviar foto'),
            subtitle: const Text(
                'Abrir las aplicaciones disponibles para compartir.'),
            onTap: () =>
                Navigator.pop(sheetContext, _CapturedPhotoAction.share),
          ),
          ListTile(
            leading: const Icon(Icons.receipt_long_outlined),
            title: const Text('Crear pedido con este mockup'),
            subtitle: const Text(
                'Agrega el diseño y vuelve al formulario del pedido.'),
            onTap: () =>
                Navigator.pop(sheetContext, _CapturedPhotoAction.createOrder),
          ),
        ]),
      ),
    );
    if (!mounted || action == null) return;
    final file = await _storeCapturedMockup(captured.file);
    var mockup = MockupReference(
      file: file,
      designId: design.id,
      designName: design.name,
      sizeCm: captured.sizeCm,
      surface: captured.surface,
      material: 'Vinilo',
      comment: '',
      approval: MockupApproval.pending,
      curved: captured.curved,
      createdAt: DateTime.now().toUtc(),
    );
    if (action == _CapturedPhotoAction.attach ||
        action == _CapturedPhotoAction.createOrder) {
      final detailed = await _editCapturedMockup(mockup);
      if (detailed == null || !mounted) return;
      mockup = detailed;
      widget.onMockupCaptured(mockup);
      if (action == _CapturedPhotoAction.createOrder) {
        _selected.add(design.id);
        Navigator.pop(context, Set.of(_selected));
        return;
      }
      /*if (!_canAddStickerItems) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('El pedido actual contiene productos. Creá un pedido de stickers para asociar la foto.'),
          ),
        );
        return;
      }
      setState(() => _mockups.add(file));*/
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Mockup asociado al pedido actual.')),
      );
      return;
    }
    try {
      await const MethodChannel('com.doccione.mobile/share')
          .invokeMethod<void>('shareImage', {'path': file.path});
    } on PlatformException {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text('No se pudo abrir el envío de la foto.')),
        );
      }
    }
  }

  /// Camera plug-ins commonly return a cache file. Copy it immediately so a
  /// mockup attached to an offline order survives app restarts and cache cleanup.
  Future<File> _storeCapturedMockup(XFile captured) async {
    final documents = await getApplicationDocumentsDirectory();
    final folder = Directory(path.join(documents.path, 'order_mockups'));
    await folder.create(recursive: true);
    final source = File(captured.path);
    final extension = path.extension(captured.path).isEmpty
        ? '.jpg'
        : path.extension(captured.path);
    final target = File(path.join(
      folder.path,
      'mockup_${DateTime.now().microsecondsSinceEpoch}$extension',
    ));
    return source.copy(target.path);
  }

  Future<MockupReference?> _editCapturedMockup(MockupReference mockup) async {
    var surface = mockup.surface;
    var approval = mockup.approval;
    final material = TextEditingController(text: mockup.material);
    final comment = TextEditingController(text: mockup.comment);
    final result = await showDialog<MockupReference>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Completar mockup'),
          content: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              DropdownButtonFormField<MockupSurface>(
                initialValue: surface,
                decoration: const InputDecoration(labelText: 'Superficie'),
                items: MockupSurface.values
                    .map((value) => DropdownMenuItem(
                          value: value,
                          child: Text(value.label),
                        ))
                    .toList(),
                onChanged: (value) {
                  if (value != null) setDialogState(() => surface = value);
                },
              ),
              const SizedBox(height: 10),
              TextField(
                controller: material,
                decoration: const InputDecoration(labelText: 'Material'),
              ),
              const SizedBox(height: 10),
              DropdownButtonFormField<MockupApproval>(
                initialValue: approval,
                decoration: const InputDecoration(labelText: 'Aprobación'),
                items: MockupApproval.values
                    .map((value) => DropdownMenuItem(
                          value: value,
                          child: Text(value.label),
                        ))
                    .toList(),
                onChanged: (value) {
                  if (value != null) setDialogState(() => approval = value);
                },
              ),
              const SizedBox(height: 10),
              TextField(
                controller: comment,
                maxLines: 3,
                decoration: const InputDecoration(labelText: 'Comentario'),
              ),
            ]),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('Cancelar'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(
                dialogContext,
                mockup.copyWith(
                  surface: surface,
                  material: material.text.trim().isEmpty
                      ? 'Sin especificar'
                      : material.text.trim(),
                  comment: comment.text.trim(),
                  approval: approval,
                ),
              ),
              child: const Text('Guardar'),
            ),
          ],
        ),
      ),
    );
    material.dispose();
    comment.dispose();
    return result;
  }
}

enum _DesignPreviewAction { design, surface, ar }

enum _NativeArExit { manual }

enum _CapturedPhotoAction { attach, share, createOrder }

class _CapturedMockup {
  const _CapturedMockup({
    required this.file,
    required this.sizeCm,
    required this.surface,
    required this.curved,
  });

  final XFile file;
  final double sizeCm;
  final MockupSurface surface;
  final bool curved;
}

class _NativeArPreview extends StatefulWidget {
  const _NativeArPreview({required this.design});

  final CatalogDesign design;

  @override
  State<_NativeArPreview> createState() => _NativeArPreviewState();
}

class _NativeArPreviewState extends State<_NativeArPreview> {
  MethodChannel? _channel;
  late final Future<Uint8List> _overlayBytes;
  double _sizeCm = 10;
  bool _curved = false;
  bool _capturing = false;
  bool _supported = true;
  String _status = 'Move el telefono para detectar una superficie';

  @override
  void initState() {
    super.initState();
    _overlayBytes = _loadOverlay();
  }

  Future<Uint8List> _loadOverlay() async {
    final assetPath = widget.design.assetPreviewPath;
    if (assetPath == null) {
      throw StateError(
          'El diseno no tiene una copia local para usar sin internet.');
    }
    final data = await rootBundle.load(assetPath);
    return data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes);
  }

  Future<void> _onPlatformViewCreated(int viewId, Uint8List bytes) async {
    final channel = MethodChannel('com.doccione.mobile/ar_mockup/$viewId');
    _channel = channel;
    channel.setMethodCallHandler((call) async {
      if (call.method != 'status' || !mounted) return;
      final arguments = Map<Object?, Object?>.from(call.arguments as Map);
      setState(() {
        _supported = arguments['supported'] as bool? ?? true;
        _status = arguments['message'] as String? ?? _status;
      });
    });
    await channel.invokeMethod<void>('updateConfiguration', {
      'overlayBytes': bytes,
      'aspectRatio': widget.design.aspectRatio,
      'sizeCm': _sizeCm,
      'curved': _curved,
    });
  }

  Future<void> _updateConfiguration() async {
    await _channel?.invokeMethod<void>('updateConfiguration', {
      'aspectRatio': widget.design.aspectRatio,
      'sizeCm': _sizeCm,
      'curved': _curved,
    });
  }

  Future<void> _capture() async {
    final channel = _channel;
    if (channel == null || _capturing) return;
    setState(() => _capturing = true);
    try {
      final output = await channel.invokeMethod<String>('capture');
      if (output != null && mounted) {
        Navigator.pop(
          context,
          _CapturedMockup(
            file: XFile(output),
            sizeCm: _sizeCm,
            surface: _curved ? MockupSurface.bottle : MockupSurface.other,
            curved: _curved,
          ),
        );
      }
    } on PlatformException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
              content: Text(error.message ?? 'No se pudo sacar la foto AR.')),
        );
      }
    } finally {
      if (mounted) setState(() => _capturing = false);
    }
  }

  @override
  Widget build(BuildContext context) => Dialog.fullscreen(
        child: Scaffold(
          backgroundColor: Colors.black,
          body: FutureBuilder<Uint8List>(
            future: _overlayBytes,
            builder: (context, snapshot) {
              if (snapshot.hasError) {
                return _ArUnavailable(
                  message: '${snapshot.error}',
                  onManual: () => Navigator.pop(context, _NativeArExit.manual),
                );
              }
              final bytes = snapshot.data;
              if (bytes == null) {
                return const Center(child: CircularProgressIndicator());
              }
              final creationParams = <String, Object>{
                'overlayBytes': bytes,
                'aspectRatio': widget.design.aspectRatio,
                'sizeCm': _sizeCm,
                'curved': _curved,
              };
              final nativeView = Platform.isAndroid
                  ? AndroidView(
                      viewType: 'doccione/ar_mockup',
                      creationParams: creationParams,
                      creationParamsCodec: const StandardMessageCodec(),
                      onPlatformViewCreated: (id) =>
                          _onPlatformViewCreated(id, bytes),
                    )
                  : UiKitView(
                      viewType: 'doccione/ar_mockup',
                      creationParams: creationParams,
                      creationParamsCodec: const StandardMessageCodec(),
                      onPlatformViewCreated: (id) =>
                          _onPlatformViewCreated(id, bytes),
                    );
              return Stack(children: [
                Positioned.fill(child: nativeView),
                SafeArea(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Row(children: [
                      IconButton.filledTonal(
                        tooltip: 'Cerrar',
                        onPressed: () => Navigator.pop(context),
                        icon: const Icon(Icons.close),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          _status,
                          style: const TextStyle(
                            color: Colors.white,
                            shadows: [Shadow(blurRadius: 5)],
                          ),
                        ),
                      ),
                    ]),
                  ),
                ),
                Align(
                  alignment: Alignment.bottomCenter,
                  child: SafeArea(
                    minimum: const EdgeInsets.all(12),
                    child: Material(
                      color: Colors.black.withValues(alpha: .78),
                      borderRadius: BorderRadius.circular(18),
                      child: Padding(
                        padding: const EdgeInsets.all(14),
                        child:
                            Column(mainAxisSize: MainAxisSize.min, children: [
                          Row(children: [
                            Text(
                              '${_sizeCm.toStringAsFixed(0)} cm',
                              style: const TextStyle(color: Colors.white),
                            ),
                            Expanded(
                              child: Slider(
                                min: 3,
                                max: 29,
                                divisions: 26,
                                value: _sizeCm.clamp(3.0, 29.0),
                                onChanged: (value) {
                                  setState(() => _sizeCm = value);
                                  _updateConfiguration();
                                },
                              ),
                            ),
                          ]),
                          Row(children: [
                            Expanded(
                              child: SegmentedButton<bool>(
                                segments: const [
                                  ButtonSegment(
                                    value: false,
                                    icon: Icon(Icons.crop_square),
                                    label: Text('Plano'),
                                  ),
                                  ButtonSegment(
                                    value: true,
                                    icon: Icon(Icons.local_drink_outlined),
                                    label: Text('Curvo'),
                                  ),
                                ],
                                selected: {_curved},
                                onSelectionChanged: (selection) {
                                  setState(() => _curved = selection.first);
                                  _updateConfiguration();
                                },
                              ),
                            ),
                            IconButton(
                              tooltip: 'Volver a colocar',
                              color: Colors.white,
                              onPressed: () =>
                                  _channel?.invokeMethod<void>('reset'),
                              icon: const Icon(Icons.refresh),
                            ),
                            IconButton.filled(
                              tooltip: 'Sacar foto',
                              onPressed:
                                  _supported && !_capturing ? _capture : null,
                              icon: _capturing
                                  ? const SizedBox.square(
                                      dimension: 18,
                                      child: CircularProgressIndicator(
                                        strokeWidth: 2,
                                      ),
                                    )
                                  : const Icon(Icons.camera_alt),
                            ),
                          ]),
                          TextButton.icon(
                            onPressed: () =>
                                Navigator.pop(context, _NativeArExit.manual),
                            icon: const Icon(Icons.camera_outlined),
                            label: Text(_supported
                                ? 'Usar camara manual'
                                : 'AR no disponible: usar camara manual'),
                          ),
                        ]),
                      ),
                    ),
                  ),
                ),
              ]);
            },
          ),
        ),
      );
}

class _ArUnavailable extends StatelessWidget {
  const _ArUnavailable({required this.message, required this.onManual});

  final String message;
  final VoidCallback onManual;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.view_in_ar_outlined,
                size: 58, color: Colors.white),
            const SizedBox(height: 16),
            Text(
              message,
              textAlign: TextAlign.center,
              style: const TextStyle(color: Colors.white),
            ),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: onManual,
              child: const Text('Usar camara manual'),
            ),
          ]),
        ),
      );
}

class _LiveSurfacePreview extends StatefulWidget {
  final CatalogDesign design;
  final ImageProvider imageProvider;

  const _LiveSurfacePreview({
    required this.design,
    required this.imageProvider,
  });

  @override
  State<_LiveSurfacePreview> createState() => _LiveSurfacePreviewState();
}

class _LiveSurfacePreviewState extends State<_LiveSurfacePreview> {
  final _stageKey = GlobalKey();
  CameraController? _controller;
  Object? _cameraError;
  double _sizeCm = 10;
  Offset _position = Offset.zero;
  double _rotationX = 0;
  double _rotationY = 0;
  double _rotationZ = 0;
  double _startingRotationZ = 0;
  bool _curvedSurface = false;
  bool _capturing = false;

  @override
  void initState() {
    super.initState();
    _initializeCamera();
  }

  Future<void> _initializeCamera() async {
    try {
      final cameras = await availableCameras();
      final camera = cameras.firstWhere(
        (item) => item.lensDirection == CameraLensDirection.back,
        orElse: () => cameras.first,
      );
      final controller = CameraController(
        camera,
        ResolutionPreset.medium,
        enableAudio: false,
      );
      await controller.initialize();
      if (!mounted) {
        await controller.dispose();
        return;
      }
      setState(() => _controller = controller);
    } catch (error) {
      if (!mounted) return;
      setState(() => _cameraError = error);
    }
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Dialog.fullscreen(
      child: Scaffold(
        backgroundColor: Colors.black,
        body: SafeArea(
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
                child: Row(
                  children: [
                    IconButton(
                      onPressed: () => Navigator.pop(context),
                      icon: const Icon(Icons.close),
                      color: Colors.white,
                      tooltip: 'Cerrar',
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        'Vista en vivo: ${widget.design.name}',
                        style: Theme.of(context)
                            .textTheme
                            .titleMedium
                            ?.copyWith(color: Colors.white),
                      ),
                    ),
                    IconButton(
                      onPressed: _controller == null || _capturing
                          ? null
                          : _capturePhoto,
                      icon: _capturing
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.camera_alt),
                      color: Colors.white,
                      tooltip: 'Sacar foto',
                    ),
                  ],
                ),
              ),
              Expanded(
                child: LayoutBuilder(
                    builder: (context, constraints) => Stack(
                          key: _stageKey,
                          fit: StackFit.expand,
                          children: [
                            if (_controller != null)
                              CameraPreview(_controller!)
                            else if (_cameraError != null)
                              Center(
                                child: Padding(
                                  padding: const EdgeInsets.all(24),
                                  child: Text(
                                    'No se pudo abrir la cámara.\n$_cameraError',
                                    textAlign: TextAlign.center,
                                    style: const TextStyle(color: Colors.white),
                                  ),
                                ),
                              )
                            else
                              const Center(child: CircularProgressIndicator()),
                            _buildPlacementOverlay(constraints),
                          ],
                        )),
              ),
              Container(
                color: Colors.black87,
                padding: const EdgeInsets.fromLTRB(20, 8, 20, 18),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      'Tamaño del diseño',
                      style: Theme.of(context)
                          .textTheme
                          .labelLarge
                          ?.copyWith(color: Colors.white),
                    ),
                    Slider(
                      value: _sizeCm,
                      min: 3,
                      max: 29,
                      divisions: 26,
                      label: '${_sizeCm.toStringAsFixed(0)} cm',
                      onChanged: (value) => setState(() => _sizeCm = value),
                    ),
                    Row(children: [
                      ChoiceChip(
                        label: const Text('Plano'),
                        selected: !_curvedSurface,
                        onSelected: (_) =>
                            setState(() => _curvedSurface = false),
                      ),
                      const SizedBox(width: 8),
                      ChoiceChip(
                        label: const Text('Vaso / botella'),
                        selected: _curvedSurface,
                        onSelected: (_) =>
                            setState(() => _curvedSurface = true),
                      ),
                      const Spacer(),
                      IconButton(
                        tooltip: 'Restablecer',
                        color: Colors.white,
                        onPressed: () => setState(() {
                          _position = Offset.zero;
                          _rotationX = 0;
                          _rotationY = 0;
                          _rotationZ = 0;
                        }),
                        icon: const Icon(Icons.center_focus_strong),
                      ),
                    ]),
                    Text(
                      '${_sizeCm.toStringAsFixed(0)} cm. Arrastra para ubicar; usa dos dedos para girar y ajustar la perspectiva.',
                      style: Theme.of(context)
                          .textTheme
                          .bodySmall
                          ?.copyWith(color: Colors.white70),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _capturePhoto() async {
    final controller = _controller;
    if (controller == null || _capturing) return;
    setState(() => _capturing = true);
    try {
      final photo = await controller.takePicture();
      final mockup = await _composeMockup(photo);
      if (mounted) {
        Navigator.pop(
          context,
          _CapturedMockup(
            file: mockup,
            sizeCm: _sizeCm,
            surface:
                _curvedSurface ? MockupSurface.bottle : MockupSurface.notebook,
            curved: _curvedSurface,
          ),
        );
      }
    } on CameraException catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('No se pudo sacar la foto.')),
        );
      }
    } finally {
      if (mounted) setState(() => _capturing = false);
    }
  }

  /// Android composites the original camera capture locally.  It deliberately
  /// uses the asset bytes rather than a URL, so mockups work offline.
  Future<XFile> _composeMockup(XFile photo) async {
    if ((!Platform.isAndroid && !Platform.isIOS) ||
        widget.design.assetPreviewPath == null) {
      return photo;
    }
    final renderBox =
        _stageKey.currentContext?.findRenderObject() as RenderBox?;
    if (renderBox == null || !renderBox.hasSize) return photo;
    try {
      final imageData = await rootBundle.load(widget.design.assetPreviewPath!);
      final stage = renderBox.size;
      final shortestSide = stage.shortestSide;
      final width = shortestSide * (.16 + ((_sizeCm - 3) / 26) * .68);
      final aspect = widget.design.aspectRatio.clamp(.2, 5.0).toDouble();
      final height = width / aspect;
      final mesh = _projectedMesh(
        stage: stage,
        width: width,
        height: height,
        segments: _curvedSurface ? 24 : 1,
      );
      final output = await const MethodChannel('com.doccione.mobile/share')
          .invokeMethod<String>('composeMockup', {
        'photoPath': photo.path,
        'overlayBytes': imageData.buffer.asUint8List(),
        'left': ((stage.width - width) / 2 + _position.dx) / stage.width,
        'top': ((stage.height - height) / 2 + _position.dy) / stage.height,
        'width': width / stage.width,
        'height': height / stage.height,
        'rotationDegrees': _rotationZ * 180 / 3.141592653589793,
        'mesh': mesh,
        'segments': _curvedSurface ? 24 : 1,
        'curved': _curvedSurface,
        'sizeCm': _sizeCm.round(),
      });
      return output == null ? photo : XFile(output);
    } on PlatformException {
      return photo;
    }
  }

  List<double> _projectedMesh({
    required Size stage,
    required double width,
    required double height,
    required int segments,
  }) {
    final result = <double>[];
    final centerX = stage.width / 2 + _position.dx;
    final centerY = stage.height / 2 + _position.dy;
    final radius = width * .72;
    for (var index = 0; index <= segments; index++) {
      final x = -width / 2 + width * index / segments;
      final z = _curvedSurface
          ? radius - math.sqrt(math.max(0, radius * radius - x * x))
          : 0.0;
      for (final y in <double>[-height / 2, height / 2]) {
        final cosX = math.cos(_rotationX);
        final sinX = math.sin(_rotationX);
        final y1 = y * cosX - z * sinX;
        final z1 = y * sinX + z * cosX;
        final cosY = math.cos(_rotationY);
        final sinY = math.sin(_rotationY);
        final x2 = x * cosY + z1 * sinY;
        final z2 = -x * sinY + z1 * cosY;
        final cosZ = math.cos(_rotationZ);
        final sinZ = math.sin(_rotationZ);
        final x3 = x2 * cosZ - y1 * sinZ;
        final y3 = x2 * sinZ + y1 * cosZ;
        final perspective = (1 / (1 + z2 * .002)).clamp(.35, 2.5).toDouble();
        result
          ..add((centerX + x3 * perspective) / stage.width)
          ..add((centerY + y3 * perspective) / stage.height);
      }
    }
    return result;
  }

  Widget _buildPlacementOverlay(BoxConstraints constraints) {
    final shortestSide = constraints.biggest.shortestSide;
    // Visual calibration: AR plane tracking can later replace this mapping
    // with depth-derived centimetres on devices that support it.
    final width = shortestSide * (.16 + ((_sizeCm - 3) / 26) * .68);
    final aspect = widget.design.aspectRatio.clamp(.2, 5.0).toDouble();
    final height = width / aspect;
    final transform = Matrix4.identity()
      ..setEntry(3, 2, .0015)
      ..rotateX(_rotationX)
      ..rotateY(_rotationY + (_curvedSurface ? .16 : 0))
      ..rotateZ(_rotationZ);

    return Center(
      child: Transform.translate(
        offset: _position,
        child: GestureDetector(
          onScaleStart: (_) => _startingRotationZ = _rotationZ,
          onScaleUpdate: (details) => setState(() {
            _position += details.focalPointDelta;
            if (details.pointerCount > 1) {
              _rotationZ = _startingRotationZ + details.rotation;
              _rotationY = (_rotationY + details.focalPointDelta.dx / 350)
                  .clamp(-.8, .8)
                  .toDouble();
              _rotationX = (_rotationX - details.focalPointDelta.dy / 350)
                  .clamp(-.8, .8)
                  .toDouble();
            }
          }),
          child: Transform(
            alignment: Alignment.center,
            transform: transform,
            child: Opacity(
              opacity: .88,
              child: ClipRRect(
                borderRadius: _curvedSurface
                    ? BorderRadius.horizontal(
                        left: Radius.circular(width * .18),
                        right: Radius.circular(width * .18))
                    : BorderRadius.zero,
                child: Image(
                  image: widget.imageProvider,
                  width: width,
                  height: height,
                  fit: BoxFit.fill,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
