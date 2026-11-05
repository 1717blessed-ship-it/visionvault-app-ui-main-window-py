import 'package:flutter/material.dart';
import '../models/product_variant.dart';
import '../services/unified_orders_manager.dart';

/// Widget para seleccionar un producto y, opcionalmente, un subproducto/variante
class ProductVariantSelector extends StatefulWidget {
  final String productId;
  final String productName;
  final UnifiedOrdersManager ordersManager;
  final Function(String variantId, String variantName, double? price)?
      onVariantSelected;
  final bool allowMultipleVariants;

  const ProductVariantSelector({
    super.key,
    required this.productId,
    required this.productName,
    required this.ordersManager,
    this.onVariantSelected,
    this.allowMultipleVariants = false,
  });

  @override
  State<ProductVariantSelector> createState() => _ProductVariantSelectorState();
}

class _ProductVariantSelectorState extends State<ProductVariantSelector> {
  late Future<List<ProductVariant>> _variantsFuture;
  String? _selectedVariantId;

  @override
  void initState() {
    super.initState();
    _variantsFuture = widget.ordersManager.getProductVariants(widget.productId);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<ProductVariant>>(
      future: _variantsFuture,
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }

        if (snapshot.hasError) {
          return Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.error_outline, color: Colors.red),
                const SizedBox(height: 8),
                Text('Error: ${snapshot.error}'),
              ],
            ),
          );
        }

        final variants = snapshot.data ?? [];

        if (variants.isEmpty) {
          return Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.info_outline, color: Colors.grey),
                const SizedBox(height: 8),
                Text(
                    'No hay subproductos disponibles para ${widget.productName}'),
              ],
            ),
          );
        }

        return SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.all(16.0),
                child: Text(
                  'Selecciona una variante de ${widget.productName}',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              ListView.builder(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                itemCount: variants.length,
                itemBuilder: (context, index) {
                  final variant = variants[index];
                  final isSelected = _selectedVariantId == variant.id;

                  return Card(
                    margin:
                        const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    child: ListTile(
                      leading: isSelected
                          ? const Icon(Icons.check_circle, color: Colors.green)
                          : const Icon(Icons.radio_button_unchecked),
                      title: Text(variant.name),
                      subtitle: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          if (variant.description != null)
                            Text(variant.description!),
                          if (variant.attributes != null)
                            Text(
                              'Atributos: ${variant.attributes.toString()}',
                              style: const TextStyle(fontSize: 12),
                            ),
                          if (variant.price != null)
                            Text(
                              'Precio: \$${variant.price!.toStringAsFixed(2)}',
                              style: const TextStyle(
                                fontWeight: FontWeight.bold,
                                color: Colors.green,
                              ),
                            ),
                        ],
                      ),
                      trailing: variant.stock != null
                          ? Text(
                              'Stock: ${variant.stock}',
                              style: TextStyle(
                                color: variant.stock! > 0
                                    ? Colors.green
                                    : Colors.red,
                              ),
                            )
                          : null,
                      onTap: () {
                        setState(() {
                          _selectedVariantId = variant.id;
                        });
                        widget.onVariantSelected?.call(
                          variant.id,
                          variant.name,
                          variant.price,
                        );
                      },
                    ),
                  );
                },
              ),
            ],
          ),
        );
      },
    );
  }
}
