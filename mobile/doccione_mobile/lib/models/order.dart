import 'dart:convert';

/// Order model representing a client order or purchase
class Order {
  final String id;
  final String? orderNumber;
  final String? jobId;
  final String? clientId;
  final String? client;
  final String? whatsapp;
  final String? status;
  final String? material;
  final String? size;
  final int? quantity;
  final String? deliveryDate;
  final String? printPriority;
  final bool? isArchived;
  final String? observations;
  final String? orderConcept;
  final String? orderDescription;
  final double? totalAmount;
  final String? currency;
  final String? orderDate;
  final String? createdAt;
  final String? updatedAt;
  final Map<String, dynamic>? metadata;

  Order({
    required this.id,
    this.orderNumber,
    this.jobId,
    this.clientId,
    this.client,
    this.whatsapp,
    this.status,
    this.material,
    this.size,
    this.quantity,
    this.deliveryDate,
    this.printPriority,
    this.isArchived,
    this.observations,
    this.orderConcept,
    this.orderDescription,
    this.totalAmount,
    this.currency,
    this.orderDate,
    this.createdAt,
    this.updatedAt,
    this.metadata,
  });

  Map<String, dynamic> toMap() {
    return {
      'id': id,
      'order_number': orderNumber,
      'job_id': jobId,
      'client_id': clientId,
      'client': client,
      'whatsapp': whatsapp,
      'status': status,
      'material': material,
      'size': size,
      'quantity': quantity,
      'delivery_date': deliveryDate,
      'print_priority': printPriority,
      'is_archived': isArchived == true ? 1 : 0,
      'observations': observations,
      'order_concept': orderConcept,
      'order_description': orderDescription,
      'total_amount': totalAmount,
      'currency': currency,
      'order_date': orderDate,
      'created_at': createdAt,
      'updated_at': updatedAt,
      'metadata': metadata != null ? jsonEncode(metadata) : null,
    };
  }

  factory Order.fromMap(Map<String, dynamic> map) {
    return Order(
      id: map['id'] as String,
      orderNumber: map['order_number'] as String?,
      jobId: map['job_id'] as String?,
      clientId: map['client_id'] as String?,
      client: map['client'] as String?,
      whatsapp: map['whatsapp'] as String?,
      status: map['status'] as String?,
      material: map['material'] as String?,
      size: map['size'] as String?,
      quantity: map['quantity'] as int?,
      deliveryDate: map['delivery_date'] as String?,
      printPriority: map['print_priority'] as String?,
      isArchived: map['is_archived'] == 1,
      observations: map['observations'] as String?,
      orderConcept: map['order_concept'] as String?,
      orderDescription: map['order_description'] as String?,
      totalAmount: map['total_amount'] != null 
          ? (map['total_amount'] as num).toDouble()
          : null,
      currency: map['currency'] as String?,
      orderDate: map['order_date'] as String?,
      createdAt: map['created_at'] as String?,
      updatedAt: map['updated_at'] as String?,
      metadata: map['metadata'] != null 
          ? jsonDecode(map['metadata'] as String) as Map<String, dynamic>
          : null,
    );
  }

  Order copyWith({
    String? id,
    String? orderNumber,
    String? jobId,
    String? clientId,
    String? client,
    String? whatsapp,
    String? status,
    String? material,
    String? size,
    int? quantity,
    String? deliveryDate,
    String? printPriority,
    bool? isArchived,
    String? observations,
    String? orderConcept,
    String? orderDescription,
    double? totalAmount,
    String? currency,
    String? orderDate,
    String? createdAt,
    String? updatedAt,
    Map<String, dynamic>? metadata,
  }) {
    return Order(
      id: id ?? this.id,
      orderNumber: orderNumber ?? this.orderNumber,
      jobId: jobId ?? this.jobId,
      clientId: clientId ?? this.clientId,
      client: client ?? this.client,
      whatsapp: whatsapp ?? this.whatsapp,
      status: status ?? this.status,
      material: material ?? this.material,
      size: size ?? this.size,
      quantity: quantity ?? this.quantity,
      deliveryDate: deliveryDate ?? this.deliveryDate,
      printPriority: printPriority ?? this.printPriority,
      isArchived: isArchived ?? this.isArchived,
      observations: observations ?? this.observations,
      orderConcept: orderConcept ?? this.orderConcept,
      orderDescription: orderDescription ?? this.orderDescription,
      totalAmount: totalAmount ?? this.totalAmount,
      currency: currency ?? this.currency,
      orderDate: orderDate ?? this.orderDate,
      createdAt: createdAt ?? this.createdAt,
      updatedAt: updatedAt ?? this.updatedAt,
      metadata: metadata ?? this.metadata,
    );
  }
}
