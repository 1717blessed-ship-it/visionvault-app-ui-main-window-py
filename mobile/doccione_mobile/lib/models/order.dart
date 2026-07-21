import 'dart:convert';

/// Order model representing a client order or purchase
class Order {
  final String id;
  final String? orderNumber;
  final String? jobId;
  final String? clientId;
  final String? status;
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
    this.status,
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
      'status': status,
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
      status: map['status'] as String?,
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
    String? status,
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
      status: status ?? this.status,
      totalAmount: totalAmount ?? this.totalAmount,
      currency: currency ?? this.currency,
      orderDate: orderDate ?? this.orderDate,
      createdAt: createdAt ?? this.createdAt,
      updatedAt: updatedAt ?? this.updatedAt,
      metadata: metadata ?? this.metadata,
    );
  }
}
