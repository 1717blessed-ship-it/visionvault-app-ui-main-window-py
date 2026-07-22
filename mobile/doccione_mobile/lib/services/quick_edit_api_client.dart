import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'sync_api_client.dart';

/// Result of a quick-edit API call
class QuickEditResult {
  final bool success;
  final String? errorMessage;
  final Map<String, dynamic>? data;

  const QuickEditResult.success(this.data) : success = true, errorMessage = null;
  const QuickEditResult.failure(this.errorMessage) : success = false, data = null;
}

/// HTTP client for quick-edit actions from mobile
class QuickEditApiClient {
  final String baseUrl;
  final String? authToken;
  final Duration timeout;
  final http.Client _httpClient;

  QuickEditApiClient({
    required this.baseUrl,
    this.authToken,
    this.timeout = const Duration(seconds: 15),
    http.Client? httpClient,
  }) : _httpClient = httpClient ?? http.Client();

  /// PATCH /api/v1/mobile/orders/{id}/status
  Future<QuickEditResult> updateOrderStatus(int orderId, String status) async {
    return _patch(
      '/api/v1/mobile/orders/$orderId/status',
      {'status': status},
    );
  }

  /// PATCH /api/v1/mobile/orders/{id}/priority
  Future<QuickEditResult> updateOrderPriority(int orderId, int priority) async {
    return _patch(
      '/api/v1/mobile/orders/$orderId/priority',
      {'print_priority': priority},
    );
  }

  /// PATCH /api/v1/mobile/orders/{oid}/jobs/{jid}
  Future<QuickEditResult> updateJobFields(
    int orderId,
    int jobId, {
    int? quantity,
    String? size,
  }) async {
    final body = <String, dynamic>{};
    if (quantity != null) body['quantity'] = quantity;
    if (size != null) body['size'] = size;
    return _patch(
      '/api/v1/mobile/orders/$orderId/jobs/$jobId',
      body,
    );
  }

  /// POST /api/v1/mobile/orders/{id}/payments
  Future<QuickEditResult> registerPayment(
    int orderId, {
    required double amount,
    String method = '',
    String note = '',
  }) async {
    return _post(
      '/api/v1/mobile/orders/$orderId/payments',
      {'amount': amount, 'method': method, 'note': note},
    );
  }

  /// POST /api/v1/mobile/orders/{id}/deliver
  Future<QuickEditResult> markDelivered(int orderId) async {
    return _post(
      '/api/v1/mobile/orders/$orderId/deliver',
      {},
    );
  }

  /// POST /api/v1/mobile/jobs/{id}/stage (existing endpoint)
  Future<QuickEditResult> changeJobStage(int jobId, String stage) async {
    return _post(
      '/api/v1/mobile/jobs/$jobId/stage',
      {'stage': stage},
    );
  }

  // ── Private helpers ────────────────────────────────────────────────────

  Future<QuickEditResult> _patch(String path, Map<String, dynamic> body) async {
    try {
      final uri = Uri.parse('$baseUrl$path');
      final response = await _httpClient
          .patch(uri, headers: _buildHeaders(), body: jsonEncode(body))
          .timeout(timeout);
      return _handleResponse(response);
    } on TimeoutException {
      return const QuickEditResult.failure('Tiempo de espera agotado');
    } on http.ClientException {
      return const QuickEditResult.failure('Error de red');
    } catch (e) {
      if (_isConnectionError(e)) {
        return const QuickEditResult.failure('Sin conexión al servidor');
      }
      return QuickEditResult.failure('Error inesperado: $e');
    }
  }

  Future<QuickEditResult> _post(String path, Map<String, dynamic> body) async {
    try {
      final uri = Uri.parse('$baseUrl$path');
      final response = await _httpClient
          .post(uri, headers: _buildHeaders(), body: jsonEncode(body))
          .timeout(timeout);
      return _handleResponse(response);
    } on TimeoutException {
      return const QuickEditResult.failure('Tiempo de espera agotado');
    } on http.ClientException {
      return const QuickEditResult.failure('Error de red');
    } catch (e) {
      if (_isConnectionError(e)) {
        return const QuickEditResult.failure('Sin conexión al servidor');
      }
      return QuickEditResult.failure('Error inesperado: $e');
    }
  }

  QuickEditResult _handleResponse(http.Response response) {
    if (response.statusCode >= 200 && response.statusCode < 300) {
      try {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        return QuickEditResult.success(data);
      } catch (_) {
        return const QuickEditResult.success(null);
      }
    }

    String message;
    try {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      message = body['error'] ?? 'Error del servidor';
    } catch (_) {
      message = 'Error del servidor (${response.statusCode})';
    }

    return QuickEditResult.failure(message);
  }

  Map<String, String> _buildHeaders() {
    final headers = <String, String>{
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    };
    if (authToken != null) {
      headers['Authorization'] = 'Bearer $authToken';
    }
    return headers;
  }

  static bool _isConnectionError(Object e) {
    final msg = e.toString();
    return msg.contains('Connection refused') ||
        msg.contains('Failed host lookup') ||
        msg.contains('No address associated') ||
        msg.contains('SocketException');
  }

  void close() {
    _httpClient.close();
  }
}
