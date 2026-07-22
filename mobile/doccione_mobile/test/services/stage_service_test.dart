import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:doccione_mobile/services/stage_service.dart';
import 'package:doccione_mobile/models/order.dart';
import 'package:doccione_mobile/models/order_with_details.dart';
import 'package:doccione_mobile/models/job.dart';

OrderWithDetails _makeOrder({
  String? status,
  String? printPriority,
  String? material,
  String? orderDate,
  List<Job>? jobs,
}) {
  return OrderWithDetails(
    order: Order(
      id: '1',
      status: status,
      printPriority: printPriority,
      material: material,
      orderDate: orderDate,
    ),
    jobs: jobs ?? [],
  );
}

void main() {
  group('StageService.normalizeStatus', () {
    test('returns GENERAL_WORKFLOW stage as-is', () {
      for (final stage in StageService.generalWorkflow) {
        expect(StageService.normalizeStatus(stage), stage);
      }
    });

    test('maps legacy "Nuevo" to "Recibido"', () {
      expect(StageService.normalizeStatus('Nuevo'), 'Recibido');
    });

    test('maps legacy "En revisión" to "Esperando archivos"', () {
      expect(StageService.normalizeStatus('En revisión'), 'Esperando archivos');
    });

    test('maps legacy "En producción" to "En armado de planchas"', () {
      expect(StageService.normalizeStatus('En producción'), 'En armado de planchas');
    });

    test('maps legacy "Impreso" to "Impresión"', () {
      expect(StageService.normalizeStatus('Impreso'), 'Impresión');
    });

    test('maps legacy "Aprobado" to "Diseños confirmados"', () {
      expect(StageService.normalizeStatus('Aprobado'), 'Diseños confirmados');
    });

    test('maps legacy "Pendiente" to "Recibido"', () {
      expect(StageService.normalizeStatus('Pendiente'), 'Recibido');
    });

    test('maps legacy "Bloqueado" to "Recibido"', () {
      expect(StageService.normalizeStatus('Bloqueado'), 'Recibido');
    });

    test('maps vinyl "Armado de plancha" to general', () {
      expect(StageService.normalizeStatus('Armado de plancha'), 'En armado de planchas');
    });

    test('maps vinyl "Laminado" to general', () {
      expect(StageService.normalizeStatus('Laminado'), 'Sublimado / Laminado');
    });

    test('maps vinyl "Corte plotter" to general', () {
      expect(StageService.normalizeStatus('Corte plotter'), 'Corte');
    });

    test('maps textile "Sublimado" to general', () {
      expect(StageService.normalizeStatus('Sublimado'), 'Sublimado / Laminado');
    });

    test('maps finishing "Preparación" to general', () {
      expect(StageService.normalizeStatus('Preparación'), 'Listo para armado de planchas');
    });

    test('maps finishing "Producción" to general', () {
      expect(StageService.normalizeStatus('Producción'), 'Impresión');
    });

    test('maps finishing "Terminación" to general', () {
      expect(StageService.normalizeStatus('Terminación'), 'Corte');
    });

    test('maps "Empaquetado" to "Finalizado"', () {
      expect(StageService.normalizeStatus('Empaquetado'), 'Finalizado');
    });

    test('returns "Recibido" for null', () {
      expect(StageService.normalizeStatus(null), 'Recibido');
    });

    test('returns "Recibido" for empty string', () {
      expect(StageService.normalizeStatus(''), 'Recibido');
    });

    test('returns "Recibido" for unknown status', () {
      expect(StageService.normalizeStatus('SomeWeirdStatus'), 'Recibido');
    });
  });

  group('StageService.nextStage', () {
    test('returns next stage in workflow', () {
      expect(StageService.nextStage('Recibido'), 'Esperando archivos');
      expect(StageService.nextStage('Impresión'), 'Sublimado / Laminado');
      expect(StageService.nextStage('Control de calidad'), 'Finalizado');
    });

    test('returns null at "Entregado"', () {
      expect(StageService.nextStage('Entregado'), isNull);
    });

    test('returns null for unknown stage', () {
      expect(StageService.nextStage('Nonexistent'), isNull);
    });
  });

  group('StageService.isBlocking', () {
    test('identifies blocking states', () {
      expect(StageService.isBlocking('Esperando aprobacion'), true);
      expect(StageService.isBlocking('Esperando pago'), true);
      expect(StageService.isBlocking('Pendiente'), true);
      expect(StageService.isBlocking('Bloqueado'), true);
    });

    test('rejects non-blocking states', () {
      expect(StageService.isBlocking('Impresión'), false);
      expect(StageService.isBlocking('Recibido'), false);
      expect(StageService.isBlocking('Entregado'), false);
      expect(StageService.isBlocking(null), false);
      expect(StageService.isBlocking(''), false);
    });
  });

  group('StageService.priorityInt', () {
    test('parses string priorities', () {
      expect(StageService.priorityInt('high'), 3);
      expect(StageService.priorityInt('alta'), 3);
      expect(StageService.priorityInt('medium'), 2);
      expect(StageService.priorityInt('media'), 2);
      expect(StageService.priorityInt('low'), 1);
      expect(StageService.priorityInt('baja'), 1);
      expect(StageService.priorityInt('urgente'), 4);
    });

    test('parses numeric string priorities', () {
      expect(StageService.priorityInt('0'), 0);
      expect(StageService.priorityInt('1'), 1);
      expect(StageService.priorityInt('2'), 2);
      expect(StageService.priorityInt('3'), 3);
      expect(StageService.priorityInt('4'), 4);
    });

    test('returns 0 for null', () {
      expect(StageService.priorityInt(null), 0);
    });

    test('returns 0 for unknown strings', () {
      expect(StageService.priorityInt('something'), 0);
      expect(StageService.priorityInt('99'), 0);
    });
  });

  group('StageService.isUrgent', () {
    test('returns true for priority >= 3', () {
      expect(StageService.isUrgent(_makeOrder(printPriority: 'high')), true);
      expect(StageService.isUrgent(_makeOrder(printPriority: 'alta')), true);
      expect(StageService.isUrgent(_makeOrder(printPriority: 'urgente')), true);
      expect(StageService.isUrgent(_makeOrder(printPriority: '4')), true);
      expect(StageService.isUrgent(_makeOrder(printPriority: '3')), true);
    });

    test('returns false for priority < 3', () {
      expect(StageService.isUrgent(_makeOrder(printPriority: 'medium')), false);
      expect(StageService.isUrgent(_makeOrder(printPriority: 'low')), false);
      expect(StageService.isUrgent(_makeOrder(printPriority: '0')), false);
      expect(StageService.isUrgent(_makeOrder(printPriority: null)), false);
    });
  });

  group('StageService.materialIcon', () {
    test('maps vinyl materials', () {
      expect(StageService.materialIcon('Vinilo'), Icons.view_day);
      expect(StageService.materialIcon('Vinilo Full Color'), Icons.view_day);
      expect(StageService.materialIcon('Stickers'), Icons.view_day);
    });

    test('maps lona/banner', () {
      expect(StageService.materialIcon('Lona'), Icons.flag);
      expect(StageService.materialIcon('Banner'), Icons.flag);
    });

    test('maps textil', () {
      expect(StageService.materialIcon('Textil'), Icons.checkroom);
      expect(StageService.materialIcon('Remera'), Icons.checkroom);
    });

    test('maps resina', () {
      expect(StageService.materialIcon('Resina 3D'), Icons.diamond);
    });

    test('returns default for null/empty', () {
      expect(StageService.materialIcon(null), Icons.inventory_2);
      expect(StageService.materialIcon(''), Icons.inventory_2);
      expect(StageService.materialIcon('Otros'), Icons.inventory_2);
    });
  });

  group('StageService.ageDays', () {
    test('computes days from orderDate', () {
      final now = DateTime.now();
      final thirtyDaysAgo = now.subtract(const Duration(days: 30));
      final od = _makeOrder(
        orderDate: thirtyDaysAgo.toIso8601String().substring(0, 10),
      );
      expect(StageService.ageDays(od), 30);
    });

    test('returns null for missing date', () {
      expect(StageService.ageDays(_makeOrder(orderDate: null)), isNull);
      expect(StageService.ageDays(_makeOrder(orderDate: '')), isNull);
    });

    test('returns null for invalid date', () {
      expect(StageService.ageDays(_makeOrder(orderDate: 'not-a-date')), isNull);
    });
  });

  group('StageService.oldestAgeDays', () {
    test('returns max age across orders', () {
      final now = DateTime.now();
      final orders = [
        _makeOrder(orderDate: now.subtract(const Duration(days: 5)).toIso8601String().substring(0, 10)),
        _makeOrder(orderDate: now.subtract(const Duration(days: 30)).toIso8601String().substring(0, 10)),
        _makeOrder(orderDate: now.subtract(const Duration(days: 10)).toIso8601String().substring(0, 10)),
      ];
      expect(StageService.oldestAgeDays(orders), 30);
    });

    test('returns 0 for empty list', () {
      expect(StageService.oldestAgeDays([]), 0);
    });

    test('skips orders with no date', () {
      final now = DateTime.now();
      final orders = [
        _makeOrder(orderDate: null),
        _makeOrder(orderDate: now.subtract(const Duration(days: 7)).toIso8601String().substring(0, 10)),
      ];
      expect(StageService.oldestAgeDays(orders), 7);
    });
  });

  group('StageService.computeMetrics', () {
    test('groups orders by normalized status', () {
      final orders = [
        _makeOrder(status: 'Impresión', printPriority: 'high', jobs: [Job(id: '1'), Job(id: '2')]),
        _makeOrder(status: 'Impresión', printPriority: 'low', jobs: [Job(id: '3')]),
        _makeOrder(status: 'Recibido', jobs: []),
        _makeOrder(status: 'Entregado', jobs: [Job(id: '4')]),
      ];
      final metrics = StageService.computeMetrics(orders);

      expect(metrics.containsKey('Impresión'), true);
      expect(metrics['Impresión']!.orderCount, 2);
      expect(metrics['Impresión']!.jobCount, 3);
      expect(metrics['Impresión']!.urgentCount, 1);

      expect(metrics.containsKey('Recibido'), true);
      expect(metrics['Recibido']!.orderCount, 1);
      expect(metrics['Recibido']!.jobCount, 0);

      expect(metrics.containsKey('Entregado'), true);
      expect(metrics['Entregado']!.orderCount, 1);
    });

    test('groups blocking states under "Bloqueados"', () {
      final orders = [
        _makeOrder(status: 'Bloqueado'),
        _makeOrder(status: 'Esperando pago'),
        _makeOrder(status: 'Impresión'),
      ];
      final metrics = StageService.computeMetrics(orders);

      expect(metrics['Bloqueados']!.orderCount, 2);
      expect(metrics['Impresión']!.orderCount, 1);
    });

    test('normalizes workflow-specific statuses', () {
      final orders = [
        _makeOrder(status: 'Corte plotter'), // vinyl → "Corte"
        _makeOrder(status: 'Laminado'),       // vinyl → "Sublimado / Laminado"
        _makeOrder(status: 'Empaquetado'),    // → "Finalizado"
      ];
      final metrics = StageService.computeMetrics(orders);

      expect(metrics.containsKey('Corte'), true);
      expect(metrics['Corte']!.orderCount, 1);

      expect(metrics.containsKey('Sublimado / Laminado'), true);
      expect(metrics['Sublimado / Laminado']!.orderCount, 1);

      expect(metrics.containsKey('Finalizado'), true);
      expect(metrics['Finalizado']!.orderCount, 1);
    });

    test('returns empty map for empty input', () {
      expect(StageService.computeMetrics([]), isEmpty);
    });

    test('computes oldest age per stage', () {
      final now = DateTime.now();
      final orders = [
        _makeOrder(
          status: 'Impresión',
          orderDate: now.subtract(const Duration(days: 15)).toIso8601String().substring(0, 10),
        ),
        _makeOrder(
          status: 'Impresión',
          orderDate: now.subtract(const Duration(days: 3)).toIso8601String().substring(0, 10),
        ),
      ];
      final metrics = StageService.computeMetrics(orders);
      expect(metrics['Impresión']!.oldestAgeDays, 15);
    });
  });
}
