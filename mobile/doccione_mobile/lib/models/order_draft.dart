import '../services/offline_orders_service.dart';

/// Borrador local, no es un pedido confirmado ni un payload HTTP de Studio.
class OrderDraft {
  final String id;
  final int revision;
  final String client, whatsapp, notes;
  final List<OrderWork> jobs;
  OrderDraft(
      {String? id,
      this.revision = 0,
      this.client = '',
      this.whatsapp = '',
      this.notes = '',
      List<OrderWork> jobs = const []})
      : id = id ?? OfflineOrdersService.newRequestId(),
        jobs = List.unmodifiable(jobs);

  Map<String, dynamic> toJson() => {
        'id': id,
        'revision': revision,
        'client': client,
        'whatsapp': whatsapp,
        'observations': notes,
        'jobs': jobs.map((job) => job.toJson()).toList(),
        'persistence': 'local_draft',
        'desktop_confirmed': false
      };
  factory OrderDraft.fromJson(Map<String, dynamic> json) => OrderDraft(
      id: json['id'] as String,
      revision: json['revision'] as int? ?? 0,
      client: json['client'] as String? ?? '',
      whatsapp: json['whatsapp'] as String? ?? '',
      notes: json['observations'] as String? ?? '',
      jobs: (json['jobs'] as List? ?? [])
          .map((j) => OrderWork.fromJson(Map<String, dynamic>.from(j as Map)))
          .toList());
}

class DesignAllocation {
  final String designId, name;
  final int quantity;
  const DesignAllocation(
      {required this.designId, required this.name, required this.quantity});
  Map<String, dynamic> toJson() =>
      {'catalog_design_id': designId, 'name': name, 'quantity': quantity};
  factory DesignAllocation.fromJson(Map<String, dynamic> json) =>
      DesignAllocation(
          designId: json['catalog_design_id'] as String,
          name: json['name'] as String? ?? '',
          quantity: json['quantity'] as int);
}

/// IDs del catálogo HTTP son identificadores de transporte, no IDs SQLite inferidos.
class OrderWork {
  final String id, productCode, productName, variantCode, variantName;
  final String material, size, unitKind, notes;
  final int quantity;
  final List<DesignAllocation> designs;
  OrderWork(
      {String? id,
      required this.productCode,
      required this.productName,
      this.variantCode = '',
      this.variantName = '',
      this.material = '',
      this.size = '',
      this.unitKind = 'units',
      required this.quantity,
      this.notes = '',
      List<DesignAllocation> designs = const []})
      : id = id ?? OfflineOrdersService.newRequestId(),
        designs = List.unmodifiable(designs);

  int get assigned => designs.fold(0, (sum, d) => sum + d.quantity);
  int get pending => quantity - assigned;
  void validate() {
    if (productCode.trim().isEmpty || productName.trim().isEmpty) {
      throw ArgumentError('Seleccioná un producto válido.');
    }
    if (quantity < 1 || !['units', 'sheets'].contains(unitKind)) {
      throw ArgumentError('Cantidad positiva y unidad válidas requeridas.');
    }
    final ids = <String>{};
    for (final design in designs) {
      if (design.designId.isEmpty ||
          design.quantity < 1 ||
          !ids.add(design.designId)) {
        throw ArgumentError('Diseños duplicados o cantidades inválidas.');
      }
    }
    if (assigned > quantity) {
      throw ArgumentError('Los diseños superan la cantidad del trabajo.');
    }
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'product_code': productCode,
        'product_name': productName,
        'variant_code': variantCode,
        'variant_name': variantName,
        'material': material,
        'size': size,
        'quantity': quantity,
        'unit_kind': unitKind,
        'notes': notes,
        'designs': designs.map((d) => d.toJson()).toList(),
        'price_status': 'requires_desktop_quote'
      };
  factory OrderWork.fromJson(Map<String, dynamic> j) => OrderWork(
      id: j['id'] as String,
      productCode: j['product_code'] as String,
      productName: j['product_name'] as String,
      variantCode: j['variant_code'] as String? ?? '',
      variantName: j['variant_name'] as String? ?? '',
      material: j['material'] as String? ?? '',
      size: j['size'] as String? ?? '',
      quantity: j['quantity'] as int,
      unitKind: j['unit_kind'] as String? ?? 'units',
      notes: j['notes'] as String? ?? '',
      designs: (j['designs'] as List? ?? [])
          .map((d) =>
              DesignAllocation.fromJson(Map<String, dynamic>.from(d as Map)))
          .toList());
}
