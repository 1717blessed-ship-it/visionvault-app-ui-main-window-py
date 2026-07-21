import sys
import os
import traceback

# Ensure project root is on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.ui.main_window import VisionVaultApp

try:
    app = VisionVaultApp()
    app.update()
    app.mainloop()
except Exception:
    traceback.print_exc()
    raise
