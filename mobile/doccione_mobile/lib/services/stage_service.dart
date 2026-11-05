import 'package:flutter/material.dart';
import 'package:doccione_mobile/models/order_with_details.dart';
import 'package:doccione_mobile/models/mobile_runtime_config.dart';

/// Aggregated metrics for a single production stage.
class StageMetrics {
  final int orderCount;
  final int jobCount;
  final int urgentCount;
  final int oldestAgeDays;

  const StageMetrics({
    required this.orderCount,
    required this.jobCount,
    required this.urgentCount,
    required this.oldestAgeDays,
  });

  static const empty = StageMetrics(
    orderCount: 0,
    jobCount: 0,
    urgentCount: 0,
    oldestAgeDays: 0,
  );
}

/// Production stage service — normalization, workflow logic, metrics.
///
/// Pure static methods, no Flutter dependencies beyond [IconData]/[Color].
/// Replicates the backend's `get_current_stage()` logic from
/// `app/workflow/timeline.py` for the GENERAL_WORKFLOW.
class StageService {
  StageService._();

  // ── GENERAL_WORKFLOW (source of truth: backend timeline.py) ─────────

  static const _defaultGeneralWorkflow = [
    'Recibido',
    'Esperando archivos',
    'Diseños confirmados',
    'Listo para armado de planchas',
    'En armado de planchas',
    'Listo para imprimir',
    'Impresión',
    'Sublimado / Laminado',
    'Corte',
    'Control de calidad',
    'Finalizado',
    'Entregado',
  ];

  // ── Blocking states (backend BLOCKING_STATES) ──────────────────────

  static const blockingStates = [
    'Esperando aprobacion',
    'Esperando pago',
    'Pendiente',
    'Bloqueado',
  ];

  // ── Legacy → current stage mapping ─────────────────────────────────

  static const _legacyMap = {
    'pending': 'Recibido',
    'production': 'En armado de planchas',
    'completed': 'Finalizado',
    'delivered': 'Entregado',
    'Nuevo': 'Recibido',
    'En revisión': 'Esperando archivos',
    'En diseño': 'Esperando archivos',
    'Esperando aprobación': 'Esperando archivos',
    'Esperando pago': 'Recibido',
    'Pendiente': 'Recibido',
    'Bloqueado': 'Recibido',
    'Listo para Armado de Planchas': 'Listo para armado de planchas',
    'En Armado de Planchas': 'En armado de planchas',
    'Listo para plancha': 'Listo para armado de planchas',
    'En producción': 'En armado de planchas',
    'Impreso': 'Impresión',
    'Aprobado': 'Diseños confirmados',
    'Presupuesto enviado': 'Recibido',
    'Rechazado': 'Recibido',
  };

  // ── Workflow-specific → GENERAL_WORKFLOW reverse mapping ────────────
  // Backend maps general→specific per workflow; we reverse it so that
  // orders with vinyl/textile/finishing-specific statuses land in the
  // correct GENERAL_WORKFLOW stage on the production board.

  static const _workflowToGeneral = {
    // Vinyl-specific
    'Armado de plancha': 'En armado de planchas',
    'Laminado': 'Sublimado / Laminado',
    'Corte plotter': 'Corte',
    // Textile-specific
    'Sublimado': 'Sublimado / Laminado',
    // Finishing-specific
    'Preparación': 'Listo para armado de planchas',
    'Producción': 'Impresión',
    'Terminación': 'Corte',
    // Shared closing stage (vinyl/textile/finishing)
    'Empaquetado': 'Finalizado',
  };

  // ── Stage metadata (colors from backend STAGE_METADATA) ────────────

  static const _defaultStageColors = <String, int>{
    'Recibido': 0xFF9E9E9E,
    'Esperando archivos': 0xFFFF9800,
    'Diseños confirmados': 0xFF2196F3,
    'Listo para armado de planchas': 0xFF00BCD4,
    'En armado de planchas': 0xFF00BCD4,
    'Listo para imprimir': 0xFF00BCD4,
    'Impresión': 0xFF4CAF50,
    'Sublimado / Laminado': 0xFF00BCD4,
    'Corte': 0xFF795548,
    'Control de calidad': 0xFF9C27B0,
    'Finalizado': 0xFF4CAF50,
    'Entregado': 0xFF8BC34A,
  };

  static List<String> generalWorkflow =
      List.unmodifiable(_defaultGeneralWorkflow);
  static Map<String, int> stageColors = Map.unmodifiable(_defaultStageColors);
  static List<String> orderStatuses =
      List.unmodifiable(MobileRuntimeConfig.defaults.orderStatuses);
  static List<RuntimePriority> priorities =
      List.unmodifiable(MobileRuntimeConfig.defaults.priorities);

  /// Actualiza referencias visuales sin perder los valores conocidos por la
  /// compilación cuando el servidor no publica una opción válida.
  static void applyRuntimeConfig(MobileRuntimeConfig config) {
    generalWorkflow = List.unmodifiable(
      config.workflowStages.isEmpty
          ? _defaultGeneralWorkflow
          : config.workflowStages,
    );
    stageColors = Map.unmodifiable({
      ..._defaultStageColors,
      ...config.stageColors,
    });
    orderStatuses = List.unmodifiable(config.orderStatuses);
    priorities = List.unmodifiable(config.priorities);
  }

  static void resetRuntimeConfig() {
    applyRuntimeConfig(MobileRuntimeConfig.defaults);
  }

  // ── Public: normalization ───────────────────────────────────────────

