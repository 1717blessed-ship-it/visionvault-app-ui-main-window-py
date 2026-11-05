import '../config/server_config.dart';
import 'database_helper.dart';

class ServerConfigRepository {
  final DatabaseHelper _dbHelper;

  ServerConfigRepository(this._dbHelper);

  Future<ServerConfig> getConfig() async {
    final db = await _dbHelper.database;
    final result = await db.query('server_config', where: 'id = 1');
    if (result.isEmpty) return ServerConfig.defaults;
    return ServerConfig.fromMap(result.first);
  }

  Future<void> updateConfig(ServerConfig config) async {
    if (!ServerConfig.isValid(config.host, config.port, config.scheme)) {
      throw ArgumentError.value(
          config, 'config', 'Configuración de servidor inválida');
    }
    final db = await _dbHelper.database;
    final updated = await db.update(
      'server_config',
      config.toMap(),
      where: 'id = 1',
    );
    if (updated == 0) {
      await db.insert('server_config', {'id': 1, ...config.toMap()});
    }
  }
}
