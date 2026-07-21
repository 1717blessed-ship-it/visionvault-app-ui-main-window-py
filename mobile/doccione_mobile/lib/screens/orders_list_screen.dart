import 'package:flutter/material.dart';
import 'package:doccione_mobile/database/database_helper.dart';
import 'package:doccione_mobile/database/orders_repository.dart';
import 'package:doccione_mobile/models/order_with_details.dart';
import 'package:doccione_mobile/widgets/order_card.dart';
import 'package:doccione_mobile/screens/order_detail_screen.dart';

class OrdersListScreen extends StatefulWidget {
  final String? initialStatus;

  const OrdersListScreen({
    super.key,
    this.initialStatus,
  });

  @override
  State<OrdersListScreen> createState() => _OrdersListScreenState();
}

class _OrdersListScreenState extends State<OrdersListScreen> {
  final DatabaseHelper _dbHelper = DatabaseHelper();
  late final OrdersRepository _ordersRepo;
  final TextEditingController _searchController = TextEditingController();
  
  List<OrderWithDetails> _orders = [];
  bool _isLoading = true;
  bool _isSyncing = false;
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
    _loadOrders();
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _loadOrders() async {
    if (_isSyncing) return; // Skip if syncing
    
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

      setState(() {
        _orders = orders;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _isLoading = false;
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error al cargar pedidos: $e')),
        );
      }
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
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
        actions: [
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
                // Debounce search
                Future.delayed(const Duration(milliseconds: 500), () {
                  if (mounted) _loadOrders();
                });
              },
            ),
          ),
          // Status filter chips
          Container(
            height: 50,
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
                          color: isSelected ? Colors.white : Colors.grey[700],
                        ),
                        const SizedBox(width: 4),
                        Text(filter['label'] as String),
                      ],
                    ),
                    onSelected: (selected) {
                      _onStatusFilterChanged(selected ? filter['value'] as String? : null);
                    },
                    selectedColor: Theme.of(context).colorScheme.primary,
                    checkmarkColor: Colors.white,
                    labelStyle: TextStyle(
                      color: isSelected ? Colors.white : Colors.grey[700],
                      fontWeight: isSelected ? FontWeight.w600 : FontWeight.normal,
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
                                      onContactWhatsApp: null, // TODO: Implement WhatsApp integration
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
              color: Colors.grey[400],
            ),
            const SizedBox(height: 16),
            Text(
              hasFilters 
                  ? 'No se encontraron pedidos'
                  : 'No hay pedidos',
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w600,
                color: Colors.grey[700],
              ),
            ),
            const SizedBox(height: 8),
            Text(
              hasFilters
                  ? 'Intenta cambiar los filtros o la búsqueda'
                  : 'Sincroniza para obtener los últimos datos',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 14,
                color: Colors.grey[500],
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
                        Icon(Icons.priority_high, size: 16, color: Colors.red),
                        SizedBox(width: 4),
                        Text('Alta'),
                      ],
                    ),
                    selected: tempPriority == 'high',
                    onSelected: (selected) {
                      setModalState(() {
                        tempPriority = selected ? 'high' : null;
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
                    selected: tempPriority == 'medium',
                    onSelected: (selected) {
                      setModalState(() {
                        tempPriority = selected ? 'medium' : null;
                      });
                    },
                  ),
                  FilterChip(
                    label: const Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.arrow_downward, size: 16, color: Colors.blue),
                        SizedBox(width: 4),
                        Text('Baja'),
                      ],
                    ),
                    selected: tempPriority == 'low',
                    onSelected: (selected) {
                      setModalState(() {
                        tempPriority = selected ? 'low' : null;
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
                  style: TextStyle(
                    fontSize: 12,
                    color: Colors.grey[600],
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
      {'value': 'order_date', 'label': 'Fecha del pedido', 'icon': Icons.calendar_today},
      {'value': 'delivery_date', 'label': 'Fecha de entrega', 'icon': Icons.event},
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
                color: isSelected ? Theme.of(context).colorScheme.primary : null,
              ),
              title: Text(
                option['label'] as String,
                style: TextStyle(
                  fontWeight: isSelected ? FontWeight.w600 : FontWeight.normal,
                  color: isSelected ? Theme.of(context).colorScheme.primary : null,
                ),
              ),
              trailing: isSelected
                  ? Icon(
                      _sortDescending ? Icons.arrow_downward : Icons.arrow_upward,
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

  String _getStatusLabel(String status) {
    final filter = _statusFilters.firstWhere(
      (f) => f['value'] == status,
      orElse: () => {'label': status},
    );
    return filter['label'] as String;
  }
}
