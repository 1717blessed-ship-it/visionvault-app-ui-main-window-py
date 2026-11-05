import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as path;
import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

import '../models/catalog_design.dart';
import 'database_helper.dart';

/// Snapshot local del catálogo. El contenido es de solo lectura fuera de línea.
class OfflineCatalogRepository {
  final DatabaseHelper _dbHelper;
  OfflineCatalogRepository(this._dbHelper);

  Future<void> saveDesigns(List<CatalogDesign> designs) async {
    final db = await _dbHelper.database;
    final existing = await db
        .query('catalog_designs', columns: ['id', 'cached_preview_path']);
    final cachedPaths = <String, String?>{
      for (final row in existing)
        row['id'] as String: row['cached_preview_path'] as String?,
    };
    final batch = db.batch();
    final now = DateTime.now().toUtc().toIso8601String();
    for (final design in designs) {
      batch.insert(
          'catalog_designs',
          {
            'id': design.id,
            'data': jsonEncode(design.toJson()),
            'cached_preview_path':
                design.cachedPreviewPath ?? cachedPaths[design.id],
            'updated_at': now,
          },
          conflictAlgorithm: ConflictAlgorithm.replace);
    }
    await batch.commit(noResult: true);
  }

  Future<List<CatalogDesign>> getDesigns() async {
    final db = await _dbHelper.database;
    final rows = await db.query('catalog_designs', orderBy: 'id');
    return rows.map((row) {
      final data = jsonDecode(row['data'] as String) as Map<String, dynamic>;
      data['cached_preview_path'] = row['cached_preview_path'];
      return CatalogDesign.fromJson(data);
    }).toList();
  }

  Future<void> saveProducts(List<StudioProduct> products) async {
    final db = await _dbHelper.database;
    final batch = db.batch();
    batch.delete('catalog_products');
    final now = DateTime.now().toUtc().toIso8601String();
    for (final product in products) {
      batch.insert('catalog_products', {
        'code': product.code,
        'data': jsonEncode(product.toJson()),
        'cached_preview_path': product.cachedPreviewPath,
        'updated_at': now,
      });
    }
    await batch.commit(noResult: true);
  }

  Future<List<StudioProduct>> getProducts() async {
    final db = await _dbHelper.database;
    final rows = await db.query('catalog_products', orderBy: 'code');
    return rows.map((row) {
      final data = jsonDecode(row['data'] as String) as Map<String, dynamic>;
      data['cached_preview_path'] = row['cached_preview_path'];
      return StudioProduct.fromJson(data);
    }).toList();
  }

  Future<String?> productPreviewPath(String productCode) async {
    final db = await _dbHelper.database;
    final rows = await db.query('catalog_products',
        columns: ['cached_preview_path'],
        where: 'code = ?',
        whereArgs: [productCode],
        limit: 1);
    final value =
        rows.isEmpty ? null : rows.first['cached_preview_path'] as String?;
    return value != null && await File(value).exists() ? value : null;
  }

  Future<void> cacheProductPreview(
      StudioProduct product, List<int> bytes) async {
    final directory = await getApplicationDocumentsDirectory();
    final folder = Directory(path.join(directory.path, 'product_previews'));
    await folder.create(recursive: true);
    final target = File(path.join(folder.path, 'product_${product.id}.img'));
    await target.writeAsBytes(bytes, flush: true);
    final db = await _dbHelper.database;
    await db.update('catalog_products', {'cached_preview_path': target.path},
        where: 'code = ?', whereArgs: [product.code]);
  }

  Future<String?> previewPath(String designId) async {
    final db = await _dbHelper.database;
    final rows = await db.query('catalog_designs',
        columns: ['cached_preview_path'],
        where: 'id = ?',
        whereArgs: [designId],
        limit: 1);
    final value =
        rows.isEmpty ? null : rows.first['cached_preview_path'] as String?;
    return value != null && await File(value).exists() ? value : null;
  }

  Future<void> cachePreview(CatalogDesign design, List<int> bytes) async {
    final directory = await getApplicationDocumentsDirectory();
    final folder = Directory(path.join(directory.path, 'catalog_previews'));
    await folder.create(recursive: true);
    final target = File(path.join(folder.path, '${design.id}.img'));
    await target.writeAsBytes(bytes, flush: true);
    final db = await _dbHelper.database;
    await db.update('catalog_designs', {'cached_preview_path': target.path},
        where: 'id = ?', whereArgs: [design.id]);
  }

  Future<List<String>> getFilters(String kind) async {
    final db = await _dbHelper.database;
    final rows =
        await db.query('catalog_filters', where: 'kind = ?', whereArgs: [kind]);
    return rows.map((row) => row['value'] as String).toList();
  }
}
