import 'package:http/http.dart' as http;

/// Evita pantallas bloqueadas cuando una conexión Wi-Fi queda abierta sin
/// responder. Los clientes pueden inyectar uno simulado en las pruebas.
class TimeoutHttpClient extends http.BaseClient {
  final http.Client _delegate;
  final Duration timeout;

  TimeoutHttpClient(this._delegate,
      {this.timeout = const Duration(seconds: 20)});

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) =>
      _delegate.send(request).timeout(timeout);

  @override
  void close() => _delegate.close();
}
