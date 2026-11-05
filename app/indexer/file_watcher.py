"""Monitor automático de carpeta Banco Stickers para procesar imágenes nuevas."""
from __future__ import annotations
import threading
import time
from pathlib import Path
from typing import Callable
import logging

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent
    _WATCHDOG_AVAILABLE = True
except ImportError:  # La app debe poder abrirse aunque falte la dependencia opcional.
    Observer = None
    _WATCHDOG_AVAILABLE = False

    class FileSystemEventHandler:
        """Compatibilidad mínima para conservar el handler importable."""

        pass

    FileCreatedEvent = FileModifiedEvent = object

from app.indexer.scanner import IMAGE_EXTENSIONS

logger = logging.getLogger(__name__)


class StickerBankHandler(FileSystemEventHandler):
    """Manejador de eventos para carpeta Banco Stickers."""

    def __init__(self, on_new_image: Callable[[str], None], debounce_seconds: float = 2.0):
        """
        Args:
            on_new_image: Callback que se llama con la ruta de la imagen nueva
            debounce_seconds: Tiempo de espera antes de procesar para evitar eventos duplicados
        """
        super().__init__()
        self.on_new_image = on_new_image
        self.debounce_seconds = debounce_seconds
        self._pending_files = {}  # path -> timestamp
        self._lock = threading.Lock()
        self._debounce_thread = None
        self._stop_debounce = False

    def on_created(self, event):
        """Se llama cuando se crea un archivo."""
        if event.is_directory:
            return
        self._handle_file_event(event.src_path)

    def on_modified(self, event):
        """Se llama cuando se modifica un archivo."""
        if event.is_directory:
            return
        self._handle_file_event(event.src_path)

    def _handle_file_event(self, file_path: str):
        """Maneja un evento de archivo con debounce."""
        path = Path(file_path)

        # Verificar que sea una imagen
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            return

        # Ignorar archivos temporales y ocultos
        if path.name.startswith('.') or path.name.startswith('~'):
            return

        # Ignorar archivos dentro de carpetas .trash (archivos borrados)
        if any(part.startswith('.trash') for part in path.parts):
            return

        # Agregar a pendientes con timestamp
        with self._lock:
            # Mantener la ruta reportada por watchdog. `resolve()` puede
            # cambiar la representación (por ejemplo, en carpetas temporales
            # o unidades enlazadas) y rompe consumidores que comparan la ruta
            # recibida con la que acaba de crear el usuario.
            self._pending_files[str(path)] = time.time()

            # Iniciar thread de debounce si no está corriendo
            if self._debounce_thread is None or not self._debounce_thread.is_alive():
                self._stop_debounce = False
                self._debounce_thread = threading.Thread(
                    target=self._process_pending_files,
                    daemon=True,
                    name="sticker-bank-debounce"
                )
                self._debounce_thread.start()

    def _process_pending_files(self):
        """Procesa archivos pendientes después del tiempo de debounce."""
        while not self._stop_debounce:
            time.sleep(0.5)

            with self._lock:
                if not self._pending_files:
                    break

                current_time = time.time()
                ready_files = []

                # Buscar archivos que ya pasaron el tiempo de debounce
                for file_path, timestamp in list(self._pending_files.items()):
                    if current_time - timestamp >= self.debounce_seconds:
                        ready_files.append(file_path)
                        del self._pending_files[file_path]

                # Procesar archivos listos fuera del lock
                if not ready_files:
                    continue

            # Procesar cada archivo listo
            for file_path in ready_files:
                try:
                    # Verificar que el archivo existe y es accesible
                    path = Path(file_path)
                    if path.exists() and path.is_file():
                        logger.info(f"Imagen nueva detectada en Banco Stickers: {path.name}")
                        self.on_new_image(file_path)
                except Exception as e:
                    logger.error(f"Error procesando imagen nueva {file_path}: {e}")

    def stop(self):
        """Detiene el procesamiento de archivos pendientes."""
        self._stop_debounce = True
        if self._debounce_thread:
            self._debounce_thread.join(timeout=5.0)


class StickerBankWatcher:
    """Monitor de carpeta Banco Stickers para procesar imágenes automáticamente."""

    def __init__(self, on_new_image: Callable[[str], None]):
        """
        Args:
            on_new_image: Callback que se llama con la ruta de cada imagen nueva
        """
        self.on_new_image = on_new_image
        self._observer = None
        self._handler = None
        self._watched_path = None

    def start(self, folder_path: str):
        """Inicia el monitoreo de una carpeta.

        Args:
            folder_path: Ruta de la carpeta Banco Stickers a monitorear
        """
        if not _WATCHDOG_AVAILABLE:
            logger.warning("Monitoreo de Banco Stickers desactivado: falta watchdog")
            return

        if self._observer is not None:
            self.stop()

        # Conservar la forma de la ruta que eligió el usuario. En Windows,
        # `resolve()` puede expandir nombres 8.3 y hacer que los callbacks no
        # coincidan con la ruta original.
        path = Path(folder_path)
        if not path.exists() or not path.is_dir():
            logger.warning(f"No se puede monitorear carpeta inexistente: {folder_path}")
            return

        self._watched_path = str(path.resolve())
        self._handler = StickerBankHandler(self.on_new_image)
        self._observer = Observer()
        self._observer.schedule(self._handler, str(path), recursive=True)
        self._observer.start()

        logger.info(f"Iniciado monitoreo de Banco Stickers: {path}")

    def stop(self):
        """Detiene el monitoreo."""
        if self._handler:
            self._handler.stop()
            self._handler = None

        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None

        if self._watched_path:
            logger.info(f"Detenido monitoreo de Banco Stickers: {self._watched_path}")
            self._watched_path = None

    def is_active(self) -> bool:
        """Retorna True si el monitor está activo."""
        return self._observer is not None and self._observer.is_alive()

    def watched_path(self) -> str | None:
        """Retorna la ruta actualmente monitoreada o None."""
        return self._watched_path
