import 'package:flutter/material.dart';
import '../config/server_config.dart';
import '../database/server_config_repository.dart';
import '../models/connection_test_result.dart';

class ServerConfigScreen extends StatefulWidget {
  final ServerConfigRepository repository;
  final Future<ConnectionTestResult> Function(String baseUrl)? onTestConnection;

  const ServerConfigScreen({
    super.key,
    required this.repository,
    this.onTestConnection,
  });

  @override
  State<ServerConfigScreen> createState() => _ServerConfigScreenState();
}

class _ServerConfigScreenState extends State<ServerConfigScreen> {
  final _formKey = GlobalKey<FormState>();
  final _hostController = TextEditingController();
  final _portController = TextEditingController();
  String _scheme = 'http';

  bool _isLoading = true;
  bool _isSaving = false;
  bool _isTesting = false;
  bool _isLocalNetwork = true;
  String? _error;
  String? _saveSuccess;
  ConnectionTestResult? _testResult;
  ServerConfig? _currentConfig;

  @override
  void initState() {
    super.initState();
    _loadConfig();
  }

  @override
  void dispose() {
    _hostController.dispose();
    _portController.dispose();
    super.dispose();
  }

  Future<void> _loadConfig() async {
    try {
      final config = await widget.repository.getConfig();
      final isLocal = ServerConfig.isPrivateOrLocalHost(config.host);
      if (!mounted) return;
      setState(() {
        _currentConfig = config;
        _hostController.text = config.host;
        _portController.text = config.port.toString();
        _scheme = isLocal ? config.scheme : 'https';
        _isLocalNetwork = isLocal;
        _isLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = 'Error al cargar configuración: $e';
        _isLoading = false;
      });
    }
  }

  void _setNetworkType(bool isLocal) {
    setState(() {
      _isLocalNetwork = isLocal;
      if (isLocal) {
        _scheme = 'http';
        _portController.text = '8765';
        if (!ServerConfig.isPrivateOrLocalHost(_hostController.text.trim())) {
          _hostController.text = '';
        }
      } else {
        _scheme = 'https';
        _portController.text = '443';
        if (ServerConfig.isPrivateOrLocalHost(_hostController.text.trim())) {
          _hostController.text = '';
        }
      }
    });
  }

