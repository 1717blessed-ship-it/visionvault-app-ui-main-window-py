class ServerConfig {
  final String host;
  final int port;
  final String scheme;

  const ServerConfig({
    required this.host,
    required this.port,
    required this.scheme,
  });

  String get baseUrl => '$scheme://$host:$port';

  static const ServerConfig defaults = ServerConfig(
    host: 'localhost',
    port: 8765,
    scheme: 'http',
  );

  static bool isValidHost(String host) {
    if (host.isEmpty || host.length > 255) return false;
    // Permitir localhost, IPs, y hostnames simples
    final ipPattern = RegExp(
      r'^(localhost|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|[a-zA-Z0-9\-\.]+)$',
    );
    return ipPattern.hasMatch(host);
  }

  static bool isValidPort(int port) {
    return port >= 1 && port <= 65535;
  }

  static bool isValidScheme(String scheme) {
    return scheme == 'http' || scheme == 'https';
  }

  static bool isValid(String host, int port, String scheme) {
    return isValidHost(host) && isValidPort(port) && isValidScheme(scheme);
  }

  Map<String, dynamic> toMap() => {
    'host': host,
    'port': port,
    'scheme': scheme,
  };

  factory ServerConfig.fromMap(Map<String, dynamic> map) => ServerConfig(
    host: map['host'] as String? ?? 'localhost',
    port: map['port'] as int? ?? 8765,
    scheme: map['scheme'] as String? ?? 'http',
  );

  ServerConfig copyWith({String? host, int? port, String? scheme}) {
    return ServerConfig(
      host: host ?? this.host,
      port: port ?? this.port,
      scheme: scheme ?? this.scheme,
    );
  }

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is ServerConfig &&
          host == other.host &&
          port == other.port &&
          scheme == other.scheme;

  @override
  int get hashCode => Object.hash(host, port, scheme);

  @override
  String toString() => 'ServerConfig($baseUrl)';
}
