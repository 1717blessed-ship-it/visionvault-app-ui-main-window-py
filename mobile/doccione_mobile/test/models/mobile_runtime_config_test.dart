import 'package:doccione_mobile/models/mobile_runtime_config.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  tearDown(MobileRuntimeConfigStore.reset);

  test('uses safe defaults when an old server has no runtime config', () {
    final config = MobileRuntimeConfig.fromCapabilities({
      'api_version': '1.0',
      'supports_pull': true,
    });

    expect(config.featureEnabled('design_catalog'), isTrue);
    expect(config.workflowStages, contains('Entregado'));
    expect(config.materials, contains('Otro'));
    expect(config.requiresUpgrade('1.0.2'), isFalse);
  });

  test('parses feature flags, references and compatibility', () {
    final config = MobileRuntimeConfig.fromCapabilities({
      'runtime_config': {
        'features': {
          'design_catalog': false,
          'product_catalog': true,
        },
        'announcement': {
          'enabled': true,
          'title': 'Novedad',
          'message': 'Nuevo catálogo',
        },
        'maintenance': {
          'enabled': true,
          'message': 'Volvemos pronto',
        },
        'compatibility': {
          'minimum_app_version': '1.1.0',
          'recommended_app_version': '1.2.0',
          'update_url': 'https://example.test/update',
        },
        'references': {
          'workflows': {
            'general': {
              'stages': ['Inicio', 'Final'],
            },
          },
          'stages': [
            {'key': 'Inicio', 'color': '#112233'},
          ],
          'materials': ['Lona'],
          'payment_methods': ['Transferencia'],
          'sticker_modes': ['Plancha A4'],
          'order_statuses': ['Pendiente', 'Entregado'],
          'priorities': [
            {'value': 0, 'label': 'Normal'},
            {'value': 4, 'label': 'Urgente'},
          ],
        },
      },
    });

    expect(config.featureEnabled('design_catalog'), isFalse);
    expect(config.featureEnabled('product_catalog'), isTrue);
    expect(config.announcementEnabled, isTrue);
    expect(config.maintenanceMessage, 'Volvemos pronto');
    expect(config.workflowStages, ['Inicio', 'Final']);
    expect(config.stageColors['Inicio'], 0xFF112233);
    expect(config.materials, ['Lona', 'Otro']);
    expect(config.paymentMethods, ['Transferencia', 'Otro']);
    expect(config.requiresUpgrade('1.0.2'), isTrue);
    expect(config.recommendsUpgrade('1.1.5'), isTrue);
  });

  test('runtime store applies and resets configuration', () {
    final config = MobileRuntimeConfig.fromCapabilities({
      'runtime_config': {
        'features': {'sticker_orders': false},
      },
    });

    MobileRuntimeConfigStore.apply(config);
    expect(
      MobileRuntimeConfigStore.current.featureEnabled('sticker_orders'),
      isFalse,
    );

    MobileRuntimeConfigStore.reset();
    expect(
      MobileRuntimeConfigStore.current.featureEnabled('sticker_orders'),
      isTrue,
    );
  });
}
