import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('recibo HTTP real tiene identidades y revisión confirmadas', () {
    // Explicit cross-runtime test. Run pytest test_order_sync_http.py first.
    // Kept outside test/ so the ordinary Mobile suite needs no generated artifact.
    final data = jsonDecode(
        File('../../artifacts/s2a2-http-contract-response.json')
            .readAsStringSync()) as Map<String, dynamic>;
    expect(data['contract_version'], 1);
    expect(data['persisted'], true);
    expect(data['desktop_order_id'], isA<String>());
    expect(int.parse(data['desktop_order_id'] as String), greaterThan(0));
    expect(data['revision'], isA<int>());
    final snapshot = data['snapshot'] as Map<String, dynamic>;
    expect(snapshot['revision'], data['revision']);
    expect(snapshot['desktop_order_id'], data['desktop_order_id']);
    expect((snapshot['jobs'] as List).map((j) => j['unit_kind']),
        ['item', 'sheet']);
  });
}
