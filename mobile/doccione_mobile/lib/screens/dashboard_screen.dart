import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../config/app_identity.dart';
import '../database/database_helper.dart';
import '../database/server_config_repository.dart';
import '../database/sync_state_repository.dart';
import '../database/jobs_repository.dart';
import '../database/orders_repository.dart';
import '../database/clients_repository.dart';
import '../database/pending_orders_repository.dart';
import '../database/offline_catalog_repository.dart';
import '../models/dashboard_metrics.dart';
import '../models/order_with_details.dart';
import '../models/mobile_runtime_config.dart';
import '../widgets/sales_timeline_card.dart';
import '../screens/orders_list_screen.dart';
import '../screens/products_catalog_screen.dart';
import '../screens/fotocopia_quote_screen.dart';
import '../screens/sticker_order_screen.dart';
import '../screens/visit_map_screen.dart';
import '../screens/clients_screen.dart';
import '../services/sync_service.dart';
import '../services/sync_api_client.dart';
import '../services/stage_service.dart';
import '../services/catalog_api_client.dart';
import '../services/offline_orders_service.dart';
import '../services/session_scope.dart';
import '../services/handlers/jobs_sync_handler.dart';
import '../services/handlers/orders_sync_handler.dart';
import '../services/handlers/clients_sync_handler.dart';
import '../theme/doccione_palette.dart';

/// Seller dashboard showing sync status and the progress of their sales.
class DashboardScreen extends StatefulWidget {
  final String? sessionToken;
  final Future<void> Function()? onLogout;
  final Future<void> Function()? onSessionExpired;

  const DashboardScreen({
    super.key,
    this.sessionToken,
    this.onLogout,
    this.onSessionExpired,
  });

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  late final DatabaseHelper _dbHelper;
  late final OrdersRepository _ordersRepo;
  late final SyncStateRepository _syncStateRepo;
  late final JobsRepository _jobsRepo;
  late final ClientsRepository _clientsRepo;
  SyncService? _syncService;

  DashboardMetrics _metrics = DashboardMetrics.empty();
  List<OrderWithDetails> _sales = [];
  bool _isLoading = true;
  bool _isSyncing = false;
  bool _isUploadingPendingOrders = false;
  bool _isDownloadingDesigns = false;
  bool _hasAutoSynced = false;
  MobileRuntimeConfig _runtimeConfig = MobileRuntimeConfig.defaults;

  @override
  void initState() {
    super.initState();
    _initializeRepositories();
    _initialize();
  }

  @override
  void dispose() {
    _syncService?.close();
    super.dispose();
  }

  Future<void> _initialize() async {
    // La caché debe aparecer aunque Studio o la red no estén disponibles.
    await _loadMetrics();
    await _initializeSyncService();
    if (!mounted) return;
    await _checkAndResumeSync();
  }

  void _initializeRepositories() {
    _dbHelper = DatabaseHelper();
    _ordersRepo = OrdersRepository(_dbHelper);
    _syncStateRepo = SyncStateRepository(_dbHelper);
    _jobsRepo = JobsRepository(_dbHelper);
    _clientsRepo = ClientsRepository(_dbHelper);
  }

  Future<void> _initializeSyncService() async {
    if (widget.sessionToken == null) return;

    final repository = ServerConfigRepository(_dbHelper);
    final config = await repository.getConfig();
    if (!mounted) return;

    final apiClient = SyncApiClient(
      baseUrl: config.baseUrl,
      authToken: widget.sessionToken!,
    );

    try {
      final runtimeConfig = await apiClient.getRuntimeConfig();
      MobileRuntimeConfigStore.apply(runtimeConfig);
      StageService.applyRuntimeConfig(runtimeConfig);
      if (mounted) {
        setState(() => _runtimeConfig = runtimeConfig);
      }
    } catch (error) {
      // La configuración remota nunca debe impedir sincronizar o consultar.
      debugPrint('No se pudo cargar la configuración móvil: $error');
      MobileRuntimeConfigStore.apply(MobileRuntimeConfig.defaults);
      StageService.resetRuntimeConfig();
    }

    final syncService = SyncService(
      dbHelper: _dbHelper,
      syncStateRepo: _syncStateRepo,
      apiClient: apiClient,
    );

    // Register handlers
    syncService.registerHandler('jobs', JobsSyncHandler(_jobsRepo));
    syncService.registerHandler('orders', OrdersSyncHandler(_ordersRepo));
    syncService.registerHandler('clients', ClientsSyncHandler(_clientsRepo));
    _syncService = syncService;
  }

