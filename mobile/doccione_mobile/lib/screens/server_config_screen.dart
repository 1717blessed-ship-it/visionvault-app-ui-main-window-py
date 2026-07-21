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
      setState(() {
        _currentConfig = config;
        _hostController.text = config.host;
        _portController.text = config.port.toString();
        _scheme = config.scheme;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _error = 'Error al cargar configuración: $e';
        _isLoading = false;
      });
    }
  }

  Future<void> _saveConfig() async {
    if (!_formKey.currentState!.validate()) return;

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

      setState(() {
        _currentConfig = config;
        _isSaving = false;
        _saveSuccess = 'Configuración guardada correctamente';
      });
    } catch (e) {
      setState(() {
        _isSaving = false;
        _error = 'Error al guardar: $e';
      });
    }
  }

  Future<void> _testConnection() async {
    if (widget.onTestConnection == null) return;

    setState(() {
      _isTesting = true;
      _testResult = null;
      _error = null;
      _saveSuccess = null;
    });

    try {
      final baseUrl = _baseUrlPreview;
      final result = await widget.onTestConnection!(baseUrl);
      setState(() {
        _isTesting = false;
        _testResult = result;
      });
    } catch (e) {
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
                                style: Theme.of(context).textTheme.titleMedium?.copyWith(
                                      fontFamily: 'monospace',
                                    ),
                              ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(height: 16),
                    ],

                    // Host
                    TextFormField(
                      controller: _hostController,
                      decoration: const InputDecoration(
                        labelText: 'Host o Dirección IP',
                        hintText: 'localhost',
                        border: OutlineInputBorder(),
                        helperText: 'Ej: localhost, 192.168.1.50, studio.local',
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
                      value: _scheme,
                      decoration: const InputDecoration(
                        labelText: 'Esquema',
                        border: OutlineInputBorder(),
                      ),
                      items: const [
                        DropdownMenuItem(value: 'http', child: Text('HTTP')),
                        DropdownMenuItem(value: 'https', child: Text('HTTPS')),
                      ],
                      onChanged: (value) {
                        if (value != null) {
                          setState(() => _scheme = value);
                        }
                      },
                    ),
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
                                    color: Theme.of(context).colorScheme.primary,
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
                                            ? Theme.of(context).colorScheme.primary
                                            : Theme.of(context).colorScheme.error,
                                      ),
                                    ),
                                    if (_testResult!.responseTime != null) ...[
                                      const SizedBox(height: 4),
                                      Text(
                                        'Latencia: ${_testResult!.responseTime!.inMilliseconds}ms',
                                        style: Theme.of(context).textTheme.labelSmall,
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
                                    child: CircularProgressIndicator(strokeWidth: 2),
                                  )
                                : const Icon(Icons.wifi_find),
                            label: Text(_isTesting ? 'Probando...' : 'Probar conexión'),
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
                                    child: CircularProgressIndicator(strokeWidth: 2),
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
