import 'package:flutter/material.dart';
import '../models/order.dart';
import '../services/quick_edit_api_client.dart';

/// Editor operativo acotado: no altera importes ni reglas comerciales.
class OrderEditorSheet extends StatefulWidget {
  final QuickEditApiClient api;
  final int orderId;
  final Order order;
  final VoidCallback onSaved;

  const OrderEditorSheet({
    super.key,
    required this.api,
    required this.orderId,
    required this.order,
    required this.onSaved,
  });

  static Future<void> show(
    BuildContext context, {
    required QuickEditApiClient api,
    required int orderId,
    required Order order,
    required VoidCallback onSaved,
  }) =>
      showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        builder: (_) => OrderEditorSheet(
            api: api, orderId: orderId, order: order, onSaved: onSaved),
      );

  @override
  State<OrderEditorSheet> createState() => _OrderEditorSheetState();
}

class _OrderEditorSheetState extends State<OrderEditorSheet> {
  late final TextEditingController _material =
      TextEditingController(text: widget.order.material ?? '');
  late final TextEditingController _size =
      TextEditingController(text: widget.order.size ?? '');
  late final TextEditingController _quantity =
      TextEditingController(text: '${widget.order.quantity ?? 1}');
  late final TextEditingController _delivery =
      TextEditingController(text: widget.order.deliveryDate ?? '');
  late final TextEditingController _concept =
      TextEditingController(text: widget.order.orderConcept ?? '');
  late final TextEditingController _description =
      TextEditingController(text: widget.order.orderDescription ?? '');
  late final TextEditingController _observations =
      TextEditingController(text: widget.order.observations ?? '');
  bool _saving = false;
  String? _error;

  @override
  void dispose() {
    _material.dispose();
    _size.dispose();
    _quantity.dispose();
    _delivery.dispose();
    _concept.dispose();
    _description.dispose();
    _observations.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final quantity = int.tryParse(_quantity.text.trim());
    if (quantity == null || quantity < 1) {
      setState(() => _error = 'La cantidad debe ser un número mayor que cero.');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    final result = await widget.api.updateOrderDetails(widget.orderId, {
      'material': _material.text.trim(),
      'size': _size.text.trim(),
      'quantity': quantity,
      'delivery_date': _delivery.text.trim(),
      'order_concept': _concept.text.trim(),
      'order_description': _description.text.trim(),
      'observations': _observations.text.trim(),
    });
    if (!mounted) return;
    if (!result.success) {
      setState(() {
        _saving = false;
        _error = result.errorMessage ?? 'No se pudieron guardar los cambios.';
      });
      return;
    }
    Navigator.pop(context);
    widget.onSaved();
  }

  @override
  Widget build(BuildContext context) => SafeArea(
        child: Padding(
          padding: EdgeInsets.fromLTRB(
              20, 16, 20, 20 + MediaQuery.viewInsetsOf(context).bottom),
          child: SingleChildScrollView(
            child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text('Editar pedido',
                      style: Theme.of(context)
                          .textTheme
                          .titleLarge
                          ?.copyWith(fontWeight: FontWeight.w700)),
                  const SizedBox(height: 4),
                  Text(
                      'Datos operativos. Los precios y costos se administran desde Studio.',
                      style: Theme.of(context).textTheme.bodySmall),
                  const SizedBox(height: 16),
                  _field(_material, 'Material'),
                  _field(_size, 'Tamaño'),
                  _field(_quantity, 'Cantidad',
                      keyboardType: TextInputType.number),
                  _field(_delivery, 'Entrega', hint: 'AAAA-MM-DD'),
                  _field(_concept, 'Concepto'),
                  _field(_description, 'Descripción', lines: 3),
                  _field(_observations, 'Observaciones', lines: 3),
                  if (_error != null)
                    Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: Text(_error!,
                            style: TextStyle(
                                color: Theme.of(context).colorScheme.error))),
                  FilledButton.icon(
                      onPressed: _saving ? null : _save,
                      icon: _saving
                          ? const SizedBox.square(
                              dimension: 18,
                              child: CircularProgressIndicator(strokeWidth: 2))
                          : const Icon(Icons.save_outlined),
                      label:
                          Text(_saving ? 'Guardando...' : 'Guardar cambios')),
                ]),
          ),
        ),
      );

  Widget _field(TextEditingController controller, String label,
          {String? hint, int lines = 1, TextInputType? keyboardType}) =>
      Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: TextField(
            controller: controller,
            maxLines: lines,
            keyboardType: keyboardType,
            decoration: InputDecoration(
                labelText: label, hintText: hint, isDense: true)),
      );
}
