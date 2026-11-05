import 'dart:convert';

/// Represents an item within an order (with optional subproduct selection)
class OrderItem {
  final String id;
  final String orderId;
  final String productId;
  final String? productName;
  final String? variantId; // subproduct/variant ID (optional)
  final String? variantName; // subproduct/variant name
  final int quantity;
  final double? unitPrice;
  final double? totalPrice;
  final Map<String, dynamic>? metadata; // e.g., custom attributes, design refs
  final String? createdAt;
  final String? updatedAt;

  OrderItem({
    required this.id,
    required this.orderId,
    required this.productId,
    this.productName,
    this.variantId,
    this.variantName,
    required this.quantity,
    this.unitPrice,
    this.totalPrice,
    this.metadata,
    this.createdAt,
    this.updatedAt,
  });

  Map<String, dynamic> toMap() {
    return {
      'id': id,
      'order_id': orderId,
      'product_id': productId,
      'product_name': productName,
      'variant_id': variantId,
      'variant_name': variantName,
      'quantity': quantity,
      'unit_price': unitPrice,
      'total_price': totalPrice,
      'metadata': metadata != null ? jsonEncode(metadata) : null,
      'created_at': createdAt,
      'updated_at': updatedAt,
    };
  }

  factory OrderItem.fromMap(Map<String, dynamic> map) {
    return OrderItem(
      id: map['id'].toString(),
      orderId: map['order_id'].toString(),
      productId: map['product_id'].toString(),
      productName: map['product_name'] as String?,
      variantId: map['variant_id']?.toString(),
      variantName: map['variant_name'] as String?,
      quantity: map['quantity'] as int,
      unitPrice: map['unit_price'] != null
          ? (map['unit_price'] as num).toDouble()
          : null,
      totalPrice: map['total_price'] != null
          ? (map['total_price'] as num).toDouble()
          : null,
      metadata: map['metadata'] != null
          ? jsonDecode(map['metadata'] as String) as Map<String, dynamic>
          : null,
      createdAt: map['created_at'] as String?,
      updatedAt: map['updated_at'] as String?,
    );
  }

  factory OrderItem.fromJson(Map<String, dynamic> json) {
    return OrderItem(
      id: json['id'] as String,
      orderId: json['order_id'] as String,
      productId: json['product_id'] as String,
      productName: json['product_name'] as String?,
      variantId: json['variant_id'] as String?,
      variantName: json['variant_name'] as String?,
      quantity: json['quantity'] as int,
      unitPrice: json['unit_price'] != null
          ? (json['unit_price'] as num).toDouble()
          : null,
      totalPrice: json['total_price'] != null
          ? (json['total_price'] as num).toDouble()
          : null,
      metadata: json['metadata'] as Map<String, dynamic>?,
      createdAt: json['created_at'] as String?,
      updatedAt: json['updated_at'] as String?,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'order_id': orderId,
        'product_id': productId,
        'product_name': productName,
        'variant_id': variantId,
        'variant_name': variantName,
        'quantity': quantity,
        'unit_price': unitPrice,
        'total_price': totalPrice,
        'metadata': metadata,
        'created_at': createdAt,
        'updated_at': updatedAt,
      };

  OrderItem copyWith({
    String? id,
    String? orderId,
    String? productId,
    String? productName,
    String? variantId,
    String? variantName,
    int? quantity,
    double? unitPrice,
    double? totalPrice,
    Map<String, dynamic>? metadata,
    String? createdAt,
    String? updatedAt,
  }) {
    return OrderItem(
      id: id ?? this.id,
      orderId: orderId ?? this.orderId,
      productId: productId ?? this.productId,
      productName: productName ?? this.productName,
      variantId: variantId ?? this.variantId,
      variantName: variantName ?? this.variantName,
      quantity: quantity ?? this.quantity,
      unitPrice: unitPrice ?? this.unitPrice,
      totalPrice: totalPrice ?? this.totalPrice,
      metadata: metadata ?? this.metadata,
      createdAt: createdAt ?? this.createdAt,
      updatedAt: updatedAt ?? this.updatedAt,
    );
  }
}
