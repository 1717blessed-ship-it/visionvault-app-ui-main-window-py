"""Crea una base A/B/C irrepetible y abre Studio con esa base aislada."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.create_batch_demo import create_demo


def create_unique_demo(root: Path | None = None) -> Path:
    root = (root or (Path(tempfile.gettempdir()) / "DoccioneStudio-Pruebas")).resolve()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    database_path = root / f"tandas-abc-{stamp}-{uuid.uuid4().hex[:8]}.db"
    return create_demo(database_path)


def main() -> int:
    database_path = create_unique_demo()
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    executable = pythonw if os.name == "nt" and pythonw.exists() else python
    subprocess.Popen(
        [str(executable), str(REPOSITORY_ROOT / "main.py"), "--database", str(database_path)],
        cwd=str(database_path.parent),
    )
    print(f"Base ficticia creada y abierta: {database_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
