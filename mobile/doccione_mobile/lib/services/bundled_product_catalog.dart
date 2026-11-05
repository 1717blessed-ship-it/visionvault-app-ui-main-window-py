import 'dart:convert';

import 'package:flutter/services.dart';

import '../models/catalog_design.dart';

/// Catálogo de productos incluido en el APK/IPA para operar offline.
class BundledProductCatalog {
  static const _manifest = 'assets/product_catalog.json';
  static List<StudioProduct>? _cache;

  static Future<List<StudioProduct>> load() async {
    if (_cache != null) return _cache!;
    try {
      final source = await rootBundle.loadString(_manifest);
      final json = jsonDecode(source) as Map<String, dynamic>;
      final list = (json['products'] as List<dynamic>? ?? const [])
          .map((item) => StudioProduct.fromJson(item as Map<String, dynamic>))
          .toList();
      _cache = list;
      return list;
    } catch (_) {
      _cache = const [];
      return const [];
    }
  }
}
