import 'package:doccione_mobile/models/visit_pin.dart';
import 'package:doccione_mobile/services/visit_clusterer.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  VisitPin pin(String id, double latitude, double longitude) => VisitPin(
        title: id,
        latitude: latitude,
        longitude: longitude,
        createdAt: DateTime(2026, 8, 12),
        clientUuid: id,
      );

  test('agrupa visitas cercanas y mantiene separadas las lejanas', () {
    final clusters = VisitClusterer.cluster([
      pin('a', -27.4810, -55.1170),
      pin('b', -27.4811, -55.1171),
      pin('c', -27.50, -55.14),
    ], 13);

    expect(clusters, hasLength(2));
    expect(clusters.map((cluster) => cluster.pins.length), containsAll([1, 2]));
  });

  test('al acercar el mapa desagrupa puntos suficientemente separados', () {
    final pins = [
      pin('a', -27.4810, -55.1170),
      pin('b', -27.4815, -55.1175),
    ];

    expect(VisitClusterer.cluster(pins, 11), hasLength(1));
    expect(VisitClusterer.cluster(pins, 18), hasLength(2));
  });
}
