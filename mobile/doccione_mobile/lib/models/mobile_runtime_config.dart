class RuntimePriority {
  final int value;
  final String label;

  const RuntimePriority(this.value, this.label);

  factory RuntimePriority.fromJson(Map<String, dynamic> json) =>
      RuntimePriority(
        (json['value'] as num? ?? 0).toInt(),
        json['label']?.toString() ?? 'Prioridad',
      );
}

class MobileRuntimeConfig {
  static const _defaultFeatures = {
    'design_catalog': true,
    'product_catalog': true,
    'sticker_orders': true,
    'quick_edits': true,
    'payments': true,
    'push_notifications': true,
  };

  static const _defaultWorkflow = [
    'Recibido',
    'Esperando archivos',
    'Diseños confirmados',
    'Listo para armado de planchas',
    'En armado de planchas',
    'Listo para imprimir',
    'Impresión',
    'Sublimado / Laminado',
    'Corte',
    'Control de calidad',
    'Finalizado',
    'Entregado',
  ];

  static const defaults = MobileRuntimeConfig(
    features: _defaultFeatures,
    announcementEnabled: false,
    announcementTitle: '',
    announcementMessage: '',
    maintenanceEnabled: false,
    maintenanceMessage: '',
    minimumAppVersion: '1.0.0',
    recommendedAppVersion: '1.0.2',
    updateUrl: '',
    workflowStages: _defaultWorkflow,
    stageColors: {},
    materials: [
      'Vinilo Full Color HD',
      'Vinilo Premium',
      'Vinilo Ploteado',
      'Resina 3D Premium',
      'Otro',
    ],
    paymentMethods: [
      'Efectivo',
      'Transferencia',
      'Mercado Pago',
      'Otro',
    ],
    stickerModes: ['Plancha A4', 'Plancha A5', 'Franja', 'Individuales'],
    orderStatuses: [
      'Pendiente',
      'En producción',
      'Finalizado',
      'Entregado',
      'Cancelado',
      'Archivado',
    ],
    priorities: [
      RuntimePriority(0, 'Sin prisa'),
      RuntimePriority(1, 'Baja'),
      RuntimePriority(2, 'Media'),
      RuntimePriority(3, 'Alta'),
      RuntimePriority(4, 'Urgente'),
    ],
  );

  final Map<String, bool> features;
  final bool announcementEnabled;
  final String announcementTitle;
  final String announcementMessage;
  final bool maintenanceEnabled;
  final String maintenanceMessage;
  final String minimumAppVersion;
  final String recommendedAppVersion;
  final String updateUrl;
  final List<String> workflowStages;
  final Map<String, int> stageColors;
  final List<String> materials;
  final List<String> paymentMethods;
  final List<String> stickerModes;
  final List<String> orderStatuses;
  final List<RuntimePriority> priorities;

  const MobileRuntimeConfig({
    required this.features,
    required this.announcementEnabled,
    required this.announcementTitle,
    required this.announcementMessage,
    required this.maintenanceEnabled,
    required this.maintenanceMessage,
    required this.minimumAppVersion,
    required this.recommendedAppVersion,
    required this.updateUrl,
    required this.workflowStages,
    required this.stageColors,
    required this.materials,
    required this.paymentMethods,
    required this.stickerModes,
    required this.orderStatuses,
    required this.priorities,
  });

  bool featureEnabled(String key) => features[key] ?? true;

  bool requiresUpgrade(String currentVersion) =>
      _compareVersions(currentVersion, minimumAppVersion) < 0;

  bool recommendsUpgrade(String currentVersion) =>
      _compareVersions(currentVersion, recommendedAppVersion) < 0;

