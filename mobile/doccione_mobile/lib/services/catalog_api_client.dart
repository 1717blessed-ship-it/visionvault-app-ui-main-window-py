import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';
import 'package:path/path.dart' as path;
import '../models/catalog_design.dart';
import '../models/mockup_reference.dart';
import '../models/pos_cart.dart';
import 'sync_api_client.dart';
import 'timeout_http_client.dart';

class StickerQuote {
  final double total;
  final bool matched;
  final String? ruleName;
  final String? warning;

  const StickerQuote({
    required this.total,
    required this.matched,
    this.ruleName,
    this.warning,
  });

  factory StickerQuote.fromJson(Map<String, dynamic> json) => StickerQuote(
        total: (json['total'] as num? ?? 0).toDouble(),
        matched: json['matched'] as bool? ?? false,
        ruleName: json['rule_name'] as String?,
        warning: json['warning'] as String?,
      );
}

class CatalogApiClient {
  final String baseUrl;
  final String authToken;
  final http.Client _httpClient;

  CatalogApiClient(
      {required this.baseUrl, required this.authToken, http.Client? httpClient})
      : _httpClient = TimeoutHttpClient(httpClient ?? http.Client());

  Map<String, String> get headers => {
        'Authorization': 'Bearer $authToken',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
      };

  MediaType _imageContentType(String filePath) {
    switch (path.extension(filePath).toLowerCase()) {
      case '.png':
        return MediaType('image', 'png');
      case '.webp':
        return MediaType('image', 'webp');
      default:
        return MediaType('image', 'jpeg');
    }
  }

