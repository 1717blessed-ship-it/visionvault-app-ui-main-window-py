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
  
  List<OrderWithDetails> _orders = [];
  bool _isLoading = true;
  String? _selectedStatus;
  
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

  Future<void> _loadOrders() async {
    setState(() {
      _isLoading = true;
    });

    try {
      final orders = await _ordersRepo.getOrdersWithDetails(
        status: _selectedStatus,
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

  void _onStatusFilterChanged(String? status) {
    setState(() {
      _selectedStatus = status;
    });
    _loadOrders();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Pedidos'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
      ),
      body: Column(
        children: [
          // Status filter chips
          Container(
            height: 60,
            padding: const EdgeInsets.symmetric(vertical: 8),
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
                        onRefresh: _loadOrders,
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
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            Icons.inbox_outlined,
            size: 64,
            color: Colors.grey[400],
          ),
          const SizedBox(height: 16),
          Text(
            _selectedStatus == null
                ? 'No hay pedidos'
                : 'No hay pedidos ${_getStatusLabel(_selectedStatus!).toLowerCase()}',
            style: TextStyle(
              fontSize: 16,
              color: Colors.grey[600],
            ),
          ),
          const SizedBox(height: 8),
          Text(
            'Sincroniza para obtener los últimos datos',
            style: TextStyle(
              fontSize: 14,
              color: Colors.grey[500],
            ),
          ),
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
