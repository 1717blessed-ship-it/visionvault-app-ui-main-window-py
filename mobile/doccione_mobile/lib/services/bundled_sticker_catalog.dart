import 'dart:convert';

import 'package:flutter/services.dart';

import '../models/catalog_design.dart';

/// Catálogo incluido en el APK/IPA. Se renueva al distribuir una nueva versión.
class BundledStickerCatalog {
  static const _manifest = 'assets/sticker_bank/manifest.json';
  static List<CatalogDesign>? _cache;

  static Future<List<CatalogDesign>> load() async {
    if (_cache != null) return _cache!;
    try {
      final source = await rootBundle.loadString(_manifest);
      final json = jsonDecode(source) as Map<String, dynamic>;
      final list = (json['designs'] as List<dynamic>? ?? const [])
          .map((item) => CatalogDesign.fromJson(item as Map<String, dynamic>))
          .toList();
      _cache = list;
      return list;
    } catch (_) {
      _cache = const [];
      return const [];
    }
  }
}
