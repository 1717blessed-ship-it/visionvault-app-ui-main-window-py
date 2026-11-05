import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

import '../models/visit_attachment.dart';
import '../models/visit_history_entry.dart';
import '../models/visit_pin.dart';
import 'timeout_http_client.dart';

class VisitSyncConflict implements Exception {
  final VisitPin remote;
  const VisitSyncConflict(this.remote);
}

class VisitSyncApiClient {
  final String baseUrl;
  final String sessionToken;
  final http.Client _client;

  VisitSyncApiClient(
      {required this.baseUrl, required this.sessionToken, http.Client? client})
      : _client = TimeoutHttpClient(client ?? http.Client());

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $sessionToken'
      };

  Future<VisitPin> upsert(VisitPin pin, {bool force = false}) async {
    final response =
        await _client.post(Uri.parse('$baseUrl/api/v1/mobile/visits'),
            headers: _headers,
            body: jsonEncode({
              ...pin.toMap(),
              'client_uuid': pin.clientUuid,
              'force': force,
            }));
    if (response.statusCode == 409) {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      throw VisitSyncConflict(
          VisitPin.fromMap(Map<String, Object?>.from(body['visit'] as Map)));
    }
    if (response.statusCode != 200) {
      throw StateError('No se pudo sincronizar la visita.');
    }
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    return VisitPin.fromMap(Map<String, Object?>.from(body['visit'] as Map));
  }

  Future<List<VisitPin>> pull() async {
    final response = await _client
        .get(Uri.parse('$baseUrl/api/v1/mobile/visits'), headers: _headers);
    if (response.statusCode != 200) {
      throw StateError('No se pudieron descargar las visitas.');
    }
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    return (body['visits'] as List<dynamic>? ?? const [])
        .map((item) => VisitPin.fromMap(Map<String, Object?>.from(item as Map)))
        .toList();
  }

  Future<void> delete(String clientUuid) async {
    final response = await _client.post(
        Uri.parse('$baseUrl/api/v1/mobile/visits/delete'),
        headers: _headers,
        body: jsonEncode({'client_uuid': clientUuid}));
    if (response.statusCode != 200) {
      throw StateError('No se pudo eliminar la visita sincronizada.');
    }
  }

  Future<void> upsertHistory(VisitHistoryEntry entry) async {
    final response = await _client.post(
      Uri.parse('$baseUrl/api/v1/mobile/visits/history'),
      headers: _headers,
      body: jsonEncode(entry.toJson()),
    );
    if (response.statusCode != 200) {
      throw StateError('No se pudo sincronizar el historial.');
    }
  }

  Future<List<VisitHistoryEntry>> pullHistory() async {
    final response = await _client.get(
      Uri.parse('$baseUrl/api/v1/mobile/visits/history'),
      headers: _headers,
    );
    if (response.statusCode != 200) {
      throw StateError('No se pudo descargar el historial.');
    }
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    return (body['history'] as List<dynamic>? ?? const [])
        .map((item) =>
            VisitHistoryEntry.fromMap(Map<String, Object?>.from(item as Map)))
        .toList();
  }

  Future<void> uploadAttachment(VisitAttachment attachment) async {
    final request = http.MultipartRequest(
        'POST', Uri.parse('$baseUrl/api/v1/mobile/visits/attachments'));
    request.headers['Authorization'] = 'Bearer $sessionToken';
    request.files.add(http.MultipartFile.fromString(
      'metadata',
      jsonEncode({
        'attachment_uuid': attachment.attachmentUuid,
        'client_uuid': attachment.clientUuid,
        'created_at': attachment.createdAt.toUtc().toIso8601String(),
      }),
    ));
    request.files.add(await http.MultipartFile.fromPath(
      'images',
      attachment.localPath,
      filename: attachment.fileName,
      contentType: MediaType.parse(attachment.mimeType),
    ));
    final response = await request.send().timeout(const Duration(seconds: 45));
    if (response.statusCode != 200) {
      throw StateError('No se pudo sincronizar la foto.');
    }
  }

  Future<List<VisitAttachment>> pullAttachmentMetadata() async {
    final response = await _client.get(
      Uri.parse('$baseUrl/api/v1/mobile/visits/attachments'),
      headers: _headers,
    );
    if (response.statusCode != 200) {
      throw StateError('No se pudieron descargar los adjuntos.');
    }
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    return (body['attachments'] as List<dynamic>? ?? const [])
        .map((item) => VisitAttachment.fromMap({
              ...Map<String, Object?>.from(item as Map),
              'local_path': '',
              'sync_dirty': 0,
              'deleted': 0,
            }))
        .toList();
  }

  Future<Uint8List> downloadAttachment(String attachmentUuid) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/api/v1/mobile/visits/attachments/$attachmentUuid'),
      headers: _headers,
    );
    if (response.statusCode != 200) {
      throw StateError('No se pudo descargar la foto.');
    }
    return response.bodyBytes;
  }

  void close() => _client.close();
}
