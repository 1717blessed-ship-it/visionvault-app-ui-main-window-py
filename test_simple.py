"""Test simple del StickerStudio."""
import sys
import traceback

try:
    import tkinter as tk
    from app.stickers.editor import StickerStudio
    from app.database.database import ImageDatabase
    
    print("Creando ventana root...")
    root = tk.Tk()
    root.withdraw()
    
    print("Conectando base de datos...")
    db = ImageDatabase("visionvault.db")
    
    print("Creando StickerStudio...")
    studio = StickerStudio(root, db)
    
    print("\n" + "=" * 60)
    print("✓✓✓ ÉXITO: El creador de stickers se creó correctamente ✓✓✓")
    print("=" * 60)
    
    studio.destroy()
    root.destroy()
    sys.exit(0)
    
except Exception as e:
    print("\n" + "=" * 60)
    print("✗✗✗ ERROR al crear el StickerStudio ✗✗✗")
    print("=" * 60)
    print(f"\nError: {e}")
    print(f"Tipo: {type(e).__name__}")
    print("\nTraceback completo:")
    traceback.print_exc()
    sys.exit(1)