  Future<List<CatalogDesign>> getDesigns(
      {String query = '',
      String? category,
      String? tag,
      bool recent = false,
      bool random = false,
      int? limit}) async {
    final uri = Uri.parse('$baseUrl/api/v1/mobile/catalog/designs').replace(
      queryParameters: {
        if (query.trim().isNotEmpty) 'q': query.trim(),
        if (category != null && category.isNotEmpty) 'category': category,
        if (tag != null && tag.isNotEmpty) 'tag': tag,
        if (recent) 'recent': '1',
        if (random) 'random': '1',
        if (limit != null) 'limit': limit.toString(),
      },
    );
    final response = await _httpClient.get(uri, headers: headers);
    if (response.statusCode != 200) {
      throw SyncApiException('No se pudo cargar el catálogo',
          statusCode: response.statusCode);
    }
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    return (body['designs'] as List<dynamic>)
        .map((item) => CatalogDesign.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<List<int>> download(String url) async {
    final uri = Uri.parse(url.startsWith('http') ? url : '$baseUrl$url');
    final response = await _httpClient.get(uri, headers: headers);
    if (response.statusCode != 200) {
      throw SyncApiException('No se pudo descargar la vista previa',
          statusCode: response.statusCode);
    }
    return response.bodyBytes;
  }

  Future<Map<String, dynamic>> analyzeFotocopiaPdf({
    required String path,
    required int copies,
    required bool duplex,
  }) async {
    final request = http.MultipartRequest(
      'POST',
      Uri.parse('$baseUrl/api/v1/mobile/fotocopias/analyze-pdf'),
    );
    request.headers['Authorization'] = 'Bearer $authToken';
    request.fields['copies'] = copies.toString();
    request.fields['duplex'] = duplex.toString();
    request.files.add(await http.MultipartFile.fromPath('pdf', path));
    final streamed = await request.send().timeout(const Duration(seconds: 45));
    final response = await http.Response.fromStream(streamed);
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    if (response.statusCode != 200) {
      throw SyncApiException(
          body['error']?.toString() ?? 'No se pudo analizar el PDF',
          statusCode: response.statusCode);
    }
    return body;
  }

  Future<List<String>> getCategories() => _getNames('categories', 'category');
  Future<List<String>> getTags() => _getNames('tags', 'name');

  Future<List<StudioProduct>> getProducts() async {
    final response = await _httpClient.get(
        Uri.parse('$baseUrl/api/v1/mobile/catalog/products'),
        headers: headers);
    if (response.statusCode != 200) {
      throw SyncApiException('No se pudieron cargar los productos',
          statusCode: response.statusCode);
    }
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    return (body['products'] as List<dynamic>)
        .map((item) => StudioProduct.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<List<String>> _getNames(String endpoint, String field) async {
    final response = await _httpClient.get(
      Uri.parse('$baseUrl/api/v1/mobile/catalog/$endpoint'),
      headers: headers,
    );
    if (response.statusCode != 200) {
      throw SyncApiException('No se pudieron cargar los filtros',
          statusCode: response.statusCode);
    }
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    return (body[endpoint] as List<dynamic>)
        .map((item) => (item as Map<String, dynamic>)[field].toString())
        .toList();
  }

  Future<int> createOrder({
    required String client,
    required String whatsapp,
    required String observations,
    required List<CatalogCartItem> items,
    required double paidAmount,
    required String paymentMethod,
    required String paymentNote,
    required String deliveryDate,
    required int printPriority,
  }) async {
    final response = await _httpClient.post(
      Uri.parse('$baseUrl/api/v1/mobile/catalog/orders'),
      headers: headers,
      body: jsonEncode({
        'client': client,
        'whatsapp': whatsapp,
        'observations': observations,
        'items': items.map((item) => item.toJson()).toList(),
        'paid_amount': paidAmount,
        'payment_method': paymentMethod,
        'payment_note': paymentNote,
        'delivery_date': deliveryDate,
        'print_priority': printPriority,
      }),
    );
    if (response.statusCode != 201) {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      throw SyncApiException(
          body['error']?.toString() ?? 'No se pudo crear el pedido',
          statusCode: response.statusCode);
    }
    return (jsonDecode(response.body) as Map<String, dynamic>)['order_id']
        as int;
  }

  Future<CatalogQuote> quoteOrder(
      {required List<CatalogCartItem> items}) async {
    final response = await _httpClient.post(
      Uri.parse('$baseUrl/api/v1/mobile/catalog/quote'),
      headers: headers,
      body: jsonEncode({'items': items.map((item) => item.toJson()).toList()}),
    );
    if (response.statusCode != 200) {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      throw SyncApiException(
          body['error']?.toString() ?? 'No se pudo calcular la venta',
          statusCode: response.statusCode);
    }
    return CatalogQuote.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>);
  }

  Future<int> createProductOrder(
      {required String client,
      required String whatsapp,
      required String observations,
      required Map<String, int> items}) async {
    final response = await _httpClient.post(
        Uri.parse('$baseUrl/api/v1/mobile/catalog/product-orders'),
        headers: headers,
        body: jsonEncode({
          'client': client,
          'whatsapp': whatsapp,
          'observations': observations,
          'items': items.entries
              .map((entry) =>
                  {'product_code': entry.key, 'quantity': entry.value})
              .toList()
        }));
    if (response.statusCode != 201) {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      throw SyncApiException(
          body['error']?.toString() ?? 'No se pudo crear la venta',
          statusCode: response.statusCode);
    }
    return (jsonDecode(response.body) as Map<String, dynamic>)['order_id']
        as int;
  }

  Future<int> createProductOrderLines({
    required String client,
    required String whatsapp,
    required String observations,
    required List<PosProductLine> items,
    int? targetOrderId,
  }) async {
    final response = await _httpClient.post(
        Uri.parse('$baseUrl/api/v1/mobile/catalog/product-orders'),
        headers: headers,
        body: jsonEncode({
          'client': client,
          'whatsapp': whatsapp,
          'observations': observations,
          'items': items.map((item) => item.toRequestJson()).toList(),
          if (targetOrderId != null) 'target_order_id': targetOrderId,
        }));
    if (response.statusCode != 201) {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      throw SyncApiException(
          body['error']?.toString() ?? 'No se pudo crear la venta',
          statusCode: response.statusCode);
    }
    return (jsonDecode(response.body) as Map<String, dynamic>)['order_id']
        as int;
  }

  Future<double> quoteProductOrder(Map<String, int> items) async {
    final response = await _httpClient.post(
        Uri.parse('$baseUrl/api/v1/mobile/catalog/product-quote'),
        headers: headers,
        body: jsonEncode({
          'items': items.entries
              .map((entry) =>
                  {'product_code': entry.key, 'quantity': entry.value})
              .toList()
        }));
    if (response.statusCode != 200) {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      throw SyncApiException(body['error']?.toString() ?? 'No se pudo cotizar',
          statusCode: response.statusCode);
    }
    return ((jsonDecode(response.body) as Map<String, dynamic>)['total'] as num)
        .toDouble();
  }

  Future<int> createStickerOrder({
    required String clientRequestId,
    required String client,
    required String whatsapp,
    required String observations,
    required String mode,
    required List<String> catalogDesignIds,
    required List<File> images,
    List<MockupReference> referenceImages = const [],
  }) async {
    final request = http.MultipartRequest(
        'POST', Uri.parse('$baseUrl/api/v1/mobile/sticker-orders'));
    request.headers['Authorization'] = 'Bearer $authToken';
    request.headers['Accept'] = 'application/json';
    request.fields['metadata'] = jsonEncode({
      'client_request_id': clientRequestId,
      'client': client,
      'whatsapp': whatsapp,
      'observations': observations,
      'mode': mode,
      'catalog_design_ids': catalogDesignIds,
      'reference_metadata':
          referenceImages.map((reference) => reference.toUploadJson()).toList(),
    });
    for (final image in images) {
      request.files.add(await http.MultipartFile.fromPath(
        'images',
        image.path,
        contentType: _imageContentType(image.path),
      ));
    }
    for (final reference in referenceImages) {
      request.files.add(await http.MultipartFile.fromPath(
        'reference_images',
        reference.file.path,
        contentType: _imageContentType(reference.file.path),
      ));
    }
    final streamed = await request.send().timeout(const Duration(seconds: 45));
    final response = await http.Response.fromStream(streamed);
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    if (response.statusCode != 201) {
      throw SyncApiException(
          body['error']?.toString() ?? 'No se pudo crear el pedido',
          statusCode: response.statusCode);
    }
    return (body['order_id'] as num).toInt();
  }

  Future<StickerQuote> quoteStickerOrder({
    required String mode,
    required int designCount,
  }) async {
    final response = await _httpClient.post(
      Uri.parse('$baseUrl/api/v1/mobile/sticker-orders/quote'),
      headers: headers,
      body: jsonEncode({'mode': mode, 'design_count': designCount}),
    );
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    if (response.statusCode != 200) {
      throw SyncApiException(
          body['error']?.toString() ?? 'No se pudo cotizar el pedido',
          statusCode: response.statusCode);
    }
    return StickerQuote.fromJson(body);
  }

  void close() => _httpClient.close();
}
