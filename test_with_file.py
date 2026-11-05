"""Smoke test manual que escribe a archivo."""
import sys
from pathlib import Path

log_file = Path("test_output.log")


def run_smoke_test() -> int:
    try:
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write("TEST DEL CREADOR DE STICKERS\n")
            f.write("=" * 60 + "\n\n")

            f.write("1. Importando tkinter...\n")
            f.flush()
            import tkinter as tk
            f.write("   ✓ tkinter OK\n\n")

            f.write("2. Importando database...\n")
            f.flush()
            from app.database.database import ImageDatabase
            f.write("   ✓ database OK\n\n")

            f.write("3. Importando StickerStudio...\n")
            f.flush()
            from app.stickers.editor import StickerStudio
            f.write("   ✓ StickerStudio OK\n\n")

            f.write("4. Creando instancia...\n")
            f.flush()
            root = tk.Tk()
            root.withdraw()
            db = ImageDatabase("visionvault.db")
            studio = StickerStudio(root, db)
            f.write("   ✓ Instancia creada OK\n\n")

            f.write("=" * 60 + "\n")
            f.write("✓✓✓ ÉXITO TOTAL ✓✓✓\n")
            f.write("El creador de stickers funciona correctamente\n")
            f.write("=" * 60 + "\n")

            studio.destroy()
            root.destroy()

        print(f"Test completado. Ver resultados en: {log_file.absolute()}")
        return 0

    except Exception as e:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n✗✗✗ ERROR ✗✗✗\n")
            f.write(f"Error: {e}\n")
            f.write(f"Tipo: {type(e).__name__}\n\n")

            import traceback
            f.write("Traceback:\n")
            traceback.print_exc(file=f)

        print(f"Test falló. Ver detalles en: {log_file.absolute()}")
        return 1


if __name__ == "__main__":
    sys.exit(run_smoke_test())
