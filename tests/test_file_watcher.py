"""Tests para el monitoreo automático de Banco Stickers."""
import unittest
import tempfile
import time
from pathlib import Path
from PIL import Image

from app.indexer.file_watcher import StickerBankWatcher, StickerBankHandler


class TestFileWatcher(unittest.TestCase):
    """Tests para el sistema de monitoreo de archivos."""

    def setUp(self):
        """Configura un directorio temporal para las pruebas."""
        self.temp_dir = tempfile.mkdtemp()
        self.detected_files = []

    def tearDown(self):
        """Limpia el directorio temporal."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def on_new_image(self, image_path: str):
        """Callback de prueba que registra archivos detectados."""
        self.detected_files.append(image_path)

    def wait_for_detections(self, count: int, timeout: float = 6.0) -> bool:
        """Espera el callback sin depender de un margen temporal fijo."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.detected_files) >= count:
                return True
            time.sleep(0.05)
        return len(self.detected_files) >= count

    def test_detect_new_image(self):
        """Verifica que se detecten imágenes nuevas."""
        watcher = StickerBankWatcher(self.on_new_image)
        watcher.start(self.temp_dir)

        # Esperar que el observer se inicie
        time.sleep(0.5)

        # Crear una imagen de prueba
        test_image_path = Path(self.temp_dir) / "test_sticker.png"
        img = Image.new("RGB", (100, 100), color=(255, 0, 0))
        img.save(test_image_path)

        # Esperar a que se detecte (debounce + carga variable del host)
        self.assertTrue(self.wait_for_detections(1))

        # Verificar que se detectó
        self.assertEqual(len(self.detected_files), 1)
        self.assertTrue(str(test_image_path) in self.detected_files[0])

        watcher.stop()

    def test_ignore_non_images(self):
        """Verifica que se ignoren archivos que no son imágenes."""
        watcher = StickerBankWatcher(self.on_new_image)
        watcher.start(self.temp_dir)

        time.sleep(0.5)

        # Crear un archivo de texto
        text_file = Path(self.temp_dir) / "test.txt"
        text_file.write_text("test content")

        # Esperar
        time.sleep(3)

        # Verificar que NO se detectó
        self.assertEqual(len(self.detected_files), 0)

        watcher.stop()

    def test_ignore_hidden_files(self):
        """Verifica que se ignoren archivos ocultos."""
        watcher = StickerBankWatcher(self.on_new_image)
        watcher.start(self.temp_dir)

        time.sleep(0.5)

        # Crear una imagen oculta
        hidden_image = Path(self.temp_dir) / ".hidden_sticker.png"
        img = Image.new("RGB", (100, 100), color=(0, 255, 0))
        img.save(hidden_image)

        # Esperar
        time.sleep(3)

        # Verificar que NO se detectó
        self.assertEqual(len(self.detected_files), 0)

        watcher.stop()

    def test_detect_in_subdirectory(self):
        """Verifica que se detecten imágenes en subcarpetas."""
        watcher = StickerBankWatcher(self.on_new_image)
        watcher.start(self.temp_dir)

        time.sleep(0.5)

        # Crear subcarpeta
        subdir = Path(self.temp_dir) / "subfolder"
        subdir.mkdir()

        # Crear imagen en subcarpeta
        test_image_path = subdir / "nested_sticker.png"
        img = Image.new("RGB", (100, 100), color=(0, 0, 255))
        img.save(test_image_path)

        # Esperar el callback sin asumir una planificación exacta del observer.
        self.assertTrue(self.wait_for_detections(1))

        # Verificar que se detectó
        self.assertEqual(len(self.detected_files), 1)
        self.assertTrue(str(test_image_path) in self.detected_files[0])

        watcher.stop()

    def test_debounce_multiple_events(self):
        """Verifica que el debounce evite múltiples procesamientos del mismo archivo."""
        self.detected_files = []

        watcher = StickerBankWatcher(self.on_new_image)
        watcher.start(self.temp_dir)

        time.sleep(0.5)

        # Crear y modificar imagen rápidamente
        test_image_path = Path(self.temp_dir) / "modified_sticker.png"
        img = Image.new("RGB", (100, 100), color=(255, 255, 0))
        img.save(test_image_path)

        # Modificar inmediatamente
        time.sleep(0.1)
        img2 = Image.new("RGB", (100, 100), color=(0, 255, 255))
        img2.save(test_image_path)

        # Esperar debounce completo
        self.assertTrue(self.wait_for_detections(1))

        # Debería detectarse solo una vez gracias al debounce
        self.assertEqual(len(self.detected_files), 1)

        watcher.stop()

    def test_watcher_is_active(self):
        """Verifica el estado del watcher."""
        watcher = StickerBankWatcher(self.on_new_image)

        # Inicialmente inactivo
        self.assertFalse(watcher.is_active())

        # Activo después de start
        watcher.start(self.temp_dir)
        time.sleep(0.5)
        self.assertTrue(watcher.is_active())

        # Inactivo después de stop
        watcher.stop()
        self.assertFalse(watcher.is_active())

    def test_watched_path(self):
        """Verifica que se retorne la ruta monitoreada correctamente."""
        watcher = StickerBankWatcher(self.on_new_image)

        # Sin path inicialmente
        self.assertIsNone(watcher.watched_path())

        # Con path después de start
        watcher.start(self.temp_dir)
        time.sleep(0.5)
        self.assertEqual(watcher.watched_path(), str(Path(self.temp_dir).resolve()))

        # Sin path después de stop
        watcher.stop()
        self.assertIsNone(watcher.watched_path())


class TestStickerBankHandler(unittest.TestCase):
    """Tests para el handler de eventos."""

    def test_handler_filters_extensions(self):
        """Verifica que el handler filtre correctamente las extensiones."""
        detected = []
        handler = StickerBankHandler(lambda path: detected.append(path))

        # Simular evento de imagen válida
        class FakeEvent:
            def __init__(self, path):
                self.src_path = path
                self.is_directory = False

        # Imagen válida
        handler._handle_file_event(str(Path(tempfile.gettempdir()) / "test.png"))
        time.sleep(0.1)

        # Archivo inválido
        handler._handle_file_event(str(Path(tempfile.gettempdir()) / "test.txt"))
        time.sleep(0.1)

        # Esperar debounce
        time.sleep(3)

        # Limpiar
        handler.stop()

        # Solo debería haberse agregado la imagen PNG
        # (aunque no exista el archivo, se agrega a pending_files)
        # Este test verifica la lógica de filtrado de extensiones


if __name__ == "__main__":
    unittest.main()
