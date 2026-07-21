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
    final db = await _dbHelper.database;
    await db.update(
      'server_config',
      config.toMap(),
      where: 'id = 1',
    );
  }
}
