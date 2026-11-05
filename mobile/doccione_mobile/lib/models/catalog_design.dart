class CatalogDesign {
  final String id;
  final String name;
  final String category;
  final String caption;
  final List<String> tags;
  final String previewUrl;
  final int visibleWidth;
  final int visibleHeight;
  final String? cachedPreviewPath;
  final String? assetPreviewPath;
  final int modifiedMs;

  const CatalogDesign({
    required this.id,
    required this.name,
    required this.category,
    required this.caption,
    required this.tags,
    required this.previewUrl,
    this.visibleWidth = 0,
    this.visibleHeight = 0,
    this.cachedPreviewPath,
    this.assetPreviewPath,
    this.modifiedMs = 0,
  });

  double get aspectRatio =>
      visibleWidth > 0 && visibleHeight > 0 ? visibleWidth / visibleHeight : 1;
  bool get hasVisibleDimensions => visibleWidth > 0 && visibleHeight > 0;

  factory CatalogDesign.fromJson(Map<String, dynamic> json) => CatalogDesign(
        id: json['id'] as String,
        name: json['name'] as String? ?? 'Diseño',
        category: json['category'] as String? ?? 'Sin categoría',
        caption: json['caption'] as String? ?? '',
        tags: (json['tags'] as List<dynamic>? ?? const [])
            .map((tag) => tag.toString())
            .toList(),
        previewUrl: json['preview_url'] as String,
        visibleWidth: (json['visible_width'] as num? ?? 0).toInt(),
        visibleHeight: (json['visible_height'] as num? ?? 0).toInt(),
        cachedPreviewPath: json['cached_preview_path'] as String?,
        assetPreviewPath: json['asset_preview_path'] as String?,
        modifiedMs: (json['modified_ms'] as num? ?? 0).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'category': category,
        'caption': caption,
        'tags': tags,
        'preview_url': previewUrl,
        'visible_width': visibleWidth,
        'visible_height': visibleHeight,
        'modified_ms': modifiedMs,
        'cached_preview_path': cachedPreviewPath,
        'asset_preview_path': assetPreviewPath,
      };
}

class CatalogCartItem {
  final CatalogDesign design;
  final int quantity;
  final String material;
  final String size;

  const CatalogCartItem({
    required this.design,
    required this.quantity,
    required this.material,
    required this.size,
  });

  Map<String, dynamic> toJson() => {
        'design_id': design.id,
        'quantity': quantity,
        'material': material,
        'size': size,
      };
}

class CatalogQuote {
  final double subtotal;
  final double discountPercent;
  final double discountAmount;
  final double total;
  final List<String> warnings;

  const CatalogQuote(
      {required this.subtotal,
      required this.discountPercent,
      required this.discountAmount,
      required this.total,
      required this.warnings});

  factory CatalogQuote.fromJson(Map<String, dynamic> json) => CatalogQuote(
        subtotal: (json['subtotal'] as num? ?? 0).toDouble(),
        discountPercent: (json['discount_percent'] as num? ?? 0).toDouble(),
        discountAmount: (json['discount_amount'] as num? ?? 0).toDouble(),
        total: (json['total'] as num? ?? 0).toDouble(),
        warnings: (json['warnings'] as List<dynamic>? ?? const [])
            .map((value) => value.toString())
            .toList(),
      );
}

class StudioProduct {
  final int id;
  final String code;
  final String name;
  final String description;
  final String category;
  final String imagePath;
  final double basePrice;
  final int priceRules;
  final List<String> materials;
  final double? minPrice;
  final double? maxPrice;
  final List<StudioProductOption> options;
  final String? cachedPreviewPath;

  const StudioProduct(
      {required this.id,
      required this.code,
      required this.name,
      required this.description,
      required this.category,
      required this.imagePath,
      required this.basePrice,
      required this.priceRules,
      required this.materials,
      this.minPrice,
      this.maxPrice,
      this.options = const [],
      this.cachedPreviewPath});

  factory StudioProduct.fromJson(Map<String, dynamic> json) => StudioProduct(
        id: (json['id'] as num).toInt(),
        code: json['code'] as String? ?? '',
        name: json['name'] as String? ?? 'Producto',
        description: json['description'] as String? ?? '',
        category: json['category'] as String? ?? '',
        imagePath: json['image_path'] as String? ?? '',
        basePrice: (json['base_price'] as num? ?? 0).toDouble(),
        priceRules: (json['price_rules'] as num? ?? 0).toInt(),
        materials: (json['materials'] as List<dynamic>? ?? const [])
            .map((value) => value.toString())
            .toList(),
        minPrice: json['min_price'] != null
            ? (json['min_price'] as num).toDouble()
            : null,
        maxPrice: json['max_price'] != null
            ? (json['max_price'] as num).toDouble()
            : null,
        options: (json['options'] as List<dynamic>? ?? const [])
            .map((value) =>
                StudioProductOption.fromJson(value as Map<String, dynamic>))
            .toList(),
        cachedPreviewPath: json['cached_preview_path'] as String?,
      );

  String get displayPrice {
    if (minPrice != null && maxPrice != null && minPrice != maxPrice) {
      return '\$${minPrice!.toStringAsFixed(0)} - \$${maxPrice!.toStringAsFixed(0)}';
    } else if (minPrice != null) {
      return '\$${minPrice!.toStringAsFixed(0)}';
    } else if (maxPrice != null) {
      return '\$${maxPrice!.toStringAsFixed(0)}';
    } else if (basePrice > 0) {
      return '\$${basePrice.toStringAsFixed(0)}';
    }
    return 'Sin precio';
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'code': code,
        'name': name,
        'description': description,
        'category': category,
        'image_path': imagePath,
        'base_price': basePrice,
        'price_rules': priceRules,
        'materials': materials,
        'min_price': minPrice,
        'max_price': maxPrice,
        'options': options.map((option) => option.toJson()).toList(),
        'cached_preview_path': cachedPreviewPath,
      };
}

class StudioProductOption {
  final String variantCode, variantName, material, size;
  final double? price;
  const StudioProductOption(
      {required this.variantCode,
      required this.variantName,
      required this.material,
      required this.size,
      this.price});
  factory StudioProductOption.fromJson(Map<String, dynamic> json) =>
      StudioProductOption(
        variantCode: json['variant_code'] as String? ?? '',
        variantName: json['variant_name'] as String? ?? '',
        material: json['material'] as String? ?? '',
        size: json['size'] as String? ?? '',
        price: json['price'] != null
            ? (json['price'] as num).toDouble()
            : json['variant_price'] != null
                ? (json['variant_price'] as num).toDouble()
                : null,
      );

  Map<String, dynamic> toJson() => {
        'variant_code': variantCode,
        'variant_name': variantName,
        'material': material,
        'size': size,
        'price': price,
      };
}
