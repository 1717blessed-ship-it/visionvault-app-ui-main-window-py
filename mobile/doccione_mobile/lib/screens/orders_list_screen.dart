import 'dart:async';

import 'package:flutter/material.dart';
import 'package:doccione_mobile/database/database_helper.dart';
import 'package:doccione_mobile/database/orders_repository.dart';
import 'package:doccione_mobile/database/server_config_repository.dart';
import 'package:doccione_mobile/models/order_with_details.dart';
import 'package:doccione_mobile/widgets/order_card.dart';
import 'package:doccione_mobile/screens/order_detail_screen.dart';
import 'package:doccione_mobile/services/quick_edit_api_client.dart';
import 'package:doccione_mobile/theme/doccione_palette.dart';
import 'package:url_launcher/url_launcher.dart';
import 'unified_order_creation_screen.dart';

class OrdersListScreen extends StatefulWidget {
  final String? initialStatus;
  final String? sessionToken;

  const OrdersListScreen({
    super.key,
    this.initialStatus,
    this.sessionToken,
  });

  @override
  State<OrdersListScreen> createState() => _OrdersListScreenState();
}

class _OrdersListScreenState extends State<OrdersListScreen> {
  final DatabaseHelper _dbHelper = DatabaseHelper();
  late final OrdersRepository _ordersRepo;
  final TextEditingController _searchController = TextEditingController();
  QuickEditApiClient? _quickEditClient;
  Timer? _searchDebounce;
  int _loadRequest = 0;

  List<OrderWithDetails> _orders = [];
  bool _isLoading = true;
  String? _selectedStatus;
  String? _selectedPriority;
  bool _showArchived = false;
  String _sortBy = 'order_date';
  bool _sortDescending = true;

  // Status filter options
  final List<Map<String, dynamic>> _statusFilters = [
    {'value': null, 'label': 'Todos', 'icon': Icons.list},
    {'value': 'pending', 'label': 'Pendientes', 'icon': Icons.schedule},
    {'value': 'production', 'label': 'Producción', 'icon': Icons.build},
    {'value': 'completed', 'label': 'Completados', 'icon': Icons.check_circle},
    {'value': 'delivered', 'label': 'Entregados', 'icon': Icons.local_shipping},
  ];

  @override
  void initState() {
    super.initState();
    _ordersRepo = OrdersRepository(_dbHelper);
    _selectedStatus = widget.initialStatus;
    _initQuickEditClient();
    _loadOrders();
  }

  Future<void> _initQuickEditClient() async {
    if (widget.sessionToken == null) return;
    final repo = ServerConfigRepository(_dbHelper);
    final config = await repo.getConfig();
    if (mounted) {
      setState(() {
        _quickEditClient = QuickEditApiClient(
          baseUrl: config.baseUrl,
          authToken: widget.sessionToken,
        );
      });
    }
  }

  @override
  void dispose() {
    _loadRequest++;
    _searchDebounce?.cancel();
    _searchController.dispose();
    _quickEditClient?.close();
    super.dispose();
  }

  Future<void> _loadOrders() async {
    if (!mounted) return;
    final request = ++_loadRequest;

    setState(() {
      _isLoading = true;
    });

    try {
      final searchQuery = _searchController.text.trim();

      final orders = await _ordersRepo.searchOrders(
        searchQuery: searchQuery.isEmpty ? null : searchQuery,
        status: _selectedStatus,
        priority: _selectedPriority,
        showArchived: _showArchived,
        sortBy: _sortBy,
        sortDescending: _sortDescending,
        limit: 100,
      );

      if (!mounted || request != _loadRequest) return;
      setState(() {
        _orders = orders;
        _isLoading = false;
      });
    } catch (e) {
      if (!mounted || request != _loadRequest) return;
      setState(() {
        _isLoading = false;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Error al cargar pedidos: $e')),
      );
    }
  }

  Future<void> _onRefresh() async {
    // Just reload orders - sync is handled by DashboardScreen
    await _loadOrders();
  }

  void _onStatusFilterChanged(String? status) {
    setState(() {
      _selectedStatus = status;
    });
    _loadOrders();
  }

  void _showFiltersBottomSheet() {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (context) => _buildFiltersSheet(),
    );
  }

