"""Smoke test manual del StickerStudio."""
import sys
import traceback


def run_smoke_test():
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
        return 0

    except Exception as e:
        print("\n" + "=" * 60)
        print("✗✗✗ ERROR al crear el StickerStudio ✗✗✗")
        print("=" * 60)
        print(f"\nError: {e}")
        print(f"Tipo: {type(e).__name__}")
        print("\nTraceback completo:")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(run_smoke_test())
