"""Preflight y escritura atómica; nunca modifica reservas o estados."""
import logging
import os
import math
from pathlib import Path
import tempfile
import shutil
from functools import wraps

logger = logging.getLogger(__name__)


class ExportValidationError(ValueError):
    pass


def output_action(function):
    @wraps(function)
    def run(self, *args, **kwargs):
        try:
            return function(self, *args, **kwargs)
        except (ValueError, OSError) as error:
            logger.exception('Operación bloqueada: %s', function.__name__)
            if kwargs.get('silent'):
                raise
            from tkinter import messagebox
            messagebox.showerror('Operación bloqueada', str(error), parent=self)
            return False
    return run


def validate_sources(items):
    from PIL import Image
    issues = []
    if not items:
        issues.append('El proyecto no contiene diseños; no se puede generar una hoja vacía.')
    for item in items:
        try:
            if any(not math.isfinite(float(value)) or float(value) <= 0 for value in (item.width_cm, item.height_cm)):
                raise ValueError('dimensiones físicas inválidas')
            with Image.open(item.path) as image:
                image.load()
                if image.convert('RGBA').getchannel('A').getbbox() is None:
                    raise ValueError('imagen completamente transparente')
        except Exception as error:
            issues.append(f'{item.name} · referencia {item.item_id} · {item.path} · '
                          f'{item.width_cm:g}×{item.height_cm:g} cm · solicitada 1, colocada 0, no colocada 1: '
                          f'{type(error).__name__}: {error}. Revisá el archivo y su ubicación.')
    if issues:
        message = 'Exportación bloqueada:\n' + '\n'.join(issues)
        logger.error('%s', message)
        raise ExportValidationError(message)


def validate_geometry(project):
    """Un histórico inválido se informa, no se reacomoda silenciosamente."""
    for item in project.items:
        if (not all(math.isfinite(float(v)) for v in (item.x_cm,item.y_cm))
                or item.x_cm < project.margin_cm-.001 or item.y_cm < project.margin_cm-.001
                or item.x_cm+item.reserved_width_cm > 21-project.margin_cm+.001
                or item.y_cm+item.reserved_height_cm > project.workspace_bottom_cm+.001):
            raise ExportValidationError(f'{item.name} · {item.item_id} · {item.path}: geometría fuera del área imprimible; revisá el proyecto sin recalibrar.')


def atomic_write(path, writer):
    """El archivo anterior sólo se sustituye tras terminar la escritura."""
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    os.close(descriptor)
    try:
        writer(Path(temporary))
        with open(temporary, 'r+b') as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        logger.exception('No se pudo escribir %s; se conserva el archivo anterior.', path)
        raise
    finally:
        Path(temporary).unlink(missing_ok=True)


def save_image(image, path, format, **options):
    atomic_write(path, lambda temporary: image.save(temporary, format, **options))


def save_text(path, text):
    atomic_write(path, lambda temporary: temporary.write_text(text, encoding='utf-8'))


def save_page_outputs(projects, base_path, render):
    """Prepara todo el lote antes de publicar archivos o registrar producción."""
    base_path = Path(base_path)
    files = []
    published = []
    with tempfile.TemporaryDirectory(prefix='.plancha-stage-', dir=base_path.parent) as staging:
        staging = Path(staging)
        for index, project in enumerate(projects, 1):
            sheet = render(project)
            for extension in ('json', 'png'):
                target = base_path.parent / f'{base_path.stem}_plancha_{index}.{extension}'
                staged = staging / target.name
                if extension == 'json':
                    project.save(staged)
                else:
                    save_image(sheet, staged, 'PNG', dpi=(300,300), compress_level=3)
                files.append((staged,target))
        manifest = staging/'manifest.json'
        from app.planchas.model import PlanchaProject
        PlanchaProject.save_pages(manifest, projects)
        files.append((manifest,base_path))
        backups = {}
        for index, (_, target) in enumerate(files):
            if target.exists():
                backup = staging/f'backup-{index}'
                shutil.copyfile(target,backup)
                backups[target] = backup
        try:
            for staged,target in files:
                os.replace(staged,target)
                published.append(target)
        except Exception:
            for target in reversed(published):
                if target in backups:
                    os.replace(backups[target],target)
                else:
                    target.unlink(missing_ok=True)
            logger.exception('Fallo publicando el conjunto %s; se restauraron sus archivos.',base_path)
            raise
