"""Entorno de pruebas: Tcl/Tk local para el Python administrado de Windows."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time


def pytest_configure(config):
    if sys.platform != "win32":
        return
    # _tkinter usa fopen de Tcl, no el cargador de módulos de Python. Algunos
    # entornos administrados permiten importar tkinter pero no leer sus scripts
    # en AppData de forma estable. Se reutilizan los scripts de esa instalación
    # en un cache local; no se descargan runtimes ni se omiten pruebas gráficas.
    installed = Path(sys.base_prefix) / "tcl"
    if not (installed / "tcl8.6" / "init.tcl").is_file():
        return  # La ausencia real de Tcl debe quedar visible como fallo.
    # El checkout puede estar sincronizado o vigilado y producir lecturas
    # transitorias incompletas durante una suite larga. Tcl necesita estos
    # scripts como runtime, no como artefactos del repositorio; el temporal del
    # sistema es el lugar estable y escribible apropiado.
    local = (Path(tempfile.gettempdir()) /
             f"doccione-pytest-tcl-{sys.version_info.major}{sys.version_info.minor}")
    for name in ("tcl8", "tcl8.6", "tk8.6"):
        source = installed / name
        destination = local / name
        if source.is_dir():
            # Un pytest interrumpido puede dejar la carpeta creada pero
            # incompleta (por ejemplo, tk8.6/ttk sin button.tcl).  Mezclar la
            # instalación vuelve idempotente la preparación y repara ese
            # estado sin borrar caches ni ocultar fallos reales de Tk.
            shutil.copytree(source, destination, dirs_exist_ok=True)
    # No se reemplaza una instalación elegida explícitamente por el usuario.
    os.environ.setdefault("TCL_LIBRARY", str(local / "tcl8.6"))
    os.environ.setdefault("TK_LIBRARY", str(local / "tk8.6"))
    # Verificar el runtime antes de ejecutar cualquier test. En este Python
    # administrado la primera apertura puede fallar de forma transitoria aun
    # con los scripts presentes. El reintento afecta solo a esta comprobación
    # de arranque, nunca a una prueba ni a sus aserciones.
    import tkinter
    for attempt in range(3):
        try:
            config._sticker_test_tcl = tkinter.Tcl()
            break
        except tkinter.TclError:
            if attempt == 2:
                raise
            time.sleep(.1)
