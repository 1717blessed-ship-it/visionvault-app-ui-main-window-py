import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Identificador estable del vendedor activo. Se usa para que ninguna cola
/// local se comparta entre dos sesiones del mismo teléfono.
class SessionScope {
  SessionScope._();

  static const _storage = FlutterSecureStorage();

  static Future<String?> current() async {
    final value = (await _storage.read(key: 'seller_user_id'))?.trim();
    return value == null || value.isEmpty ? null : 'user:$value';
  }

  static Future<String> requireCurrent() async {
    final value = await current();
    if (value == null) {
      throw StateError('No se pudo identificar al vendedor de esta sesión.');
    }
    return value;
  }
}
