import 'package:flutter/material.dart';
import '../database/database_helper.dart';
import '../database/sync_state_repository.dart';
import '../database/jobs_repository.dart';
import '../database/orders_repository.dart';
import '../database/clients_repository.dart';
import '../models/dashboard_metrics.dart';
import '../widgets/dashboard_metrics_card.dart';
import '../widgets/sync_status_card.dart';
import '../screens/orders_list_screen.dart';

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

  DashboardMetrics _metrics = DashboardMetrics.empty();
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _initializeRepositories();
    _loadMetrics();
  }

  void _initializeRepositories() {
    _dbHelper = DatabaseHelper();
    _ordersRepo = OrdersRepository(_dbHelper);
    _syncStateRepo = SyncStateRepository(_dbHelper);
    _jobsRepo = JobsRepository(_dbHelper);
    _clientsRepo = ClientsRepository(_dbHelper);
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

  void _onSyncCompleted() {
    // Reload metrics after sync
    _loadMetrics();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Doccione Mobile'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
      ),
      body: RefreshIndicator(
        onRefresh: _loadMetrics,
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
