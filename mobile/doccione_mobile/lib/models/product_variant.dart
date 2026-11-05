import 'dart:convert';

/// Represents a product variant or subproduct (e.g., different sizes, colors)
class ProductVariant {
  final String id;
  final String productId;
  final String name;
  final String? description;
  final Map<String, dynamic>? attributes; // e.g., {'size': 'M', 'color': 'red'}
  final double? price;
  final String? sku;
  final int? stock;
  final bool? isActive;
  final String? createdAt;
  final String? updatedAt;

  ProductVariant({
    required this.id,
    required this.productId,
    required this.name,
    this.description,
    this.attributes,
    this.price,
    this.sku,
    this.stock,
    this.isActive = true,
    this.createdAt,
    this.updatedAt,
  });

  Map<String, dynamic> toMap() {
    return {
      'id': id,
      'product_id': productId,
      'name': name,
      'description': description,
      'attributes': attributes != null ? jsonEncode(attributes) : null,
      'price': price,
      'sku': sku,
      'stock': stock,
      'is_active': isActive == true ? 1 : 0,
      'created_at': createdAt,
      'updated_at': updatedAt,
    };
  }

  factory ProductVariant.fromMap(Map<String, dynamic> map) {
    return ProductVariant(
      id: map['id'].toString(),
      productId: map['product_id'].toString(),
      name: map['name'] as String,
      description: map['description'] as String?,
      attributes: map['attributes'] != null
          ? jsonDecode(map['attributes'] as String) as Map<String, dynamic>
          : null,
      price: map['price'] != null ? (map['price'] as num).toDouble() : null,
      sku: map['sku'] as String?,
      stock: map['stock'] as int?,
      isActive: map['is_active'] == 1,
      createdAt: map['created_at'] as String?,
      updatedAt: map['updated_at'] as String?,
    );
  }

  factory ProductVariant.fromJson(Map<String, dynamic> json) {
    return ProductVariant(
      id: json['id'] as String,
      productId: json['product_id'] as String,
      name: json['name'] as String,
      description: json['description'] as String?,
      attributes: json['attributes'] as Map<String, dynamic>?,
      price: json['price'] != null ? (json['price'] as num).toDouble() : null,
      sku: json['sku'] as String?,
      stock: json['stock'] as int?,
      isActive: json['is_active'] as bool? ?? true,
      createdAt: json['created_at'] as String?,
      updatedAt: json['updated_at'] as String?,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'product_id': productId,
        'name': name,
        'description': description,
        'attributes': attributes,
        'price': price,
        'sku': sku,
        'stock': stock,
        'is_active': isActive,
        'created_at': createdAt,
        'updated_at': updatedAt,
      };

  ProductVariant copyWith({
    String? id,
    String? productId,
    String? name,
    String? description,
    Map<String, dynamic>? attributes,
    double? price,
    String? sku,
    int? stock,
    bool? isActive,
    String? createdAt,
    String? updatedAt,
  }) {
    return ProductVariant(
      id: id ?? this.id,
      productId: productId ?? this.productId,
      name: name ?? this.name,
      description: description ?? this.description,
      attributes: attributes ?? this.attributes,
      price: price ?? this.price,
      sku: sku ?? this.sku,
      stock: stock ?? this.stock,
      isActive: isActive ?? this.isActive,
      createdAt: createdAt ?? this.createdAt,
      updatedAt: updatedAt ?? this.updatedAt,
    );
  }
}
