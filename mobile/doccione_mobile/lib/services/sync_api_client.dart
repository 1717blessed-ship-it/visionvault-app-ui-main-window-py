import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/connection_test_result.dart';

/// Exception thrown when a sync API call fails
class SyncApiException implements Exception {
  final String message;
  final int? statusCode;
  final dynamic originalError;

  SyncApiException(this.message, {this.statusCode, this.originalError});

  @override
  String toString() {
    if (statusCode != null) {
      return 'SyncApiException($statusCode): $message';
    }
    return 'SyncApiException: $message';
  }
}

/// HTTP client for synchronization API endpoints
class SyncApiClient {
  final String baseUrl;
  final String? authToken;
  final Duration timeout;
  final http.Client _httpClient;

  SyncApiClient({
    required this.baseUrl,
    this.authToken,
    this.timeout = const Duration(seconds: 30),
    http.Client? httpClient,
  }) : _httpClient = httpClient ?? http.Client();

  /// Get server capabilities
  /// GET /api/v1/mobile/capabilities
  Future<Map<String, dynamic>> getCapabilities() async {
    try {
      final uri = Uri.parse('$baseUrl/api/v1/mobile/capabilities');
      final headers = _buildHeaders();

      final response = await _httpClient
          .get(uri, headers: headers)
          .timeout(timeout);

      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      } else {
        throw SyncApiException(
          'Failed to get capabilities: ${response.body}',
          statusCode: response.statusCode,
        );
      }
    } on TimeoutException catch (e) {
      throw SyncApiException('Request timeout', originalError: e);
    } on http.ClientException catch (e) {
      throw SyncApiException('Network error', originalError: e);
    } catch (e) {
      throw SyncApiException('Unexpected error: \$e', originalError: e);
    }
  }

  /// Test connection to the server using GET /api/v1/mobile/health
  /// Validates: status == "ok", service == "doccione-studio",
  /// api_version == "v1", mobile_api == true
  Future<ConnectionTestResult> testConnection() async {
    final stopwatch = Stopwatch()..start();

    try {
      final uri = Uri.parse('$baseUrl/api/v1/mobile/health');
      final headers = _buildHeaders();

      final response = await _httpClient
          .get(uri, headers: headers)
          .timeout(timeout);

      stopwatch.stop();

      if (response.statusCode == 200) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;

        final status = body['status'];
        final service = body['service'];
        final apiVersion = body['api_version'];
        final mobileApi = body['mobile_api'];

        if (status == 'ok' &&
            service == 'doccione-studio' &&
            apiVersion == 'v1' &&
            mobileApi == true) {
          return ConnectionTestResult.ok(
            responseTime: stopwatch.elapsed,
            healthInfo: body,
          );
        } else {
          final details = <String>[];
          if (status != 'ok') details.add('status: $status');
          if (service != 'doccione-studio') details.add('service: $service');
          if (apiVersion != 'v1') details.add('api_version: $apiVersion');
          if (mobileApi != true) details.add('mobile_api: $mobileApi');

          return ConnectionTestResult.unexpected(
            detail: 'Respuesta inválida: ${details.join(', ')}',
          );
        }
      } else if (response.statusCode == 401 || response.statusCode == 403) {
        return ConnectionTestResult.unauthorized(statusCode: response.statusCode);
      } else if (response.statusCode >= 500) {
        return ConnectionTestResult.serverError(statusCode: response.statusCode);
      } else {
        return ConnectionTestResult.unexpected(
          detail: 'Código inesperado: ${response.statusCode}',
        );
      }
    } on TimeoutException {
      stopwatch.stop();
      return ConnectionTestResult.timeout();
    } on http.ClientException {
      stopwatch.stop();
      return ConnectionTestResult.networkError();
    } catch (e) {
      stopwatch.stop();
      final message = e.toString();
      if (message.contains('Connection refused') ||
          message.contains('Failed host lookup') ||
          message.contains('No address associated')) {
        return ConnectionTestResult.networkError();
      }
      return ConnectionTestResult.unexpected(detail: e.toString());
    }
  }

  /// Pull synchronization data
  /// GET /api/v1/mobile/sync/pull?cursor=<cursor>&limit=<limit>
  Future<Map<String, dynamic>> syncPull({
    String? cursor,
    int limit = 100,
  }) async {
    try {
      final queryParams = <String, String>{
        'limit': limit.toString(),
      };
      
      if (cursor != null) {
        queryParams['cursor'] = cursor;
      }

      final uri = Uri.parse('$baseUrl/api/v1/mobile/sync/pull')
          .replace(queryParameters: queryParams);
      final headers = _buildHeaders();

      final response = await _httpClient
          .get(uri, headers: headers)
          .timeout(timeout);

      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      } else if (response.statusCode == 400) {
        final body = jsonDecode(response.body);
        throw SyncApiException(
          'Invalid request: ${body['error'] ?? response.body}',
          statusCode: response.statusCode,
        );
      } else if (response.statusCode == 401) {
        throw SyncApiException(
          'Unauthorized: Invalid or expired token',
          statusCode: response.statusCode,
        );
      } else {
        throw SyncApiException(
          'Sync pull failed: ${response.body}',
          statusCode: response.statusCode,
        );
      }
    } on TimeoutException catch (e) {
      throw SyncApiException('Request timeout', originalError: e);
    } on http.ClientException catch (e) {
      throw SyncApiException('Network error', originalError: e);
    } on SyncApiException {
      rethrow;
    } catch (e) {
      throw SyncApiException('Unexpected error: \$e', originalError: e);
    }
  }

  /// Build common headers for API requests
  Map<String, String> _buildHeaders() {
    final headers = <String, String>{
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    };

    if (authToken != null) {
      headers['Authorization'] = 'Bearer \$authToken';
    }

    return headers;
  }

  /// Close the HTTP client
  void close() {
    _httpClient.close();
  }
}
