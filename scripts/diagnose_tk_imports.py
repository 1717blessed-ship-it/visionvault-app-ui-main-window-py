"""Locate a test-module import that prevents a fresh Tk interpreter starting."""
import importlib.util
import sys
import subprocess
from pathlib import Path
import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
paths = [Path(sys.argv[1])] if len(sys.argv) > 1 else sorted((ROOT / 'tests').glob('test_*.py'))
for path in paths:
    if len(sys.argv) == 1:
        result = subprocess.run([sys.executable, __file__, str(path)], capture_output=True, text=True)
        if result.returncode:
            print(path.name, result.stderr, flush=True)
            sys.exit(result.returncode)
        continue
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    try:
        root = tk.Tk()
        root.withdraw()
        root.destroy()
    except tk.TclError:
        print('Tk failed after importing:', path.name, flush=True)
        raise
print('All imports preserve Tk initialization')