  /// Normalizes a raw DB [status] to a GENERAL_WORKFLOW stage name.
  ///
  /// Handles legacy statuses, vinyl/textile/finishing-specific stages,
  /// and unknown values.  Returns "Recibido" as ultimate fallback.
  static String normalizeStatus(String? status) {
    var s = (status ?? '').trim();
    if (s.isEmpty) return 'Recibido';

    // Already a general workflow stage?
    if (generalWorkflow.contains(s)) return s;

    // Legacy mapping
    s = _legacyMap[s] ?? s;
    if (generalWorkflow.contains(s)) return s;

    // Workflow-specific → general
    s = _workflowToGeneral[s] ?? s;
    if (generalWorkflow.contains(s)) return s;

    return 'Recibido';
  }

  /// Next stage in GENERAL_WORKFLOW, or null if already at "Entregado".
  static String? nextStage(String currentStage) {
    final idx = generalWorkflow.indexOf(currentStage);
    if (idx < 0 || idx >= generalWorkflow.length - 1) return null;
    return generalWorkflow[idx + 1];
  }

  // ── Public: blocking / priority ─────────────────────────────────────

  /// Whether [status] is a blocking state (not a production stage).
  static bool isBlocking(String? status) {
    if (status == null) return false;
    return blockingStates.contains(status.trim());
  }

  /// Parses [printPriority] to an integer 0–4.
  ///
  /// Handles both string ("high"/"alta"/"3") and numeric formats.
  static int priorityInt(String? printPriority) {
    if (printPriority == null) return 0;
    final raw = printPriority.trim().toLowerCase();
    switch (raw) {
      case 'high':
      case 'alta':
        return 3;
      case 'medium':
      case 'media':
        return 2;
      case 'low':
      case 'baja':
        return 1;
      case 'urgente':
        return 4;
      default:
        final parsed = int.tryParse(raw);
        if (parsed != null && parsed >= 0 && parsed <= 4) return parsed;
        return 0;
    }
  }

  /// Whether the order is urgent (priority ≥ 3 = Alta or Urgente).
  static bool isUrgent(OrderWithDetails od) =>
      priorityInt(od.order.printPriority) >= 3;

  /// Priority color matching backend theme.py accent colors.
  static Color priorityColor(String? printPriority) {
    switch (priorityInt(printPriority)) {
      case 4:
        return const Color(0xFFD60916); // Urgente — red
      case 3:
        return const Color(0xFFFF6B35); // Alta — orange
      case 2:
        return const Color(0xFFF5A623); // Media — amber
      case 1:
        return const Color(0xFF39D353); // Baja — green
      default:
        return const Color(0xFF00BCD4); // Sin prisa — teal
    }
  }

  // ── Public: thumbnails ──────────────────────────────────────────────

  /// Material icon for the production tile thumbnail.
  static IconData materialIcon(String? material) {
    if (material == null || material.isEmpty) return Icons.inventory_2;
    final m = material.toLowerCase();
    if (m.contains('vinilo') ||
        m.contains('sticker') ||
        m.contains('plotter')) {
      return Icons.view_day;
    }
    if (m.contains('lona') || m.contains('banner')) return Icons.flag;
    if (m.contains('textil') || m.contains('remera') || m.contains('sublim')) {
      return Icons.checkroom;
    }
    if (m.contains('resina') || m.contains('doming') || m.contains('cuadro')) {
      return Icons.diamond;
    }
    if (m.contains('acrílico') || m.contains('acrilico')) {
      return Icons.rectangle;
    }
    if (m.contains('pvc') || m.contains('foam')) {
      return Icons.square;
    }
    if (m.contains('canvas') || m.contains('lienzo')) {
      return Icons.palette;
    }
    return Icons.inventory_2;
  }

  // ── Public: age calculation ─────────────────────────────────────────

  /// Age in days of the oldest order in [orders] (by orderDate).
  /// Returns 0 if no parseable dates are found.
  static int oldestAgeDays(List<OrderWithDetails> orders) {
    final now = DateTime.now();
    int maxDays = 0;
    for (final od in orders) {
      final dateStr = od.order.orderDate;
      if (dateStr == null || dateStr.isEmpty) continue;
      final date = DateTime.tryParse(dateStr);
      if (date == null) continue;
      final days = now.difference(date).inDays;
      if (days > maxDays) maxDays = days;
    }
    return maxDays;
  }

  /// Age in days for a single order.  Returns null if no parseable date.
  static int? ageDays(OrderWithDetails od) {
    final dateStr = od.order.orderDate;
    if (dateStr == null || dateStr.isEmpty) return null;
    final date = DateTime.tryParse(dateStr);
    if (date == null) return null;
    return DateTime.now().difference(date).inDays;
  }

  // ── Public: aggregated metrics ──────────────────────────────────────

  /// Computes metrics for every stage from a flat list of orders.
  ///
  /// Returns a map keyed by stage name (GENERAL_WORKFLOW stages + "Bloqueados").
  static Map<String, StageMetrics> computeMetrics(
    List<OrderWithDetails> orders,
  ) {
    final grouped = <String, List<OrderWithDetails>>{};

    for (final od in orders) {
      final status = od.order.status;
      final stage = isBlocking(status) ? 'Bloqueados' : normalizeStatus(status);
      grouped.putIfAbsent(stage, () => []).add(od);
    }

    return grouped.map((stage, list) {
      int totalJobs = 0;
      int urgentCount = 0;
      for (final od in list) {
        totalJobs += od.jobs.length;
        if (isUrgent(od)) urgentCount++;
      }
      return MapEntry(
        stage,
        StageMetrics(
          orderCount: list.length,
          jobCount: totalJobs,
          urgentCount: urgentCount,
          oldestAgeDays: oldestAgeDays(list),
        ),
      );
    });
  }
}
