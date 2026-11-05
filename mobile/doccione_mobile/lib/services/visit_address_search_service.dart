import 'dart:convert';

import 'package:http/http.dart' as http;

class VisitAddressResult {
  final String label;
  final double latitude;
  final double longitude;
  const VisitAddressResult({
    required this.label,
    required this.latitude,
    required this.longitude,
  });
}

class VisitAddressSearchService {
  final http.Client _client;
  VisitAddressSearchService({http.Client? client})
      : _client = client ?? http.Client();

  Future<List<VisitAddressResult>> search(String query) async {
    if (query.trim().length < 3) return const [];
    final uri = Uri.https('nominatim.openstreetmap.org', '/search', {
      'q': '${query.trim()}, Oberá, Misiones, Argentina',
      'format': 'jsonv2',
      'limit': '6',
      'countrycodes': 'ar',
      'addressdetails': '1',
    });
    final response = await _client.get(uri, headers: {
      'Accept': 'application/json',
      'User-Agent': 'DoccioneMobile/1.0 (visit-map address search)',
    }).timeout(const Duration(seconds: 12));
    if (response.statusCode != 200) return const [];
    final items = jsonDecode(response.body) as List<dynamic>;
    return items.map((item) {
      final map = item as Map<String, dynamic>;
      return VisitAddressResult(
        label: map['display_name'] as String,
        latitude: double.parse(map['lat'] as String),
        longitude: double.parse(map['lon'] as String),
      );
    }).toList();
  }

  void close() => _client.close();
}
