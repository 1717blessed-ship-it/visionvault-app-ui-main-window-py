"""Simple automation runner: runs tests and verification scripts.

Usage:
    python tools/automation.py    # run tests + verifier
    python tools/automation.py --run-ui   # additionally launch main.py (detached)
"""
import subprocess
import sys
import shlex

def run(cmd):
    print("==>", cmd)
    rc = subprocess.call(cmd, shell=True)
    if rc != 0:
        print(f"Command failed: {cmd} (exit {rc})")
        sys.exit(rc)

if __name__ == "__main__":
    run("python -m pytest -q")
    run("python tools/verify_selection.py")
    if "--run-ui" in sys.argv:
        print("Launching UI (main.py) in background...")
        if sys.platform.startswith("win"):
            subprocess.Popen([sys.executable, "main.py"], creationflags=0)
        else:
            subprocess.Popen([sys.executable, "main.py"]) 
    print("Automation complete.")
