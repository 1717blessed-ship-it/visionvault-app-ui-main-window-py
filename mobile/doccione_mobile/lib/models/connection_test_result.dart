class ConnectionTestResult {
  final bool success;
  final String message;
  final int? statusCode;
  final Duration? responseTime;

  const ConnectionTestResult({
    required this.success,
    required this.message,
    this.statusCode,
    this.responseTime,
  });

  factory ConnectionTestResult.ok({required Duration responseTime}) {
    return ConnectionTestResult(
      success: true,
      message: 'Conexión exitosa',
      statusCode: 200,
      responseTime: responseTime,
    );
  }

  factory ConnectionTestResult.unauthorized({required int statusCode}) {
    return ConnectionTestResult(
      success: false,
      message: 'Token inválido',
      statusCode: statusCode,
    );
  }

  factory ConnectionTestResult.serverError({required int statusCode}) {
    return ConnectionTestResult(
      success: false,
      message: 'Error del servidor ($statusCode)',
      statusCode: statusCode,
    );
  }

  factory ConnectionTestResult.timeout() {
    return const ConnectionTestResult(
      success: false,
      message: 'Tiempo de espera agotado',
    );
  }

  factory ConnectionTestResult.networkError({String? detail}) {
    return ConnectionTestResult(
      success: false,
      message: detail ?? 'Servidor no encontrado',
    );
  }

  factory ConnectionTestResult.unexpected({String? detail}) {
    return ConnectionTestResult(
      success: false,
      message: detail ?? 'Respuesta inesperada del servidor',
    );
  }
}