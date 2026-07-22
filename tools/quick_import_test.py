import sys, time
from pathlib import Path
sys.path.insert(0, '.')
print('importing...', flush=True)
t0 = time.perf_counter()
from app.ui.main_window import VisionVaultApp
print('imported in', round((time.perf_counter()-t0)*1000,2), 'ms', flush=True)
