import 'package:flutter/material.dart';
import '../database/database_helper.dart';
import '../database/server_config_repository.dart';
import '../database/sync_state_repository.dart';
import '../database/jobs_repository.dart';
import '../database/orders_repository.dart';
import '../database/clients_repository.dart';
import '../services/sync_api_client.dart';
import '../services/sync_service.dart';
import '../services/handlers/jobs_sync_handler.dart';
import '../services/handlers/orders_sync_handler.dart';
import '../services/handlers/clients_sync_handler.dart';
import '../models/sync_result.dart';

/// Widget that displays synchronization status and controls
class SyncStatusCard extends StatefulWidget {
  final String? sessionToken;
  final VoidCallback? onSyncCompleted;

  const SyncStatusCard({
    super.key,
    this.sessionToken,
    this.onSyncCompleted,
  });

  @override
  State<SyncStatusCard> createState() => _SyncStatusCardState();
}

class _SyncStatusCardState extends State<SyncStatusCard> {
  bool _isSyncing = false;
  String _syncStatus = 'Listo para sincronizar';
  SyncResult? _lastResult;
  double? _progress;

  late final SyncService _syncService;
  late final DatabaseHelper _dbHelper;

  @override
  void initState() {
    super.initState();
    _initializeSyncService();
  }

  Future<void> _initializeSyncService() async {
    _dbHelper = DatabaseHelper();
    
    final syncStateRepo = SyncStateRepository(_dbHelper);
    final jobsRepo = JobsRepository(_dbHelper);
    final ordersRepo = OrdersRepository(_dbHelper);
    final clientsRepo = ClientsRepository(_dbHelper);

    final repository = ServerConfigRepository(_dbHelper);
    final config = await repository.getConfig();

    final apiClient = SyncApiClient(
      baseUrl: config.baseUrl,
      authToken: widget.sessionToken,
      timeout: const Duration(seconds: 30),
    );

    _syncService = SyncService(
      dbHelper: _dbHelper,
      syncStateRepo: syncStateRepo,
      apiClient: apiClient,
    );

    // Register handlers
    _syncService.registerHandler('jobs', JobsSyncHandler(jobsRepo));
    _syncService.registerHandler('orders', OrdersSyncHandler(ordersRepo));
    _syncService.registerHandler('clients', ClientsSyncHandler(clientsRepo));

    // Check for incomplete sync
    final hasIncomplete = await _syncService.hasIncompleteSync();
    if (hasIncomplete && mounted) {
      setState(() {
        _syncStatus = 'Sincronización incompleta detectada';
      });
    }
  }

  Future<void> _performSync() async {
    if (_isSyncing) return;
    
    if (widget.sessionToken == null) {
      _showError('Debe vincular el dispositivo primero');
      return;
    }

    setState(() {
      _isSyncing = true;
      _syncStatus = 'Iniciando sincronización...';
      _progress = null;
    });

    try {
      final result = await _syncService.syncAll(
        limit: 100,
        onPageComplete: (pageResult) {
          if (mounted) {
            setState(() {
              _syncStatus = 'Sincronizando: ${pageResult.jobsUpdated} trabajos, '
                  '${pageResult.ordersUpdated} pedidos, '
                  '${pageResult.clientsUpdated} clientes';
            });
          }
        },
      );

      if (mounted) {
        setState(() {
          _lastResult = result;
          
          if (result.isSuccess) {
            _syncStatus = 'Sincronización completada';
          } else {
            _syncStatus = 'Error en sincronización';
          }
        });

        if (result.isSuccess) {
          _showSuccess(result);
          widget.onSyncCompleted?.call();
        } else {
          _showError(result.error ?? 'Error desconocido');
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _syncStatus = 'Error: ${e.toString()}';
        });
        _showError(e.toString());
      }
    } finally {
      if (mounted) {
        setState(() {
          _isSyncing = false;
        });
      }
    }
  }

  void _showSuccess(SyncResult result) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          'Sincronizado: ${result.jobsUpdated} trabajos, '
          '${result.ordersUpdated} pedidos, '
          '${result.clientsUpdated} clientes\n'
          'Tiempo: ${result.totalDuration.inSeconds}s',
        ),
        backgroundColor: Colors.green,
        duration: const Duration(seconds: 4),
      ),
    );
  }

  void _showError(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: Colors.red,
        duration: const Duration(seconds: 4),
      ),
    );
  }

  IconData _getSyncIcon() {
    if (_isSyncing) {
      return Icons.sync;
    } else if (_lastResult != null && _lastResult!.isSuccess) {
      return Icons.check_circle;
    } else if (_lastResult != null && _lastResult!.hasError) {
      return Icons.error;
    } else {
      return Icons.cloud_sync;
    }
  }

  Color _getSyncIconColor() {
    if (_isSyncing) {
      return Colors.blue;
    } else if (_lastResult != null && _lastResult!.isSuccess) {
      return Colors.green;
    } else if (_lastResult != null && _lastResult!.hasError) {
      return Colors.red;
    } else {
      return Colors.grey;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  _getSyncIcon(),
                  color: _getSyncIconColor(),
                ),
                const SizedBox(width: 8),
                Text(
                  'Sincronización',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(_syncStatus),
            if (_isSyncing && _progress != null) ...[
              const SizedBox(height: 8),
              LinearProgressIndicator(value: _progress),
            ] else if (_isSyncing) ...[
              const SizedBox(height: 8),
              const LinearProgressIndicator(),
            ],
            if (_lastResult != null && _lastResult!.isSuccess) ...[
              const SizedBox(height: 8),
              _buildMetrics(_lastResult!),
            ],
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                onPressed: _isSyncing ? null : _performSync,
                icon: _isSyncing
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                        ),
                      )
                    : const Icon(Icons.sync),
                label: Text(_isSyncing ? 'Sincronizando...' : 'Sincronizar ahora'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildMetrics(SyncResult result) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Última sincronización:',
          style: Theme.of(context).textTheme.labelSmall,
        ),
        const SizedBox(height: 4),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            _buildMetricItem('Trabajos', result.jobsUpdated),
            _buildMetricItem('Pedidos', result.ordersUpdated),
            _buildMetricItem('Clientes', result.clientsUpdated),
          ],
        ),
        const SizedBox(height: 8),
        Text(
          'Rendimiento:',
          style: Theme.of(context).textTheme.labelSmall,
        ),
        const SizedBox(height: 4),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            _buildTimeMetric('HTTP', result.httpDuration),
            _buildTimeMetric('Parse', result.parseDuration),
            _buildTimeMetric('BD', result.databaseDuration),
          ],
        ),
        const SizedBox(height: 4),
        Text(
          'Total: ${result.totalDuration.inMilliseconds}ms',
          style: Theme.of(context).textTheme.labelSmall?.copyWith(
                fontWeight: FontWeight.bold,
              ),
        ),
      ],
    );
  }

  Widget _buildMetricItem(String label, int count) {
    return Column(
      children: [
        Text(
          count.toString(),
          style: Theme.of(context).textTheme.titleLarge,
        ),
        Text(
          label,
          style: Theme.of(context).textTheme.labelSmall,
        ),
      ],
    );
  }

  Widget _buildTimeMetric(String label, Duration duration) {
    return Column(
      children: [
        Text(
          '${duration.inMilliseconds}ms',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        Text(
          label,
          style: Theme.of(context).textTheme.labelSmall,
        ),
      ],
    );
  }
}
