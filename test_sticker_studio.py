"""Script de diagnóstico para el creador de stickers."""
import sys
import traceback

def test_imports():
    """Verifica que todas las importaciones necesarias funcionen."""
    print("=" * 60)
    print("DIAGNÓSTICO DEL CREADOR DE STICKERS")
    print("=" * 60)
    print()
    
    errors = []
    
    # Test 1: Importaciones básicas
    print("1. Verificando importaciones básicas...")
    try:
        import tkinter as tk
        from tkinter import ttk
        print("   ✓ tkinter OK")
    except Exception as e:
        errors.append(("tkinter", e))
        print(f"   ✗ tkinter ERROR: {e}")
    
    # Test 2: PIL/Pillow
    print("\n2. Verificando PIL/Pillow...")
    try:
        from PIL import Image, ImageTk
        print("   ✓ PIL OK")
    except Exception as e:
        errors.append(("PIL", e))
        print(f"   ✗ PIL ERROR: {e}")
    
    # Test 3: NumPy
    print("\n3. Verificando NumPy...")
    try:
        import numpy as np
        print("   ✓ NumPy OK")
    except Exception as e:
        errors.append(("NumPy", e))
        print(f"   ✗ NumPy ERROR: {e}")
    
    # Test 4: OpenCV
    print("\n4. Verificando OpenCV...")
    try:
        import cv2
        print("   ✓ OpenCV OK")
    except Exception as e:
        errors.append(("OpenCV", e))
        print(f"   ✗ OpenCV ERROR: {e}")
    
    # Test 5: Módulos de la app
    print("\n5. Verificando módulos de la aplicación...")
    try:
        from app.ui.theme import COLORS, IDENTITY_FONT, UI_FONT
        print("   ✓ theme OK")
    except Exception as e:
        errors.append(("theme", e))
        print(f"   ✗ theme ERROR: {e}")
    
    try:
        from app.stickers.pipeline import ProcessingProfile, ProcessingResult, StickerProcessor
        print("   ✓ pipeline OK")
    except Exception as e:
        errors.append(("pipeline", e))
        print(f"   ✗ pipeline ERROR: {e}")
    
    try:
        from app.stickers.profile_editor import ProcessingProfileEditor
        print("   ✓ profile_editor OK")
    except Exception as e:
        errors.append(("profile_editor", e))
        print(f"   ✗ profile_editor ERROR: {e}")
    
    try:
        from app.indexer.scanner import IMAGE_EXTENSIONS
        print("   ✓ scanner OK")
    except Exception as e:
        errors.append(("scanner", e))
        print(f"   ✗ scanner ERROR: {e}")
    
    # Test 6: Importar el StickerStudio
    print("\n6. Verificando StickerStudio...")
    try:
        from app.stickers.editor import StickerStudio
        print("   ✓ StickerStudio importado correctamente")
    except Exception as e:
        errors.append(("StickerStudio", e))
        print(f"   ✗ StickerStudio ERROR: {e}")
        print("\nTraceback completo:")
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    if errors:
        print(f"RESULTADO: {len(errors)} error(es) encontrado(s)")
        print("\nERRORES DETALLADOS:")
        for module, error in errors:
            print(f"\n  Módulo: {module}")
            print(f"  Error: {error}")
        return False
    else:
        print("RESULTADO: Todas las importaciones funcionan correctamente")
        print("\nIntentando crear una instancia de prueba...")
        try:
            import tkinter as tk
            from app.stickers.editor import StickerStudio
            from app.database.database import ImageDatabase
            
            root = tk.Tk()
            root.withdraw()
            db = ImageDatabase("visionvault.db")
            studio = StickerStudio(root, db)
            print("   ✓ StickerStudio se creó correctamente")
            print("   ✓ La ventana se puede abrir sin errores")
            studio.destroy()
            root.destroy()
            return True
        except Exception as e:
            print(f"   ✗ Error al instanciar: {e}")
            traceback.print_exc()
            return False
    
    print("=" * 60)

if __name__ == "__main__":
    success = test_imports()
    sys.exit(0 if success else 1)
