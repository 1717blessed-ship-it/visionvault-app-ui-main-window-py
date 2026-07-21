print("Inicio del script")
import sys
print("Importado sys")
sys.stdout.flush()

try:
    print("Intentando importar tkinter...")
    sys.stdout.flush()
    import tkinter as tk
    print("tkinter importado OK")
    sys.stdout.flush()
    
    print("Intentando importar StickerStudio...")
    sys.stdout.flush()
    from app.stickers.editor import StickerStudio
    print("StickerStudio importado OK")
    sys.stdout.flush()
    
    print("ÉXITO")
    
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
