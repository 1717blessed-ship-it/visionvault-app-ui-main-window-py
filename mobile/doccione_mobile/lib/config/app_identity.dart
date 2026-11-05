import 'package:package_info_plus/package_info_plus.dart';

/// Identidad de la compilación instalada. Nunca debe duplicarse a mano: Studio
/// recibe exactamente la versión declarada por Android/iOS.
class AppIdentity {
  AppIdentity._();

  static String _version = '0.0.0';
  static String _buildNumber = '0';

  static String get version => _version;
  static String get buildNumber => _buildNumber;
  static String get fullVersion => '$_version+$_buildNumber';

  static Future<void> initialize() async {
    final info = await PackageInfo.fromPlatform();
    _version = info.version;
    _buildNumber = info.buildNumber;
  }
}
