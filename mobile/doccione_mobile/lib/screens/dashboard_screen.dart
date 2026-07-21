import 'package:flutter/material.dart';
import '../database/database_helper.dart';
import '../database/server_config_repository.dart';
import '../database/sync_state_repository.dart';
import '../database/jobs_repository.dart';
import '../database/orders_repository.dart';
import '../database/clients_repository.dart';
import '../models/dashboard_metrics.dart';
import '../widgets/dashboard_metrics_card.dart';
import '../widgets/sync_status_card.dart';
import '../screens/orders_list_screen.dart';
import '../services/sync_service.dart';
import '../services/sync_api_client.dart';
import '../services/handlers/jobs_sync_handler.dart';
import '../services/handlers/orders_sync_handler.dart';
import '../services/handlers/clients_sync_handler.dart';

/// Dashboard screen showing sync status and order metrics
class DashboardScreen extends StatefulWidget {
  final String? sessionToken;

  const DashboardScreen({
    super.key,
    this.sessionToken,
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
  late final SyncService _syncService;

  DashboardMetrics _metrics = DashboardMetrics.empty();
  bool _isLoading = true;
  bool _isSyncing = false;
  bool _hasAutoSynced = false;

  @override
  void initState() {
    super.initState();
    _initializeRepositories();
    _initializeSyncService();
    _checkAndResumeSync();
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

    final apiClient = SyncApiClient(
      baseUrl: config.baseUrl,
      authToken: widget.sessionToken!,
    );

    _syncService = SyncService(
      dbHelper: _dbHelper,
      syncStateRepo: _syncStateRepo,
      apiClient: apiClient,
    );

    // Register handlers
    _syncService.registerHandler('jobs', JobsSyncHandler(_jobsRepo));
    _syncService.registerHandler('orders', OrdersSyncHandler(_ordersRepo));
    _syncService.registerHandler('clients', ClientsSyncHandler(_clientsRepo));
  }

  Future<void> _checkAndResumeSync() async {
    if (widget.sessionToken == null) {
      _loadMetrics();
      return;
    }

    // Check for incomplete sync
    final hasIncomplete = await _syncService.hasIncompleteSync();
    
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

  Future<void> _performSync({bool isAutoSync = false, bool isResume = false}) async {
    if (_isSyncing) return; // Prevent simultaneous syncs

    setState(() {
      _isSyncing = true;
    });

    try {
      final result = isResume
          ? await _syncService.continueSync()
          : await _syncService.syncAll();

      if (mounted) {
        setState(() {
          _isSyncing = false;
          _hasAutoSynced = true;
        });

        if (!result.hasError) {
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
        } else if (!isAutoSync && mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('Error en sincronización: ${result.error}'),
              backgroundColor: Colors.red,
            ),
          );
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
    }
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

      if (mounted) {
        setState(() {
          _metrics = metrics;
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

  void _onSyncCompleted() {
    // Reload metrics after sync from SyncStatusCard
    _loadMetrics();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Doccione Mobile'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
        actions: [
          if (_isSyncing)
            const Padding(
              padding: EdgeInsets.all(16),
              child: SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
            ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _onRefresh,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            // Sync Status Card
            SyncStatusCard(
              sessionToken: widget.sessionToken,
              onSyncCompleted: _onSyncCompleted,
            ),
            const SizedBox(height: 16),

            // Dashboard Metrics
            if (_isLoading)
              const Center(
                child: Padding(
                  padding: EdgeInsets.all(32),
                  child: CircularProgressIndicator(),
                ),
              )
            else
              DashboardMetricsCard(metrics: _metrics),
            
            const SizedBox(height: 16),

            // Action Buttons
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                onPressed: () {
                  Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (context) => const OrdersListScreen(),
                    ),
                  );
                },
                icon: const Icon(Icons.list),
                label: const Text('Ver todos los pedidos'),
                style: ElevatedButton.styleFrom(
                  padding: const EdgeInsets.all(16),
                ),
              ),
            ),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: () {
                  // TODO: Navigate to search
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('Búsqueda - Próximamente'),
                    ),
                  );
                },
                icon: const Icon(Icons.search),
                label: const Text('Buscar pedidos'),
                style: OutlinedButton.styleFrom(
                  padding: const EdgeInsets.all(16),
                ),
              ),
            ),

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
                            color: _metrics.hasError ? Colors.red : Colors.grey[600],
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
}
