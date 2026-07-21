import sys, os
sys.path.insert(0, os.path.abspath('.'))
from app.ui.main_window import VisionVaultApp
print('VisionVaultApp in module:', VisionVaultApp.__module__)
print('Has build_orders_module on class:', hasattr(VisionVaultApp, 'build_orders_module'))
print('build_orders_module on class object:', getattr(VisionVaultApp, 'build_orders_module', None))
