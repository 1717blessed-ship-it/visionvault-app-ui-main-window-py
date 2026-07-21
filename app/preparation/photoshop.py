"""Integración local de Photoshop sin modificar los archivos originales."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


def _work_root() -> Path:
    return Path(__file__).parents[2] / "work" / "photoshop"


def create_work_copy(original_path: str, order_id: int) -> Path:
    """Crea una copia privada de trabajo para un pedido concreto."""
    source = Path(original_path)
    if not source.exists():
        raise FileNotFoundError("No se encontró el diseño original.")
    destination_dir = _work_root() / f"pedido_{order_id}"
    destination_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = destination_dir / f"{source.stem}__edicion_{stamp}{source.suffix.lower()}"
    shutil.copy2(source, destination)
    return destination


def find_photoshop_executable(configured_path: str = "") -> str:
    """Usa la ruta guardada y luego las ubicaciones habituales de Windows."""
    options = [configured_path]
    for root in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")):
        if root:
            options.append(str(Path(root) / "Adobe" / "Adobe Photoshop" / "Photoshop.exe"))
    for option in options:
        if option and Path(option).is_file():
            return str(Path(option))
    return ""


def open_work_copy(work_path: str, configured_path: str = "") -> tuple[bool, str]:
    """Abre la copia; Photoshop es preferido, Windows actúa como respaldo."""
    work = Path(work_path)
    if not work.exists():
        return False, "No se encontró la copia de trabajo."
    executable = find_photoshop_executable(configured_path)
    try:
        if executable:
            subprocess.Popen([executable, str(work)], close_fds=True)
            return True, "Photoshop abrió la copia de trabajo."
        os.startfile(str(work))
        return True, "Se abrió la copia de trabajo con la aplicación predeterminada."
    except OSError as error:
        return False, f"No se pudo abrir la copia de trabajo: {error}"
