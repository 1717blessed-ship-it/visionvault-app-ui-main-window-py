import '../models/catalog_design.dart';
import 'catalog_api_client.dart';
import 'order_integration_client.dart';

/// Reuses the existing work editor, never its legacy HTTP routes in integration.
class OrderIntegrationCatalog extends CatalogApiClient {
  final OrderIntegrationClient integration;
  OrderIntegrationCatalog(this.integration)
      : super(baseUrl: integration.target.origin.origin, authToken: '');
  @override
  Future<List<StudioProduct>> getProducts() async =>
      ((await integration.catalog())['products'] as List)
          .map((p) => StudioProduct.fromJson(objectMap(p)))
          .toList();
  @override
  Future<List<CatalogDesign>> getDesigns(
      {String query = '',
      String? category,
      String? tag,
      bool recent = false,
      bool random = false,
      int? limit}) async {
    final response = await integration.catalog();
    return (response['designs'] as List)
        .map((d) => CatalogDesign.fromJson(objectMap(d)))
        .where((d) => d.name.toLowerCase().contains(query.toLowerCase()))
        .take(limit ?? 100)
        .toList();
  }
}
