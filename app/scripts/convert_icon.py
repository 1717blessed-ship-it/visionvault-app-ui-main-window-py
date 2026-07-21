from pathlib import Path
import sys

try:
    from PIL import Image
except Exception as e:
    print('Pillow no está disponible:', e)
    sys.exit(2)

src = Path(__file__).parents[1] / 'assets' / 'doccione_studio.png'
dst = src.with_suffix('.ico')

if not src.exists():
    print('Fuente no encontrada:', src)
    sys.exit(1)

try:
    with Image.open(src) as im:
        sizes = [(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)]
        im.save(dst, format='ICO', sizes=sizes)
    print('Icono generado en:', dst)
    sys.exit(0)
except Exception as e:
    print('Error al generar ICO:', e)
    sys.exit(3)
