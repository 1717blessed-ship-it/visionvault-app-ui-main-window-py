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
    if (host.isEmpty || host.length > 253 || host != host.trim()) return false;
    if (host == 'localhost') return true;

    final ipv4Parts = host.split('.');
    if (ipv4Parts.length == 4 && ipv4Parts.every((part) => part.isNotEmpty)) {
      return ipv4Parts.every((part) {
        final value = int.tryParse(part);
        return value != null &&
            value >= 0 &&
            value <= 255 &&
            (part == '0' || !part.startsWith('0'));
      });
    }

    // DNS hostnames only: reject URLs, paths, whitespace and invalid labels.
    final hostname = RegExp(
      r'^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?))*$',
    );
    return hostname.hasMatch(host);
  }

  static bool isValidPort(int port) {
    return port >= 1 && port <= 65535;
  }

  static bool isPrivateOrLocalHost(String host) {
    if (host == 'localhost' || host.endsWith('.local')) return true;
    final parts = host.split('.').map(int.tryParse).toList();
    if (parts.length != 4 || parts.any((part) => part == null)) return false;
    final a = parts[0]!;
    final b = parts[1]!;
    return a == 10 ||
        a == 127 ||
        (a == 100 && b >= 64 && b <= 127) ||
        (a == 192 && b == 168) ||
        (a == 172 && b >= 16 && b <= 31);
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