  void _showSortBottomSheet() {
    showModalBottomSheet(
      context: context,
      builder: (context) => _buildSortSheet(),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Pedidos'),
        actions: [
          IconButton(
              icon: const Icon(Icons.edit_note),
              tooltip: 'Borradores multi-trabajo',
              onPressed: widget.sessionToken == null
                  ? null
                  : () async {
                      final config =
                          await ServerConfigRepository(_dbHelper).getConfig();
                      if (!context.mounted) return;
                      await Navigator.push(
                          context,
                          MaterialPageRoute(
                              builder: (_) => UnifiedOrderCreationScreen(
                                  baseUrl: config.baseUrl,
                                  sessionToken: widget.sessionToken!)));
                    }),
          // Sort button
          IconButton(
            icon: const Icon(Icons.sort),
            onPressed: _showSortBottomSheet,
            tooltip: 'Ordenar',
          ),
          // Filters button
          IconButton(
            icon: Badge(
              isLabelVisible: _selectedPriority != null || _showArchived,
              child: const Icon(Icons.filter_list),
            ),
            onPressed: _showFiltersBottomSheet,
            tooltip: 'Filtros',
          ),
        ],
      ),
      body: Column(
        children: [
          // Search bar
          Padding(
            padding: const EdgeInsets.all(12),
            child: TextField(
              controller: _searchController,
              decoration: InputDecoration(
                hintText: 'Buscar por pedido, cliente, WhatsApp, material...',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: _searchController.text.isNotEmpty
                    ? IconButton(
                        icon: const Icon(Icons.clear),
                        onPressed: () {
                          _searchController.clear();
                          _loadOrders();
                        },
                      )
                    : null,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
                contentPadding: const EdgeInsets.symmetric(vertical: 12),
              ),
              onChanged: (_) {
                setState(() {});
                _searchDebounce?.cancel();
                _searchDebounce = Timer(
                  const Duration(milliseconds: 500),
                  _loadOrders,
                );
              },
            ),
          ),
          // Status filter chips
          Container(
            height: 54,
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: ListView.builder(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12),
              itemCount: _statusFilters.length,
              itemBuilder: (context, index) {
                final filter = _statusFilters[index];
                final isSelected = _selectedStatus == filter['value'];

                return Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4),
                  child: FilterChip(
                    selected: isSelected,
                    label: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          filter['icon'] as IconData,
                          size: 16,
                          color: isSelected
                              ? Theme.of(context).colorScheme.onPrimary
                              : DoccionePalette.muted,
                        ),
                        const SizedBox(width: 4),
                        Text(filter['label'] as String),
                      ],
                    ),
                    onSelected: (selected) {
                      _onStatusFilterChanged(
                          selected ? filter['value'] as String? : null);
                    },
                    selectedColor: Theme.of(context).colorScheme.primary,
                    checkmarkColor: Theme.of(context).colorScheme.onPrimary,
                    labelStyle: TextStyle(
                      color: isSelected
                          ? Theme.of(context).colorScheme.onPrimary
                          : DoccionePalette.muted,
                      fontWeight:
                          isSelected ? FontWeight.w600 : FontWeight.normal,
                    ),
                  ),
                );
              },
            ),
          ),
          const Divider(height: 1),
          // Orders list
          Expanded(
            child: _isLoading
                ? const Center(child: CircularProgressIndicator())
                : _orders.isEmpty
                    ? _buildEmptyState()
                    : RefreshIndicator(
                        onRefresh: _onRefresh,
                        child: ListView.builder(
                          itemCount: _orders.length,
                          itemBuilder: (context, index) {
                            final orderDetails = _orders[index];
                            return OrderCard(
                              orderDetails: orderDetails,
                              onTap: () {
                                Navigator.push(
                                  context,
                                  MaterialPageRoute(
                                    builder: (context) => OrderDetailScreen(
                                      orderDetails: orderDetails,
                                      onContactWhatsApp: () =>
                                          _contactWhatsApp(orderDetails.order),
                                      apiClient: _quickEditClient,
                                      onRefresh: () => _loadOrders(),
                                      onDeleteLocal: (orderId) async {
                                        await _ordersRepo
                                            .deleteOrderLocally(orderId);
                                        await _loadOrders();
                                      },
                                    ),
                                  ),
                                );
                              },
                            );
                          },
                        ),
                      ),
          ),
        ],
      ),
    );
  }

  Future<void> _contactWhatsApp(order) async {
    final phone = (order.whatsapp ?? '').replaceAll(RegExp(r'[^0-9]'), '');
    if (phone.isEmpty) return;
    final orderLabel = order.orderNumber ?? order.id;
    final message =
        'Hola ${order.client ?? ''}, te escribimos desde Doccione Studio por tu pedido #$orderLabel. Estado actual: ${order.status ?? 'Pendiente'}.';
    final url = Uri.https('wa.me', '/$phone', {'text': message});
    if (!await launchUrl(url, mode: LaunchMode.externalApplication) &&
        mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('No se pudo abrir WhatsApp.')));
    }
  }

  Widget _buildEmptyState() {
    final hasFilters = _selectedStatus != null ||
        _selectedPriority != null ||
        _searchController.text.isNotEmpty;

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              hasFilters ? Icons.search_off : Icons.inbox_outlined,
              size: 64,
              color: DoccionePalette.subtle,
            ),
            const SizedBox(height: 16),
            Text(
              hasFilters ? 'No se encontraron pedidos' : 'No hay pedidos',
              style: const TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w600,
                color: DoccionePalette.ink,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              hasFilters
                  ? 'Intenta cambiar los filtros o la búsqueda'
                  : 'Sincroniza para obtener los últimos datos',
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontSize: 14,
                color: DoccionePalette.muted,
              ),
            ),
            if (hasFilters) ...[
              const SizedBox(height: 16),
              OutlinedButton.icon(
                onPressed: () {
                  setState(() {
                    _searchController.clear();
                    _selectedStatus = null;
                    _selectedPriority = null;
                    _showArchived = false;
                  });
                  _loadOrders();
                },
                icon: const Icon(Icons.clear_all),
                label: const Text('Limpiar filtros'),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildFiltersSheet() {
    String? tempPriority = _selectedPriority;
    bool tempShowArchived = _showArchived;

    return StatefulBuilder(
      builder: (context, setModalState) {
        return Padding(
          padding: EdgeInsets.only(
            bottom: MediaQuery.of(context).viewInsets.bottom,
            left: 16,
            right: 16,
            top: 16,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    'Filtros',
                    style: Theme.of(context).textTheme.titleLarge?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                  ),
                  TextButton(
                    onPressed: () {
                      setModalState(() {
                        tempPriority = null;
                        tempShowArchived = false;
                      });
                    },
                    child: const Text('Limpiar'),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              // Priority filter
              Text(
                'Prioridad',
                style: Theme.of(context).textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                children: [
                  FilterChip(
                    label: const Text('Todas'),
                    selected: tempPriority == null,
                    onSelected: (selected) {
                      setModalState(() {
                        tempPriority = null;
                      });
                    },
                  ),
                  FilterChip(
                    label: const Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.bolt, size: 16, color: Colors.red),
                        SizedBox(width: 4),
                        Text('Urgente'),
                      ],
                    ),
                    selected: tempPriority == '4',
                    onSelected: (selected) {
                      setModalState(() {
                        tempPriority = selected ? '4' : null;
                      });
                    },
                  ),
                  FilterChip(
                    label: const Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.priority_high, size: 16, color: Colors.red),
                        SizedBox(width: 4),
                        Text('Alta'),
                      ],
                    ),
                    selected: tempPriority == '3',
                    onSelected: (selected) {
                      setModalState(() {
                        tempPriority = selected ? '3' : null;
                      });
                    },
                  ),
                  FilterChip(
                    label: const Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.remove, size: 16, color: Colors.orange),
                        SizedBox(width: 4),
                        Text('Media'),
                      ],
                    ),
                    selected: tempPriority == '2',
                    onSelected: (selected) {
                      setModalState(() {
                        tempPriority = selected ? '2' : null;
                      });
                    },
                  ),
                  FilterChip(
                    label: const Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.arrow_downward,
                            size: 16, color: Colors.blue),
                        SizedBox(width: 4),
                        Text('Baja'),
                      ],
                    ),
                    selected: tempPriority == '1',
                    onSelected: (selected) {
                      setModalState(() {
                        tempPriority = selected ? '1' : null;
                      });
                    },
                  ),
                ],
              ),
              const SizedBox(height: 16),
              // Show archived switch
              SwitchListTile(
                title: const Text('Mostrar archivados'),
                subtitle: Text(
                  tempShowArchived
                      ? 'Incluyendo pedidos archivados'
                      : 'Ocultando pedidos archivados',
                  style: const TextStyle(
                    fontSize: 12,
                    color: DoccionePalette.muted,
                  ),
                ),
                value: tempShowArchived,
                onChanged: (value) {
                  setModalState(() {
                    tempShowArchived = value;
                  });
                },
              ),
              const SizedBox(height: 16),
              // Apply button
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: () {
                    setState(() {
                      _selectedPriority = tempPriority;
                      _showArchived = tempShowArchived;
                    });
                    Navigator.pop(context);
                    _loadOrders();
                  },
                  child: const Text('Aplicar filtros'),
                ),
              ),
              const SizedBox(height: 16),
            ],
          ),
        );
      },
    );
  }

  Widget _buildSortSheet() {
    final sortOptions = [
      {
        'value': 'order_date',
        'label': 'Fecha del pedido',
        'icon': Icons.calendar_today
      },
      {
        'value': 'delivery_date',
        'label': 'Fecha de entrega',
        'icon': Icons.event
      },
      {'value': 'priority', 'label': 'Prioridad', 'icon': Icons.flag},
      {'value': 'client', 'label': 'Cliente', 'icon': Icons.person},
    ];

    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Ordenar por',
            style: Theme.of(context).textTheme.titleLarge?.copyWith(
                  fontWeight: FontWeight.bold,
                ),
          ),
          const SizedBox(height: 16),
          ...sortOptions.map((option) {
            final isSelected = _sortBy == option['value'];
            return ListTile(
              leading: Icon(
                option['icon'] as IconData,
                color:
                    isSelected ? Theme.of(context).colorScheme.primary : null,
              ),
              title: Text(
                option['label'] as String,
                style: TextStyle(
                  fontWeight: isSelected ? FontWeight.w600 : FontWeight.normal,
                  color:
                      isSelected ? Theme.of(context).colorScheme.primary : null,
                ),
              ),
              trailing: isSelected
                  ? Icon(
                      _sortDescending
                          ? Icons.arrow_downward
                          : Icons.arrow_upward,
                      color: Theme.of(context).colorScheme.primary,
                    )
                  : null,
              onTap: () {
                setState(() {
                  if (_sortBy == option['value']) {
                    // Toggle sort direction
                    _sortDescending = !_sortDescending;
                  } else {
                    // Change sort field
                    _sortBy = option['value'] as String;
                    // Default to descending for dates, ascending for others
                    _sortDescending = option['value'] == 'order_date' ||
                        option['value'] == 'delivery_date';
                  }
                });
                Navigator.pop(context);
                _loadOrders();
              },
            );
          }),
          const SizedBox(height: 8),
        ],
      ),
    );
  }
}