  factory MobileRuntimeConfig.fromCapabilities(Map<String, dynamic> data) {
    final rawRuntime = data['runtime_config'];
    if (rawRuntime is! Map) return defaults;
    final runtime = Map<String, dynamic>.from(rawRuntime);
    final references = _map(runtime['references']);
    final workflows = _map(references['workflows']);
    final general = _map(workflows['general']);

    final features = Map<String, bool>.from(_defaultFeatures);
    final rawFeatures = _map(runtime['features']);
    for (final entry in rawFeatures.entries) {
      if (entry.value is bool) features[entry.key] = entry.value as bool;
    }

    final stages = _mapList(references['stages']);
    final colors = <String, int>{};
    for (final stage in stages) {
      final key = stage['key']?.toString() ?? '';
      final color = _parseColor(stage['color']?.toString());
      if (key.isNotEmpty && color != null) colors[key] = color;
    }

    final announcement = _map(runtime['announcement']);
    final maintenance = _map(runtime['maintenance']);
    final compatibility = _map(runtime['compatibility']);

    return MobileRuntimeConfig(
      features: Map.unmodifiable(features),
      announcementEnabled: announcement['enabled'] == true,
      announcementTitle: announcement['title']?.toString() ?? '',
      announcementMessage: announcement['message']?.toString() ?? '',
      maintenanceEnabled: maintenance['enabled'] == true,
      maintenanceMessage: maintenance['message']?.toString() ?? '',
      minimumAppVersion:
          compatibility['minimum_app_version']?.toString() ?? '1.0.0',
      recommendedAppVersion:
          compatibility['recommended_app_version']?.toString() ?? '1.0.2',
      updateUrl: compatibility['update_url']?.toString() ?? '',
      workflowStages: _strings(general['stages'], defaults.workflowStages),
      stageColors: Map.unmodifiable(colors),
      materials: _withOther(
        _strings(references['materials'], defaults.materials),
      ),
      paymentMethods: _withOther(
        _strings(references['payment_methods'], defaults.paymentMethods),
      ),
      stickerModes:
          _strings(references['sticker_modes'], defaults.stickerModes),
      orderStatuses:
          _strings(references['order_statuses'], defaults.orderStatuses),
      priorities: _priorities(references['priorities']),
    );
  }

  static List<RuntimePriority> _priorities(dynamic value) {
    final parsed = _mapList(value)
        .map(RuntimePriority.fromJson)
        .where((item) => item.label.trim().isNotEmpty)
        .toList(growable: false);
    return parsed.isEmpty ? defaults.priorities : parsed;
  }

  static List<String> _strings(dynamic value, List<String> fallback) {
    if (value is! List) return fallback;
    final values = <String>[];
    final seen = <String>{};
    for (final item in value) {
      final clean = item.toString().trim();
      if (clean.isNotEmpty && seen.add(clean.toLowerCase())) values.add(clean);
    }
    return values.isEmpty ? fallback : List.unmodifiable(values);
  }

  static List<String> _withOther(List<String> values) {
    if (values.any((value) => value.toLowerCase() == 'otro')) return values;
    return List.unmodifiable([...values, 'Otro']);
  }

  static Map<String, dynamic> _map(dynamic value) =>
      value is Map ? Map<String, dynamic>.from(value) : <String, dynamic>{};

  static List<Map<String, dynamic>> _mapList(dynamic value) => value is List
      ? value
          .whereType<Map>()
          .map((item) => Map<String, dynamic>.from(item))
          .toList(growable: false)
      : const [];

  static int? _parseColor(String? value) {
    if (value == null) return null;
    final clean = value.replaceFirst('#', '');
    if (clean.length != 6) return null;
    final rgb = int.tryParse(clean, radix: 16);
    return rgb == null ? null : 0xFF000000 | rgb;
  }

  static int _compareVersions(String left, String right) {
    final leftParts = _versionParts(left);
    final rightParts = _versionParts(right);
    final length = leftParts.length > rightParts.length
        ? leftParts.length
        : rightParts.length;
    for (var index = 0; index < length; index++) {
      final a = index < leftParts.length ? leftParts[index] : 0;
      final b = index < rightParts.length ? rightParts[index] : 0;
      if (a != b) return a.compareTo(b);
    }
    return 0;
  }

  static List<int> _versionParts(String version) => version
      .split('+')
      .first
      .split('.')
      .map((part) => int.tryParse(part.replaceAll(RegExp(r'[^0-9]'), '')) ?? 0)
      .toList(growable: false);
}

class MobileRuntimeConfigStore {
  MobileRuntimeConfigStore._();

  static MobileRuntimeConfig current = MobileRuntimeConfig.defaults;

  static void apply(MobileRuntimeConfig config) {
    current = config;
  }

  static void reset() {
    current = MobileRuntimeConfig.defaults;
  }
}
