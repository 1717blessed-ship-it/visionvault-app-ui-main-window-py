import 'package:flutter/material.dart';
import '../models/order_item.dart';
import '../services/unified_orders_manager.dart';

/// Widget para mostrar y gestionar los items de una orden
class OrderItemsListWidget extends StatefulWidget {
  final List<OrderItem> items;
  final UnifiedOrdersManager ordersManager;
  final VoidCallback? onItemsChanged;
  final bool isEditable;

  const OrderItemsListWidget({
    super.key,
    required this.items,
    required this.ordersManager,
    this.onItemsChanged,
    this.isEditable = true,
  });

  @override
  State<OrderItemsListWidget> createState() => _OrderItemsListWidgetState();
}

class _OrderItemsListWidgetState extends State<OrderItemsListWidget> {
  late List<OrderItem> _items;

  @override
  void initState() {
    super.initState();
    _items = List.from(widget.items);
  }

  @override
  void didUpdateWidget(OrderItemsListWidget oldWidget) {
    super.didUpdateWidget(oldWidget);
    _items = List.from(widget.items);
  }

  void _removeItem(String itemId) {
    setState(() {
      _items.removeWhere((item) => item.id == itemId);
    });
    widget.ordersManager.removeItemFromOrder(itemId);
    widget.onItemsChanged?.call();
  }

  void _updateQuantity(String itemId, int newQuantity) {
    if (newQuantity <= 0) {
      _removeItem(itemId);
      return;
    }

    setState(() {
      final index = _items.indexWhere((item) => item.id == itemId);
      if (index != -1) {
        final item = _items[index];
        _items[index] = item.copyWith(
          quantity: newQuantity,
          totalPrice:
              item.unitPrice != null ? item.unitPrice! * newQuantity : null,
        );
      }
    });

    widget.ordersManager.updateOrderItem(
      itemId,
      quantity: newQuantity,
    );
    widget.onItemsChanged?.call();
  }

  @override
  Widget build(BuildContext context) {
    if (_items.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                Icons.shopping_cart_outlined,
                size: 64,
                color: Colors.grey[300],
              ),
              const SizedBox(height: 16),
              Text(
                'Sin items en la orden',
                style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      color: Colors.grey[600],
                    ),
              ),
            ],
          ),
        ),
      );
    }

    return ListView.builder(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      itemCount: _items.length,
      itemBuilder: (context, index) {
        final item = _items[index];
        return Card(
          margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
          child: Padding(
            padding: const EdgeInsets.all(12.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Header: Producto y acciones
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            item.productName ?? item.productId,
                            style: const TextStyle(
                              fontWeight: FontWeight.bold,
                              fontSize: 16,
                            ),
                          ),
                          if (item.variantName != null)
                            Padding(
                              padding: const EdgeInsets.only(top: 4.0),
                              child: Text(
                                'Variante: ${item.variantName}',
                                style: TextStyle(
                                  color: Colors.grey[600],
                                  fontSize: 12,
                                ),
                              ),
                            ),
                        ],
                      ),
                    ),
                    if (widget.isEditable)
                      IconButton(
                        icon:
                            const Icon(Icons.delete_outline, color: Colors.red),
                        onPressed: () => _removeItem(item.id),
                        tooltip: 'Eliminar item',
                      ),
                  ],
                ),
                const SizedBox(height: 12),
                // Cantidad y precio
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    // Cantidad
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Cantidad',
                          style:
                              TextStyle(color: Colors.grey[600], fontSize: 12),
                        ),
                        const SizedBox(height: 4),
                        if (widget.isEditable)
                          Container(
                            decoration: BoxDecoration(
                              border: Border.all(color: Colors.grey[300]!),
                              borderRadius: BorderRadius.circular(4),
                            ),
                            child: Row(
                              children: [
                                IconButton(
                                  icon: const Icon(Icons.remove),
                                  onPressed: () => _updateQuantity(
                                    item.id,
                                    item.quantity - 1,
                                  ),
                                  iconSize: 18,
                                  padding: EdgeInsets.zero,
                                  constraints: const BoxConstraints(
                                    minWidth: 32,
                                    minHeight: 32,
                                  ),
                                ),
                                Padding(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 12.0,
                                  ),
                                  child: Text(
                                    item.quantity.toString(),
                                    style: const TextStyle(
                                      fontWeight: FontWeight.bold,
                                    ),
                                  ),
                                ),
                                IconButton(
                                  icon: const Icon(Icons.add),
                                  onPressed: () => _updateQuantity(
                                    item.id,
                                    item.quantity + 1,
                                  ),
                                  iconSize: 18,
                                  padding: EdgeInsets.zero,
                                  constraints: const BoxConstraints(
                                    minWidth: 32,
                                    minHeight: 32,
                                  ),
                                ),
                              ],
                            ),
                          )
                        else
                          Text(
                            item.quantity.toString(),
                            style: const TextStyle(fontWeight: FontWeight.bold),
                          ),
                      ],
                    ),
                    // Precio
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Text(
                          'Precio Total',
                          style:
                              TextStyle(color: Colors.grey[600], fontSize: 12),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          item.totalPrice != null
                              ? '\$${item.totalPrice!.toStringAsFixed(2)}'
                              : 'N/A',
                          style: const TextStyle(
                            fontWeight: FontWeight.bold,
                            color: Colors.green,
                            fontSize: 16,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}