  void _showNetworkHelp(BuildContext context) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Configuración de red'),
        content: const SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                'Conexión Local / VPN',
                style: TextStyle(fontWeight: FontWeight.bold),
              ),
              SizedBox(height: 8),
              Text(
                '• Ambos dispositivos en la misma red WiFi\n'
                '• O conectados por una VPN privada\n'
                '• Usa la IP privada de la PC (ej: 192.168.1.50)\n'
                '• Encuentra la IP en: Configuración de red de Windows',
              ),
              SizedBox(height: 16),
              Text(
                'Conexión Externa (Datos)',
                style: TextStyle(fontWeight: FontWeight.bold),
              ),
              SizedBox(height: 8),
              Text(
                '• Funciona desde cualquier red\n'
                '• Requiere un dominio público con HTTPS\n'
                '• Recomendado: reverse proxy con certificado TLS\n'
                '• No publiques el puerto HTTP directamente',
              ),
              SizedBox(height: 16),
              Text(
                'Cómo encontrar tu IP local:',
                style: TextStyle(fontWeight: FontWeight.bold),
              ),
              SizedBox(height: 8),
              Text(
                '1. Abre CMD en Windows\n'
                '2. Ejecuta: ipconfig\n'
                '3. Busca "Dirección IPv4" (ej: 192.168.1.50)',
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Entendido'),
          ),
        ],
      ),
    );
  }

  Future<bool> _saveConfig() async {
    if (!_formKey.currentState!.validate()) return false;
    if (!_isLocalNetwork && _scheme != 'https') {
      setState(() {
        _error = 'HTTPS es obligatorio para conexiones externas.';
      });
      return false;
    }

    setState(() {
      _isSaving = true;
      _error = null;
      _saveSuccess = null;
    });

    try {
      final host = _hostController.text.trim();
      final port = int.parse(_portController.text.trim());
      final config = ServerConfig(
        host: host,
        port: port,
        scheme: _scheme,
      );

      await widget.repository.updateConfig(config);

      if (!mounted) return false;
      setState(() {
        _currentConfig = config;
        _isSaving = false;
        _saveSuccess = 'Configuración guardada correctamente';
      });
      return true;
    } catch (e) {
      if (!mounted) return false;
      setState(() {
        _isSaving = false;
        _error = 'Error al guardar: $e';
      });
      return false;
    }
  }

  Future<void> _testConnection() async {
    if (widget.onTestConnection == null) return;
    if (!_formKey.currentState!.validate()) return;

    setState(() {
      _isTesting = true;
      _testResult = null;
      _error = null;
      _saveSuccess = null;
    });

    try {
      final baseUrl = _baseUrlPreview;
      var result = await widget.onTestConnection!(baseUrl);
      if (!mounted) return;

      if (result.success) {
        final saved = await _saveConfig();
        if (!mounted) return;
        if (!saved) {
          result = ConnectionTestResult.unexpected(
            detail:
                'La conexión funciona, pero no se pudo guardar la configuración.',
          );
        }
      }

      setState(() {
        _isTesting = false;
        _testResult = result;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _isTesting = false;
        _testResult = ConnectionTestResult.unexpected(detail: e.toString());
      });
    }
  }

  String get _baseUrlPreview {
    final host = _hostController.text.trim();
    final port = _portController.text.trim();
    if (host.isEmpty || port.isEmpty) return '';
    return '$_scheme://$host:$port';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Configuración del Servidor'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // URL Preview
                    if (_baseUrlPreview.isNotEmpty) ...[
                      Card(
                        child: Padding(
                          padding: const EdgeInsets.all(16),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'URL del servidor',
                                style: Theme.of(context).textTheme.labelSmall,
                              ),
                              const SizedBox(height: 4),
                              Text(
                                _baseUrlPreview,
                                style: Theme.of(context)
                                    .textTheme
                                    .titleMedium
                                    ?.copyWith(
                                      fontFamily: 'monospace',
                                    ),
                              ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(height: 16),
                    ],

                    // Network type selection
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Tipo de conexión',
                              style: Theme.of(context).textTheme.labelMedium,
                            ),
                            const SizedBox(height: 12),
                            Wrap(
                              spacing: 8,
                              runSpacing: 8,
                              children: [
                                _NetworkTypeChip(
                                  label: 'Local / VPN',
                                  icon: Icons.wifi,
                                  isSelected: _isLocalNetwork,
                                  onTap: () => _setNetworkType(true),
                                ),
                                _NetworkTypeChip(
                                  label: 'Externa (Datos)',
                                  icon: Icons.public,
                                  isSelected: !_isLocalNetwork,
                                  onTap: () => _setNetworkType(false),
                                ),
                              ],
                            ),
                            const SizedBox(height: 8),
                            Text(
                              _isLocalNetwork
                                  ? 'Usa la IP privada de la PC en WiFi o VPN'
                                  : 'Usa un dominio público protegido con HTTPS',
                              style: Theme.of(context)
                                  .textTheme
                                  .bodySmall
                                  ?.copyWith(
                                    color: Colors.grey[600],
                                  ),
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // Host
                    TextFormField(
                      controller: _hostController,
                      decoration: InputDecoration(
                        labelText: 'Host o Dirección IP',
                        hintText:
                            _isLocalNetwork ? '192.168.1.50' : 'tu-dominio.com',
                        border: const OutlineInputBorder(),
                        helperText: _isLocalNetwork
                            ? 'IP privada de la PC en la red local o VPN'
                            : 'Dominio o IP pública del servidor',
                        suffixIcon: IconButton(
                          icon: const Icon(Icons.info_outline),
                          onPressed: () => _showNetworkHelp(context),
                        ),
                      ),
                      validator: (value) {
                        if (value == null || value.trim().isEmpty) {
                          return 'El host es obligatorio';
                        }
                        if (value.contains(' ')) {
                          return 'El host no debe contener espacios';
                        }
                        if (!ServerConfig.isValidHost(value.trim())) {
                          return 'Host no válido';
                        }
                        if (!_isLocalNetwork &&
                            ServerConfig.isPrivateOrLocalHost(value.trim())) {
                          return 'Usá un dominio público; para VPN elegí Local / VPN';
                        }
                        return null;
                      },
                      onChanged: (_) => setState(() {}),
                    ),
                    const SizedBox(height: 16),

                    // Port
                    TextFormField(
                      controller: _portController,
                      decoration: const InputDecoration(
                        labelText: 'Puerto',
                        hintText: '8765',
                        border: OutlineInputBorder(),
                      ),
                      keyboardType: TextInputType.number,
                      validator: (value) {
                        if (value == null || value.trim().isEmpty) {
                          return 'El puerto es obligatorio';
                        }
                        final port = int.tryParse(value.trim());
                        if (port == null) {
                          return 'Debe ser un número';
                        }
                        if (!ServerConfig.isValidPort(port)) {
                          return 'Puerto debe estar entre 1 y 65535';
                        }
                        return null;
                      },
                      onChanged: (_) => setState(() {}),
                    ),
                    const SizedBox(height: 16),

                    // Scheme
                    DropdownButtonFormField<String>(
                      key: ValueKey('scheme-$_scheme-$_isLocalNetwork'),
                      initialValue: _scheme,
                      decoration: const InputDecoration(
                        labelText: 'Esquema',
                        border: OutlineInputBorder(),
                      ),
                      items: _isLocalNetwork
                          ? const [
                              DropdownMenuItem(
                                value: 'http',
                                child: Text('HTTP (solo red local)'),
                              ),
                              DropdownMenuItem(
                                value: 'https',
                                child: Text('HTTPS'),
                              ),
                            ]
                          : const [
                              DropdownMenuItem(
                                value: 'https',
                                child: Text('HTTPS'),
                              ),
                            ],
                      onChanged: (value) {
                        if (value != null) {
                          setState(() => _scheme = value);
                        }
                      },
                    ),
                    if (!_isLocalNetwork) ...[
                      const SizedBox(height: 8),
                      const Text(
                        'HTTPS es obligatorio para proteger usuario, contraseña y pedidos fuera de la red local.',
                        style: TextStyle(color: Colors.orange, fontSize: 12),
                      ),
                    ],
                    const SizedBox(height: 24),

                    // Error message
                    if (_error != null) ...[
                      Card(
                        color: Theme.of(context).colorScheme.errorContainer,
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Row(
                            children: [
                              Icon(
                                Icons.error,
                                color: Theme.of(context).colorScheme.error,
                              ),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  _error!,
                                  style: TextStyle(
                                    color: Theme.of(context).colorScheme.error,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(height: 16),
                    ],

                    // Success message
                    if (_saveSuccess != null) ...[
                      Card(
                        color: Theme.of(context).colorScheme.primaryContainer,
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Row(
                            children: [
                              Icon(
                                Icons.check_circle,
                                color: Theme.of(context).colorScheme.primary,
                              ),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  _saveSuccess!,
                                  style: TextStyle(
                                    color:
                                        Theme.of(context).colorScheme.primary,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(height: 16),
                    ],

                    // Test result
                    if (_testResult != null) ...[
                      Card(
                        color: _testResult!.success
                            ? Theme.of(context).colorScheme.primaryContainer
                            : Theme.of(context).colorScheme.errorContainer,
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Row(
                            children: [
                              Icon(
                                _testResult!.success
                                    ? Icons.check_circle
                                    : Icons.error,
                                color: _testResult!.success
                                    ? Theme.of(context).colorScheme.primary
                                    : Theme.of(context).colorScheme.error,
                              ),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      _testResult!.message,
                                      style: TextStyle(
                                        color: _testResult!.success
                                            ? Theme.of(context)
                                                .colorScheme
                                                .primary
                                            : Theme.of(context)
                                                .colorScheme
                                                .error,
                                      ),
                                    ),
                                    if (_testResult!.responseTime != null) ...[
                                      const SizedBox(height: 4),
                                      Text(
                                        'Latencia: ${_testResult!.responseTime!.inMilliseconds}ms',
                                        style: Theme.of(context)
                                            .textTheme
                                            .labelSmall,
                                      ),
                                    ],
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(height: 16),
                    ],

                    // Health info
                    if (_testResult != null &&
                        _testResult!.success &&
                        _testResult!.healthInfo != null) ...[
                      Card(
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'Información del servidor',
                                style: Theme.of(context).textTheme.labelSmall,
                              ),
                              const SizedBox(height: 8),
                              Text(
                                  'Servicio: ${_testResult!.healthInfo!['service'] ?? 'N/A'}'),
                              Text(
                                  'API: ${_testResult!.healthInfo!['api_version'] ?? 'N/A'}'),
                              if (_testResult!.healthInfo!['version'] != null)
                                Text(
                                    'Versión: ${_testResult!.healthInfo!['version']}'),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(height: 16),
                    ],

                    // Continuar button after successful test
                    if (_testResult != null && _testResult!.success) ...[
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton.icon(
                          onPressed: () {
                            Navigator.pop(context);
                          },
                          icon: const Icon(Icons.arrow_forward),
                          label: const Text('Continuar'),
                        ),
                      ),
                      const SizedBox(height: 16),
                    ],

                    // Buttons
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton.icon(
                            onPressed: _isTesting ? null : _testConnection,
                            icon: _isTesting
                                ? const SizedBox(
                                    width: 16,
                                    height: 16,
                                    child: CircularProgressIndicator(
                                        strokeWidth: 2),
                                  )
                                : const Icon(Icons.wifi_find),
                            label: Text(
                                _isTesting ? 'Probando...' : 'Probar conexión'),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: ElevatedButton.icon(
                            onPressed: _isSaving ? null : _saveConfig,
                            icon: _isSaving
                                ? const SizedBox(
                                    width: 16,
                                    height: 16,
                                    child: CircularProgressIndicator(
                                        strokeWidth: 2),
                                  )
                                : const Icon(Icons.save),
                            label: Text(_isSaving ? 'Guardando...' : 'Guardar'),
                          ),
                        ),
                      ],
                    ),

                    // Last config info
                    if (_currentConfig != null) ...[
                      const SizedBox(height: 24),
                      Card(
                        child: Padding(
                          padding: const EdgeInsets.all(16),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'Configuración actual',
                                style: Theme.of(context).textTheme.labelSmall,
                              ),
                              const SizedBox(height: 8),
                              Text('Host: ${_currentConfig!.host}'),
                              Text('Puerto: ${_currentConfig!.port}'),
                              Text('Esquema: ${_currentConfig!.scheme}'),
                              Text('URL: ${_currentConfig!.baseUrl}'),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
    );
  }
}

class _NetworkTypeChip extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool isSelected;
  final VoidCallback onTap;

  const _NetworkTypeChip({
    required this.label,
    required this.icon,
    required this.isSelected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return FilterChip(
      label: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 16),
          const SizedBox(width: 6),
          Text(label),
        ],
      ),
      selected: isSelected,
      onSelected: (_) => onTap(),
      selectedColor: Theme.of(context).colorScheme.primaryContainer,
      checkmarkColor: Theme.of(context).colorScheme.primary,
    );
  }
}