  Future<void> _checkAndResumeSync() async {
    if (widget.sessionToken == null) {
      _loadMetrics();
      return;
    }

    // Check for incomplete sync
    final syncService = _syncService;
    if (syncService == null) {
      await _loadMetrics();
      return;
    }
    final hasIncomplete = await syncService.hasIncompleteSync();

    if (hasIncomplete && !_hasAutoSynced) {
      // Resume incomplete sync
      await _performSync(isAutoSync: true, isResume: true);
    } else if (!_hasAutoSynced) {
      // Auto-sync on startup with debounce
      await Future.delayed(const Duration(milliseconds: 500));
      if (mounted && !_isSyncing) {
        await _performSync(isAutoSync: true);
      }
    } else {
      _loadMetrics();
    }
  }

  Future<void> _performSync(
      {bool isAutoSync = false, bool isResume = false}) async {
    if (_isSyncing) return; // Prevent simultaneous syncs

    setState(() {
      _isSyncing = true;
    });

    try {
      final syncService = _syncService;
      if (syncService == null) {
        throw StateError('El servicio de sincronización no está disponible');
      }
      final result = isResume
          ? await syncService.continueSync()
          : await syncService.syncAll();
      await _sendPendingOrders();

      if (mounted) {
        setState(() {
          _isSyncing = false;
          _hasAutoSynced = true;
        });

        if (_isUnauthorized(result.error)) {
          await widget.onSessionExpired?.call();
          return;
        } else if (!result.hasError) {
          await _loadMetrics();

          if (!isAutoSync && mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text(
                  'Sincronización completada: ${result.jobsUpdated} trabajos, ${result.ordersUpdated} pedidos, ${result.clientsUpdated} clientes',
                ),
                backgroundColor: Colors.green,
              ),
            );
          }
        } else {
          await _loadMetrics();
          if (!isAutoSync && mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text('Error en sincronización: ${result.error}'),
                backgroundColor: Colors.red,
              ),
            );
          }
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isSyncing = false;
        });

        if (!isAutoSync) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('Error en sincronización: $e'),
              backgroundColor: Colors.red,
            ),
          );
        }
      }
      await _loadMetrics();
    }
  }

  bool _isUnauthorized(String? error) {
    if (error == null) return false;
    final normalized = error.toLowerCase();
    return normalized.contains('syncapiexception(401)') ||
        normalized.contains('invalid or expired session token') ||
        normalized.contains('unauthorized');
  }

  Future<void> _loadMetrics() async {
    setState(() {
      _isLoading = true;
    });

    try {
      final metrics = await _ordersRepo.getDashboardMetrics(
        _syncStateRepo,
        _jobsRepo,
        _clientsRepo,
      );
      final syncedSales = await _ordersRepo.searchOrders(
        showArchived: false,
        sortBy: 'order_date',
        sortDescending: true,
        limit: 20,
      );
      final activeSales = syncedSales.where((sale) {
        final status = (sale.order.status ?? '').trim().toLowerCase();
        return status != 'entregado' &&
            status != 'delivered' &&
            status != 'cancelado' &&
            status != 'cancelled';
      });
      final closedSales = syncedSales.where((sale) {
        final status = (sale.order.status ?? '').trim().toLowerCase();
        return status == 'entregado' ||
            status == 'delivered' ||
            status == 'cancelado' ||
            status == 'cancelled';
      });

      if (mounted) {
        setState(() {
          _metrics = metrics;
          _sales = [...activeSales, ...closedSales];
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error al cargar métricas: $e'),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  Future<void> _onRefresh() async {
    if (widget.sessionToken != null) {
      await _performSync();
    } else {
      await _loadMetrics();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Doccione'),
        actions: [
          IconButton(
            key: const Key('dashboard-sync-button'),
            icon: _isSyncing
                ? const SizedBox.square(
                    dimension: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.refresh),
            tooltip: _isSyncing ? 'Sincronizando...' : 'Sincronizar',
            onPressed: _isSyncing || widget.sessionToken == null
                ? null
                : () => _performSync(),
          ),
          IconButton(
            icon: _isDownloadingDesigns
                ? const SizedBox.square(
                    dimension: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.download_outlined),
            tooltip: _isDownloadingDesigns
                ? 'Descargando diseños...'
                : 'Descargar nuevos diseños',
            onPressed: widget.sessionToken == null || _isDownloadingDesigns
                ? null
                : _downloadDesignUpdates,
          ),
          if (_runtimeConfig.featureEnabled('design_catalog'))
            IconButton(
              icon: const Icon(Icons.collections_bookmark_outlined),
              tooltip: 'Catálogo de diseños',
              onPressed: widget.sessionToken == null ? null : _openCatalog,
            ),
          if (_runtimeConfig.featureEnabled('product_catalog'))
            IconButton(
              icon: const Icon(Icons.inventory_2_outlined),
              tooltip: 'Productos de Studio',
              onPressed: widget.sessionToken == null ? null : _openProducts,
            ),
          if (widget.onLogout != null)
            IconButton(
              key: const Key('dashboard-logout-button'),
              icon: const Icon(Icons.logout),
              tooltip: 'Cerrar sesión',
              onPressed: () async {
                final confirmed = await showDialog<bool>(
                  context: context,
                  builder: (context) => AlertDialog(
                    title: const Text('Cerrar sesión'),
                    content: const Text(
                      'Este dispositivo quedará desvinculado y necesitará '
                      'usuario, contraseña y un nuevo código para volver a entrar.',
                    ),
                    actions: [
                      TextButton(
                        onPressed: () => Navigator.pop(context, false),
                        child: const Text('Cancelar'),
                      ),
                      FilledButton(
                        onPressed: () => Navigator.pop(context, true),
                        child: const Text('Cerrar sesión'),
                      ),
                    ],
                  ),
                );
                if (confirmed == true) {
                  await widget.onLogout!();
                }
              },
            ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _onRefresh,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 28),
          children: [
            _buildWelcomeHeader(context),
            if (_runtimeConfig.requiresUpgrade(AppIdentity.version)) ...[
              const SizedBox(height: 12),
              _buildRuntimeNotice(
                context,
                icon: Icons.system_update_alt,
                title: 'Actualización necesaria',
                message:
                    'Esta versión ya no es compatible con todas las funciones de Studio.',
                color: Theme.of(context).colorScheme.error,
                actionLabel:
                    _runtimeConfig.updateUrl.isNotEmpty ? 'Actualizar' : null,
                onAction: _runtimeConfig.updateUrl.isNotEmpty
                    ? () => launchUrl(Uri.parse(_runtimeConfig.updateUrl))
                    : null,
              ),
            ] else if (_runtimeConfig
                .recommendsUpgrade(AppIdentity.version)) ...[
              const SizedBox(height: 12),
              _buildRuntimeNotice(
                context,
                icon: Icons.system_update_outlined,
                title: 'Hay una versión más reciente',
                message:
                    'Actualizá cuando puedas para recibir todas las mejoras.',
                color: DoccionePalette.info,
                actionLabel:
                    _runtimeConfig.updateUrl.isNotEmpty ? 'Actualizar' : null,
                onAction: _runtimeConfig.updateUrl.isNotEmpty
                    ? () => launchUrl(Uri.parse(_runtimeConfig.updateUrl))
                    : null,
              ),
            ],
            if (_runtimeConfig.announcementEnabled &&
                _runtimeConfig.announcementMessage.isNotEmpty) ...[
              const SizedBox(height: 12),
              _buildRuntimeNotice(
                context,
                icon: Icons.campaign_outlined,
                title: _runtimeConfig.announcementTitle.isEmpty
                    ? 'Novedad'
                    : _runtimeConfig.announcementTitle,
                message: _runtimeConfig.announcementMessage,
                color: DoccionePalette.info,
              ),
            ],
            if (_runtimeConfig.maintenanceEnabled) ...[
              const SizedBox(height: 12),
              _buildRuntimeNotice(
                context,
                icon: Icons.build_circle_outlined,
                title: 'Modo mantenimiento',
                message: _runtimeConfig.maintenanceMessage.isEmpty
                    ? 'Las operaciones están temporalmente limitadas.'
                    : _runtimeConfig.maintenanceMessage,
                color: DoccionePalette.production,
              ),
            ],
            const SizedBox(height: 20),
            // Read-only order progress for the seller's own synced sales.
            if (_isLoading)
              const Center(
                child: Padding(
                  padding: EdgeInsets.all(32),
                  child: CircularProgressIndicator(),
                ),
              )
            else
              SalesTimelineCard(
                sales: _sales,
                onViewAll: _openOrders,
              ),

            const SizedBox(height: 20),
            Text('Accesos rápidos',
                style: Theme.of(context)
                    .textTheme
                    .titleMedium
                    ?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                    child: _QuickAction(
                        icon: Icons.receipt_long_outlined,
                        label: 'Mis ventas',
                        color: DoccionePalette.wine,
                        onTap: _openOrders)),
                const SizedBox(width: 12),
                Expanded(
                    child: _QuickAction(
                        icon: Icons.people_alt_outlined,
                        label: 'Clientes',
                        color: DoccionePalette.info,
                        onTap: _openClients)),
              ],
            ),
            const SizedBox(height: 12),
            _QuickAction(
                icon: Icons.location_on_outlined,
                label: 'Mapa de visitas',
                color: DoccionePalette.production,
                onTap: _openVisits),
            const SizedBox(height: 12),
            _QuickAction(
                icon: Icons.calculate_outlined,
                label: 'Presupuestar fotocopias',
                color: DoccionePalette.info,
                onTap: _openFotocopiaQuote),
            const SizedBox(height: 12),
            _QuickAction(
                icon: _isUploadingPendingOrders
                    ? Icons.hourglass_top_rounded
                    : Icons.cloud_upload_outlined,
                label: _isUploadingPendingOrders
                    ? 'Cargando pedidos...'
                    : 'Cargar pedidos a DoccioneStudio',
                color: DoccionePalette.info,
                onTap: _isUploadingPendingOrders || widget.sessionToken == null
                    ? null
                    : _uploadPendingOrders),
            const SizedBox(height: 12),
            if (_runtimeConfig.featureEnabled('product_catalog')) ...[
              _QuickAction(
                  icon: Icons.note_add_outlined,
                  label: 'Nuevo pedido',
                  color: DoccionePalette.info,
                  onTap:
                      _runtimeConfig.maintenanceEnabled ? null : _openProducts),
              const SizedBox(height: 12),
            ],
            if (_runtimeConfig.featureEnabled('sticker_orders') ||
                _runtimeConfig.featureEnabled('design_catalog')) ...[
              _QuickAction(
                  icon: Icons.auto_awesome_mosaic_outlined,
                  label: 'Creador de stickers',
                  color: DoccionePalette.production,
                  onTap: _runtimeConfig.maintenanceEnabled
                      ? null
                      : _openStickerCreator),
              const SizedBox(height: 12),
            ],

            // Last Sync Info
            if (_metrics.hasBeenSynced) ...[
              const SizedBox(height: 24),
              Center(
                child: Column(
                  children: [
                    Icon(
                      _metrics.hasError ? Icons.error : Icons.check_circle,
                      color: _metrics.hasError ? Colors.red : Colors.green,
                      size: 20,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      _metrics.hasError
                          ? 'Error en última sincronización'
                          : 'Sincronizado ${_metrics.lastSyncFormatted}',
                      style: Theme.of(context).textTheme.labelSmall?.copyWith(
                            color: _metrics.hasError
                                ? Colors.red
                                : DoccionePalette.muted,
                          ),
                    ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  void _openOrders() {
    Navigator.push(
        context,
        MaterialPageRoute(
            builder: (_) =>
                OrdersListScreen(sessionToken: widget.sessionToken)));
  }

  Future<void> _openCatalog() async {
    final token = widget.sessionToken;
    if (token == null) return;
    final config = await ServerConfigRepository(_dbHelper).getConfig();
    if (!mounted) return;
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => StickerOrderScreen(
          baseUrl: config.baseUrl,
          sessionToken: token,
          // El catálogo de diseños abre el creador de stickers. Los
          // productos de Studio se crean desde _openProducts.
          stickerCreatorOnly: true,
          showCatalogDesigns: true,
        ),
      ),
    );
  }

  Future<void> _openProducts() async {
    final token = widget.sessionToken;
    if (token == null) return;
    final config = await ServerConfigRepository(_dbHelper).getConfig();
    if (!mounted) return;
    await Navigator.push(
        context,
        MaterialPageRoute(
            builder: (_) => ProductsCatalogScreen(
                baseUrl: config.baseUrl, sessionToken: token)));
  }

  Future<void> _openFotocopiaQuote() async {
    final token = widget.sessionToken;
    if (token == null) return;
    final config = await ServerConfigRepository(_dbHelper).getConfig();
    if (!mounted) return;
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => FotocopiaQuoteScreen(
          baseUrl: config.baseUrl,
          sessionToken: token,
        ),
      ),
    );
  }

  Future<void> _openStickerCreator() async {
    final token = widget.sessionToken;
    if (token == null) return;
    final config = await ServerConfigRepository(_dbHelper).getConfig();
    if (!mounted) return;
    await Navigator.push(
        context,
        MaterialPageRoute(
            builder: (_) => StickerOrderScreen(
                baseUrl: config.baseUrl,
                sessionToken: token,
                stickerCreatorOnly: true)));
  }

  Widget _buildWelcomeHeader(BuildContext context) {
    final hour = DateTime.now().hour;
    final greeting = hour < 12
        ? 'Buen día'
        : hour < 20
            ? 'Buenas tardes'
            : 'Buenas noches';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(greeting,
            style: Theme.of(context)
                .textTheme
                .titleLarge
                ?.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(height: 4),
        Text('Seguí el estado de los pedidos de tus ventas.',
            style: Theme.of(context)
                .textTheme
                .bodyMedium
                ?.copyWith(color: DoccionePalette.muted)),
      ],
    );
  }

  Future<int> _sendPendingOrders() async {
    final token = widget.sessionToken;
    if (token == null) return 0;
    final config = await ServerConfigRepository(_dbHelper).getConfig();
    final api = CatalogApiClient(baseUrl: config.baseUrl, authToken: token);
    try {
      return await OfflineOrdersService(PendingOrdersRepository(_dbHelper), api)
          .sendPending();
    } finally {
      api.close();
    }
  }

  Future<void> _downloadDesignUpdates() async {
    final token = widget.sessionToken;
    if (token == null || _isDownloadingDesigns) return;
    setState(() => _isDownloadingDesigns = true);
    final config = await ServerConfigRepository(_dbHelper).getConfig();
    final api = CatalogApiClient(baseUrl: config.baseUrl, authToken: token);
    final catalog = OfflineCatalogRepository(_dbHelper);
    try {
      final designs = await api.getDesigns();
      for (final design in designs) {
        if (design.previewUrl.isEmpty) continue;
        try {
          final url = design.previewUrl.startsWith('http')
              ? design.previewUrl
              : '${config.baseUrl}${design.previewUrl}';
          await catalog.cachePreview(design, await api.download(url));
        } catch (_) {
          // Un diseño sin vista previa no bloquea la actualización.
        }
      }
      // La base se actualiza al final: las nuevas entradas quedan disponibles
      // junto con su archivo de vista previa ya guardado en el teléfono.
      await catalog.saveDesigns(designs);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('${designs.length} diseños actualizados.')),
        );
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('No se pudieron descargar diseños: $error')),
        );
      }
    } finally {
      api.close();
      if (mounted) setState(() => _isDownloadingDesigns = false);
    }
  }

  Future<void> _uploadPendingOrders() async {
    final pending = PendingOrdersRepository(_dbHelper);
    final scope = await SessionScope.current();
    if (scope == null) return;
    final before = await pending.count(ownerScope: scope);
    if (before == 0) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('No hay pedidos pendientes para cargar.'),
        ));
      }
      return;
    }

    setState(() => _isUploadingPendingOrders = true);
    try {
      final sent = await _sendPendingOrders();
      final remaining = await pending.count(ownerScope: scope);
      if (!mounted) return;
      final message = remaining == 0
          ? '$sent pedido${sent == 1 ? '' : 's'} cargado${sent == 1 ? '' : 's'} a DoccioneStudio.'
          : 'Se cargaron $sent de $before pedidos. Quedan $remaining pendientes; verificá la conexión.';
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(message),
        backgroundColor: remaining == 0 ? Colors.green : Colors.orange,
      ));
      if (sent > 0) await _performSync(isAutoSync: true);
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('No se pudieron cargar los pedidos: $error'),
          backgroundColor: Colors.red,
        ));
      }
    } finally {
      if (mounted) setState(() => _isUploadingPendingOrders = false);
    }
  }

  Future<void> _openVisits() async {
    final config = await ServerConfigRepository(_dbHelper).getConfig();
    if (!mounted) return;
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => VisitMapScreen(
          baseUrl: config.baseUrl,
          sessionToken: widget.sessionToken,
        ),
      ),
    );
  }

  Future<void> _openClients() async {
    await Navigator.push(
        context, MaterialPageRoute(builder: (_) => const ClientsScreen()));
    if (mounted) await _loadMetrics();
  }

  Widget _buildRuntimeNotice(
    BuildContext context, {
    required IconData icon,
    required String title,
    required String message,
    required Color color,
    String? actionLabel,
    Future<bool> Function()? onAction,
  }) =>
      Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: color.withValues(alpha: .10),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: color.withValues(alpha: .35)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: color),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title,
                      style: const TextStyle(fontWeight: FontWeight.w700)),
                  const SizedBox(height: 3),
                  Text(message),
                  if (actionLabel != null && onAction != null)
                    Align(
                      alignment: Alignment.centerRight,
                      child: TextButton(
                        onPressed: () async => onAction(),
                        child: Text(actionLabel),
                      ),
                    ),
                ],
              ),
            ),
          ],
        ),
      );
}

class _QuickAction extends StatelessWidget {
  const _QuickAction(
      {required this.icon,
      required this.label,
      required this.color,
      this.onTap});
  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => Material(
        color: onTap == null
            ? DoccionePalette.surface.withValues(alpha: .55)
            : DoccionePalette.surface,
        borderRadius: BorderRadius.circular(16),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(16),
          child: Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: DoccionePalette.border)),
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              CircleAvatar(
                  backgroundColor: color.withValues(alpha: .12),
                  foregroundColor: color,
                  child: Icon(icon)),
              const SizedBox(height: 14),
              Text(onTap == null ? '$label · No disponible' : label,
                  style: Theme.of(context)
                      .textTheme
                      .labelLarge
                      ?.copyWith(fontWeight: FontWeight.w700)),
            ]),
          ),
        ),
      );
}
