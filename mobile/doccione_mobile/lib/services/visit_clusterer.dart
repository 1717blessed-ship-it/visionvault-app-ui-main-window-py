import 'dart:math' as math;

import 'package:latlong2/latlong.dart';

import '../models/visit_pin.dart';

class VisitCluster {
  final List<VisitPin> pins;
  final LatLng center;
  const VisitCluster({required this.pins, required this.center});
  bool get isSingle => pins.length == 1;
}

abstract final class VisitClusterer {
  static List<VisitCluster> cluster(List<VisitPin> pins, double zoom) {
    if (pins.isEmpty) return const [];
    final cell = 0.055 / math.pow(2, math.max(0, zoom - 10));
    final buckets = <String, List<VisitPin>>{};
    for (final pin in pins) {
      final x = (pin.longitude / cell).floor();
      final y = (pin.latitude / cell).floor();
      buckets.putIfAbsent('$x:$y', () => []).add(pin);
    }
    return buckets.values.map((items) {
      final latitude = items.fold<double>(0, (sum, pin) => sum + pin.latitude) /
          items.length;
      final longitude =
          items.fold<double>(0, (sum, pin) => sum + pin.longitude) /
              items.length;
      return VisitCluster(
        pins: List.unmodifiable(items),
        center: LatLng(latitude, longitude),
      );
    }).toList();
  }
}
